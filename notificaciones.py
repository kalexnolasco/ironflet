"""Recordatorios de la app → notificaciones del sistema, vía un fichero.

Flet 0.28.3 no expone ninguna API de notificaciones a Python, así que el puente
es un fichero: este módulo escribe `notifications.json` en
`FLET_APP_STORAGE_DATA`, y el `main.dart` de la plantilla forkeada lo relee — al
arrancar y con un sondeo de mtime cada tres segundos — cancelándolo todo y
reprogramando desde cero con `flutter_local_notifications`.

## El reparto de responsabilidades es deliberado

**Toda la aritmética de repetición está aquí**, en Python, donde hay tests. El
lado Dart no sabe qué es un cron ni un día de la semana: recibe una lista plana
de instantes absolutos (ISO con zona) y los programa tal cual. Así las dos
mitades no pueden discrepar sobre cuándo es el martes — la clase de fallo que
nadie nota hasta que un aviso suena a la hora equivocada.

El precio es una ventana: se materializan los próximos `HORIZONTE_DIAS` días de
cada aviso recurrente. Si la app no se abre en un mes, los avisos se agotan.
Para una app de entreno que se abre a diario es un no-problema, y la
alternativa — reimplementar el cron del bot en Dart — es exactamente la clase de
duplicación que este repo lleva evitando desde el espejo de esquema.

## Quién entrega qué

* **En el móvil** (SQLite): esta app es el planificador. Los avisos son filas
  locales de `recordatorios` y los entrega Android, con la app cerrada incluso.
* **En el PC** (PostgreSQL compartido): el bot de Telegram es el planificador —
  sondea `vencidos()` cada 30 s y entrega por Telegram. Ahí este módulo **no
  escribe nada**: ni fichero (no hay Android) ni `proxima` (avanzarla es del
  bot; dos planificadores sobre una tabla es como un aviso suena dos veces).

## La zona horaria es Madrid, no la del dispositivo

La misma decisión, documentada, de `storage.get_reminders_today()`: el cron del
bot se evalúa en reloj de pared de Madrid, y un aviso creado en el PC y restaurado
en el móvil debe significar la misma hora. `06:45` es 06:45 en Madrid todo el
año; el instante UTC que se emite se mueve solo con el cambio de hora.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from storage import _madrid, is_sqlite_url

#: Días de recurrencia que se materializan en el fichero. 30 días de un aviso
#: diario son 30 notificaciones; Android admite 500 alarmas pendientes por app,
#: así que cinco avisos diarios caben con margen de sobra.
HORIZONTE_DIAS = 30

#: `id` de fila → ids de notificación. Cada ocurrencia necesita un id entero de
#: 32 bits propio; multiplicar deja sitio para `HORIZONTE_DIAS` ocurrencias por
#: aviso sin colisiones hasta ids de fila de dos millones.
_FACTOR_ID = 1000

FICHERO = "notifications.json"

#: Lo escribe el lado Dart tras cada sincronización: `{"granted": bool,
#: "exact": bool, "updated": iso}`. Es la única ventana que Python tiene a los
#: permisos del sistema — el puente principal es de ida, este es el de vuelta.
ESTADO_FICHERO = "notif_status.json"


# ── el subconjunto de cron que la app escribe ─────────────────────────────


def parse_cron_simple(cron: str | None) -> dict | None:
    """`"45 6 * * *"` → `{minute, hour, weekdays}`; None si no es del subconjunto.

    El bot acepta cron completo (rangos, pasos, la regla OR de vixie). La app
    solo *escribe* dos formas — diaria y semanal a hora fija — y solo *expande*
    esas dos. Una fila con un cron más rico (creada hablando con el bot) no se
    descarta: cae al caso "una sola ocurrencia, la que diga `proxima`", que es
    la verdad más honesta disponible sin duplicar el parser del bot aquí.

    `weekdays` usa el convenio del cron y del bot: 0 y 7 son domingo, 1 lunes.
    Devuelve None — no lanza — para cualquier cosa fuera del subconjunto.
    """
    if not cron:
        return None
    partes = cron.strip().split()
    if len(partes) != 5:
        return None
    minuto, hora, dom, mes, dow = partes
    if dom != "*" or mes != "*":
        return None
    try:
        m, h = int(minuto), int(hora)
    except ValueError:
        return None
    if not (0 <= m <= 59 and 0 <= h <= 23):
        return None

    if dow == "*":
        return {"minute": m, "hour": h, "weekdays": None}

    dias: set[int] = set()
    for trozo in dow.split(","):
        try:
            d = int(trozo)
        except ValueError:
            return None
        if not 0 <= d <= 7:
            return None
        dias.add(0 if d == 7 else d)
    return {"minute": m, "hour": h, "weekdays": dias} if dias else None


def _python_weekday_a_cron(wd: int) -> int:
    """`date.weekday()` (0=lunes) → convenio cron (0=domingo, 1=lunes)."""
    return (wd + 1) % 7


def cron_para(kind: str, hour: int, minute: int, weekdays: set[int] | None = None) -> str | None:
    """La línea cron que la app escribe. `kind`: "once" | "daily" | "weekly".

    Emite el mismo dialecto que el bot parsea, porque una fila creada aquí en el
    PC la entrega el bot por Telegram: `45 6 * * *`, `30 17 * * 1,3`. Para
    "once" no hay cron — el bot desactiva la fila tras dispararla, y el móvil
    la programa una única vez.
    """
    if kind == "once":
        return None
    if kind == "daily":
        return f"{minute} {hour} * * *"
    if kind == "weekly":
        if not weekdays:
            raise ValueError("Un aviso semanal necesita al menos un día.")
        dias = ",".join(str(d) for d in sorted(weekdays))
        return f"{minute} {hour} * * {dias}"
    raise ValueError(f"Tipo de aviso desconocido: {kind!r}")


# ── expansión a instantes absolutos ───────────────────────────────────────


def _aware(valor: Any) -> datetime | None:
    """`proxima` tal y como vuelve de la base, a UTC-aware.

    Bajo PostgreSQL llega con zona; bajo SQLite llega naive **en UTC**, porque
    así la escribe esta app (el mismo convenio que `get_reminders_today`
    documenta). Interpretar el naive como hora local partiría cada aviso
    restaurado de un backup en una o dos horas, silenciosamente.
    """
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def next_occurrence(cron: str | None, after: datetime) -> datetime | None:
    """El siguiente instante (UTC) en que un cron del subconjunto dispararía.

    `after` debe ser aware. None para cron fuera del subconjunto — el llamante
    decide qué hacer con la fila, este módulo no adivina.
    """
    ocurrencias = expand(cron, after, dias=8 if cron else 0)
    return ocurrencias[0] if ocurrencias else None


def expand(cron: str | None, after: datetime, dias: int = HORIZONTE_DIAS) -> list[datetime]:
    """Todas las ocurrencias de un cron del subconjunto en los próximos `dias`.

    En reloj de pared de Madrid, devueltas en UTC, estrictamente posteriores a
    `after`. En los dos domingos de cambio de hora la conversión la hace
    `zoneinfo`: `45 6` sigue siendo 06:45 de pared, y el instante UTC se
    desplaza una hora — exactamente lo que hace el bot.
    """
    receta = parse_cron_simple(cron)
    if receta is None:
        return []

    zona = _madrid()
    cursor = after.astimezone(zona)
    salida: list[datetime] = []
    for delta in range(dias + 1):
        dia = (cursor + timedelta(days=delta)).date()
        if (
            receta["weekdays"] is not None
            and _python_weekday_a_cron(dia.weekday()) not in receta["weekdays"]
        ):
            continue
        momento = datetime.combine(dia, time(receta["hour"], receta["minute"]), tzinfo=zona)
        if momento > cursor:
            salida.append(momento.astimezone(timezone.utc))
    return salida


def _titulo_y_cuerpo(texto: str) -> tuple[str, str]:
    """Primera línea al título, el resto al cuerpo, sin el énfasis de Markdown.

    Los avisos fijos del bot traen `**negritas**` y varios párrafos pensados
    para Telegram; una notificación de Android muestra una línea y media. La
    primera línea limpia es el titular honesto y el resto queda expandible.
    """
    limpio = (texto or "").replace("**", "").strip()
    lineas = [ln.strip() for ln in limpio.splitlines() if ln.strip()]
    if not lineas:
        return ("Recordatorio", "")
    return (lineas[0][:80], " ".join(lineas[1:])[:200])


def build_payload(filas: list[dict], now: datetime | None = None) -> list[dict]:
    """Las filas de `recordatorios` → la lista plana que Dart programa.

    Puro: ni base de datos ni ficheros, para que los tests afirmen sobre
    instantes concretos. Cada elemento: `{id, title, body, when}` con `when` en
    ISO UTC. Las filas inactivas no existen a estos efectos — son lápidas.
    """
    ahora = now or datetime.now(timezone.utc)
    salida: list[dict] = []
    for fila in filas:
        if not fila.get("activo", True):
            continue
        titulo, cuerpo = _titulo_y_cuerpo(fila.get("texto") or "")
        base = int(fila["id"]) * _FACTOR_ID

        momentos = expand(fila.get("cron"), ahora)
        if not momentos:
            # Sin cron (una vez) o cron fuera del subconjunto: la única verdad
            # disponible es `proxima`, si aún no ha pasado.
            unica = _aware(fila.get("proxima"))
            momentos = [unica] if unica and unica > ahora else []

        for n, momento in enumerate(momentos[: _FACTOR_ID - 1]):
            salida.append(
                {
                    "id": base + n,
                    "title": titulo,
                    "body": cuerpo,
                    "when": momento.isoformat(),
                }
            )
    salida.sort(key=lambda x: x["when"])
    return salida


# ── el punto de sincronización ────────────────────────────────────────────


def _destino_por_defecto() -> Path | None:
    """Dónde escribe el fichero, o None cuando no toca escribirlo.

    Solo en Android: `FLET_APP_STORAGE_DATA` es la misma ruta que calcula el
    `main.dart` de la plantilla, y fuera del móvil no hay nadie escuchando —
    en el PC los avisos los entrega el bot por Telegram.
    """
    raiz = os.environ.get("FLET_APP_STORAGE_DATA")
    if not raiz:
        return None
    return Path(raiz) / FICHERO


def estado_android(target: Path | str | None = None) -> dict | None:
    """Los permisos de notificación tal y como los vio Dart, o None.

    None significa "no hay lado Dart" (PC, o el fichero aún no existe): ahí
    no hay nada que avisar. La interfaz solo debe alarmar cuando el fichero
    exista y diga que algo está apagado — un móvil recién instalado pasa por
    None durante los primeros segundos y eso no es un problema que enseñar.
    """
    if target is not None:
        ruta = Path(target)
    else:
        raiz = os.environ.get("FLET_APP_STORAGE_DATA")
        if not raiz:
            return None
        ruta = Path(raiz) / ESTADO_FICHERO
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict):
        return None
    return {
        "granted": bool(datos.get("granted", True)),
        "exact": bool(datos.get("exact", True)),
        # Ausente en un `notif_status.json` escrito por una versión anterior:
        # `False` es el defecto correcto porque no alarmar de algo que no se
        # sabe es mejor que alarmar sin motivo.
        "battery_optimised": bool(datos.get("battery_optimised", False)),
    }


#: Notas que se le dejan a Dart, en el mismo directorio y con el mismo
#: mecanismo que `notifications.json`. Flet no expone `MethodChannel` a Python,
#: así que un fichero es toda la forma que hay de pedirle algo al lado Android.
PETICION_PRUEBA = "notif_test.request"
PETICION_BATERIA = "battery_opt.request"


def _peticion(nombre: str, target: Path | str | None = None) -> bool:
    """Deja una nota para Dart. Devuelve si se pudo dejar."""
    if target is not None:
        ruta = Path(target)
    else:
        raiz = os.environ.get("FLET_APP_STORAGE_DATA")
        if not raiz:
            return False
        ruta = Path(raiz) / nombre
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("1", encoding="utf-8")
        return True
    except OSError:
        return False


def probar_aviso(target: Path | str | None = None) -> bool:
    """Pide un aviso inmediato. Es lo que convierte «no suena» en un dato.

    Sin esto no hay forma de separar «la app no programa la alarma» de
    «Android no la entrega»: desde fuera las dos son silencio, y llevan a
    sitios opuestos. Este no pasa por el planificador, así que si suena y los
    programados no, el problema está en la batería o en las alarmas exactas.
    """
    return _peticion(PETICION_PRUEBA, target)


def abrir_ajustes_bateria(target: Path | str | None = None) -> bool:
    """Pide abrir la pantalla donde se quita la optimización de batería."""
    return _peticion(PETICION_BATERIA, target)


def sync(store: Any, now: datetime | None = None, target: Path | str | None = None) -> list[dict]:
    """Reconstruye el fichero de notificaciones y refresca `proxima`.

    Se llama al arrancar la app y tras cada alta/edición/borrado. Devuelve el
    payload (para los tests y para que la interfaz pueda decir cuántos quedan).

    Dos efectos, cada uno con su guarda:

    * **El fichero** se escribe solo si hay destino (Android, o `target` en un
      test). Escritura atómica — tmp y `os.replace` — porque Dart lo relee por
      mtime cada tres segundos y un JSON a medio escribir sería "cancela todo".
    * **`proxima`** se refresca solo en SQLite. En el PostgreSQL compartido la
      avanza el bot al disparar; tocarla desde aquí sería un segundo
      planificador sobre la misma tabla. En el móvil nadie más la toca, y sin
      refresco un aviso diario ya disparado quedaría "atrasado" para siempre en
      la tarjeta de Home.
    """
    ahora = now or datetime.now(timezone.utc)
    try:
        filas = store.get_all_reminders()
    except Exception:
        filas = []

    payload = build_payload(filas, now=ahora)

    es_sqlite = False
    with contextlib.suppress(Exception):
        es_sqlite = is_sqlite_url(str(store._engine.url))

    if es_sqlite:
        for fila in filas:
            if not fila.get("activo") or not fila.get("cron"):
                continue
            siguiente = next_occurrence(fila["cron"], ahora)
            vieja = _aware(fila.get("proxima"))
            if siguiente and (vieja is None or vieja <= ahora):
                with contextlib.suppress(Exception):
                    store.touch_reminder(fila["id"], siguiente)

    destino = Path(target) if target else _destino_por_defecto()
    if destino is not None:
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, destino)
        except OSError:
            # Un disco que no deja escribir cuesta avisos, no la app.
            pass
    return payload
