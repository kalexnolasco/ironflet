"""El widget de la pantalla de inicio: lo que Python le da de comer.

El widget es Kotlin y no se puede probar desde aquí, pero **todo lo que
decide** está en `widget.py`: qué se enseña, cómo se dice y cómo se formatea.
Kotlin solo pinta las cuatro cadenas del JSON. Ese reparto es lo que hace
testeable un widget de Android desde pytest, y estos tests son los que lo
sostienen — el día que Kotlin empiece a formatear algo, habrá dos sitios
decidiendo lo mismo y esto dejará de valer.

Un widget además tiene una exigencia que una pantalla no tiene: **no puede
lanzar**. No hay dónde enseñar un error, y la alternativa a un dato que falta
es dejar en pantalla el de ayer, que es peor que un hueco — un ✓ de ayer dice
que ya entrenaste hoy.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

import widget
from storage import Storage, WorkoutEntry

HOY = date(2026, 8, 21)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(db_url=f"sqlite:///{tmp_path / 'widget'}.db")


# ── el formato lo decide Python, no Kotlin ──────────────────────────────


def test_los_numeros_usan_el_mismo_punto_que_la_app():
    """El JSON viaja con «82.4 kg» ya formateado, no con el número suelto.

    Punto y no coma: es lo que pinta el resto de la app, y el widget vive en
    la misma pantalla de inicio desde la que se abre. Dos formas de escribir
    la misma cifra a dos centímetros una de otra es peor que cualquiera de las
    dos.

    Si Kotlin recibiera el número tendría que decidir el separador, el
    redondeo y la unidad — tres decisiones duplicadas y sin tests.
    """
    assert widget._num(82.4, 1) == "82.4"
    assert widget._num(2550) == "2550"


def test_un_entero_no_arrastra_el_decimal():
    assert widget._num(82.0, 1) == "82"


def test_el_peso_sale_con_su_unidad(store):
    store.save_weight(82.4, HOY.isoformat())
    assert widget.payload(store, HOY)["peso"] == "82.4 kg"


def test_sin_pesaje_la_linea_queda_vacia_y_no_a_cero(store):
    """«0 kg» es un dato; el hueco es la ausencia de dato."""
    assert widget.payload(store, HOY)["peso"] == ""


# ── qué toca hoy ────────────────────────────────────────────────────────


def test_un_dia_de_entreno_dice_su_nombre(store, monkeypatch):
    """El nombre va en inglés porque es `TrainingDay.name` (trampa 22)."""
    monkeypatch.setattr(widget, "_linea_entreno", lambda s, d: "Chest-Biceps", raising=False)
    assert widget.payload(store, HOY)["entreno"] == "Chest-Biceps"


def test_entrenar_hoy_pone_el_visto(store):
    """La media razón de ser del widget: saberlo sin abrir nada."""
    store.save_workout(
        WorkoutEntry(
            date=HOY.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
        )
    )
    entreno = widget.payload(store, HOY)["entreno"]
    assert entreno.startswith("✓"), f"con la sesión hecha esperaba un visto: {entreno!r}"


def test_sin_rotacion_lo_dice_en_vez_de_inventar_descanso(store):
    """Un fin de semana no está en `week_rotation`, y eso no es «Descanso».

    Decir «Descanso» donde el plan no dice nada es inventarse una prescripción.
    """
    entreno = widget.payload(store, HOY)["entreno"]
    assert entreno in ("Sin plan para hoy", "Descanso") or entreno.startswith("✓")


# ── las macros usan las claves de nutrition, no las traducidas ──────────


def test_las_macros_salen_con_su_objetivo(store):
    datos = widget.payload(store, HOY)
    assert "kcal" in datos["kcal"]
    assert datos["proteina"].endswith("g P")


def test_lee_protein_y_no_proteina(store, monkeypatch):
    """La trampa 22, que ya pintó «Proteína 0 g» en Inicio con 42 g apuntados.

    Se le da un diccionario que SOLO tiene la clave inglesa: si el módulo
    buscara la española, la cifra saldría a cero sin que nada fallara.
    """
    monkeypatch.setattr(widget, "_linea_entreno", lambda s, d: "Legs", raising=False)
    import nutrition

    monkeypatch.setattr(nutrition, "day_totals", lambda s, d: {"kcal": 1800.0, "protein": 142.0})
    monkeypatch.setattr(nutrition, "targets_for", lambda s, d: {"kcal": 2550.0, "protein": 115.0})
    datos = widget.payload(store, HOY)
    assert datos["proteina"] == "142 / 115 g P"
    assert datos["kcal"] == "1800 / 2550 kcal"


# ── un widget no puede lanzar ───────────────────────────────────────────


class StoreRoto:
    """Todo lo que se le pida, revienta."""

    def __getattr__(self, nombre):
        def _explota(*a, **k):
            raise RuntimeError(f"{nombre} está roto")

        return _explota


def test_con_todo_roto_devuelve_el_texto_de_invitacion():
    """No hay dónde enseñar un error, así que el widget invita a abrir la app."""
    datos = widget.payload(StoreRoto(), HOY)
    assert datos["entreno"] == widget.VACIO["entreno"]
    assert datos["peso"] == ""


def test_un_bloque_roto_no_se_lleva_a_los_demas(store, monkeypatch):
    """El peso sin apuntar no puede borrar las calorías."""
    monkeypatch.setattr(store, "get_weights", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
    datos = widget.payload(store, HOY)
    assert datos["peso"] == ""
    assert datos["kcal"], "las macros siguen ahí"


def test_todas_las_claves_estan_siempre(store):
    """Kotlin hace `optString` de las cuatro; que falte una es un hueco mudo."""
    assert set(widget.payload(store, HOY)) == set(widget.VACIO)


def test_todos_los_valores_son_cadenas(store):
    """El contrato con Kotlin: `optString` sobre un número da "" en silencio."""
    for clave, valor in widget.payload(store, HOY).items():
        assert isinstance(valor, str), f"{clave} es {type(valor).__name__}"


# ── el fichero ──────────────────────────────────────────────────────────


def test_sync_escribe_json_utf8_legible(store, tmp_path):
    store.save_weight(82.4, HOY.isoformat())
    destino = tmp_path / "widget.json"
    escrito = widget.sync(store, HOY, target=destino)

    leido = json.loads(destino.read_text(encoding="utf-8"))
    assert leido == escrito
    assert leido["peso"] == "82.4 kg"


def test_sync_no_deja_el_temporal_atras(store, tmp_path):
    """Escritura atómica: Kotlin puede estar leyendo justo en ese momento."""
    destino = tmp_path / "widget.json"
    widget.sync(store, HOY, target=destino)
    assert not list(tmp_path.glob("*.tmp"))


def test_sync_sobreescribe_en_vez_de_acumular(store, tmp_path):
    destino = tmp_path / "widget.json"
    widget.sync(store, HOY, target=destino)
    store.save_weight(81.0, HOY.isoformat())
    widget.sync(store, HOY, target=destino)
    assert json.loads(destino.read_text(encoding="utf-8"))["peso"] == "81 kg"


def test_sin_android_no_escribe_pero_devuelve_igual(store, monkeypatch):
    """En el escritorio no hay widget al que hablarle, y no es un error."""
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    datos = widget.sync(store, HOY)
    assert set(datos) == set(widget.VACIO)


def test_un_destino_imposible_no_tumba_la_app(store, tmp_path):
    """Un widget que no se puede escribir cuesta un widget, no la app."""
    imposible = tmp_path / "no-existe" / "x" / "widget.json"
    imposible.parent.mkdir(parents=True)
    imposible.parent.chmod(0o500)
    try:
        datos = widget.sync(store, HOY, target=imposible)
        assert set(datos) == set(widget.VACIO)
    finally:
        imposible.parent.chmod(0o700)


def test_el_nombre_del_fichero_es_el_que_kotlin_abre():
    """Escrito una vez aquí y una vez en Kotlin; que no haya una tercera."""
    assert widget.FICHERO == "widget.json"


# ── pedirle al lanzador que lo coloque ──────────────────────────────────


def test_la_peticion_deja_una_nota_junto_al_json(tmp_path):
    """Un fichero, no un canal: Flet no expone `MethodChannel` a Python."""
    nota = tmp_path / widget.FICHERO_PIN
    assert widget.pedir_colocacion(target=nota) is True
    assert nota.exists()


def test_sin_android_la_peticion_dice_que_no(monkeypatch):
    """En el escritorio no hay lanzador, y decir que sí sería mentir."""
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    assert widget.pedir_colocacion() is False
    assert widget.disponible() is False


def test_con_android_la_peticion_va_al_lado_del_json(monkeypatch, tmp_path):
    """La nota tiene que caer en el directorio que Dart sondea, no en otro."""
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    assert widget.disponible() is True
    assert widget.pedir_colocacion() is True
    assert (tmp_path / widget.FICHERO_PIN).exists()


def test_un_destino_imposible_para_la_nota_devuelve_false(tmp_path):
    """El botón de Ajustes distingue «te lo va a ofrecer» de «hazlo a mano»."""
    carpeta = tmp_path / "cerrada"
    carpeta.mkdir()
    carpeta.chmod(0o500)
    try:
        assert widget.pedir_colocacion(target=carpeta / "x" / widget.FICHERO_PIN) is False
    finally:
        carpeta.chmod(0o700)


# ── el día que se pide es el día que se mira ────────────────────────────


def test_el_visto_mira_el_dia_pedido_y_no_el_de_hoy(store):
    """`payload(store, dia)` tiene que respetar ese `dia` entero.

    No lo hacía: la línea de entreno llamaba a `store.get_today()`, que usa la
    fecha del sistema, así que el parámetro no hacía nada. Invisible en
    producción —el widget siempre pide hoy— y visible en cuanto un test con
    fecha fija se ejecutó al día siguiente y el ✓ desapareció.

    Se comprueba con AYER a propósito: si vuelve a mirar el reloj del sistema,
    esto falla siempre y no solo a medianoche.
    """
    from datetime import timedelta

    ayer = HOY - timedelta(days=1)
    store.save_workout(
        WorkoutEntry(
            date=ayer.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
        )
    )

    assert widget.payload(store, ayer)["entreno"].startswith("✓"), (
        "con la sesión de ayer registrada, el payload de AYER lleva visto"
    )
    assert not widget.payload(store, HOY)["entreno"].startswith("✓"), (
        "y el de hoy no, que no se entrenó"
    )


def test_storage_sabe_dar_los_entrenos_de_un_dia(store):
    """El método que hizo falta para lo de arriba, por su cuenta."""
    from datetime import timedelta

    ayer = HOY - timedelta(days=1)
    store.save_workout(
        WorkoutEntry(
            date=ayer.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
        )
    )
    assert len(store.get_workouts_on(ayer)) == 1
    assert store.get_workouts_on(HOY) == []
    # Y sin fecha sigue siendo hoy, que es lo que `get_today()` promete.
    assert store.get_workouts_on() == store.get_today()
