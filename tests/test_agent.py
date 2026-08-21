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

import json
from datetime import date, timedelta

import pytest

import agent
import backup
import openrouter
from data import set_active_routine
from storage import SECRET_PREF_KEYS, Storage, WorkoutEntry, sqlite_url

CLAVE = "sk-or-v1-" + "a" * 48
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
    assert "Reemplazado" in dicho


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
    doc["prefs"][agent.API_KEY_PREF] = "sk-or-v1-de-otra-persona-" + "b" * 30

    backup.import_all(store, doc, wipe=True)
    assert agent.read_key(store) == CLAVE, "the restore dropped or replaced his key"


def test_el_repositorio_no_lleva_ninguna_clave():
    """No key compiled in. The promise made to Alex, as a test.

    The pattern is a whole key, not the `sk-ant-` prefix: the prefix appears
    legitimately in a hint, a `startswith` and this file's own placeholder — all
    of which are short and none of which is a credential. Twenty-odd key
    characters after the prefix is not something anyone types by accident.

    The placeholders in this file are deliberately built by concatenation
    (`"sk-or-v1-" + "a" * 48`) so that this test can be strict without having to
    know about itself. Both prefixes are checked — the coach moved to OpenRouter
    but an Anthropic key left behind in a file would be just as leaked.
    """
    import re
    from pathlib import Path

    parece_clave = re.compile(r"sk-(?:ant|or)-[A-Za-z0-9_\-]{20,}")
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
    assert agent.mask_key(CLAVE).endswith("aaaa")
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


