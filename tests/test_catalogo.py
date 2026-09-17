"""catalogo.py — los 875 ejercicios de la Free Exercise DB.

El test que de verdad importa aquí es uno: que traer un catálogo grande **no
pueda partir un historial**. El nombre con el que se guarda una serie es la
clave de todo (`exercise_key`, trampa 2), y la base llama al press de banca
`Barbell Bench Press - Medium Grip` mientras la app lo llama `Barbell Bench
Press`. Ofrecer los dos, o el de la base en vez del de casa, abriría una
segunda historia del mismo movimiento sin que nada fallara.
"""

from __future__ import annotations

from collections import Counter

import pytest

import catalogo
from data import EXERCISE_CATALOG, ROUTINES
from exercises import exercise_key


@pytest.fixture(autouse=True)
def _cache_limpia():
    catalogo.reset_cache()
    yield
    catalogo.reset_cache()


def _nombres_de_la_app() -> set[str]:
    de_catalogo = {n for grupo in EXERCISE_CATALOG.values() for n in grupo}
    de_rutinas = {
        exercise_key(e)
        for r in ROUTINES
        for dias in r.days_by_phase.values()
        for d in dias
        for e in d.exercises
    }
    return de_catalogo | de_rutinas


# ── el fichero llega y se lee ────────────────────────────────────────────


def test_el_catalogo_viaja_con_la_app():
    """Si no, el buscador queda con los 67 de siempre y nadie se entera."""
    assert len(catalogo.todos()) > 800


def test_cada_ejercicio_trae_lo_que_hace_falta_para_pintarlo():
    for e in catalogo.todos():
        assert e.nombre and e.slug
        assert e.grupo, f"{e.nombre} sin grupo"
        assert e.descripcion(), f"{e.nombre} sin descripción"


def test_un_fichero_que_falta_deja_la_app_entera(monkeypatch, tmp_path):
    """Degradar a los 67 de casa es correcto; una excepción aquí es pantalla
    en blanco justo cuando alguien busca un ejercicio a mitad de sesión."""
    monkeypatch.setattr(catalogo, "_ruta", lambda: tmp_path / "no-existe.json")
    catalogo.reset_cache()
    assert catalogo.todos() == ()
    assert catalogo.buscar("curl") == ()
    assert catalogo.grupos() == ()


def test_un_fichero_corrupto_tampoco_tumba_nada(monkeypatch, tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text("esto no es json")
    monkeypatch.setattr(catalogo, "_ruta", lambda: malo)
    catalogo.reset_cache()
    assert catalogo.todos() == ()


# ── LA regla: no partir historiales ──────────────────────────────────────


def test_manda_el_nombre_de_la_app_no_el_de_la_base():
    """El press de banca es «Barbell Bench Press», no el nombre largo.

    Este es el test que justifica el módulo entero. `EXERCISE_IMAGE` mapea
    nombre de casa → slug, y se lee al revés para traducir.
    """
    from exercise_images import EXERCISE_IMAGE

    slug = EXERCISE_IMAGE["Barbell Bench Press"]
    e = next(x for x in catalogo.todos() if x.slug == slug)
    assert e.nombre == "Barbell Bench Press"
    assert e.de_la_casa is True


def test_ningun_nombre_del_catalogo_duplica_uno_de_casa():
    """Ni un solo movimiento puede ofrecerse con dos nombres distintos.

    Se comprueba por slug: si dos entradas distintas del catálogo apuntan al
    mismo slug, una de ellas está ofreciendo el mismo ejercicio bajo otro
    nombre — y quien lo elija abrirá un historial paralelo.
    """
    por_slug = Counter(e.slug for e in catalogo.todos())
    repetidos = [s for s, c in por_slug.items() if c > 1]
    assert repetidos == [], f"un mismo movimiento con dos nombres: {repetidos}"


def test_ningun_nombre_aparece_dos_veces():
    """Dos filas idénticas en el buscador. Pasó: la app llama «Alternate
    Hammer Curl» al slug `Hammer_Curls` y la base traía además un
    `Alternate_Hammer_Curl` con ese mismo nombre."""
    repes = [n for n, c in Counter(e.nombre for e in catalogo.todos()).items() if c > 1]
    assert repes == []


def test_los_de_casa_llevan_el_nombre_que_dice_exercise_image():
    """«De casa» significa exactamente eso: que `EXERCISE_IMAGE` le puso nombre.

    No todos son nombres que alguna rutina prescriba hoy. Cinco son **las
    mitades de los bi-sets** —«Bi-set: Barbell + DB Skull Crushers» tiene la
    foto de cada mitad mapeada— y ofrecerlos sueltos es justo lo que hace falta
    el día que el bi-set no encaja. Lo que no puede pasar es que uno de ellos
    salga con el nombre largo de la base.
    """
    from exercise_images import EXERCISE_IMAGE

    de_casa = [e for e in catalogo.todos() if e.de_la_casa]
    assert len(de_casa) > 50
    nombres_de_imagen = {n.lower() for n in EXERCISE_IMAGE}
    for e in de_casa:
        assert e.nombre.lower() in nombres_de_imagen, (
            f"{e.nombre} se dice de casa y no sale de EXERCISE_IMAGE"
        )


def test_casi_todos_los_de_casa_son_nombres_que_alguna_rutina_usa():
    """El resto son las mitades de los bi-sets, y son cinco contadas.

    Son cuatro y no cinco porque `Incline Flyes` comparte slug con `Incline DB
    Flyes`, que sí se prescribe, y en ese empate gana el vivo — a propósito, no
    por orden alfabético: es el nombre bajo el que ya hay series guardadas.

    El número está fijado a propósito: si crece, alguien añadió un nombre a
    `EXERCISE_IMAGE` que ninguna rutina prescribe, y eso o es una mitad nueva o
    es un nombre que se quedó atrás al retirar una rutina.
    """
    conocidos = {n.lower() for n in _nombres_de_la_app()}
    sueltos = [
        e.nombre for e in catalogo.todos() if e.de_la_casa and e.nombre.lower() not in conocidos
    ]
    assert len(sueltos) == 4, f"esperaba 4 mitades de bi-set, hay {len(sueltos)}: {sueltos}"


def test_en_un_empate_de_slug_gana_el_nombre_que_se_prescribe():
    """`Incline DB Flyes` y `Incline Flyes` apuntan al mismo slug de la base.

    Solo uno puede ganar —ofrecer los dos sería el mismo movimiento con dos
    historiales— y tiene que ser aquel bajo el que Alex ya tiene series.
    """
    from exercise_images import EXERCISE_IMAGE

    slug = EXERCISE_IMAGE["Incline Flyes"]
    assert EXERCISE_IMAGE["Incline DB Flyes"] == slug, "el empate que este test vigila ya no existe"
    ofrecido = next(e for e in catalogo.todos() if e.slug == slug)
    assert ofrecido.nombre == "Incline DB Flyes"


def test_todo_nombre_que_ofrece_es_guardable():
    """Si el buscador lo enseña, `extras.es_valido` tiene que aceptarlo.

    Los dos leen el mismo catálogo, así que esto pinta el contrato entre ellos:
    un ejercicio ofrecido y luego rechazado al tocarlo es un botón muerto.
    """
    import extras

    validos = {n.lower() for n in extras.nombres_conocidos()}
    for e in catalogo.buscar("", limite=900):
        assert e.nombre.lower() in validos, f"{e.nombre} se ofrece y no se puede guardar"


# ── la búsqueda, que es lo que hace usable a 875 ─────────────────────────


def test_lo_que_empieza_por_la_consulta_va_primero():
    """Escribir «curl» tiene que ofrecer `Curl` antes que `Alternate Hammer
    Curl`, o el que buscabas queda el decimoséptimo de una lista de 40."""
    r = [e.nombre.lower() for e in catalogo.buscar("bench")]
    empiezan = [i for i, n in enumerate(r) if n.startswith("bench")]
    contienen = [i for i, n in enumerate(r) if not n.startswith("bench")]
    assert not empiezan or not contienen or max(empiezan) < min(contienen)


def test_los_de_casa_suben_dentro_de_su_tramo():
    r = catalogo.buscar("curl", limite=8)
    assert r[0].de_la_casa, "un ejercicio que Alex ya usa debería salir antes"


def test_la_busqueda_ignora_mayusculas_y_tildes():
    assert catalogo.buscar("BENCH") == catalogo.buscar("bench")
    # El catálogo es inglés, pero la normalización tiene que estar puesta para
    # el día que alguien busque «tríceps» en un nombre con tilde.
    assert catalogo._sin_tildes("Tríceps") == "triceps"


def test_una_busqueda_sin_resultados_devuelve_vacio_y_no_revienta():
    assert catalogo.buscar("qwertyuiop") == ()


def test_el_filtro_por_grupo_acota():
    pecho = catalogo.buscar("", grupo="Chest", limite=900)
    assert pecho and all(e.grupo == "Chest" for e in pecho)


def test_el_limite_se_respeta():
    assert len(catalogo.buscar("", limite=7)) == 7


def test_los_grupos_van_en_el_orden_de_la_app():
    from data import MUSCLE_GROUPS

    g = list(catalogo.grupos())
    conocidos = [x for x in g if x in MUSCLE_GROUPS]
    assert conocidos == [x for x in MUSCLE_GROUPS if x in conocidos]


# ── la foto ──────────────────────────────────────────────────────────────


def test_el_slug_sale_de_la_tabla_de_casa_cuando_existe():
    from exercise_images import EXERCISE_IMAGE

    assert catalogo.slug_de("Barbell Bench Press") == EXERCISE_IMAGE["Barbell Bench Press"]


def test_un_ejercicio_solo_del_catalogo_grande_tambien_tiene_slug():
    e = next(x for x in catalogo.todos() if not x.de_la_casa)
    assert catalogo.slug_de(e.nombre) == e.slug


def test_un_nombre_desconocido_no_inventa_slug():
    assert catalogo.slug_de("Prensa Marciana") == ""


# ── que el fichero llegue al APK ─────────────────────────────────────────


def test_el_json_esta_donde_el_modulo_lo_busca():
    """Un fichero de datos que no viaja es la trampa 10 otra vez.

    Las fotos de ejercicios no se veían en el móvil porque el APK no resuelve
    una URL de `assets/`. Esto no es lo mismo — se abre con `open()`, y
    `app.zip` se extrae entero — pero el modo de fallo sí: el catálogo se
    quedaría vacío y el buscador ofrecería los 67 de siempre sin decir nada.
    """
    assert catalogo._ruta().exists(), f"falta {catalogo._ruta()}"
    assert catalogo._ruta().stat().st_size > 100_000


def test_el_json_no_cae_en_la_exclusion_de_assets():
    """`pyproject.toml` excluye `assets/exercises` del APK a propósito (esas
    9 MB se bajan en marcha). Este fichero es hermano de esa carpeta, no hijo,
    y una exclusión escrita como `assets` a secas se lo llevaría por delante.
    """
    from pathlib import Path

    import tomllib

    cfg = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    excluidos = cfg["tool"]["flet"]["app"]["exclude"]
    ruta = "assets/" + catalogo.FICHERO
    for patron in excluidos:
        assert not ruta.startswith(patron.rstrip("/") + "/"), f"«{patron}» excluye el catálogo"
        assert patron != "assets", "excluir `assets` entero deja la app sin catálogo"


# ── la foto de un ejercicio añadido a mano ───────────────────────────────


def test_image_props_resuelve_el_slug_del_catalogo_grande(monkeypatch, tmp_path):
    """`EXERCISE_IMAGE` tiene 87 nombres y el catálogo 875: sin este respaldo,
    todo lo que Alex añada a mitad de sesión sale sin foto para siempre."""
    import asset_manager
    import exercise_images

    e = next(x for x in catalogo.todos() if not x.de_la_casa)
    assert e.nombre not in exercise_images.EXERCISE_IMAGE
    assert exercise_images._slug_de(e.nombre) == e.slug

    # Y con la foto en disco, `image_props` la devuelve de verdad.
    carpeta = tmp_path / e.slug
    carpeta.mkdir(parents=True)
    (carpeta / "0.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 64)
    monkeypatch.setattr(asset_manager, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(exercise_images, "url_is_served", lambda: True)
    assert exercise_images.image_props(e.nombre)


def test_un_nombre_que_nadie_conoce_no_pinta_nada():
    from exercise_images import image_props

    assert image_props("Prensa Marciana") == {}


async def test_descargar_uno_no_pide_lo_que_ya_esta(monkeypatch, tmp_path):
    """Añadir un ejercicio del catálogo de casa no debe gastar una petición."""
    import asset_manager

    carpeta = tmp_path / "Ab_Crunch_Machine"
    carpeta.mkdir(parents=True)
    (carpeta / "0.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 64)
    monkeypatch.setattr(asset_manager, "_data_dir", lambda: tmp_path)

    def _no(*_a, **_k):
        raise AssertionError("pidió una foto que ya estaba en disco")

    monkeypatch.setattr(asset_manager.httpx, "AsyncClient", _no)
    assert await asset_manager.descargar_uno("Ab_Crunch_Machine") is True


async def test_descargar_uno_sin_red_no_revienta(monkeypatch, tmp_path):
    """Se llama en mitad de un entreno: una foto que no llega no puede tumbar
    la pantalla ni dejar una excepción suelta en el bucle de eventos."""
    import asset_manager

    monkeypatch.setattr(asset_manager, "_data_dir", lambda: tmp_path)

    def _revienta(*_a, **_k):
        raise OSError("sin red")

    monkeypatch.setattr(asset_manager.httpx, "AsyncClient", _revienta)
    assert await asset_manager.descargar_uno("Lo_Que_Sea") is False


async def test_descargar_uno_ignora_un_slug_vacio(tmp_path, monkeypatch):
    import asset_manager

    monkeypatch.setattr(asset_manager, "_data_dir", lambda: tmp_path)
    assert await asset_manager.descargar_uno("") is True
