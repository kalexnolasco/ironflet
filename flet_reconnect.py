"""Keep answering the Flutter client after Android re-creates it (black screen).

The bug, in Alex's words: *"cuando la utilizan y cambian de app para cambiar la
musica o leer .. al volver a la app....la pantalla se queda negra y no se puede
volver a la app"*. The workout in progress is on that screen, so this makes the
app unusable in a gym.

What actually happens
---------------------
An APK built by `flet build` is two halves talking over a Unix domain socket:
embedded CPython (this code) is the server, the Flutter/Dart client is the only
consumer. When Android destroys the Activity — which it does routinely once
another app takes the foreground — the Dart side calls `_appServices.close()`
and the socket drops. On the way back Flutter starts a **new** isolate with an
**empty** control store and reconnects to the same, still-running Python
process, retrying every 200 ms.

Flet 0.28.3 never answers that second client. `FletSocketServer`:

    async def handle_connection(self, reader, writer):
        if not self.__connected:          # set once in start(), never reset
            self.__connected = True
            self.__receive_loop_task = asyncio.create_task(...)
            self.__send_loop_task = asyncio.create_task(...)

`__connected` latches on the first client and is never lowered, so every later
connection is accepted at socket level and then ignored forever: nothing is read
from it, nothing is written to it, no session is registered, the writer is not
even closed. The client sends `registerWebClient` and waits for a page that
never comes.

What that looks like on screen, read out of the Dart side of flet 0.28.3 rather
than assumed: `AppState.initial()` does contain a bare `page` control with no
children, so `controls/page.dart` builds a `MaterialApp` whose `themeMode` is
still null — ThemeMode.system — and, because `routesView.views` is empty,
renders `Scaffold(body: PageMedia())` into it. An empty Material scaffold, in
the *system* theme. On a phone in dark mode that is a black, blank,
unresponsive rectangle, which is Alex's report word for word; note that it is
black despite IronFlet forcing the LIGHT palette (`apply_theme(page, LIGHT)`),
because the palette lives in a page the client never received. `pyproject.toml`
now turns Flet's startup screen on so that state at least shows a spinner and a
message instead of nothing.

Upstream fixed exactly this in flet-dev/flet#5909 ("Ensure only a single active
socket client is processed at a time and terminate any existing connection
before accepting a new one"), but only on the v1 line (`flet.messaging.*`).
There is no 0.28.x carrying the fix: after 0.28.3 the project jumped to 0.7x/0.8x
and this line is dead. So the fix is backported here, from the app's own code,
by replacing `handle_connection` before `ft.app()` starts the server.

Verified vs assumed — read this before trusting the file
-------------------------------------------------------
VERIFIED on this machine, by running the same embedded+UDS code path an APK
takes: without this patch the second client gets no reply at all; with it, it
gets a register response, a fresh session and a rebuilt page. `tests/
test_flet_reconnect.py` pins both halves.

NOT VERIFIED: that this is what Alex's phone does. There is no Android device
or emulator here, so nobody has watched the black screen appear or disappear.
The chain "Activity destroyed -> client reconnects -> server ignores it" is the
best-supported explanation (it matches the exact symptom — permanent black and
unresponsive, rather than the clean restart a killed process would give — and it
explains why the lifecycle handler in `main.py` never helped), but the first
link is inferred, not measured.

That is what `record()` is for. Every accepted connection and every lifecycle
transition is appended to a small text file under `FLET_APP_STORAGE_DATA` (and
echoed to stdout, which serious_python 0.9.12 pipes into logcat under the tag
`serious_python`). If a black screen is ever followed by a `connection #N
reconnect` line, the diagnosis is proven in the field, on Alex's own phone, with
no PC and no adb. If black screens happen with **no** second connection logged,
the diagnosis is wrong and the fault is below us in the Flutter engine — start
again from there, and do not delete this file until that question is answered.

Blast radius
------------
This monkey-patches a private class of a pinned dependency, so it is guarded
twice: it refuses to run on any Flet other than the versions listed below, and
every failure is swallowed and logged. A future `flet` upgrade therefore
silently disables the patch instead of breaking start-up — and if that upgrade
is to a version that already contains #5909, disabling it is also correct.

Nothing here imports Flet at module import time beyond the socket server itself,
and web mode never touches this code path (it serves over websockets, not UDS),
so the patch is inert there.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path

#: Flet releases this patch was read against, line by line. Anything else is
#: left alone: the private names below (`_FletSocketServer__send_queue` and
#: friends) are not API and a rename would turn a fixed bug into a dead app.
SUPPORTED_VERSIONS = ("0.28.3",)

#: Where the field evidence lands. `FLET_APP_STORAGE_DATA` is the app-private,
#: writable, update-surviving directory on Android — the same root
#: `storage.sqlite_path()` puts the database in, so everything worth pulling off
#: the phone sits together.
LOG_FILENAME = "connections.log"

#: A few hundred lines is plenty to see a week of use, and the file must never
#: become something that costs disk or start-up time.
LOG_MAX_BYTES = 32 * 1024
LOG_KEEP_LINES = 200

#: Set on the class once patched, so `apply()` is idempotent.
_MARKER = "_ironflet_reconnect_patched"


# ── field evidence ────────────────────────────────────────────


def log_path() -> Path | None:
    """Where the connection log goes, or `None` when there is nowhere for it.

    `IRONFLET_CONNLOG` names a file outright (tests, and anyone debugging).
    Otherwise it lands in `FLET_APP_STORAGE_DATA`, the app-private directory
    Flet sets on Android *and* on the desktop — the same root
    `storage.sqlite_path()` uses.

    No variable, no file: that is `python main.py` from a source checkout and a
    pytest process, neither of which should have a log dropped in the working
    directory. Those runs still get the stdout copy.
    """
    override = (os.environ.get("IRONFLET_CONNLOG") or "").strip()
    if override:
        return Path(override)
    base = (os.environ.get("FLET_APP_STORAGE_DATA") or "").strip()
    return Path(base) / LOG_FILENAME if base else None


def _rotate(path: Path) -> None:
    """Keep the tail of the file when it grows past `LOG_MAX_BYTES`.

    Rewrite-in-place rather than a `.1` sidecar: the point of this file is that
    Alex can find *one* file and send it, and a rotation scheme that leaves two
    halves lying around defeats that.

    Trimmed by lines *and* by bytes, and down to half the ceiling rather than to
    it: a line count alone cannot bound anything (one pathological entry would
    survive at any length), and trimming to exactly the ceiling would rotate on
    every single write from then on.
    """
    with contextlib.suppress(Exception):
        if not path.exists() or path.stat().st_size <= LOG_MAX_BYTES:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-LOG_KEEP_LINES:])[-(LOG_MAX_BYTES // 2) :]
        path.write_text(tail + "\n", encoding="utf-8")


def record(event: str, detail: str = "") -> None:
    """Append one line of evidence. Never raises, never blocks anything.

    Also printed: serious_python redirects Python's stdout/stderr into logcat,
    so `adb logcat -s serious_python` is a second, independent read-out for
    anyone who does have a cable.
    """
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {event} {detail}".rstrip()
    with contextlib.suppress(Exception):
        print(f"[ironflet] {line}", flush=True)
    path = log_path()
    if path is None:
        return
    with contextlib.suppress(Exception):
        _rotate(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# ── the backport ──────────────────────────────────────────────


def _tear_down_previous(server) -> None:
    """Undo everything the previous client left behind, best effort.

    Order matters only in that the send queue must be replaced *after* the send
    loop is cancelled: `FletSocketServer.__send_loop` re-enqueues a message it
    failed to write, so the old queue still holds updates addressed to a socket
    nobody is reading. Handing that queue to the new client would replay a dead
    session's paint commands into a page that does not have those controls.

    Every step is individually guarded: a half-dead previous connection must
    never be able to stop the new one from being served.
    """
    for attr in (
        "_FletSocketServer__receive_loop_task",
        "_FletSocketServer__send_loop_task",
    ):
        task = getattr(server, attr, None)
        if task is not None and not task.done():
            with contextlib.suppress(Exception):
                task.cancel()
        with contextlib.suppress(Exception):
            setattr(server, attr, None)

    # Close the dead socket ourselves. Flet 0.28.3 leaks the writer of every
    # connection it ignores; on a phone that flips foreground/background all day
    # those file descriptors add up.
    previous_writer = getattr(server, "_ironflet_writer", None)
    if previous_writer is not None:
        with contextlib.suppress(Exception):
            previous_writer.close()
    server._ironflet_writer = None

    # Drop the stale session. Two reasons, and the second is the one that bites:
    #   1. `on_session_created` re-runs `main(page)` on a NEW Page, so the old
    #      one is dead weight holding nine views and a Storage.
    #   2. the Dart client reuses the same session id (""), and leaving the old
    #      Page in `sessions` leaves stale background loops (RestTimer,
    #      the session chronometer) ticking against it. `page._close()` sets its
    #      connection to None, so their next `page.update()` raises
    #      PageDisconnectedException and the loop ends — noisy in the log,
    #      correct in effect.
    sessions = getattr(server, "sessions", None)
    if isinstance(sessions, dict):
        for session_id in list(sessions):
            page = sessions.pop(session_id, None)
            if page is None:
                continue
            with contextlib.suppress(Exception):
                page._close()

    with contextlib.suppress(Exception):
        server._FletSocketServer__send_queue = asyncio.Queue()


async def _handle_connection(self, reader, writer):
    """Replacement for `FletSocketServer.handle_connection`.

    The original serves the first client and ignores every later one. This one
    always serves the newest client, tearing the previous connection down first
    — the same decision upstream made in flet-dev/flet#5909.
    """
    count = getattr(self, "_ironflet_connections", 0) + 1
    self._ironflet_connections = count

    if count > 1:
        # THE line to look for in the log after a black screen: it means the
        # Flutter client really was re-created, and that this patch is what
        # stands between Alex and a dead app.
        record("connection", f"#{count} reconnect: replacing the previous client")
        try:
            _tear_down_previous(self)
        except Exception as exc:  # pragma: no cover - defensive
            record("connection", f"#{count} teardown failed: {exc!r}")
    else:
        record("connection", "#1 first client")

    self._ironflet_writer = writer
    self._FletSocketServer__connected = True
    self._FletSocketServer__receive_loop_task = asyncio.create_task(
        self._FletSocketServer__receive_loop(reader)
    )
    self._FletSocketServer__send_loop_task = asyncio.create_task(
        self._FletSocketServer__send_loop(writer)
    )


def apply(*, force: bool = False) -> bool:
    """Install the backport. Returns True when it is in place.

    Call it **before** `ft.app()`: `start()` does
    `asyncio.start_unix_server(self.handle_connection, ...)`, which binds the
    method object there and then. Patching the class after the server is up has
    no effect at all — the already-bound method still points at the old
    function. Module level in `main.py` is the right place.

    `force=True` is for tests only; it bypasses the version guard.
    """
    try:
        import flet.version
        from flet.flet_socket_server import FletSocketServer
    except Exception as exc:
        record("patch", f"skipped: flet internals not importable ({exc!r})")
        return False

    if getattr(FletSocketServer, _MARKER, False):
        return True

    version = getattr(flet.version, "version", "") or "unknown"
    if version not in SUPPORTED_VERSIONS and not force:
        # Deliberately not an error. A newer Flet either fixed this itself
        # (#5909 is in the v1 line) or moved the internals this patch pokes at;
        # either way, running blind on it is worse than not running.
        record("patch", f"skipped: flet {version} not in {SUPPORTED_VERSIONS}")
        return False

    try:
        FletSocketServer.handle_connection = _handle_connection
        setattr(FletSocketServer, _MARKER, True)
    except Exception as exc:  # pragma: no cover - defensive
        record("patch", f"failed: {exc!r}")
        return False

    record("patch", f"applied to flet {version}")
    return True
