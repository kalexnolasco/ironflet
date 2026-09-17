"""Tests for set_types.py.

No database and no Flet — everything under test is a pure function.

Two groups matter more than the rest:

* **Backward compatibility.** Every set already in `entrenos.series` was
  written without a `"type"` key, and the Telegram coach still writes without
  it. Those sets are work and have to keep counting. Half of this file exists
  to make that impossible to break by accident.
* **Coherence with the coach.** The rest-time tests read the real constants out
  of `../agente/entrenador/sesion_viva.py` and the real session plan out of
  `plan.py`, then check that both sides return the same number of seconds for
  every exercise Alex actually trains. Edit the coach's list of basic lifts and
  this file fails, which is the whole idea. The agent lives outside this repo,
  so the tests skip when it is not checked out next to it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import data
from analytics import personal_records, volume
from exercises import exercise_key
from set_types import (
    CYCLE_ORDER,
    LABELS,
    REST_AFTER_WARMUP_S,
    REST_COMPOUND_S,
    REST_ISOLATION_S,
    SetType,
    count_by_type,
    counts_as_work,
    format_rest,
    is_compound,
    is_warmup,
    next_set_type,
    parse_prescribed_rest,
    parse_set_type,
    rest_seconds,
    rest_seconds_for_phase,
    set_type_of,
    tag_set,
    warmup_sets,
    working_sets,
)

AGENT_DIR = Path(__file__).resolve().parents[2] / "agente" / "entrenador"


def s(weight, reps, **kw):
    return {"weight": weight, "reps": reps, **kw}


def entry(day, exercise, sets):
    return {"date": day, "exercise": exercise, "sets": sets}


# ── backward compatibility: no "type" key means normal ───────────────────


def test_a_set_without_a_type_key_is_normal():
    """The shape of every row written before this module existed."""
    old = {"weight": 100.0, "reps": 5}
    assert set_type_of(old) is SetType.NORMAL
    assert not is_warmup(old)
    assert counts_as_work(old)
    assert working_sets([old]) == [old]


def test_sets_written_by_the_telegram_coach_still_count():
    """`agente/entrenador/entrenos.py::guardar_series` builds exactly this.

    It writes `weight`, `reps` and — only when filled in — `rir`. No `type`,
    and there is no reason for it to grow one: absent already means normal.
    """
    from_coach = [
        {"weight": 100.0, "reps": 5, "rir": 2.0},
        {"weight": 100.0, "reps": 5},
    ]
    for one in from_coach:
        assert "type" not in one
        assert set_type_of(one) is SetType.NORMAL
        assert counts_as_work(one)
    assert working_sets(from_coach) == from_coach
    # The load-bearing consequence: it is still volume.
    assert volume(from_coach) == 1000.0


def test_untyped_sets_still_count_towards_volume_and_prs():
    """A history with no `type` anywhere must read exactly as it always did."""
    history = [
        entry("2026-08-10", "Squat", [s(100, 5), s(100, 5), s(100, 5)]),
        entry("2026-08-13", "Squat", [s(105, 5), s(105, 5)]),
    ]
    assert volume(history[0]["sets"]) == 1500.0
    prs = personal_records(history, "Squat")
    assert prs.max_weight is not None
    assert prs.max_weight.value == 105.0


def test_an_unknown_type_is_treated_as_work():
    """A spelling nobody planned for is still a set that happened."""
    weird = s(100, 5, type="myo-reps")
    assert set_type_of(weird) is SetType.NORMAL
    assert counts_as_work(weird)
    assert volume([weird]) == 500.0


def test_junk_never_raises():
    assert set_type_of(None) is SetType.NORMAL
    assert set_type_of("not a dict") is SetType.NORMAL
    assert set_type_of({"type": 7}) is SetType.NORMAL
    assert parse_set_type(object()) is SetType.NORMAL
    assert working_sets(None) == []
    assert working_sets([s(100, 5), "junk", None]) == [s(100, 5)]


# ── parsing and tagging ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("warmup", SetType.WARMUP),
        ("Warm-Up", SetType.WARMUP),
        ("warm up", SetType.WARMUP),
        ("warm_up", SetType.WARMUP),
        ("  WARMUP  ", SetType.WARMUP),
        ("normal", SetType.NORMAL),
        ("working", SetType.NORMAL),
        ("dropset", SetType.DROPSET),
        ("drop set", SetType.DROPSET),
        ("drop-set", SetType.DROPSET),
        ("failure", SetType.FAILURE),
        ("to failure", SetType.FAILURE),
        (SetType.FAILURE, SetType.FAILURE),
        (None, SetType.NORMAL),
    ],
)
def test_parse_set_type_accepts_the_spellings_in_the_wild(raw, expected):
    assert parse_set_type(raw) is expected


def test_only_warmups_are_discounted():
    """Drop sets and failure sets are work. They say how, not whether."""
    assert not counts_as_work(s(60, 10, type="warmup"))
    for kind in ("normal", "dropset", "failure"):
        assert counts_as_work(s(100, 5, type=kind)), kind
    assert volume([s(100, 5, type="dropset"), s(100, 5, type="failure")]) == 1000.0


def test_tag_set_writes_the_key_only_when_it_says_something():
    """Normal is the default, so a normal set keeps the coach's exact shape."""
    plain = tag_set({"weight": 100.0, "reps": 5}, SetType.NORMAL)
    assert plain == {"weight": 100.0, "reps": 5}
    assert "type" not in plain

    warm = tag_set({"weight": 40.0, "reps": 10}, SetType.WARMUP)
    assert warm == {"weight": 40.0, "reps": 10, "type": "warmup"}


def test_tag_set_does_not_mutate_its_input():
    """Callers pass rows read straight out of storage."""
    original = {"weight": 100.0, "reps": 5, "rir": 2.0}
    tagged = tag_set(original, SetType.WARMUP)
    assert original == {"weight": 100.0, "reps": 5, "rir": 2.0}
    assert tagged["rir"] == 2.0  # every other key survives


def test_tag_set_can_relabel_and_can_clear():
    warm = tag_set({"weight": 40.0, "reps": 10}, "warmup")
    assert tag_set(warm, SetType.DROPSET)["type"] == "dropset"
    assert "type" not in tag_set(warm, SetType.NORMAL)


def test_the_stored_value_is_a_plain_string():
    """`series` is a JSON column: whatever goes in has to survive a round trip."""
    payload = [tag_set(s(40, 10), SetType.WARMUP), tag_set(s(100, 5), SetType.NORMAL)]
    restored = json.loads(json.dumps(payload))
    assert restored == [
        {"weight": 40, "reps": 10, "type": "warmup"},
        {"weight": 100, "reps": 5},
    ]
    assert isinstance(restored[0]["type"], str)
    assert is_warmup(restored[0])


def test_warmups_and_working_sets_partition_the_list():
    sets = [s(40, 10, type="warmup"), s(60, 8, type="warmup"), s(100, 5), s(100, 5)]
    assert len(warmup_sets(sets)) == 2
    assert len(working_sets(sets)) == 2
    assert len(warmup_sets(sets)) + len(working_sets(sets)) == len(sets)


def test_count_by_type_reports_every_type():
    counts = count_by_type([s(40, 10, type="warmup"), s(100, 5), s(90, 8, type="failure")])
    assert counts[SetType.WARMUP] == 1
    assert counts[SetType.NORMAL] == 1
    assert counts[SetType.FAILURE] == 1
    assert counts[SetType.DROPSET] == 0


def test_cycling_visits_every_type_and_comes_back():
    seen = [SetType.NORMAL]
    for _ in range(len(CYCLE_ORDER) - 1):
        seen.append(next_set_type(seen[-1]))
    assert set(seen) == set(SetType)
    assert next_set_type(seen[-1]) is SetType.NORMAL
    assert all(LABELS[t] for t in SetType)


