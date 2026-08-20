"""Etiquetas de fecha, solo en español.

Hubo un conmutador de idioma, luego una época "English only", y ahora esto: la
interfaz entera está en español porque Alex la pidió así, y estas siguen siendo
consultas planas sin capa de traducción — un solo idioma cada vez, el suyo.

Minúsculas a propósito: en español los días y los meses no se capitalizan, y
"Jue, 20 Ago" es exactamente el anglicismo que delata una traducción hecha con
prisa. Quien componga un titular ya capitalizará la frase entera si le toca.
"""

from __future__ import annotations

DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTHS = [
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
]
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie"]


def day_name(idx: int) -> str:
    """Abreviatura del día, lunes = 0."""
    return DAYS[idx % 7]


def month_name(idx: int) -> str:
    """Abreviatura del mes, enero = 0."""
    return MONTHS[idx % 12]


def weekday_label(idx: int) -> str:
    """Etiqueta de la semana de entreno: el plan solo corre de lunes a viernes."""
    return WEEKDAYS[idx % 5]
