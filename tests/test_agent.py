"""The in-app coach, tested at the two places it can hurt Alex.

Everything here is offline. There is no network call, no API key and no
PostgreSQL — the store is a SQLite file in `tmp_path` and the model is a stub —
because a test suite that needs a paid API to run is a test suite that stops
being run.

Two properties carry the whole feature, and both are asserted rather than
assumed:

1. **No model turn can write to the history.** Not "the prompt says not to" —
   there is no tool that can. `test_ninguna_herramienta_escribe` proves it by
   running every tool against a store that raises on every write.
2. **The API key never leaves the device.** It is in the same key-value table
   that the backup exporter copies verbatim, which is exactly how a credential
   ends up inside a JSON file someone sends themselves over WhatsApp.

The rest is the sharp edges found by running the thing: a Spanish exercise name
that resolved, confidently, to the wrong lift; a proposal that would have
silently duplicated a row; a failed request that poisoned the next question.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import agent
import backup
from data import set_active_routine
from storage import SECRET_PREF_KEYS, Storage, WorkoutEntry, sqlite_url

CLAVE = "sk-ant-api03-" + "A" * 40
HOY = date.today()
AYER = HOY - timedelta(days=1)


@pytest.fixture
def store(tmp_path):
    set_active_routine("cambiatufisico")
    return Storage(db_url=sqlite_url(tmp_path / "coach.db"))


@pytest.fixture
def claves():
    set_active_routine("cambiatufisico")
    return agent.known_exercises()


# ── property 1: nothing here can write ────────────────────────────────────


class TiendaDeSoloLectura:
    """A store that fails loudly on any write. Wraps a real one for reads."""

    ESCRITURAS = (
        "save_workout",
        "replace_workout",
        "save_weight",
        "delete_weight",
        "set_pref",
        "set_profile",
        "set_session_note",
        "set_exercise_note",
        "set_session_duration",
        "import_all",
        "clear_workouts",
        "clear_all",
    )

    def __init__(self, real):
        self._real = real
        self.intentos: list[str] = []

    def __getattr__(self, name):
        if name in self.ESCRITURAS:

            def prohibido(*a, **k):
                self.intentos.append(name)
                raise AssertionError(f"A tool called {name}() — tools must never write.")

            return prohibido
        return getattr(self._real, name)


def test_ninguna_herramienta_escribe(store, claves):
    """THE ONE. Every tool, run for real, against a store that refuses writes.

    Asserted structurally rather than by reading the code, because "no tool
    writes" is the kind of invariant a helpful future edit breaks in one line.
    """
    store.set_pref("routine", "cambiatufisico")
    store.save_workout(
        WorkoutEntry(
            date=AYER.isoformat(),
            exercise="Barbell Bench Press",
            muscle_group="Chest",
            phase=2,
            sets=[{"weight": 60, "reps": 8}],
        )
    )
    store.save_weight(74.0, AYER.isoformat())

    blindada = TiendaDeSoloLectura(store)
    ctx = agent._Context(store=blindada, today=HOY, entries=store.get_all())

    llamadas = {
        "today": {},
        "exercise_history": {"exercise": "Barbell Bench Press"},
        "recent_training": {"days": 30},
        "body_weight": {"days": 60},
        "nutrition": {},
        "list_exercises": {},
    }
    for nombre, kwargs in llamadas.items():
        salida = agent._READ_TOOLS[nombre](ctx, **kwargs)
        assert isinstance(salida, str) and salida

    proponer = {
        "propose_workout_log": {
            "exercise": "Barbell Bench Press",
            "sets": [{"weight": 62.5, "reps": 8}],
        },
        "propose_body_weight": {"kg": 73.8},
    }
    for nombre, kwargs in proponer.items():
        texto, propuesta = agent._PROPOSE_TOOLS[nombre](ctx, **kwargs)
        assert propuesta is not None, f"{nombre} produced no proposal"
        assert "NOT saved" in texto, f"{nombre} did not tell the model it is unsaved"

    assert blindada.intentos == []


def test_una_propuesta_no_toca_la_base(store):
    """Building a proposal changes nothing. Only the Save button does."""
    antes = len(store.get_all())
    ctx = agent._Context(store=store, today=HOY, entries=store.get_all())

    _, propuesta = agent._tool_propose_workout(
        ctx, exercise="Squat", sets=[{"weight": 100, "reps": 5}]
    )
    assert propuesta is not None
    assert len(store.get_all()) == antes, "the proposal wrote a row on its own"

    agent.commit_proposal(store, propuesta)
    assert len(store.get_all()) == antes + 1, "Save did not write"


def test_guardar_dos_veces_no_duplica(store):
    """He taps Save, spots a typo, corrects it, taps Save again.

    `save_workout()` always INSERTs, so the naive path leaves two rows for one
    exercise on one day and doubles every metric that sums them — with nothing
    raising, because a superset legitimately produces two rows.
    """
    ctx = agent._Context(store=store, today=HOY, entries=store.get_all())
    _, primera = agent._tool_propose_workout(
        ctx, exercise="Squat", sets=[{"weight": 100, "reps": 5}]
    )
    agent.commit_proposal(store, primera)

    ctx = agent._Context(store=store, today=HOY, entries=store.get_all())
    texto, segunda = agent._tool_propose_workout(
        ctx, exercise="Squat", sets=[{"weight": 110, "reps": 5}]
    )
    assert segunda.replaces == 1, "the card would not have warned him"
    assert "already logged" in texto
    dicho = agent.commit_proposal(store, segunda)

    filas = [e for e in store.get_all() if e.exercise == "Squat"]
    assert len(filas) == 1, f"{len(filas)} rows for one exercise on one day"
    assert filas[0].sets[0]["weight"] == 110
    assert "Replaced" in dicho


# ── property 2: the key stays on the device ───────────────────────────────


def test_la_clave_no_viaja_en_el_backup(store):
    """A backup is a file Alex sends himself. The key must not be in it."""
    agent.save_key(store, CLAVE)
    store.set_pref("routine", "cambiatufisico")

    doc_v3 = backup.export_all(store)
    doc_v2 = store.export_all()

    for nombre, doc in (("v3", doc_v3), ("v2", doc_v2)):
        assert agent.API_KEY_PREF not in doc["prefs"], f"{nombre} exported the key"
        assert CLAVE not in str(doc), f"{nombre} carries the key somewhere else in the document"
        assert doc["prefs"].get("routine") == "cambiatufisico", f"{nombre} lost ordinary prefs"


def test_restaurar_no_borra_ni_importa_claves(store, tmp_path):
    """A restore keeps *this* device's key and refuses the document's.

    Both halves matter. Wiping it logs the coach out on the exact operation
    somebody performs on a new phone; importing one points his coach at whoever
    made the backup, and bills them.
    """
    agent.save_key(store, CLAVE)
    doc = backup.export_all(store)
    # A document written before the exclusion existed — the one case the
    # exporter cannot fix retroactively.
    doc["prefs"][agent.API_KEY_PREF] = "sk-ant-de-otra-persona-" + "B" * 30

    backup.import_all(store, doc, wipe=True)
    assert agent.read_key(store) == CLAVE, "the restore dropped or replaced his key"


def test_el_repositorio_no_lleva_ninguna_clave():
    """No key compiled in. The promise made to Alex, as a test.

    The pattern is a whole key, not the `sk-ant-` prefix: the prefix appears
    legitimately in a hint, a `startswith` and this file's own placeholder — all
    of which are short and none of which is a credential. Twenty-odd key
    characters after the prefix is not something anyone types by accident.

    The placeholders in this file are deliberately built by concatenation
    (`"sk-ant-api03-" + "A" * 40`) so that this test can be strict without
    having to know about itself.
    """
    import re
    from pathlib import Path

    parece_clave = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")
    raiz = Path(__file__).resolve().parent.parent
    sospechosos = []
    for archivo in sorted(raiz.rglob("*.py")):
        if set(archivo.parts) & {".venv", "build", "build_template", "__pycache__"}:
            continue
        for numero, linea in enumerate(
            archivo.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if parece_clave.search(linea):
                sospechosos.append(f"{archivo.relative_to(raiz)}:{numero}")
    assert not sospechosos, "a key-shaped literal is in the source: " + ", ".join(sospechosos)


def test_la_clave_se_enmascara():
    assert agent.mask_key(CLAVE).endswith("AAAA")
    assert CLAVE not in agent.mask_key(CLAVE)
    assert agent.mask_key("") == ""


@pytest.mark.parametrize(
    "malo",
    ["", "   ", "sk ant clave", "corto"],
)
def test_claves_imposibles_se_rechazan(malo):
    with pytest.raises(ValueError):
        agent.clean_key(malo)


def test_la_clave_esta_declarada_como_secreta():
    """The exclusion works by name. If the pref is renamed, this catches it."""
    assert agent.API_KEY_PREF in SECRET_PREF_KEYS


# ── the exercise name: the silent-history-split guard ─────────────────────


def test_un_nombre_en_espanol_no_resuelve_solo(claves):
    """ "press banca" scored a confident match on **Leg Press** — one shared word.

    A proposal built on that files chest work into his leg history, and nothing
    anywhere raises. Ambiguity has to refuse, not rank.
    """
    encontrado, opciones = agent.resolve_exercise("press banca", claves)
    assert encontrado is None
    assert opciones, "it refused but offered nothing, which is a dead end"


def test_un_nombre_ambiguo_no_elige_por_longitud(claves):
    """ "bench press" matched Smith ahead of Barbell on two characters of name.

    Smith machine and barbell are different lifts with different loads. The
    right answer is to ask.
    """
    encontrado, opciones = agent.resolve_exercise("bench press", claves)
    assert encontrado is None
    assert {"Smith Bench Press", "Barbell Bench Press"} <= set(opciones)


def test_un_nombre_exacto_si_resuelve(claves):
    assert agent.resolve_exercise("Barbell Bench Press", claves)[0] == "Barbell Bench Press"
    assert agent.resolve_exercise("Squat", claves)[0] == "Squat"


def test_un_ejercicio_inventado_se_rechaza(store):
    ctx = agent._Context(store=store, today=HOY, entries=[])
    texto, propuesta = agent._tool_propose_workout(
        ctx, exercise="Press de banca con mancuernas raro", sets=[{"weight": 30, "reps": 10}]
    )
    assert propuesta is None
    assert "Refused" in texto


def test_un_ejercicio_ambiguo_se_rechaza(store):
    ctx = agent._Context(store=store, today=HOY, entries=[])
    texto, propuesta = agent._tool_propose_workout(
        ctx, exercise="bench press", sets=[{"weight": 60, "reps": 8}]
    )
    assert propuesta is None
    assert "more than one" in texto


def test_el_grupo_se_escribe_como_lo_escribe_la_pantalla_de_entreno(store):
    """`entrenos.grupo` has one vocabulary, and it is the routine day's name.

    `views/workout.py` writes `muscle_group=day.name` — "Chest-Biceps",
    "Shoulder-Leg". An earlier version of `muscle_group_for` returned the
    *catalogue* group ("Leg"), so the coach and the training screen labelled the
    same squat two different ways. The column takes any string, so nothing
    raises; History just groups the session twice.
    """
    from data import active_routine

    routine = active_routine()
    dias = {d.name for fase in routine.days_by_phase.values() for d in fase}

    for nombre in ("Squat", "Barbell Bench Press", "Front Lat Pulldown"):
        grupo = agent.muscle_group_for(nombre)
        assert grupo in dias, f"{nombre} got {grupo!r}, which no routine day is called"


def test_un_ejercicio_fuera_de_la_rutina_no_queda_sin_grupo():
    """The fallback still has to say something, not leave the column blank."""
    assert agent.muscle_group_for("Push-ups")
    assert agent.muscle_group_for("Un ejercicio que no existe") == "Other"


def test_todo_nombre_conocido_es_su_propia_clave(claves):
    """`known_exercises()` must already be in `exercise_key()`'s alphabet.

    If it were not, a proposal would validate against one spelling and write
    another, which is the history split by a different route.
    """
    from exercises import exercise_key

    assert [n for n in claves if exercise_key(n) != n] == []


# ── the sets: bounds that stop a misheard number ──────────────────────────


@pytest.mark.parametrize(
    "series",
    [
        [],
        "no es una lista",
        [{"weight": 60}],  # sin repeticiones
        [{"weight": 60, "reps": 0}],
        [{"weight": 60, "reps": 200}],
        [{"weight": 5000, "reps": 8}],
        [{"weight": -5, "reps": 8}],
        [{"weight": 60, "reps": 8, "rir": 99}],
        [{"weight": 60, "reps": 8, "type": "supersaiyan"}],
        [{"weight": 60, "reps": 8}] * 31,
    ],
)
def test_series_imposibles_se_rechazan(series):
    with pytest.raises(ValueError):
        agent._clean_sets(series)


def test_una_serie_normal_no_gana_la_clave_type():
    """Absent "type" means normal, everywhere in this codebase. Keep it absent."""
    limpio = agent._clean_sets([{"weight": 60, "reps": 8, "type": "normal"}])
    assert "type" not in limpio[0]
    assert agent._clean_sets([{"weight": 60, "reps": 8, "type": "warmup"}])[0]["type"] == "warmup"


def test_el_peso_corporal_es_cero_no_un_error():
    assert agent._clean_sets([{"weight": 0, "reps": 12}])[0]["weight"] == 0


def test_una_fecha_futura_se_rechaza():
    with pytest.raises(ValueError):
        agent._parse_day((HOY + timedelta(days=1)).isoformat(), HOY)
    assert agent._parse_day("", HOY) == HOY
    assert agent._parse_day(AYER.isoformat(), HOY) == AYER


def test_un_peso_corporal_absurdo_se_rechaza(store):
    ctx = agent._Context(store=store, today=HOY, entries=[])
    assert agent._tool_propose_weight(ctx, kg=740)[1] is None
    assert agent._tool_propose_weight(ctx, kg="mucho")[1] is None
    assert agent._tool_propose_weight(ctx, kg=74.2)[1] is not None


# ── the loop, with the model stubbed out ──────────────────────────────────


class Bloque:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Uso:
    input_tokens = 100
    output_tokens = 50


class Respuesta:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = Uso()


class ClienteFalso:
    """Replays a scripted list of responses and records what it was sent."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.peticiones: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        # `messages` is the Coach's own list, passed by reference, and the loop
        # keeps appending to it after this call returns. Recording the live
        # object would mean every recorded request showed the *final* state of
        # the conversation — which is how a test can assert on a message the
        # request never contained. The real SDK serialises at call time; so does
        # this.
        registro = dict(kwargs)
        registro["messages"] = list(kwargs.get("messages") or [])
        self.peticiones.append(registro)
        if not self.guion:
            raise AssertionError("the loop asked for more turns than the script has")
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def _texto(t):
    return Bloque(type="text", text=t)


