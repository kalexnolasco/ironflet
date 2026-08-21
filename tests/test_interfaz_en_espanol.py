"""Ningún texto de pantalla en inglés. El guardia, no la lista.

La app se tradujo entera y aun así `label="Date (YYYY-MM-DD)"` sobrevivió en
dos diálogos de `views/profile.py` — apareció en un barrido, se dio por
traducido, y siguió en pantalla dos versiones más hasta que alguien volvió a
abrir el diálogo de apuntar peso. Un barrido es una foto; esto es un guardia.

## Qué mira y qué no

Solo los **argumentos que pintan texto** (`label=`, `hint_text=`, `text=`,
`tooltip=`, `title=`) y las cadenas literales de `ft.Text(...)`, en los
módulos que construyen interfaz. No mira comentarios, ni docstrings, ni
nombres de variables, ni tests.

Y busca **palabras concretas**, no "inglés" en abstracto: la lista de abajo son
las que de verdad aparecieron en esta app. Un detector genérico de idioma daría
falsos positivos con los nombres de ejercicio, que están en inglés a propósito.

## Lo que está en inglés a propósito

Lo dice `CLAUDE.md` y la trampa 22 lo repite: nombres de ejercicios y sus
claves, `TrainingDay.name`, las claves de tipo de serie, las cadenas
`scheme`/`rest` de las fases. Nada de eso pasa por los argumentos que este
fichero mira, salvo cuando una vista los pinta — y para eso están
`set_types.describir_esquema/descanso`, que traducen para mostrar sin tocar
el dato.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

#: Módulos que construyen interfaz. `data.py` entra por sus `description`, que
#: se pintan en la pantalla Plan.
FUENTES = ("views", "components")
SUELTOS = ("main.py", "guides.py", "data.py")

#: Palabras que delatan un literal sin traducir. Todas salieron de esta app.
#: Se buscan con límites de palabra y sin distinguir mayúsculas.
_INGLESAS = (
    "date",
    "sets",
    "session",
    "sessions",
    "exercise",
    "exercises",
    "weeks",
    "phases",
    "missing",
    "remove",
    "removed",
    "routine",
    "week",
    "loadable",
    "warm-up",
    "warmup",
    "confirm",
    "next",
    "back off",
    "hold",
    "today",
    "yesterday",
    "save",
    "cancel",
    "delete",
    "close",
    "done",
    "search",
    "settings",
)
_RE_INGLESA = re.compile(
    r"(?<![\w'])(" + "|".join(re.escape(p) for p in _INGLESAS) + r")(?![\w'])", re.I
)

#: Argumentos cuyo valor se pinta. `value=` queda fuera a propósito: se usa
#: para el contenido de campos y para claves de desplegable, y ahí sí hay
#: valores en inglés que son contrato.
#
# **Sin `re.S`, y es load-bearing.** Con el punto casando saltos de línea, un
# `ft.Text("", size=11, ...)` —cadena vacía, que las hay— hacía que el regex se
# saltara las comillas de cierre y capturase todo el código hasta la siguiente
# comilla del fichero, con sus `def save(...)` y sus `day: date` dentro. Dos
# falsos positivos preciosos. Una cadena de Python de una línea no cruza saltos.
_RE_ARGUMENTO = re.compile(
    r"""\b(?:label|hint_text|helper_text|tooltip|dialog_title)\s*=\s*(["'])(.*?)\1"""
)
#: `ft.Text("...")` con una cadena literal como primer argumento.
_RE_TEXTO = re.compile(r"""ft\.Text\(\s*(["'])(.{2,120}?)\1""")

#: Excepciones justificadas, cada una con su motivo.
_PERMITIDO = {
    # Nombres propios y siglas que no se traducen.
    "OpenRouter",
    "IronFlet",
    "Google",
    "Telegram",
    "RIR",
    "1RM",
    # `set_types.SHORT_LABELS` y compañía: letras sueltas, no palabras.
    "N",
    "C",
    "D",
    "F",
}


def _ficheros_de_interfaz() -> list[Path]:
    salida: list[Path] = []
    for carpeta in FUENTES:
        salida.extend(sorted((RAIZ / carpeta).rglob("*.py")))
    salida.extend(RAIZ / nombre for nombre in SUELTOS if (RAIZ / nombre).exists())
    return salida


def _literales(texto: str) -> list[str]:
    """Las cadenas que se pintan, sin comentarios ni docstrings.

    Se quitan los comentarios de línea entera y los docstrings de tres comillas
    antes de buscar: los dos están llenos de prosa inglesa que es documentación
    y no interfaz.
    """
    sin_docstrings = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""', texto)
    sin_comentarios = re.sub(r"^\s*#.*$", "", sin_docstrings, flags=re.M)
    encontrados = [m.group(2) for m in _RE_ARGUMENTO.finditer(sin_comentarios)]
    encontrados += [m.group(2) for m in _RE_TEXTO.finditer(sin_comentarios)]
    return encontrados


@pytest.mark.parametrize("fichero", _ficheros_de_interfaz(), ids=lambda p: p.name)
def test_ningun_texto_de_pantalla_en_ingles(fichero):
    """El guardia. Falla nombrando el fichero, la palabra y la cadena entera."""
    culpables = []
    for literal in _literales(fichero.read_text(encoding="utf-8")):
        if literal in _PERMITIDO:
            continue
        # Un literal con `{}` puede ser una plantilla con nombres de ejercicio
        # dentro; se mira igual, porque la parte fija sí es texto de pantalla.
        for palabra in set(m.group(1).lower() for m in _RE_INGLESA.finditer(literal)):
            culpables.append(f"«{palabra}» en {literal!r}")
    assert not culpables, f"{fichero.relative_to(RAIZ)} pinta texto en inglés:\n  " + "\n  ".join(
        culpables
    )


def test_el_guardia_reconoce_lo_que_se_le_escapo():
    """Y que no se está midiendo con una vara imposible de fallar.

    Si `_INGLESAS` se vacía o el regex de argumentos deja de casar, los tests
    de arriba pasan a ser verdes vacíos. Esto comprueba que la cadena exacta
    que sobrevivió dos versiones sería detectada.
    """
    codigo = 'ft.TextField(\n    label="Date (YYYY-MM-DD)",\n)'
    literales = _literales(codigo)
    assert literales == ["Date (YYYY-MM-DD)"]
    assert _RE_INGLESA.search(literales[0]), "«Date» tiene que delatarse"


def test_el_guardia_no_se_queja_de_lo_que_debe_seguir_en_ingles():
    """Los nombres de ejercicio son contrato de datos y van en inglés.

    Pero no llegan por estos argumentos: se pintan desde variables, no desde
    literales. Un literal que sí los lleve —una plantilla— se mira por su
    parte fija, que es la que es texto de pantalla.
    """
    codigo = 'ft.Text(f"Serie {n} · {ejercicio}")'
    assert _literales(codigo) == [], "una f-string con variables no es un literal fijo"


def test_los_comentarios_y_docstrings_no_cuentan():
    """Están llenos de prosa inglesa que es documentación, no interfaz."""
    codigo = '''
def f():
    """Save the next session date."""
    # today and tomorrow
    return ft.Text("Guardar")
'''
    assert _literales(codigo) == ["Guardar"]
