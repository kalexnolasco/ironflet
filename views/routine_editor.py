"""Routine editor — build your own, or fork one of the eight built-ins.

Modelled on how Hevy and Strong handle templates: the library lists what you
have, editing is one flat scrollable form (day → exercises → sets×reps), and
picking an exercise opens a searchable catalogue rather than a free-text box.
The one deliberate difference is the phase selector: this app's routines are
periodized, so a routine is phases first and days second.

Two screens, switched by `self.mode`, in line with how the rest of the app does
sub-navigation: state on the instance, `refresh_current()` to re-render,
`handle_back()` unwinding one level per press.

Nothing is written until Save. The editor mutates a `DraftRoutine` held here and
hands it whole to `save_draft()`; a write per keystroke on a database the
Telegram bot also reads would be both wasteful and impossible to cancel.
"""

from __future__ import annotations

import flet as ft

from data import EXERCISE_CATALOG, MUSCLE_GROUPS, active_routine
from routine_builder import (
    MAX_SETS,
    DraftDay,
    DraftExercise,
    DraftPhase,
    DraftRoutine,
    builtin_routines,
    delete_routine,
    duplicate_routine,
    ensure_tables,
    list_user_drafts,
    load_draft,
    move,
    new_draft,
    parse_exercise,
    save_draft,
    sync_user_routines,
    user_routine_id,
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


class RoutineEditorView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store

        self.mode = "list"  # "list" | "edit"
        self.draft: DraftRoutine | None = None
        self.phase_idx = 0
        self.error = ""

        # Exercise picker state. It survives the dialog on purpose: reopening the
        # picker lands on the muscle group you were last adding from.
        self._picker_group = MUSCLE_GROUPS[0]
        self._picker_query = ""

    # ── view contract ────────────────────────────────────────
    def on_show(self):
        ensure_tables(self.store)
        sync_user_routines(self.store)

    def handle_back(self) -> bool:
        if self.mode == "edit":
            self._close_editor()
            return True
        return False

    def build(self) -> ft.Control:
        if self.mode == "edit" and self.draft is not None:
            return self._render_editor()
        return self._render_library()

    # ── shared bits ──────────────────────────────────────────
    def _refresh(self):
        self.page.data["refresh_current"]()

    def _icon_btn(self, icon: str, tooltip: str, on_click, color: str | None = None):
        return ft.IconButton(
            icon=icon,
            icon_color=color or C.text_muted,
            icon_size=18,
            tooltip=tooltip,
            on_click=on_click,
            padding=0,
            width=32,
            height=32,
        )

    def _field(self, value: str, on_change, hint: str = "", width=None, expand=False, **kw):
        return ft.TextField(
            value=value,
            hint_text=hint,
            bgcolor=C.bg_sunken,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            hint_style=ft.TextStyle(color=C.text_muted),
            text_size=13,
            height=42,
            width=width,
            expand=expand,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            on_change=on_change,
            **kw,
        )

    def _back_row(self, label: str, on_click) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                    ft.Text(label, color=C.accent, size=12, weight=ft.FontWeight.W_700),
                ],
                spacing=4,
                tight=True,
            ),
            on_click=on_click,
            padding=ft.padding.symmetric(vertical=6),
            ink=True,
        )

    # ── library ──────────────────────────────────────────────
    def _open_new(self, _=None):
        self.draft = new_draft()
        self.phase_idx = 0
        self.error = ""
        self.mode = "edit"
        self._refresh()

    def open_routine(self, pk: int):
        """Public entry point, used by `page.data["edit_routine"]`.

        Plan sends the user straight into a routine; without this it would have
        to reach into a private method to do it.
        """
        self._open_existing(pk)

    def _open_existing(self, pk: int):
        draft = load_draft(self.store, pk)
        if draft is None:  # deleted from another session
            sync_user_routines(self.store)
            self._refresh()
            return
        self.draft = draft
        self.phase_idx = 0
        self.error = ""
        self.mode = "edit"
        self._refresh()

    def _close_editor(self):
        self.mode = "list"
        self.draft = None
        self.error = ""
        self._refresh()

    def _duplicate(self, routine_id: str):
        pk = duplicate_routine(self.store, routine_id)
        self._open_existing(pk)

    def _activate(self, routine_id: str):
        """Make it the routine the rest of the app shows."""
        setter = self.page.data.get("set_routine")
        if setter:
            setter(routine_id)
        else:  # standalone use (tests): at least keep data.py consistent
            from data import set_active_routine

            set_active_routine(routine_id)
            self.store.set_pref("routine", routine_id)
        self._refresh()

    def _confirm_delete(self, pk: int, name: str):
        def do_delete(_):
            self.page.close(dlg)
            delete_routine(self.store, pk)
            self._refresh()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text("Delete routine", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Text(
                f'"{name}" and all its days will be removed. Logged workouts are not affected.',
                size=12,
                color=C.text_secondary,
            ),
            actions=[
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                ft.TextButton("Delete", on_click=do_delete, style=ft.ButtonStyle(color=C.danger)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _user_routine_card(self, draft: DraftRoutine) -> ft.Control:
        assert draft.pk is not None
        rid = user_routine_id(draft.pk)
        is_active = active_routine().id == rid
        n_days, n_ex = draft.day_count(), draft.exercise_count()

        header = ft.Row(
            [
                ft.Text(
                    draft.name,
                    size=15,
                    weight=ft.FontWeight.W_800,
                    color=C.text,
                    expand=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                chip("Active", color=C.on_accent, bg=C.accent) if is_active else ft.Container(),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        )
        meta = muted_text(
            f"{len(draft.phases)} phase{'s' if len(draft.phases) != 1 else ''} · "
            f"{n_days} day{'s' if n_days != 1 else ''} · {n_ex} exercises"
            + (f" · from {draft.source}" if draft.source else "")
        )
        actions = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        "Use" if not is_active else "In use",
                        size=11,
                        weight=ft.FontWeight.W_800,
                        color=C.text_muted if is_active else C.accent,
                    ),
                    border=ft.border.all(1, C.border if is_active else C.accent),
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    on_click=(None if is_active else (lambda _, r=rid: self._activate(r))),
                    ink=not is_active,
                ),
                ft.Container(expand=True),
                self._icon_btn(
                    ft.Icons.EDIT_OUTLINED,
                    "Edit",
                    lambda _, pk=draft.pk: self._open_existing(pk),
                    C.accent,
                ),
                self._icon_btn(
                    ft.Icons.COPY_ALL_OUTLINED,
                    "Duplicate",
                    lambda _, r=rid: self._duplicate(r),
                ),
                self._icon_btn(
                    ft.Icons.DELETE_OUTLINE,
                    "Delete",
                    lambda _, pk=draft.pk, n=draft.name: self._confirm_delete(pk, n),
                    C.danger,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )
        return card(
            header,
            meta,
            ft.Container(height=Space.x1),
            actions,
            padding=Space.x3,
            margin=ft.margin.only(bottom=Space.x2),
            border_color=C.accent if is_active else None,
        )

    def _builtin_row(self, routine) -> ft.Control:
        return card(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                routine.name, size=13, weight=ft.FontWeight.W_700, color=C.text
                            ),
                            muted_text(routine.description),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self._icon_btn(
                        ft.Icons.CONTENT_COPY,
                        "Duplicate and edit",
                        lambda _, r=routine.id: self._duplicate(r),
                        C.accent,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Space.x2,
            ),
            padding=Space.x3,
            margin=ft.margin.only(bottom=Space.x2),
        )

    def _render_library(self) -> ft.Control:
        drafts = list_user_drafts(self.store)

        mine: list[ft.Control]
        if drafts:
            mine = [self._user_routine_card(d) for d in drafts]
        else:
            mine = [
                card(
                    ft.Text(
                        "No routines of your own yet.",
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=C.text,
                    ),
                    muted_text(
                        "Duplicate the one you already follow and change what you "
                        "disagree with — it is faster than starting from nothing."
                    ),
                    padding=Space.x4,
                    margin=ft.margin.only(bottom=Space.x2),
                )
            ]

        return ft.Column(
            [
                ft.Text("Routines", size=22, weight=ft.FontWeight.W_900, color=C.text),
                muted_text("Your own routines sit next to the built-in ones."),
                ft.Container(height=Space.x3),
                primary_button(
                    "New routine", on_click=self._open_new, icon=ft.Icons.ADD, expand=True
                ),
                ft.Container(height=Space.x4),
                section_title("Yours"),
                ft.Container(height=Space.x2),
                *mine,
                ft.Container(height=Space.x3),
                section_title("Start from a template"),
                muted_text("Makes an editable copy. The original stays untouched."),
                ft.Container(height=Space.x2),
                *[self._builtin_row(r) for r in builtin_routines()],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )

    # ── editor: phases ───────────────────────────────────────
    def _phase(self) -> DraftPhase:
        assert self.draft is not None
        self.phase_idx = max(0, min(self.phase_idx, len(self.draft.phases) - 1))
        return self.draft.phases[self.phase_idx]

    def _add_phase(self, _=None):
        assert self.draft is not None
        n = len(self.draft.phases) + 1
        self.draft.phases.append(DraftPhase(name=f"Phase {n}", days=[DraftDay(name="Day 1")]))
        self.phase_idx = n - 1
        self._refresh()

    def _remove_phase(self, _=None):
        assert self.draft is not None
        if len(self.draft.phases) <= 1:
            self.error = "A routine needs at least one phase."
            self._refresh()
            return
        self.draft.phases.pop(self.phase_idx)
        self.phase_idx = max(0, self.phase_idx - 1)
        self._refresh()

    def _select_phase(self, idx: int):
        self.phase_idx = idx
        self._refresh()

    def _phase_tabs(self) -> ft.Control:
        assert self.draft is not None
        tabs: list[ft.Control] = []
        for i, p in enumerate(self.draft.phases):
            on = i == self.phase_idx
            tabs.append(
                ft.Container(
                    content=ft.Text(
                        p.name or f"Phase {i + 1}",
                        size=11,
                        weight=ft.FontWeight.W_800,
                        color=C.accent if on else C.text_secondary,
                    ),
                    bgcolor=C.accent_soft if on else C.bg_surface,
                    border=ft.border.all(1, C.accent if on else C.border),
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    on_click=lambda _, idx=i: self._select_phase(idx),
                    ink=True,
                )
            )
        tabs.append(
            ft.Container(
                content=ft.Icon(ft.Icons.ADD, size=14, color=C.text_secondary),
                border=ft.border.all(1, C.border_strong),
                border_radius=Radius.sm,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                on_click=self._add_phase,
                tooltip="Add phase",
                ink=True,
            )
        )
        return ft.Row(tabs, spacing=6, wrap=True, run_spacing=6)

    # ── editor: days ─────────────────────────────────────────
    def _add_day(self, _=None):
        phase = self._phase()
        phase.days.append(DraftDay(name=f"Day {len(phase.days) + 1}"))
        self._refresh()

    def _remove_day(self, idx: int):
        phase = self._phase()
        if 0 <= idx < len(phase.days):
            phase.days.pop(idx)
            self._refresh()

    def _move_day(self, idx: int, delta: int):
        if move(self._phase().days, idx, delta):
            self._refresh()

    def _remove_exercise(self, day_idx: int, ex_idx: int):
        day = self._phase().days[day_idx]
        if 0 <= ex_idx < len(day.exercises):
            day.exercises.pop(ex_idx)
            self._refresh()

    def _move_exercise(self, day_idx: int, ex_idx: int, delta: int):
        if move(self._phase().days[day_idx].exercises, ex_idx, delta):
            self._refresh()

    def _add_exercise(self, day_idx: int, name: str) -> None:
        """Append a catalogue exercise to a day, pre-filled with the phase scheme.

        `parse_exercise` does the naming too, so a name carrying a scheme or a
        star (which is what data.py's own strings look like) lands as the
        canonical key rather than as a second, never-matching exercise.
        """
        phase = self._phase()
        if not (0 <= day_idx < len(phase.days)) or not (name or "").strip():
            return
        phase.days[day_idx].exercises.append(parse_exercise(name, phase.scheme))

    def _exercise_row(self, day_idx: int, ex_idx: int, ex: DraftExercise) -> ft.Control:
        def set_sets(e):
            raw = (e.control.value or "").strip()
            # Ignore anything unparseable instead of fighting the user mid-typing;
            # save_draft() clamps whatever survives.
            if raw.isdigit():
                ex.sets = max(1, min(int(raw), MAX_SETS))

        def set_reps(e):
            ex.reps = (e.control.value or "").strip()[:40]

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        ex.name,
                        size=12,
                        color=C.text,
                        weight=ft.FontWeight.W_600,
                        expand=True,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    self._field(str(ex.sets), set_sets, width=42, text_align=ft.TextAlign.CENTER),
                    ft.Text("×", size=12, color=C.text_muted),
                    self._field(
                        ex.reps, set_reps, hint="reps", width=64, text_align=ft.TextAlign.CENTER
                    ),
                    self._icon_btn(
                        ft.Icons.KEYBOARD_ARROW_UP,
                        "Move up",
                        lambda _, d=day_idx, i=ex_idx: self._move_exercise(d, i, -1),
                    ),
                    self._icon_btn(
                        ft.Icons.KEYBOARD_ARROW_DOWN,
                        "Move down",
                        lambda _, d=day_idx, i=ex_idx: self._move_exercise(d, i, 1),
                    ),
                    self._icon_btn(
                        ft.Icons.CLOSE,
                        "Remove",
                        lambda _, d=day_idx, i=ex_idx: self._remove_exercise(d, i),
                        C.danger,
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=Space.x2, vertical=2),
        )

    def _day_card(self, day_idx: int, day: DraftDay) -> ft.Control:
        def set_name(e):
            day.name = e.control.value or ""

        header = ft.Row(
            [
                self._field(day.name, set_name, hint="Day name", expand=True),
                self._icon_btn(
                    ft.Icons.KEYBOARD_ARROW_UP,
                    "Move up",
                    lambda _, i=day_idx: self._move_day(i, -1),
                ),
                self._icon_btn(
                    ft.Icons.KEYBOARD_ARROW_DOWN,
                    "Move down",
                    lambda _, i=day_idx: self._move_day(i, 1),
                ),
                self._icon_btn(
                    ft.Icons.DELETE_OUTLINE,
                    "Delete day",
                    lambda _, i=day_idx: self._remove_day(i),
                    C.danger,
                ),
            ],
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        rows: list[ft.Control] = [
            self._exercise_row(day_idx, i, ex) for i, ex in enumerate(day.exercises)
        ]
        if not rows:
            rows = [
                ft.Container(
                    content=muted_text("No exercises yet."),
                    padding=ft.padding.symmetric(horizontal=Space.x2, vertical=Space.x2),
                )
            ]

        return card(
            header,
            ft.Container(height=Space.x1),
            *rows,
            ft.Container(height=Space.x1),
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ADD, size=14, color=C.accent),
                        ft.Text(
                            "Add exercise", size=12, weight=ft.FontWeight.W_700, color=C.accent
                        ),
                    ],
                    spacing=4,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                border=ft.border.all(1, C.border_strong),
                border_radius=Radius.sm,
                padding=ft.padding.symmetric(vertical=8),
                on_click=lambda _, i=day_idx: self._open_picker(i),
                ink=True,
            ),
            padding=Space.x3,
            margin=ft.margin.only(bottom=Space.x2),
        )

    # ── editor: exercise picker ──────────────────────────────
    def _open_picker(self, day_idx: int):
        """Catalogue dialog: group filter + search, the Hevy/Strong pattern.

        The list is mutated in place rather than re-rendered through
        `refresh_current()` — that rebuilds the page underneath the dialog and
        the search box would lose focus on every character.
        """
        self._picker_query = ""
        results = ft.ListView(spacing=0, padding=0, expand=True)
        group_row = ft.Row([], spacing=6, wrap=True, run_spacing=6)

        def add(name: str):
            self._add_exercise(day_idx, name)
            self.page.close(dlg)
            self._refresh()

        def matches() -> list[str]:
            q = self._picker_query.strip().lower()
            if not q:
                return list(EXERCISE_CATALOG.get(self._picker_group, []))
            # A search cuts across groups, like both apps do. dict.fromkeys
            # de-duplicates in order: a few exercises are filed under two groups
            # ("Close-Grip Bench Press" is chest and triceps) and would show up
            # twice otherwise.
            return list(
                dict.fromkeys(
                    n for names in EXERCISE_CATALOG.values() for n in names if q in n.lower()
                )
            )

        def render_results():
            results.controls = [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(n, size=13, color=C.text, expand=True),
                            ft.Icon(ft.Icons.ADD, size=16, color=C.accent),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=Space.x2, vertical=10),
                    border=ft.border.only(bottom=ft.BorderSide(1, C.border)),
                    on_click=lambda _, name=n: add(name),
                    ink=True,
                )
                for n in matches()
            ] or [ft.Container(content=muted_text("Nothing matches that."), padding=Space.x3)]

        def render_groups():
            def pick(g: str):
                self._picker_group = g
                self._picker_query = ""
                search.value = ""
                render_groups()
                render_results()
                self.page.update()

            group_row.controls = [
                ft.Container(
                    content=ft.Text(
                        g,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color=C.accent if g == self._picker_group else C.text_secondary,
                    ),
                    bgcolor=C.accent_soft if g == self._picker_group else C.bg_sunken,
                    border=ft.border.all(1, C.accent if g == self._picker_group else C.border),
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    on_click=lambda _, gg=g: pick(gg),
                    ink=True,
                )
                for g in MUSCLE_GROUPS
            ]

        def on_search(e):
            self._picker_query = e.control.value or ""
            render_results()
            self.page.update()

        search = self._field("", on_search, hint="Search exercises", expand=True)
        render_groups()
        render_results()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text("Add exercise", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(
                    [search, group_row, ft.Container(height=Space.x1), results],
                    spacing=Space.x2,
                    tight=False,
                ),
                width=340,
                height=460,
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    # ── editor: save ─────────────────────────────────────────
    def _save(self, _=None):
        assert self.draft is not None
        draft = self.draft
        if not (draft.name or "").strip():
            self.error = "Give the routine a name."
            self._refresh()
            return
        if draft.exercise_count() == 0:
            self.error = "Add at least one exercise before saving."
            self._refresh()
            return

        was_new = draft.pk is None
        pk = save_draft(self.store, draft)
        rid = user_routine_id(pk)
        self.mode = "list"
        self.draft = None
        self.error = ""
        if was_new and self.page.data.get("set_routine"):
            # A routine you just built is almost certainly the one you want to
            # train next; activating it saves a trip to the Plan tab.
            self._activate(rid)
        else:
            self._refresh()

    def _render_editor(self) -> ft.Control:
        draft = self.draft
        assert draft is not None
        phase = self._phase()

        def set_name(e):
            draft.name = e.control.value or ""

        def set_desc(e):
            draft.description = e.control.value or ""

        def set_weeks(e):
            phase.weeks = e.control.value or ""

        def set_scheme(e):
            phase.scheme = e.control.value or ""

        def set_rest(e):
            phase.rest = e.control.value or ""

        def set_phase_name(e):
            phase.name = e.control.value or ""

        header = [
            self._back_row("Routines", lambda _: self._close_editor()),
            ft.Text(
                "Edit routine" if draft.pk else "New routine",
                size=22,
                weight=ft.FontWeight.W_900,
                color=C.text,
            ),
            ft.Container(height=Space.x2),
            self._field(draft.name, set_name, hint="Routine name"),
            ft.Container(height=Space.x2),
            self._field(draft.description, set_desc, hint="Description (optional)"),
            ft.Container(height=Space.x4),
            section_title("Phases"),
            muted_text("Blocks of weeks. One is fine if you do not periodize."),
            ft.Container(height=Space.x2),
            self._phase_tabs(),
            ft.Container(height=Space.x3),
            card(
                ft.Row(
                    [
                        self._field(phase.name, set_phase_name, hint="Phase name", expand=True),
                        self._icon_btn(
                            ft.Icons.DELETE_OUTLINE,
                            "Delete phase",
                            self._remove_phase,
                            C.danger,
                        ),
                    ],
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=Space.x1),
                ft.Row(
                    [
                        self._field(phase.weeks, set_weeks, hint="Weeks", expand=True),
                        self._field(phase.scheme, set_scheme, hint="Sets scheme", expand=True),
                        self._field(phase.rest, set_rest, hint="Rest", expand=True),
                    ],
                    spacing=Space.x2,
                ),
                muted_text("Scheme and rest are shown in the Plan tab, e.g. 4×8-10 · 90s."),
                padding=Space.x3,
                margin=ft.margin.only(bottom=Space.x3),
            ),
            section_title("Days"),
            ft.Container(height=Space.x2),
        ]

        days = [self._day_card(i, d) for i, d in enumerate(phase.days)]

        footer: list[ft.Control] = [
            ghost_button("Add day", on_click=self._add_day, expand=True),
            ft.Container(height=Space.x4),
        ]
        if self.error:
            footer.append(ft.Text(self.error, size=12, color=C.danger, weight=ft.FontWeight.W_700))
            footer.append(ft.Container(height=Space.x2))
        footer.append(
            ft.Row(
                [
                    ghost_button("Cancel", on_click=lambda _: self._close_editor(), expand=True),
                    primary_button("Save routine", on_click=self._save, expand=True),
                ],
                spacing=Space.x2,
            )
        )
        footer.append(ft.Container(height=Space.x4))

        return ft.Column(
            [*header, *days, *footer],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )
