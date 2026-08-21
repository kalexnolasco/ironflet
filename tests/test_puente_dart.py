"""El lado Dart del puente de notificaciones, leído como texto.

No hay tests de Dart en este repo y no los va a haber: montar el toolchain de
Flutter en CI para tres funciones cuesta más de lo que protege. Pero `main.dart`
tiene una propiedad estructural de la que depende toda la entrega de avisos, y
esa sí se puede comprobar leyendo el fichero.

**El `Timer.periodic` no puede compartir `try` con el `initialize`.**

Es lo que rompió los avisos durante una versión entera. El icono de las
notificaciones se cambió a un drawable monocromo, el recurso llegó al proyecto
Android generado pero no al APK, Gradle no dijo nada, y `initialize` lanzó una
`Resources$NotFoundException`. Como el temporizador estaba dentro del mismo
`try`, nunca llegó a registrarse: sin poll no se lee `notifications.json`, sin
lectura no se programa nada, y en pantalla se veía el aviso recién creado en
su lista tan tranquilo. Ningún error, ninguna traza — `debugPrint` no llega a
logcat en release, y Flet no pinta los errores de Dart.

Un icono es cosmética. El aviso es la función. Este fichero es lo que impide
que vuelvan a estar atados.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MAIN_DART = RAIZ / "build_template" / "{{cookiecutter.out_dir}}" / "lib" / "main.dart"


@pytest.fixture(scope="module")
def fuente() -> str:
    if not MAIN_DART.exists():
        pytest.skip(f"sin plantilla forkeada en {MAIN_DART}")
    return MAIN_DART.read_text(encoding="utf-8")


def _bloque_del_try(fuente: str, desde: int) -> str:
    """El texto del `try { ... }` que empieza en `desde`, contando llaves."""
    inicio = fuente.index("{", desde)
    nivel, i = 0, inicio
    while i < len(fuente):
        if fuente[i] == "{":
            nivel += 1
        elif fuente[i] == "}":
            nivel -= 1
            if nivel == 0:
                return fuente[inicio : i + 1]
        i += 1
    raise AssertionError("try sin cerrar en main.dart")


def test_el_temporizador_no_vive_dentro_del_try_del_initialize(fuente):
    """La propiedad que se rompió, dicha en una frase.

    Se comprueba sobre CADA `try` del fichero: ninguno puede contener a la vez
    la inicialización del plugin y el registro del temporizador, porque un
    fallo de la primera se lleva al segundo.
    """
    culpables = []
    for m in re.finditer(r"\btry\b", fuente):
        bloque = _bloque_del_try(fuente, m.end())
        inicializa = "_notifPlugin.initialize(" in bloque
        programa = "Timer.periodic(" in bloque and "_syncNotifications" in bloque
        if inicializa and programa:
            culpables.append(bloque[:160].replace("\n", " "))
    assert not culpables, (
        "el `Timer.periodic` de los avisos comparte `try` con "
        "`_notifPlugin.initialize`: si el icono no resuelve, el temporizador no "
        "se registra y NINGÚN aviso se entrega, en silencio.\n" + "\n".join(culpables)
    )


def test_el_temporizador_se_registra_siempre(fuente):
    """Y está, no es que se haya ido con el acoplamiento."""
    assert "Timer.periodic(" in fuente
    assert "_syncNotifications" in fuente


def test_el_icono_tiene_alternativa(fuente):
    """El drawable propio se intenta; el del lanzador es la red debajo.

    Sin alternativa, un recurso que no resuelve deja al plugin sin inicializar
    y las notificaciones no se pintan aunque el temporizador sí corra.
    """
    assert "@drawable/ic_stat_ironflet" in fuente, "el icono monocromo es el que debe salir"
    assert "@mipmap/ic_launcher" in fuente, (
        "hace falta el icono del lanzador como alternativa: es el que había y "
        "funciona, aunque salga como una silueta sin forma"
    )


def test_el_drawable_del_icono_existe_y_es_monocromo():
    """Android se queda solo con el canal alfa de un icono de notificación.

    Un icono a color se pinta como una mancha — que es de lo que se venía: el
    adaptativo de la app salía como un círculo hueco en cada aviso.
    """
    icono = (
        RAIZ
        / "build_template"
        / "{{cookiecutter.out_dir}}"
        / "android"
        / "app"
        / "src"
        / "main"
        / "res"
        / "drawable"
        / "ic_stat_ironflet.xml"
    )
    if not icono.exists():
        pytest.skip("sin plantilla forkeada")

    texto = icono.read_text(encoding="utf-8")
    assert "<vector" in texto, "tiene que ser un VectorDrawable, no un bitmap"

    colores = set(re.findall(r'android:fillColor="(#[0-9A-Fa-f]{6,8})"', texto))
    assert colores, "sin fillColor no se dibuja nada"
    assert colores <= {"#FFFFFFFF", "#FFFFFF"}, (
        f"un icono de notificación se recorta a su silueta; estos colores no "
        f"aportan nada y engañan a quien lo edite: {sorted(colores)}"
    )