def _uso(nombre, entrada, ident="tu_1"):
    return Bloque(type="tool_use", name=nombre, input=entrada, id=ident)


def test_sin_clave_no_revienta_solo_avisa(store):
    coach = agent.Coach(store, today=HOY)
    respuesta = coach.ask("¿qué toca hoy?")
    assert not respuesta.ok
    assert "Settings" in respuesta.error
    assert coach.messages == [], "a failed turn left the question in the history"


def test_una_vuelta_con_herramienta_y_propuesta(store, monkeypatch):
    """The whole path: he speaks, a tool runs, a card appears, nothing is written."""
    agent.save_key(store, CLAVE)
    cliente = ClienteFalso(
        [
            Respuesta(
                [
                    _uso(
                        "propose_workout_log",
                        {"exercise": "Squat", "sets": [{"weight": 100, "reps": 5}]},
                    )
                ],
                "tool_use",
            ),
            Respuesta([_texto("Te lo dejo en pantalla, dale a guardar si está bien.")]),
        ]
    )
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    coach = agent.Coach(store, today=HOY)
    respuesta = coach.ask("hice 5 series... digo, una serie de sentadilla a 100 por 5")

    assert respuesta.ok, respuesta.error
    assert respuesta.proposal is not None
    assert respuesta.proposal.exercise == "Squat"
    assert respuesta.tool_calls == ("propose_workout_log",)
    assert store.get_all() == [], "the turn wrote to the database"
    assert respuesta.input_tokens == 200 and respuesta.output_tokens == 100


def test_el_prompt_del_sistema_va_cacheado(store, monkeypatch):
    """A cache breakpoint on a byte-stable prefix, or every follow-up pays full price."""
    agent.save_key(store, CLAVE)
    cliente = ClienteFalso([Respuesta([_texto("hola")])])
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    agent.Coach(store, today=HOY).ask("hola")
    enviado = cliente.peticiones[0]
    assert enviado["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert enviado["output_config"] == {"effort": agent.DEFAULT_EFFORT}
    assert enviado["model"] == agent.DEFAULT_MODEL
    # The date must not be interpolated into the system prompt: it would change
    # the cached prefix at midnight and re-bill the whole thing.
    assert HOY.isoformat() not in enviado["system"][0]["text"]


def test_un_fallo_de_red_no_envenena_la_siguiente_pregunta(store, monkeypatch):
    """A half-built exchange left behind makes the *next* question fail too."""
    agent.save_key(store, CLAVE)
    cliente = ClienteFalso(
        [
            Respuesta([_uso("today", {})], "tool_use"),
            RuntimeError("la red se cayó"),
            Respuesta([_texto("todo bien")]),
        ]
    )
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    coach = agent.Coach(store, today=HOY)
    primera = coach.ask("¿qué toca?")
    assert not primera.ok
    assert coach.messages == [], f"left {len(coach.messages)} orphaned messages behind"

    segunda = coach.ask("¿y ahora?")
    assert segunda.ok, segunda.error


def test_un_rechazo_del_modelo_se_cuenta_no_se_traga(store, monkeypatch):
    """`stop_reason: refusal` arrives as HTTP 200 with no text. Reading content[0] crashes."""
    agent.save_key(store, CLAVE)
    cliente = ClienteFalso([Respuesta([], "refusal")])
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    respuesta = agent.Coach(store, today=HOY).ask("algo raro")
    assert not respuesta.ok
    assert "declined" in respuesta.error


def test_el_bucle_no_gira_para_siempre(store, monkeypatch):
    agent.save_key(store, CLAVE)
    cliente = ClienteFalso([Respuesta([_uso("today", {})], "tool_use")] * 20)
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    respuesta = agent.Coach(store, today=HOY).ask("da vueltas")
    assert not respuesta.ok
    assert len(respuesta.tool_calls) == agent.MAX_TOOL_ROUNDS


def test_una_herramienta_rota_no_tumba_la_vuelta(store, monkeypatch):
    """A tool that raises must come back as a tool_result, not kill the answer."""
    agent.save_key(store, CLAVE)

    def explota(ctx, **kw):
        raise RuntimeError("boom")

    monkeypatch.setitem(agent._READ_TOOLS, "today", explota)
    cliente = ClienteFalso(
        [Respuesta([_uso("today", {})], "tool_use"), Respuesta([_texto("sigo aquí")])]
    )
    monkeypatch.setattr(agent, "_client", lambda key: cliente)

    respuesta = agent.Coach(store, today=HOY).ask("¿qué toca?")
    assert respuesta.ok
    resultados = cliente.peticiones[1]["messages"][-1]["content"]
    assert "boom" in resultados[0]["content"]


def test_el_recorte_no_deja_un_tool_use_huerfano(store):
    """The API rejects an assistant `tool_use` whose `tool_result` was cut away."""
    coach = agent.Coach(store, today=HOY)
    for i in range(20):
        coach.messages.append({"role": "user", "content": f"pregunta {i}"})
        coach.messages.append({"role": "assistant", "content": [_uso("today", {}, f"t{i}")]})
        coach.messages.append(
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}],
            }
        )
        coach.messages.append({"role": "assistant", "content": [_texto("respuesta")]})
    coach._trim()

    assert coach.messages, "trimming emptied the conversation"
    primero = coach.messages[0]
    assert primero["role"] == "user"
    assert not agent._is_tool_result(primero), "the window opens on an orphaned tool_result"
    assert len(coach.messages) <= agent.MAX_HISTORY_TURNS