class RespuestaFalsa:
    """What `_post_chat` would have returned, without a network."""

    def __init__(self, contenido=None, llamadas=None, finish="stop", cost=0.0):
        mensaje = {"role": "assistant", "content": contenido}
        if llamadas:
            mensaje["tool_calls"] = llamadas
        self.cuerpo = {
            "id": "gen-fake",
            "model": "anthropic/claude-sonnet-5",
            "choices": [{"index": 0, "message": mensaje, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost},
        }


def _llamada(nombre, argumentos, ident="call_1"):
    """A tool call in OpenRouter's shape.

    `arguments` is serialised with `json.dumps` ON PURPOSE. The API sends a JSON
    **string**, and a fake that passes a dict would let a client that forgets to
    parse it sail through the tests and then see every tool called with no
    arguments against the real endpoint.
    """
    return {
        "id": ident,
        "type": "function",
        "function": {"name": nombre, "arguments": json.dumps(argumentos)},
    }


class TransporteFalso:
    """Replays scripted responses and records exactly what was posted."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.peticiones: list[dict] = []

    def __call__(self, payload, api_key, timeout=90.0):
        # Deep-ish copy: `messages` is the Coach's own list and the loop keeps
        # appending to it after this returns, so recording the live object would
        # show every request holding the FINAL conversation.
        registro = dict(payload)
        registro["messages"] = [dict(m) for m in payload.get("messages") or []]
        registro["_key"] = api_key
        self.peticiones.append(registro)
        if not self.guion:
            raise AssertionError("the loop asked for more turns than the script has")
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente.cuerpo


def test_sin_clave_no_revienta_solo_avisa(store):
    coach = agent.Coach(store, today=HOY)
    respuesta = coach.ask("¿qué toca hoy?")
    assert not respuesta.ok
    assert "Ajustes" in respuesta.error
    assert coach.messages == [], "a failed turn left the question in the history"


def test_una_vuelta_con_herramienta_y_propuesta(store, monkeypatch):
    """The whole path: he speaks, a tool runs, a card appears, nothing is written."""
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(
                llamadas=[
                    _llamada(
                        "propose_workout_log",
                        {"exercise": "Squat", "sets": [{"weight": 100, "reps": 5}]},
                    )
                ],
                finish="tool_calls",
            ),
            RespuestaFalsa("Te lo dejo en pantalla, dale a guardar si está bien.", cost=0.0042),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)

    coach = agent.Coach(store, today=HOY)
    respuesta = coach.ask("hice una serie de sentadilla a 100 por 5")

    assert respuesta.ok, respuesta.error
    assert respuesta.proposal is not None and respuesta.proposal.exercise == "Squat"
    assert respuesta.tool_calls == ("propose_workout_log",)
    assert store.get_all() == [], "the turn wrote to the database"
    assert respuesta.input_tokens == 200 and respuesta.output_tokens == 100
    assert respuesta.charged == pytest.approx(0.0042), "OpenRouter's own price was dropped"


def test_los_argumentos_llegan_como_json_de_texto(store, monkeypatch):
    """`function.arguments` is a STRING. Reading it as a dict loses every argument.

    The failure is silent: the tool runs with no arguments, refuses, and the
    coach says it could not find the exercise — which reads like a matching bug,
    not a parsing one.
    """
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(
                llamadas=[_llamada("exercise_history", {"exercise": "Squat", "limit": 3})],
                finish="tool_calls",
            ),
            RespuestaFalsa("Vas bien."),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)
    agent.Coach(store, today=HOY).ask("¿cómo voy de sentadilla?")

    resultado = transporte.peticiones[1]["messages"][-1]
    assert resultado["role"] == "tool"
    assert "Squat" in resultado["content"], "the arguments never reached the tool"
    assert resultado["tool_call_id"] == "call_1"


def test_la_peticion_tiene_la_forma_de_openrouter(store, monkeypatch):
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso([RespuestaFalsa("hola")])
    monkeypatch.setattr(agent, "_post_chat", transporte)

    agent.Coach(store, today=HOY).ask("hola")
    enviado = transporte.peticiones[0]

    # The system prompt is a MESSAGE, not a top-level field. Getting this wrong
    # gives a coach with no instructions rather than an error.
    assert enviado["messages"][0]["role"] == "system"
    assert "IronFlet" in enviado["messages"][0]["content"]
    assert "system" not in enviado, "sent the Anthropic way; OpenRouter would ignore it"
    assert enviado["model"] == agent.DEFAULT_MODEL
    assert enviado["usage"] == {"include": True}, "no cost asked for, so none comes back"
    # Tools must ride on EVERY request, not just the first.
    assert enviado["tools"] and enviado["tools"][0]["type"] == "function"
    assert "parameters" in enviado["tools"][0]["function"]
    # The date must not be interpolated into the system prompt: it would change
    # the cached prefix at midnight and re-bill the whole thing.
    assert HOY.isoformat() not in enviado["messages"][0]["content"]


def test_las_herramientas_van_en_todas_las_vueltas(store, monkeypatch):
    """OpenRouter validates the tool schema per call — omit it and the second
    round has no tools to call."""
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(llamadas=[_llamada("today", {})], finish="tool_calls"),
            RespuestaFalsa("Hoy toca pecho."),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)
    agent.Coach(store, today=HOY).ask("¿qué toca?")

    assert len(transporte.peticiones) == 2
    for i, envio in enumerate(transporte.peticiones):
        assert envio.get("tools"), f"request {i + 1} carried no tools"


def test_un_fallo_de_red_no_envenena_la_siguiente_pregunta(store, monkeypatch):
    """A half-built exchange left behind makes the *next* question fail too."""
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(llamadas=[_llamada("today", {})], finish="tool_calls"),
            agent.ApiError("la red se cayó"),
            RespuestaFalsa("todo bien"),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)

    coach = agent.Coach(store, today=HOY)
    primera = coach.ask("¿qué toca?")
    assert not primera.ok
    assert coach.messages == [], f"left {len(coach.messages)} orphaned messages behind"

    segunda = coach.ask("¿y ahora?")
    assert segunda.ok, segunda.error


def test_un_filtro_de_contenido_se_cuenta_no_se_traga(store, monkeypatch):
    agent.save_key(store, CLAVE)
    monkeypatch.setattr(
        agent, "_post_chat", TransporteFalso([RespuestaFalsa("", finish="content_filter")])
    )
    respuesta = agent.Coach(store, today=HOY).ask("algo raro")
    assert not respuesta.ok and "no quiso" in respuesta.error


def test_una_respuesta_cortada_se_marca(store, monkeypatch):
    agent.save_key(store, CLAVE)
    monkeypatch.setattr(
        agent, "_post_chat", TransporteFalso([RespuestaFalsa("Media frase", finish="length")])
    )
    respuesta = agent.Coach(store, today=HOY).ask("cuéntame")
    assert respuesta.ok and "cortado" in respuesta.text


def test_el_bucle_no_gira_para_siempre(store, monkeypatch):
    agent.save_key(store, CLAVE)
    monkeypatch.setattr(
        agent,
        "_post_chat",
        TransporteFalso(
            [RespuestaFalsa(llamadas=[_llamada("today", {})], finish="tool_calls")] * 20
        ),
    )
    respuesta = agent.Coach(store, today=HOY).ask("da vueltas")
    assert not respuesta.ok
    assert len(respuesta.tool_calls) == agent.MAX_TOOL_ROUNDS


def test_una_herramienta_rota_no_tumba_la_vuelta(store, monkeypatch):
    """A tool that raises must come back as a tool message, not kill the answer."""
    agent.save_key(store, CLAVE)

    def explota(ctx, **kw):
        raise RuntimeError("boom")

    monkeypatch.setitem(agent._READ_TOOLS, "today", explota)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(llamadas=[_llamada("today", {})], finish="tool_calls"),
            RespuestaFalsa("sigo aquí"),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)

    respuesta = agent.Coach(store, today=HOY).ask("¿qué toca?")
    assert respuesta.ok
    assert "boom" in transporte.peticiones[1]["messages"][-1]["content"]


def test_varias_herramientas_en_paralelo_cada_una_su_respuesta(store, monkeypatch):
    """One assistant turn, several calls, one `tool` message each keyed by id."""
    agent.save_key(store, CLAVE)
    transporte = TransporteFalso(
        [
            RespuestaFalsa(
                llamadas=[
                    _llamada("today", {}, "call_a"),
                    _llamada("recent_training", {"days": 7}, "call_b"),
                ],
                finish="tool_calls",
            ),
            RespuestaFalsa("Ahí lo tienes."),
        ]
    )
    monkeypatch.setattr(agent, "_post_chat", transporte)
    agent.Coach(store, today=HOY).ask("resúmeme la semana")

    mensajes = transporte.peticiones[1]["messages"]
    respuestas = [m for m in mensajes if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in respuestas] == ["call_a", "call_b"]


def test_el_recorte_no_deja_llamadas_huerfanas(store):
    """The API rejects an assistant `tool_calls` whose `tool` replies were cut."""
    coach = agent.Coach(store, today=HOY)
    for i in range(20):
        coach.messages.append({"role": "user", "content": f"pregunta {i}"})
        coach.messages.append(
            {"role": "assistant", "content": "", "tool_calls": [_llamada("today", {}, f"t{i}")]}
        )
        coach.messages.append({"role": "tool", "tool_call_id": f"t{i}", "content": "ok"})
        coach.messages.append({"role": "assistant", "content": "respuesta"})
    coach._trim()

    assert coach.messages, "trimming emptied the conversation"
    assert coach.messages[0]["role"] == "user", "the window opens mid-exchange"
    assert len(coach.messages) <= agent.MAX_HISTORY_TURNS


def test_el_coste_real_gana_a_la_estimacion(store):
    """OpenRouter knows what it charged. A price table in this repo never will."""
    barato = openrouter.Model("x/y", "Y", 1000, prompt_price=1.0, completion_price=2.0)
    con_precio = agent.Reply(text="", input_tokens=1_000_000, output_tokens=0)
    assert agent.estimate_cost(con_precio, barato) == pytest.approx(1.0)

    cobrado = agent.Reply(text="", input_tokens=1_000_000, output_tokens=0, charged=0.37)
    assert agent.estimate_cost(cobrado, barato) == pytest.approx(0.37)


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
    declaradas = {t["function"]["name"] for t in agent.tool_schemas()}
    implementadas = set(agent._READ_TOOLS) | set(agent._PROPOSE_TOOLS)
    assert declaradas == implementadas


def test_el_esquema_avisa_de_que_no_guarda():
    """The description is the model's only contract. It has to say it plainly."""
    for envoltorio in agent.tool_schemas():
        esquema = envoltorio["function"]
        if esquema["name"].startswith("propose_"):
            assert "NOT save" in esquema["description"]


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


#: A dropdown gets roughly this many characters on a phone before Flet cuts the
#: label rather than shortening it.
MAX_CARACTERES_DESPLEGABLE = 22


def test_las_opciones_del_desplegable_caben(store, monkeypatch):
    """ "Opus 5 — best, $5/$25" rendered as **"Opus 5 — be"** on the phone.

    Same failure as the "Heig" height field, and invisible from a desktop window.
    Now the labels come from the live catalogue, so the risk moved rather than
    went away: a model id is `vendor/name` and some are very long.
    """
    import flet as ft

    from views.profile import ProfileView

    monkeypatch.setattr(openrouter, "models_or_empty", lambda **k: (_catalogo(), False))
    vista = ProfileView(_pagina(store), store)
    vista.on_show()

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

    recorrer(vista._coach_section())
    assert not largas, f"these would be cut off on a phone: {largas}"


def _catalogo():
    """A small stand-in for OpenRouter's 348 tool-capable models."""
    return [openrouter.Model(i, i.split("/")[-1], 200000, 1.0, 5.0) for i in openrouter.CURATED]


def test_ajustes_se_dibuja_sin_red(store, monkeypatch):
    """A phone in a basement must still show the dropdown and the stored choice.

    The catalogue is a network call inside a settings screen — the one screen
    someone opens *because* something is wrong. If it raised, the setting that
    fixes it would be unreachable.
    """
    from views.profile import ProfileView

    monkeypatch.setattr(openrouter, "models_or_empty", lambda **k: ([], True))
    vista = ProfileView(_pagina(store), store)
    vista.on_show()
    assert vista._coach_section() is not None


def test_solo_se_ofrecen_modelos_con_herramientas():
    """A model without tool support looks fine and then breaks the coach.

    It cannot read one fact about Alex's training without tool calls, so it
    would answer from imagination rather than say it cannot.
    """
    payload = {
        "data": [
            {
                "id": "con/herramientas",
                "context_length": 1000,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "supported_parameters": ["tools", "temperature"],
            },
            {
                "id": "sin/herramientas",
                "context_length": 1000,
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["temperature"],
            },
        ]
    }
    ids = [m.id for m in openrouter.parse_models(payload)]
    assert ids == ["con/herramientas"]


def test_los_precios_se_convierten_a_millones():
    """OpenRouter quotes per token. "$0.000003" tells nobody anything."""
    modelo = openrouter.parse_models(
        {
            "data": [
                {
                    "id": "x/y",
                    "context_length": 10,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "supported_parameters": ["tools"],
                }
            ]
        }
    )[0]
    assert modelo.prompt_price == pytest.approx(3.0)
    assert modelo.completion_price == pytest.approx(15.0)
    assert modelo.price_label() == "$3 / $15 por M"


def test_un_catalogo_roto_no_vacia_la_lista():
    """One bad row out of 417 must not empty the dropdown."""
    payload = {
        "data": [
            {"nope": True},
            "no soy un objeto",
            {
                "id": "bien/hecho",
                "context_length": "no es un número",
                "pricing": {"prompt": "gratis", "completion": None},
                "supported_parameters": ["tools"],
            },
        ]
    }
    modelos = openrouter.parse_models(payload)
    assert [m.id for m in modelos] == ["bien/hecho"]
    assert modelos[0].context == 0 and modelos[0].prompt_price == 0.0


def test_ya_no_hay_una_tabla_de_precios_en_el_codigo():
    """The two hardcoded price tables are gone, and must not come back.

    There were two — prose in `views/profile.py` and arithmetic in
    `agent.estimate_cost` — holding the same numbers, which is exactly how the
    price on the screen and the price on the bill drift apart. OpenRouter
    publishes both per model and reports what it actually charged, so nothing in
    this repo has an opinion about what a model costs any more.
    """
    from pathlib import Path

    import views.profile as perfil

    assert not hasattr(perfil, "MODEL_PRICES"), "the settings price table grew back"
    fuente = (Path(__file__).resolve().parent.parent / "agent.py").read_text(encoding="utf-8")
    assert '"claude-opus-5": (' not in fuente, "a rate table grew back in agent.py"


def test_las_pantallas_no_nombran_al_proveedor_viejo():
    """No screen may still say "Anthropic API key" or hint `sk-ant-`.

    Three of them did after the move to OpenRouter, and they survived a green
    test suite and a device check — the app worked perfectly while telling Alex
    to paste the wrong kind of key into it. Caught on a screenshot. Wrong words
    on a settings screen are a bug like any other; this is the cheap guard.
    """
    from pathlib import Path

    vistas = Path(__file__).resolve().parent.parent / "views"
    culpables = []
    for archivo in sorted(vistas.glob("*.py")):
        for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            desnuda = linea.strip()
            if desnuda.startswith("#"):
                continue  # a comment is documentation, not something Alex reads
            if "Anthropic" in linea or "sk-ant-" in linea:
                culpables.append(f"{archivo.name}:{numero}: {desnuda[:70]}")
    assert not culpables, "screens still naming the old provider:\n" + "\n".join(culpables)


# ── fotos en el chat y objetivos semanales ─────────────────────────────────


def _foto_jpeg(tmp_path):
    from PIL import Image

    ruta = tmp_path / "2026-08-21.jpg"
    Image.new("RGB", (60, 90), (90, 60, 60)).save(ruta, format="JPEG")
    return str(ruta)


def test_propose_week_targets_valida_y_apunta_al_lunes(store):
    ctx = agent._Context(store=store, today=date(2026, 8, 21))  # viernes
    told, propuesta = agent._tool_propose_week_targets(
        ctx, kcal=2400, protein_g=170, fat_g=70, carbs_g=250, note="Semana de ajuste."
    )
    assert propuesta is not None
    assert propuesta.starts_on == date(2026, 8, 24), "el lunes que viene, no mitad de semana"
    assert "NOT saved" in told

    assert (
        agent._tool_propose_week_targets(ctx, kcal=200, protein_g=170, fat_g=70, carbs_g=250)[1]
        is None
    )
    assert (
        agent._tool_propose_week_targets(ctx, kcal="mucho", protein_g=1, fat_g=1, carbs_g=1)[1]
        is None
    )


def test_commit_de_objetivos_escribe_targets_versionados(store):
    import nutrition

    propuesta = agent.MealTargetsProposal(
        starts_on=date(2026, 8, 24), kcal=2400, protein=170, fat=70, carbs=250, note="ajuste"
    )
    mensaje = agent.commit_proposal(store, propuesta)
    assert "2026-08-24" in mensaje
    objetivo = nutrition.targets_for(store, date(2026, 8, 25))
    assert objetivo and objetivo["kcal"] == 2400 and objetivo["protein"] == 170
    # Los días anteriores al inicio no se reescriben: versionado, no mutación.
    assert nutrition.targets_for(store, date(2026, 8, 23)) != objetivo


def test_progress_photos_lista_fechas_sin_bytes(store, tmp_path):
    import fotos as fotos_mod

    carpeta = tmp_path / "progreso"
    carpeta.mkdir()
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (50, 50), (10, 10, 10)).save(buf, format="JPEG")
    fotos_mod.guardar(store, buf.getvalue(), on_date=HOY.isoformat(), base=carpeta)
    store.save_weight(82.0, HOY.isoformat())

    ctx = agent._Context(store=store, today=HOY)
    texto = agent._tool_progress_photos(ctx)
    assert HOY.isoformat() in texto
    assert "82" in texto
    assert "base64" not in texto and ".jpg" not in texto, (
        "la herramienta no debe filtrar rutas ni bytes"
    )


