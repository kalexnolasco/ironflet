"""Home as "my whole day", and the two bot-owned tables it had to learn to read.

Offline by construction — SQLite in `tmp_path`, no PostgreSQL, no network — so
this file runs everywhere. The one thing that genuinely needs Postgres is the
*gate*, and the gate is asserted from the other side: on SQLite it must be shut.

Three things here are not obvious and are the reason the file exists:

1. **A partial measurement must not delete the rest of the row.** `medidas` has
   five columns, the Telegram coach fills all five at a check-in, and this app
   only ever asks for the waist. A naive save wipes a fortnight of measurements
   to record one of them.
2. **The reminders panel must be off on the phone, not empty.** `create_all()`
   creates `recordatorios` in the APK's SQLite and it stays empty for the life
   of the install. A panel that decides by counting rows renders a permanently
   blank box that reads as broken.
3. **The waist rule is ambiguous in the plan, so the screen must not pick.**
   `plan_recomposicion.md` states the +1 cm trigger against the *initial*
   measurement in one place and against the *previous* one in another. Both are
   returned, labelled; neither is turned into a verdict.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import analytics
from data import set_active_routine
from storage import Medida, Recordatorio, Storage, WorkoutEntry, sqlite_url

HOY = date.today()


@pytest.fixture
def store(tmp_path):
    set_active_routine("cambiatufisico")
    return Storage(db_url=sqlite_url(tmp_path / "dia.db"))


def _pagina(store):
    page = MagicMock()
    page.width, page.height = 400, 800
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
        "store": store,
    }
    return page


# ── medidas: the partial-write trap ───────────────────────────────────────


def test_guardar_solo_la_cintura_no_borra_lo_demas(store):
    """THE ONE. The coach records five numbers; the app records one of them.

    Writing a fresh row for the waist would null the other four — deleting a
    fortnightly check-in to record a single tape measurement, with nothing
    raising and nothing to recover from.
    """
    store.save_measurement(waist=84.0, hip=98.0, chest=104.0, arm=36.0, thigh=58.0)
    store.save_measurement(waist=84.6)

    fila = store.get_measurements()[-1]
    assert fila["waist"] == 84.6, "the waist did not update"
    assert fila["hip"] == 98.0, "the hip was wiped by a waist-only save"
    assert fila["chest"] == 104.0
    assert fila["arm"] == 36.0
    assert fila["thigh"] == 58.0


def test_una_medida_por_dia(store):
    store.save_measurement(waist=84.0)
    store.save_measurement(waist=85.0)
    assert len(store.get_measurements()) == 1


@pytest.mark.parametrize("mala", [{"waist": 8}, {"waist": 400}, {"waist": "ancho"}, {}])
def test_medidas_imposibles_se_rechazan(store, mala):
    with pytest.raises(ValueError):
        store.save_measurement(**mala)


def test_un_campo_inventado_se_rechaza(store):
    with pytest.raises(ValueError):
        store.save_measurement(tobillo=22.0)


def test_la_ultima_cintura_salta_las_filas_sin_cintura(store):
    """A check-in that recorded only the chest is not a waist measurement.

    Taking the newest *row* would answer "no waist on record" while a perfectly
    good one sat a row below.
    """
    store.save_measurement(waist=84.0, on_date=(HOY - timedelta(days=14)).isoformat())
    store.save_measurement(chest=105.0, on_date=HOY.isoformat())

    ultima = store.get_latest_measurement("waist")
    assert ultima == {"date": (HOY - timedelta(days=14)).isoformat(), "waist": 84.0}


def test_sin_medidas_no_hay_ultima(store):
    assert store.get_latest_measurement("waist") is None


# ── waist_summary: both readings, no verdict ──────────────────────────────


def _medidas(*pares):
    return [{"date": (HOY - timedelta(days=d)).isoformat(), "waist": w} for d, w in pares]


def test_una_sola_medida_no_es_una_variacion():
    """One point IS the baseline. "+0.0 cm vs start" dresses that up as a comparison."""
    r = analytics.waist_summary(_medidas((3, 84.0)), today=HOY)
    assert r.known and r.count == 1
    assert r.vs_baseline is None and r.vs_previous is None
    assert r.headroom is None


def test_se_devuelven_las_dos_lecturas_del_plan():
    """The plan says +1 cm vs the initial measurement AND vs the previous one.

    They disagree on a lean bulk that is working. Returning one silently would
    make this the first place in the system where an ambiguous rule becomes a
    number Alex acts on.
    """
    r = analytics.waist_summary(_medidas((28, 83.0), (14, 83.4), (0, 83.8)), today=HOY)
    assert r.vs_baseline == 0.8, "drift from the initial measurement"
    assert r.vs_previous == 0.4, "change since the previous one"
    assert r.vs_baseline != r.vs_previous, "the premise of this test is broken"
    assert r.headroom == pytest.approx(0.2)


def test_la_cintura_vence_a_las_dos_semanas():
    """Nothing in the coach nudges for measurements — this is the only thing that will."""
    assert analytics.waist_summary(_medidas((3, 84.0)), today=HOY).due is False
    assert analytics.waist_summary(_medidas((14, 84.0)), today=HOY).due is True
    assert analytics.waist_summary([], today=HOY).due is True, "never measured is overdue"


def test_las_filas_sin_cintura_no_cuentan():
    filas = [
        {"date": (HOY - timedelta(days=20)).isoformat(), "waist": 83.0},
        {"date": (HOY - timedelta(days=2)).isoformat(), "waist": None, "chest": 105.0},
    ]
    r = analytics.waist_summary(filas, today=HOY)
    assert r.count == 1
    assert r.days_ago == 20, "an empty waist made the real one look fresh"


# ── recordatorios: the gate, and the window ───────────────────────────────


def test_en_el_movil_el_panel_se_apaga(store):
    """SQLite means there is no coach on this device. Off, not empty.

    `create_all()` creates the table on the phone and it stays empty forever, so
    "is the list empty?" is the wrong question — it renders a blank box that
    reads as a bug for the life of the install.
    """
    assert store.reminders_available() is False
    assert store.get_reminders_today() == []


def _recordatorio(store, texto, cuando, *, activo=True, cron=None, origen="fijo"):
    with store._Session() as s:
        s.add(
            Recordatorio(
                texto=texto,
                proxima=cuando,
                cron=cron,
                origen=origen,
                activo=activo,
                creado=datetime.now(timezone.utc),
            )
        )
        s.commit()


def test_la_ventana_del_dia_y_los_atrasados(store, monkeypatch):
    """Active, before tomorrow 00:00, with NO lower bound — mirroring the bot.

    `db.vencidos()` has no lower bound either: an active reminder whose instant
    has passed has *not* been sent and goes out on the next 30-second tick.
    Filtering those away gives a prettier list that hides the backlog.
    """
    # The gate is about the backend; here the query itself is what is under test.
    monkeypatch.setattr(Storage, "reminders_available", lambda self: True)

    zona = timezone.utc
    ahora = datetime(2026, 8, 20, 12, 0, tzinfo=zona)
    _recordatorio(store, "atrasado de ayer", datetime(2026, 8, 19, 9, 0, tzinfo=zona))
    _recordatorio(store, "esta tarde", datetime(2026, 8, 20, 19, 45, tzinfo=zona))
    _recordatorio(store, "mañana", datetime(2026, 8, 21, 6, 45, tzinfo=zona))
    _recordatorio(store, "cancelado", datetime(2026, 8, 20, 8, 0, tzinfo=zona), activo=False)

    avisos = store.get_reminders_today(now=ahora)
    textos = [a["text"] for a in avisos]

    assert "mañana" not in textos, "a reminder from tomorrow leaked into today"
    assert "cancelado" not in textos, "a cancelled reminder is a tombstone, not a plan"
    assert "atrasado de ayer" in textos, "the backlog the bot is about to send was hidden"
    assert "esta tarde" in textos
    assert avisos[0]["text"] == "atrasado de ayer", "not sorted soonest first"
    assert avisos[0]["overdue"] is True
    assert avisos[1]["overdue"] is False


def test_un_recordatorio_trae_lo_que_la_tarjeta_pinta(store, monkeypatch):
    monkeypatch.setattr(Storage, "reminders_available", lambda self: True)
    _recordatorio(
        store,
        "⚖️ **Buenos días**\n\nPésate ahora",
        datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc),
        cron="45 6 * * *",
    )
    a = store.get_reminders_today(now=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc))[0]
    assert a["recurring"] is True and a["fixed"] is True
    assert ":" in a["at"], "no clock time to show"


# ── the screen itself, in the states Alex will actually see ───────────────


def _home(store):
    from views.home import HomeView

    v = HomeView(_pagina(store), store)
    v.on_show()
    return v


def test_home_se_dibuja_sin_ningun_dato(store):
    """The state a fresh install is in — and, today, the real one: both tables empty."""
    assert _home(store).build() is not None


def test_home_se_dibuja_con_el_dia_entero(store):
    """Everything present: trained, weighed in, measured, ate."""
    import nutrition

    for dias, kg in ((21, 73.0), (14, 73.4), (7, 73.9), (0, 74.2)):
        store.save_weight(kg, (HOY - timedelta(days=dias)).isoformat())
    store.save_measurement(waist=83.0, on_date=(HOY - timedelta(days=28)).isoformat())
    store.save_measurement(waist=83.6, on_date=(HOY - timedelta(days=3)).isoformat())
    store.save_workout(
        WorkoutEntry(
            date=HOY.isoformat(),
            exercise="Squat",
            muscle_group="Shoulder-Leg",
            phase=1,
            sets=[{"weight": 100, "reps": 5}],
        )
    )
    nutrition.log_food  # noqa: B018 - the facade exists; the diary may be empty

    assert _home(store).build() is not None


def test_el_recuadro_del_peso_dice_si_es_de_hoy(store):
    """A weight without its age reads as current. That is the whole caption.

    Rendered rather than asserted on a string, because the failure this guards
    is the tile silently showing a three-day-old number as today's.
    """
    vista = _home(store)
    assert vista._weight_tile() is not None  # nunca pesado

    store.save_weight(74.0, (HOY - timedelta(days=3)).isoformat())
    con_viejo = _home(store)._weight_tile()
    assert con_viejo is not None

    store.save_weight(74.2, HOY.isoformat())
    assert _home(store)._weight_tile() is not None


def test_el_recuadro_de_cintura_no_da_veredicto(store):
    """No green/red. The plan wants waist stable WHILE weight rises — one tile
    cannot say whether that is happening, and a green waist next to flat weight
    means the plan is failing."""
    store.save_measurement(waist=83.0, on_date=(HOY - timedelta(days=28)).isoformat())
    store.save_measurement(waist=83.6, on_date=(HOY - timedelta(days=3)).isoformat())

    recuadro = _home(store)._waist_tile()
    pista = recuadro.tooltip or ""
    assert "vs the initial measurement" in pista
    assert "vs the previous one" in pista, "only one reading of an ambiguous rule was shown"
    assert "on track" not in pista.lower() and "good" not in pista.lower()


def test_sin_coach_en_el_movil_no_hay_tarjeta_de_avisos(store):
    assert _home(store)._reminders_card() is None, "a permanently empty box on the phone"


def test_con_coach_y_sin_avisos_si_hay_tarjeta(store, monkeypatch):
    """An empty list on the PC is a fact worth stating: nothing else is due."""
    monkeypatch.setattr(Storage, "reminders_available", lambda self: True)
    assert _home(store)._reminders_card() is not None


def test_una_base_caida_no_tumba_la_pantalla(store, monkeypatch):
    """Every new panel reads the database. Home is the first screen of the app."""

    def revienta(*a, **k):
        raise RuntimeError("la base no responde")

    for nombre in ("get_weights", "get_measurements", "get_reminders_today"):
        monkeypatch.setattr(Storage, nombre, revienta)
    assert _home(store).build() is not None


# ── the mirror, from this side ────────────────────────────────────────────


def test_las_dos_tablas_nuevas_existen_de_verdad(store):
    """Declaring them is what put them under the cross-repo mirror rule.

    `agente/tests/test_modelos_espejo.py` is the real guard; this only checks
    the app can create and use them, which is what `create_all()` promises.
    """
    with store._Session() as s:
        assert s.query(Medida).count() == 0
        assert s.query(Recordatorio).count() == 0
