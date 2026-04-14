"""IronLog - Entry point + navigation."""

from __future__ import annotations

import flet as ft

import i18n
from data import ROUTINES, set_active_routine
from i18n import t
from storage import Storage
from theme import DARK_BG, ACCENT, NAV_BG
from views.browse import BrowseView
from views.home import HomeView
from views.plan import PlanView
from views.profile import ProfileView
from views.workout import WorkoutView
from views.history import HistoryView


def main(page: ft.Page):
    page.title = "IronLog"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = DARK_BG
    page.padding = 0
    page.window.width = 420
    page.window.height = 820
    page.fonts = {}
    page.theme = ft.Theme(color_scheme_seed=ACCENT)

    store = Storage()
    i18n.set_language(store.get_pref("lang", "en") or "en")
    set_active_routine(store.get_pref("routine", "cambiatufisico") or "cambiatufisico")

    current_tab = {"idx": 0}

    home_view = HomeView(page, store)
    plan_view = PlanView(page, store)
    workout_view = WorkoutView(page, store)
    browse_view = BrowseView(page, store)
    history_view = HistoryView(page, store)
    profile_view = ProfileView(page, store)
    view_list = [home_view, plan_view, workout_view, browse_view,
                 history_view, profile_view]
    # Only first 5 are represented in the nav bar; profile is reached from Home.
    NAV_COUNT = 5

    content_area = ft.Container(
        expand=True,
        padding=ft.padding.only(left=14, right=14, top=14, bottom=4),
    )

    def navigate_to(idx: int, refresh: bool = True):
        current_tab["idx"] = idx
        if 0 <= idx < NAV_COUNT:
            nav_bar.selected_index = idx
        v = view_list[idx]
        if refresh and hasattr(v, "on_show"):
            v.on_show()
        content_area.content = v.build()
        page.update()

    def on_nav_change(e):
        navigate_to(e.control.selected_index)

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        bgcolor=NAV_BG,
        indicator_color=ft.Colors.with_opacity(0.15, ACCENT),
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_ROUNDED, label=t("Home")),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH, label=t("Plan")),
            ft.NavigationBarDestination(icon=ft.Icons.FITNESS_CENTER, label=t("Train")),
            ft.NavigationBarDestination(icon=ft.Icons.SEARCH, label=t("Browse")),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART_ROUNDED, label=t("History")),
        ],
    )

    def set_language(lang: str):
        i18n.set_language(lang)
        store.set_pref("lang", lang)
        nav_labels = ["Home", "Plan", "Train", "Browse", "History"]
        for dest, key in zip(nav_bar.destinations, nav_labels):
            dest.label = t(key)
        navigate_to(current_tab["idx"])

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

    page.data = {
        "navigate_to": navigate_to,
        "store": store,
        "refresh_current": lambda: navigate_to(current_tab["idx"]),
        "set_language": set_language,
        "set_routine": set_routine,
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
    if os.environ.get("IRONLOG_WEB"):
        ft.app(main, view=ft.AppView.WEB_BROWSER, port=8550, host="0.0.0.0",
               assets_dir="assets")
    else:
        ft.app(main, assets_dir="assets")
