"""History: weekly muscle volume, exercise records and progression.

This screen is where the app is at its most cryptic: it prints `est. 1RM`,
`🏆 vol` and `12.3k` with no unit and no definition anywhere on the page, and
`12 sets unmapped in 4w` in language nobody outside this repository uses. Every
one of those now sits next to a `?` from `views/help_dialog.py` — the same
legend pattern the training screen already uses for N/W/D/F and RIR — and the
sentences themselves are written in English rather than in field names.

Two habits this file keeps:

* **Every number says its unit**, either in the label beside it or in a tooltip
  carrying the unshortened figure. A big accent-coloured number with a nine-point
  caption is exactly the shape a reader does not question.
* **Nothing is pluralised by hand.** `shared_ui.plural` does it, because "3
  warm-up" reached the screen three lines below a line that got it right.

And one thing this screen owes the training screen: **a note that is written and
never read again is not worth writing.** Both kinds reach the session cards —
the exercise note out of `WorkoutEntry.note`, which is the `entrenos.nota`
column, and the day's whole-session note out of `Storage.get_session_notes()`.
Absence is the normal case for both (every row the Telegram coach writes has
none), so they are read with `.get()` and simply take no height when there is
nothing to show.

The same argument covers **how long a session lasted**. `duraciones_sesion` is
keyed by date and holds only the days that were actually timed, so a missing day
is not a gap to apologise for — it is "nobody clocked that one", which is true of
every session logged before the table existed and of everything the coach writes.
It reaches the screen through `format_duration`, which returns `""` for that
case, and an empty string is the signal to render nothing rather than a `0m` that
would claim a session took no time.
"""

from __future__ import annotations

import contextlib

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
from components.charts import axis_note, bar_chart
from gym_tools import percentage_table
from set_types import SetType, set_type_of, short_label_for, warmup_sets, working_sets
from storage import Storage, format_duration
from theme import (
    C,
    Radius,
    card,
    chip,
    muted_text,
    section_title,
)
from views.help_dialog import (
    TOPIC_E1RM,
    TOPIC_MUSCLE,
    TOPIC_RECORDS,
    TOPIC_VOLUME,
    metric_help_icon,
)
from views.shared_ui import db_error_screen, plural

#: Four weeks is what fits as a chip row on a 420 px screen, and it is long
#: enough to see a mesocycle's volume ramp without scrolling sideways.
MUSCLE_WEEKS = 4
#: Bars beyond this turn the card into a wall; the tail is always noise anyway.
MAX_MUSCLE_BARS = 8
#: Widest a muscle bar may draw, leaving room for its label and value.
BAR_MAX_WIDTH = 150

#: One chart at a time. Three stacked charts on a phone means none get read.
CHART_KINDS: tuple[tuple[str, str], ...] = (
    ("e1rm", "1RM est. (kg)"),
    ("weight", "Máx kg"),
    ("volume", "Volumen (kg)"),
)

#: Which glossary entry the `?` beside "Progresión" should open, per chart.
#: "Máx kg" is the only one of the three that needs no explaining, so it
#: borrows the records entry, which defines "heaviest single set".
CHART_HELP_TOPICS: dict[str, str] = {
    "e1rm": TOPIC_E1RM,
    "weight": TOPIC_RECORDS,
    "volume": TOPIC_VOLUME,
}

#: Tile-width labels for the three records. `analytics.PR_LABELS` is the prose
#: version and does not fit in a third of a phone screen.
PR_TILE_LABELS: dict[PRKind, str] = {
    PRKind.E1RM: "1RM est.",
    PRKind.MAX_WEIGHT: "Más pesado",
    PRKind.SESSION_VOLUME: "Vol. sesión",
}
PR_BADGES: dict[PRKind, str] = {
    PRKind.E1RM: "1RM",
    PRKind.MAX_WEIGHT: "kg",
    PRKind.SESSION_VOLUME: "vol",
}
#: What each trophy on a session card actually claims, as a tooltip. The badge
#: itself has room for three characters; this is the sentence behind them, and
#: it is the same wording as `help_dialog.METRIC_HELP[TOPIC_RECORDS]`.
PR_BADGE_TOOLTIPS: dict[PRKind, str] = {
    PRKind.E1RM: "Mejor 1RM estimado de este ejercicio",
    PRKind.MAX_WEIGHT: "La serie más pesada de este ejercicio",
    PRKind.SESSION_VOLUME: "Mayor total de sesión (peso × reps) de este ejercicio",
}

