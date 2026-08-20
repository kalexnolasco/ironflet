"""Guards for the rest-timer alert.

Audio cannot be heard from a test, so nothing here asserts that a beep came out
of a speaker. What it does assert is everything that decides *whether* one
should have: that the tone files exist and are the ones the script generates,
that the mute preference is obeyed, that restarting a countdown does not replay
the alert of the countdown it replaced, and — the one that matters most — that
a player which refuses to play (a browser blocking autoplay, an unmounted
control) leaves the countdown running to the end.

No database is needed: `Storage` is replaced by a two-method fake, because the
only thing the timer asks it is `get_pref`/`set_pref`.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import sys
import wave
from pathlib import Path

import pytest

from components import timer as timer_mod
from components.timer import (
    DONE_SOUND,
    PRE_ALERT_MIN_TOTAL_S,
    PRE_ALERT_S,
    SOUND_PREF,
    SOUNDS_DIR,
    WARN_SOUND,
    RestTimer,
    haptics_enabled,
    set_haptics_enabled,
    set_sound_enabled,
    sound_enabled,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = SOUNDS_DIR.parent


def _load_generator():
    """Import `scripts/make_timer_sounds.py` by path.

    By path rather than `import scripts.make_timer_sounds`: `scripts/` has no
    `__init__.py` and is a bag of one-off tools, not a package the app imports.
    """
    path = ROOT / "scripts" / "make_timer_sounds.py"
    spec = importlib.util.spec_from_file_location("make_timer_sounds", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before executing: `@dataclass` resolves its annotations
    # through `sys.modules[cls.__module__]`, and an unregistered module makes
    # that lookup return None.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── fakes ─────────────────────────────────────────────────────


class FakeStore:
    """Just the two preference methods, optionally broken."""

    def __init__(self, values: dict | None = None, raises: bool = False):
        self.values = dict(values or {})
        self.raises = raises
        self.writes: list[tuple[str, str]] = []

    def get_pref(self, key: str, default=None):
        if self.raises:
            raise RuntimeError("database is down")
        return self.values.get(key, default)

    def set_pref(self, key: str, value: str):
        if self.raises:
            raise RuntimeError("database is down")
        self.values[key] = value
        self.writes.append((key, value))


class FakePage:
    """Enough of `ft.Page` for the timer: update, overlay, data, run_task."""

    def __init__(self, store=None):
        self.overlay: list = []
        self.data = {"store": store} if store is not None else {}
        self.updates = 0
        self.tasks: list[asyncio.Task] = []

    def update(self):
        self.updates += 1

    def run_task(self, fn, *args):
        task = asyncio.get_running_loop().create_task(fn(*args))
        self.tasks.append(task)
        return task

    async def drain(self):
        """Let every countdown loop finish (or die stale)."""
        for task in list(self.tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _instrument(t: RestTimer) -> list[str]:
    """Replace the two Flet edges with recorders. Returns the call log."""
    fired: list[str] = []
    t._play = fired.append  # type: ignore[method-assign]
    t._vibrate = lambda src: None  # type: ignore[method-assign]
    return fired


@pytest.fixture(autouse=True)
def fast_ticks(monkeypatch):
    """One millisecond per second, so a three-minute rest runs in 0.2 s.

    This is why `TICK_S` is a module constant instead of a literal `1` inside
    `asyncio.sleep`.
    """
    monkeypatch.setattr(timer_mod, "TICK_S", 0.001)


# ── the sound files ───────────────────────────────────────────


@pytest.mark.parametrize("src", [WARN_SOUND, DONE_SOUND])
def test_sound_file_exists_under_assets(src):
    """The src is an assets-relative URL that resolves to a real file.

    A leading slash and no scheme is the contract: `main.py` serves `assets/`
    at the web root, and a `file://` src is refused outright by the browser
    ("Not allowed to load local resource") — the same trap that once made every
    exercise image invisible in web mode.
    """
    assert src.startswith("/")
    assert "://" not in src
    assert (ASSETS / src.lstrip("/")).is_file()


@pytest.mark.parametrize("src", [WARN_SOUND, DONE_SOUND])
def test_sound_file_is_a_small_valid_wav(src):
    path = ASSETS / src.lstrip("/")
    with wave.open(str(path)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22_050
        seconds = wav.getnframes() / wav.getframerate()
    # Long enough to register over gym noise, short enough not to be a jingle.
    assert 0.05 <= seconds <= 1.0
    # An alert that costs more than a page of text has no business in an APK.
    assert path.stat().st_size < 64 * 1024


def test_committed_wavs_match_the_generator(tmp_path):
    """The assets are exactly what `scripts/make_timer_sounds.py` produces.

    The generator is deterministic, so this is a real equality check: it fails
    if someone hand-edits a WAV, or changes the script and forgets to re-run it.
    """
    generator = _load_generator()
    written = generator.build(tmp_path)
    assert set(written) == {"rest_warning", "rest_done"}
    for name, regenerated in written.items():
        committed = SOUNDS_DIR / f"{name}.wav"
        assert regenerated.read_bytes() == committed.read_bytes(), (
            f"{committed} is stale — re-run scripts/make_timer_sounds.py"
        )


def test_the_two_tones_are_different_pitches():
    """The 10-second warning must not be mistakable for the finish."""
    generator = _load_generator()
    warn = generator.SOUNDS["rest_warning"]
    done = generator.SOUNDS["rest_done"]
    assert warn.freq_hz != done.freq_hz
    # Both in the 2–4 kHz band where the ear is most sensitive and a phone
    # speaker actually radiates. A 400 Hz "nicer" tone would be inaudible on
    # the gym floor, which is the whole point of the feature.
    for spec in (warn, done):
        assert 1500 <= spec.freq_hz <= 4000
    # And distinguishable by rhythm too, not only by pitch.
    assert len(warn.bursts_s) != len(done.bursts_s)


def test_audio_control_builds_without_leaking_a_deprecation_warning():
    """`ft.Audio` is a deprecated shim in 0.28 and warns on every construction.

    The timer builds one per rest, so the warning is suppressed at the call
    site. This fails if that suppression is dropped — which would print a
    DeprecationWarning into the log every ninety seconds.
    """
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        control = timer_mod._make_audio(DONE_SOUND)
    assert control is not None
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []


# ── the preference ────────────────────────────────────────────


def test_pref_defaults_to_on_when_never_set():
    store = FakeStore()
    assert sound_enabled(store) is True
    assert haptics_enabled(store) is True


def test_pref_defaults_to_on_when_storage_is_broken():
    """A database hiccup must not silently mute the timer, nor raise."""
    store = FakeStore(raises=True)
    assert sound_enabled(store) is True
    assert haptics_enabled(store) is True
    # Writing through a broken store is a no-op, not an exception.
    set_sound_enabled(store, False)


def test_pref_round_trips_through_storage():
    store = FakeStore()
    set_sound_enabled(store, False)
    assert store.values[SOUND_PREF] == "off"
    assert sound_enabled(store) is False
    set_sound_enabled(store, True)
    assert sound_enabled(store) is True
    set_haptics_enabled(store, False)
    assert haptics_enabled(store) is False


def test_no_store_reads_as_on():
    """Before `page.data` exists there is no store, and silence is not the
    default the user asked for."""
    assert sound_enabled(None) is True


async def test_muted_timer_makes_no_sound():
    store = FakeStore({SOUND_PREF: "off"})
    page = FakePage(store)
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(3)
    await page.drain()

    assert t.sound_on is False
    assert fired == []
    # Muted or not, the countdown still ran to the end.
    assert t.display.value == "¡YA!"


async def test_unmuted_timer_sounds_the_finish():
    page = FakePage(FakeStore())
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(3)
    await page.drain()

    assert fired == [DONE_SOUND]


async def test_toggle_sound_persists_and_takes_effect():
    """The speaker button writes the preference and stops the next beep."""
    store = FakeStore()
    page = FakePage(store)
    t = RestTimer(page)
    fired = _instrument(t)

    assert t.sound_on is True
    t.toggle_sound()
    assert t.sound_on is False
    assert store.values[SOUND_PREF] == "off"

    t.start(3)
    await page.drain()
    assert fired == []


async def test_haptics_have_their_own_switch():
    """Sound off, buzz on: the case of training with headphones in."""
    store = FakeStore({SOUND_PREF: "off"})
    page = FakePage(store)
    t = RestTimer(page)
    buzzed: list[str] = []
    t._play = lambda src: None  # type: ignore[method-assign]
    t._vibrate = buzzed.append  # type: ignore[method-assign]

    t.start(3)
    await page.drain()

    assert buzzed == [DONE_SOUND]


# ── firing exactly once ───────────────────────────────────────


async def test_restart_does_not_replay_the_previous_alert():
    """The bug this guards: `start()` while a countdown is running used to be
    able to leave two loops racing, and two "¡YA!" beeps is worse than none."""
    page = FakePage(FakeStore())
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(300)  # long enough that it is still running below
    await asyncio.sleep(0.005)
    t.start(3)  # restart — the first loop must die without alerting
    await page.drain()

    assert fired == [DONE_SOUND]
    assert len(page.tasks) == 2  # both loops really ran; only one alerted


async def test_stop_cancels_the_alert():
    """Cancelling a rest is a decision, and it must not be answered with a beep."""
    page = FakePage(FakeStore())
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(60)
    await asyncio.sleep(0.005)
    t.stop()
    await page.drain()

    assert fired == []
    assert t.running is False
    assert t.display.value == "—"


async def test_pre_alert_fires_once_and_before_the_finish():
    page = FakePage(FakeStore())
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(PRE_ALERT_MIN_TOTAL_S)
    await page.drain()

    assert fired == [WARN_SOUND, DONE_SOUND]


async def test_short_rest_gets_no_pre_alert():
    """ "Ten seconds left" on a fifteen-second rest is noise, not information."""
    page = FakePage(FakeStore())
    t = RestTimer(page)
    fired = _instrument(t)

    t.start(PRE_ALERT_S + 2)
    await page.drain()

    assert fired == [DONE_SOUND]


async def test_players_are_mounted_once_across_many_rests():
    """`page.overlay` must not grow an audio control per rest."""
    page = FakePage(FakeStore())
    t = RestTimer(page)
    _instrument(t)

    t.start(2)
    await page.drain()
    after_first = len(page.overlay)
    t.start(2)
    await page.drain()

    assert after_first > 0
    assert len(page.overlay) == after_first


# ── failure must not reach the countdown ──────────────────────


async def test_player_failure_does_not_break_the_countdown():
    """A browser refusing to play is the expected case, not an exception path.

    Autoplay policies block programmatic playback on a document the user has
    never touched. Reaching a rest requires tapping, so this should not happen
    — but if it does, the countdown is the part that must survive.
    """
    page = FakePage(FakeStore())
    t = RestTimer(page)

    def explode(src):
        raise RuntimeError("NotAllowedError: play() failed")

    t._play = explode  # type: ignore[method-assign]
    t._vibrate = explode  # type: ignore[method-assign]

    t.start(PRE_ALERT_MIN_TOTAL_S)
    await page.drain()

    assert t.running is False
    assert t.display.value == "¡YA!"
    assert t.ring.value == 1


async def test_unmountable_overlay_does_not_break_start():
    """A page that will not take the audio control still gets its countdown."""

    class HostilePage(FakePage):
        @property
        def overlay(self):
            raise RuntimeError("no overlay here")

        @overlay.setter
        def overlay(self, value):
            pass

    page = HostilePage(FakeStore())
    t = RestTimer(page)

    t.start(3)
    await page.drain()

    assert t.display.value == "¡YA!"


async def test_alert_with_nothing_mounted_is_a_no_op():
    """`_play` on a timer that never mounted resolves to no player at all."""
    page = FakePage(FakeStore())
    t = RestTimer(page)
    t._alert(DONE_SOUND)  # must not raise
    assert t._players == {}


# ── the store is found late ───────────────────────────────────


async def test_store_is_read_from_page_data_not_the_constructor():
    """`main.py` builds the views before it fills `page.data`.

    So the timer cannot capture the store at construction time; it has to look
    it up on first use. This is the test that fails if that is "simplified".
    """
    page = FakePage()  # no store yet — exactly the state at construction
    t = RestTimer(page)
    fired = _instrument(t)

    page.data["store"] = FakeStore({SOUND_PREF: "off"})  # main.py, later

    t.start(3)
    await page.drain()

    assert t.sound_on is False
    assert fired == []


async def test_explicit_store_argument_wins():
    """Passing the store directly stays supported, and skips `page.data`."""
    page = FakePage(FakeStore())  # says "on"
    t = RestTimer(page, store=FakeStore({SOUND_PREF: "off"}))
    fired = _instrument(t)

    t.start(3)
    await page.drain()

    assert fired == []


# ── the red panel ────────────────────────────────────────────
# An APK built by `flet build` has no audioplayers plugin, and Flet does not
# ignore a control the client cannot build: it paints a red "Unknown control:
# audio" panel over a third of the screen. The whole suite was green while that
# happened, because nothing in Python can see what the Dart side refuses to
# draw. These pin the platform decision so it cannot regress.


def _timer_en(plataforma, web):
    from unittest.mock import MagicMock

    import flet as ft

    from components.timer import RestTimer

    page = MagicMock(spec=ft.Page)
    page.platform, page.web, page.overlay, page.data = plataforma, web, [], {}
    t = RestTimer(page)
    t._mount_players()
    return [type(c).__name__ for c in page.overlay]


def test_android_no_monta_audio():
    """El fallo que se vio en el emulador: un panel rojo tapando la pantalla."""
    import flet as ft

    tipos = _timer_en(ft.PagePlatform.ANDROID, False)
    assert not [x for x in tipos if "Audio" in x], (
        "la APK no puede dibujar un control de audio: montar uno pinta "
        "'Unknown control: audio' sobre la pantalla de entreno"
    )


def test_android_conserva_la_vibracion():
    """Sin sonido, el aviso es la vibración — y en un gimnasio ruidoso es mejor."""
    import flet as ft

    tipos = _timer_en(ft.PagePlatform.ANDROID, False)
    assert [x for x in tipos if "Haptic" in x]


def test_el_navegador_si_tiene_sonido():
    """El cliente web sí trae el reproductor: ahí no hay que renunciar a nada."""
    import flet as ft

    tipos = _timer_en(ft.PagePlatform.LINUX, True)
    assert len([x for x in tipos if "Audio" in x]) == 2


# ── the vibration toggle (the preference nothing could change) ────────────


def test_el_boton_de_vibracion_esta_en_la_fila_de_controles():
    """THE REGRESSION. `HAPTICS_PREF` was stored, read and honoured — and no
    control in the whole app could flip it, so it was permanently on."""
    store = FakeStore()
    page = FakePage(store)
    t = RestTimer(page, store)
    fila = t.build()

    def aplanar(c):
        yield c
        for hijo in getattr(c, "controls", None) or []:
            yield from aplanar(hijo)
        contenido = getattr(c, "content", None)
        if contenido is not None:
            yield from aplanar(contenido)

    assert t.haptics_btn in list(aplanar(fila)), (
        "the vibration button is built but never rendered — the same "
        "'built and not wired' failure this project has had three times"
    )


def test_alternar_la_vibracion_la_persiste():
    store = FakeStore()
    page = FakePage(store)
    t = RestTimer(page, store)
    t.build()
    assert t.haptics_on is True

    t.toggle_haptics()
    assert t.haptics_on is False
    assert haptics_enabled(store) is False

    t.toggle_haptics()
    assert t.haptics_on is True
    assert haptics_enabled(store) is True


def test_sonido_y_vibracion_son_independientes():
    """Muting the beep must not also kill the buzz: they solve different rooms."""
    store = FakeStore()
    page = FakePage(store)
    t = RestTimer(page, store)
    t.build()

    t.toggle_sound()
    assert t.sound_on is False
    assert t.haptics_on is True, "muting the sound silently disabled the vibration too"


def test_la_vibracion_apagada_no_vibra():
    store = FakeStore()
    page = FakePage(store)
    t = RestTimer(page, store)
    t.build()
    t.toggle_haptics()
    t._mount_players()

    disparos = []
    if t._haptics is not None:
        t._haptics.heavy_impact = lambda: disparos.append("heavy")
        t._haptics.light_impact = lambda: disparos.append("light")
    t._alert(DONE_SOUND)
    assert disparos == []
