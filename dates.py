"""Date labels, English only.

These used to switch on the active language. There is no active language any
more, so they are plain lookups.
"""

from __future__ import annotations

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def day_name(idx: int) -> str:
    """Weekday abbreviation, Monday = 0."""
    return DAYS[idx % 7]


def month_name(idx: int) -> str:
    """Month abbreviation, January = 0."""
    return MONTHS[idx % 12]


def weekday_label(idx: int) -> str:
    """Training-week label: the plan only runs Monday to Friday."""
    return WEEKDAYS[idx % 5]
