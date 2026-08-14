"""History: weekly muscle volume, exercise records and progression."""

from __future__ import annotations

import flet as ft

from analytics import (
    PRKind,
    Record,
    best_e1rm,
    e1rm_progression,
    personal_records,
    sets_per_muscle_group,
    volume,
)
from components.charts import bar_chart
from set_types import SetType, set_type_of, short_label_for, warmup_sets, working_sets
from storage import Storage
from theme import (
    C,
    Radius,
    card,
    chip,
    muted_text,
    section_title,
)

#: Four weeks is what fits as a chip row on a 420 px screen, and it is long
#: enough to see a mesocycle's volume ramp without scrolling sideways.
MUSCLE_WEEKS = 4
#: Bars beyond this turn the card into a wall; the tail is always noise anyway.
MAX_MUSCLE_BARS = 8
#: Widest a muscle bar may draw, leaving room for its label and value.
BAR_MAX_WIDTH = 150

#: One chart at a time. Three stacked charts on a phone means none get read.
CHART_KINDS: tuple[tuple[str, str], ...] = (
    ("e1rm", "Est. 1RM"),
    ("weight", "Max kg"),
    ("volume", "Volume"),
)

#: Tile-width labels for the three records. `analytics.PR_LABELS` is the prose
#: version and does not fit in a third of a phone screen.
PR_TILE_LABELS: dict[PRKind, str] = {
    PRKind.E1RM: "Est. 1RM",
    PRKind.MAX_WEIGHT: "Heaviest",
    PRKind.SESSION_VOLUME: "Session vol",
}
PR_BADGES: dict[PRKind, str] = {
    PRKind.E1RM: "1RM",
    PRKind.MAX_WEIGHT: "kg",
    PRKind.SESSION_VOLUME: "vol",
}


def _fmt(value: float) -> str:
    """Compact number for a tile: 12345 → 12.3k."""
    if abs(value) >= 10000:
        return f"{value / 1000:.1f}k"
    return f"{round(value, 1):g}"


def _week_label(weeks_back: int) -> str:
    """ISO week keys ("2026-W33") mean nothing at a glance; offsets do."""
    return "This week" if weeks_back == 0 else f"−{weeks_back}w"


def _sessions_label(count: int) -> str:
    return "1 session" if count == 1 else f"{count} sessions"


def _set_label(one_set: dict) -> str:
    """A set as text. Bodyweight work is logged at 0 kg — say "8 reps"."""
    weight = one_set.get("weight") or 0
    reps = one_set.get("reps") or 0
    return f"{weight:g}kg × {reps}" if weight > 0 else f"{reps} reps"


