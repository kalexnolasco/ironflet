"""Plan: the phases of the active routine, and where routines are chosen.

Choosing a routine is also where people go looking for "make me one of my own",
so the way into the routine editor lives here rather than in a tab of its own:
duplicating the built-in you already follow is the realistic first step, and it
is offered on the built-ins themselves.

This screen also answers "what does *this* week look like", which used to be a
tab you had to go and find. All the arithmetic is `program_week.py`'s; this file
only renders `ProgramWeek`, and it renders every one of its four statuses
instead of only the happy one. The unknown case is not decorated away: without a
start date a confident "today: Chest-Biceps" is a coin flip, and training the
wrong day is worse than being told the app cannot tell yet.

`current_program_week()` runs a query, so it is called in `on_show()` and held
on the view — `build()` renders from `self._week`. Every refresh path in main.py
goes through `navigate_to`, which calls `on_show()` first, so the held value
cannot go stale behind a re-render (including after the start-date dialog).

`open_start_date_dialog()` is also used by views/home.py, and lives here because
this is the program screen. It is imported rather than reimplemented for the
same reason home.py imports `bar_flex` from the food screen: two copies of the
one control that decides which week Alex is in would drift, and the two screens
would then disagree about it.
"""

from __future__ import annotations

import contextlib
from datetime import date, timedelta

import flet as ft

from data import ROUTINES, active_routine
from dates import day_name
from exercise_details import details_for
from exercise_images import image_props
from exercises import exercise_key, phase_color
from program_week import (
    ProgramWeek,
    StartSource,
    WeekStatus,
    current_program_week,
    is_rest_label,
    restart_date,
    rotation_applies_to,
    set_program_start,
)
from routine_builder import duplicate_builtin, is_user_routine, routine_pk
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
)
from views.exercise_dialog import open_exercise_detail
from views.shared_ui import db_error_screen, dialog_width, plural

# View indices owned by main.py; named so the call sites read as intent.
VIEW_WORKOUT = 2
VIEW_ROUTINE_EDITOR = 7


def week_headline(pw: ProgramWeek) -> str:
    """`WEEK 5 OF 24`, degrading to `WEEK 5`, then to `THIS WEEK`.

    `total_weeks` is 0 when no phase declares a readable range — a half-built
    routine from the editor — and "of 0" would be worse than saying nothing.
    """
    if pw.week is None:
        return "THIS WEEK"
    return f"WEEK {pw.week} OF {pw.total_weeks}" if pw.total_weeks else f"WEEK {pw.week}"


def next_session(pw: ProgramWeek) -> tuple[int, str] | None:
    """The next training day left in this week, as (weekday index, label).

    None once the week has nothing left. It deliberately does not roll into next
    week: the row the rotation turns to depends on the phase that week belongs
    to, and guessing it here is the kind of confident wrong answer these two
    screens exist to stop making.
    """
    if pw.rotation is None:
        return None
    for i in range(((pw.today or date.today()).weekday()) + 1, len(pw.rotation)):
        if not is_rest_label(pw.rotation[i]):
            return i, pw.rotation[i]
    return None


def start_caveat(pw: ProgramWeek) -> str | None:
    """The sentence that keeps a guessed week from reading as a fact.

    `StartSource.FIRST_WORKOUT` means program_week inferred the start from the
    earliest logged session, which is right often and not always — `entrenos`
    has no routine column, so "first workout ever" may belong to a different
    routine entirely. Alex should be able to see the assumption and correct it,
    so it is printed, not hidden behind a tooltip.
    """
    if pw.start.certain or pw.start.day is None or not pw.start.known:
        return None
    return f"Assuming you started on {pw.start.day.isoformat()} — your first logged session."