# ── what the tools actually say ───────────────────────────────────────────


def test_la_recomendacion_viene_de_progression(store):
    """The model must relay the app's number, not invent a second one."""
    for semana in range(3):
        store.save_workout(
            WorkoutEntry(
                date=(HOY - timedelta(days=7 * (3 - semana))).isoformat(),
                exercise="Squat",
                muscle_group="Legs",
                phase=2,
                sets=[{"weight": 100, "reps": 10}] * 4,
            )
        )
    ctx = agent._Context(store=store, today=HOY, entries=store.get_all())
    salida = agent._tool_exercise_history(ctx, exercise="Squat")

    assert "recommendation" in salida
    assert "do not compute a different one" in salida


def test_el_peso_corporal_da_media_y_ritmo(store):
    """Needs TWO weigh-ins, and that is the whole point of this test.

    The trend branch only runs with at least two points, so a one-row fixture
    walks straight past it. It was hiding a `KeyError`: this code read
    `["average"]` from `analytics.moving_average`, which returns `{"date", "kg"}`.
    Every real question about body weight would have crashed the turn.
    """
    for dias, kg in ((21, 73.0), (14, 73.4), (7, 73.9), (0, 74.2)):
        store.save_weight(kg, (HOY - timedelta(days=dias)).isoformat())

    ctx = agent._Context(store=store, today=HOY, entries=[])
    salida = agent._tool_body_weight(ctx)

    assert "7-day rolling average" in salida
    assert "kg/week" in salida, "no weekly rate — the plan steers on that number"
    assert "74.2" in salida


