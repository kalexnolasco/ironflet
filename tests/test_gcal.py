"""gcal.py sin red: refresh, parse de eventos, creación y credenciales.

El transporte (httpx.get/post/delete) se sustituye entero — un test que
tocara la API real necesitaría el refresh token de Alex, y una suite que
necesita un secreto de producción es una suite que deja de correrse (la
misma razón por la que test_agent.py stubbed el modelo).
"""

from __future__ import annotations

import json
from datetime import date

import pytest

import gcal
from storage import SECRET_PREF_KEYS, Storage


@pytest.fixture
def store(tmp_path):
    s = Storage(f"sqlite:///{tmp_path / 'gcal.db'}")
    s.set_pref(gcal.CLIENT_ID_PREF, "id-prueba.apps.googleusercontent.com")
    s.set_pref(gcal.CLIENT_SECRET_PREF, "secreto-prueba")
    s.set_pref(gcal.REFRESH_PREF, "refresh-prueba")
    return s


@pytest.fixture(autouse=True)
def _sin_cache():
    gcal._cache["token"], gcal._cache["expira"] = None, 0.0
    yield
    gcal._cache["token"], gcal._cache["expira"] = None, 0.0


class _Respuesta:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_las_credenciales_son_secretos_de_verdad():
    """La regla 19 de CLAUDE.md, aplicada: nada de esto entra en una copia."""
    for clave in (gcal.CLIENT_ID_PREF, gcal.CLIENT_SECRET_PREF, gcal.REFRESH_PREF):
        assert clave in SECRET_PREF_KEYS


def test_conectado_y_desconectar(store):
    assert gcal.conectado(store) is True
    gcal.desconectar(store)
    assert gcal.conectado(store) is False


def test_conectar_desde_bot_lee_el_token(tmp_path):
    s = Storage(f"sqlite:///{tmp_path / 'limpio.db'}")
    fichero = tmp_path / "token_google.json"
    fichero.write_text(
        json.dumps(
            {
                "client_id": "abc.apps.googleusercontent.com",
                "client_secret": "shhh",
                "refresh_token": "1//refresco",
                "scopes": ["https://www.googleapis.com/auth/calendar"],
            }
        )
    )
    assert gcal.conectar_desde_bot(s, ruta=fichero) is True
    assert gcal.conectado(s) is True
    # Un fichero a medias no conecta a medias.
    fichero.write_text(json.dumps({"client_id": "solo-esto"}))
    s2 = Storage(f"sqlite:///{tmp_path / 'limpio2.db'}")
    assert gcal.conectar_desde_bot(s2, ruta=fichero) is False
    assert gcal.conectado(s2) is False


def test_refresh_cachea_y_reutiliza(store, monkeypatch):
    llamadas = []

    def post_falso(url, data=None, timeout=None, **kw):
        llamadas.append(url)
        assert data["grant_type"] == "refresh_token"
        return _Respuesta(200, {"access_token": "acceso-1", "expires_in": 3600})

    monkeypatch.setattr(gcal.httpx, "post", post_falso)
    assert gcal._access_token(store) == "acceso-1"
    assert gcal._access_token(store) == "acceso-1"
    assert len(llamadas) == 1, "el segundo uso debe salir de la caché, no de la red"


def test_refresh_rechazado_da_error_legible(store, monkeypatch):
    monkeypatch.setattr(
        gcal.httpx, "post", lambda *a, **k: _Respuesta(400, {"error": "invalid_grant"})
    )
    with pytest.raises(gcal.GcalError, match="desconecta y vuelve a conectar"):
        gcal._access_token(store)


def test_sin_conectar_pide_ajustes(tmp_path):
    s = Storage(f"sqlite:///{tmp_path / 'sin.db'}")
    with pytest.raises(gcal.GcalError, match="no está conectado"):
        gcal._access_token(s)


