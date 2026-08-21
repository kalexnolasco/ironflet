"""La pantalla que dice qué lleva una copia tiene que decirlo bien.

Es la única superficie donde alguien decide si sobreescribir su teléfono, así
que un cero de más no es cosmético: se lee como «esto no está en la copia» y
la respuesta a eso es no restaurar, o restaurar creyendo que se pierde algo.

Durante tres versiones `photos`, `session_notes` y `session_durations`
imprimieron un `0` fijo — no porque el backup no los llevara (los lleva desde
la v4 y la v5), sino porque `count_document` no los buscaba. Debajo de la lista
había un aviso que los nombraba en snake_case, así que la pantalla decía «no
hay fotos» y «no estoy contando las fotos» a la vez. Nada de esto lo miraba un
test; se vio en el emulador, con una foto guardada y un cero en la fila.

Los dos primeros tests son de contrato y no dependen de estos tres nombres: se
cumplen para cualquier tabla que alguien añada mañana a `backup.TABLES`.
"""

from __future__ import annotations

from datetime import date

import pytest

import backup
from storage import Storage, WorkoutEntry
from views.data_view import (
    TABLE_LABELS,
    UNCOUNTED_TABLES,
    count_document,
    ordered_counts,
)

DIA = date(2026, 8, 21)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(db_url=f"sqlite:///{tmp_path / 'cuentas'}.db")


# ── contrato: nada del backup se queda fuera ────────────────────────────


def test_no_queda_ninguna_tabla_sin_contar():
    """Cada tabla que la copia lleva, la pantalla la sabe contar.

    `UNCOUNTED_TABLES` se deriva de la diferencia entre `backup.TABLES` y lo
    que `count_document` mira, así que esto falla solo en cuanto alguien añade
    una sección al documento y no la enseña a contar — que es exactamente el
    día en que hay que acordarse.
    """
    assert UNCOUNTED_TABLES == (), (
        f"estas tablas saldrán con un 0 permanente: {UNCOUNTED_TABLES}. "
        "Un cero se lee como «no hay», no como «no lo sé»."
    )


def test_toda_tabla_tiene_una_etiqueta_en_espanol():
    """Sin etiqueta, la fila sale con la clave técnica: «Session durations».

    Que es lo que salía, en inglés y en medio de una pantalla en español.
    """
    sin_etiqueta = [t for t in backup.TABLES if t not in TABLE_LABELS]
    assert not sin_etiqueta, f"filas que saldrían con su nombre de tabla: {sin_etiqueta}"

    for clave, etiqueta in TABLE_LABELS.items():
        assert "_" not in etiqueta, f"{clave} conserva el snake_case: {etiqueta!r}"


def test_toda_tabla_aparece_en_algun_grupo_de_la_pantalla():
    """`ordered_counts` reparte en grupos; nada debe caer en «Otros».

    «Otros» existe como red de seguridad para que una tabla nueva se vea aunque
    nadie toque `TABLE_GROUPS`, no como sitio donde vivan las de siempre.
    """
    filas = ordered_counts(dict.fromkeys(backup.TABLES, 0))
    huerfanas = [clave for grupo, clave, _n in filas if grupo == "Otros"]
    assert not huerfanas, f"sin grupo asignado: {huerfanas}"


# ── el conteo, contra un documento exportado de verdad ──────────────────


def test_cuenta_lo_que_el_exportador_escribe_de_verdad(store):
    """Un día con foto, nota y tiempo de sesión, ida y vuelta por `backup`.

    No se construye el documento a mano: sale de `backup.export_all`, así que
    el test compara la pantalla con el exportador y no con lo que yo creía que
    el exportador escribe. Ese hueco es justo por donde se coló el cero.
    """
    store.save_workout(
        WorkoutEntry(
            date=DIA.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
        )
    )
    store.save_weight(82.4, date_iso=DIA.isoformat())
    store.save_photo(DIA, "2026-08-21.jpg", nota="de frente")
    store.set_session_note("Buena sesión", on_date=DIA)
    store.set_session_duration(7 * 60, on_date=DIA)

    documento = backup.export_all(store)
    cuentas = count_document(documento)

    assert cuentas["photos"] == 1, "la foto está en la copia y la pantalla la ignoraba"
    assert cuentas["session_notes"] == 1
    assert cuentas["session_durations"] == 1
    assert cuentas["workouts"] == 1
    assert cuentas["weights"] == 1