# ── the point of all this: a warm-up cannot inflate volume or steal a PR ──


def test_a_warmup_does_not_count_towards_volume():
    sets = [tag_set(s(40, 10), SetType.WARMUP), s(100, 5), s(100, 5)]
    assert volume(sets) == 1000.0  # not 1400


def test_a_heavy_warmup_cannot_steal_a_pr():
    """The failure mode this feature exists for: a mis-logged heavy single."""
    history = [entry("2026-08-13", "Squat", [tag_set(s(300, 1), SetType.WARMUP), s(100, 5)])]
    prs = personal_records(history, "Squat")
    assert prs.max_weight is not None
    assert prs.max_weight.value == 100.0


def test_this_module_and_analytics_agree_on_what_a_warmup_is():
    """Two copies of the same rule, until analytics delegates here.

    `analytics.WARMUP_TYPES` hardcodes its own spellings. If either side grows
    one the other lacks, a warm-up silently starts counting as work again.
    """
    import analytics

    for raw in ("warmup", "warm_up", "warm-up", "warm up", "Warm-Up", "WARMUP"):
        mine, theirs = is_warmup(s(60, 10, type=raw)), analytics.is_warmup(s(60, 10, type=raw))
        assert mine is theirs is True, raw
    for raw in ("normal", "dropset", "failure", "myo-reps"):
        assert is_warmup(s(60, 10, type=raw)) is analytics.is_warmup(s(60, 10, type=raw)) is False
    assert is_warmup(s(60, 10)) is analytics.is_warmup(s(60, 10)) is False


# ── rest: agreement with the Telegram coach ──────────────────────────────

# Every exercise the coach prescribes, mapped to the canonical English key the
# app stores it under (`agente/entrenador/entrenos.py::EJERCICIOS` does the
# same mapping in the other direction). If the coach's plan grows an exercise
# that is not here, test_every_coached_exercise_is_mapped says so.
COACH_TO_APP = {
    # Monday — Push
    "Press banca con barra": "Barbell Bench Press",
    "Press militar de pie": "Barbell Military Press",
    "Press inclinado mancuernas": "Incline DB Press",
    "Elevaciones laterales": "Lateral Raises",
    "Fondos en paralelas": "Dips",
    "Extensión tríceps en polea": "Triceps Pushdown",
    # Tuesday — Legs A
    "Sentadilla trasera": "Squat",
    "Prensa": "Leg Press",
    "Extensión de cuádriceps": "Leg Extensions",
    "Curl femoral tumbado": "Lying Leg Curl",
    "Gemelo de pie": "Standing Calf Raise",
    # Wednesday — Pull
    "Dominadas": "Pull-ups",
    "Remo con barra": "Barbell Row",
    "Remo polea baja neutro": "Seated Cable Row",
    "Face pull": "Face Pull",
    "Curl de bíceps con barra": "EZ Bar Curl",
    "Curl martillo": "Hammer Curl",
    # Thursday — Upper
    "Press inclinado con barra": "Incline Barbell Bench Press",
    "Remo mancuerna a una mano": "DB Row",
    "Press hombro sentado": "Seated DB Press",
    "Jalón al pecho": "Front Lat Pulldown",
    "Elevaciones laterales en polea": "Cable Lateral Raises",
    "Curl inclinado": "Incline DB Curl",
    "Extensión tríceps overhead": "Overhead Extension",
    # Friday — Lower
    "Peso muerto rumano": "Romanian Deadlift",
    "Hip thrust con barra": "Hip Thrust",
    "Sentadilla búlgara": "Bulgarian Split Squat",
    "Curl femoral sentado": "Seated Leg Curl",
    "Gemelo sentado": "Seated Calf Raise",
}


