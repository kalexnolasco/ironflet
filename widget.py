"""Lo de hoy, en la pantalla de inicio del móvil, sin abrir la app.

Mismo puente de fichero que `notificaciones.py` y por la misma razón: Flet no
expone widgets de Android a Python. Este módulo escribe `widget.json` en
`FLET_APP_STORAGE_DATA`; el `IronFletWidget.kt` de la plantilla forkeada lo lee
y pinta. Los dos procesos comparten UID, así que el widget puede leer el
almacenamiento privado de la app directamente — no hace falta ni
`SharedPreferences` ni un ContentProvider.

## Qué enseña, y por qué tan poco

Cuatro líneas: qué toca entrenar hoy, el peso, las calorías y la proteína. Un
widget se mira de refilón mientras se hace otra cosa, y lo único que justifica
un widget frente a abrir la app es que responda a «¿qué me toca?» y «¿cómo voy
hoy?» sin un solo toque. Todo lo demás cabe mejor dentro.

Nada de esto es una fuente nueva: sale de `program_week`, `Storage` y
`nutrition`, igual que la pantalla de Inicio. El widget es una vista, no un
sitio donde vivan datos.

## Por qué el payload es texto ya formateado

El JSON lleva `"82.4 kg"`, no `{"kg": 82.4}`. Kotlin no repite ninguna decisión
de formato — ni el separador decimal, ni el redondeo, ni cómo se dice "hoy toca
descansar". Toda esa lógica está en Python, donde hay tests, y el widget solo
pinta cadenas. Es el mismo reparto que con los avisos, donde la aritmética de
cron vive aquí y Dart recibe instantes planos: **las dos mitades no pueden
discrepar sobre algo que solo una de ellas decide.**

## Cuándo se refresca

`updatePeriodMillis` tiene un mínimo real de 30 minutos en Android, que para
esto sobra: lo que enseña cambia cuando abres la app, no por su cuenta. Y
cuando la app está delante, `main.dart` ya sondea este directorio cada tres
segundos por lo de los avisos, así que avisa al widget en cuanto el fichero
cambia. Entre esas dos vías no hay ningún caso en que se quede rancio.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

#: El nombre que `IronFletWidget.kt` abre. Escrito aquí una vez y allí una vez;
#: no hay una tercera copia.
FICHERO = "widget.json"

#: La nota que se le deja a Dart para que pida colocar el widget.
#:
#: Un fichero y no un canal porque **Flet no expone `MethodChannel` a Python**.
#: `main.dart` lo ve en el mismo sondeo de tres segundos que ya hace por los
#: avisos, lo borra y llama a Kotlin. Su contenido da igual: lo que significa
#: algo es que exista.
FICHERO_PIN = "widget_pin.request"

#: Qué se pinta cuando algo falla. Un widget que se queda con los datos de
#: ayer miente; uno que dice "abre la app" no.
VACIO: dict[str, str] = {
    "entreno": "Abre IronFlet",
    "peso": "",
    "kcal": "",
    "proteina": "",
}


def _destino_por_defecto() -> Path | None:
    """Dónde se escribe, o None cuando no hay nadie escuchando.

    Igual que `notificaciones._destino_por_defecto`: solo en Android, donde
    `FLET_APP_STORAGE_DATA` es la misma ruta que calcula el lado Kotlin.
    """
    raiz = os.environ.get("FLET_APP_STORAGE_DATA")
    return Path(raiz) / FICHERO if raiz else None


def _num(valor: float, decimales: int = 0) -> str:
    """`82.4` → `"82.4"`. Punto decimal, y sin `.0` cuando es entero.

    Punto y no coma **porque es lo que usa el resto de la app**: Inicio pone
    «80.5 kg», Ajustes «25.8» de IMC, la gráfica «82.4». Un widget con coma al
    lado de una app con punto es la misma cifra escrita de dos formas en la
    misma pantalla de inicio. Decisión de Alex, y la correcta: la coherencia
    dentro del producto pesa más que la convención del idioma cuando solo se
    puede tener una.
    """
    texto = f"{valor:.{decimales}f}"
    if decimales:
        texto = texto.rstrip("0").rstrip(".")
    return texto


def _linea_entreno(store: Any, dia: date) -> str:
    """«Chest-Biceps», «✓ Chest-Biceps», «Descanso» o «Abre IronFlet».

    El nombre del día va tal cual, en inglés: sale de `week_rotation` y es el
    mismo `TrainingDay.name` que se escribe en `entrenos.grupo` y que enseña
    Inicio. Traducirlo aquí sería un segundo vocabulario para lo mismo
    (trampa 22).

    El ✓ es media razón de ser del widget: mirar la pantalla de inicio y saber
    si ya entrenaste hoy sin abrir nada.
    """
    # `REST_LABEL` importado, no reescrito: es la etiqueta con la que
    # `week_rotation` marca el día libre, y una segunda copia aquí se
    # desincronizaría en silencio el día que cambie.
    from program_week import REST_LABEL, current_program_week

    try:
        semana = current_program_week(store, today=dia)
        foco = semana.today_focus
    except Exception:
        return VACIO["entreno"]

    try:
        # `get_workouts_on(hoy)`, no `get_today()`: esta función recibe el día
        # y tiene que respetarlo. Con `get_today()` el parámetro no hacía nada
        # —daba igual mientras el día pedido fuera el de hoy, que es siempre en
        # producción— y el widget habría dicho «no has entrenado» al pedirle
        # cualquier otra fecha.
        hecho = bool(store.get_workouts_on(dia))
    except Exception:
        hecho = False

    if hecho:
        # Si entrenaste, eso manda sobre lo que dijera la rotación — incluido
        # un día que el plan daba por libre.
        return f"✓ {foco}" if foco and foco != REST_LABEL else "✓ Hecho"
    if foco == REST_LABEL:
        return "Descanso"
    if not foco:
        # Sin rotación (o fin de semana, que la rotación no cubre) no se sabe
        # qué toca. Decirlo es mejor que inventar un "Descanso".
        return "Sin plan para hoy"
    return str(foco)


def payload(store: Any, hoy: date | None = None) -> dict[str, str]:
    """Las cuatro cadenas que pinta el widget, ya formateadas.

    Nunca lanza. Un widget es lo último que debe romperse por un dato que
    falta: cada bloque cae a cadena vacía por su cuenta, así que un peso sin
    apuntar no se lleva por delante las calorías.
    """
    dia = hoy or date.today()
    datos = dict(VACIO)

    datos["entreno"] = _linea_entreno(store, dia)

    try:
        pesos = store.get_weights()
        if pesos:
            datos["peso"] = f"{_num(float(pesos[-1]['kg']), 1)} kg"
    except Exception:
        pass

    try:
        from nutrition import day_totals, targets_for

        totales = day_totals(store, dia) or {}
        objetivos = targets_for(store, dia) or {}
        # Las claves son inglesas porque son contrato de datos, no texto
        # (trampa 22, y la que ya pintó «Proteína 0 g» una vez en Inicio).
        kcal = float(totales.get("kcal") or 0)
        proteina = float(totales.get("protein") or 0)
        meta_kcal = float(objetivos.get("kcal") or 0)
        meta_prot = float(objetivos.get("protein") or 0)
        datos["kcal"] = (
            f"{_num(kcal)} / {_num(meta_kcal)} kcal" if meta_kcal else f"{_num(kcal)} kcal"
        )
        datos["proteina"] = (
            f"{_num(proteina)} / {_num(meta_prot)} g P" if meta_prot else f"{_num(proteina)} g P"
        )
    except Exception:
        pass

    return datos


def sync(store: Any, hoy: date | None = None, target: Path | str | None = None) -> dict[str, str]:
    """Reescribe `widget.json`. Devuelve lo que se escribió.

    Escritura atómica por tmp + `os.replace`, igual que el puente de avisos: el
    lado Kotlin puede estar leyendo justo en ese momento, y un JSON a medias es
    un widget en blanco.

    Sin destino (en el escritorio) no escribe nada y devuelve el payload igual,
    que es lo que los tests miran.
    """
    datos = payload(store, hoy)
    ruta = Path(target) if target is not None else _destino_por_defecto()
    if ruta is None:
        return datos

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ruta)
    except OSError:
        # Un widget que no se puede actualizar no es motivo para tumbar la app.
        pass
    return datos


def disponible() -> bool:
    """Si hay un lado Android al que pedirle nada.

    En el escritorio no lo hay, y la pantalla de Ajustes usa esto para no
    ofrecer un botón que no puede hacer nada.
    """
    return _destino_por_defecto() is not None


def pedir_colocacion(target: Path | str | None = None) -> bool:
    """Deja la nota para que el lanzador ofrezca colocar el widget.

    Devuelve si se pudo dejar. Que se deje no garantiza que el widget acabe
    colocado: eso lo decide el lanzador (algunos de terceros no soportan la
    petición) y luego Alex en su diálogo. Por eso la pantalla que llama a esto
    dice «te lo va a ofrecer», no «hecho».
    """
    if target is not None:
        ruta = Path(target)
    else:
        base = _destino_por_defecto()
        if base is None:
            return False
        ruta = base.with_name(FICHERO_PIN)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("1", encoding="utf-8")
        return True
    except OSError:
        return False
