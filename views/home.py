"""Home: what today is, the week in three numbers, and the doors out.

The first card is the one that earns the screen: which session today is. It is
the question the app gets opened with, and until now the answer lived two taps
into Plan, in a tab you had to know existed. The arithmetic is
`program_week.py`'s and the copy is shared with Plan through
`views.plan.open_start_date_dialog` — imported rather than reimplemented, for
the same reason `bar_flex` is imported from the food screen: two versions of the
control that decides which week Alex is in would drift, and this one decides
which gym session he does.

That card says "I do not know" out loud when nothing records when the routine
started, which is the state of a fresh install. It is not softened into a guess:
a confident wrong session is a wasted training day, an admitted unknown is one
tap from being fixed. `current_program_week()` runs a query, so it is taken in
`on_show()` and held, exactly as that module asks.

Home is also the only way into two screens that have no slot in the bottom bar:
the exercise catalogue (Browse) and — by tapping the nutrition card — the food
diary. A screen nobody can navigate to may as well not have been written.

The numbers here are deliberately literal. The streak counts *weeks*, not days,
and "Sessions" counts *days trained*, not table rows; both labels used to claim
something the value did not mean. See `analytics.training_streak` for why the
weekly definition is the honest one, and `storage.weekly_session_minimum` for
where the weekly bar comes from — routines here train 3 to 6 days a week, so
the bar is read off the active routine rather than fixed.
"""

from __future__ import annotations

from datetime import date

import flet as ft

from dates import day_name, month_name
from exercises import phase_color
from nutrition import day_totals, targets_for
from program_week import (
    ProgramWeek,
    StartSource,
    WeekStatus,
    current_program_week,
    is_rest_label,
    training_day_for_label,
)
from storage import Storage
from theme import (
    C,
    Radius,
    Space,
    card,
    chip,
    ghost_button,
    muted_text,
    primary_button,
    section_title,
)
from views.plan import next_session, open_start_date_dialog, start_caveat, week_headline

# main.py owns the routing table; naming the indices here keeps the calls
# readable and makes it obvious what breaks if that table is reordered.
VIEW_PLAN = 1
VIEW_WORKOUT = 2
VIEW_BROWSE = 3
VIEW_PROFILE = 5
VIEW_NUTRITION = 6

# Trailing window behind get_week_stats(); shown so the three numbers below it
# are not read as "all time".
STATS_WINDOW_LABEL = "Last 7 days"


def today_display() -> str:
    d = date.today()
    return f"{day_name(d.weekday())}, {d.day} {month_name(d.month - 1)}"


def _n(value) -> str:
    """Whole numbers only — a summary card has no room for tenths of a gram."""
    return f"{round(float(value or 0)):.0f}"


