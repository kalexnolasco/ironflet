"""Home: what today is, the week in three numbers, and the doors out.

The first card is the one that earns the screen: which session today is. It is
the question the app gets opened with, and until now the answer lived two taps
into Plan, in a tab you had to know existed. The arithmetic is
`program_week.py`'s and the copy is shared with Plan through
`views.plan.open_start_date_dialog` — imported rather than reimplemented, for
the same reason `bar_flex` is imported from the food screen: two versions of the
control that decides which week Alex is in would drift, and this one decides
which gym session he does.

That card says "no lo sé" out loud when nothing records when the routine
started, which is the state of a fresh install. It is not softened into a guess:
a confident wrong session is a wasted training day, an admitted unknown is one
tap from being fixed. `current_program_week()` runs a query, so it is taken in
`on_show()` and held, exactly as that module asks.

Home is also the only way into two screens that have no slot in the bottom bar:
the exercise catalogue (Browse) and — by tapping the nutrition card — the food
diary. A screen nobody can navigate to may as well not have been written.

The numbers here are deliberately literal. The streak counts *weeks*, not days,
and "Sesiones" counts *days trained*, not table rows; both labels used to claim
something the value did not mean. See `analytics.training_streak` for why the
weekly definition is the honest one, and `storage.weekly_session_minimum` for
where the weekly bar comes from — routines here train 3 to 6 days a week, so
the bar is read off the active routine rather than fixed.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import flet as ft

import nombres_es
from analytics import MEASUREMENT_EVERY_DAYS, MIN_TREND_DAYS, waist_summary, weight_trend
from dates import day_name, month_name
from exercises import phase_color
from nutrition import day_totals, targets_for
from program_week import (
    ProgramWeek,
    StartSource,
    WeekStatus,
    current_program_week,
    is_rest_label,
    training_day_for_label,
)
from storage import Storage
from theme import (
    C,
    Radius,
    Space,
    card,
    chip,
    ghost_button,
    muted_text,
    primary_button,
    section_title,
)
from views.plan import next_session, open_start_date_dialog, start_caveat, week_headline
from views.shared_ui import db_error_screen, dialog_height, dialog_width, plural

# main.py owns the routing table; naming the indices here keeps the calls
# readable and makes it obvious what breaks if that table is reordered.
VIEW_PLAN = 1
VIEW_WORKOUT = 2
VIEW_BROWSE = 3
VIEW_PROFILE = 5
VIEW_NUTRITION = 6
#: The in-app coach. Appended after Backup (8) — indices are frozen, so a new
#: screen goes on the end and never in the middle. See trap #1 in CLAUDE.md.
VIEW_COACH = 9
VIEW_PHOTOS = 10

# Trailing window behind get_week_stats(); shown so the three numbers below it
# are not read as "all time".
STATS_WINDOW_LABEL = "Últimos 7 días"


def today_display() -> str:
    d = date.today()
    return f"{day_name(d.weekday())}, {d.day} {month_name(d.month - 1)}"


def _n(value) -> str:
    """Whole numbers only — a summary card has no room for tenths of a gram."""
    return f"{round(float(value or 0)):.0f}"


def _macro_bar(current: float, target: float, color: str, over_color: str) -> ft.Control:
    """Progress towards a daily target, using the food screen's own geometry.

    `bar_flex` is imported rather than reimplemented so this bar and the ones on
    the Food screen stay the same bar; two implementations would drift the first
    time one of them was tuned.
    """
    from views.nutrition_view import bar_flex

    eaten, rest, over = bar_flex(current, target)
    segments: list[ft.Control] = []
    if eaten:
        segments.append(ft.Container(bgcolor=color, expand=eaten))
    if rest:
        segments.append(ft.Container(bgcolor=C.bg_sunken, expand=rest))
    if over:
        segments.append(ft.Container(bgcolor=over_color, expand=over))
    return ft.Container(
        content=ft.Row(segments, spacing=0),
        height=6,
        bgcolor=C.bg_sunken,
        border_radius=Radius.pill,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


class HomeView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self._week: ProgramWeek | None = None

    def on_show(self):
        # One query per activation, held for `build()` — `program_week` asks for
        # this explicitly, and every refresh path in main.py comes through
        # `navigate_to`, which calls `on_show()` before rebuilding.
        #
        # Caught, not raised: `on_show()` runs *before* `build()` inside
        # `navigate_to`, so an exception here takes the navigation down rather
        # than one screen — Home would refuse to open at all. Dropping the held
        # week makes `build()` retry it and report the failure properly.
        try:
            self._week = current_program_week(self.store)
        except Exception:
            self._week = None

    def _program_week(self) -> ProgramWeek:
        """The held answer, computed on demand if `on_show()` never ran."""
        if self._week is None:
            self._week = current_program_week(self.store)
        return self._week

    def _reload(self):
        self._week = None
        self.page.data["refresh_current"]()

    def handle_back(self) -> bool:
        return False

    # ── small pieces ─────────────────────────────────────────
    def _stat_card(self, value: str, label: str, tooltip: str | None = None) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        value,
                        size=22,
                        weight=ft.FontWeight.W_900,
                        color=C.accent,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color=C.text_secondary,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.xl,
            padding=ft.padding.symmetric(horizontal=8, vertical=10),
            expand=True,
            height=72,
            tooltip=tooltip,
        )

    # ── the day panel ────────────────────────────────────────
    def _day_tile(
        self,
        label: str,
        value: str,
        caption: str = "",
        *,
        tone: str | None = None,
        on_click=None,
        tooltip: str | None = None,
    ) -> ft.Control:
        """A number with its label AND its caption. The caption is the point.

        `_stat_card` above deliberately has no third line — "Sessions / 2" needs
        none. Everything in the day panel does: a body weight without "today" or
        "3 days ago" beside it reads as current when it is not, and a waist
        without its age is the same lie with a fortnight's worth of drift behind
        it. So this tile has room for the qualifier and `_stat_card` stays as it
        is rather than growing an argument nobody else passes.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label, size=10, weight=ft.FontWeight.W_800, color=C.text_secondary),
                    ft.Text(
                        value,
                        size=19,
                        weight=ft.FontWeight.W_900,
                        color=tone or (C.text if value != "—" else C.text_muted),
                    ),
                    ft.Text(caption, size=10, color=C.text_secondary),
                ],
                spacing=1,
                tight=True,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.xl,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            expand=True,
            on_click=on_click,
            ink=on_click is not None,
            tooltip=tooltip,
        )

    def _weight_tile(self) -> ft.Control:
        """Today's weigh-in, the rolling average and the rate — or what is missing.

        The plan steers on the average and adjusts at ±0.3 kg/week, so the raw
        number is the least interesting thing here and gets the caption, not the
        headline, once there is a rate to show.
        """
        nav = self.page.data["navigate_to"]
        try:
            pesos = self.store.get_weights(limit=90)
        except Exception:
            pesos = []

        hoy = date.today().isoformat()
        de_hoy = next((p for p in reversed(pesos) if p["date"] == hoy), None)
        media, ritmo = weight_trend(pesos)

        if de_hoy is not None:
            valor, tono = f"{de_hoy['kg']:g} kg", C.success
        elif pesos:
            ultimo = pesos[-1]
            dias = (date.today() - date.fromisoformat(ultimo["date"])).days
            valor, tono = f"{ultimo['kg']:g} kg", C.warning
            return self._day_tile(
                "PESO",
                valor,
                f"hace {plural(dias, 'día')} · hoy no",
                tone=tono,
                on_click=lambda _: nav(VIEW_PROFILE),
            )
        else:
            return self._day_tile(
                "PESO",
                "—",
                "sin registrar · toca para añadir",
                on_click=lambda _: nav(VIEW_PROFILE),
            )

        if ritmo is not None:
            pie = f"media {media:.1f} · {ritmo:+.2f} kg/sem"
        elif media is not None:
            pie = f"media {media:.1f} · ritmo a los {MIN_TREND_DAYS} d"
        else:
            pie = "pesado hoy"
        return self._day_tile("PESO", valor, pie, tone=tono, on_click=lambda _: nav(VIEW_PROFILE))

    def _agenda_card(self) -> ft.Control | None:
        """Hoy y mañana del Google Calendar, si está conectado.

        None cuando no lo está: una tarjeta "conecta tu calendario" permanente
        sería ruido para una función opcional — la puerta vive en Ajustes. Un
        calendario conectado pero inalcanzable (sin señal) tampoco rompe Home:
        la tarjeta dice que no pudo leer, y ya.
        """
        import gcal

        try:
            if not gcal.conectado(self.store):
                return None
            eventos = gcal.eventos(self.store, days=2)
            error = None
        except Exception as exc:
            eventos, error = [], str(exc)

        hoy = date.today().isoformat()
        manana = (date.today() + timedelta(days=1)).isoformat()
        filas: list[ft.Control] = [
            ft.Row(
                [
                    ft.Text("AGENDA", size=10, weight=ft.FontWeight.W_800, color=C.text_secondary),
                ]
            )
        ]
        if error:
            filas.append(
                ft.Text(f"No se pudo leer el calendario: {error}", size=10, color=C.warning)
            )
        elif not eventos:
            filas.append(muted_text("Nada en la agenda hoy ni mañana."))
        else:
            for ev in eventos[:5]:
                etiqueta_dia = (
                    "hoy" if ev["day"] == hoy else ("mañana" if ev["day"] == manana else ev["day"])
                )
                hora = "todo el día" if ev["all_day"] else ev["start"][11:16]
                filas.append(
                    ft.Row(
                        [
                            ft.Text(
                                f"{etiqueta_dia} {hora}",
                                size=11,
                                color=C.accent,
                                weight=ft.FontWeight.W_700,
                                width=110,
                            ),
                            ft.Text(
                                ev["title"],
                                size=12,
                                color=C.text,
                                expand=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=8,
                    )
                )
        return ft.Container(
            content=ft.Column(filas, spacing=4, tight=True),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.lg,
            padding=12,
        )

    def _photo_tile(self) -> ft.Control:
        """La foto de progreso de hoy — hecha o pendiente, y la puerta a la galería.

        Mismo papel que PESO y CINTURA: un hábito diario con su estado a la
        vista. Sin foto hoy, el toque abre directamente el selector (un toque
        menos para el hábito); con ella, abre la galería, que es donde está
        el valor una vez la de hoy ya existe.
        """
        import fotos as _fotos

        nav = self.page.data["navigate_to"]
        hoy = date.today().isoformat()
        try:
            de_hoy = _fotos.para_fecha(self.store, hoy)
            total = len(self.store.get_photos())
        except Exception:
            de_hoy, total = None, 0

        vista_fotos = self.page.data.get("photos_view")

        def _tap(_):
            if de_hoy is None and vista_fotos is not None:
                nav(VIEW_PHOTOS)
                vista_fotos.pick_today()
            else:
                nav(VIEW_PHOTOS)

        mini: ft.Control
        if de_hoy and de_hoy.get("path"):
            mini = ft.Image(
                src=de_hoy["path"],
                width=44,
                height=44,
                fit=ft.ImageFit.COVER,
                cache_width=88,
                border_radius=Radius.sm,
            )
        else:
            mini = ft.Icon(ft.Icons.ADD_A_PHOTO_OUTLINED, color=C.text_muted, size=26)

        guardadas = "guardada" if total == 1 else "guardadas"
        if de_hoy:
            titulo, tono = "Foto de hoy hecha", C.success
            pie = f"{plural(total, 'foto')} en la galería · toca para verlas"
        else:
            titulo, tono = "Sin foto hoy", C.text
            pie = (
                "toca para añadirla — misma luz, misma pose"
                if total == 0
                # El participio concuerda con el número, igual que el sustantivo:
                # `plural()` daba «1 foto» y el «guardadas» fijo de al lado lo
                # deshacía en la misma frase.
                else f"toca para añadirla · {plural(total, 'foto')} {guardadas}"
            )

        return ft.Container(
            content=ft.Row(
                [
                    mini,
                    ft.Column(
                        [
                            ft.Text(
                                "FOTO", size=10, weight=ft.FontWeight.W_800, color=C.text_secondary
                            ),
                            ft.Text(titulo, size=14, weight=ft.FontWeight.W_900, color=tono),
                            ft.Text(pie, size=10, color=C.text_secondary),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.lg,
            padding=12,
            on_click=_tap,
            ink=True,
        )

    def _waist_tile(self) -> ft.Control:
        """Waist, its age, and how far it has drifted — with no verdict.

        The plan calls the waist "el freno" and cuts 150 kcal at +1 cm, but it
        says that twice and the two statements disagree about the window (from
        the initial measurement, or fortnight over fortnight). `waist_summary`
        returns both on purpose; the caption shows the baseline one because that
        is the wording in the goal section and the more conservative reading,
        and the tooltip carries the other. Picking one silently would make this
        tile the first place in the system where an ambiguous rule becomes a
        number Alex acts on.
        """
        nav = self.page.data["navigate_to"]
        try:
            resumen = waist_summary(self.store.get_measurements(limit=30))
        except Exception:
            resumen = waist_summary([])

        if not resumen.known:
            return self._day_tile(
                "CINTURA",
                "—",
                "sin base · toca para añadir",
                tone=C.warning,
                on_click=lambda _: nav(VIEW_PROFILE),
            )

        if resumen.vs_baseline is None:
            pie = f"base · hace {plural(resumen.days_ago or 0, 'día')}"
            consejo = "Una sola medición es la base, no un cambio."
        else:
            pie = f"{resumen.vs_baseline:+.1f} cm desde el inicio · hace {plural(resumen.days_ago or 0, 'día')}"
            consejo = (
                f"{resumen.vs_baseline:+.1f} cm desde {resumen.baseline_on} "
                f"(respecto a la medición inicial)\n"
                f"{resumen.vs_previous:+.1f} cm desde {resumen.previous_on} "
                f"(respecto a la anterior)\n"
                f"El plan recorta 150 kcal a +1,0 cm, y enuncia la ventana de dos formas — "
                f"así que aquí están las dos. El ruido de la cinta ronda ±0,5 cm.\n"
                f"Se mide cada {MEASUREMENT_EVERY_DAYS} días."
            )
        if resumen.due:
            pie += " · toca medir"
        return self._day_tile(
            "CINTURA",
            f"{resumen.latest:g} cm",
            pie,
            tone=C.warning if resumen.due else None,
            on_click=lambda _: nav(VIEW_PROFILE),
            tooltip=consejo,
        )

    def _reminders_card(self) -> ft.Control:
        """Los avisos de hoy, y la puerta de entrada a gestionarlos.

        Ya no devuelve `None` en el móvil: desde que la plantilla forkeada
        programa notificaciones (`notificaciones.py` + `main.dart`), el móvil
        entrega sus propios avisos y la tarjeta vacía es accionable — "añade el
        primero" — en vez de una caja en blanco que parece rota.

        Sigue habiendo dos repartidores y la tarjeta lo dice: en el PC entrega
        el bot por Telegram; en el móvil, Android. La lista es "lo que queda por
        sonar HOY" — un diario ya disparado apunta a mañana y es correcto que no
        esté; el diálogo de gestión enseña todos.
        """
        try:
            avisos = self.store.get_reminders_today()
            todos = self.store.get_all_reminders()
        except Exception:
            avisos, todos = [], []

        filas: list[ft.Control] = []
        if not avisos:
            vacio = (
                "Nada más pendiente hoy"
                if any(a["activo"] for a in todos)
                else "Sin avisos aún — añade el primero"
            )
            filas.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, size=16, color=C.text_muted),
                        ft.Text(vacio, size=12, color=C.text_secondary, expand=True),
                    ],
                    spacing=8,
                )
            )
        for a in avisos:
            # Solo la primera línea: los fijos del bot traen párrafos de
            # Markdown pensados para Telegram y enterrarían la pantalla.
            titulo = (a["text"] or "").splitlines()[0].strip() or "(sin texto)"
            filas.append(
                ft.Row(
                    [
                        ft.Text(
                            "¡ya!" if a["overdue"] else a["at"],
                            size=11,
                            weight=ft.FontWeight.W_800,
                            color=C.warning if a["overdue"] else C.accent,
                            width=42,
                        ),
                        ft.Text(titulo, size=12, color=C.text, expand=True, max_lines=2),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        return card(
            ft.Row(
                [
                    ft.Text(
                        "AVISOS DE HOY",
                        size=10,
                        weight=ft.FontWeight.W_800,
                        color=C.text_secondary,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Icon(ft.Icons.ADD_ROUNDED, size=16, color=C.accent),
                        on_click=lambda _: self._open_reminders(),
                        ink=True,
                        padding=4,
                        border_radius=Radius.pill,
                        tooltip="Añadir o gestionar avisos",
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=2),
            *filas,
            padding=12,
        )

    def _open_reminders(self):
        """Gestión de avisos: la lista completa y el alta, en un diálogo.

        El alta escribe una fila `origen="usuario"` y llama a
        `notificaciones.sync()`: en el móvil eso reescribe `notifications.json`
        y Android queda programado aunque la app se cierre; en el PC la fila la
        recoge el bot en su siguiente vuelta y la entrega por Telegram. Los
        `fijo` del bot se enseñan sin papelera — borrarlos aquí solo haría que
        el bot los resembrara con otro id en su siguiente arranque.
        """
        import notificaciones

        texto = ft.TextField(
            label="Texto del aviso",
            hint_text="Sacar el pollo del congelador",
            dense=True,
            border_color=C.border,
            color=C.text,
        )
        hora = ft.TextField(
            label="Hora (HH:MM)",
            value="20:00",
            dense=True,
            width=110,
            border_color=C.border,
            color=C.text,
        )
        fecha = ft.TextField(
            label="Fecha (AAAA-MM-DD)",
            value=date.today().isoformat(),
            dense=True,
            expand=True,
            visible=True,
            border_color=C.border,
            color=C.text,
        )
        error = ft.Text("", size=11, color=C.danger)

        DIAS = [("L", 1), ("M", 2), ("X", 3), ("J", 4), ("V", 5), ("S", 6), ("D", 0)]
        elegidos: set[int] = set()
        chips_dias: list[ft.Container] = []

        def _pinta_chip(caja: ft.Container, activo: bool):
            caja.bgcolor = C.accent_soft if activo else None
            caja.border = ft.border.all(1, C.accent if activo else C.border)
            caja.content.color = C.accent if activo else C.text_secondary

        def _toca_dia(caja: ft.Container, valor: int):
            def go(_):
                if valor in elegidos:
                    elegidos.discard(valor)
                else:
                    elegidos.add(valor)
                _pinta_chip(caja, valor in elegidos)
                self.page.update()

            return go

        for etiqueta, valor in DIAS:
            caja = ft.Container(
                content=ft.Text(etiqueta, size=12, weight=ft.FontWeight.W_700),
                width=32,
                height=32,
                alignment=ft.alignment.center,
                border_radius=Radius.pill,
                ink=True,
            )
            caja.on_click = _toca_dia(caja, valor)
            _pinta_chip(caja, False)
            chips_dias.append(caja)
        fila_dias = ft.Row(chips_dias, spacing=4, visible=False)

        tipo = ft.Dropdown(
            label="Repetición",
            value="once",
            dense=True,
            expand=True,
            border_color=C.border,
            color=C.text,
            options=[
                ft.dropdown.Option("once", "Una vez"),
                ft.dropdown.Option("daily", "Cada día"),
                ft.dropdown.Option("weekly", "Días de la semana"),
            ],
        )

        def _cambia_tipo(_):
            fila_dias.visible = tipo.value == "weekly"
            fecha.visible = tipo.value == "once"
            self.page.update()

        tipo.on_change = _cambia_tipo

        lista = ft.Column(spacing=4, tight=True)

        def _refresca_lista():
            try:
                todos = self.store.get_all_reminders()
            except Exception:
                todos = []
            filas: list[ft.Control] = []
            for a in todos:
                encabezado = (a["texto"] or "").splitlines()[0].strip()[:60]
                receta = notificaciones.parse_cron_simple(a["cron"])
                if a["cron"] is None:
                    pauta = "una vez"
                elif receta is None:
                    pauta = "pauta del bot"
                elif receta["weekdays"] is None:
                    pauta = f"cada día · {receta['hour']:02d}:{receta['minute']:02d}"
                else:
                    nombres = {1: "L", 2: "M", 3: "X", 4: "J", 5: "V", 6: "S", 0: "D"}
                    dias_txt = "".join(
                        nombres[d] for d in sorted(receta["weekdays"], key=lambda x: (x - 1) % 7)
                    )
                    pauta = f"{dias_txt} · {receta['hour']:02d}:{receta['minute']:02d}"
                if not a["activo"]:
                    pauta += " · pausado"
                es_usuario = a["origen"] != "fijo"
                acciones: list[ft.Control] = []
                if es_usuario:
                    acciones.append(
                        ft.Container(
                            content=ft.Icon(ft.Icons.DELETE_OUTLINE, size=16, color=C.danger),
                            on_click=(lambda rid: lambda _: _borra(rid))(a["id"]),
                            ink=True,
                            padding=4,
                            tooltip="Borrar este aviso",
                        )
                    )
                else:
                    acciones.append(
                        ft.Icon(ft.Icons.SMART_TOY_OUTLINED, size=14, color=C.text_muted)
                    )
                filas.append(
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(encabezado, size=12, color=C.text, max_lines=1),
                                    ft.Text(pauta, size=10, color=C.text_muted),
                                ],
                                spacing=0,
                                tight=True,
                                expand=True,
                            ),
                            *acciones,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
            lista.controls = filas or [ft.Text("Sin avisos todavía.", size=11, color=C.text_muted)]

        def _borra(rid: int):
            self.store.delete_reminder(rid)
            notificaciones.sync(self.store)
            _refresca_lista()
            self.page.update()

        def _guarda(_):
            try:
                h, m = (texto_hora := (hora.value or "").strip()).split(":")
                h, m = int(h), int(m)
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError(texto_hora)
            except ValueError:
                error.value = "La hora tiene que ser HH:MM, de 00:00 a 23:59."
                self.page.update()
                return
            if not (texto.value or "").strip():
                error.value = "El aviso necesita un texto."
                self.page.update()
                return
            try:
                if tipo.value == "once":
                    from storage import _madrid

                    dia = date.fromisoformat((fecha.value or "").strip())
                    cuando = datetime.combine(dia, time(h, m), tzinfo=_madrid()).astimezone(
                        timezone.utc
                    )
                    if cuando <= datetime.now(timezone.utc):
                        error.value = "Ese momento ya ha pasado."
                        self.page.update()
                        return
                    cron = None
                else:
                    if tipo.value == "weekly" and not elegidos:
                        error.value = "Elige al menos un día de la semana."
                        self.page.update()
                        return
                    cron = notificaciones.cron_para(
                        tipo.value, h, m, elegidos if tipo.value == "weekly" else None
                    )
                    cuando = notificaciones.next_occurrence(cron, datetime.now(timezone.utc))
                self.store.add_reminder(texto.value, cuando, cron)
                notificaciones.sync(self.store)
            except (ValueError, Exception) as exc:  # noqa: B014 - un alta fallida se explica, no revienta
                error.value = f"No se pudo guardar: {exc}"
                self.page.update()
                return
            texto.value = ""
            error.value = ""
            _refresca_lista()
            self.page.update()

        _refresca_lista()

        entrega = (
            "Los entrega Telegram (el bot del PC)."
            if self.store.bot_delivers_reminders()
            else "Los entrega el móvil, con la app cerrada incluso."
        )

        # El puente de vuelta desde Dart: si el sistema tiene algo apagado, el
        # sitio donde Alex lo va a buscar es exactamente este diálogo — "creo
        # que se tiene que pedir permisos" es literalmente lo que reportó. Sin
        # fichero de estado (PC, primer arranque) no se alarma de nada.
        avisos_sistema: list[ft.Control] = []
        estado = notificaciones.estado_android()
        if estado is not None:
            if not estado["granted"]:
                avisos_sistema.append(
                    ft.Container(
                        content=ft.Text(
                            "Las notificaciones están APAGADAS para IronFlet. "
                            "Actívalas en Ajustes del sistema → Aplicaciones → "
                            "IronFlet → Notificaciones, o ningún aviso sonará.",
                            size=11,
                            color=C.danger,
                            weight=ft.FontWeight.W_700,
                        ),
                        border=ft.border.all(1, C.danger),
                        border_radius=10,
                        padding=10,
                    )
                )
            elif not estado["exact"]:
                avisos_sistema.append(
                    ft.Container(
                        content=ft.Text(
                            "Los avisos pueden llegar con retraso: activa "
                            "«Alarmas y recordatorios» para IronFlet en los "
                            "Ajustes del sistema. Si tu móvil «optimiza» la "
                            "batería de la app, quítale también esa optimización.",
                            size=11,
                            color=C.warning,
                        ),
                        border=ft.border.all(1, C.warning),
                        border_radius=10,
                        padding=10,
                    )
                )

            # LA CAUSA NÚMERO UNO de «no me suena» en un móvil de verdad, y la
            # que el emulador nunca reproduce: el sistema mete la app en la
            # lista de optimización de batería y le cancela las alarmas. El
            # permiso puede estar concedido y la alarma ser exacta, y aun así
            # no llegar nada. Se avisa aunque los otros dos estén bien, porque
            # es independiente de ellos.
            if estado.get("battery_optimised"):
                avisos_sistema.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    "Tu móvil está «optimizando» la batería de IronFlet, "
                                    "y eso le cancela las alarmas: los avisos no sonarán "
                                    "aunque el permiso esté dado.",
                                    size=11,
                                    color=C.warning,
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Container(height=6),
                                ghost_button(
                                    "Quitar la optimización",
                                    on_click=lambda _: _abre_bateria(),
                                    expand=True,
                                ),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        border=ft.border.all(1, C.warning),
                        border_radius=10,
                        padding=10,
                    )
                )

        def _abre_bateria():
            notificaciones.abrir_ajustes_bateria()
            self.page.close(dlg)

        def _prueba(_):
            # Separa «la app no programa» de «Android no entrega». Las dos se
            # ven igual desde fuera —silencio— y llevan a sitios opuestos, así
            # que sin este botón no hay forma de saber cuál de las dos es.
            if notificaciones.probar_aviso():
                prueba_msg.value = (
                    "Enviado. Si en unos segundos no ves nada en la barra, el "
                    "problema es el permiso o el canal, no los horarios."
                )
                prueba_msg.color = C.text_secondary
            else:
                prueba_msg.value = "Aquí no hay avisos del sistema que probar."
                prueba_msg.color = C.text_muted
            self.page.update()

        prueba_msg = ft.Text("", size=10, color=C.text_muted)

        dlg = ft.AlertDialog(
            bgcolor=C.bg_surface,
            title=ft.Text("Avisos", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(
                    [
                        *avisos_sistema,
                        texto,
                        ft.Row([tipo, hora], spacing=8),
                        fecha,
                        fila_dias,
                        error,
                        ft.Row([primary_button("Añadir aviso", on_click=_guarda, expand=True)]),
                        # El botón de diagnóstico va AQUÍ y no al final: la
                        # lista de abajo crece con cada aviso, y detrás de
                        # quince filas de scroll está justo donde no se
                        # encuentra la herramienta que se busca cuando algo no
                        # suena. Aquí se ve sin desplazar, siempre.
                        ghost_button("Probar un aviso ahora", on_click=_prueba, expand=True),
                        prueba_msg,
                        ft.Container(height=6),
                        ft.Text(
                            "TODOS LOS AVISOS",
                            size=10,
                            weight=ft.FontWeight.W_800,
                            color=C.text_secondary,
                        ),
                        lista,
                        ft.Text(entrega, size=10, color=C.text_muted),
                    ],
                    spacing=8,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=dialog_width(self.page),
                height=dialog_height(self.page, 520),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                )
            ],
        )
        self.page.open(dlg)

    def _streak_card(self, streak: int) -> ft.Control:
        return card(
            ft.Text("🔥", size=18, text_align=ft.TextAlign.CENTER),
            ft.Text(
                str(streak),
                size=20,
                weight=ft.FontWeight.W_900,
                color=C.accent,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "semana" if streak == 1 else "semanas",  # the number is above it, so noun only
                size=9,
                weight=ft.FontWeight.W_700,
                color=C.text_muted,
                text_align=ft.TextAlign.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            alignment=ft.alignment.center,
            tooltip="Semanas seguidas cumpliendo el mínimo de sesiones de tu rutina",
        )

    def _today_item(self, w) -> ft.Container:
        set_chips = [
            chip(
                f"{s['weight']:g}kg × {s['reps']}"
                if s.get("weight", 0) > 0
                else f"{s['reps']} reps",
                color=C.accent,
            )
            for s in w.sets
        ]
        return card(
            ft.Row(
                [
                    ft.Text(
                        nombres_es.ejercicio(w.exercise),
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=C.text,
                        expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    chip(w.muscle_group, color=C.accent),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(set_chips, wrap=True, spacing=6, run_spacing=4) if set_chips else ft.Container(),
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    # ── what today is ────────────────────────────────────────
    def _today_card(self) -> ft.Control:
        """Today's session, in the first thing on the screen.

        Four outcomes on an active week, and each says exactly what it knows:

        * a training day — the session name, big, how many exercises it holds,
          and the card opens Train;
        * a rest day — said plainly, plus what is next, so a rest day does not
          read as a bug. The weekend lands here too: the rotation rows only
          cover Mon-Fri, so `today_focus` is None on Saturday, and the next
          week's row only exists once Monday makes it the current one;
        * a known week whose phase does not pin sessions to weekdays
          (CambiaTuFísico phases 4-7, and every routine with no rotation) — the
          phase, and an honest "pick it in Train". Those phases prescribe five
          sessions without saying which day each falls on, and dealing them out
          Mon-to-Fri would be the app inventing the plan;
        * no week at all — see `_no_session_card`.
        """
        pw = self._program_week()
        if pw.status is not WeekStatus.ACTIVE or pw.phase is None:
            return self._no_session_card(pw)

        phase = pw.phase
        focus = pw.today_focus
        sub = f"Fase {phase.id} · {phase.name}"
        tip: str | None

        if pw.rotation is None:
            # The phase name is the headline here, so the line under it carries
            # the subtitle instead — printing the name twice tells nobody
            # anything.
            headline, target, tip = phase.name, VIEW_WORKOUT, "Elige la sesión de hoy en Entreno"
            sub = f"Fase {phase.id} · {phase.subtitle}" if phase.subtitle else f"Fase {phase.id}"
        elif focus is None or is_rest_label(focus):
            nxt = next_session(pw)
            headline, target = "Día de descanso", VIEW_PLAN
            if nxt:
                tip = f"Siguiente: {day_name(nxt[0])} · {nxt[1]}"
            else:
                tip = "El plan de la semana nueva empieza el lunes"
        else:
            headline, target = nombres_es.dia(focus), VIEW_WORKOUT
            # The label is a session name; the phase turns it into real work.
            # None when this phase does not have that day, and then the count is
            # simply not claimed.
            day = training_day_for_label(focus, phase)
            tip = plural(len(day.exercises), "ejercicio") if day else None

        lines: list[ft.Control] = [
            ft.Text(
                f"HOY · {week_headline(pw)}", size=10, weight=ft.FontWeight.W_900, color=C.accent
            ),
            ft.Text(
                headline,
                size=20,
                weight=ft.FontWeight.W_900,
                color=C.text,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Text(sub, size=11, weight=ft.FontWeight.W_700, color=phase_color(phase.id)),
        ]
        if tip:
            lines.append(ft.Text(tip, size=11, color=C.text_muted))
        # Both of these are silent on a normal week. They are the difference
        # between a number that is a fact and one that is arithmetic: an
        # inferred start date, and a week count that has run on without training.
        caveat = start_caveat(pw)
        if caveat:
            lines.append(ft.Text(caveat, size=10, color=C.text_muted))
        if pw.stale:
            lines.append(
                ft.Text(
                    f"Nada registrado en {plural(pw.weeks_idle, 'semana')} — mira Plan para retomar",
                    size=10,
                    color=C.warning,
                )
            )

        nav = self.page.data["navigate_to"]
        return card(
            ft.Row(
                [
                    ft.Column(lines, spacing=2, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=Space.x3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            border_color=C.accent,
            on_click=lambda _, v=target: nav(v),
            ink=True,
            tooltip="Abrir Entreno" if target == VIEW_WORKOUT else "Abrir el plan de la semana",
        )

    def _no_session_card(self, pw: ProgramWeek) -> ft.Control:
        """No session to name — never dated, not started, over, or off-plan.

        Four different reasons and four different sentences: "I don't know when
        you started" and "you finished the routine" both leave today blank, and
        telling them apart is the whole reason `WeekStatus` exists. The fix
        button is here rather than a trip to Plan because this is where the
        reader is standing when they find out.
        """
        started = pw.start.day
        if pw.status is WeekStatus.SCHEDULED:
            title = "Sin empezar todavía"
            body = (
                f"Esta rutina está fijada para empezar el {started.isoformat()}."
                if started
                else "Esta rutina está fijada para empezar más adelante."
            )
        elif pw.status is WeekStatus.FINISHED:
            title = "Rutina terminada"
            body = (
                f"{week_headline(pw).capitalize()} ya pasa del final de esta rutina. "
                "Fija otra fecha de inicio para repetirla, o elige otra rutina en Plan."
            )
        elif pw.status is WeekStatus.ACTIVE:  # active, but no phase claims the week
            title = "Ninguna fase cubre esta semana"
            body = (
                f"{week_headline(pw).capitalize()} cae en un hueco entre los rangos "
                "de fases de esta rutina. Revísalos en Plan."
            )
        elif pw.start.source is StartSource.OTHER_ROUTINE:
            # A date exists, it just belongs to a routine he switched away from.
            # Saying "nothing records when you started" here would be a lie he
            # could disprove, and the fix is one tap: the dialog opens on that
            # date, so adopting it is a save.
            title = "Semana desconocida"
            body = (
                "Hay una fecha de inicio guardada, pero era de otra rutina, así que "
                "no puede situarte en esta — cambiar de rutina arranca un programa "
                "nuevo. Fija la fecha para traerla."
            )
        else:
            title = "Semana desconocida"
            body = (
                "Nada registra cuándo empezaste esta rutina, así que la app no puede "
                "decir qué sesión toca hoy — y adivinar te mandaría al gimnasio el "
                "día equivocado. Fija la fecha, o simplemente entrena: la primera "
                "sesión que registres fecha la rutina."
            )
        prefill = started if pw.start.source is StartSource.OTHER_ROUTINE else None
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.HELP_OUTLINE, color=C.warning, size=18),
                    ft.Text(title, size=15, weight=ft.FontWeight.W_900, color=C.text, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(body, size=11, color=C.text_secondary),
            ft.Container(height=Space.x1),
            ghost_button(
                "Fijar fecha de inicio",
                on_click=lambda _, d=prefill: open_start_date_dialog(
                    self.page, self.store, on_saved=self._reload, initial=d
                ),
                expand=True,
            ),
            padding=14,
            border_color=C.warning,
        )

    # ── nutrition ────────────────────────────────────────────
    def _macro_line(self, label: str, current: float, target: float, unit: str) -> ft.Control:
        # Overshooting calories is worth a warning; overshooting protein is not,
        # so each line says for itself what "past the target" looks like.
        over_target = label == "Calorías"
        value = f"{_n(current)} / {_n(target)} {unit}" if target > 0 else f"{_n(current)} {unit}"
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(label, size=11, weight=ft.FontWeight.W_700, color=C.text_secondary),
                        ft.Text(value, size=11, color=C.text_muted),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                _macro_bar(
                    current,
                    target,
                    C.accent if over_target else C.success,
                    C.warning if over_target else C.success,
                ),
            ],
            spacing=3,
            tight=True,
        )

    def _nutrition_body(self, totals: dict, targets: dict, logged: bool) -> ft.Control:
        # Las claves son inglesas a propósito: son las que devuelven
        # `nutrition.day_totals()` y `nutrition.targets_for()`, contrato de
        # datos y no texto (trampa 22). Traducirlas aquí no rompió nada
        # ruidosamente — `.get()` devolvía None y la tarjeta pintaba 0 g de
        # proteína con 42 g registrados.
        target_kcal = float(targets.get("kcal") or 0)
        target_protein = float(targets.get("protein") or 0)

        if not logged:
            # Zeroes against a target read as failure at 9am. An empty day is an
            # invitation, so it gets one.
            hint = (
                f"Objetivo de hoy: {_n(target_kcal)} kcal · {_n(target_protein)} g de proteína"
                if target_kcal > 0
                else "Apunta una comida para empezar a contar calorías y proteína"
            )
            return ft.Column(
                [
                    ft.Text(
                        "Nada registrado hoy", size=13, weight=ft.FontWeight.W_700, color=C.text
                    ),
                    ft.Text(hint, size=11, color=C.text_muted),
                ],
                spacing=2,
                tight=True,
                expand=True,
            )

        return ft.Column(
            [
                ft.Text("Comida de hoy", size=13, weight=ft.FontWeight.W_700, color=C.text),
                self._macro_line("Calorías", float(totals.get("kcal") or 0), target_kcal, "kcal"),
                self._macro_line(
                    "Proteína", float(totals.get("protein") or 0), target_protein, "g"
                ),
            ],
            spacing=Space.x2,
            tight=True,
            expand=True,
        )

    def _nutrition_card(self) -> ft.Control:
        today = date.today()
        totals = day_totals(self.store, today) or {}
        targets = targets_for(self.store, today) or {}
        # Entries first: an entry can legitimately be 0 kcal (black coffee), and
        # a day with one is not an empty day. Calories are the fallback for when
        # the meal blocks arrive without their entries.
        logged = bool(
            any(block.get("entries") for block in (totals.get("by_meal") or {}).values())
            or float(totals.get("kcal") or 0) > 0
        )
        nav = self.page.data["navigate_to"]
        return card(
            ft.Row(
                [
                    ft.Text("🍽", size=20),
                    self._nutrition_body(totals, targets, logged),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=Space.x3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            on_click=lambda _: nav(VIEW_NUTRITION),
            ink=True,
            tooltip="Abrir el diario de comida",
        )

    def _abdomen_card(self) -> ft.Control | None:
        """El abdomen de hoy, o `None` si está apagado.

        Existe porque Alex pidió abdomen «cada día» y entrena cuatro o cinco:
        dentro de la sesión de pesas ya se añade solo, pero los días de
        descanso no habría dónde hacerlo. Esta tarjeta es ese sitio, y es la
        que convierte «cada día» en verdad.

        Cuando ya está hecho lo dice y deja de invitar: una tarjeta que sigue
        pidiendo algo que acabas de hacer enseña a ignorarla.
        """
        import abdomen

        try:
            if not abdomen.activo(self.store):
                return None
            toca = abdomen.de_hoy(self.store)
        except Exception:
            return None
        if not toca:
            return None

        hechos = self._abdomen_hechos(toca)
        completo = len(hechos) >= len(toca)

        if completo:
            titulo, detalle, color = (
                "Abdomen hecho",
                "los " + plural(len(toca), "ejercicio"),
                C.success,
            )
        elif hechos:
            titulo = "Abdomen a medias"
            detalle = f"{len(hechos)} de {len(toca)} · sigue por {toca[len(hechos)]}"
            color = C.warning
        else:
            titulo = "Abdomen de hoy"
            detalle = " · ".join(toca)
            color = C.text_secondary

        nav = self.page.data["navigate_to"]

        def _empezar(_):
            vista = self.page.data.get("workout_view")
            if vista is not None:
                vista.empezar_abdomen()
            nav(VIEW_WORKOUT)

        return card(
            ft.Row(
                [
                    ft.Text("🔥" if not completo else "✅", size=20),
                    ft.Column(
                        [
                            ft.Text(titulo, size=13, weight=ft.FontWeight.W_700, color=C.text),
                            ft.Text(
                                detalle,
                                size=11,
                                color=color,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=2,
                        tight=True,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=18),
                ],
                spacing=Space.x3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
            on_click=_empezar,
            ink=True,
            tooltip="Hacer el abdomen de hoy",
        )

    def _abdomen_hechos(self, toca: tuple[str, ...]) -> list[str]:
        """Cuáles de los de hoy ya están en `entrenos`.

        Contra el historial y no contra un flag: el flag habría que ponerlo al
        guardar, y una sesión abandonada a medias lo dejaría mintiendo.
        """
        from exercises import exercise_key

        try:
            hoy = {exercise_key(e.exercise) for e in self.store.get_workouts_on(date.today())}
        except Exception:
            return []
        return [n for n in toca if exercise_key(n) in hoy]

    # ── screen ───────────────────────────────────────────────
    def build(self) -> ft.Control:
        try:
            return self._screen()
        except Exception as exc:
            # Home is the first screen of the app: if it raises, the app opens
            # on nothing at all and there is no way to reach Profile or Plan to
            # find out why. A card that names the failure and offers a retry is
            # the difference between "the server is off" and "it is broken".
            return db_error_screen("IronFlet", exc, on_retry=self._reload)

    def _screen(self) -> ft.Control:
        streak = self.store.get_streak()
        stats = self.store.get_week_stats()
        today = self.store.get_today()

        vol = stats["volume"]
        # `12.3k` with a nine-point "Vol (kg)" under it does not say whether it
        # is 12.3 thousand kilos or something else entirely. The tile keeps the
        # short form — it has room for five characters — and the tooltip
        # carries the whole number, its unit and how it was worked out.
        vol_str = f"{vol / 1000:.1f}k" if vol >= 1000 else f"{int(vol)}"
        vol_tooltip = f"Peso × reps, sumado en {STATS_WINDOW_LABEL.lower()}: {vol:,.0f} kg"

        nav = self.page.data["navigate_to"]
        profile_btn = ft.Container(
            content=ft.Icon(ft.Icons.SETTINGS, color=C.accent, size=18),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.sm,
            width=34,
            height=34,
            alignment=ft.alignment.center,
            on_click=lambda _: nav(VIEW_PROFILE),
            ink=True,
            tooltip="Ajustes",
        )

        coach_btn = ft.Container(
            content=ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, color=C.accent, size=18),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.sm,
            width=34,
            height=34,
            alignment=ft.alignment.center,
            on_click=lambda _: nav(VIEW_COACH),
            ink=True,
            tooltip="Entrenador",
        )

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("IRONFLET", size=11, weight=ft.FontWeight.W_900, color=C.accent),
                        ft.Text(today_display(), size=22, weight=ft.FontWeight.W_900, color=C.text),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.Row(
                    [coach_btn, profile_btn, self._streak_card(streak)],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # La etiqueta concuerda con su número. Eran literales fijos, así que la
        # primera semana de cualquiera dice «1 Sesiones» — el número está justo
        # encima, así que la discordancia se lee de golpe. `plural()` devuelve
        # también el número; aquí solo se quiere la palabra, porque el número
        # va en la línea grande de arriba.
        sesiones = plural(int(stats["sessions"]), "sesión").split(" ", 1)[1].capitalize()
        series = plural(int(stats["sets"]), "serie").split(" ", 1)[1].capitalize()

        stats_row = ft.Row(
            [
                # The window is named once, above the row, so the tooltips only
                # have to say what each number counts.
                self._stat_card(str(stats["sessions"]), sesiones, tooltip="Días que entrenaste"),
                self._stat_card(
                    str(stats["sets"]), series, tooltip="Series efectivas — calentamientos fuera"
                ),
                self._stat_card(vol_str, "Vol (kg)", tooltip=vol_tooltip),
            ],
            spacing=8,
        )

        start_btn = primary_button(
            "Empezar sesión",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=lambda _: nav(VIEW_WORKOUT),
            expand=True,
        )

        def _libre(_):
            vista = self.page.data.get("workout_view")
            if vista is not None:
                vista.empezar_libre()
            nav(VIEW_WORKOUT)

        # Llegar al gimnasio sin plan y hacer cuatro cosas. Antes obligaba a
        # entrar por una fase y un día, o sea a fingir que hoy tocaba pecho —
        # y esa mentira acaba en `entrenos.grupo`, que es lo que agrupa
        # Historial.
        libre_btn = ghost_button(
            "Libre",
            on_click=_libre,
            width=88,
            height=48,
            tooltip="Entrenar sin rutina: eliges tú los ejercicios",
        )
        # Browse lost its tab when the bar went down to five. This is now the
        # only entrance to the catalogue, so it is a labelled button, not an icon.
        browse_btn = ghost_button(
            "Ejercicios",
            on_click=lambda _: nav(VIEW_BROWSE),
            width=112,
            height=48,
            tooltip="Abrir el catálogo de ejercicios",
        )

        if today:
            today_block: ft.Control = ft.Column(
                [self._today_item(w) for w in today],
                spacing=0,
                tight=True,
            )
        else:
            today_block = ft.Container(
                content=ft.Column(
                    [
                        ft.Text("💤", size=28, text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            "Sin registros",
                            size=12,
                            color=C.text_muted,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                bgcolor=C.bg_surface,
                border=ft.border.all(1, C.border),
                border_radius=Radius.xl,
                padding=24,
                alignment=ft.alignment.center,
            )

        # THE ORDER IS THE FEATURE. Alex asked to "see my whole day when I open
        # it", so the screen reads top to bottom as the day does: which session
        # is today → the button that starts it → the rest of the day's numbers
        # (body, food, what the coach still has queued) → last week's totals →
        # what has actually been logged.
        #
        # Two things moved to get there. The Start/Exercises row came UP to sit
        # directly under the session card, because it is the action that card
        # asks for and it had drifted below a block of statistics. The food card
        # came up into the day panel, where it belongs with the other "how is
        # today going" numbers rather than floating between the buttons and the
        # log. `Last 7 days` stays below all of it: it is history, and history is
        # not what the app is opened for.
        dia: list[ft.Control] = [
            ft.Row([self._weight_tile(), self._waist_tile()], spacing=8),
            ft.Container(height=Space.x1),
            self._photo_tile(),
            ft.Container(height=Space.x1),
            self._nutrition_card(),
        ]
        # Después de la comida y antes de los avisos: es una tarea del día, y
        # el día de descanso es donde más falta hace.
        abs_hoy = self._abdomen_card()
        if abs_hoy is not None:
            dia.append(ft.Container(height=Space.x1))
            dia.append(abs_hoy)
        avisos = self._reminders_card()
        if avisos is not None:
            dia.append(ft.Container(height=Space.x1))
            dia.append(avisos)
        agenda = self._agenda_card()
        if agenda is not None:
            dia.append(ft.Container(height=Space.x1))
            dia.append(agenda)

        return ft.Column(
            [
                header,
                ft.Container(height=Space.x4),
                # Above the numbers on purpose: the numbers are last week, this
                # is the next hour.
                self._today_card(),
                ft.Container(height=Space.x2),
                ft.Row([start_btn, libre_btn, browse_btn], spacing=8),
                ft.Container(height=Space.x4),
                section_title("Tu día"),
                ft.Container(height=Space.x1),
                *dia,
                ft.Container(height=Space.x4),
                muted_text(STATS_WINDOW_LABEL),
                ft.Container(height=Space.x1),
                stats_row,
                ft.Container(height=Space.x4),
                # "Hoy" twice on one screen would be two different meanings of
                # the word: the card at the top is the *plan*, this is what was
                # actually logged.
                section_title("Registrado hoy"),
                ft.Container(height=Space.x1),
                today_block,
                ft.Container(height=18),
                section_title("Guías"),
                ft.Container(height=Space.x1),
                self._guides_row(),
                ft.Container(height=Space.x4),
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
        )

    def _guides_row(self) -> ft.Control:
        """One card per guide, however many there are.

        The row is driven by `guide_ids()` and every card is `expand=True`, so
        the width is split evenly whatever the count: measured at the 420 px
        window, three cards come out 125 px each and two come out 192 px, both
        flush with the stats row above. Dropping the women guide therefore
        needed no change here. Do not pin a width to keep the old card size —
        two fixed cards leave a dead strip on the right instead of filling it.
        """
        from guides import guide_icon, guide_ids, guide_title_key
        from views.guide_dialog import open_guide

        def card_link(gid: str) -> ft.Container:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            guide_icon(gid),
                            size=22,
                            color=C.text,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            guide_title_key(gid),
                            size=11,
                            color=C.text_secondary,
                            weight=ft.FontWeight.W_700,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
                bgcolor=C.bg_surface,
                border=ft.border.all(1, C.border),
                border_radius=Radius.xl,
                padding=ft.padding.symmetric(horizontal=8, vertical=10),
                on_click=lambda _, g=gid: open_guide(self.page, g),
                ink=True,
                expand=True,
                height=72,
            )

        return ft.Row([card_link(gid) for gid in guide_ids()], spacing=8)