def test_imagen_con_modelo_sin_vision_se_rechaza_sin_red(store, tmp_path):
    agent.save_key(store, CLAVE)
    store.set_pref(agent.VISION_PREF, "0")
    coach = agent.Coach(store, today=HOY)
    r = coach.ask("mira esto", image_path=_foto_jpeg(tmp_path))
    assert r.error and "📷" in r.error
    assert coach.messages == [], "el turno rechazado no debe quedar en el historial"


def test_imagen_viaja_multiparte_y_se_colapsa_despues(store, monkeypatch, tmp_path):
    agent.save_key(store, CLAVE)
    store.set_pref(agent.VISION_PREF, "1")
    transporte = TransporteFalso([RespuestaFalsa("Se te ve más definido que en julio.")])
    monkeypatch.setattr(agent, "_post_chat", transporte)

    coach = agent.Coach(store, today=HOY)
    r = coach.ask("¿me ves mejor?", image_path=_foto_jpeg(tmp_path))
    assert not r.error

    turno = transporte.peticiones[0]["messages"][-1]
    assert turno["role"] == "user" and isinstance(turno["content"], list)
    tipos = [p["type"] for p in turno["content"]]
    assert tipos == ["text", "image_url"]
    assert turno["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    # Tras responder, el historial guarda la marca, no los bytes.
    ultimo_usuario = [m for m in coach.messages if m["role"] == "user"][-1]
    assert isinstance(ultimo_usuario["content"], str)
    assert "[foto adjunta, ya vista]" in ultimo_usuario["content"]


def test_image_part_rechaza_gigantes(tmp_path):
    gorda = tmp_path / "gorda.jpg"
    gorda.write_bytes(b"x" * 9_000_000)
    import pytest as _pytest

    with _pytest.raises(ValueError):
        agent._image_part(str(gorda))


def test_el_catalogo_marca_la_vision():
    import openrouter

    payload = {
        "data": [
            {
                "id": "google/gemini-2.5-flash",
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text", "image"]},
                "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
                "context_length": 1048576,
            },
            {
                "id": "solo-texto/modelo",
                "supported_parameters": ["tools"],
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 8192,
            },
        ]
    }
    modelos = {m.id: m for m in openrouter.parse_models(payload)}
    assert modelos["google/gemini-2.5-flash"].vision is True
    assert modelos["solo-texto/modelo"].vision is False


def test_propose_reminder_valida_y_el_commit_crea_el_aviso(store, tmp_path):
    ctx = agent._Context(store=store, today=date(2026, 8, 21))
    assert agent._tool_propose_reminder(ctx, text="", time_hhmm="10:00")[1] is None
    assert agent._tool_propose_reminder(ctx, text="Agua", time_hhmm="25:00")[1] is None
    assert (
        agent._tool_propose_reminder(ctx, text="Agua", time_hhmm="10:00", repeat="weekly")[1]
        is None
    ), "semanal sin días debe rechazarse"

    told, p = agent._tool_propose_reminder(
        ctx, text="Lista de la compra", time_hhmm="10:00", repeat="weekly", weekdays=[6]
    )
    assert p is not None and "sáb" in p.summary()
    assert "NOT created" in told or "NOT" in told

    mensaje = agent.commit_proposal(store, p)
    assert "Aviso creado" in mensaje
    filas = store.get_all_reminders()
    assert len(filas) == 1
    assert filas[0]["texto"] == "Lista de la compra"
    assert filas[0]["cron"] == "0 10 * * 6"
    assert filas[0]["origen"] == "usuario"


def test_commit_de_aviso_una_vez_calcula_madrid(store):
    p = agent.ReminderProposal(
        texto="Meal prep", hour=17, minute=0, tipo="once", day=date(2026, 8, 23)
    )
    agent.commit_proposal(store, p)
    fila = store.get_all_reminders()[0]
    assert fila["cron"] is None
    proxima = fila["proxima"]
    if proxima.tzinfo is None:
        from datetime import timezone as _tz

        proxima = proxima.replace(tzinfo=_tz.utc)
    # 17:00 de Madrid en agosto (CEST, +2) son las 15:00Z.
    assert proxima.hour == 15 and proxima.date().isoformat() == "2026-08-23"