def _agent_literal(module: str, name: str):
    """Read a module-level literal out of the agent's source, without importing.

    Importing `sesion_viva` would drag in the bot's database session and its
    Telegram config. The values wanted here are plain literals, so the AST is
    both enough and immune to whatever the bot needs at import time.
    """
    path = AGENT_DIR / f"{module}.py"
    if not path.exists():
        pytest.skip(f"the Telegram coach is not checked out at {AGENT_DIR}")
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if name in targets and node.value is not None:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is gone from {path}")


def _coach_rest(spanish_name: str) -> int:
    """`sesion_viva.descanso_de`, re-expressed over the coach's own constants."""
    basics = _agent_literal("sesion_viva", "BASICOS")
    basic_s = _agent_literal("sesion_viva", "DESCANSO_BASICO")
    isolation_s = _agent_literal("sesion_viva", "DESCANSO_AISLAMIENTO")
    low = spanish_name.lower()
    return basic_s if any(b.lower() in low for b in basics) else isolation_s


def _coached_exercises() -> list[str]:
    sessions = _agent_literal("plan", "SESIONES")
    return [name for day in sessions.values() for name, _, _ in day["ejercicios"]]


def test_our_constants_are_the_coachs_constants():
    assert _agent_literal("sesion_viva", "DESCANSO_BASICO") == REST_COMPOUND_S
    assert _agent_literal("sesion_viva", "DESCANSO_AISLAMIENTO") == REST_ISOLATION_S


def test_every_coached_exercise_is_mapped():
    missing = [name for name in _coached_exercises() if name not in COACH_TO_APP]
    assert not missing, (
        "the coach's plan changed; map these to their canonical English keys "
        f"and re-check the rest times: {missing}"
    )


def test_rest_agrees_with_the_coach_for_every_exercise_in_the_plan():
    """The one that matters: same exercise, same seconds, both sides."""
    disagreements = []
    for spanish in _coached_exercises():
        english = COACH_TO_APP[spanish]
        theirs, mine = _coach_rest(spanish), rest_seconds(english)
        if theirs != mine:
            disagreements.append(f"{spanish} / {english}: coach {theirs}s, app {mine}s")
    assert not disagreements, "\n".join(disagreements)


def test_the_mapped_names_are_real_exercise_keys():
    """A typo in COACH_TO_APP would make the agreement test meaningless."""
    keys = {
        exercise_key(e)
        for routine in data.ROUTINES
        for days in routine.days_by_phase.values()
        for day in days
        for e in day.exercises
    }
    unknown = sorted(set(COACH_TO_APP.values()) - keys)
    assert not unknown, f"not exercises any routine prescribes: {unknown}"


# ── rest: classification and prescriptions ───────────────────────────────


@pytest.mark.parametrize(
    "exercise",
    ["Squat", "Barbell Bench Press", "Deadlift", "Romanian Deadlift", "Pull-ups", "Leg Press"],
)
def test_the_basics_get_the_long_rest(exercise):
    assert is_compound(exercise)
    assert rest_seconds(exercise) == REST_COMPOUND_S


@pytest.mark.parametrize(
    "exercise",
    ["Lateral Raises", "Leg Extensions", "Incline DB Curl", "Face Pull", "Seated Calf Raise"],
)
def test_accessories_get_the_short_rest(exercise):
    assert not is_compound(exercise)
    assert rest_seconds(exercise) == REST_ISOLATION_S


def test_the_patterns_do_not_leak_into_neighbouring_exercises():
    """The near-misses that a plain substring list would get wrong."""
    assert is_compound("Incline DB Press") and not is_compound("Incline DB Curl")
    assert is_compound("Leg Press") and not is_compound("Leg Extensions")
    assert is_compound("Barbell Row") and not is_compound("T-Bar Row")
    assert not is_compound("Calf Press + Seated")  # a calf raise, not a leg press


def test_rest_reads_the_prescription_off_the_full_string():
    """`data.py` hands over "Squat [5×12,10,8,8,8]", brackets and all."""
    assert rest_seconds("Squat [5×12,10,8,8,8]") == REST_COMPOUND_S
    assert rest_seconds("Hanging Abs [3×max]") == REST_ISOLATION_S
    assert rest_seconds("") == REST_ISOLATION_S


