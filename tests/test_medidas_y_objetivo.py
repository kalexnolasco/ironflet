"""Las cinco medidas, el objetivo de peso y su proyección.

Las cuatro columnas que no eran de nadie: `medidas` tiene cintura, cadera,
pecho, brazo y muslo desde que existe, y hasta 0.20 la app solo pedía la
cintura porque «las otras son del coach». Ese coach era el de Telegram y se
jubiló en 0.13 — llevaban dos versiones vacías en un plan donde son justo las
que dicen si funciona.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analytics import (
    CAMPOS_MEDIDA,
    DIRECCION_DESEADA,
    RUIDO_CINTA_CM,
    cambios_de_medidas,
    lectura_de_recomposicion,
    proyectar_peso,
)
from storage import Storage

HOY = date(2026, 9, 1)


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'm.db'}")


def _serie(**por_campo):
    """Dos lecturas: la base hace dos meses y la de ahora."""
    base = {"date": "2026-07-01"}
    ahora = {"date": "2026-08-30"}
    for campo, (a, b) in por_campo.items():
        base[campo], ahora[campo] = a, b
    return [base, ahora]


# ── las cinco columnas ───────────────────────────────────────────────────


def test_las_cinco_columnas_existen_y_se_guardan(store):
    """Si la app pide un campo que la tabla no tiene, `save_measurement` lo
    rechaza — y este test lo diría antes que la pantalla."""
    valores = {campo: 50.0 + i for i, (campo, _e, _d) in enumerate(CAMPOS_MEDIDA)}
    store.save_measurement(on_date="2026-09-01", **valores)
    fila = store.get_measurements(limit=1)[0]
    for campo, valor in valores.items():
        assert fila[campo] == valor


def test_guardar_una_no_borra_las_otras(store):
    """`save_measurement` deja intacto lo que no recibe. Es lo que permite
    apuntar solo la cintura un día sin perder el pecho de la semana pasada."""
    store.save_measurement(on_date="2026-09-01", waist=88.0, chest=102.0)
    store.save_measurement(on_date="2026-09-01", waist=87.5)
    fila = store.get_measurements(limit=1)[0]
    assert fila["waist"] == 87.5
    assert fila["chest"] == 102.0, "guardar la cintura se llevó el pecho"


def test_cada_campo_tiene_etiqueta_y_donde_se_mide():
    for campo, etiqueta, donde in CAMPOS_MEDIDA:
        assert campo in DIRECCION_DESEADA
        assert etiqueta and donde, f"{campo} sin etiqueta o sin instrucción"


def test_la_cintura_va_primera():
    """Es la que frena el plan; el resto es contexto."""
    assert CAMPOS_MEDIDA[0][0] == "waist"


# ── qué se mueve y qué no ────────────────────────────────────────────────


def test_una_sola_lectura_no_es_un_cambio(store):
    """Pintarla con «+0,0» invita a leer que no se mueve cuando lo que pasa es
    que no hay con qué comparar."""
    filas = [{"date": "2026-09-01", "waist": 88.0}]
    assert cambios_de_medidas(filas, HOY) == ()


def test_el_ruido_de_la_cinta_no_es_un_cambio():
    cambios = cambios_de_medidas(_serie(waist=(88.0, 87.7)), HOY)
    assert cambios[0].cambio == -0.3
    assert cambios[0].significativo is False
    assert cambios[0].va_bien is None, "0,3 cm es apretar distinto, no adelgazar"


def test_por_encima_del_ruido_si_cuenta():
    cambios = cambios_de_medidas(_serie(waist=(88.0, 88.0 - RUIDO_CINTA_CM)), HOY)
    assert cambios[0].significativo is True
    assert cambios[0].va_bien is True


def test_la_direccion_deseada_de_cada_campo():
    c = {
        x.campo: x
        for x in cambios_de_medidas(_serie(waist=(88.0, 86.0), chest=(100.0, 102.0)), HOY)
    }
    assert c["waist"].va_bien is True  # bajar es lo que se busca
    assert c["chest"].va_bien is True  # subir, también


def test_la_cintura_subiendo_va_mal():
    c = cambios_de_medidas(_serie(waist=(86.0, 88.0)), HOY)[0]
    assert c.cambio == 2.0
    assert c.va_bien is False


def test_la_cadera_no_tiene_veredicto():
    """Baja con la grasa y sube con el glúteo: decidir por Alex sería el
    veredicto que `WaistSummary` explica por qué no se da."""
    c = cambios_de_medidas(_serie(hip=(96.0, 98.0)), HOY)[0]
    assert c.significativo is True
    assert c.va_bien is None


# ── la lectura de las cinco juntas ───────────────────────────────────────


def test_cintura_abajo_y_musculo_arriba_es_la_recomposicion():
    """Lo único que justifica medir cinco cosas en vez de una."""
    cambios = cambios_de_medidas(_serie(waist=(88.5, 86.8), chest=(102.0, 103.2)), HOY)
    frase = lectura_de_recomposicion(cambios)
    assert "recomposición" in frase
    assert "-1.7" in frase


def test_todo_subiendo_se_dice_sin_adornos():
    cambios = cambios_de_medidas(_serie(waist=(86.0, 87.5), arm=(35.0, 36.0)), HOY)
    frase = lectura_de_recomposicion(cambios)
    assert "demasiada comida" in frase


def test_dentro_del_ruido_no_dice_nada():
    """Las primeras semanas todo está dentro del ruido, e inventar una lectura
    ahí es exactamente el veredicto que no se da."""
    assert lectura_de_recomposicion(cambios_de_medidas(_serie(waist=(88.0, 87.8)), HOY)) == ""
    assert lectura_de_recomposicion([]) == ""


# ── el objetivo de peso ──────────────────────────────────────────────────


def _pesos(desde: float, por_semana: float, dias: int = 30):
    return [
        {"date": (HOY - timedelta(days=dias - i)).isoformat(), "kg": desde + por_semana * i / 7}
        for i in range(dias)
    ]


def test_da_fecha_cuando_el_ritmo_lleva_al_objetivo():
    p = proyectar_peso(_pesos(84.0, -0.35), 78.0, today=HOY)
    assert p.fecha is not None and p.fecha > HOY
    assert p.semanas and p.semanas > 0
    assert p.acercandose is True


def test_no_da_fecha_si_vas_en_direccion_contraria():
    """Y lo dice, en vez de tragárselo en un «no se puede estimar»: son dos
    cosas distintas y se leen distinto."""
    p = proyectar_peso(_pesos(84.0, -0.35), 90.0, today=HOY)
    assert p.fecha is None
    assert p.acercandose is False
    assert p.faltan < 0


def test_no_da_fecha_a_ritmo_casi_nulo():
    """A 0,05 kg/semana faltarían dos años para cinco kilos: eso no es una
    previsión, es una división."""
    p = proyectar_peso(_pesos(84.0, -0.02), 78.0, today=HOY)
    assert p.fecha is None
    assert p.ritmo is not None


def test_no_da_fecha_mas_alla_de_un_ano():
    p = proyectar_peso(_pesos(120.0, -0.15), 60.0, today=HOY)
    assert p.fecha is None
    assert p.acercandose is True


def test_reconoce_que_ya_estas():
    p = proyectar_peso(_pesos(82.5, -0.1), 82.4, today=HOY)
    assert p.logrado is True
    assert p.fecha is None


def test_sin_peso_no_inventa_nada():
    p = proyectar_peso([], 78.0, today=HOY)
    assert p.actual is None and p.ritmo is None and p.fecha is None
    assert p.objetivo == 78.0


def test_con_peso_pero_sin_recorrido_no_hay_ritmo():
    """`None` en el ritmo significa «no hay con qué decirlo», que no es lo
    mismo que «no cambia»."""
    p = proyectar_peso([{"date": HOY.isoformat(), "kg": 84.0}], 78.0, today=HOY)
    assert p.actual is not None
    assert p.ritmo is None and p.fecha is None


def test_la_media_amortigua_un_pesaje_raro():
    """La báscula se mueve dos kilos con la sal de una cena, y la previsión
    sale de la **media de 7 días** justo por eso.

    Amortigua, que no es lo mismo que ignorar: dos kilos en un solo día siguen
    moviendo la media de siete unos 0,3, y con un objetivo a cinco kilos eso
    basta para que el ritmo deje de dar fecha. Lo que este test fija es la
    proporción — el peso crudo entra dividido, no entero.
    """
    base = _pesos(84.0, -0.35)
    con_ruido = [*base[:-1], {**base[-1], "kg": base[-1]["kg"] + 2.0}]

    a = proyectar_peso(base, 78.0, today=HOY)
    b = proyectar_peso(con_ruido, 78.0, today=HOY)

    assert a.actual is not None and b.actual is not None
    desvio = b.actual - a.actual
    assert 0 < desvio < 0.5, f"2 kg de ruido movieron la media {desvio:.2f} kg"

    # Y con el dato crudo el salto habría sido los dos kilos enteros.
    assert desvio < 2.0 / 3


def test_la_prevision_se_dice_con_la_precision_que_aguanta():
    """Un pesaje de dos kilos menos adelanta la fecha **46 días**, y eso no se
    arregla amortiguando más: lo que está mal es prometer un martes concreto de
    diciembre. Así que la unidad es la semana y la fecha se dice como
    referencia, más redonda cuanto más lejos queda.
    """
    base = _pesos(84.0, -0.35)
    ligero = [*base[:-1], {**base[-1], "kg": base[-1]["kg"] - 2.0}]

    a, b = proyectar_peso(base, 78.0, today=HOY), proyectar_peso(ligero, 78.0, today=HOY)
    assert a.fecha and b.fecha
    assert abs((b.fecha - a.fecha).days) > 30, "el caso que motiva esto ya no ocurre"

    # A trece semanas ninguna de las dos promete un día.
    assert "meses" in a.cuando() and "/" not in a.cuando()

    # Cerca sí lleva día, porque a dos semanas el dato aguanta eso.
    cerca = proyectar_peso(_pesos(84.0, -0.35), 82.0, today=HOY)
    assert cerca.semanas and cerca.semanas <= 2
    assert "/" in cerca.cuando()


def test_ya_estar_ahi_se_dice_asi():
    p = proyectar_peso(_pesos(82.5, -0.1), 82.4, today=HOY)
    assert p.cuando() == "ya estás ahí"


def test_sin_prevision_no_hay_frase():
    assert proyectar_peso([], 78.0, today=HOY).cuando() == ""
