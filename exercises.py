"""The canonical exercise key.

Lifted verbatim out of the old i18n.py. Despite having lived among the
translations, this was never one: it turns a prescription string like
`"Squat [5×12,10,8,8,8]"` into `"Squat"`, and that stripped name is the key
under which every set is stored in `entrenos.ejercicio`.

The Telegram coach in ../agente/ writes and reads that same column through its
own `a_canonico()` mapping — all 28 of its exercise names resolve to keys this
function produces. Change the normalisation and the two halves of the history
stop matching, with no error to warn you.

tests/test_exercise_key.py freezes the behaviour: 282 routine strings collapse
into exactly 104 keys.
"""

from __future__ import annotations

import re as _re

_EXERCISE_BRACKETS_RE = _re.compile(r"^(.*?)((?:\s*\[[^\]]*\])*)\s*$")


def exercise_key(s: str) -> str:
    """Canonical DB key: strips trailing [..] brackets and trailing `*`."""
    m = _EXERCISE_BRACKETS_RE.match(s)
    name = m.group(1).rstrip() if m else s
    if name.endswith("*"):
        name = name[:-1].rstrip()
    return name


def phase_color(phase_id: int) -> str:
    """Colour for a training phase, taken from the active palette.

    `Phase.color` in data.py holds the original values, picked against a black
    background: #FFD93D sits at 1.38:1 on a white card, i.e. invisible. The
    palette carries seven hues darkened to work on light surfaces, so the phase
    is the *index* and the theme decides the shade.
    """
    from theme import C

    return C.phase[(phase_id - 1) % len(C.phase)]