def test_el_ritmo_del_coach_es_el_mismo_que_el_del_perfil(store):
    """One number, one implementation. Three screens must not disagree.

    The plan adjusts calories at ±0.3 kg/week. Two implementations of that
    figure — the coach's and the Profile screen's — differed in what they
    compared against, so the same weigh-ins produced two rates and neither
    looked wrong.
    """
    import analytics
    from views.profile import ProfileView

    for dias, kg in ((28, 72.6), (21, 73.0), (14, 73.4), (7, 73.9), (0, 74.2)):
        store.save_weight(kg, (HOY - timedelta(days=dias)).isoformat())
    pesos = store.get_weights()

    vista = ProfileView(_pagina(store), store)
    assert vista._trend(pesos) == analytics.weight_trend(pesos, min_days=vista.MIN_TREND_DAYS)


def test_hoy_dice_el_plan_y_lo_ya_registrado(store):
    store.save_workout(
        WorkoutEntry(
            date=HOY.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=2,
            sets=[{"weight": 100, "reps": 5}],
        )
    )
    ctx = agent._Context(store=store, today=HOY, entries=store.get_all())
    salida = agent._tool_today(ctx)

    assert HOY.isoformat() in salida
    assert "CambiaTuFísico" in salida
    assert "Already logged today" in salida and "Squat" in salida


