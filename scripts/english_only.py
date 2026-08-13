"""Unwrap the translation layer. English-only, one file at a time.

The previous attempt used a regex and mangled docstrings, missed `t_muscle`,
`get_language` and the indented imports. This walks the AST instead: only real
`Call` nodes are touched, and each one is replaced by the exact source slice of
its argument, so `t(phase.name)` becomes `phase.name` and a `t(` inside a
docstring is invisible.

Two functions in i18n.py are NOT translation and must survive elsewhere:
`exercise_key()` (the database key shared with the Telegram bot) and the
date helpers. This script does not move them — it only unwraps calls and
rewrites imports to point at their new homes.

    .venv/bin/python scripts/english_only.py --dry-run
    .venv/bin/python scripts/english_only.py views/home.py
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Estas se desenvuelven: en inglés devuelven su argumento tal cual.
IDENTIDAD = {"t", "t_exercise", "t_muscle"}
# Estas sobreviven, en módulos nuevos.
MUDADAS = {
    "exercise_key": "exercises",
    "day_name": "dates",
    "month_name": "dates",
    "weekday_label": "dates",
}


# Dentro de una f-string, `{t('PHASE')}` no necesita interpolación: el literal
# se incrusta directamente y queda `f"PHASE ..."`. Se resuelve antes del AST
# porque las posiciones dentro de f-strings no son fiables entre versiones.
EN_FSTRING = re.compile(
    r"\{\s*(?:t|t_exercise|t_muscle)\(\s*(['\"])([^'\"{}]*)\1\s*\)\s*(\.lower\(\)|\.upper\(\))?\s*\}"
)


def _incrustar(m: re.Match) -> str:
    literal, metodo = m.group(2), m.group(3)
    if metodo == ".lower()":
        return literal.lower()
    if metodo == ".upper()":
        return literal.upper()
    # Las llaves del propio literal habría que escaparlas; no las hay en este repo.
    return literal


def aplanar_fstrings(fuente: str) -> tuple[str, int]:
    return EN_FSTRING.subn(_incrustar, fuente)


class Localizador(ast.NodeVisitor):
    """Recoge las llamadas a desenvolver con su posición exacta en el código."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[int, int, int, int]] = []

    def visit_Call(self, nodo: ast.Call) -> None:
        self.generic_visit(nodo)  # de dentro afuera: primero las anidadas
        if (
            isinstance(nodo.func, ast.Name)
            and nodo.func.id in IDENTIDAD
            and len(nodo.args) == 1
            and not nodo.keywords
        ):
            arg = nodo.args[0]
            self.llamadas.append(
                (nodo.lineno, nodo.col_offset, nodo.end_lineno, nodo.end_col_offset)
            )
            self.llamadas.append((arg.lineno, arg.col_offset, arg.end_lineno, arg.end_col_offset))


def desenvolver(fuente: str) -> tuple[str, int]:
    """Sustituye cada llamada por el texto exacto de su argumento.

    `col_offset` de ast va en BYTES UTF-8, no en caracteres. Con acentos o con
    la flecha de "Save → Next" (3 bytes, 1 carácter) los cortes se desplazan y
    parten los literales por la mitad. Por eso todo se hace sobre bytes y se
    decodifica al final.
    """
    arbol = ast.parse(fuente)
    loc = Localizador()
    loc.visit(arbol)
    if not loc.llamadas:
        return fuente, 0

    crudo = fuente.encode("utf-8")
    lineas = fuente.splitlines(keepends=True)
    inicios = [0]
    for linea in lineas:
        inicios.append(inicios[-1] + len(linea.encode("utf-8")))

    def desplazamiento(fila: int, columna: int) -> int:
        return inicios[fila - 1] + columna

    # Las posiciones llegan en parejas (llamada, argumento); se aplican de atrás
    # hacia delante para que los desplazamientos previos sigan siendo válidos.
    parejas = [(loc.llamadas[i], loc.llamadas[i + 1]) for i in range(0, len(loc.llamadas), 2)]
    parejas.sort(key=lambda p: desplazamiento(p[0][0], p[0][1]), reverse=True)

    for llamada, arg in parejas:
        ini_ll = desplazamiento(llamada[0], llamada[1])
        fin_ll = desplazamiento(llamada[2], llamada[3])
        ini_a = desplazamiento(arg[0], arg[1])
        fin_a = desplazamiento(arg[2], arg[3])
        crudo = crudo[:ini_ll] + crudo[ini_a:fin_a] + crudo[fin_ll:]

    return crudo.decode("utf-8"), len(parejas)


IMPORT_I18N = re.compile(r"^[ \t]*(from i18n import [^\n(]*\n|import i18n\n)", re.M)
IMPORT_PAREN = re.compile(r"^[ \t]*from i18n import \([^)]*\)\n", re.M)


def reescribir_imports(fuente: str) -> str:
    """Quita los imports de i18n y añade los de los módulos nuevos si hacen falta."""
    necesarios: dict[str, set[str]] = {}
    for nombre, modulo in MUDADAS.items():
        if re.search(rf"\b{nombre}\s*\(", fuente):
            necesarios.setdefault(modulo, set()).add(nombre)

    nuevos = "".join(
        f"from {mod} import {', '.join(sorted(n))}\n" for mod, n in sorted(necesarios.items())
    )
    fuente, n = IMPORT_PAREN.subn("", fuente)
    fuente, m = IMPORT_I18N.subn("", fuente)
    if (n or m) and nuevos:
        # Se coloca donde estaba el primer import del módulo, para que ruff
        # después lo ordene en su sitio.
        fuente = re.sub(
            r"^(from storage import|import flet as ft)", nuevos + r"\1", fuente, count=1, flags=re.M
        )
    return fuente


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ficheros", nargs="*", help="por defecto, todos")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    objetivos = (
        [RAIZ / f for f in args.ficheros]
        if args.ficheros
        else sorted([*(RAIZ / "views").glob("*.py"), RAIZ / "main.py"])
    )

    total = 0
    for ruta in objetivos:
        if not ruta.is_file() or ruta.name == "__init__.py":
            continue
        original = ruta.read_text(encoding="utf-8")
        texto, incrustados = aplanar_fstrings(original)
        texto, n = desenvolver(texto)
        n += incrustados
        texto = reescribir_imports(texto)
        if texto == original:
            continue
        total += n
        # No se escribe nada que no compile.
        try:
            ast.parse(texto)
        except SyntaxError as exc:
            print(f"  ❌ {ruta.name}: quedaría roto ({exc}), lo dejo intacto", file=sys.stderr)
            continue
        print(f"  {ruta.relative_to(RAIZ)}: {n} llamadas desenvueltas")
        if not args.dry_run:
            ruta.write_text(texto, encoding="utf-8")

    print(f"\n{total} llamadas desenvueltas" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