#: Above this a tile shows `12.3k` instead of the figure. Named because the
#: help text quotes it and because the tooltip exists to undo it.
COMPACT_FROM = 10000

#: How many days of whole-session notes the list screen shows. Five is about a
#: training week and a half — long enough to find the one you meant to re-read,
#: short enough not to push the exercise list off the first screen.
NOTE_DAYS = 5

#: How many timed days the list screen shows. Same number as `NOTE_DAYS` and for
#: the same reason, but it earns its place differently: a session time is only
#: worth recording if it can be compared, and one figure on its own compares
#: with nothing. Five consecutive sessions are enough to see "these are running
#: long" without turning the first screen of History into a table.
DURATION_DAYS = 5


def _fmt(value: float) -> str:
    """Compact number for a tile: 12345 → 12.3k.

    Only ever used where a tooltip or a caption says the unit — a bare `12.3k`
    on screen is the exact thing the audit caught. Use `_kg()` anywhere there is
    room for the real figure.
    """
    if abs(value) >= COMPACT_FROM:
        return f"{value / 1000:.1f}k"
    return f"{round(value, 1):g}"


def _kg(value: float) -> str:
    """The full figure with its unit: `12,345 kg`. For lines, not for tiles."""
    return f"{value:,.0f} kg"


def _kg_tooltip(value: float, what: str) -> str:
    """What a shortened number really says, for the control that shows it."""
    return f"{what}: {_kg(value)}"


def _week_label(weeks_back: int) -> str:
    """Las claves ISO («2026-W33») no dicen nada de un vistazo; los saltos sí.

    «sem» y no «w»: la w venía de *week* y era la última letra inglesa que
    quedaba en un chip, al lado de un «Esta semana» que ya estaba traducido.
    """
    return "Esta semana" if weeks_back == 0 else f"−{weeks_back} sem"


def _sessions_label(count: int) -> str:
    return plural(count, "sesión", "sesiones")


