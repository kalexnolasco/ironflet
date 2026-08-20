"""notificaciones.py — la aritmética del puente y el CRUD de avisos.

Todo corre sobre SQLite en tmp_path, como test_agent.py y por la misma razón:
la mitad interesante del módulo es aritmética pura de fechas (parsear el
subconjunto de cron, expandir a instantes UTC en pared de Madrid) y la otra
mitad es el contrato con `main.dart` — el JSON que se escribe y cuándo NO se
escribe. Nada de esto necesita PostgreSQL, y el caso móvil ES SQLite.

Las horas se afirman en UTC contra fechas de enero y de julio a propósito:
Madrid es CET (+1) en invierno y CEST (+2) en verano, y la promesa del módulo
es que `45 6 * * *` significa 06:45 *de pared* todo el año — es decir, que el
instante UTC emitido se mueve una hora entre estaciones. Un test que solo
mirase enero pasaría igual con la zona clavada a +1, que es justo el fallo
que costaría un aviso a las 07:45 medio año.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import notificaciones as notif
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'notif.db'}")


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# ── parse_cron_simple: el subconjunto y solo el subconjunto ──────────────


def test_parsea_diaria():
    assert notif.parse_cron_simple("45 6 * * *") == {"minute": 45, "hour": 6, "weekdays": None}


def test_parsea_semanal_y_normaliza_domingo_7():
    receta = notif.parse_cron_simple("30 17 * * 1,3,7")
    assert receta == {"minute": 30, "hour": 17, "weekdays": {1, 3, 0}}


@pytest.mark.parametrize(
    "cron",
    [
        None,
        "",
        "45 6 * *",  # cuatro campos
        "45 6 1 * *",  # día del mes fijado
        "45 6 * 2 *",  # mes fijado
        "*/15 6 * * *",  # paso: dialecto del bot, no de la app
        "45 6 * * 1-5",  # rango: ídem
        "60 6 * * *",  # minuto imposible
        "45 24 * * *",  # hora imposible
        "45 6 * * 8",  # día imposible
        "x 6 * * *",
    ],
)
def test_fuera_del_subconjunto_devuelve_none(cron):
    assert notif.parse_cron_simple(cron) is None


def test_cron_para_las_tres_formas():
    assert notif.cron_para("once", 7, 5) is None
    assert notif.cron_para("daily", 6, 45) == "45 6 * * *"
    assert notif.cron_para("weekly", 17, 30, {3, 1}) == "30 17 * * 1,3"
    with pytest.raises(ValueError):
        notif.cron_para("weekly", 17, 30, set())
    with pytest.raises(ValueError):
        notif.cron_para("mensual", 9, 0)


def test_ida_y_vuelta_app_bot():
    """Lo que la app escribe, la app lo vuelve a leer — y el bot también.

    La forma emitida es el dialecto vixie del bot (0 o 7 = domingo, coma para
    listas); si `cron_para` y `parse_cron_simple` divergen, un aviso creado en
    el móvil deja de sonar tras el primer backup restaurado.
    """
    cron = notif.cron_para("weekly", 6, 45, {0, 5})
    assert notif.parse_cron_simple(cron) == {"minute": 45, "hour": 6, "weekdays": {0, 5}}


# ── expand: pared de Madrid, emitido en UTC ──────────────────────────────


def test_expande_diaria_en_invierno_cet():
    # 15 de enero: Madrid = UTC+1, así que 06:45 de pared son 05:45Z.
    after = _utc(2026, 1, 15, 12, 0)
    dias = notif.expand("45 6 * * *", after, dias=3)
    assert dias[0] == _utc(2026, 1, 16, 5, 45)
    assert [d.hour for d in dias] == [5, 5, 5]


def test_expande_diaria_en_verano_cest():
    # 15 de julio: Madrid = UTC+2, la misma pared 06:45 son 04:45Z.
    after = _utc(2026, 7, 15, 12, 0)
    dias = notif.expand("45 6 * * *", after, dias=2)
    assert dias[0] == _utc(2026, 7, 16, 4, 45)


def test_expand_es_estrictamente_posterior():
    # A las 06:00Z de invierno, las 06:45 de pared (05:45Z) de hoy ya pasaron.
    after = _utc(2026, 1, 15, 6, 0)
    dias = notif.expand("45 6 * * *", after, dias=1)
    assert dias[0] == _utc(2026, 1, 16, 5, 45)
    # …pero a las 05:00Z aún no, y la primera ocurrencia es la de hoy.
    dias = notif.expand("45 6 * * *", _utc(2026, 1, 15, 5, 0), dias=1)
    assert dias[0] == _utc(2026, 1, 15, 5, 45)


def test_expande_semanal_solo_sus_dias():
    # 2026-01-15 es jueves. `1,3` = lunes y miércoles.
    after = _utc(2026, 1, 15, 12, 0)
    dias = notif.expand("0 7 * * 1,3", after, dias=7)
    assert [d.weekday() for d in dias] == [0, 2]  # date.weekday(): 0=lunes
    assert dias[0].date().isoformat() == "2026-01-19"


def test_expand_cruza_el_cambio_de_hora():
    """El último domingo de marzo de 2026 (el 29) Madrid salta a CEST.

    La pared se queda en 06:45; el instante UTC baja una hora. Este es el
    comportamiento que costaría un desayuno avisado a las 07:45 si alguien
    "simplificara" la conversión a un offset fijo.
    """
    after = _utc(2026, 3, 27, 12, 0)  # viernes antes del cambio
    dias = notif.expand("45 6 * * *", after, dias=3)
    horas_utc = [(d.date().isoformat(), d.hour) for d in dias]
    assert ("2026-03-28", 5) in horas_utc  # todavía CET
    assert ("2026-03-30", 4) in horas_utc  # ya CEST


# ── build_payload: filas → lo que Dart programa ──────────────────────────


def test_payload_diario_materializa_la_ventana():
    filas = [
        {
            "id": 3,
            "texto": "**Pesaje**\nEn ayunas, tras el baño.",
            "proxima": _utc(2026, 1, 15, 5, 45),
            "cron": "45 6 * * *",
            "activo": True,
        }
    ]
    now = _utc(2026, 1, 15, 12, 0)
    payload = notif.build_payload(filas, now=now)
    assert len(payload) == notif.HORIZONTE_DIAS
    primero = payload[0]
    # Markdown fuera y primera línea al título; ids sin colisión por fila.
    assert primero["title"] == "Pesaje"
    assert primero["body"] == "En ayunas, tras el baño."
    assert primero["id"] == 3 * 1000
    assert payload[1]["id"] == 3001
    assert primero["when"] == "2026-01-16T05:45:00+00:00"


def test_payload_una_vez_usa_proxima_y_caduca():
    fila = {"id": 9, "texto": "Llamar al fisio", "proxima": _utc(2026, 1, 20, 10, 0), "cron": None}
    aun_no = notif.build_payload([fila], now=_utc(2026, 1, 15))
    assert [p["when"] for p in aun_no] == ["2026-01-20T10:00:00+00:00"]
    # Pasada la hora, la fila una-vez no produce nada: no hay pasado que avisar.
    ya_paso = notif.build_payload([fila], now=_utc(2026, 1, 21))
    assert ya_paso == []


def test_payload_cron_rico_cae_a_proxima():
    """Una fila del bot con `*/15 9-21 * * *` no se descarta ni se adivina:

    la única verdad que este módulo puede afirmar sin duplicar el parser del
    bot es su `proxima`, una sola vez."""
    fila = {
        "id": 4,
        "texto": "Bebe agua",
        "proxima": _utc(2026, 1, 15, 15, 0),
        "cron": "*/15 9-21 * * *",
        "activo": True,
    }
    payload = notif.build_payload([fila], now=_utc(2026, 1, 15, 12, 0))
    assert [p["when"] for p in payload] == ["2026-01-15T15:00:00+00:00"]


def test_payload_ignora_inactivos_y_proxima_naive_es_utc():
    filas = [
        {"id": 1, "texto": "apagado", "proxima": _utc(2026, 1, 16), "cron": None, "activo": False},
        # Naive, como lo devuelve SQLite: el convenio del repo es que ES UTC.
        {"id": 2, "texto": "naive", "proxima": datetime(2026, 1, 16, 8, 0), "cron": None},
    ]
    payload = notif.build_payload(filas, now=_utc(2026, 1, 15))
    assert [p["id"] for p in payload] == [2000]
    assert payload[0]["when"] == "2026-01-16T08:00:00+00:00"


def test_payload_texto_vacio_no_rompe():
    fila = {"id": 5, "texto": "", "proxima": _utc(2026, 1, 16), "cron": None}
    payload = notif.build_payload([fila], now=_utc(2026, 1, 15))
    assert payload[0]["title"] == "Recordatorio"


# ── el CRUD de storage que alimenta todo esto ────────────────────────────


def test_add_reminder_valida_y_recorta(store):
    with pytest.raises(ValueError):
        store.add_reminder("   ", _utc(2026, 1, 16))
    with pytest.raises(ValueError):
        store.add_reminder("sin zona", datetime(2026, 1, 16, 8, 0))  # naive
    rid = store.add_reminder("x" * 600, _utc(2026, 1, 16, 8, 0), cron="0 8 * * *")
    fila = next(f for f in store.get_all_reminders() if f["id"] == rid)
    assert len(fila["texto"]) == 500
    assert fila["origen"] == "usuario"
    assert fila["cron"] == "0 8 * * *"
    assert fila["activo"] is True


def test_delete_y_pausa_respetan_los_fijos(store):
    rid = store.add_reminder("mío", _utc(2026, 1, 16, 8, 0))
    # Sembrar un fijo como lo haría el bot, directo por el ORM.
    from storage import Recordatorio

    with store._Session() as se:
        fijo = Recordatorio(
            texto="**Pesaje**",
            proxima=_utc(2026, 1, 16, 5, 45),
            cron="45 6 * * *",
            origen="fijo",
            clave="pesaje",
            activo=True,
            creado=_utc(2026, 1, 1),
        )
        se.add(fijo)
        se.commit()
        fijo_id = fijo.id

    assert store.delete_reminder(fijo_id) is False  # el bot lo re-sembraría
    assert store.set_reminder_active(fijo_id, False) is False
    assert store.delete_reminder(999_999) is False  # desaparecida ≠ excepción
    assert store.set_reminder_active(rid, False) is True
    assert store.delete_reminder(rid) is True
    assert all(f["id"] != rid for f in store.get_all_reminders())


# ── sync: los dos efectos, cada uno con su guarda ────────────────────────


def test_sync_escribe_json_atomico_y_refresca_proxima(store, tmp_path):
    rid = store.add_reminder(
        "Creatina", _utc(2026, 1, 10, 7, 0), cron=notif.cron_para("daily", 8, 0)
    )
    # `proxima` quedó atrás a propósito: sync debe adelantarla (esto es SQLite).
    destino = tmp_path / "notifications.json"
    ahora = _utc(2026, 1, 15, 12, 0)
    payload = notif.sync(store, now=ahora, target=destino)

    assert destino.exists() and not destino.with_suffix(".tmp").exists()
    en_disco = json.loads(destino.read_text(encoding="utf-8"))
    assert en_disco == payload and len(payload) == notif.HORIZONTE_DIAS

    fila = next(f for f in store.get_all_reminders() if f["id"] == rid)
    proxima = fila["proxima"]
    if proxima.tzinfo is None:  # SQLite devuelve naive-UTC
        proxima = proxima.replace(tzinfo=timezone.utc)
    assert proxima > ahora
    assert proxima == datetime.fromisoformat(payload[0]["when"])


def test_sync_sin_destino_no_escribe_pero_devuelve(store, tmp_path, monkeypatch):
    """En el PC (sin FLET_APP_STORAGE_DATA) no hay fichero que escribir.

    El payload se devuelve igualmente: la pantalla de avisos lo usa para decir
    cuántas notificaciones quedan programadas."""
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    store.add_reminder("Estirar", _utc(2026, 1, 16, 19, 0))
    payload = notif.sync(store, now=_utc(2026, 1, 15))
    assert len(payload) == 1
    assert not list(tmp_path.glob("*.json"))


def test_sync_en_postgres_no_toca_proxima(tmp_path):
    """La guarda del doble planificador, sin PostgreSQL de verdad.

    Un stub con la URL del backend compartido y un `touch_reminder` que
    explota: si sync intentara refrescar `proxima` ahí, este test lo oiría.
    En el Postgres real quien avanza la fila es el bot al disparar."""

    class _Stub:
        class _engine:
            url = "postgresql+psycopg://entrenador@127.0.0.1:5432/entrenador"

        def get_all_reminders(self):
            return [
                {
                    "id": 1,
                    "texto": "Pesaje",
                    "proxima": _utc(2026, 1, 10, 5, 45),
                    "cron": "45 6 * * *",
                    "activo": True,
                }
            ]

        def touch_reminder(self, rid, proxima):
            raise AssertionError("proxima es del bot en PostgreSQL")

    destino = tmp_path / "n.json"
    payload = notif.sync(_Stub(), now=_utc(2026, 1, 15, 12, 0), target=destino)
    assert len(payload) == notif.HORIZONTE_DIAS  # el fichero sí; la tabla no


def test_sync_traga_disco_roto(store, tmp_path):
    """Un destino imposible cuesta avisos, nunca el arranque de la app."""
    store.add_reminder("Agua", _utc(2026, 1, 16, 9, 0))
    imposible = tmp_path / "fichero" / "dentro" / "de" / "fichero"
    imposible.parent.parent.parent.write_text("soy un fichero, no un directorio")
    payload = notif.sync(store, now=_utc(2026, 1, 15), target=imposible)
    assert len(payload) == 1  # devuelto igualmente; la escritura falló en silencio
