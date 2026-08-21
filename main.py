"""IronFlet - Entry point + navigation."""

from __future__ import annotations

import contextlib

import flet as ft

import flet_reconnect
import notificaciones
from data import set_active_routine
from routine_builder import ensure_tables, sync_user_routines
from storage import THEME_PREF, Storage
from theme import C, apply_theme, palette_for
from views.agent_view import AgentView
from views.browse import BrowseView
from views.data_view import DataView
from views.history import HistoryView
from views.home import HomeView
from views.nutrition_view import NutritionView
from views.photos_view import PhotosView
from views.plan import PlanView
from views.profile import ProfileView
from views.routine_editor import RoutineEditorView
from views.workout import WorkoutView
from workout_draft import DraftStore

# THE BLACK-SCREEN FIX. Must run at import time, before `ft.app()`: the server
# binds `self.handle_connection` when it starts, so patching the class later
# changes nothing. See flet_reconnect.py — it is the whole explanation.
flet_reconnect.apply()

#: View index of the training screen. Frozen, like every index here (home.py
#: navigates by number); see the NAV_TABS comment inside `main`.
TRAIN_VIEW_IDX = 2

#: The session `main()` built last. Re-entrant on purpose: after a reconnect
#: Flet creates a new Page and calls `main()` again in the same process, so the
#: previous one's database engine has to be let go or every trip to Spotify
#: leaks a connection pool.
_previous_session: dict = {"store": None}


def initial_view_index(store) -> int:
    """Which tab a cold start lands on: Train when a workout is in progress.

    The safety net for the case this app cannot prevent — Android killing the
    process outright. `workout_draft` already persists the session on every
    structural change and `WorkoutView.on_show()` already restores it, but
    start-up always landed on Home, so Alex had to *know* to tap Train to get
    his sets back. Unless he knew, a killed process looked exactly like lost
    work.

    `DraftStore.load()` decides on its own whether the draft is live: it applies
    the six-hour TTL, refuses a draft belonging to another routine, and re-points
    it at the routine as it is now. Anything it will not restore lands on Home,
    which is the old behaviour. It never raises; the try/except is for the
    unexpected, because nothing about start-up may be able to take the app down.
    """
    try:
        if DraftStore(store).load() is not None:
            return TRAIN_VIEW_IDX
    except Exception as exc:  # pragma: no cover - defensive
        flet_reconnect.record("startup", f"draft check failed: {exc!r}")
    return 0


def _release_previous_session(store) -> None:
    """Dispose the engine of the session this one replaces.

    Only ever fires on a reconnect (Android re-created the Flutter client and
    Flet ran `main()` again). Without it every foreground/background cycle would
    add a `Storage` — a SQLAlchemy engine and its pool — with nothing releasing
    the previous one. Private attribute on purpose: `Storage` exposes no
    `close()`, and inventing one here is a wider change than this fix deserves.
    """
    previous = _previous_session.get("store")
    _previous_session["store"] = store
    if previous is None or previous is store:
        return
    engine = getattr(previous, "_engine", None)
    if engine is None:
        return
    with contextlib.suppress(Exception):
        engine.dispose()