def test_listar_ejercicios_dice_que_son_los_unicos(store):
    ctx = agent._Context(store=store, today=HOY, entries=[])
    salida = agent._tool_list_exercises(ctx)
    assert "only names that may be logged" in salida
    assert "Squat" in salida


def test_las_herramientas_declaradas_existen_todas():
    """A schema with no handler is a tool that always errors at runtime."""
    declaradas = {t["name"] for t in agent.tool_schemas()}
    implementadas = set(agent._READ_TOOLS) | set(agent._PROPOSE_TOOLS)
    assert declaradas == implementadas


def test_el_esquema_avisa_de_que_no_guarda():
    """The description is the model's only contract. It has to say it plainly."""
    for esquema in agent.tool_schemas():
        if esquema["name"].startswith("propose_"):
            assert "does NOT save" in esquema["description"] or "NOT save" in esquema["description"]


def test_el_prompt_prohibe_decir_que_esta_guardado(store):
    prompt = agent.build_system_prompt(store, HOY)
    assert "never tell him something is saved" in prompt
    assert "cannot write to his log" in prompt


# ── the screen, in the states where a view actually breaks ────────────────


def _pagina(store):
    from unittest.mock import MagicMock

    page = MagicMock()
    page.width, page.height = 400, 800
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
        "store": store,
    }
    return page