def test_un_documento_viejo_sin_esas_secciones_cuenta_cero_sin_reventar(store):
    """Una copia v2/v3 no las lleva. Ahí el cero **sí** es la verdad."""
    documento = backup.export_all(store)
    for clave in ("photos", "session_notes", "session_durations"):
        documento.pop(clave, None)

    cuentas = count_document(documento)
    assert cuentas["photos"] == 0
    assert cuentas["session_notes"] == 0
    assert cuentas["session_durations"] == 0


def test_una_seccion_corrupta_no_tumba_la_vista_previa(store):
    """La vista previa es lo que avisa ANTES de sobreescribir el teléfono.

    Tiene que sobrevivir a peor entrada que el importador, así que una cadena
    donde va una lista cuenta 0 en vez de lanzar.
    """
    documento = backup.export_all(store)
    documento["photos"] = "no soy una lista"
    documento["session_notes"] = {"tampoco": "soy una lista"}

    cuentas = count_document(documento)
    assert cuentas["photos"] == 0
    assert cuentas["session_notes"] == 0


# ── el segundo guardado, el que Android rechaza ─────────────────────────


def _vista(store, tmp_path):
    """Un `DataView` con `page` de mentira; nada de esto pinta nada."""
    from unittest.mock import MagicMock

    import views.data_view as dv

    page = MagicMock()
    page.width = 400
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    vista = dv.DataView(page, store)
    vista._pending_export = b'{"app": "ironflet"}'
    vista._last_export = tmp_path / "backups" / "ironflet-backup.json"
    return vista


def test_un_uri_del_saf_no_se_lee_como_copia_perdida(store, tmp_path):
    """Android devuelve `/document/12`, que no es una ruta que se pueda abrir.

    El mensaje decía «No se pudo escribir 12.json: [Errno 2]» y pisaba el
    éxito de la copia interna, que en ese mismo momento tenía 28 KB de JSON
    válido. Se leía como «te has quedado sin copia», que es la conclusión más
    cara posible en esta pantalla.
    """
    from unittest.mock import MagicMock

    vista = _vista(store, tmp_path)
    evento = MagicMock()
    evento.path = "/document/12"

    vista._on_save_result(evento)
    nivel, mensaje = vista._status

    assert nivel == "error", "sigue siendo un fallo: la segunda copia no se escribió"
    assert "VACÍO" in mensaje, "hay que nombrar el fichero de 0 bytes que queda en Descargas"
    assert str(vista._last_export) in mensaje, "y sobre todo decir dónde SÍ está la copia buena"


def test_un_fallo_de_disco_normal_sigue_diciendo_lo_de_siempre(store, tmp_path):
    """Sin URI raro, el mensaje no debe inventarse una explicación de Android."""
    from unittest.mock import MagicMock

    vista = _vista(store, tmp_path)
    evento = MagicMock()
    evento.path = str(tmp_path / "no-existe" / "copia.json")

    vista._on_save_result(evento)
    _nivel, mensaje = vista._status

    assert "Android" not in mensaje
    assert str(vista._last_export) in mensaje, "la copia buena se nombra igual"


def test_sin_copia_interna_el_mensaje_no_promete_uno(store, tmp_path):
    """Si tampoco hubo copia local, hay que decirlo claro y sin consuelo."""
    from unittest.mock import MagicMock

    vista = _vista(store, tmp_path)
    vista._last_export = None
    evento = MagicMock()
    evento.path = "/document/12"

    vista._on_save_result(evento)
    _nivel, mensaje = vista._status

    assert "no hay copia" in mensaje.lower()
