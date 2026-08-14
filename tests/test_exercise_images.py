"""Exercise images shipped broken twice, in two different ways.

First they were never downloaded at all, so `image_for()` returned None for
every exercise and the views rendered blank space that looked like a layout
bug. Then, once downloaded, they still did not show: the paths were `file://`
URLs, which a browser refuses to load from an http page ("Not allowed to load
local resource") — and web mode is how this app is actually used.

These tests pin both failures. They do not require the bundle to be present:
what must never regress is the *shape* of what the helpers return.
"""

from __future__ import annotations

import re

import pytest

from data import ROUTINES
from exercise_images import EXERCISE_IMAGE, image_for, image_frames
from exercises import exercise_key

# A composite entry ("SS: Squat + Lying Leg Curl") is one line in the routine
# but two movements, so no single photo is right. Those render blank on purpose.
COMPUESTO = ("+", "SS:", "Bi-set", "Triset")


def es_compuesto(nombre: str) -> bool:
    return any(t in nombre for t in COMPUESTO)


def claves_de_rutina() -> set[str]:
    return {
        exercise_key(ejercicio)
        for rutina in ROUTINES
        for dias in rutina.days_by_phase.values()
        for dia in dias
        for ejercicio in dia.exercises
    }


def test_nunca_devuelve_una_url_file():
    """The bug that made every image invisible in web mode."""
    for clave in EXERCISE_IMAGE:
        for valor in (image_for(clave), *(image_frames(clave) or ())):
            if valor is not None:
                assert not valor.startswith("file://"), (
                    f"{clave} devuelve {valor!r}: el navegador lo rechaza con "
                    "'Not allowed to load local resource'"
                )


def test_las_rutas_son_relativas_a_assets():
    """Flet serves `assets/` at the site root, so paths start at /exercises/."""
    patron = re.compile(r"^/exercises/[^/]+/\d+\.jpg$")
    for clave in EXERCISE_IMAGE:
        ruta = image_for(clave)
        if ruta is not None:
            assert patron.match(ruta), f"{clave} -> {ruta!r}"


def test_image_frames_devuelve_dos_o_nada():
    for clave in EXERCISE_IMAGE:
        frames = image_frames(clave)
        if frames is not None:
            assert len(frames) == 2, f"{clave} -> {frames!r}"


def test_un_ejercicio_sin_mapeo_no_revienta():
    assert image_for("Exercise That Does Not Exist") is None
    assert image_frames("Exercise That Does Not Exist") is None
    assert image_for("") is None


def test_los_ejercicios_simples_de_las_rutinas_estan_mapeados():
    """Anything that is one movement should have a photo mapped.

    Bulgarian Split Squat is the single exception: it does not exist in the
    500-exercise source, and mapping it to a different movement would show a
    confidently wrong photo, which is worse than none.
    """
    SIN_ORIGEN = {"Bulgarian Split Squat"}
    faltan = {
        clave
        for clave in claves_de_rutina()
        if not es_compuesto(clave) and clave not in EXERCISE_IMAGE and clave not in SIN_ORIGEN
    }
    assert not faltan, f"ejercicios simples sin imagen mapeada: {sorted(faltan)}"


@pytest.mark.parametrize(
    ("nombre", "slug"),
    [
        # A lat pulldown used to point at a bent-over row: the photo showed a
        # different exercise entirely. Pinned so it cannot drift back.
        ("Behind-Neck Lat Pulldown", "Full_Range-Of-Motion_Lat_Pulldown"),
        ("Front Lat Pulldown", "Wide-Grip_Lat_Pulldown"),
        ("Hip Thrust", "Barbell_Hip_Thrust"),
    ],
)
def test_mapeos_que_ya_estuvieron_mal(nombre, slug):
    assert EXERCISE_IMAGE.get(nombre) == slug