def test_eventos_normaliza_horas_y_dias_enteros(store, monkeypatch):
    monkeypatch.setattr(
        gcal.httpx,
        "post",
        lambda *a, **k: _Respuesta(200, {"access_token": "t", "expires_in": 3600}),
    )

    def get_falso(url, params=None, headers=None, timeout=None):
        assert params["singleEvents"] == "true", "sin expandir recurrencias llega una RRULE"
        assert headers["Authorization"] == "Bearer t"
        return _Respuesta(
            200,
            {
                "items": [
                    {
                        "id": "ev1",
                        "summary": "Entreno",
                        "start": {"dateTime": "2026-08-22T18:00:00+02:00"},
                        "end": {"dateTime": "2026-08-22T19:00:00+02:00"},
                    },
                    {
                        "id": "ev2",
                        "start": {"date": "2026-08-23"},
                        "end": {"date": "2026-08-24"},
                    },
                ]
            },
        )

    monkeypatch.setattr(gcal.httpx, "get", get_falso)
    filas = gcal.eventos(store, days=7)
    assert filas[0]["title"] == "Entreno" and filas[0]["all_day"] is False
    assert filas[0]["day"] == "2026-08-22"
    assert filas[1]["title"] == "(sin título)" and filas[1]["all_day"] is True


def test_crear_evento_con_hora_y_de_dia_entero(store, monkeypatch):
    creados = []

    def post_falso(url, data=None, json=None, headers=None, timeout=None):
        if "oauth2" in url:
            return _Respuesta(200, {"access_token": "t", "expires_in": 3600})
        creados.append(json)
        return _Respuesta(200, {"id": "nuevo-ev"})

    monkeypatch.setattr(gcal.httpx, "post", post_falso)

    ident = gcal.crear_evento(
        store, "Meal prep", date(2026, 8, 23), "17:00", 90, "Preparaciones de la semana"
    )
    assert ident == "nuevo-ev"
    con_hora = creados[0]
    assert con_hora["start"]["dateTime"].startswith("2026-08-23T17:00")
    assert con_hora["end"]["dateTime"].startswith("2026-08-23T18:30")
    assert "+02:00" in con_hora["start"]["dateTime"], "agosto en Madrid es CEST"

    gcal.crear_evento(store, "Día de compra", date(2026, 8, 22), None)
    entero = creados[1]
    assert entero["start"] == {"date": "2026-08-22"}
    assert entero["end"] == {"date": "2026-08-23"}


def test_borrar_evento(store, monkeypatch):
    monkeypatch.setattr(
        gcal.httpx,
        "post",
        lambda *a, **k: _Respuesta(200, {"access_token": "t", "expires_in": 3600}),
    )
    monkeypatch.setattr(gcal.httpx, "delete", lambda *a, **k: _Respuesta(204))
    assert gcal.borrar_evento(store, "ev1") is True


def test_codigo_vinculo_ida_y_vuelta(store, tmp_path):
    codigo = gcal.codigo_vinculo(store)
    assert codigo and codigo.startswith("ifgc1:")

    movil = Storage(f"sqlite:///{tmp_path / 'movil.db'}")
    assert gcal.aplicar_codigo(movil, codigo) is True
    assert (movil.get_pref(gcal.CLIENT_ID_PREF) or "").endswith("googleusercontent.com")
    assert movil.get_pref(gcal.CLIENT_SECRET_PREF) == "secreto-prueba"
    # El refresh NO viaja en el código: cada dispositivo autoriza el suyo.
    assert not (movil.get_pref(gcal.REFRESH_PREF) or "").strip()
    assert gcal.conectado(movil) is False


def test_codigo_corrupto_se_rechaza(tmp_path):
    s = Storage(f"sqlite:///{tmp_path / 'x.db'}")
    assert gcal.aplicar_codigo(s, "") is False
    assert gcal.aplicar_codigo(s, "ifgc1:no-es-base64!!!") is False
    assert gcal.aplicar_codigo(s, "otra-cosa:abcd") is False
    import base64

    sin_dominio = "ifgc1:" + base64.urlsafe_b64encode(b"id-raro\nsecreto").decode()
    assert gcal.aplicar_codigo(s, sin_dominio) is False
    assert not (s.get_pref(gcal.CLIENT_ID_PREF) or "").strip()