def _macro_bar(current: float, target: float, color: str, over_color: str) -> ft.Control:
    """Progress towards a daily target, using the food screen's own geometry.

    `bar_flex` is imported rather than reimplemented so this bar and the ones on
    the Food screen stay the same bar; two implementations would drift the first
    time one of them was tuned.
    """
    from views.nutrition_view import bar_flex

    eaten, rest, over = bar_flex(current, target)
    segments: list[ft.Control] = []
    if eaten:
        segments.append(ft.Container(bgcolor=color, expand=eaten))
    if rest:
        segments.append(ft.Container(bgcolor=C.bg_sunken, expand=rest))
    if over:
        segments.append(ft.Container(bgcolor=over_color, expand=over))
    return ft.Container(
        content=ft.Row(segments, spacing=0),
        height=6,
        bgcolor=C.bg_sunken,
        border_radius=Radius.pill,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


class HomeView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self._week: ProgramWeek | None = None

    def on_show(self):
        # One query per activation, held for `build()` — `program_week` asks for
        # this explicitly, and every refresh path in main.py comes through
        # `navigate_to`, which calls `on_show()` before rebuilding.
        self._week = current_program_week(self.store)

    def _program_week(self) -> ProgramWeek:
        """The held answer, computed on demand if `on_show()` never ran."""
        if self._week is None:
            self._week = current_program_week(self.store)
        return self._week

    def _reload(self):
        self._week = None
        self.page.data["refresh_current"]()

    def handle_back(self) -> bool:
        return False

    # ── small pieces ─────────────────────────────────────────
    def _stat_card(self, value: str, label: str, tooltip: str | None = None) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        value,
                        size=22,
                        weight=ft.FontWeight.W_900,
                        color=C.accent,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color=C.text_secondary,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.xl,
            padding=ft.padding.symmetric(horizontal=8, vertical=10),
            expand=True,
            height=72,
            tooltip=tooltip,
        )

    def _streak_card(self, streak: int) -> ft.Control:
        return card(
            ft.Text("🔥", size=18, text_align=ft.TextAlign.CENTER),
            ft.Text(
                str(streak),
                size=20,
                weight=ft.FontWeight.W_900,
                color=C.accent,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "week" if streak == 1 else "weeks",
                size=9,
                weight=ft.FontWeight.W_700,
                color=C.text_muted,
                text_align=ft.TextAlign.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            alignment=ft.alignment.center,
            tooltip="Consecutive weeks that hit your routine's session minimum",
        )

    def _today_item(self, w) -> ft.Container:
        set_chips = [
            chip(
                f"{s['weight']:g}kg × {s['reps']}"
                if s.get("weight", 0) > 0
                else f"{s['reps']} reps",
                color=C.accent,
            )
            for s in w.sets
        ]
        return card(
            ft.Row(
                [
                    ft.Text(
                        w.exercise,
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=C.text,
                        expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    chip(w.muscle_group, color=C.accent),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(set_chips, wrap=True, spacing=6, run_spacing=4) if set_chips else ft.Container(),
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    # ── what today is ────────────────────────────────────────
    def _today_card(self) -> ft.Control:
        """Today's session, in the first thing on the screen.

        Four outcomes on an active week, and each says exactly what it knows:

        * a training day — the session name, big, how many exercises it holds,
          and the card opens Train;
        * a rest day — said plainly, plus what is next, so a rest day does not
          read as a bug. The weekend lands here too: the rotation rows only
          cover Mon-Fri, so `today_focus` is None on Saturday, and the next
          week's row only exists once Monday makes it the current one;
        * a known week whose phase does not pin sessions to weekdays
          (CambiaTuFísico phases 4-7, and every routine with no rotation) — the
          phase, and an honest "pick it in Train". Those phases prescribe five
          sessions without saying which day each falls on, and dealing them out
          Mon-to-Fri would be the app inventing the plan;
        * no week at all — see `_no_session_card`.
        """
        pw = self._program_week()
        if pw.status is not WeekStatus.ACTIVE or pw.phase is None:
            return self._no_session_card(pw)

        phase = pw.phase
        focus = pw.today_focus
        sub = f"Phase {phase.id} · {phase.name}"
        tip: str | None

        if pw.rotation is None:
            # The phase name is the headline here, so the line under it carries
            # the subtitle instead — printing the name twice tells nobody
            # anything.
            headline, target, tip = phase.name, VIEW_WORKOUT, "Pick today's session in Train"
            sub = f"Phase {phase.id} · {phase.subtitle}" if phase.subtitle else f"Phase {phase.id}"
        elif focus is None or is_rest_label(focus):
            nxt = next_session(pw)
            headline, target = "Rest day", VIEW_PLAN
            if nxt:
                tip = f"Next: {day_name(nxt[0])} · {nxt[1]}"
            else:
                tip = "The new week's plan starts on Monday"
        else:
            headline, target = focus, VIEW_WORKOUT
            # The label is a session name; the phase turns it into real work.
            # None when this phase does not have that day, and then the count is
            # simply not claimed.
            day = training_day_for_label(focus, phase)
            tip = f"{len(day.exercises)} exercises" if day else None

        lines: list[ft.Control] = [
            ft.Text(
                f"TODAY · {week_headline(pw)}", size=10, weight=ft.FontWeight.W_900, color=C.accent
            ),
            ft.Text(
                headline,
                size=20,
                weight=ft.FontWeight.W_900,
                color=C.text,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Text(sub, size=11, weight=ft.FontWeight.W_700, color=phase_color(phase.id)),
        ]
        if tip:
            lines.append(ft.Text(tip, size=11, color=C.text_muted))
        # Both of these are silent on a normal week. They are the difference
        # between a number that is a fact and one that is arithmetic: an
        # inferred start date, and a week count that has run on without training.
        caveat = start_caveat(pw)
        if caveat:
            lines.append(ft.Text(caveat, size=10, color=C.text_muted))
        if pw.stale:
            lines.append(
                ft.Text(
                    f"Nothing logged for {pw.weeks_idle} weeks — see Plan to restart",
                    size=10,
                    color=C.warning,
                )
            )

        nav = self.page.data["navigate_to"]
        return card(
            ft.Row(
                [
                    ft.Column(lines, spacing=2, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=Space.x3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            border_color=C.accent,
            on_click=lambda _, v=target: nav(v),
            ink=True,
            tooltip="Open Train" if target == VIEW_WORKOUT else "Open the week's plan",
        )

    def _no_session_card(self, pw: ProgramWeek) -> ft.Control:
        """No session to name — never dated, not started, over, or off-plan.

        Four different reasons and four different sentences: "I don't know when
        you started" and "you finished the routine" both leave today blank, and
        telling them apart is the whole reason `WeekStatus` exists. The fix
        button is here rather than a trip to Plan because this is where the
        reader is standing when they find out.
        """
        started = pw.start.day
        if pw.status is WeekStatus.SCHEDULED:
            title = "Not started yet"
            body = (
                f"This routine is set to start on {started.isoformat()}."
                if started
                else "This routine is set to start in a later week."
            )
        elif pw.status is WeekStatus.FINISHED:
            title = "Routine finished"
            body = (
                f"{week_headline(pw).capitalize()} is past the end of this routine. "
                "Set a new start date to run it again, or pick another routine in Plan."
            )
        elif pw.status is WeekStatus.ACTIVE:  # active, but no phase claims the week
            title = "No phase covers this week"
            body = (
                f"{week_headline(pw).capitalize()} falls in a gap between the phase "
                "ranges of this routine. Check them in Plan."
            )
        elif pw.start.source is StartSource.OTHER_ROUTINE:
            # A date exists, it just belongs to a routine he switched away from.
            # Saying "nothing records when you started" here would be a lie he
            # could disprove, and the fix is one tap: the dialog opens on that
            # date, so adopting it is a save.
            title = "Week unknown"
            body = (
                "A start date is stored, but it was saved for another routine, so "
                "it cannot place you in this one — switching routines starts a new "
                "program. Set the date to carry it over."
            )
        else:
            title = "Week unknown"
            body = (
                "Nothing records when you started this routine, so the app cannot "
                "say which session today is — and a guess would send you to the gym "
                "on the wrong day. Set the date, or just train: the first session "
                "you log dates the routine."
            )
        prefill = started if pw.start.source is StartSource.OTHER_ROUTINE else None
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.HELP_OUTLINE, color=C.warning, size=18),
                    ft.Text(title, size=15, weight=ft.FontWeight.W_900, color=C.text, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(body, size=11, color=C.text_secondary),
            ft.Container(height=Space.x1),
            ghost_button(
                "Set start date",
                on_click=lambda _, d=prefill: open_start_date_dialog(
                    self.page, self.store, on_saved=self._reload, initial=d
                ),
                expand=True,
            ),
            padding=14,
            border_color=C.warning,
        )

    # ── nutrition ────────────────────────────────────────────
    def _macro_line(self, label: str, current: float, target: float, unit: str) -> ft.Control:
        # Overshooting calories is worth a warning; overshooting protein is not,
        # so each line says for itself what "past the target" looks like.
        over_target = label == "Calories"
        value = f"{_n(current)} / {_n(target)} {unit}" if target > 0 else f"{_n(current)} {unit}"
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(label, size=11, weight=ft.FontWeight.W_700, color=C.text_secondary),
                        ft.Text(value, size=11, color=C.text_muted),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                _macro_bar(
                    current,
                    target,
                    C.accent if over_target else C.success,
                    C.warning if over_target else C.success,
                ),
            ],
            spacing=3,
            tight=True,
        )

    def _nutrition_body(self, totals: dict, targets: dict, logged: bool) -> ft.Control:
        target_kcal = float(targets.get("kcal") or 0)
        target_protein = float(targets.get("protein") or 0)

        if not logged:
            # Zeroes against a target read as failure at 9am. An empty day is an
            # invitation, so it gets one.
            hint = (
                f"Today's target: {_n(target_kcal)} kcal · {_n(target_protein)} g protein"
                if target_kcal > 0
                else "Log a meal to start tracking calories and protein"
            )
            return ft.Column(
                [
                    ft.Text(
                        "Nothing logged today", size=13, weight=ft.FontWeight.W_700, color=C.text
                    ),
                    ft.Text(hint, size=11, color=C.text_muted),
                ],
                spacing=2,
                tight=True,
                expand=True,
            )

        return ft.Column(
            [
                ft.Text("Food today", size=13, weight=ft.FontWeight.W_700, color=C.text),
                self._macro_line("Calories", float(totals.get("kcal") or 0), target_kcal, "kcal"),
                self._macro_line("Protein", float(totals.get("protein") or 0), target_protein, "g"),
            ],
            spacing=Space.x2,
            tight=True,
            expand=True,
        )

    def _nutrition_card(self) -> ft.Control:
        today = date.today()
        totals = day_totals(self.store, today) or {}
        targets = targets_for(self.store, today) or {}
        # Entries first: an entry can legitimately be 0 kcal (black coffee), and
        # a day with one is not an empty day. Calories are the fallback for when
        # the meal blocks arrive without their entries.
        logged = bool(
            any(block.get("entries") for block in (totals.get("by_meal") or {}).values())
            or float(totals.get("kcal") or 0) > 0
        )
        nav = self.page.data["navigate_to"]
        return card(
            ft.Row(
                [
                    ft.Text("🍽", size=20),
                    self._nutrition_body(totals, targets, logged),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=Space.x3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            on_click=lambda _: nav(VIEW_NUTRITION),
            ink=True,
            tooltip="Open the food diary",
        )

    # ── screen ───────────────────────────────────────────────
    def build(self) -> ft.Control:
        streak = self.store.get_streak()
        stats = self.store.get_week_stats()
        today = self.store.get_today()

        vol = stats["volume"]
        vol_str = f"{vol / 1000:.1f}k" if vol >= 1000 else f"{int(vol)}"

        nav = self.page.data["navigate_to"]
        profile_btn = ft.Container(
            content=ft.Icon(ft.Icons.SETTINGS, color=C.accent, size=18),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.sm,
            width=34,
            height=34,
            alignment=ft.alignment.center,
            on_click=lambda _: nav(VIEW_PROFILE),
            ink=True,
            tooltip="Settings",
        )

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("IRONFLET", size=11, weight=ft.FontWeight.W_900, color=C.accent),
                        ft.Text(today_display(), size=22, weight=ft.FontWeight.W_900, color=C.text),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.Row(
                    [profile_btn, self._streak_card(streak)],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        stats_row = ft.Row(
            [
                # The window is named once, above the row, so the tooltips only
                # have to say what each number counts.
                self._stat_card(str(stats["sessions"]), "Sessions", tooltip="Days you trained"),
                self._stat_card(str(stats["sets"]), "Sets", tooltip="Sets logged"),
                self._stat_card(vol_str, "Vol (kg)", tooltip="Weight × reps"),
            ],
            spacing=8,
        )

        start_btn = primary_button(
            "Start Routine",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=lambda _: nav(VIEW_WORKOUT),
            expand=True,
        )
        # Browse lost its tab when the bar went down to five. This is now the
        # only entrance to the catalogue, so it is a labelled button, not an icon.
        browse_btn = ghost_button(
            "Exercises",
            on_click=lambda _: nav(VIEW_BROWSE),
            width=112,
            height=48,
            tooltip="Browse the exercise library",
        )

        if today:
            today_block: ft.Control = ft.Column(
                [self._today_item(w) for w in today],
                spacing=0,
                tight=True,
            )
        else:
            today_block = ft.Container(
                content=ft.Column(
                    [
                        ft.Text("💤", size=28, text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            "No records",
                            size=12,
                            color=C.text_muted,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                bgcolor=C.bg_surface,
                border=ft.border.all(1, C.border),
                border_radius=Radius.xl,
                padding=24,
                alignment=ft.alignment.center,
            )

        return ft.Column(
            [
                header,
                ft.Container(height=Space.x4),
                # Above the numbers on purpose: the numbers are last week, this
                # is the next hour.
                self._today_card(),
                ft.Container(height=Space.x4),
                muted_text(STATS_WINDOW_LABEL),
                ft.Container(height=Space.x1),
                stats_row,
                ft.Container(height=Space.x4),
                ft.Row([start_btn, browse_btn], spacing=8),
                ft.Container(height=Space.x4),
                self._nutrition_card(),
                ft.Container(height=Space.x4),
                # "Today" twice on one screen would be two different meanings of
                # the word: the card at the top is the *plan*, this is what was
                # actually logged.
                section_title("Logged today"),
                ft.Container(height=Space.x1),
                today_block,
                ft.Container(height=18),
                section_title("Guides"),
                ft.Container(height=Space.x1),
                self._guides_row(),
                ft.Container(height=Space.x4),
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
        )

    def _guides_row(self) -> ft.Control:
        """One card per guide, however many there are.

        The row is driven by `guide_ids()` and every card is `expand=True`, so
        the width is split evenly whatever the count: measured at the 420 px
        window, three cards come out 125 px each and two come out 192 px, both
        flush with the stats row above. Dropping the women guide therefore
        needed no change here. Do not pin a width to keep the old card size —
        two fixed cards leave a dead strip on the right instead of filling it.
        """
        from guides import guide_icon, guide_ids, guide_title_key
        from views.guide_dialog import open_guide

        def card_link(gid: str) -> ft.Container:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            guide_icon(gid),
                            size=22,
                            color=C.text,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            guide_title_key(gid),
                            size=11,
                            color=C.text_secondary,
                            weight=ft.FontWeight.W_700,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
                bgcolor=C.bg_surface,
                border=ft.border.all(1, C.border),
                border_radius=Radius.xl,
                padding=ft.padding.symmetric(horizontal=8, vertical=10),
                on_click=lambda _, g=gid: open_guide(self.page, g),
                ink=True,
                expand=True,
                height=72,
            )

        return ft.Row([card_link(gid) for gid in guide_ids()], spacing=8)
