"""IronFlet - Entry point + navigation."""

from __future__ import annotations

import flet as ft

from data import set_active_routine
from routine_builder import ensure_tables, sync_user_routines
from storage import Storage
from theme import LIGHT, C, apply_theme
from views.browse import BrowseView
from views.history import HistoryView
from views.home import HomeView
from views.nutrition_view import NutritionView
from views.plan import PlanView
from views.profile import ProfileView
from views.routine_editor import RoutineEditorView
from views.workout import WorkoutView


def main(page: ft.Page):
    page.title = "IronFlet"
    # One call sets the palette, the theme mode and the Material ColorScheme.
    # Doing it piecemeal leaves dialogs and text fields on the previous theme.
    apply_theme(page, LIGHT)
    page.padding = 0
    page.window.width = 420
    page.window.height = 820
    page.fonts = {}

    store = Storage()
    # Load user-built routines into data.ROUTINES before resolving the active
    # one: the saved preference may well point at one of them.
    ensure_tables(store)
    sync_user_routines(store)
    set_active_routine(store.get_pref("routine", "cambiatufisico") or "cambiatufisico")

    current_tab = {"idx": 0}

    home_view = HomeView(page, store)
    plan_view = PlanView(page, store)
    workout_view = WorkoutView(page, store)
    browse_view = BrowseView(page, store)
    history_view = HistoryView(page, store)
    profile_view = ProfileView(page, store)
    nutrition_view = NutritionView(page, store)
    routines_view = RoutineEditorView(page, store)
    view_list = [
        home_view,
        plan_view,
        workout_view,
        browse_view,
        history_view,
        profile_view,
        nutrition_view,
        routines_view,
    ]
    # The bar shows five of them. This indirection exists because home.py calls
    # navigate_to(2) and navigate_to(5) by number, so view indices are frozen —
    # NAV_TABS maps a bar slot to a view index instead of forcing them to match.
    # Browse, Profile and Routines are reached from inside other screens.
    NAV_TABS = (0, 1, 2, 6, 4)

    content_area = ft.Container(
        expand=True,
        padding=ft.padding.only(left=14, right=14, top=14, bottom=4),
    )

    def navigate_to(idx: int, refresh: bool = True):
        current_tab["idx"] = idx
        if idx in NAV_TABS:
            nav_bar.selected_index = NAV_TABS.index(idx)
        v = view_list[idx]
        if refresh and hasattr(v, "on_show"):
            v.on_show()
        content_area.content = v.build()
        page.update()

    def on_nav_change(e):
        navigate_to(NAV_TABS[e.control.selected_index])

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        bgcolor=C.bg_nav,
        indicator_color=C.accent_soft,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_ROUNDED, label="Home"),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH, label="Plan"),
            ft.NavigationBarDestination(icon=ft.Icons.FITNESS_CENTER, label="Train"),
            ft.NavigationBarDestination(icon=ft.Icons.RESTAURANT_ROUNDED, label="Food"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART_ROUNDED, label="History"),
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

    def on_lifecycle(e):
        # Force a repaint when the OS brings the app back to foreground —
        # otherwise the Flutter shell can stay black until the user interacts.
        state = getattr(e, "state", None)
        if state and str(state).endswith("RESUME"):
            navigate_to(current_tab["idx"])

    page.on_app_lifecycle_state_change = on_lifecycle

    if hasattr(home_view, "on_show"):
        home_view.on_show()
    content_area.content = home_view.build()
    page.add(
        ft.SafeArea(content=content_area, expand=True),
        nav_bar,
    )


if __name__ == "__main__":
    import os

    if os.environ.get("IRONFLET_WEB"):
        ft.app(
            main,
            view=ft.AppView.WEB_BROWSER,
            # Both are overridable so a second instance can be started for
            # testing without stopping the one systemd is running on 8550.
            port=int(os.environ.get("IRONFLET_PORT", "8550")),
            # Loopback by default: this app is served on the machine it runs on
            # and nothing about it is meant to be reachable from the network.
            host=os.environ.get("IRONFLET_HOST", "127.0.0.1"),
            assets_dir="assets",
        )
    else:
        ft.app(main, assets_dir="assets")