@pytest.mark.parametrize(
    ("prescription", "expected"),
    [
        # The recomposition routine: parses to the coach's own two numbers.
        ("3' compounds / 60-90s isolation", (180, 90)),
        # "sets" wins over "exercises": the timer counts between sets.
        ("1' sets / 2-3' exercises", (60, 60)),
        ("1'30\" sets / 3' exercises", (90, 90)),
        # A parenthesised ceiling is not the prescription.
        ("1'30\" sets (max 2')", (90, 90)),
        # Ranges resolve to their upper bound.
        ("60-90s sets", (90, 90)),
        ("45-60s sets", (60, 60)),
        ("2-3' sets", (180, 180)),
        ("45s sets", (45, 45)),
        # No keyword at all: the first duration named.
        ("2-2'30\" / 3' ex. / 1' on *", (150, 150)),
        ("Min. between blocks, 1-1'30\"", (90, 90)),
        (None, None),
        ("no numbers here", None),
    ],
)
def test_phase_rest_prose_is_parsed(prescription, expected):
    assert parse_prescribed_rest(prescription) == expected


def test_every_phase_in_every_routine_yields_a_usable_rest():
    """`Phase.rest` is free prose; none of it may fall through to nonsense."""
    for routine in data.ROUTINES:
        for phase in routine.phases:
            secs = rest_seconds_for_phase("Squat", phase)
            assert 30 <= secs <= 600, f"{routine.id} phase {phase.id}: {secs}s"


def test_an_unparseable_prescription_falls_back_to_the_defaults():
    assert rest_seconds("Squat", phase_rest="whenever you feel ready") == REST_COMPOUND_S
    assert rest_seconds("Lateral Raises", phase_rest=None) == REST_ISOLATION_S


def test_the_phase_prescription_overrides_the_defaults():
    recomp = next(r for r in data.ROUTINES if r.id == "recomp-ppl-ul")
    phase = recomp.phases[0]
    assert rest_seconds_for_phase("Squat", phase) == REST_COMPOUND_S
    assert rest_seconds_for_phase("Lateral Raises", phase) == REST_ISOLATION_S
    # A phase that prescribes something else is obeyed.
    assert rest_seconds("Squat", phase_rest="1' sets") == 60


# ── rest: set types ──────────────────────────────────────────────────────


def test_a_warmup_gets_a_short_rest():
    assert rest_seconds("Squat", set_type=SetType.WARMUP) == REST_AFTER_WARMUP_S
    assert rest_seconds("Squat", set_type="warmup") == REST_AFTER_WARMUP_S


def test_a_warmup_never_rests_longer_than_the_working_set():
    """A 45 s isolation prescription must not produce a 60 s warm-up rest."""
    assert rest_seconds("Lateral Raises", set_type=SetType.WARMUP, phase_rest="45s sets") == 45


def test_drop_sets_and_failure_sets_rest_like_normal_ones():
    """Harder, not different. Only warm-ups shorten the clock."""
    for kind in (SetType.NORMAL, SetType.DROPSET, SetType.FAILURE, None):
        assert rest_seconds("Squat", set_type=kind) == REST_COMPOUND_S


def test_rest_accepts_a_set_dict_through_set_type_of():
    """The shape workout.py has at hand: the set that was just logged."""
    last = tag_set(s(40, 10), SetType.WARMUP)
    assert rest_seconds("Squat", set_type=set_type_of(last)) == REST_AFTER_WARMUP_S
    assert rest_seconds("Squat", set_type=set_type_of(s(100, 5))) == REST_COMPOUND_S


@pytest.mark.parametrize(
    ("seconds", "text"), [(180, "3:00"), (90, "1:30"), (45, "0:45"), (0, "0:00"), (-5, "0:00")]
)
def test_format_rest(seconds, text):
    assert format_rest(seconds) == text


