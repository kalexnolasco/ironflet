"""Guards for the black-screen fix: a reconnecting client must be served.

What is being pinned here is the defect described in `flet_reconnect.py`: Flet
0.28.3's socket server latches onto the first client and ignores every later
one, which on Android — where the Flutter client is re-created whenever the user
comes back from another app — leaves a page nobody paints.

These tests drive the **real** `FletSocketServer` over a real Unix socket, in
the same embedded/UDS mode the APK runs in, and play the part of the Dart client
by hand: connect, send `registerWebClient`, wait for the framed reply. That is
as close to the phone as this machine can get — there is no Android device here,
so nothing below proves the black screen is gone on Alex's phone. It proves the
server no longer goes deaf, which is the part that *is* testable.

`test_flet_0283_ignores_a_reconnecting_client` is the canary: it asserts the bug
still exists in the unpatched library. The day it fails, Flet has fixed this
upstream and `flet_reconnect.py` should be deleted rather than carried.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import struct

import pytest

import flet_reconnect

pytestmark = pytest.mark.asyncio

# How long to wait for a reply that should be immediate. Long enough not to
# flake on a loaded machine, short enough that the "no reply" tests are quick.
REPLY_TIMEOUT_S = 3.0
NO_REPLY_TIMEOUT_S = 1.5

REGISTER = {
    "action": "registerWebClient",
    "payload": {
        "pageName": "",
        "pageRoute": "/",
        "pageWidth": "400",
        "pageHeight": "800",
        "windowWidth": "",
        "windowHeight": "",
        "windowTop": "",
        "windowLeft": "",
        "isPWA": "false",
        "isWeb": "false",
        "isDebug": "false",
        "platform": "android",
        "platformBrightness": "light",
        "media": "",
        "sessionId": "",
    },
}


# ── harness ──────────────────────────────────────────────────────────────


@pytest.fixture
def pristine_flet():
    """A `FletSocketServer` class with the patch definitely NOT applied.

    The patch is process-wide and `main.py` applies it at import time, so by the
    time this file runs pytest may already have imported `main` for another
    test — the unpatched state cannot be assumed, and the original function is
    no longer reachable to save and restore. Reloading the module is what gets
    it back. Every test here builds its server from the class this yields, so a
    reload can never leave a test talking to the wrong class object.
    """
    import flet.flet_socket_server as module

    importlib.reload(module)
    try:
        yield module.FletSocketServer
    finally:
        # Leave the library as found, patch and all — the next test decides.
        importlib.reload(module)


async def start_server(cls, tmp_path, sessions: list):
    """A real `FletSocketServer` on a real UDS, as an APK runs it."""
    server = cls(
        loop=asyncio.get_running_loop(),
        uds_path=str(tmp_path / "flet.sock"),
        on_session_created=lambda data: _remember(sessions, data),
    )
    await server.start()
    return server


async def _remember(sessions: list, data) -> None:
    sessions.append(data.sessionID)


async def read_frame(reader, timeout: float) -> str | None:
    """One length-prefixed message, or None if the server never answers."""
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout)
        (size,) = struct.unpack(">I", header)
        body = await asyncio.wait_for(reader.readexactly(size), timeout)
    except (TimeoutError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        return None
    return body.decode("utf-8")


async def register(server, timeout: float = REPLY_TIMEOUT_S):
    """Connect as the Dart client does and ask for a session."""
    reader, writer = await asyncio.open_unix_connection(server.page_url)
    data = json.dumps(REGISTER).encode("utf-8")
    writer.write(struct.pack(">I", len(data)) + data)
    await writer.drain()
    return writer, await read_frame(reader, timeout)


# ── the defect ───────────────────────────────────────────────────────────


async def test_flet_0283_ignores_a_reconnecting_client(pristine_flet, tmp_path):
    """The bug itself, unpatched. Delete this file when it starts failing.

    A failure means the installed Flet serves reconnecting clients on its own —
    i.e. the backport is obsolete and should go, not be "fixed".
    """
    import flet.version

    if flet.version.version not in flet_reconnect.SUPPORTED_VERSIONS:
        pytest.skip(f"flet {flet.version.version}: this defect is 0.28.3's")

    sessions: list = []
    server = await start_server(pristine_flet, tmp_path, sessions)
    try:
        first_writer, first = await register(server)
        assert first is not None, "the very first client is served even unpatched"
        first_writer.close()
        await asyncio.sleep(0.2)

        second_writer, second = await register(server, NO_REPLY_TIMEOUT_S)
        second_writer.close()
        assert second is None  # accepted at socket level, then ignored forever
    finally:
        await server.close()


# ── the fix ──────────────────────────────────────────────────────────────


async def test_a_reconnecting_client_gets_a_session(pristine_flet, tmp_path):
    """The whole point: coming back from Spotify must produce a page.

    Two sessions from two connections is what the Flutter side needs — its
    control store is empty after the isolate is re-created, so being handed a
    session is the difference between the app and a black rectangle.
    """
    assert flet_reconnect.apply(force=True)

    sessions: list = []
    server = await start_server(pristine_flet, tmp_path, sessions)
    try:
        first_writer, first = await register(server)
        assert first is not None
        first_writer.close()
        await asyncio.sleep(0.2)

        second_writer, second = await register(server)
        second_writer.close()
        assert second is not None, "the reconnecting client got no page: black screen"
        assert json.loads(second)["action"] == "registerWebClient"
        await asyncio.sleep(0.2)
        assert len(sessions) == 2, "a reconnect must start a new session, not reuse a dead one"
    finally:
        await server.close()


async def test_five_reconnections_in_a_row_are_all_served(pristine_flet, tmp_path):
    """Alex changes song more than once. Nothing may degrade with repetition."""
    assert flet_reconnect.apply(force=True)

    sessions: list = []
    server = await start_server(pristine_flet, tmp_path, sessions)
    try:
        for _ in range(5):
            writer, reply = await register(server)
            assert reply is not None
            writer.close()
            await asyncio.sleep(0.1)
        assert server._ironflet_connections == 5
    finally:
        await server.close()


async def test_the_previous_clients_pending_updates_are_not_replayed(pristine_flet, tmp_path):
    """The new client must not inherit the dead one's queued paint commands.

    `FletSocketServer.__send_loop` re-enqueues whatever it could not write, so
    the queue outlives the socket. Replaying it would push updates for controls
    the new client has never heard of.
    """
    assert flet_reconnect.apply(force=True)

    sessions: list = []
    server = await start_server(pristine_flet, tmp_path, sessions)
    try:
        first_writer, first = await register(server)
        assert first is not None
        first_writer.close()
        server._FletSocketServer__send_queue.put_nowait('{"action":"stale"}')

        second_writer, second = await register(server)
        assert second is not None
        assert "stale" not in second
        second_writer.close()
    finally:
        await server.close()


# ── the guards around the patch ──────────────────────────────────────────


async def test_apply_is_idempotent(pristine_flet):
    assert flet_reconnect.apply(force=True)
    patched = pristine_flet.handle_connection
    assert flet_reconnect.apply(force=True)
    assert pristine_flet.handle_connection is patched


async def test_an_unexpected_flet_version_is_left_alone(pristine_flet, monkeypatch):
    """A Flet upgrade must disable the patch, never break start-up.

    The mangled private names this patch writes to are not API. On any version
    it was not read against, doing nothing is the only safe answer — and if that
    version already carries flet-dev/flet#5909, doing nothing is also right.
    """
    import flet.version

    original = pristine_flet.handle_connection
    monkeypatch.setattr(flet.version, "version", "9.9.9")

    assert flet_reconnect.apply() is False
    assert pristine_flet.handle_connection is original


# ── the field evidence ───────────────────────────────────────────────────


async def test_record_appends_a_line(tmp_path, monkeypatch):
    log = tmp_path / "connections.log"
    monkeypatch.setenv("IRONFLET_CONNLOG", str(log))

    flet_reconnect.record("lifecycle", "RESUME")
    flet_reconnect.record("connection", "#2 reconnect")

    lines = log.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("lifecycle RESUME")
    assert "#2 reconnect" in lines[1]


async def test_the_log_never_grows_without_bound(tmp_path, monkeypatch):
    log = tmp_path / "connections.log"
    log.write_text("x" * (flet_reconnect.LOG_MAX_BYTES + 10) + "\n")
    monkeypatch.setenv("IRONFLET_CONNLOG", str(log))

    flet_reconnect.record("connection", "#1 first client")

    assert log.stat().st_size < flet_reconnect.LOG_MAX_BYTES
    assert log.read_text().endswith("connection #1 first client\n")


async def test_no_storage_directory_means_no_file(tmp_path, monkeypatch):
    """A source checkout must not sprout a log file next to main.py."""
    monkeypatch.delenv("IRONFLET_CONNLOG", raising=False)
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    monkeypatch.chdir(tmp_path)

    assert flet_reconnect.log_path() is None
    flet_reconnect.record("connection", "#1 first client")  # must not raise
    assert list(tmp_path.iterdir()) == []


async def test_recording_survives_an_unwritable_path(tmp_path, monkeypatch):
    """Evidence is nice to have; the app is not. A bad path may not raise."""
    monkeypatch.setenv("IRONFLET_CONNLOG", str(tmp_path / "nope" / "deeper" / "c.log"))
    flet_reconnect.record("connection", "#1 first client")