class HistoryView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected: str | None = None
        self.chart_kind: str = "e1rm"
        self.weeks_back: int = 0

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        if self.selected is not None:
            self.selected = None
            self.page.data["refresh_current"]()
            return True
        return False

    def _select(self, name: str):
        self.selected = name
        # The headline metric is the same for every exercise, so the detail
        # always opens on it rather than on whatever was last inspected.
        self.chart_kind = "e1rm"
        self.page.data["refresh_current"]()

    def _back_to_list(self, _=None):
        self.selected = None
        self.page.data["refresh_current"]()

    def _set_chart(self, kind: str):
        self.chart_kind = kind
        self.page.data["refresh_current"]()

    def _set_week(self, weeks_back: int):
        self.weeks_back = weeks_back
        self.page.data["refresh_current"]()

    # ── weekly muscle volume ─────────────────────────────────
    def _muscle_bar(self, name: str, sets: float, top: float) -> ft.Control:
        width = max(4, int(BAR_MAX_WIDTH * (sets / top))) if top else 4
        return ft.Row(
            [
                ft.Text(
                    name,
                    size=10,
                    color=C.text_secondary,
                    width=66,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Container(
                    width=width,
                    height=8,
                    bgcolor=C.chart_bar,
                    border_radius=Radius.pill,
                ),
                ft.Text(f"{sets:g}", size=10, color=C.text_muted),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _muscle_card(self, entries) -> ft.Control:
        mv = sets_per_muscle_group(entries, MUSCLE_WEEKS, coarse=True)
        # `weeks` runs oldest → newest, so the current week is the last one.
        idx = max(0, len(mv.weeks) - 1 - self.weeks_back)
        week = mv.by_week[mv.weeks[idx]]

        chips = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        _week_label(back),
                        size=10,
                        weight=ft.FontWeight.W_700,
                        color=C.on_accent if back == self.weeks_back else C.text_secondary,
                    ),
                    bgcolor=C.accent if back == self.weeks_back else C.bg_sunken,
                    border_radius=Radius.pill,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    on_click=lambda _, b=back: self._set_week(b),
                    ink=True,
                )
                for back in range(len(mv.weeks))
            ],
            spacing=6,
            wrap=True,
        )

        rows: list[ft.Control] = []
        if week:
            ranked = sorted(week.items(), key=lambda kv: kv[1], reverse=True)[:MAX_MUSCLE_BARS]
            top = ranked[0][1]
            rows = [self._muscle_bar(m, v, top) for m, v in ranked]
        else:
            rows = [muted_text("No working sets logged this week", size=11)]

        # The unresolved keys are counted over the whole window, not the
        # selected week — say so instead of letting them read as this week's.
        notes: list[ft.Control] = []
        if mv.unattributed:
            names = ", ".join(list(mv.unattributed)[:2])
            extra = len(mv.unattributed) - 2
            if extra > 0:
                names += f" +{extra}"
            notes.append(
                ft.Text(
                    f"{mv.unattributed_sets} sets unmapped in {MUSCLE_WEEKS}w ({names})",
                    size=10,
                    color=C.warning,
                    max_lines=2,
                )
            )
        if mv.partial:
            notes.append(
                ft.Text(
                    f"{len(mv.partial)} combos only partly attributed",
                    size=10,
                    color=C.text_muted,
                    max_lines=2,
                )
            )

        return card(
            ft.Row(
                [
                    section_title("Weekly sets by muscle"),
                    ft.Text(f"{MUSCLE_WEEKS} weeks", size=10, color=C.text_muted),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            muted_text("Primary muscle counts 1 set, secondary ½", size=10),
            ft.Container(height=6),
            chips,
            ft.Container(height=8),
            *rows,
            *([ft.Container(height=6), *notes] if notes else []),
            padding=14,
            margin=ft.margin.only(bottom=12),
        )

    # ── list ─────────────────────────────────────────────────
    def _empty(self) -> ft.Control:
        return ft.Column(
            [
                ft.Text("History & Progress", size=22, weight=ft.FontWeight.W_900, color=C.text),
                muted_text("Tap an exercise to see records and progression"),
                ft.Container(height=20),
                card(
                    ft.Text("📭", size=28, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "Start training to see your progress",
                        size=12,
                        color=C.text_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=24,
                    alignment=ft.alignment.center,
                ),
            ],
            expand=True,
            spacing=0,
            tight=True,
        )

    def _list(self) -> ft.Control:
        summary = self.store.get_exercise_summary()
        if not summary:
            return self._empty()

        entries = self.store.get_all()
        # One pass for every exercise's best estimated 1RM: cheaper than asking
        # `personal_records` per exercise, and it is all the list needs.
        best_by_exercise: dict[str, float] = {}
        for e in entries:
            value = best_e1rm(e.sets)
            if value is not None and value > best_by_exercise.get(e.exercise, 0.0):
                best_by_exercise[e.exercise] = value

        items = []
        for ex in summary:
            e1rm = best_by_exercise.get(ex["name"])
            subtitle = f"{_sessions_label(ex['count'])} · {ex['last_date']}"
            if ex["max_weight"]:
                # Bodyweight exercises are stored at 0 kg; "max 0kg" is noise.
                subtitle += f" · max {ex['max_weight']:g}kg"
            items.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        ex["name"],
                                        size=13,
                                        weight=ft.FontWeight.W_700,
                                        color=C.text,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(
                                        subtitle,
                                        size=10,
                                        color=C.text_muted,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        _fmt(e1rm) if e1rm else "—",
                                        size=16,
                                        color=C.accent,
                                        weight=ft.FontWeight.W_900,
                                    ),
                                    ft.Text("est. 1RM", size=9, color=C.text_muted),
                                ],
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=C.bg_surface,
                    border=ft.border.all(1, C.border),
                    border_radius=Radius.lg,
                    padding=12,
                    margin=ft.margin.only(bottom=6),
                    on_click=lambda _, n=ex["name"]: self._select(n),
                    ink=True,
                )
            )

        return ft.Column(
            [
                ft.Text("History & Progress", size=22, weight=ft.FontWeight.W_900, color=C.text),
                muted_text("Tap an exercise to see records and progression"),
                ft.Container(height=10),
                self._muscle_card(entries),
                section_title("Exercises"),
                ft.Container(height=6),
                *items,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    # ── detail ───────────────────────────────────────────────
    def _pr_tile(self, kind: PRKind, record: Record | None, unit: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        _fmt(record.value) if record else "—",
                        size=16,
                        weight=ft.FontWeight.W_900,
                        color=C.accent if record else C.text_muted,
                    ),
                    ft.Text(unit, size=8, color=C.text_muted),
                    ft.Text(
                        PR_TILE_LABELS[kind],
                        size=9,
                        weight=ft.FontWeight.W_700,
                        color=C.text_secondary,
                    ),
                    ft.Text(record.date if record else "no data", size=8, color=C.text_muted),
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=6, vertical=10),
            expand=True,
        )

    def _chart_chip(self, kind: str, label: str) -> ft.Control:
        active = kind == self.chart_kind
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_700,
                color=C.on_accent if active else C.text_secondary,
            ),
            bgcolor=C.accent if active else C.bg_sunken,
            border_radius=Radius.pill,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=lambda _, k=kind: self._set_chart(k),
            ink=True,
        )

    def _chart_data(self, hist, name: str) -> tuple[list[float], list[str], str]:
        if self.chart_kind == "e1rm":
            points = e1rm_progression(hist, name)
            return (
                [p["e1rm"] for p in points],
                [p["date"][5:] for p in points],  # MM-DD
                C.accent,
            )
        labels = [h.date[5:] for h in hist]
        if self.chart_kind == "weight":
            values = [
                max((s.get("weight") or 0 for s in working_sets(h.sets)), default=0) for h in hist
            ]
            return values, labels, C.accent_2
        return [volume(h.sets) for h in hist], labels, C.chart_bar

    def _session_card(self, h, badges: list[str]) -> ft.Control:
        set_chips = []
        for s in h.sets:
            kind = set_type_of(s)
            text = _set_label(s)
            if kind is not SetType.NORMAL:
                text = f"{short_label_for(kind)} · {text}"
            if s.get("rir") is not None:
                text += f" · RIR {s['rir']:g}"
            warmup = kind is SetType.WARMUP
            set_chips.append(
                chip(
                    text,
                    color=C.text_muted if warmup else C.accent,
                    bg=C.bg_page if warmup else None,
                )
            )

        header = [ft.Text(h.date, size=11, color=C.accent, weight=ft.FontWeight.W_700)]
        for badge in badges:
            header.append(
                ft.Container(
                    content=ft.Text(
                        f"🏆 {badge}", size=9, weight=ft.FontWeight.W_700, color=C.success
                    ),
                    bgcolor=C.bg_sunken,
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                )
            )

        working = working_sets(h.sets)
        plural = "" if len(working) == 1 else "s"
        summary = f"{len(working)} set{plural} · {_fmt(volume(h.sets))} kg"
        # Counted, not subtracted: `working_sets` also drops malformed rows,
        # which are not warm-ups.
        warmups = len(warmup_sets(h.sets))
        if warmups:
            summary += f" · {warmups} warm-up"

        return card(
            ft.Row(
                [
                    ft.Row(header, spacing=4, tight=True, wrap=True, run_spacing=2),
                    ft.Text(h.muscle_group, size=10, color=C.text_secondary),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Text(summary, size=10, color=C.text_muted),
            ft.Row(set_chips, wrap=True, spacing=6, run_spacing=4),
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    def _detail(self) -> ft.Control:
        name = self.selected
        assert name
        hist = self.store.get_exercise_history(name)
        records = personal_records(hist, name)
        values, labels, color = self._chart_data(hist, name)

        # A session is flagged only for the records it actually holds — the old
        # 🏆 fired on every set matching the all-time max, in every session.
        badges_by_date: dict[str, list[str]] = {}
        for record in records.all():
            badges_by_date.setdefault(record.date, []).append(PR_BADGES[record.kind])

        headline = _sessions_label(len(hist))
        if records.e1rm:
            headline += f" · best 1RM {_fmt(records.e1rm.value)}kg"

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text(
                                "Exercises", color=C.accent, size=12, weight=ft.FontWeight.W_700
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=self._back_to_list,
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text(name, size=20, weight=ft.FontWeight.W_900, color=C.text, max_lines=2),
                muted_text(headline, size=12),
                ft.Container(height=12),
                section_title("Personal records"),
                ft.Container(height=6),
                ft.Row(
                    [
                        self._pr_tile(PRKind.E1RM, records.e1rm, "kg"),
                        self._pr_tile(PRKind.MAX_WEIGHT, records.max_weight, "kg"),
                        self._pr_tile(PRKind.SESSION_VOLUME, records.session_volume, "kg"),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                ft.Container(height=14),
                section_title("Progression"),
                ft.Container(height=6),
                ft.Row([self._chart_chip(k, lbl) for k, lbl in CHART_KINDS], spacing=6, wrap=True),
                ft.Container(height=8),
                card(
                    bar_chart(values, labels, color=color, height=110),
                    padding=12,
                ),
                ft.Container(height=14),
                section_title("Session detail"),
                ft.Container(height=6),
                *[self._session_card(h, badges_by_date.get(h.date, [])) for h in reversed(hist)],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def build(self) -> ft.Control:
        if self.selected is None:
            return self._list()
        return self._detail()
