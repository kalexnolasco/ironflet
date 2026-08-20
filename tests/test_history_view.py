"""What History says about numbers it prints, and what it says when it cannot.

Three things are guarded here, all of them things the screen got wrong:

* **Plurals.** "3 warm-up" reached the session card, three lines under a line
  that pluralised correctly.
* **Jargon.** `unmapped`, a bare `12.3k`, and a 16 pt number captioned
  `est. 1RM` with no unit anywhere near it.
* **A dead database.** Every read happened inside `build()` unguarded, so an
  outage rendered History as an empty screen rather than as a message.

No real database: a fake store hands back `WorkoutEntry` objects, which is what
`analytics.py` consumes, so the metrics under test are the real ones.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft
import pytest

from storage import WorkoutEntry
from theme import LIGHT, set_palette
from views.help_dialog import METRIC_HELP, TOPIC_RECORDS
from views.history import HistoryView


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


class FakeStore:
    """Just enough Storage for History, plus a switch to make it fail."""

    def __init__(self, entries: list[WorkoutEntry], fail: Exception | None = None):
        self.entries = entries
        self.fail = fail

    def _check(self):
        if self.fail is not None:
            raise self.fail

    def get_all(self) -> list[WorkoutEntry]:
        self._check()
        return list(self.entries)

    def get_exercise_summary(self) -> list[dict]:
        self._check()
        summary: dict[str, dict] = {}
        for w in self.entries:
            row = summary.setdefault(
                w.exercise,
                {"name": w.exercise, "count": 0, "last_date": w.date, "max_weight": 0.0},
            )
            row["count"] += 1
            row["last_date"] = max(row["last_date"], w.date)
            for s in w.sets:
                row["max_weight"] = max(row["max_weight"], s.get("weight") or 0)
        return sorted(summary.values(), key=lambda r: r["count"], reverse=True)

    def get_exercise_history(self, name: str) -> list[WorkoutEntry]:
        self._check()
        return [w for w in self.entries if w.exercise == name]


def entry(date: str, sets: list[dict], exercise: str = "Squat") -> WorkoutEntry:
    return WorkoutEntry(date=date, exercise=exercise, muscle_group="Legs", phase=1, sets=sets)


def work(weight: float, reps: int) -> dict:
    return {"weight": weight, "reps": reps}


def warmup(weight: float, reps: int) -> dict:
    return {"weight": weight, "reps": reps, "type": "warmup"}


def make_view(entries, fail=None) -> HistoryView:
    page = MagicMock()
    page.width = 400
    page.height = 800
    page.data = {"refresh_current": lambda: None}
    return HistoryView(page, FakeStore(entries, fail))


def texts(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, ft.Text) and isinstance(node.value, str):
            found.append(node.value)
        for attr in ("content", "controls", "actions", "title", "spans"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


def tooltips(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        tip = getattr(node, "tooltip", None)
        if isinstance(tip, str) and tip:
            found.append(tip)
        for attr in ("content", "controls", "actions", "title"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


def blob(control) -> str:
    return " | ".join(texts(control))


# ── plurals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("warmups", "expected"),
    [(1, "1 warm-up"), (3, "3 warm-ups")],
)
def test_the_session_card_pluralises_its_warmups(warmups, expected):
    """`3 warm-up` is the exact string the audit found on screen."""
    sets = [warmup(60, 5) for _ in range(warmups)] + [work(100, 5)]
    view = make_view([entry("2026-08-10", sets)])
    view.selected = "Squat"
    rendered = blob(view.build())
    assert expected in rendered
    assert "3 warm-up |" not in rendered  # i.e. no unpluralised leftover


def test_the_session_card_pluralises_its_working_sets():
    one = make_view([entry("2026-08-10", [work(100, 5)])])
    one.selected = "Squat"
    assert "1 set ·" in blob(one.build())

    many = make_view([entry("2026-08-10", [work(100, 5), work(100, 5)])])
    many.selected = "Squat"
    assert "2 sets ·" in blob(many.build())


def test_a_single_unattributed_exercise_is_not_reported_as_plural():
    """`1 sets ... 1 exercises` was the same bug in the muscle card."""
    view = make_view([entry("2026-08-10", [work(40, 10)], exercise="Not A Real Exercise")])
    rendered = blob(view.build())
    assert "1 sets" not in rendered
    assert "1 weeks" not in rendered


def test_the_muscle_note_has_no_verb_to_disagree_with_its_count():
    """Found by rendering it: "1 set … are not counted … Not A Real Exercise have".

    Pluralising the count is only half the job — the sentence around it has to
    work at one *and* at twelve. This one is built from noun phrases so there is
    no verb to get wrong.
    """
    one = make_view([entry("2026-08-10", [work(40, 10)], exercise="Not A Real Exercise")])
    rendered = blob(one.build())
    assert "Not counted above: 1 set in the last 4 weeks." in rendered
    for wrong in (" are not counted", " have no muscle data", "1 set are"):
        assert wrong not in rendered

    many = make_view(
        [
            entry("2026-08-10", [work(40, 10), work(40, 10)], exercise="Not A Real Exercise"),
            entry("2026-08-11", [work(40, 10)], exercise="Also Not Real"),
        ]
    )
    assert "Not counted above: 3 sets in the last 4 weeks." in blob(many.build())


# ── jargon ──────────────────────────────────────────────────────────────


def test_the_muscle_card_does_not_say_unmapped():
    """ "unmapped" is a field name from analytics.py, not English."""
    view = make_view([entry("2026-08-10", [work(40, 10)], exercise="Not A Real Exercise")])
    rendered = blob(view.build()).lower()
    assert "unmapped" not in rendered
    assert "attributed" not in rendered
    # And it says what actually happened instead.
    assert "no muscle data" in rendered


def test_the_list_says_what_unit_the_big_number_is_in():
    view = make_view([entry("2026-08-10", [work(100, 5)])])
    tree = view.build()
    assert "est. 1RM · kg" in blob(tree)
    # …and the tooltip carries the unshortened figure.
    assert any("Estimated one-rep max" in t and "kg" in t for t in tooltips(tree))


def test_the_session_summary_prints_kilos_not_a_bare_k():
    """A wide line has room for the real figure, so it shows the real figure.

    The narrow PR tile still shortens to `20.0k` — it is five characters wide —
    but it captions itself "kg" and carries the full number in its tooltip.
    """
    sets = [work(100, 10) for _ in range(20)]  # 20,000 kg
    view = make_view([entry("2026-08-10", sets)])
    view.selected = "Squat"
    tree = view.build()
    summary = [t for t in texts(tree) if t.startswith("20 sets")]
    assert summary == ["20 sets · 20,000 kg"]
    assert any("20,000 kg" in t for t in tooltips(tree)), "the shortened tile explains itself"


def test_every_trophy_carries_the_sentence_behind_it():
    """`🏆 vol` is three characters with no key anywhere near it."""
    view = make_view([entry("2026-08-10", [work(100, 5)])])
    view.selected = "Squat"
    tips = tooltips(view.build())
    assert any("Biggest session total" in t for t in tips)
    assert any("Heaviest single set" in t for t in tips)


def test_the_glossary_is_reachable_from_the_screen():
    view = make_view([entry("2026-08-10", [work(100, 5)])])
    view.selected = "Squat"
    view.build()
    # The `?` next to "Personal records" opens the records entry.
    icons = [c for c in _walk(view.build()) if getattr(c, "on_click", None)]
    view.page.open.reset_mock()
    for control in icons:
        control.on_click(None)
    opened = [c.args[0] for c in view.page.open.call_args_list]
    rendered = " | ".join(blob(d) for d in opened)
    assert METRIC_HELP[TOPIC_RECORDS].lead in rendered


def test_the_empty_screen_also_offers_the_glossary():
    """Nothing logged yet is exactly when the words are unfamiliar."""
    view = make_view([])
    tips = tooltips(view.build())
    assert any("numbers" in t.lower() for t in tips)


def _walk(node, seen=None):
    seen = seen if seen is not None else set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item, seen)
        return
    yield node
    for attr in ("content", "controls", "actions", "title"):
        yield from _walk(getattr(node, attr, None), seen)


# ── the database is down ────────────────────────────────────────────────


class _DriverError(Exception):
    pass


_DriverError.__module__ = "sqlalchemy.exc"


def test_a_dead_database_renders_a_message_not_a_blank_screen():
    view = make_view([], fail=_DriverError("could not connect to server"))
    rendered = blob(view.build())
    assert "Can't reach the database" in rendered
    assert "could not connect to server" in rendered
    # The heading survives, so this reads as "no data" and not "the app is gone".
    assert "History & Progress" in rendered


def test_the_detail_screen_survives_the_database_too():
    view = make_view([], fail=_DriverError("server closed the connection"))
    view.selected = "Squat"
    rendered = blob(view.build())
    assert "Can't reach the database" in rendered
    assert "Squat" in rendered


def test_the_error_card_offers_a_retry():
    view = make_view([], fail=_DriverError("down"))
    retry = [
        c
        for c in _walk(view.build())
        if getattr(c, "on_click", None) and any("Try again" in t for t in texts(c))
    ]
    assert retry, "no way to try again once the database comes back"