def _set_label(one_set: dict) -> str:
    """A set as text. Bodyweight work is logged at 0 kg — say "8 reps"."""
    weight = one_set.get("weight") or 0
    reps = one_set.get("reps") or 0
    return f"{weight:g}kg × {reps}" if weight > 0 else plural(reps, "rep")


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

    def _reload(self):
        """The "try again" of the database-down card. Nothing is cached here —
        every read happens inside `build()` — so a plain refresh is the retry."""
        self.page.data["refresh_current"]()

    def _section_with_help(self, title: str, topic: str) -> ft.Control:
        """A section heading with its glossary `?` pinned to the right of it.

        The `?` goes on the heading rather than on each number: the numbers are
        16 pt values in a three-across row and there is no room beside them for
        a second tap target that is not a mis-tap waiting to happen.
        """
        return ft.Row(
            [
                ft.Container(content=section_title(title), expand=True),
                metric_help_icon(self.page, topic),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _set_chart(self, kind: str):
        self.chart_kind = kind
        self.page.data["refresh_current"]()

    def _set_week(self, weeks_back: int):
        self.weeks_back = weeks_back
        self.page.data["refresh_current"]()

    # ── weekly muscle volume ─────────────────────────────────
    def _muscle_bar(self, name: str, sets: float, top: float) -> ft.Control:
        width = max(4, int(BAR_MAX_WIDTH * (sets / top))) if top else 4
        return ft.Container(
            content=ft.Row(
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
                    # The trailing figure is a count of sets and nothing on the
                    # row says so; the tooltip is where the unit lives.
                    ft.Text(f"{sets:g}", size=10, color=C.text_muted),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            tooltip=f"{name}: {plural(sets, 'serie')} esta semana",
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
            rows = [muted_text("Sin series efectivas esta semana", size=11)]

        # The unresolved keys are counted over the whole window, not the
        # selected week — say so instead of letting them read as this week's.
        #
        # "unmapped" and "attributed" are field names out of analytics.py, not
        # English: the line used to read "12 sets unmapped in 4w", which tells a
        # reader that something is wrong and nothing about what. Both notes now
        # say what actually happened — the sets exist, no muscle claims them —
        # and the `?` on the heading explains the rest.
        notes: list[ft.Control] = []
        if mv.unattributed:
            names = ", ".join(list(mv.unattributed)[:2])
            extra = len(mv.unattributed) - 2
            if extra > 0:
                names += f" y {plural(extra, 'otro')}"
            # Phrased so no verb has to agree with a count: "1 set ... are not
            # counted ... Not A Real Exercise have no muscle data" is what the
            # obvious wording produced on a one-row database. Nouns only.
            notes.append(
                ft.Text(
                    f"Sin contar arriba: {plural(mv.unattributed_sets, 'serie')} de "
                    f"las últimas {plural(MUSCLE_WEEKS, 'semana')}. Sin datos musculares de {names}.",
                    size=10,
                    color=C.warning,
                    max_lines=3,
                )
            )
        if mv.partial:
            notes.append(
                ft.Text(
                    f"Contado a medias: {plural(len(mv.partial), 'ejercicio combinado', 'ejercicios combinados')} — "
                    "solo los músculos que se pudieron identificar.",
                    size=10,
                    color=C.text_muted,
                    max_lines=3,
                )
            )

        return card(
            ft.Row(
                [
                    section_title("Series semanales por músculo"),
                    ft.Row(
                        [
                            ft.Text(plural(MUSCLE_WEEKS, "semana"), size=10, color=C.text_muted),
                            metric_help_icon(self.page, TOPIC_MUSCLE),
                        ],
                        spacing=2,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            muted_text("Un músculo trabajado directo cuenta 1 serie; uno que asiste, ½", size=10),
            ft.Container(height=6),
            chips,
            ft.Container(height=8),
            *rows,
            *([ft.Container(height=6), *notes] if notes else []),
            padding=14,
            margin=ft.margin.only(bottom=12),
        )

    # ── list ─────────────────────────────────────────────────
    def _notes_card(self, notes: dict[str, str]) -> ft.Control:
        """The last few whole-session notes, newest first.

        On the list screen and not only on the session cards, because a session
        note does not need a workout to exist: `notas_sesion` is keyed by date
        alone, so "gym shut, did nothing" is a note about a day with no rows for
        any exercise detail view to hang it on. Without this card that note
        could be written and never read again, which is the one thing a note may
        not be.
        """
        if not notes:
            return ft.Container()
        recent = sorted(notes.items(), reverse=True)[:NOTE_DAYS]
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.EDIT_NOTE, size=16, color=C.accent),
                    section_title("Notas de sesión"),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=6),
            *[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(day, size=10, color=C.accent, weight=ft.FontWeight.W_700),
                            ft.Text(
                                text, size=11, color=C.text_secondary, max_lines=4, selectable=True
                            ),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    bgcolor=C.bg_sunken,
                    border_radius=Radius.sm,
                    padding=8,
                    margin=ft.margin.only(bottom=6),
                )
                for day, text in recent
            ],
            padding=14,
            margin=ft.margin.only(bottom=12),
        )

    def _times_card(self, durations: dict[str, int]) -> ft.Control:
        """The last few session times, newest first. Nothing when none are timed.

        On the list screen for the same reason `_notes_card` is: a duration
        belongs to a **day**, not to an exercise, so the only other place it
        appears is a chip on a session card two taps in — and a session time you
        have to go looking for is one nobody compares. Here it sits next to the
        weekly volume, which is the other thing you would ask it about ("more
        sets, or just a longer time in the gym?").

        Days with no row simply are not listed. This is not a calendar and an
        untimed day is not a hole in it.
        """
        if not durations:
            return ft.Container()
        recent = sorted(durations.items(), reverse=True)[:DURATION_DAYS]
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.TIMER_OUTLINED, size=16, color=C.accent),
                    section_title("Tiempos de sesión"),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            muted_text("Solo las sesiones cronometradas — el resto no se midió", size=10),
            ft.Container(height=6),
            *[
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(
                                day,
                                size=10,
                                color=C.accent,
                                weight=ft.FontWeight.W_700,
                                expand=True,
                            ),
                            ft.Text(
                                format_duration(seconds),
                                size=12,
                                color=C.text,
                                weight=ft.FontWeight.W_900,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=C.bg_sunken,
                    border_radius=Radius.sm,
                    padding=8,
                    margin=ft.margin.only(bottom=6),
                )
                for day, seconds in recent
            ],
            padding=14,
            margin=ft.margin.only(bottom=12),
        )

    def _empty(self, extra: ft.Control | None = None) -> ft.Control:
        return ft.Column(
            [
                self._title_row(),
                muted_text("Toca un ejercicio para ver marcas y progresión"),
                ft.Container(height=20),
                # A day can carry a note with nothing logged against it, and
                # that day is exactly the one this screen would otherwise call
                # empty.
                extra or ft.Container(),
                card(
                    ft.Text("📭", size=28, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "Entrena para empezar a ver tu progreso",
                        size=12,
                        color=C.text_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=24,
                    alignment=ft.alignment.center,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=0,
            tight=True,
        )

    def _title_row(self) -> ft.Control:
        """The screen heading, with the way into the glossary beside it.

        One `?` for the whole screen, on the title: History prints four
        different unexplained numbers and a reader who does not know what
        `est. 1RM` is does not know which section to look under either.
        """
        return ft.Row(
            [
                ft.Text(
                    "Historial y progreso",
                    size=22,
                    weight=ft.FontWeight.W_900,
                    color=C.text,
                    expand=True,
                ),
                metric_help_icon(self.page, size=30),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _list(self) -> ft.Control:
        try:
            summary = self.store.get_exercise_summary()
            entries = self.store.get_all() if summary else []
        except Exception as exc:  # database down, driver missing, anything
            # Without this the exception escapes `build()` and History renders
            # as a blank screen, which reads as a crash rather than as "the
            # server is off".
            return db_error_screen("Historial y progreso", exc, on_retry=self._reload)
        notes_card = self._notes_card(self._session_notes())
        times_card = self._times_card(self._durations())
        if not summary:
            # Both can exist with nothing logged: a note needs no workout row,
            # and a restored backup can carry a duration whose sets never made
            # it back. The "start training" screen is exactly where they would
            # otherwise be unreachable.
            return self._empty(ft.Column([notes_card, times_card], spacing=0, tight=True))

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
                subtitle += f" · máx {ex['max_weight']:g} kg"
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
                                    # The unit was missing entirely: a 16 pt
                                    # accent number captioned "est. 1RM" could
                                    # be kilos, pounds or a score. The `?` on
                                    # the screen title says what it is; this
                                    # says at least what it is measured in.
                                    ft.Text("est. 1RM · kg", size=9, color=C.text_muted),
                                ],
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    tooltip=(
                        _kg_tooltip(e1rm, "Máximo estimado a una repetición")
                        if e1rm
                        else "Aún no hay 1RM estimado para este ejercicio"
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
                self._title_row(),
                muted_text("Toca un ejercicio para ver marcas y progresión"),
                ft.Container(height=10),
                self._muscle_card(entries),
                times_card,
                notes_card,
                section_title("Ejercicios"),
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
                    ft.Text(record.date if record else "sin datos", size=8, color=C.text_muted),
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=6, vertical=10),
            expand=True,
            # Session volume runs into five figures, so this is the tile most
            # likely to be showing `12.3k`. The tooltip carries the real number
            # and the sentence behind the three-letter label.
            tooltip=(
                f"{PR_BADGE_TOOLTIPS[kind]} — {_kg(record.value)} el {record.date}"
                if record
                else f"{PR_BADGE_TOOLTIPS[kind]} — nada registrado aún"
            ),
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

    #: Which series get a cropped axis. Not all three: **volume** is a
    #: magnitude that legitimately runs to zero — a light day really is a small
    #: bar, and lifting that baseline would exaggerate an ordinary week into a
    #: collapse. The other two never start at zero: nobody's estimated 1RM or
    #: top set is near it, so a zero axis squeezes months of progress into a
    #: couple of pixels. Alex's 82-84 kg body-weight chart drew 2.2 kg of change
    #: as three pixels of a hundred and ten; these two had the same shape.
    _CROPPED_AXIS = ("e1rm", "weight")

    def _progression_chart(self, values, labels, color) -> list[ft.Control]:
        base = "auto" if self.chart_kind in self._CROPPED_AXIS else "zero"
        grafica = bar_chart(values, labels, color=color, height=110, baseline=base)
        nota = axis_note(grafica)
        if not nota:
            return [grafica]
        # A cropped axis that does not say so is a nicer-looking lie.
        return [grafica, ft.Text(nota, size=9, color=C.text_muted, italic=True)]

    def _session_notes(self) -> dict[str, str]:
        """Every day that carries a whole-session note, keyed by ISO date.

        One query for the screen rather than one per card: `get_session_notes`
        returns the last 60 days, which covers the sessions a detail view shows
        several times over. A database that answers the workout query and not
        this one still renders the sets — a missing note is not a broken screen.
        """
        notes: dict[str, str] = {}
        try:
            rows = self.store.get_session_notes()
        except Exception:
            return notes
        for row in rows:
            text = (row.get("note") or "").strip()
            if text:
                notes[str(row.get("date") or "")] = text
        return notes

    def _durations(self) -> dict[str, int]:
        """`{iso date: seconds}` for every timed day. One query for the screen.

        `get_duration_map`, not `get_session_durations`: the detail view paints
        one card per session and this is read with `.get()` per card, so a
        per-card query would be one round-trip per exercise-day. Same shape and
        same reason as `_session_notes` above.

        A database that will not answer means "nothing timed". This number is
        context on a card whose sets are the point; it must never be the reason
        History renders an error.
        """
        found: dict[str, int] = {}
        with contextlib.suppress(Exception):
            found = dict(self.store.get_duration_map())
        return found

    def _duration_chip(self, iso: str, durations: dict[str, int]) -> ft.Control:
        """ "1h 12m" beside a session's date, or nothing at all.

        Nothing at all is the common case and has to cost no height: most rows
        in `entrenos` predate the table, and the coach never writes one.
        """
        text = format_duration(durations.get(iso))
        if not text:
            return ft.Container()
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TIMER_OUTLINED, size=11, color=C.text_secondary),
                    ft.Text(text, size=9, color=C.text_secondary, weight=ft.FontWeight.W_700),
                ],
                spacing=3,
                tight=True,
            ),
            bgcolor=C.bg_sunken,
            border_radius=Radius.sm,
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            # Says whose time it is. The duration belongs to the whole day, not
            # to this exercise, and a bare "1h 12m" on a Bench Press card reads
            # like an hour of bench pressing.
            tooltip="Cuánto duró la sesión entera de ese día",
        )

    def _note_line(self, text: str, *, whole_session: bool) -> ft.Control:
        """A note under the sets it belongs to, labelled by which kind it is.

        The two are genuinely different claims — "this exercise felt heavy"
        against "this whole day felt heavy" — and a note shown without saying
        which one it is invites reading a bad night's sleep as a bad bench
        press. The icon and the lead-in carry that distinction; the text itself
        is Alex's and is printed unaltered.
        """
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.EDIT_NOTE if whole_session else ft.Icons.STICKY_NOTE_2_OUTLINED,
                        size=13,
                        color=C.text_secondary,
                    ),
                    ft.Text(
                        text,
                        size=10,
                        color=C.text_secondary,
                        expand=True,
                        max_lines=6,
                        selectable=True,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=C.bg_sunken,
            border_radius=Radius.sm,
            padding=8,
            margin=ft.margin.only(top=6),
            tooltip=("Nota de la sesión entera" if whole_session else "Nota de este ejercicio"),
        )

    def _session_card(
        self,
        h,
        badges: list[PRKind],
        session_note: str = "",
        durations: dict[str, int] | None = None,
    ) -> ft.Control:
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
        # Right beside the date, because it is a fact about that date. Defaulted
        # to `{}` rather than made required: this method is also handed rows by
        # callers that never read the table, and a session card is not worth
        # breaking over a missing duration.
        header.append(self._duration_chip(h.date, durations or {}))
        for kind in badges:
            # `🏆 vol` is three characters of internal shorthand sitting on a
            # card with no key anywhere near it. The badge stays — it has to fit
            # a header row — but it now carries the sentence, and the `?` beside
            # "Marcas personales" carries all three.
            header.append(
                ft.Container(
                    content=ft.Text(
                        f"🏆 {PR_BADGES[kind]}", size=9, weight=ft.FontWeight.W_700, color=C.success
                    ),
                    bgcolor=C.bg_sunken,
                    border_radius=Radius.sm,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    tooltip=f"Sigue siendo tu mejor marca: {PR_BADGE_TOOLTIPS[kind]}",
                )
            )

        working = working_sets(h.sets)
        session_volume = volume(h.sets)
        # `_kg`, not `_fmt`: this is a full-width line with room for the real
        # figure, so there is no reason to print `12.3k` and make the reader
        # guess at both the scale and the unit.
        summary = f"{plural(len(working), 'serie')} · {_kg(session_volume)}"
        # Counted, not subtracted: `working_sets` also drops malformed rows,
        # which are not warm-ups.
        warmups = len(warmup_sets(h.sets))
        if warmups:
            summary += f" · {plural(warmups, 'calentamiento')}"

        # `getattr`, not `h.note`: `WorkoutEntry.note` is new and defaulted, and
        # this method is also handed rows by anything holding an older entry.
        exercise_note = (getattr(h, "note", None) or "").strip()
        notes: list[ft.Control] = []
        if exercise_note:
            notes.append(self._note_line(exercise_note, whole_session=False))
        if session_note:
            notes.append(self._note_line(session_note, whole_session=True))

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
            *notes,
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    #: Which percentages the planning table shows. The classic four, and the
    #: range hypertrophy work actually lives in: 60 % is roughly a set of 15,
    #: 90 % roughly a set of 4. Above that the Epley estimate is guessing about
    #: a rep nobody in this plan performs.
    _PLAN_PERCENTS = (0.6, 0.7, 0.75, 0.8, 0.85, 0.9)

    def _percent_table(self, one_rm: float | None) -> list[ft.Control]:
        """The estimated 1RM read forwards instead of backwards.

        `analytics.estimated_1rm` has always been on this screen, as a record
        that has already happened. `gym_tools.percentage_table` turns it into
        next session's numbers — "80 % is 82.5 kg, about 8 reps" — and every
        weight comes back rounded to something the room can actually load, with
        its plates, because a plan built on 83.7 kg is a plan for a gym that
        does not exist.

        It lives here and not in the set row on purpose: this is a thing you
        read at the kitchen table when deciding what to do next week, not
        between two sets with the rest timer running.
        """
        if not one_rm:
            return []

        filas = percentage_table(one_rm, percentages=self._PLAN_PERCENTS)
        if not filas:
            return []

        def linea(fila) -> ft.Control:
            reps = plural(fila.reps, "rep") if fila.reps else "—"
            discos = fila.plates.label() if fila.plates and not fila.plates.bar_only else ""
            # `plates.total`, NOT `fila.weight`. The latter is the arithmetic
            # percentage — 70 % of 102.5 is 71.75 kg — and the plate list beside
            # it describes the *loadable* weight, 72.5. Printing the arithmetic
            # next to plates that make a different number is a table that
            # contradicts itself, and the rep estimate is computed against the
            # loaded weight anyway.
            peso = fila.plates.total if fila.plates else fila.weight
            return ft.Row(
                [
                    ft.Container(
                        content=ft.Text(
                            f"{fila.percent * 100:.0f}%",
                            size=12,
                            color=C.text_secondary,
                            weight=ft.FontWeight.W_700,
                        ),
                        width=46,
                    ),
                    ft.Container(
                        content=ft.Text(
                            f"{peso:g} kg", size=13, color=C.text, weight=ft.FontWeight.W_700
                        ),
                        width=76,
                    ),
                    ft.Container(
                        content=ft.Text(f"≈ {reps}", size=11, color=C.text_secondary),
                        width=64,
                    ),
                    ft.Container(
                        content=ft.Text(
                            discos,
                            size=10,
                            color=C.text_muted,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        expand=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        return [
            ft.Container(height=14),
            self._section_with_help("Planificar desde este 1RM", TOPIC_E1RM),
            ft.Container(height=6),
            card(
                muted_text(
                    "Porcentajes del 1RM estimado de arriba, redondeados a pesos que "
                    "puedes montar de verdad. Las reps son una estimación, no un objetivo.",
                    size=10,
                ),
                ft.Container(height=8),
                *[linea(f) for f in filas],
                padding=12,
            ),
        ]

    def _detail(self) -> ft.Control:
        name = self.selected
        assert name
        try:
            hist = self.store.get_exercise_history(name)
        except Exception as exc:  # database down, driver missing, anything
            return db_error_screen(name, exc, on_retry=self._reload)
        records = personal_records(hist, name)
        values, labels, color = self._chart_data(hist, name)
        session_notes = self._session_notes()
        durations = self._durations()

        # A session is flagged only for the records it actually holds — the old
        # 🏆 fired on every set matching the all-time max, in every session.
        # Kinds, not their three-letter badges: the card needs the kind to look
        # up what the badge means.
        badges_by_date: dict[str, list[PRKind]] = {}
        for record in records.all():
            badges_by_date.setdefault(record.date, []).append(record.kind)

        headline = _sessions_label(len(hist))
        if records.e1rm:
            headline += f" · mejor 1RM estimado {_kg(records.e1rm.value)}"

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text(
                                "Ejercicios", color=C.accent, size=12, weight=ft.FontWeight.W_700
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
                self._section_with_help("Marcas personales", TOPIC_RECORDS),
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
                # The chart's own chips are "1RM est.", "Máx kg" and "Volumen",
                # so the `?` follows whichever one is selected rather than
                # always explaining the first.
                self._section_with_help("Progresión", CHART_HELP_TOPICS[self.chart_kind]),
                ft.Container(height=6),
                ft.Row([self._chart_chip(k, lbl) for k, lbl in CHART_KINDS], spacing=6, wrap=True),
                ft.Container(height=8),
                card(
                    *self._progression_chart(values, labels, color),
                    padding=12,
                ),
                *self._percent_table(records.e1rm.value if records.e1rm else None),
                ft.Container(height=14),
                section_title("Detalle de la sesión"),
                ft.Container(height=6),
                *[
                    self._session_card(
                        h,
                        badges_by_date.get(h.date, []),
                        session_notes.get(h.date, ""),
                        durations,
                    )
                    for h in reversed(hist)
                ],
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
