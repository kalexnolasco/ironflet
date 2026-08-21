"""Google Calendar para IronFlet: httpx puro contra la API v3.

Sin `google-api-python-client` a propósito, por la misma razón que el coach
habla con OpenRouter a pelo: el SDK arrastra dependencias que complican la
APK, y las tres llamadas que esta app necesita — refrescar el token, listar
eventos, crear/borrar uno — son tres peticiones HTTPS con JSON.

## De dónde salen las credenciales

Del OAuth que el bot del PC ya hizo en su día (`agente/token_google.json`,
scope `auth/calendar`). Dos caminos hacia las prefs (las tres claves están en
`storage.SECRET_PREF_KEYS`: nunca entran en una copia de seguridad):

* **En el PC**: `conectar_desde_bot()` lee ese fichero y copia client_id,
  client_secret y refresh_token. Un toque.
* **En el móvil** (o donde no esté el bot): el flujo *loopback* de app
  instalada — `iniciar_oauth()` abre el navegador con la URL de Google y un
  servidor de un solo uso en 127.0.0.1 espera el `code`; Chrome puede
  redirigir al localhost del propio dispositivo, así que funciona en Android
  sin componentes nativos nuevos.

## La regla de siempre

Leer es libre; **crear eventos pasa por tarjeta**. `agent.py` expone la
lectura como herramienta y la creación solo como propuesta — el modelo no
tiene ningún camino hasta `crear_evento()`.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time as time_mod
import urllib.parse
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx

from storage import _madrid

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"

CLIENT_ID_PREF = "gcal_client_id"
CLIENT_SECRET_PREF = "gcal_client_secret"
REFRESH_PREF = "gcal_refresh_token"

#: Access token vivo, por proceso. Google los da para ~1 h; cachearlo evita un
#: refresh por render de la tarjeta de agenda. No va a prefs: es efímero y
#: guardarlo solo crearía un segundo secreto que caduca.
_cache: dict = {"token": None, "expira": 0.0}


class GcalError(RuntimeError):
    """Algo que el usuario puede leer: sin conexión, sin permiso, token caído."""


# ── credenciales ──────────────────────────────────────────────────────────


def conectado(store: Any) -> bool:
    return bool(
        (store.get_pref(REFRESH_PREF) or "").strip()
        and (store.get_pref(CLIENT_ID_PREF) or "").strip()
    )


def desconectar(store: Any) -> None:
    """Borra las credenciales locales. El acceso en sí se revoca en Google."""
    for clave in (CLIENT_ID_PREF, CLIENT_SECRET_PREF, REFRESH_PREF):
        store.set_pref(clave, "")
    _cache["token"], _cache["expira"] = None, 0.0


def ruta_token_bot() -> Path:
    """Dónde vive el token del bot cuando esta app corre en el PC."""
    return Path(__file__).resolve().parent.parent / "agente" / "token_google.json"


def conectar_desde_bot(store: Any, ruta: Path | str | None = None) -> bool:
    """Copia las credenciales del token del bot a las prefs. Solo tiene
    sentido en el PC; en el móvil el fichero no existe y devuelve False."""
    fichero = Path(ruta) if ruta else ruta_token_bot()
    try:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not all(datos.get(c) for c in ("client_id", "client_secret", "refresh_token")):
        return False
    store.set_pref(CLIENT_ID_PREF, datos["client_id"])
    store.set_pref(CLIENT_SECRET_PREF, datos["client_secret"])
    store.set_pref(REFRESH_PREF, datos["refresh_token"])
    _cache["token"], _cache["expira"] = None, 0.0
    return True


# ── el flujo loopback para conectar sin el bot ────────────────────────────


def iniciar_oauth(store: Any, abrir_url, timeout: float = 240.0) -> threading.Thread:
    """Conecta la cuenta con el flujo de app instalada (loopback).

    `abrir_url` recibe la URL de autorización (la vista pasa
    `page.launch_url`). Un servidor de UN SOLO USO espera en 127.0.0.1 el
    redirect con el `code`, lo intercambia y guarda el refresh token. Corre en
    un hilo para no congelar la interfaz; el hilo muere solo tras `timeout`.

    Requiere que las prefs ya tengan client_id/client_secret (los de un
    cliente OAuth de tipo "Desktop app" — los del bot valen y no son secretos
    de verdad en una app instalada; Google lo documenta así).
    """
    client_id = (store.get_pref(CLIENT_ID_PREF) or "").strip()
    client_secret = (store.get_pref(CLIENT_SECRET_PREF) or "").strip()
    if not client_id or not client_secret:
        raise GcalError(
            "Faltan el client_id y el client_secret. En el PC usa "
            "«Importar del bot» primero; el móvil los hereda al conectarse una vez."
        )

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    servidor.settimeout(timeout)
    puerto = servidor.getsockname()[1]
    redirect = f"http://127.0.0.1:{puerto}"

    url = (
        AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                # Sin esto Google solo devuelve refresh_token la PRIMERA vez que
                # la cuenta autoriza este cliente; reconectar quedaría sin token.
                "prompt": "consent",
            }
        )
    )

    def _espera():
        try:
            conexion, _ = servidor.accept()
            with conexion:
                peticion = conexion.recv(4096).decode("utf-8", "replace")
                linea = peticion.split("\r\n", 1)[0]
                consulta = urllib.parse.urlparse(linea.split(" ")[1]).query
                code = urllib.parse.parse_qs(consulta).get("code", [""])[0]
                cuerpo = (
                    "<html><body style='font-family:sans-serif'>"
                    "<h3>IronFlet conectado ✓</h3>Ya puedes volver a la app."
                    "</body></html>"
                    if code
                    else "<html><body><h3>Sin código — vuelve a intentarlo.</h3></body></html>"
                )
                conexion.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                    + cuerpo.encode()
                )
            if not code:
                return
            respuesta = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect,
                    "grant_type": "authorization_code",
                },
                timeout=30,
            )
            datos = respuesta.json()
            refresco = datos.get("refresh_token")
            if refresco:
                store.set_pref(REFRESH_PREF, refresco)
                _cache["token"], _cache["expira"] = None, 0.0
        except Exception:
            # El hilo jamás puede tumbar la app: un fallo aquí se ve como
            # "sigue sin conectar" y el usuario reintenta.
            pass
        finally:
            with contextlib.suppress(Exception):
                servidor.close()

    hilo = threading.Thread(target=_espera, daemon=True)
    hilo.start()
    abrir_url(url)
    return hilo


# ── el token de acceso ────────────────────────────────────────────────────


def _access_token(store: Any) -> str:
    if _cache["token"] and time_mod.monotonic() < _cache["expira"]:
        return _cache["token"]
    refresh = (store.get_pref(REFRESH_PREF) or "").strip()
    client_id = (store.get_pref(CLIENT_ID_PREF) or "").strip()
    client_secret = (store.get_pref(CLIENT_SECRET_PREF) or "").strip()
    if not refresh:
        raise GcalError("El calendario no está conectado — Ajustes → Calendario de Google.")
    try:
        r = httpx.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise GcalError(f"Sin conexión con Google: {exc}") from exc
    if r.status_code != 200:
        raise GcalError("Google rechazó el token del calendario — desconecta y vuelve a conectar.")
    datos = r.json()
    _cache["token"] = datos["access_token"]
    _cache["expira"] = time_mod.monotonic() + int(datos.get("expires_in") or 3600) - 60
    return _cache["token"]


# ── las tres operaciones ──────────────────────────────────────────────────


def eventos(store: Any, days: int = 7) -> list[dict]:
    """Los próximos `days` días, ordenados, en la zona de Madrid.

    Normalizados a lo que la tarjeta y el coach necesitan: `{id, title,
    start, end, all_day, day}` con `start`/`end` en ISO local. `singleEvents`
    expande las recurrencias — sin ello un "entreno L-X-V" sería una sola
    fila con una regla RRULE que nadie quiere parsear.
    """
    zona = _madrid()
    ahora = datetime.now(zona)
    fin = ahora + timedelta(days=max(1, min(60, days)))
    r = httpx.get(
        f"{API}/calendars/primary/events",
        params={
            "timeMin": ahora.isoformat(),
            "timeMax": fin.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
        },
        headers={"Authorization": f"Bearer {_access_token(store)}"},
        timeout=30,
    )
    if r.status_code != 200:
        raise GcalError(f"Google contestó {r.status_code} al listar eventos.")
    salida = []
    for item in r.json().get("items", []):
        inicio = item.get("start") or {}
        final = item.get("end") or {}
        all_day = "date" in inicio
        comienzo = inicio.get("dateTime") or inicio.get("date") or ""
        salida.append(
            {
                "id": item.get("id") or "",
                "title": item.get("summary") or "(sin título)",
                "start": comienzo,
                "end": final.get("dateTime") or final.get("date") or "",
                "all_day": all_day,
                "day": comienzo[:10],
            }
        )
    return salida


def crear_evento(
    store: Any,
    title: str,
    day: date,
    hhmm: str | None,
    duration_min: int = 60,
    description: str = "",
) -> str:
    """Crea el evento y devuelve su id. Sin hora → evento de día completo."""
    zona = _madrid()
    cuerpo: dict = {"summary": title.strip()[:200]}
    if description.strip():
        cuerpo["description"] = description.strip()[:1000]
    if hhmm:
        hh, mm = (int(p) for p in hhmm.split(":")[:2])
        inicio = datetime.combine(day, time(hh, mm), tzinfo=zona)
        cuerpo["start"] = {"dateTime": inicio.isoformat()}
        cuerpo["end"] = {"dateTime": (inicio + timedelta(minutes=max(5, duration_min))).isoformat()}
    else:
        cuerpo["start"] = {"date": day.isoformat()}
        cuerpo["end"] = {"date": (day + timedelta(days=1)).isoformat()}
    r = httpx.post(
        f"{API}/calendars/primary/events",
        json=cuerpo,
        headers={"Authorization": f"Bearer {_access_token(store)}"},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise GcalError(f"Google contestó {r.status_code} al crear el evento.")
    return r.json().get("id") or ""


def borrar_evento(store: Any, event_id: str) -> bool:
    r = httpx.delete(
        f"{API}/calendars/primary/events/{urllib.parse.quote(event_id)}",
        headers={"Authorization": f"Bearer {_access_token(store)}"},
        timeout=30,
    )
    return r.status_code in (200, 204)


def _flag_pc() -> bool:
    """True en el PC (donde puede existir el token del bot)."""
    return not os.environ.get("FLET_APP_STORAGE_DATA")