def test_la_pantalla_se_dibuja_sin_clave(store):
    """The state every install starts in. It must offer the way out, not a blank."""
    from views.agent_view import AgentView

    vista = AgentView(_pagina(store), store)
    vista.on_show()
    assert vista.build() is not None


def test_la_pantalla_se_dibuja_con_la_tarjeta_de_confirmacion(store):
    """The proposal card is the one control that has to be right.

    Building it is not decoration: an unrendered card is a proposal Alex cannot
    accept or reject, and the turn that produced it is stuck on screen.
    """
    from views.agent_view import AgentView

    agent.save_key(store, CLAVE)
    vista = AgentView(_pagina(store), store)
    vista.on_show()

    ctx = agent._Context(store=store, today=HOY, entries=[])
    _, vista.pending = agent._tool_propose_workout(
        ctx, exercise="Squat", sets=[{"weight": 100, "reps": 5}]
    )
    vista.bubbles = [
        agent_bubble("me", "hice sentadilla"),
        agent_bubble("coach", "te lo dejo en pantalla"),
    ]
    assert vista.build() is not None

    _, vista.pending = agent._tool_propose_weight(ctx, kg=74.2)
    assert vista.build() is not None


def test_atras_descarta_la_tarjeta_antes_de_salir(store):
    """A pending card is unfinished business: back dismisses it, not the screen."""
    from views.agent_view import AgentView

    agent.save_key(store, CLAVE)
    vista = AgentView(_pagina(store), store)
    vista.on_show()
    ctx = agent._Context(store=store, today=HOY, entries=[])
    _, vista.pending = agent._tool_propose_workout(
        ctx, exercise="Squat", sets=[{"weight": 100, "reps": 5}]
    )

    assert vista.handle_back() is True
    assert vista.pending is None, "back left the card on screen"
    assert vista.handle_back() is True  # second press leaves the screen


def agent_bubble(who, text):
    from views.agent_view import Bubble

    return Bubble(who, text)


#: Two dropdowns side by side get about half a phone's width each, which is
#: roughly this many characters at the size Settings uses. Flet does not
#: shorten an option that does not fit — it cuts it.
MAX_CARACTERES_DESPLEGABLE = 12


def test_las_opciones_del_desplegable_caben(store):
    """ "Opus 5 — best, $5/$25" rendered as **"Opus 5 — be"** on the phone.

    With "Low — faste" next to it. Same failure as the "Heig" height field, and
    invisible from the desktop window, which is wide enough for both.
    """

    import flet as ft

    from views.profile import ProfileView

    vista = ProfileView(_pagina(store), store)
    vista.on_show()
    tarjeta = vista._coach_section()

    largas = []

    def recorrer(control):
        if isinstance(control, ft.Dropdown):
            for opcion in control.options or []:
                etiqueta = opcion.text or opcion.key or ""
                if len(etiqueta) > MAX_CARACTERES_DESPLEGABLE:
                    largas.append(etiqueta)
        for nombre in ("content", "controls"):
            hijo = getattr(control, nombre, None)
            if isinstance(hijo, list):
                for uno in hijo:
                    recorrer(uno)
            elif hijo is not None and not isinstance(hijo, str):
                recorrer(hijo)

    recorrer(tarjeta)
    assert not largas, f"these would be cut off on a phone: {largas}"


def test_los_precios_de_ajustes_y_los_del_coste_son_los_mismos():
    """Two price tables, one truth. Settings shows them; `estimate_cost` bills them.

    Split across two modules because one is prose for a screen and the other is
    arithmetic, which is exactly how they drift: the visible number would keep
    saying $5/$25 while the running cost under each answer used something else.
    """
    import re

    from views.profile import MODEL_PRICES

    for modelo, texto in MODEL_PRICES.items():
        entrada, salida = (float(x) for x in re.findall(r"\$(\d+)", texto))
        una_respuesta = agent.Reply(text="", input_tokens=1_000_000, output_tokens=0)
        otra = agent.Reply(text="", input_tokens=0, output_tokens=1_000_000)
        assert agent.estimate_cost(una_respuesta, modelo) == pytest.approx(entrada), modelo
        assert agent.estimate_cost(otra, modelo) == pytest.approx(salida), modelo
