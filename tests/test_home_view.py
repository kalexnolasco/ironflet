"""Home: the numbers say their unit, and a dead database says so.

Home is the first screen the app opens on. When its reads raised, the app came
up on nothing at all — and with Profile and Plan only reachable *from* Home,
there was no way to get anywhere to find out why.

`current_program_week`, `day_totals` and `targets_for` are patched at their
import site in `views.home`: this file is about what Home renders, not about
re-testing `program_week.py`.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import flet as ft
import pytest

from program_week import ProgramStart, ProgramWeek, StartSource, WeekStatus
from theme import LIGHT, set_palette

VIEW_PROFILE = 5


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


class FakeStore:
    def __init__(self, stats=None, streak=2, today=(), fail=None):
        self.stats = stats or {"sessions": 3, "sets": 42, "volume": 12345.0}
        self.streak = streak
        self.today = list(today)
        self.fail = fail

    def _check(self):
        if self.fail is not None:
            raise self.fail

    def get_streak(self):
        self._check()
        return self.streak

    def get_week_stats(self):
        self._check()
        return dict(self.stats)

    def get_today(self):
        self._check()
        return list(self.today)


def unknown_week() -> ProgramWeek:
    """The fresh-install state: no start date, so no week to name."""
    return ProgramWeek(
        status=WeekStatus.UNKNOWN,
        start=ProgramStart(day=None, source=StartSource.UNKNOWN),
        routine_id="recomp-ppl-ul",
        total_weeks=6,
        today=date.today(),
    )


@pytest.fixture
def home(monkeypatch):
    """A HomeView whose three outside modules are stubbed, plus its store."""
    import views.home as home_module

    monkeypatch.setattr(home_module, "current_program_week", lambda store: unknown_week())
    monkeypatch.setattr(home_module, "day_totals", lambda store, day: {})
    monkeypatch.setattr(home_module, "targets_for", lambda store, day: {})

    def build(store):
        page = MagicMock()
        page.width = 400
        page.height = 800
        page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
        view = home_module.HomeView(page, store)
        view.on_show()
        return view

    return build


def texts(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, ft.Text) and isinstance(node.value, str):
            found.append(node.value)
        for attr in ("content", "controls", "actions", "title", "spans"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


def tooltips(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        tip = getattr(node, "tooltip", None)
        if isinstance(tip, str) and tip:
            found.append(tip)
        for attr in ("content", "controls", "actions", "title"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


# ── the shortened volume ────────────────────────────────────────────────


def test_volume_tile_carries_the_real_figure(home):
    """`12.3k` under a "Vol (kg)" caption still does not say 12,300 kilos."""
    view = home(FakeStore(stats={"sessions": 3, "sets": 42, "volume": 12345.0}))
    tree = view.build()
    assert "12.3k" in texts(tree)
    assert any("12,345 kg" in t for t in tooltips(tree)), (
        "the shortened number must say what it really is somewhere"
    )


def test_volume_tooltip_names_the_window_and_the_arithmetic(home):
    view = home(FakeStore())
    tips = " | ".join(tooltips(view.build()))
    assert "Peso × reps" in tips
    assert "últimos 7 días" in tips.lower()


# ── the database is down ────────────────────────────────────────────────


class _DriverError(Exception):
    pass


_DriverError.__module__ = "sqlalchemy.exc"


def test_a_dead_database_does_not_open_the_app_on_nothing(home):
    view = home(FakeStore(fail=_DriverError("could not connect to server")))
    rendered = " | ".join(texts(view.build()))
    assert "No se llega a la base de datos" in rendered
    assert "could not connect to server" in rendered


# ── la tarjeta de comida lee las claves que nutrition escribe ───────────


DIA_CON_COMIDA = date(2026, 8, 21)


@pytest.fixture
def totales_y_objetivos_reales(tmp_path):
    """Un día con comida de verdad, por el mismo camino que la app.

    Deliberadamente NO se escriben aquí las claves a mano: los diccionarios
    salen de `nutrition.day_totals`/`targets_for`, así que el test compara la
    vista contra el módulo y no contra lo que yo creía recordar del módulo.

    Base propia en `tmp_path` en vez de la compartida del proceso: `Nutrition`
    siembra el catálogo al construirse, y hacerlo sobre una base que otro test
    acaba de vaciar deja la sesión sembrando dentro de una transacción ajena.
    """
    import nutrition as nutrition_module
    from storage import Base, create_db_engine

    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path}/comida.db")
    Base.metadata.create_all(engine)

    nut = nutrition_module.Nutrition(engine=engine)
    nut.set_targets(2550.0, 115.0, 70.0, 365.0, starts_on=DIA_CON_COMIDA)
    comida = nut.add_food("pechuga-pollo", "Pechuga de pollo (cruda)", 120.0, 23.0, 2.6, 0.0)
    nut.log_food(comida, grams=150.0, meal="lunch", day=DIA_CON_COMIDA)

    # Los facades aceptan un `Nutrition` y lo devuelven tal cual; con un
    # MagicMock en su lugar `_nutrition_for` no lo reconoce y monta una
    # instancia nueva contra DATABASE_URL, que no es esta base.
    yield (
        nutrition_module.day_totals(nut, DIA_CON_COMIDA),
        nutrition_module.targets_for(nut, DIA_CON_COMIDA),
    )
    engine.dispose()


def test_la_tarjeta_de_comida_pinta_la_proteina_que_nutrition_devuelve(
    home, monkeypatch, totales_y_objetivos_reales
):
    """42 g registrados no pueden salir como «0 g» en Inicio.

    Salían. La traducción al español renombró la CLAVE del diccionario
    (`totals.get("proteína")`), y como `.get()` de una clave que no existe
    devuelve None en vez de reventar, la tarjeta pintaba un cero perfectamente
    creíble con la comida ya apuntada. Es la trampa 22 en su forma más
    silenciosa: `nutrition` habla en inglés porque es contrato de datos.
    """
    import views.home as home_module

    totales, objetivos = totales_y_objetivos_reales
    assert totales["protein"] > 0, "el montaje del test no registró comida"

    monkeypatch.setattr(home_module, "day_totals", lambda store, day: totales)
    monkeypatch.setattr(home_module, "targets_for", lambda store, day: objetivos)

    view = home(FakeStore())
    pintado = " | ".join(texts(view.build()))

    esperado = f"{totales['protein']:.0f}"
    assert f"{esperado} / 115 g" in pintado or f"{esperado}/115 g" in pintado, (
        f"la proteína registrada ({esperado} g) no aparece en la tarjeta: {pintado}"
    )
    assert "0 / 115 g" not in pintado and "0/115 g" not in pintado


def test_las_claves_que_home_lee_existen_en_nutrition(monkeypatch, totales_y_objetivos_reales):
    """Ancla el contrato: toda clave que la tarjeta pide, `nutrition` la da.

    El test de arriba prueba el caso que se rompió; este prueba la clase
    entera, para que el próximo renombre no necesite que alguien mire la
    pantalla para enterarse.
    """
    import views.home as home_module

    totales, objetivos = totales_y_objetivos_reales
    pedidas_totales: set[str] = set()
    pedidas_objetivos: set[str] = set()

    class Espia(dict):
        def __init__(self, real, registro):
            super().__init__(real)
            self._registro = registro

        def get(self, clave, *resto):
            self._registro.add(clave)
            return super().get(clave, *resto)

    monkeypatch.setattr(
        home_module, "day_totals", lambda store, day: Espia(totales, pedidas_totales)
    )
    monkeypatch.setattr(
        home_module, "targets_for", lambda store, day: Espia(objetivos, pedidas_objetivos)
    )
    monkeypatch.setattr(home_module, "current_program_week", lambda store: unknown_week())

    page = MagicMock()
    page.width = 400
    page.height = 800
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    view = home_module.HomeView(page, FakeStore())
    view.on_show()
    view.build()

    huerfanas = (pedidas_totales - set(totales)) | (pedidas_objetivos - set(objetivos))
    assert not huerfanas, (
        f"Inicio pide claves que nutrition no devuelve: {sorted(huerfanas)}. "
        "Son contrato de datos, no texto de pantalla — no se traducen."
    )


def test_on_show_does_not_raise_when_the_week_cannot_be_read(monkeypatch):
    """`on_show` runs inside `navigate_to`, before `build()`.

    An exception there takes the whole navigation down rather than one screen,
    so Home would refuse to open at all rather than open with a message.
    """
    import views.home as home_module

    def explode(store):
        raise _DriverError("server closed the connection")

    monkeypatch.setattr(home_module, "current_program_week", explode)
    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    view = home_module.HomeView(page, FakeStore())
    view.on_show()  # must not raise
    assert view._week is None


# ── las etiquetas concuerdan con su número ──────────────────────────────


@pytest.mark.parametrize(
    ("sesiones", "series", "esperadas"),
    [
        (1, 1, ("Sesión", "Serie")),
        (0, 0, ("Sesiones", "Series")),
        (3, 42, ("Sesiones", "Series")),
    ],
)
def test_las_etiquetas_concuerdan_con_su_numero(home, sesiones, series, esperadas):
    """«1 Sesiones» con el 1 justo encima se lee de golpe.

    Eran dos literales fijos, así que la primera semana de cualquiera —y la
    de Alex, que es cuando se vio— salía mal. El cero SÍ es plural.
    """
    view = home(FakeStore(stats={"sessions": sesiones, "sets": series, "volume": 100.0}))
    pintado = texts(view.build())
    for palabra in esperadas:
        assert palabra in pintado, f"con {sesiones}/{series} esperaba «{palabra}»: {pintado}"


def test_una_sola_sesion_no_dice_sesiones(home):
    """El caso concreto que se vio en pantalla."""
    view = home(FakeStore(stats={"sessions": 1, "sets": 5, "volume": 2000.0}))
    pintado = texts(view.build())
    assert "Sesión" in pintado
    assert "Sesiones" not in pintado


# ── el diálogo de avisos nombra el interruptor que falla ────────────────


def _dialogo_avisos(monkeypatch, tmp_path, estado):
    """Abre el diálogo de avisos con un estado del sistema dado.

    Devuelve el texto que pinta. El diálogo se construye con `page.open`, así
    que se captura ahí en vez de por un valor de retorno.
    """
    import notificaciones
    import views.home as home_module

    monkeypatch.setattr(home_module, "current_program_week", lambda store: unknown_week())
    monkeypatch.setattr(home_module, "day_totals", lambda store, day: {})
    monkeypatch.setattr(home_module, "targets_for", lambda store, day: {})
    monkeypatch.setattr(notificaciones, "estado_android", lambda *a, **k: estado)

    abiertos = []
    page = MagicMock()
    page.width = 400
    page.height = 800
    page.open = abiertos.append
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}

    store = FakeStore()
    store.get_all_reminders = lambda: []
    store.bot_delivers_reminders = lambda: False
    store.get_reminders_today = lambda *a, **k: []
    view = home_module.HomeView(page, store)
    view._open_reminders()
    assert abiertos, "el diálogo tiene que abrirse"
    return " | ".join(texts(abiertos[0])), abiertos[0]


def test_avisa_de_la_optimizacion_de_bateria(monkeypatch, tmp_path):
    """El interruptor que ningún emulador reproduce y que apaga los avisos.

    El permiso concedido y la alarma exacta: los dos en verde, y aun así el
    sistema cancela las alarmas. Si la pantalla se calla aquí, no queda dónde
    enterarse.
    """
    pintado, _ = _dialogo_avisos(
        monkeypatch,
        tmp_path,
        {"granted": True, "exact": True, "battery_optimised": True},
    )
    assert "batería" in pintado, f"no menciona la batería: {pintado}"
    assert "Quitar la optimización" in pintado, "y hay que llevar al ajuste, no solo avisar"


def test_sin_optimizacion_no_dice_nada_de_bateria(monkeypatch, tmp_path):
    """Un aviso que sale siempre deja de leerse."""
    pintado, _ = _dialogo_avisos(
        monkeypatch,
        tmp_path,
        {"granted": True, "exact": True, "battery_optimised": False},
    )
    assert "batería" not in pintado


def test_el_boton_de_probar_esta_siempre(monkeypatch, tmp_path):
    """Es lo que convierte «no me suena» en un dato, así que no depende de nada."""
    pintado, _ = _dialogo_avisos(
        monkeypatch,
        tmp_path,
        {"granted": True, "exact": True, "battery_optimised": False},
    )
    assert "Probar un aviso ahora" in pintado


def test_sin_lado_android_el_dialogo_no_alarma(monkeypatch, tmp_path):
    """En el escritorio no hay interruptores del sistema de los que hablar."""
    pintado, _ = _dialogo_avisos(monkeypatch, tmp_path, None)
    assert "batería" not in pintado
    assert "APAGADAS" not in pintado


def _tarjeta_foto(monkeypatch, cuantas: int) -> str:
    """La tarjeta FOTO de Inicio con N fotos guardadas y ninguna de hoy."""
    import fotos as fotos_module
    import views.home as home_module

    monkeypatch.setattr(fotos_module, "para_fecha", lambda *a, **k: None)
    page = MagicMock()
    page.width = 400
    page.height = 800
    page.data = {
        "refresh_current": lambda: None,
        "navigate_to": lambda i, **k: None,
        "photos_view": None,
    }
    store = FakeStore()
    store.get_photos = lambda: [
        {"date": f"2026-08-{10 + i:02d}", "file": f"{i}.jpg"} for i in range(cuantas)
    ]
    return " | ".join(texts(home_module.HomeView(page, store)._photo_tile()))


def test_una_sola_foto_no_esta_guardadas(monkeypatch):
    """«1 foto guardadas»: `plural()` acertaba y el participio de al lado no.

    La concordancia no acaba en el sustantivo — cualquier palabra que vaya con
    el número tiene que seguirle, y un literal fijo al lado de un `plural()`
    deshace lo que este hace en la misma frase.
    """
    pintado = _tarjeta_foto(monkeypatch, 1)
    assert "1 foto guardada" in pintado
    assert "guardadas" not in pintado


def test_varias_fotos_si_estan_guardadas(monkeypatch):
    assert "2 fotos guardadas" in _tarjeta_foto(monkeypatch, 2)