def main(page: ft.Page):
    page.title = "IronFlet"
    # One call sets the palette, the theme mode and the Material ColorScheme.
    # Doing it piecemeal leaves dialogs and text fields on the previous theme.
    #
    # The palette is read from `preferencias` BEFORE the first render, and the
    # store is opened a few lines below — so this is deliberately done twice:
    # a default now so nothing paints unstyled, and the stored choice as soon as
    # there is a database to ask. Anything else flashes the wrong theme on every
    # cold start.
    apply_theme(page)
    page.padding = 0
    page.window.width = 420
    page.window.height = 820
    page.fonts = {}

    store = Storage()
    _release_previous_session(store)
    # Load user-built routines into data.ROUTINES before resolving the active
    # one: the saved preference may well point at one of them.
    ensure_tables(store)
    sync_user_routines(store)
    set_active_routine(store.get_pref("routine", "cambiatufisico") or "cambiatufisico")
    apply_theme(page, palette_for(store.get_pref(THEME_PREF)))
    # Reprograma las notificaciones del móvil con lo que haya en la base. En
    # el PC no escribe nada (los avisos ahí los entrega el bot por Telegram) y
    # nunca puede tumbar el arranque: un fichero que no se pudo escribir cuesta
    # avisos, no la app.
    with contextlib.suppress(Exception):
        notificaciones.sync(store)

    current_tab = {"idx": 0}

    home_view = HomeView(page, store)
    plan_view = PlanView(page, store)
    workout_view = WorkoutView(page, store)
    browse_view = BrowseView(page, store)
    history_view = HistoryView(page, store)
    profile_view = ProfileView(page, store)
    nutrition_view = NutritionView(page, store)
    routines_view = RoutineEditorView(page, store)
    data_view = DataView(page, store)
    agent_view = AgentView(page, store)
    photos_view = PhotosView(page, store)
    view_list = [
        home_view,
        plan_view,
        workout_view,
        browse_view,
        history_view,
        profile_view,
        nutrition_view,
        routines_view,
        data_view,
        # Appended, never inserted: `home.py` navigates by number and the
        # indices above are frozen. See trap #1 in CLAUDE.md.
        agent_view,
        photos_view,
    ]
    # The bar shows five of them. This indirection exists because home.py calls
    # navigate_to(2) and navigate_to(5) by number, so view indices are frozen —
    # NAV_TABS maps a bar slot to a view index instead of forcing them to match.
    # Browse, Profile and Routines are reached from inside other screens.
    NAV_TABS = (0, 1, 2, 6, 4)

    #: Cuánto dura el fundido al cambiar de pantalla. 180 ms es el rango en el
    #: que una transición se percibe como que la interfaz responde; por encima
    #: de ~250 se percibe como que va lenta.
    _FUNDIDO_MS = 180

    # El fundido es SOLO para cambiar de pantalla. `refresh_current()` se llama
    # a cada serie confirmada, a cada peso apuntado y a cada tecla del
    # buscador de alimentos, y un fundido en cada uno de esos no es pulido:
    # es la pantalla parpadeando mientras entrenas. Así que la duración se
    # pone a cero cuando se está redibujando la misma vista, y el
    # `AnimatedSwitcher` se comporta como el `Container` de antes.
    switcher = ft.AnimatedSwitcher(
        content=ft.Container(),
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=0,
        reverse_duration=0,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_IN,
        expand=True,
    )
    content_area = ft.Container(
        content=switcher,
        expand=True,
        padding=ft.padding.only(left=14, right=14, top=14, bottom=4),
    )

    def navigate_to(idx: int, refresh: bool = True):
        cambia_de_pantalla = current_tab["idx"] != idx
        current_tab["idx"] = idx
        if idx in NAV_TABS:
            nav_bar.selected_index = NAV_TABS.index(idx)
        v = view_list[idx]
        if refresh and hasattr(v, "on_show"):
            v.on_show()
        switcher.duration = _FUNDIDO_MS if cambia_de_pantalla else 0
        switcher.content = v.build()
        # Zen mode: the training screen asks for the bar to go away while a set
        # is in front of you. Read *after* build(), because the answer depends
        # on the state build() just rendered from. Any view without the method
        # keeps the bar, which is what every other screen wants.
        nav_bar.visible = not (hasattr(v, "hides_nav") and v.hides_nav())
        page.update()

    def on_nav_change(e):
        navigate_to(NAV_TABS[e.control.selected_index])

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        bgcolor=C.bg_nav,
        indicator_color=C.accent_soft,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_ROUNDED, label="Inicio"),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH, label="Plan"),
            ft.NavigationBarDestination(icon=ft.Icons.FITNESS_CENTER, label="Entreno"),
            ft.NavigationBarDestination(icon=ft.Icons.RESTAURANT_ROUNDED, label="Comida"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART_ROUNDED, label="Historial"),
        ],
    )

    def set_routine(rid: str):
        set_active_routine(rid)
        store.set_pref("routine", rid)
        # Reset workout flow state — phases differ across routines
        workout_view.phase_id = 0
        workout_view.day_idx = -1
        workout_view.ex_idx = 0
        workout_view.completed = []
        workout_view.finished = False
        plan_view.selected_phase_idx = None
        navigate_to(current_tab["idx"])

    def edit_routine(pk: int):
        """Jump straight into a routine, instead of landing on the library."""
        navigate_to(7, refresh=False)
        routines_view.open_routine(pk)

    page.data = {
        "navigate_to": navigate_to,
        # Home's photo tile opens the system picker THROUGH the gallery view,
        # so the picker object and its overlay wiring live in exactly one place.
        "photos_view": photos_view,
        "store": store,
        "refresh_current": lambda: navigate_to(current_tab["idx"]),
        "set_routine": set_routine,
        "edit_routine": edit_routine,
    }

    def on_keyboard(e: ft.KeyboardEvent):
        if e.key in ("Escape", "Back"):
            v = view_list[current_tab["idx"]]
            if hasattr(v, "handle_back") and v.handle_back():
                page.update()
                return
            if current_tab["idx"] != 0:
                navigate_to(0)

    page.on_keyboard_event = on_keyboard

    def flush_workout_draft():
        """Get the workout in progress on disk before Android can kill us.

        PAUSE is the last moment guaranteed to run: after it the process may be
        killed at any time with no further callback. Structural actions (a set
        added, an exercise changed) already force a write, so the exposure this
        closes is the few seconds of *typing* that `DraftStore` coalesces — the
        half-entered set that is on screen when the user leaves for Spotify.

        Reaches into a private method knowingly: `WorkoutView` exposes no public
        "persist now", and this file must not grow a second copy of the draft
        logic. If it is ever renamed, `getattr` degrades to a no-op and the log
        line below says so, instead of taking the lifecycle handler down.
        """
        persist = getattr(workout_view, "_persist_draft", None)
        if not callable(persist):
            flet_reconnect.record("lifecycle", "no _persist_draft on WorkoutView")
            return
        try:
            persist()
        except Exception as exc:  # pragma: no cover - defensive
            flet_reconnect.record("lifecycle", f"draft flush failed: {exc!r}")

    def on_lifecycle(e):
        # WHY THIS IS NOT JUST `navigate_to()` ANY MORE — do not "simplify" it
        # back. Version 0.1.0 shipped exactly that, the CHANGELOG announced it
        # as the fix for the black screen, and the black screen carried on
        # happening. It could not have worked: repainting rebuilds the *control
        # tree*, and the problem is that there is no longer a channel to the
        # client to paint it into. `navigate_to()` ends in `page.update()`,
        # which enqueues messages that Flet's send loop then tries to write to
        # the socket of the client Android already destroyed; the write fails,
        # the message is re-enqueued, the loop dies. Meanwhile the *new* Flutter
        # client is sitting on a connection that Flet 0.28.3 accepted and
        # ignored, with an empty control store, painting nothing.
        #
        # The actual repair is the socket-server backport applied at import time
        # (see flet_reconnect.py). What is left here is worth keeping for its
        # own reasons: the repaint still fixes the cheap case (the client
        # survived and only needs a frame), and the log line is what will tell
        # us, from Alex's phone, whether a resume was accompanied by a
        # reconnection — the one link in the diagnosis nobody could verify
        # without a device.
        raw = getattr(e, "state", None)
        state = str(raw or "").rsplit(".", 1)[-1].upper()
        flet_reconnect.record("lifecycle", state or "unknown")
        if state in ("PAUSE", "HIDE", "INACTIVE", "DETACH"):
            flush_workout_draft()
            return
        if state == "RESUME":
            navigate_to(current_tab["idx"])

    page.on_app_lifecycle_state_change = on_lifecycle

    # Land on the workout when one is in progress (see `initial_view_index`),
    # on Home otherwise. Done inline rather than through `navigate_to()` so the
    # first render is one page.add() instead of an update before the page has
    # any content.
    start_idx = initial_view_index(store)
    current_tab["idx"] = start_idx
    if start_idx in NAV_TABS:
        nav_bar.selected_index = NAV_TABS.index(start_idx)
    start_view = view_list[start_idx]
    if hasattr(start_view, "on_show"):
        start_view.on_show()
    # Al switcher, no al Container: `content_area` ya lo contiene. Y con la
    # duración todavía en cero, que es lo que queremos — la primera pantalla
    # aparece, no se funde desde nada.
    switcher.content = start_view.build()
    page.add(
        ft.SafeArea(content=content_area, expand=True),
        nav_bar,
    )


if __name__ == "__main__":
    # Una sola forma de arrancar. El modo web (`IRONFLET_WEB`, loopback, el
    # servicio `ironflet-web`) se jubiló en 0.13 junto con la versión de PC:
    # esta app es la APK, y en el escritorio solo se abre para desarrollar.
    ft.app(main, assets_dir="assets")