def open_start_date_dialog(
    page: ft.Page, store: Storage, on_saved=None, initial: date | None = None
) -> None:
    """Ask when this routine started, and hand the answer to program_week.

    A typed ISO date, like the weigh-in dialog in views/profile.py: there is no
    DatePicker anywhere in this app and this is not the screen to introduce the
    only one. The two shortcuts cover the realistic answers — you are filling
    this in either in the week you started or in the one after.

    "This week" is `restart_date()`, i.e. this week's Monday rather than today,
    because a mid-week start spends a whole program week on the two or three
    days that are left. A date Alex types is stored exactly as typed: if he
    really did start on a Wednesday, that is the truth and program_week does the
    Monday anchoring.

    `initial` prefills the field — the caller passes it when a date already
    exists but does not apply here, so adopting it costs one tap instead of a
    retype from memory. `set_program_start` stamps the *active* routine onto the
    row, which is what makes that a new start rather than a shared one.
    """
    monday = restart_date()
    field = ft.TextField(
        label="Start date (YYYY-MM-DD)",
        value=(initial or monday).isoformat(),
        dense=True,
        color=C.text,
        border_color=C.border_strong,
        focused_border_color=C.accent,
        label_style=ft.TextStyle(color=C.text_secondary),
    )
    err = ft.Text("", size=11, color=C.danger)

    def fill(day: date):
        field.value = day.isoformat()
        err.value = ""
        page.update()

    def save(_):
        try:
            chosen = date.fromisoformat((field.value or "").strip())
        except ValueError:
            err.value = "Use YYYY-MM-DD"
            page.update()
            return
        # A future date is not refused — program_week reports it as SCHEDULED
        # and the card says "starts on …", which is a real thing to want. Only
        # something that is not a date is refused.
        set_program_start(store, chosen)
        page.close(dlg)
        if on_saved is not None:
            on_saved()
            return
        with contextlib.suppress(KeyError, TypeError, AttributeError):
            page.data["refresh_current"]()

    dlg = ft.AlertDialog(
        modal=False,
        bgcolor=C.bg_surface,
        title=ft.Text("Routine start date", size=16, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(
            content=ft.Column(
                [
                    # No width: the explanation is two sentences and a pinned
                    # 300 px box clipped the second one on a narrow phone. The
                    # Column is STRETCH so it wraps to the dialog instead.
                    ft.Text(
                        "The day you started week 1 of this routine. It is what "
                        "tells the app which week and which phase you are in.",
                        size=11,
                        color=C.text_secondary,
                    ),
                    field,
                    ft.Row(
                        [
                            ghost_button("This week", on_click=lambda _: fill(monday), expand=True),
                            ghost_button(
                                "Last week",
                                on_click=lambda _: fill(monday - timedelta(days=7)),
                                expand=True,
                            ),
                        ],
                        spacing=8,
                    ),
                    err,
                ],
                spacing=10,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            width=dialog_width(page),
            # No height at all. The old 210 px was sized around a 300 px-wide
            # paragraph; now that the paragraph wraps to the window, the number
            # of lines is not knowable here. Nothing scrolls in this dialog, so
            # letting it size to its content is both correct and shorter.
        ),
        actions=[
            ft.TextButton(
                "Cancel",
                on_click=lambda _: page.close(dlg),
                style=ft.ButtonStyle(color=C.text_secondary),
            ),
            ft.TextButton("Save", on_click=save, style=ft.ButtonStyle(color=C.accent)),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.open(dlg)


class PlanView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected_phase_idx: int | None = None
        self.subview = "exercises"  # "exercises" | "distribution"
        self.dist_week_idx = 0
        self._expanded_days: set[str] = set()
        self._week: ProgramWeek | None = None
        #: The exception that stopped this screen loading, if one did. Held
        #: rather than raised so `build()` can render a message instead of
        #: nothing — see `on_show`.
        self._error: Exception | None = None

    def on_show(self):
        # `current_program_week` reads the history, so it is answered once per
        # activation and held. Every re-render in main.py goes through
        # `navigate_to`, which calls this first, so the held answer is never
        # older than the screen showing it.
        #
        # It is also the one database call on this screen, so it is the one that
        # can fail — and `on_show()` runs *outside* `build()`, where an
        # exception takes the whole navigation down rather than one view. Caught
        # here, remembered, and rendered by `build()`.
        try:
            self._week = current_program_week(self.store)
            self._error = None
        except Exception as exc:  # database down, driver missing, anything
            self._week = None
            self._error = exc

    def _program_week(self) -> ProgramWeek:
        """The held answer, computed on demand if `on_show()` never ran.

        Tests build views directly, and so does anything that renders a screen
        without activating it.
        """
        if self._week is None:
            self._week = current_program_week(self.store)
        return self._week

    def handle_back(self) -> bool:
        if self.selected_phase_idx is not None:
            self.selected_phase_idx = None
            self.page.data["refresh_current"]()
            return True
        return False

    # ─────────────────────────────────────────────────────────
    def _select_phase(self, idx: int, subview: str = "exercises"):
        """Open a phase. On the phase you are actually in, on this week.

        Opening the distribution on row 0 was fine while it was a tab you went
        looking for; now that the week card links into it, landing on someone
        else's week would undo the point of the card.
        """
        routine = active_routine()
        self.selected_phase_idx = idx
        self.subview = subview
        self.dist_week_idx = (
            self._week_row_for_phase(self._program_week(), routine.phases[idx]) or 0
        )
        self.page.data["refresh_current"]()

    def _week_row_for_phase(self, pw: ProgramWeek, phase) -> int | None:
        """The rotation row this week occupies, but only inside its own phase.

        None everywhere else: "this week" is not a property of a phase you are
        merely browsing, and marking a row in phase 3 while you are in phase 1
        would be the wrong-day lie in a different costume. `rotation_index` is
        already None when the rotation does not describe the phase, so this only
        has to check that the phase is the one being looked at.
        """
        if pw.phase is None or pw.phase.id != phase.id:
            return None
        return pw.rotation_index

    def _back_to_list(self):
        self.selected_phase_idx = None
        self.page.data["refresh_current"]()

    def _set_subview(self, v: str):
        self.subview = v
        self.page.data["refresh_current"]()

    def _set_dist_week(self, i: int):
        self.dist_week_idx = i
        self.page.data["refresh_current"]()

    # ─────────────────────────────────────────────────────────
    def _phase_card(self, phase, idx: int, current: bool = False) -> ft.Container:
        header: list[ft.Control] = [
            ft.Text(
                f"PHASE {phase.id} · WK {phase.weeks}",
                size=10,
                color=phase_color(phase.id),
                weight=ft.FontWeight.W_900,
                expand=True,
            )
        ]
        if current:
            # The list is seven near-identical cards; without this you have to
            # do the arithmetic yourself to find the one you are standing in.
            header.append(
                ft.Container(
                    content=ft.Text(
                        "YOU ARE HERE", size=9, weight=ft.FontWeight.W_900, color=C.on_accent
                    ),
                    bgcolor=C.accent,
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                )
            )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(header, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(phase.name, size=18, weight=ft.FontWeight.W_900, color=C.text),
                    ft.Text(phase.subtitle, size=11, color=C.text_secondary),
                    ft.Row(
                        [
                            chip(phase.scheme),
                            chip("High freq." if phase.freq == "high" else "Low freq."),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(2 if current else 1, C.accent if current else C.border),
            border_radius=14,
            padding=14,
            margin=ft.margin.only(bottom=8),
            on_click=lambda _, i=idx: self._select_phase(i),
            ink=True,
        )

    # ── routines ─────────────────────────────────────────────
    def _open_editor(self, pk: int | None = None):
        """Into the routine editor, on `pk` if the host can open one directly.

        `edit_routine` is an optional hook: main.py holds the view instances, so
        only it can put the editor on a specific routine. Without it this still
        lands on the editor's library, which lists the same routine one tap away.
        """
        opener = self.page.data.get("edit_routine")
        if pk is not None and callable(opener):
            opener(pk)
            return
        self.page.data["navigate_to"](VIEW_ROUTINE_EDITOR)

    def _edit_active(self, _=None):
        self._open_editor(routine_pk(active_routine().id))

    def _duplicate(self, routine_id: str):
        """Copy a built-in and open the copy. The original is untouched.

        This is the honest path to owning a routine: nobody writes 24 weeks of
        periodisation from an empty screen, they change the two exercises they
        disagree with. `duplicate_builtin` already re-syncs `data.ROUTINES`.
        """
        self._open_editor(duplicate_builtin(self.store, routine_id))

    def _routine_chip(self, r, active_id: str) -> ft.Control:
        on = r.id == active_id
        set_routine = self.page.data["set_routine"]
        parts: list[ft.Control] = [
            ft.Text(
                r.name,
                size=11,
                weight=ft.FontWeight.W_800,
                color=C.accent if on else C.text_secondary,
            )
        ]
        if not is_user_routine(r.id):
            # The copy button sits on the template it copies. Its own on_click
            # keeps the tap from also switching the active routine — you can
            # fork a routine you have not adopted.
            parts.append(
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.CONTENT_COPY_OUTLINED,
                        size=13,
                        color=C.accent if on else C.text_muted,
                    ),
                    on_click=lambda _, rid=r.id: self._duplicate(rid),
                    ink=True,
                    border_radius=Radius.sm,
                    padding=2,
                    tooltip=f"Duplicate '{r.name}' into an editable routine",
                )
            )
        return ft.Container(
            content=ft.Row(parts, spacing=6, tight=True),
            bgcolor=C.accent_soft if on else C.bg_surface,
            border=ft.border.all(1, C.accent if on else C.border),
            border_radius=Radius.sm,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=(None if on else (lambda _, rid=r.id: set_routine(rid))),
            ink=not on,
        )

    def _routine_selector(self) -> ft.Control:
        active_id = active_routine().id
        return ft.Row(
            [self._routine_chip(r, active_id) for r in ROUTINES],
            spacing=6,
            wrap=True,
            run_spacing=6,
        )

    def _routine_actions(self) -> ft.Control:
        buttons: list[ft.Control] = []
        if is_user_routine(active_routine().id):
            buttons.append(
                ghost_button("Edit this routine", on_click=self._edit_active, expand=True)
            )
        buttons.append(
            ghost_button(
                "My routines",
                on_click=lambda _: self._open_editor(),
                expand=True,
                tooltip="Create, edit or delete your own routines",
            )
        )
        return ft.Row(buttons, spacing=Space.x2)

    # ── this week ────────────────────────────────────────────
    def _day_row(self, idx: int, label: str, is_today: bool = False) -> ft.Control:
        """One weekday of a week's plan. Shared by the week card and the tab.

        Flat rather than a card of its own: five stacked cards inside a card is
        a lot of border for five words, and both places that draw these rows
        already sit inside one.
        """
        rest = is_rest_label(label)
        trailing: ft.Control = (
            ft.Text("TODAY", size=9, weight=ft.FontWeight.W_900, color=C.accent)
            if is_today
            else ft.Container(width=0)
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text(
                            day_name(idx),
                            size=10,
                            weight=ft.FontWeight.W_800,
                            color=C.on_accent if is_today else C.text_secondary,
                        ),
                        bgcolor=C.accent if is_today else C.bg_sunken,
                        border_radius=6,
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        width=46,
                        alignment=ft.alignment.center,
                    ),
                    ft.Text(
                        label,
                        size=13,
                        color=C.text_muted if rest else C.text,
                        weight=ft.FontWeight.W_500 if rest else ft.FontWeight.W_700,
                        expand=True,
                    ),
                    trailing,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.accent_soft if is_today else None,
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=6, vertical=5),
        )

    def _week_card(self, pw: ProgramWeek) -> ft.Control:
        """The week you are in, at the top of the screen, before you ask.

        This is the whole point of the change: the distribution used to be a tab
        two taps in, so the answer to "what am I doing this week" lived where
        nobody looks. Everything it can say is stated here, and what it cannot
        say is stated too — the four `WeekStatus` values each get their own
        sentence rather than collapsing into "no data".
        """
        if pw.status is WeekStatus.UNKNOWN:
            return self._no_week_card(pw)
        if pw.status is WeekStatus.SCHEDULED:
            return self._scheduled_card(pw)
        if pw.status is WeekStatus.FINISHED:
            return self._finished_card(pw)

        phase = pw.phase
        if phase is None:
            # ACTIVE with no phase: the week fell in a gap between two
            # hand-written `Phase.weeks` ranges. Rare, and a routine-editor
            # mistake rather than a program state — say which week it is and
            # leave it at that.
            return card(
                ft.Text(week_headline(pw), size=10, weight=ft.FontWeight.W_900, color=C.accent),
                ft.Text(
                    "No phase covers this week", size=16, weight=ft.FontWeight.W_900, color=C.text
                ),
                muted_text("The phases of this routine leave a gap here. Check their week ranges."),
                border_color=C.warning,
                padding=12,
            )

        today_idx = (pw.today or date.today()).weekday()
        body: list[ft.Control]
        if pw.rotation is not None:
            body = [
                self._day_row(i, label, is_today=(i == today_idx))
                for i, label in enumerate(pw.rotation)
            ]
        else:
            # A known week whose phase does not pin sessions to weekdays. Naming
            # the sessions is still worth something; dealing them out Mon-to-Fri
            # is not — nothing in the routine prescribes that order.
            days = active_routine().days_for_phase(phase.id)
            body = [
                muted_text("This phase does not fix sessions to weekdays. It prescribes:"),
                ft.Container(height=Space.x1),
                ft.Row([chip(d.name) for d in days], wrap=True, spacing=6, run_spacing=6),
            ]

        footer: list[ft.Control] = []
        caveat = start_caveat(pw)
        if caveat:
            footer += [ft.Container(height=Space.x1), muted_text(caveat)]
        if pw.stale:
            footer += [ft.Container(height=Space.x1), self._stale_notice(pw)]

        return card(
            ft.Row(
                [
                    ft.Text(
                        week_headline(pw),
                        size=10,
                        weight=ft.FontWeight.W_900,
                        color=C.accent,
                        expand=True,
                    ),
                    ft.Text(
                        f"PHASE {phase.id}",
                        size=10,
                        weight=ft.FontWeight.W_900,
                        color=phase_color(phase.id),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(phase.name, size=18, weight=ft.FontWeight.W_900, color=C.text),
            ft.Container(height=Space.x1),
            *body,
            *footer,
            border_color=C.accent,
            padding=12,
            on_click=lambda _: self._open_current_phase(pw),
            ink=True,
            tooltip="Open this phase",
        )

    def _stale_notice(self, pw: ProgramWeek) -> ft.Control:
        """Weeks keep counting while you are away; say so, and offer the reset.

        program_week deliberately never re-times the program by itself (its
        decision 3): the number is calendar arithmetic and bending it silently
        would make the same day report two different weeks. So the honesty is
        here — the gap is named, and restarting is one tap and Alex's choice.
        """
        weeks = pw.weeks_idle
        return ft.Column(
            [
                ft.Text(
                    f"Nothing logged for {plural(weeks, 'week')}. The week number keeps counting "
                    "with the calendar, so it is ahead of your training.",
                    size=11,
                    color=C.warning,
                ),
                ft.Container(height=Space.x1),
                ghost_button(
                    "Restart the program this week",
                    on_click=lambda _: self._restart_program(),
                    expand=True,
                ),
            ],
            spacing=0,
            tight=True,
        )

    def _restart_program(self):
        """Re-date the program to this week's Monday. Alex's call, never ours."""
        set_program_start(self.store, restart_date())
        self._week = None
        self.page.data["refresh_current"]()

    def _set_start_date(self, initial: date | None = None):
        open_start_date_dialog(self.page, self.store, on_saved=self._reload, initial=initial)

    def _reload(self):
        # The dialog changed the stored date, so the held week is wrong until
        # `on_show()` runs again. Dropping it makes the refresh recompute even
        # if a future refresh path stops calling `on_show()`. The held error
        # goes with it, for the same reason: this is also the "try again"
        # button of the database-down card, and a remembered failure would
        # survive the retry that fixed it.
        self._week = None
        self._error = None
        self.page.data["refresh_current"]()

    def _no_week_card(self, pw: ProgramWeek) -> ft.Control:
        """No usable start date: say so, and offer every way out there is."""
        stale_date = pw.start.day if pw.start.source is StartSource.OTHER_ROUTINE else None
        body = (
            "A start date is stored, but it was saved for another routine, so it "
            "cannot say where you are in this one. Switching routines starts a new "
            "program."
            if stale_date
            else "Nothing here records when you started this routine, so the app "
            "cannot tell which week or phase you are in — and a guessed week would "
            "put you on the wrong session. Set the date, or just train: the first "
            "session you log dates the routine."
        )
        actions: list[ft.Control] = [
            ghost_button(
                "Set start date",
                on_click=lambda _, d=stale_date: self._set_start_date(d),
                expand=True,
            ),
            primary_button(
                "Start training",
                on_click=lambda _: self.page.data["navigate_to"](VIEW_WORKOUT),
                expand=True,
            ),
        ]
        extra: list[ft.Control] = []
        if stale_date:
            extra = [
                ft.Container(height=Space.x1),
                ghost_button(
                    f"Use {stale_date.isoformat()} here too",
                    on_click=lambda _, d=stale_date: self._adopt_start(d),
                    expand=True,
                ),
            ]
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.HELP_OUTLINE, color=C.warning, size=18),
                    ft.Text(
                        "Week unknown",
                        size=15,
                        weight=ft.FontWeight.W_900,
                        color=C.text,
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(body, size=11, color=C.text_secondary),
            ft.Container(height=Space.x1),
            ft.Row(actions, spacing=Space.x2),
            *extra,
            border_color=C.warning,
            padding=12,
        )

    def _adopt_start(self, day: date):
        """Re-save a date stored under another routine, against this one."""
        set_program_start(self.store, day)
        self._reload()

    def _scheduled_card(self, pw: ProgramWeek) -> ft.Control:
        """The start date is in a future week. Not started is not unknown."""
        day = pw.start.day
        return card(
            ft.Text("NOT STARTED YET", size=10, weight=ft.FontWeight.W_900, color=C.accent),
            ft.Text("Week 1 is ahead", size=18, weight=ft.FontWeight.W_900, color=C.text),
            ft.Text(
                f"This routine is set to start on {day.isoformat()}. The week and the "
                "distribution appear then."
                if day
                else "This routine is set to start in a later week.",
                size=11,
                color=C.text_secondary,
            ),
            ft.Container(height=Space.x1),
            ghost_button(
                "Change start date", on_click=lambda _: self._set_start_date(), expand=True
            ),
            border_color=C.border_strong,
            padding=12,
        )

    def _finished_card(self, pw: ProgramWeek) -> ft.Control:
        """Past the last week of the routine. A real state, not an error."""
        return card(
            ft.Text(week_headline(pw), size=10, weight=ft.FontWeight.W_900, color=C.accent),
            ft.Text("Routine finished", size=18, weight=ft.FontWeight.W_900, color=C.text),
            ft.Text(
                f"The program runs {plural(pw.total_weeks, 'week')} and this one is past the end. "
                "Start it again from this week, or pick another routine below.",
                size=11,
                color=C.text_secondary,
            ),
            ft.Container(height=Space.x1),
            ft.Row(
                [
                    ghost_button(
                        "Set start date", on_click=lambda _: self._set_start_date(), expand=True
                    ),
                    primary_button(
                        "Start again now", on_click=lambda _: self._restart_program(), expand=True
                    ),
                ],
                spacing=Space.x2,
            ),
            border_color=C.warning,
            padding=12,
        )

    def _open_current_phase(self, pw: ProgramWeek):
        """From the week card into the phase it belongs to.

        Onto Distribution when the phase has one: the card is a week, so the
        screen it opens should be the same week rather than a list of exercises
        the reader did not ask for.
        """
        routine = active_routine()
        phase_id = getattr(pw.phase, "id", None)
        idx = next((i for i, p in enumerate(routine.phases) if p.id == phase_id), None)
        if idx is None:
            return
        subview = "distribution" if pw.rotation_index is not None else "exercises"
        self._select_phase(idx, subview=subview)

    # ─────────────────────────────────────────────────────────
    def _phase_list(self, pw: ProgramWeek) -> ft.Control:
        routine = active_routine()
        current_phase_id = getattr(pw.phase, "id", None)
        return ft.Column(
            [
                ft.Text("Training Plan", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(height=Space.x2),
                self._week_card(pw),
                ft.Container(height=Space.x4),
                self._routine_selector(),
                ft.Container(height=Space.x1),
                muted_text("Tap a copy icon to fork a built-in routine and make it yours."),
                ft.Container(height=Space.x2),
                self._routine_actions(),
                ft.Container(height=Space.x3),
                ft.Text(routine.description, size=11, color=C.text_secondary),
                ft.Container(height=Space.x3),
                *[
                    self._phase_card(p, i, current=(p.id == current_phase_id))
                    for i, p in enumerate(routine.phases)
                ],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )

    # ─────────────────────────────────────────────────────────
    def _toggle_day(self, name: str):
        if name in self._expanded_days:
            self._expanded_days.remove(name)
        else:
            self._expanded_days.add(name)
        self.page.data["refresh_current"]()

    def _exercise_row(self, ex_raw: str) -> ft.Control:
        key = exercise_key(ex_raw)
        # `image_props`, not `image_for`: on the phone an assets-relative URL
        # resolves to nothing and the thumbnail is a silent grey square. See the
        # delivery note in exercise_images.py, and views/browse.py for the same
        # call with the same reasoning.
        thumb_props = image_props(key)
        has_detail = details_for(key) is not None

        thumb: ft.Control
        if thumb_props:
            thumb = ft.Container(
                content=ft.Image(
                    **thumb_props,
                    fit=ft.ImageFit.COVER,
                    width=44,
                    height=44,
                    # DECODE SMALL. `width`/`height` only scale the drawing; the
                    # source is an 850×567 photo, so without these a phase day
                    # of eight exercises decodes eight full bitmaps. 2× the
                    # display size covers a 2x-density screen.
                    cache_width=88,
                    cache_height=88,
                    # A frame that will not decode falls back to the same icon
                    # the no-image case uses, rather than an empty square that
                    # reads as a missing exercise.
                    error_content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=20),
                ),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            thumb = ft.Container(
                content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=20),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                alignment=ft.alignment.center,
            )

        # `expand`, not `width=250`. Routine strings carry their scheme —
        # "Behind-Neck Lat Pulldown [4×10-12]" — and 250 px was measured on a
        # 420 px window: on anything narrower the name lost its scheme, and on
        # anything wider it left a dead strip before the info icon.
        name_widget = ft.Container(
            content=ft.Text(
                ex_raw,
                size=12,
                color=C.text,
                weight=ft.FontWeight.W_500,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            expand=True,
            alignment=ft.alignment.center_left,
        )
        return ft.Container(
            content=ft.Row(
                [
                    thumb,
                    name_widget,
                    (
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=C.accent, size=16)
                        if has_detail
                        else ft.Container(width=16)
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=8,
            on_click=(lambda _, k=key: self._open_detail(k)) if has_detail else None,
            ink=has_detail,
        )

    def _day_tile(self, day) -> ft.Control:
        is_open = day.name in self._expanded_days
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        day.name,
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=C.accent if is_open else C.text,
                        expand=True,
                    ),
                    ft.Text(
                        f"{len(day.exercises)}",
                        size=11,
                        color=C.text_secondary,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Icon(
                        ft.Icons.KEYBOARD_ARROW_UP if is_open else ft.Icons.KEYBOARD_ARROW_DOWN,
                        color=C.accent if is_open else C.text_secondary,
                        size=18,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            on_click=lambda _, n=day.name: self._toggle_day(n),
            ink=True,
        )
        children: list[ft.Control] = [header]
        if is_open:
            children.append(
                ft.Container(
                    content=ft.Column(
                        [self._exercise_row(ex) for ex in day.exercises],
                        spacing=2,
                        tight=True,
                    ),
                    padding=ft.padding.only(left=6, right=6, bottom=8, top=0),
                )
            )
        return ft.Container(
            content=ft.Column(children, spacing=0, tight=True),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.accent if is_open else C.border),
            border_radius=12,
            margin=ft.margin.only(bottom=6),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    def _open_detail(self, key: str):
        open_exercise_detail(self.page, key)

    def _tab_button(self, label: str, key: str) -> ft.Container:
        active = self.subview == key
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_700,
                color=C.accent if active else C.text_secondary,
            ),
            bgcolor=C.accent_soft if active else C.bg_surface,
            border=ft.border.all(1, C.accent if active else C.border),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=lambda _, k=key: self._set_subview(k),
            ink=True,
        )

    def _distribution(self, pw: ProgramWeek, phase) -> ft.Control:
        """The three-week rotation, with this week marked.

        Kept as a tab rather than folded into the week card: the rotation is
        three different weeks and looking ahead to the next one is a real thing
        to want. What it lost is the job of *also* being the only place this
        week was written down — that is the card at the top of the screen now,
        and this opens on the current row instead of always on the first.
        """
        rotation = active_routine().week_rotation or []
        here = self._week_row_for_phase(pw, phase)
        week = rotation[self.dist_week_idx] if rotation else []
        # Today is only today on the week that is actually running.
        today_idx = (
            (pw.today or date.today()).weekday()
            if here is not None and here == self.dist_week_idx
            else None
        )

        week_tabs = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        f"WK {i + 1} · NOW" if i == here else f"WK {i + 1}",
                        size=11,
                        weight=ft.FontWeight.W_800,
                        color=C.accent if i == self.dist_week_idx else C.text_secondary,
                    ),
                    bgcolor=C.accent_soft if i == self.dist_week_idx else C.bg_surface,
                    border=ft.border.all(1, C.accent if i == self.dist_week_idx else C.border),
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=14, vertical=6),
                    on_click=lambda _, idx=i: self._set_dist_week(idx),
                    ink=True,
                )
                for i in range(len(rotation))
            ],
            spacing=6,
            wrap=True,
            run_spacing=6,
        )
        caption = (
            f"Week {self.dist_week_idx + 1} of this phase. The same three days rotate "
            "over five sessions, so each week starts on a different one."
        )
        return ft.Column(
            [
                week_tabs,
                ft.Container(height=Space.x2),
                muted_text(caption),
                ft.Container(height=Space.x2),
                card(
                    *[self._day_row(i, w, is_today=(i == today_idx)) for i, w in enumerate(week)],
                    padding=10,
                ),
            ],
            spacing=0,
            tight=True,
        )

    def _phase_detail(self, pw: ProgramWeek) -> ft.Control:
        idx = self.selected_phase_idx
        assert idx is not None
        routine = active_routine()
        phase = routine.phases[idx]
        days = routine.days_for_phase(phase.id)

        # Was `routine.week_rotation is not None and phase.id in (1, 2, 3)`, an
        # unexplained literal: right for CambiaTuFísico, meaningless for any
        # other routine, and silent about why those three ids. Same answer, now
        # derived — `rotation_applies_to` asks whether the rotation's labels
        # name day templates this phase actually has, which is true of phases
        # 1-3 (they share `DAYS_PHASE_1_3`) and of nothing else.
        rotates = rotation_applies_to(phase, routine)
        tabs_row: list[ft.Control] = [self._tab_button("Exercises", "exercises")]
        if rotates:
            tabs_row.append(self._tab_button("Distribution", "distribution"))

        body: ft.Control
        # `rotates` also guards the render: the subview survives a trip back to
        # the phase list, and a distribution with no tab to leave it by is a
        # dead end.
        if self.subview == "distribution" and rotates:
            body = self._distribution(pw, phase)
        else:
            body = ft.Column([self._day_tile(d) for d in days], spacing=6, tight=True)

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text("Phases", color=C.accent, size=12, weight=ft.FontWeight.W_700),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=lambda _: self._back_to_list(),
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                card(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    f"PHASE {phase.id}",
                                    size=10,
                                    weight=ft.FontWeight.W_900,
                                    color=C.on_accent,
                                ),
                                bgcolor=phase_color(phase.id),
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            ),
                            ft.Text(f"Wk {phase.weeks}", size=11, color=C.text_secondary),
                            *(
                                [
                                    ft.Text(
                                        f"· {week_headline(pw).lower()}",
                                        size=11,
                                        weight=ft.FontWeight.W_800,
                                        color=C.accent,
                                    )
                                ]
                                if getattr(pw.phase, "id", None) == phase.id
                                else []
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Text(phase.name, size=22, weight=ft.FontWeight.W_900, color=C.text),
                    ft.Text(
                        phase.subtitle,
                        size=12,
                        color=phase_color(phase.id),
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Container(height=6),
                    ft.Text(f"Sets: {phase.scheme}", size=12, color=C.text),
                    ft.Text(f"Rest: {phase.rest}", size=11, color=C.text_secondary),
                    ft.Container(height=6),
                    ft.Text(phase.notes, size=11, color=C.text_muted),
                ),
                ft.Container(height=12),
                ft.Row(tabs_row, spacing=6),
                ft.Container(height=10),
                body,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
            tight=True,
        )

    def build(self) -> ft.Control:
        # Held, not read: `current_program_week` queries the history, and
        # `build()` runs on every refresh. See `on_show`.
        try:
            if self._error is not None:
                raise self._error
            pw = self._program_week()
            if self.selected_phase_idx is None:
                return self._phase_list(pw)
            return self._phase_detail(pw)
        except Exception as exc:
            # A screen that renders nothing is indistinguishable from a crash,
            # and this one is opened in a gym to find out what today's session
            # is. Say why it is empty and offer the retry.
            return db_error_screen("Training Plan", exc, on_retry=self._reload)
