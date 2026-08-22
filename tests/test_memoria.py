"""memoria.py — lo que el coach sabe de Alex y no vuelve a preguntar.

Dos cosas se comprueban aquí con más insistencia que el resto: que **nada se
guarda sin pasar por `commit_proposal`** (la herramienta solo propone, como el
resto del coach) y que **una pref corrupta no deja al coach sin arrancar** —
esto se lee en cada construcción del prompt, así que es el sitio donde un
`json.loads` optimista se lleva por delante la pantalla entera.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

import agent
import memoria
from storage import Storage

HOY = date(2026, 8, 22)


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'memoria.db'}")


# ── guardar y leer ───────────────────────────────────────────────────────


def test_una_memoria_recien_instalada_esta_vacia(store):
    assert memoria.leer(store) == []
    assert memoria.vacia(store) is True
    assert memoria.para_prompt(store) == ""


def test_anadir_y_leer(store):
    h = memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    assert h.texto == "No come pescado"
    assert h.categoria == "comida"
    assert h.creado == "2026-08-22"
    assert [x.texto for x in memoria.leer(store)] == ["No come pescado"]
    assert memoria.vacia(store) is False


def test_el_orden_es_el_de_llegada(store):
    for t in ("uno", "dos", "tres"):
        memoria.anadir(store, t, hoy=HOY)
    assert [h.texto for h in memoria.leer(store)] == ["uno", "dos", "tres"]


def test_un_duplicado_exacto_no_crea_una_segunda_linea(store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    memoria.anadir(store, "  no COME   pescado ", "otro", hoy=HOY)
    assert len(memoria.leer(store)) == 1
    assert memoria.leer(store)[0].categoria == "comida", "el duplicado pisó la categoría buena"


def test_el_texto_se_normaliza(store):
    h = memoria.anadir(store, "  entrena   a las\n7:00  ", hoy=HOY)
    assert h.texto == "entrena a las 7:00"


def test_un_hecho_vacio_se_rechaza(store):
    with pytest.raises(ValueError):
        memoria.anadir(store, "   ", hoy=HOY)
    with pytest.raises(ValueError):
        memoria.anadir(store, "", hoy=HOY)


def test_una_categoria_desconocida_cae_en_otro(store):
    assert memoria.anadir(store, "algo", "inventada", hoy=HOY).categoria == "otro"
    assert memoria.anadir(store, "otra cosa", "COMIDA", hoy=HOY).categoria == "comida"


def test_borrar(store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    memoria.anadir(store, "Entrena a las 7", "rutina", hoy=HOY)
    assert memoria.borrar(store, "no come PESCADO") is True
    assert [h.texto for h in memoria.leer(store)] == ["Entrena a las 7"]
    assert memoria.borrar(store, "no come pescado") is False


def test_reemplazar_deja_exactamente_la_lista(store):
    memoria.anadir(store, "viejo", hoy=HOY)
    memoria.reemplazar(
        store,
        [
            memoria.Hecho("nuevo uno", "rutina"),
            memoria.Hecho("nuevo dos", "comida"),
            memoria.Hecho("  ", "otro"),  # se cae
            memoria.Hecho("NUEVO UNO", "otro"),  # duplicado, se cae
        ],
    )
    assert [h.texto for h in memoria.leer(store)] == ["nuevo uno", "nuevo dos"]


# ── los límites, que existen porque esto se paga en cada pregunta ────────


def test_un_hecho_larguisimo_se_recorta(store):
    h = memoria.anadir(store, "x" * 500, hoy=HOY)
    assert len(h.texto) == memoria.MAX_LARGO


def test_al_llegar_al_tope_empuja_el_mas_viejo(store):
    """Fallar aquí sería fallar justo cuando alguien está contando algo."""
    for i in range(memoria.MAX_HECHOS + 5):
        memoria.anadir(store, f"hecho {i}", hoy=HOY)
    hechos = memoria.leer(store)
    assert len(hechos) == memoria.MAX_HECHOS
    assert hechos[0].texto == "hecho 5", "empujó por el lado equivocado"
    assert hechos[-1].texto == f"hecho {memoria.MAX_HECHOS + 4}"


# ── el prompt ────────────────────────────────────────────────────────────


def test_para_prompt_agrupa_por_categoria_en_su_orden(store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    memoria.anadir(store, "Entrena a las 7", "rutina", hoy=HOY)
    memoria.anadir(store, "Rodilla izquierda", "cuerpo", hoy=HOY)

    texto = memoria.para_prompt(store)
    assert texto.index("Horarios y rutina") < texto.index("Comida") < texto.index("Lesiones")
    assert "- Entrena a las 7" in texto


def test_los_hechos_llegan_al_prompt_del_sistema(store):
    """Lo que hace que el coach no vuelva a preguntar."""
    antes = agent.build_system_prompt(store)
    assert "You know nothing about him" in antes

    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    despues = agent.build_system_prompt(store)
    assert "No come pescado" in despues
    assert "You know nothing about him" not in despues


def test_el_prompt_sin_memoria_invita_a_preguntar_de_una_en_una(store):
    """Un cuestionario en una burbuja de chat no es una conversación."""
    prompt = agent.build_system_prompt(store)
    assert "ONE question at a time" in prompt


def test_el_prompt_pide_no_guardar_dos_versiones_de_lo_mismo(store):
    memoria.anadir(store, "Entrena a las 7", "rutina", hoy=HOY)
    assert "never keep both" in agent.build_system_prompt(store)


# ── robustez: esto se lee en cada arranque del coach ─────────────────────


@pytest.mark.parametrize(
    "basura",
    [
        "esto no es json",
        "{}",
        '{"hechos": []}',
        "[1, 2, 3]",
        '[{"sin_texto": "nada"}]',
        "null",
        "",
    ],
)
def test_una_pref_corrupta_no_tumba_al_coach(store, basura):
    store.set_pref(memoria.PREF, basura)
    assert memoria.leer(store) == []
    assert memoria.para_prompt(store) == ""
    assert agent.build_system_prompt(store)  # y el prompt se construye igual


def test_una_base_de_datos_muerta_deja_un_coach_sin_memoria_pero_vivo(store):
    class Rota:
        def get_pref(self, *_a, **_k):
            raise RuntimeError("no hay base de datos")

        def get_profile(self):
            raise RuntimeError("no hay base de datos")

    assert memoria.leer(Rota()) == []
    assert agent.build_system_prompt(Rota())


def test_la_forma_vieja_de_lista_de_cadenas_se_sigue_leyendo(store):
    """Nadie tiene esa forma en producción, pero leerla cuesta tres líneas y
    la alternativa es que una versión intermedia borre lo apuntado."""
    store.set_pref(memoria.PREF, json.dumps(["Entrena a las 7", "No come pescado"]))
    assert [h.texto for h in memoria.leer(store)] == ["Entrena a las 7", "No come pescado"]
    assert all(h.categoria == "otro" for h in memoria.leer(store))


# ── el coach propone; guardar es de Alex ─────────────────────────────────


def test_la_herramienta_no_guarda_nada(store):
    """La invariante de siempre, aquí donde más se nota: un modelo que escribe
    en su propia memoria acaba recordando cosas que nadie le dijo."""
    ctx = agent._Context(store=store, today=HOY)
    texto, propuesta = agent._tool_propose_memory(ctx, fact="No come pescado", category="comida")

    assert isinstance(propuesta, agent.MemoryProposal)
    assert "NOT saved" in texto
    assert memoria.leer(store) == [], "la herramienta escribió sin pasar por la tarjeta"


def test_guardar_la_tarjeta_es_lo_que_escribe(store):
    ctx = agent._Context(store=store, today=HOY)
    _texto, propuesta = agent._tool_propose_memory(ctx, fact="No come pescado", category="comida")
    respuesta = agent.commit_proposal(store, propuesta)

    assert [h.texto for h in memoria.leer(store)] == ["No come pescado"]
    assert "Apuntado" in respuesta


def test_la_herramienta_rechaza_lo_vacio_y_lo_larguisimo(store):
    ctx = agent._Context(store=store, today=HOY)
    assert agent._tool_propose_memory(ctx, fact="")[1] is None
    texto, propuesta = agent._tool_propose_memory(ctx, fact="x" * 400)
    assert propuesta is None and "200 characters max" in texto


def test_la_herramienta_no_repropone_lo_ya_apuntado(store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    ctx = agent._Context(store=store, today=HOY)
    texto, propuesta = agent._tool_propose_memory(ctx, fact="no come pescado")
    assert propuesta is None, "una tarjeta para algo que ya está apuntado es ruido"
    assert "Already remembered" in texto


def test_al_llegar_al_tope_la_herramienta_manda_a_ajustes(store):
    for i in range(memoria.MAX_HECHOS):
        memoria.anadir(store, f"hecho {i}", hoy=HOY)
    ctx = agent._Context(store=store, today=HOY)
    texto, propuesta = agent._tool_propose_memory(ctx, fact="uno más")
    assert propuesta is None
    assert "Ajustes" in texto


def test_about_me_relata_lo_apuntado(store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    ctx = agent._Context(store=store, today=HOY)
    texto = agent._tool_about_me(ctx)
    assert "No come pescado" in texto
    assert "contradict" in texto


def test_about_me_sin_nada_apuntado_sugiere_preguntar(store):
    ctx = agent._Context(store=store, today=HOY)
    texto = agent._tool_about_me(ctx)
    assert "Nothing remembered" in texto
    assert "one question at a time" in texto.lower()


def test_la_tarjeta_dice_para_que_sirve_guardarla(store):
    p = agent.MemoryProposal(texto="No come pescado", categoria="comida")
    assert "Comida" in p.summary()
    assert "cada conversación" in p.summary()


# ── el backup ────────────────────────────────────────────────────────────


def test_la_memoria_viaja_en_el_backup(store, tmp_path):
    """Es justo lo que uno quiere conservar al cambiar de móvil — al revés que
    la clave de la API, que se queda en el aparato (`SECRET_PREF_KEYS`)."""
    import storage as storage_mod

    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    doc = store.export_all()
    assert memoria.PREF in doc["prefs"]
    assert memoria.PREF not in storage_mod.SECRET_PREF_KEYS

    otro = Storage(f"sqlite:///{tmp_path / 'movil_nuevo.db'}")
    otro.import_all(doc)
    assert [h.texto for h in memoria.leer(otro)] == ["No come pescado"]


# ── las pantallas ────────────────────────────────────────────────────────


def _walk(control):
    """Los controles en el orden en que se leen."""
    import flet as ft

    out, seen = [], set()

    def bajar(c):
        if c is None or id(c) in seen:
            return
        seen.add(id(c))
        out.append(c)
        kids = getattr(c, "controls", None)
        if isinstance(kids, list):
            for k in kids:
                bajar(k)
        for attr in ("content", "title"):
            kid = getattr(c, attr, None)
            if isinstance(kid, ft.Control):
                bajar(kid)

    bajar(control)
    return out


def _textos(control) -> str:
    import flet as ft

    return " | ".join(
        str(c.value) for c in _walk(control) if isinstance(c, ft.Text) and c.value
    )


@pytest.fixture
def ajustes(store):
    from unittest.mock import MagicMock

    from views.profile import ProfileView

    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda *_a, **_k: None}
    page.width = 400
    return ProfileView(page, store)


def test_ajustes_lista_lo_apuntado(ajustes, store):
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    memoria.anadir(store, "Entrena a las 7:00", "rutina", hoy=HOY)

    texto = _textos(ajustes._memoria_section())
    assert "No come pescado" in texto
    assert "Entrena a las 7:00" in texto
    assert "Comida" in texto and "Horarios y rutina" in texto


def test_ajustes_sin_nada_explica_para_que_sirve(ajustes, store):
    texto = _textos(ajustes._memoria_section())
    assert "todavía no sabe nada de ti" in texto


def test_la_papelera_borra_ese_hecho_y_no_otro(ajustes, store):
    import flet as ft

    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    memoria.anadir(store, "Entrena a las 7:00", "rutina", hoy=HOY)

    fila = ajustes._fila_memoria(memoria.leer(store)[0])
    papelera = next(
        c
        for c in _walk(fila)
        if getattr(c, "on_click", None)
        and any(isinstance(k, ft.Icon) and k.name == ft.Icons.DELETE_OUTLINE for k in _walk(c))
    )
    papelera.on_click(None)
    assert [h.texto for h in memoria.leer(store)] == ["Entrena a las 7:00"]


def test_al_llegar_al_tope_ajustes_quita_el_campo_de_anadir(ajustes, store):
    """Y dice por qué: esto se paga en cada pregunta."""
    import flet as ft

    for i in range(memoria.MAX_HECHOS):
        memoria.anadir(store, f"hecho {i}", hoy=HOY)

    seccion = ajustes._memoria_section()
    assert "el máximo" in _textos(seccion)
    assert not [c for c in _walk(seccion) if isinstance(c, ft.TextField)], (
        "dejó el campo puesto en un sitio donde añadir ya no funciona"
    )


def test_una_base_de_datos_muerta_no_tumba_ajustes(ajustes, monkeypatch):
    monkeypatch.setattr(
        memoria, "leer", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert ajustes._memoria_section() is not None


@pytest.fixture
def chat(store):
    from unittest.mock import MagicMock

    from views.agent_view import AgentView

    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda *_a, **_k: None}
    page.width = 400
    return AgentView(page, store)


def test_el_chat_ofrece_la_entrevista_mientras_no_sepa_nada(chat, store):
    texto = _textos(chat._starters())
    assert "Todavía no sé nada de ti" in texto
    assert "Que me conozcas" in texto


def test_la_invitacion_desaparece_con_el_primer_hecho(chat, store):
    """Un botón que sigue ahí después de usarlo invita a repetir la entrevista,
    y la segunda vuelta es el coach preguntando lo que ya tiene apuntado."""
    memoria.anadir(store, "No come pescado", "comida", hoy=HOY)
    texto = _textos(chat._starters())
    assert "Todavía no sé nada de ti" not in texto
    assert "¿Qué toca hoy?" in texto, "se llevó por delante los arranques normales"


def test_la_entrevista_manda_un_mensaje_de_alex_y_no_una_orden_oculta(chat, store):
    """Aparece en la conversación como cualquier otro mensaje suyo: se puede
    leer, corregir y repetir."""
    enviados = []
    chat.page.run_task = lambda fn, texto: enviados.append(texto)

    boton = next(
        c
        for c in _walk(chat._starters())
        if getattr(c, "on_click", None) and "Que me conozcas" in _textos(c)
    )
    boton.on_click(None)
    assert enviados == [chat.ENTREVISTA]
    assert "de una en una" in chat.ENTREVISTA


def test_la_tarjeta_del_chat_pinta_la_propuesta_de_memoria(chat, store):
    chat.pending = agent.MemoryProposal(texto="No come pescado", categoria="comida")
    texto = _textos(chat._proposal_card())
    assert "Que lo recuerde" in texto
    assert "No come pescado" in texto
    assert "Nada guardado aún" in texto
    assert "Ajustes" in texto, "no dice dónde se corrige después"