# ── prescripciones dichas en español ────────────────────────────────────


class TestDescribirPrescripciones:
    """`Phase.scheme` y `Phase.rest` son dato; esto es solo cómo se dicen.

    Se pintaban crudas: Plan enseñaba «Descanso: 1' sets / 2-3' exercises» y
    la lista de fases «Ascending Pyramid», en medio de una pantalla española.
    Traducirlas en `data.py` habría sido la trampa 22 — `parse_prescribed_rest`
    las lee, y las rutinas que el usuario escribe guardan esas cadenas en la
    base. Así que el dato se queda y lo que cambia es la presentación.
    """

    def test_el_descanso_traduce_las_palabras_y_respeta_los_numeros(self):
        from set_types import describir_descanso

        assert (
            describir_descanso("1' sets / 2-3' exercises")
            == "1' entre series / 2-3' entre ejercicios"
        )
        assert describir_descanso("1'30\" sets (max 2')") == "1'30\" entre series (máx 2')"
        assert (
            describir_descanso("3' compounds / 60-90s isolation")
            == "3' en compuestos / 60-90s en aislamiento"
        )

    def test_un_esquema_numerico_sale_intacto(self):
        """No hay nada que traducir en «4×5-6 (*=3×8)» y no se inventa nada."""
        from set_types import describir_esquema

        for crudo in (
            "3×12",
            "3×8-10",
            "4×5-6 (*=3×8)",
            "BI 4×8+10 / SS 4×10+10",
            "2×5-8 / 2×8-12",
        ):
            assert describir_esquema(crudo) == crudo

    def test_la_piramide_sale_en_orden_espanol(self):
        """Primer intento: «Ascendente Pirámide». El adjetivo va detrás."""
        from set_types import describir_esquema

        assert describir_esquema("Ascending Pyramid") == "Pirámide ascendente"

    def test_drop_sets_no_se_descompone(self):
        """Primer intento: «Drop entre series».

        `drop set` se dice así en un gimnasio español; es un término, no dos
        palabras. La tabla de frases corre antes que la de palabras y aparta
        lo que traduce para que la segunda pasada no vuelva a entrar.
        """
        from set_types import describir_esquema

        assert describir_esquema("Drop sets (e.g.: 10,8,6+12↓)") == "Drop sets (p. ej.: 10,8,6+12↓)"
        assert describir_esquema("drop set") == "drop set"

    def test_ninguna_fase_de_serie_sigue_enseñando_ingles(self):
        """El barrido completo: las 4 rutinas, todas sus fases.

        Es el test que importa. Los de arriba fijan casos concretos; este falla
        el día que alguien añada una fase con una palabra inglesa que la tabla
        no conoce, que es como llegaron estas dos.
        """
        import re

        import data
        from set_types import describir_descanso, describir_esquema

        # Palabras inglesas que aparecían en las cadenas de serie. No es una
        # lista de "inglés" en general: es lo que este vocabulario usa.
        sospechosas = re.compile(
            r"(?<![\w'])(sets?|exercises?|compounds?|isolation|between|blocks?|ascending"
            r"|descending|pyramid|max|min)(?![\w'])",
            re.IGNORECASE,
        )
        restos = []
        for rutina in data.ROUTINES:
            for fase in rutina.phases:
                for crudo, dicho in (
                    (fase.scheme, describir_esquema(fase.scheme)),
                    (fase.rest, describir_descanso(fase.rest)),
                ):
                    # «drop sets» está protegido a propósito y contiene "sets".
                    limpio = dicho.lower().replace("drop sets", "").replace("drop set", "")
                    if sospechosas.search(limpio):
                        restos.append((rutina.id, crudo, dicho))
        assert not restos, f"prescripciones que siguen en inglés en pantalla: {restos}"

    def test_no_revienta_con_vacio(self):
        from set_types import describir_descanso, describir_esquema

        assert describir_esquema(None) == ""
        assert describir_descanso("") == ""
