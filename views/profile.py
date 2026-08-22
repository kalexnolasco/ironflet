"""Profile: user data + calculated health metrics + weight log + backup."""

from __future__ import annotations

from datetime import date

import flet as ft

import agent
import asset_manager
import exercise_images
import openrouter
import widget
from analytics import MEASUREMENT_EVERY_DAYS, moving_average, waist_summary, weight_trend
from components.charts import axis_note, line_chart
from health import (
    ACTIVITY_FACTORS,
    age_years,
    bmi,
    bmi_category,
    bmr_mifflin,
    protein_target_range,
    tdee,
    water_target_l,
)
from storage import THEME_PREF, Storage
from theme import (
    DEFAULT_PALETTE,
    PALETTES,
    C,
    Radius,
    Space,
    apply_theme,
    card,
    ghost_button,
    muted_text,
    primary_button,
    section_title,
)
from views.shared_ui import (
    db_error_card,
    db_error_screen,
    dialog_height,
    dialog_width,
    plural,
)

ACTIVITY_KEYS = list(ACTIVITY_FACTORS.keys())
SEX_KEYS = ["M", "F", ""]


def _texto_de_campo(valor) -> str:
    """Lo que se escribe dentro de un campo del formulario.

    `height_cm` se guarda como float y salía en pantalla como «178.0», que
    nadie escribe cuando le preguntan cuánto mide. Un float que es un entero
    exacto pierde el decimal; uno que no lo es lo conserva, porque 178,5 sí es
    una altura que alguien apunta.

    El cero se trata como vacío, igual que hacía el `str(valor or "")` de
    antes: `set_profile` guarda 0.0 cuando el campo se deja en blanco, y un
    «0» en la casilla de la altura se lee como que mides cero centímetros.
    """
    if valor is None or valor == "" or valor == 0:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _antiguedad(cuando: str, dias: int) -> str:
    """«2026-08-21 · hoy», «… · ayer», «… · hace 3 días».

    El inglés se conforma con "0 days ago" y no chirría; en español "hace 0
    días" sí, y es justo lo que se veía el día que te pesabas.
    """
    if dias <= 0:
        cerca = "hoy"
    elif dias == 1:
        cerca = "ayer"
    else:
        cerca = f"hace {plural(dias, 'día')}"
    return f"{cuando}  ·  {cerca}"


class ProfileView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self._form_values: dict = {}

    def on_show(self):
        # Guarded like `build()`: this runs *before* the first render, so an
        # exception here took the screen down before the error card could be
        # the thing that renders. Empty values are the right fallback — the
        # form then shows placeholders instead of stale data from a previous
        # session, and `build()` puts the real explanation on screen.
        try:
            self._form_values = dict(self.store.get_profile())
        except Exception:
            self._form_values = {}

    def _dialog_width(self) -> float:
        """Dialog body width that fits the screen it is actually on.

        The hardcoded 320/340 in this file were chosen against a desktop
        window. A phone is 360 dp wide and Material insets an AlertDialog by
        about 40 dp a side, so 320 was already 40 dp too wide and text ran off
        the right edge — the same failure the RIR legend had on Alex's phone.

        Delegates to `shared_ui`: every screen had its own copy of this number
        and that is precisely how one of them stayed wrong after the others
        were fixed.
        """
        return dialog_width(self.page)

    def _reload(self):
        """The "try again" of the database-down card.

        Nothing on this screen is cached — every read happens inside `build()` —
        so re-rendering *is* the retry.
        """
        self.page.data["refresh_current"]()

    def handle_back(self) -> bool:
        nav = self.page.data["navigate_to"]
        nav(0)
        return True

    # ── actions ───────────────────────────────────────────────
    def _save_form(self):
        try:
            height = float(self._form_values.get("height_cm") or 0)
        except ValueError:
            height = 0.0
        self.store.set_profile(
            name=(self._form_values.get("name") or "").strip(),
            birthdate=(self._form_values.get("birthdate") or "").strip(),
            height_cm=height,
            sex=(self._form_values.get("sex") or "").strip(),
            activity_level=(self._form_values.get("activity_level") or "moderate"),
        )
        self.page.data["refresh_current"]()

    def _open_log_weight(self):
        kg_field = ft.TextField(
            label="Peso (kg)",
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            autofocus=True,
        )
        date_field = ft.TextField(
            label="Fecha (AAAA-MM-DD)",
            value=date.today().isoformat(),
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
        )
        err = ft.Text("", size=11, color=C.danger)

        def save(_):
            try:
                kg = float((kg_field.value or "").replace(",", "."))
                if kg <= 0:
                    raise ValueError("non-positive")
            except ValueError:
                err.value = "Pon un peso válido"
                self.page.update()
                return
            dv = (date_field.value or "").strip()
            try:
                if dv:
                    date.fromisoformat(dv)
            except ValueError:
                err.value = "Formato de fecha inválido"
                self.page.update()
                return
            self.store.save_weight(kg, dv or None)
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text("Apuntar peso", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(
                    [kg_field, date_field, err],
                    spacing=10,
                    tight=True,
                ),
                # No fixed height: `err` appears and disappears, and 180 was
                # tall enough for the empty state only, so the error message
                # that explains the rejected input was itself clipped away.
                width=self._dialog_width(),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                ft.TextButton("Guardar", on_click=save, style=ft.ButtonStyle(color=C.accent)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _delete_weight(self, wid: str):  # a weigh-in is keyed by its date
        self.store.delete_weight(wid)
        self.page.data["refresh_current"]()

    # ── waist ────────────────────────────────────────────────
    def _open_log_waist(self):
        """Record the tape measurement the plan brakes on.

        This exists because nothing else captures it. The coach has a
        `registrar_medidas` tool but no command and no reminder — it fires only
        if the model happens to decide to — and `medidas` is empty, on a plan
        that is already running. A number the plan adjusts calories by cannot
        depend on an LLM remembering to ask.

        Only the waist. The other four columns of `medidas` are the coach's, and
        `save_measurement` leaves anything it is not given untouched, so saving
        here never costs him a chest or a thigh recorded at a check-in.
        """
        cm_field = ft.TextField(
            label="Cintura (cm)",
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            autofocus=True,
        )
        date_field = ft.TextField(
            label="Fecha (AAAA-MM-DD)",
            value=date.today().isoformat(),
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
        )
        err = ft.Text("", size=11, color=C.danger)

        def save(_):
            dv = (date_field.value or "").strip()
            try:
                if dv:
                    date.fromisoformat(dv)
            except ValueError:
                err.value = "Formato de fecha inválido"
                self.page.update()
                return
            try:
                self.store.save_measurement(
                    on_date=dv or None, waist=(cm_field.value or "").replace(",", ".")
                )
            except ValueError as exc:
                err.value = str(exc)
                self.page.update()
                return
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text("Apuntar cintura", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "A la altura del ombligo, relajado, a primera hora — siempre igual. "
                            "El plan recorta 150 kcal si esto sube ~1 cm.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        cm_field,
                        date_field,
                        err,
                    ],
                    spacing=10,
                    tight=True,
                ),
                width=self._dialog_width(),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                ft.TextButton("Guardar", on_click=save, style=ft.ButtonStyle(color=C.accent)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _waist_section(self) -> ft.Control:
        try:
            resumen = waist_summary(self.store.get_measurements(limit=30))
        except Exception as exc:
            return db_error_card(exc, on_retry=self._reload)

        if not resumen.known:
            cuerpo: list[ft.Control] = [
                ft.Text(
                    "Sin medición todavía. Este es el freno del plan — sin una base "
                    "no hay con qué comparar la siguiente.",
                    size=12,
                    color=C.text_secondary,
                )
            ]
        else:
            cuerpo = [
                ft.Row(
                    [
                        ft.Text(
                            f"{resumen.latest:g} cm",
                            size=22,
                            weight=ft.FontWeight.W_900,
                            color=C.text,
                        ),
                        ft.Text(
                            _antiguedad(resumen.on, resumen.days_ago or 0),
                            size=11,
                            color=C.warning if resumen.due else C.text_secondary,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                )
            ]
            if resumen.vs_baseline is None:
                cuerpo.append(
                    ft.Text(
                        "Base — con una segunda ya habrá variación.", size=11, color=C.text_muted
                    )
                )
            else:
                # Both windows, labelled. The plan states the +1 cm rule against
                # the initial measurement in one place and the previous one in
                # another; the screen shows both rather than picking.
                cuerpo.append(
                    ft.Text(
                        f"{resumen.vs_baseline:+.1f} cm vs {resumen.baseline_on} (inicio)   ·   "
                        f"{resumen.vs_previous:+.1f} cm vs {resumen.previous_on} (anterior)",
                        size=11,
                        color=C.text_secondary,
                    )
                )
                cuerpo.append(
                    ft.Text(
                        f"El plan recorta 150 kcal a +1,0 cm. El ruido de la cinta ronda ±0,5 cm, "
                        f"así que léelo en pasos de {MEASUREMENT_EVERY_DAYS} días, no día a día.",
                        size=10,
                        color=C.text_muted,
                    )
                )

        cuerpo.append(ft.Container(height=6))
        cuerpo.append(
            ft.Row(
                [
                    primary_button(
                        "Apuntar cintura" if resumen.known else "Fijar la base",
                        on_click=lambda _: self._open_log_waist(),
                        expand=True,
                    )
                ]
            )
        )
        return card(*cuerpo, padding=14)

    # ── backup / restore ─────────────────────────────────────
    def _open_backup(self, _=None):
        """Send the user to the real backup screen (view 8).

        The clipboard dialogs that used to live here only covered four of the
        twelve tables: pasting an old dump back in with wipe=True silently
        deleted every food log and user routine. A JSON with months of training
        in it does not fit in a clipboard on a phone either. DataView exports
        and imports all twelve to a file, so this is the only backup path left.
        """
        self.page.data["navigate_to"](8)

    def _toast(self, message: str):
        """El aviso corto de esta pantalla. Solo la sección del calendario lo
        usa hoy; el resto de Ajustes comunica re-renderizando el estado."""
        self.page.open(
            ft.SnackBar(
                content=ft.Text(message, size=12, color=C.text, weight=ft.FontWeight.W_700),
                bgcolor=C.bg_sunken,
            )
        )

    def _gcal_section(self) -> ft.Control:
        """Conectar la agenda: del bot en el PC, por navegador en el móvil.

        El refresh token es un secreto de verdad (SECRET_PREF_KEYS): no viaja
        en las copias, así que cada dispositivo se conecta una vez. En el PC
        basta importar el OAuth que el bot ya hizo; en el móvil el botón abre
        el navegador y un servidor de un solo uso en 127.0.0.1 recoge el
        código — el flujo estándar de app instalada de Google.
        """
        import gcal

        esta = gcal.conectado(self.store)

        def _importar(_):
            if gcal.conectar_desde_bot(self.store):
                self._toast("Calendario conectado con las credenciales del bot.")
            else:
                self._toast("No se encontró el token del bot (¿estás en el PC?).")
            self.page.data["refresh_current"]()

        def _conectar(_):
            try:
                gcal.iniciar_oauth(self.store, self.page.launch_url)
                self._toast(
                    "Se abrió el navegador: elige tu cuenta y acepta. "
                    "Al volver, toca «Comprobar conexión»."
                )
            except gcal.GcalError as exc:
                self._toast(str(exc))

        def _desconectar(_):
            gcal.desconectar(self.store)
            self._toast("Calendario desconectado de este dispositivo.")
            self.page.data["refresh_current"]()

        def _comprobar(_):
            try:
                cuantos = len(gcal.eventos(self.store, days=7))
                self._toast(f"Conectado — {cuantos} eventos en los próximos 7 días.")
            except Exception as exc:
                self._toast(f"Aún no: {exc}")
            self.page.data["refresh_current"]()

        estado = ft.Row(
            [
                ft.Icon(
                    ft.Icons.EVENT_AVAILABLE if esta else ft.Icons.EVENT_BUSY,
                    color=C.success if esta else C.text_muted,
                    size=16,
                ),
                ft.Text(
                    "Conectado — el coach ve tu agenda y puede proponer eventos"
                    if esta
                    else "Sin conectar — la agenda y los eventos del coach se activan aquí",
                    size=11,
                    color=C.text_secondary,
                    expand=True,
                ),
            ],
            spacing=6,
        )

        def _ensenar_codigo(_):
            codigo = gcal.codigo_vinculo(self.store)
            if not codigo:
                self._toast("Aquí tampoco hay credenciales — usa «Importar del bot» primero.")
                return
            dlg = ft.AlertDialog(
                bgcolor=C.bg_surface,
                title=ft.Text(
                    "Código para el móvil", size=16, weight=ft.FontWeight.W_900, color=C.text
                ),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Mándatelo al móvil (un chat contigo sirve), pégalo en "
                                "Ajustes → Calendario → «Pegar código del PC» y luego "
                                "«Conectar con Google». El código no da acceso a tu "
                                "cuenta: el permiso lo darás tú en el navegador del móvil.",
                                size=11,
                                color=C.text_secondary,
                            ),
                            ft.TextField(
                                value=codigo,
                                read_only=True,
                                multiline=True,
                                min_lines=3,
                                text_size=11,
                                border_color=C.border,
                                color=C.text,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    width=dialog_width(self.page),
                ),
                actions=[
                    ft.TextButton(
                        "Cerrar",
                        on_click=lambda _: self.page.close(dlg),
                        style=ft.ButtonStyle(color=C.accent),
                    )
                ],
            )
            self.page.open(dlg)

        def _pegar_codigo(_):
            campo = ft.TextField(
                hint_text="ifgc1:…",
                multiline=True,
                min_lines=2,
                text_size=11,
                border_color=C.border,
                color=C.text,
                hint_style=ft.TextStyle(color=C.text_muted),
            )

            def aplicar(_):
                if gcal.aplicar_codigo(self.store, campo.value or ""):
                    self.page.close(dlg)
                    self._toast("Código aplicado — ahora toca «Conectar con Google».")
                    self.page.data["refresh_current"]()
                else:
                    campo.error_text = "Ese código no es válido — cópialo entero desde el PC."
                    self.page.update()

            dlg = ft.AlertDialog(
                bgcolor=C.bg_surface,
                title=ft.Text(
                    "Pegar código del PC", size=16, weight=ft.FontWeight.W_900, color=C.text
                ),
                content=ft.Container(content=campo, width=dialog_width(self.page)),
                actions=[
                    ft.TextButton(
                        "Cancelar",
                        on_click=lambda _: self.page.close(dlg),
                        style=ft.ButtonStyle(color=C.text_secondary),
                    ),
                    ft.TextButton(
                        "Aplicar", on_click=aplicar, style=ft.ButtonStyle(color=C.accent)
                    ),
                ],
            )
            self.page.open(dlg)

        tiene_cliente = bool((self.store.get_pref(gcal.CLIENT_ID_PREF) or "").strip())
        filas_botones: list[ft.Control] = []
        if esta:
            filas_botones.append(
                ft.Row(
                    [
                        ghost_button("Comprobar conexión", on_click=_comprobar, expand=True),
                        ft.Container(width=8),
                        ghost_button("Desconectar", on_click=_desconectar, expand=True),
                    ]
                )
            )
            filas_botones.append(ft.Container(height=6))
            filas_botones.append(
                ft.Row(
                    [ghost_button("Código para el móvil", on_click=_ensenar_codigo, expand=True)]
                )
            )
        else:
            filas_botones.append(
                ft.Row(
                    [
                        ghost_button("Importar del bot (PC)", on_click=_importar, expand=True),
                        ft.Container(width=8),
                        ghost_button("Pegar código del PC", on_click=_pegar_codigo, expand=True),
                    ]
                )
            )
            filas_botones.append(ft.Container(height=6))
            filas_botones.append(
                ft.Row(
                    [
                        primary_button(
                            "Conectar con Google"
                            + ("" if tiene_cliente else " (pega el código antes)"),
                            on_click=_conectar,
                            expand=True,
                        )
                    ]
                )
            )
        return card(estado, ft.Container(height=8), *filas_botones)

    def _widget_section(self) -> list[ft.Control]:
        """La sección del widget, o nada fuera de Android.

        Devuelve una lista para poder no devolver nada: en el escritorio no hay
        pantalla de inicio a la que añadirlo, y un botón que no puede hacer
        nada es peor que la ausencia del botón.
        """
        if not widget.disponible():
            return []

        estado = ft.Text(
            "Lo de hoy en la pantalla de inicio: qué toca entrenar, tu peso y "
            "cómo vas de calorías y proteína.",
            size=11,
            color=C.text_secondary,
        )

        def _colocar(_):
            # `pedir_colocacion` solo deja la nota; quien enseña el diálogo es
            # el lanzador y quien decide es Alex. Por eso el mensaje dice que
            # «te lo va a ofrecer» y no «hecho»: prometer lo segundo y que el
            # lanzador no lo soporte sería mentir en la única frase que ve.
            if widget.pedir_colocacion():
                self._set_widget_msg("success", "Tu móvil te va a preguntar dónde ponerlo.")
            else:
                self._set_widget_msg(
                    "error",
                    "No se pudo pedir. Añádelo a mano: mantén pulsada la "
                    "pantalla de inicio → Widgets → IronFlet.",
                )
            self.page.data["refresh_current"]()

        cuerpo: list[ft.Control] = [estado, ft.Container(height=8)]
        aviso = getattr(self, "_widget_msg", None)
        if aviso:
            nivel, texto = aviso
            cuerpo.append(
                ft.Text(
                    texto,
                    size=11,
                    color=C.success if nivel == "success" else C.warning,
                )
            )
            cuerpo.append(ft.Container(height=8))
        cuerpo.append(
            ft.Row(
                [
                    # Sin `icon=`: `ghost_button` pasa sus kwargs sobrantes a
                    # `ft.Container`, que no tiene ese parámetro, y el
                    # `TypeError` se lleva la pantalla de Ajustes entera.
                    # `primary_button` sí lo acepta; este no.
                    ghost_button(
                        "Añadir a la pantalla de inicio",
                        on_click=_colocar,
                        expand=True,
                    )
                ]
            )
        )
        return [
            section_title("Widget"),
            ft.Container(height=4),
            card(*cuerpo),
            ft.Container(height=14),
        ]

    def _set_widget_msg(self, nivel: str, texto: str):
        self._widget_msg = (nivel, texto)

    # ── lo que el entrenador recuerda ────────────────────────

    def _memoria_section(self) -> ft.Control:
        """El resumen; la edición vive en un diálogo.

        Estuvo en línea, con el campo y la lista dentro de Ajustes, y en el
        móvil no valía: **cada añadido o borrado llama a `refresh_current()`,
        que reconstruye la pantalla desde arriba** y te deja a cinco arrastres
        de donde estabas. Con un hecho pasa desapercibido; rellenando seis de
        una sentada es insufrible. Un diálogo se refresca solo a sí mismo y
        deja quieto lo que hay detrás — y es lo que esta misma pantalla ya hace
        para apuntar peso y cintura.
        """
        import memoria

        try:
            hechos = memoria.leer(self.store)
        except Exception as exc:
            return db_error_card(exc, on_retry=self.page.data["refresh_current"])

        if hechos:
            resumen = ", ".join(h.texto for h in hechos[:2])
            if len(hechos) > 2:
                resumen += f" y {len(hechos) - 2} más"
            titulo = plural(len(hechos), "cosa") + " que tiene presente"
        else:
            resumen = (
                "Ni a qué hora entrenas, ni qué no comes, ni qué rodilla te molesta. "
                "Cuéntaselo una vez y no vuelve a preguntarlo."
            )
            titulo = "Todavía no sabe nada de ti"

        return card(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(titulo, size=13, weight=ft.FontWeight.W_700, color=C.text),
                                ft.Text(
                                    resumen,
                                    size=11,
                                    color=C.text_secondary,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                            tight=True,
                        ),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=C.text_muted),
                    ],
                    spacing=Space.x2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                on_click=self._open_memoria,
                ink=True,
                padding=ft.padding.symmetric(vertical=4),
                border_radius=Radius.sm,
            ),
            padding=12,
        )

    def _open_memoria(self, _=None):
        """El diálogo que edita la memoria sin mover Ajustes de sitio."""
        import memoria

        lista = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
        campo = ft.TextField(
            hint_text="Entreno a las 7:00, antes de trabajar",
            dense=True,
            expand=True,
            max_length=memoria.MAX_LARGO,
            border_color=C.border,
            color=C.text,
            text_size=12,
            on_submit=lambda _: anadir(None),
        )
        categoria = ft.Dropdown(
            value="rutina",
            dense=True,
            text_size=12,
            border_color=C.border,
            color=C.text,
            options=[ft.dropdown.Option(clave, nombre) for clave, nombre in memoria.CATEGORIAS],
        )
        aviso = ft.Text("", size=11, color=C.warning)
        fila_nueva = ft.Column([campo, categoria], spacing=8, tight=True)

        def pintar():
            """Redibuja SOLO el diálogo. Ajustes se entera al cerrarse."""
            hechos = memoria.leer(self.store)
            lista.controls = (
                [self._fila_memoria(h, pintar) for h in hechos]
                if hechos
                else [
                    ft.Container(
                        content=ft.Text(
                            "Nada todavía. Escribe algo que quieras que tenga siempre "
                            "presente — cómo es tu semana, qué no comes, qué te molesta.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        padding=ft.padding.symmetric(vertical=8),
                    )
                ]
            )
            lleno = len(hechos) >= memoria.MAX_HECHOS
            fila_nueva.visible = not lleno
            aviso.value = (
                f"Son ya {memoria.MAX_HECHOS}, el máximo. Viajan en cada pregunta que le "
                "haces y las pagas: quita alguna antes de añadir otra."
                if lleno
                else ""
            )
            self.page.update()

        def anadir(_):
            texto = (campo.value or "").strip()
            if not texto:
                return
            try:
                memoria.anadir(self.store, texto, categoria.value or "otro")
            except ValueError:
                return
            # El campo se vacía y la categoría se queda: rellenando la primera
            # vez se encadenan varios de la misma clase.
            campo.value = ""
            pintar()

        def cerrar(_=None):
            self.page.close(dlg)
            # Ahora sí: el resumen de Ajustes tiene que reflejar lo editado.
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text(
                "Lo que recuerda de ti", size=16, weight=ft.FontWeight.W_900, color=C.text
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Viaja en cada conversación, así que el entrenador no vuelve a "
                            "preguntarlo. Cuéntaselo también por el chat: te ofrecerá "
                            "guardarlo él.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        ft.Container(height=4),
                        ft.Container(content=lista, expand=True),
                        aviso,
                        fila_nueva,
                        # En una `Row`. `expand=True` reparte el eje del padre,
                        # y el de una `Column` es el vertical: suelto ahí, el
                        # botón se comía 350 px de alto del diálogo. Es el
                        # primo del `wrap=True` de la trampa 27 — el mismo
                        # parámetro queriendo decir cosas distintas según quién
                        # lo lea, y sin error por medio.
                        ft.Row([ghost_button("Añadir", on_click=anadir, expand=True)]),
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=dialog_width(self.page),
                height=dialog_height(self.page, 520),
            ),
            actions=[
                ft.TextButton("Listo", on_click=cerrar, style=ft.ButtonStyle(color=C.accent)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _: self.page.data["refresh_current"](),
        )
        pintar()
        self.page.open(dlg)

    def _fila_memoria(self, hecho, al_cambiar=None) -> ft.Control:
        """Una línea con su papelera. `al_cambiar` redibuja lo que toque —
        el diálogo cuando se edita desde él, la pantalla entera si no."""
        import memoria

        def _borrar(_):
            memoria.borrar(self.store, hecho.texto)
            (al_cambiar or self.page.data["refresh_current"])()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(hecho.texto, size=12, color=C.text),
                            muted_text(hecho.etiqueta(), size=10),
                        ],
                        spacing=1,
                        expand=True,
                        tight=True,
                    ),
                    ft.Container(
                        content=ft.Icon(ft.Icons.DELETE_OUTLINE, size=17, color=C.text_muted),
                        on_click=_borrar,
                        ink=True,
                        width=32,
                        height=32,
                        alignment=ft.alignment.center,
                        border_radius=Radius.sm,
                        tooltip="Que lo olvide",
                    ),
                ],
                spacing=Space.x2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(vertical=5),
        )

    def _backup_section(self) -> ft.Control:
        return ft.Row(
            [
                ghost_button("Copia y restauración", on_click=self._open_backup, expand=True),
            ],
            spacing=8,
        )

    # ── danger zone ──────────────────────────────────────────
    def _confirm_action(self, title_key: str, message_key: str, action_key: str, do_action) -> None:
        def confirmed(_):
            do_action()
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=C.bg_surface,
            title=ft.Text(title_key, size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                # The Text gets no width of its own: it wraps inside whatever
                # the Container turns out to be. Two nested fixed widths is how
                # the last clipping bug survived being "fixed" once.
                content=ft.Text(message_key, size=12, color=C.text_secondary),
                width=self._dialog_width(),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                ft.TextButton(action_key, on_click=confirmed, style=ft.ButtonStyle(color=C.danger)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _danger_row(self, icon, label_key: str, on_click) -> ft.Control:
        """A row that deletes something. `C.danger`, and it has to be.

        This used `C.accent_2` and looked right for a year, because in the light
        palette that token happened to be a crimson. The Symmetry palette made
        it a light blue and "Borrar todos los datos" turned friendly overnight — the
        role and the colour had never actually matched, the hue just covered for
        it. Any row that destroys data reads `danger`, whatever the theme.
        """
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=C.danger, size=18),
                    ft.Container(
                        content=ft.Text(
                            label_key, size=12, color=C.text_secondary, weight=ft.FontWeight.W_700
                        ),
                        expand=True,  # "Borrar historial de entrenos" does not fit 230
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=16),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            margin=ft.margin.only(bottom=6),
            on_click=lambda _: on_click(),
            ink=True,
        )

    # ── exercise guides (image cache) ────────────────────────
    def _open_download_dialog(self):
        st = asset_manager.status()
        total = st.total
        installed = st.complete
        status_label = ft.Text(
            "Instaladas"
            if installed
            else (f"faltan {st.missing} de {total}" if st.present else "Sin instalar  ·  ~9 MB"),
            size=11,
            color=C.accent if installed else C.text_secondary,
            weight=ft.FontWeight.W_700,
        )
        progress_bar = ft.ProgressBar(
            value=st.present / total if total else 0,
            bgcolor=C.border,
            color=C.accent,
            bar_height=6,
        )
        count_label = ft.Text(f"{st.present} / {total}", size=10, color=C.text_secondary)

        def on_progress(done: int, tot: int):
            try:
                progress_bar.value = done / tot if tot else 0
                count_label.value = f"{done} / {tot}"
                self.page.update()
            except Exception:
                pass

        async def do_download(_):
            status_label.value = "Descargando…"
            status_label.color = C.accent
            self.page.update()
            ok, err = await asset_manager.download_all(progress_cb=on_progress)
            # The frames on disk just changed, so anything already encoded from
            # the old ones is stale. Cheap to drop, and forgetting it is how a
            # repaired image keeps rendering as the broken one it replaced.
            exercise_images.clear_inline_cache()
            if err == 0:
                status_label.value = "Instaladas"
            else:
                status_label.value = f"Parcial · {ok} bien / {err} err"
            self.page.update()

        def do_clear(_):
            asset_manager.clear_cache()
            # Mandatory here, not just tidy: the files are gone but their
            # base64 would live on in the cache, so cleared images would carry
            # on rendering and "Vaciar caché" would look like it did nothing.
            exercise_images.clear_inline_cache()
            status_label.value = "Sin instalar  ·  ~9 MB"
            status_label.color = C.text_secondary
            progress_bar.value = 0
            count_label.value = f"0 / {total}"
            self.page.update()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text("Guías de ejercicios", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Las fotos e instrucciones de los ejercicios se descargan "
                            "de una base de datos pública de fitness (Unlicense). "
                            "Unos 9 MB — mejor con wifi.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        ft.Container(height=4),
                        status_label,
                        progress_bar,
                        count_label,
                        ft.Container(height=6),
                        ft.Row(
                            [
                                ghost_button("Vaciar caché", on_click=do_clear, expand=True),
                                primary_button(
                                    "Descargar",
                                    on_click=do_download,
                                    expand=True,
                                    icon=ft.Icons.CLOUD_DOWNLOAD,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
                # The height went with the width: "Partial · 12 ok / 3 err" is
                # a taller status line than "Instaladas", and 280 was measured
                # against the short one.
                width=self._dialog_width(),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _open_model_picker(self):
        """All ~350 tool-capable models, searchable, cheapest first.

        Cheapest first is not a default, it is the point: the reason to leave the
        shortlist is almost always to spend less, and 348 rows sorted by name
        would bury every cheap option under three pages of `anthropic/*`.

        Only models whose `supported_parameters` include `tools` are here.
        `openrouter.parse_models` drops the other 69 — they would look fine in
        this list and then break the coach, which cannot read one fact about
        Alex's training without tool calls, and would answer from imagination
        rather than say so.
        """
        catalogo, fallo = openrouter.models_or_empty()
        if fallo or not catalogo:
            self.page.open(
                ft.AlertDialog(
                    bgcolor=C.bg_surface,
                    title=ft.Text("Sin señal", size=16, weight=ft.FontWeight.W_900, color=C.text),
                    content=ft.Text(
                        "La lista de modelos viene de OpenRouter y este aparato no pudo conectar. "
                        "La lista corta de Ajustes sigue funcionando.",
                        size=12,
                        color=C.text_secondary,
                    ),
                )
            )
            return

        actual = agent.read_model(self.store)
        lista = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=4, expand=True)
        contador = ft.Text("", size=10, color=C.text_muted)

        def pick(modelo):
            def go(_):
                agent.save_model(self.store, modelo)
                self.page.close(dlg)
                self._reload()

            return go

        def render(query: str = ""):
            encontrados = openrouter.search(catalogo, query, limit=60)
            lista.controls = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                f"{m.id} 📷" if m.vision else m.id,
                                size=12,
                                color=C.accent if m.id == actual else C.text,
                                weight=ft.FontWeight.W_700
                                if m.id == actual
                                else ft.FontWeight.W_400,
                            ),
                            ft.Text(
                                f"{m.price_label()}   ·   {m.context:,} ctx",
                                size=10,
                                color=C.text_secondary,
                            ),
                        ],
                        spacing=1,
                        tight=True,
                    ),
                    on_click=pick(m),
                    ink=True,
                    padding=ft.padding.symmetric(horizontal=10, vertical=7),
                    bgcolor=C.accent_soft if m.id == actual else None,
                    border_radius=8,
                )
                for m in encontrados
            ]
            contador.value = f"{len(encontrados)} de {len(catalogo)} · el más barato primero"

        render()

        buscador = ft.TextField(
            # NO autofocus. With it, the soft keyboard opens with the dialog and
            # covers everything below the fourth row — a picker of 348 things
            # that shows four of them. The list is already sorted cheapest-first,
            # which is what most people came to look at; the keyboard appears
            # when he taps the box, which is when he actually wants it.
            hint_text=f"Buscar entre {len(catalogo)} modelos…",
            dense=True,
            border_color=C.border,
            color=C.text,
            on_change=lambda e: (render(e.control.value), self.page.update()),
        )

        dlg = ft.AlertDialog(
            bgcolor=C.bg_surface,
            title=ft.Text("Elegir modelo", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column([buscador, contador, lista], spacing=8, tight=False),
                width=dialog_width(self.page),
                height=dialog_height(self.page, 420),
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

    def _appearance_section(self) -> ft.Control:
        """Pick a palette. Dark is the default; daylight is one tap away.

        This exists because the default flipped. `theme.py` used to say, in as
        many words, that light was the default because the app is used in
        daylight in a gym — and that argument did not stop being true when Alex
        asked for the look of symmetry.club. So the dark theme ships as the
        default and the old one is still here, still tested, still one tap away
        rather than deleted to make the new decision look cleaner.
        """
        actual = (self.store.get_pref(THEME_PREF) or "").strip().lower()
        if actual not in PALETTES:
            actual = DEFAULT_PALETTE.name

        def elegir(nombre):
            def go(_):
                self.store.set_pref(THEME_PREF, nombre)
                # Repaint now: `apply_theme` also sets the Material ColorScheme,
                # and without it every dialog and text field keeps the old one.
                apply_theme(self.page, PALETTES[nombre])
                self.page.data["refresh_current"]()

            return go

        ETIQUETAS = {
            "symmetry": ("Oscuro", "Casi negro y azul"),
            "light": ("Luz de día", "Se lee mejor al sol"),
            "dark": ("Oscuro cálido", "El tema oscuro original"),
        }
        filas = []
        for nombre in PALETTES:
            titulo, pie = ETIQUETAS.get(nombre, (nombre.title(), ""))
            elegido = nombre == actual
            paleta = PALETTES[nombre]
            filas.append(
                ft.Container(
                    content=ft.Row(
                        [
                            # A swatch of the palette being offered, painted in
                            # its OWN colours rather than the active ones — the
                            # point of the row is to show what it looks like.
                            ft.Container(
                                width=34,
                                height=34,
                                bgcolor=paleta.bg_page,
                                border=ft.border.all(1, paleta.border_strong),
                                border_radius=Radius.md,
                                content=ft.Container(
                                    width=12,
                                    height=12,
                                    bgcolor=paleta.accent,
                                    border_radius=Radius.pill,
                                ),
                                alignment=ft.alignment.center,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        titulo, size=13, weight=ft.FontWeight.W_700, color=C.text
                                    ),
                                    ft.Text(pie, size=10, color=C.text_muted),
                                ],
                                spacing=0,
                                tight=True,
                                expand=True,
                            ),
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE_ROUNDED
                                if elegido
                                else ft.Icons.CIRCLE_OUTLINED,
                                size=18,
                                color=C.accent if elegido else C.text_muted,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_click=elegir(nombre),
                    ink=True,
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=Radius.lg,
                    bgcolor=C.accent_soft if elegido else None,
                )
            )
        return card(*filas, padding=10)

    def _coach_section(self) -> ft.Control:
        """Where Alex types the API key, once.

        The key is not in this repository, not in the APK and not in any file
        that ships. An APK is a zip: `unzip` plus `strings` recovers a compiled
        constant in seconds, so a key baked into the build would be a key
        published to anyone Alex ever sends the file to. It is typed here and
        stored in `preferencias`, in the app's own private storage, and
        `storage.SECRET_PREF_KEYS` keeps it out of every backup document.

        Once stored it is never shown again — only `mask_key()`'s last four
        characters, which is enough to tell two keys apart and not enough to be
        worth a shoulder or a screenshot.
        """
        try:
            stored = agent.read_key(self.store)
            model = agent.read_model(self.store)
        except Exception:
            stored, model = None, agent.DEFAULT_MODEL

        # The catalogue is fetched, not hardcoded, and its failure is not fatal:
        # `models_or_empty` swallows the network error and reports it separately
        # so a phone with no signal still shows the dropdown, the stored choice
        # and the last known price instead of an empty screen.
        catalogo, fallo_catalogo = openrouter.models_or_empty()
        catalogo_por_id = {m.id: m for m in catalogo}
        corta = openrouter.curated(catalogo)

        field = ft.TextField(
            label="Clave de OpenRouter" if not stored else "Cambiar la clave",
            hint_text="sk-or-v1-…",
            password=True,
            can_reveal_password=True,
            dense=True,
            expand=True,
            border_color=C.border,
            color=C.text,
            label_style=ft.TextStyle(color=C.text_secondary),
        )
        message = ft.Text("", size=11, color=C.text_secondary)

        def save(_):
            try:
                agent.save_key(self.store, field.value)
            except ValueError as exc:
                message.value = str(exc)
                message.color = C.danger
                self.page.update()
                return
            except Exception as exc:  # pragma: no cover - defensive
                message.value = f"No se pudo guardar: {exc}"
                message.color = C.danger
                self.page.update()
                return
            field.value = ""
            if not agent.looks_like_api_key(agent.read_key(self.store)):
                # A warning, not a rejection: the prefix is Anthropic's to
                # change, and refusing a valid key in a gym would be worse than
                # accepting an invalid one and saying so on the first request.
                message.value = "Guardada — aunque no empieza por sk-or-, revísala."
                message.color = C.warning
            else:
                message.value = "Guardada. El entrenador está listo."
                message.color = C.success
            self.page.update()
            self._reload()

        def forget(_):
            agent.clear_key(self.store)
            self._reload()

        rows: list[ft.Control] = []
        if stored:
            rows.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.KEY_ROUNDED, size=15, color=C.success),
                        ft.Text(
                            f"Clave guardada: {agent.mask_key(stored)}",
                            size=12,
                            color=C.text,
                            weight=ft.FontWeight.W_600,
                            expand=True,
                        ),
                        ghost_button("Olvidar", on_click=forget),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        else:
            rows.append(
                ft.Text(
                    "El entrenador necesita tu clave de OpenRouter — una sola para todos los modelos. "
                    "Pégala una vez: se guarda en el almacenamiento privado de la app, nunca en "
                    "el fichero instalado ni en ninguna copia de seguridad.",
                    size=11,
                    color=C.text_secondary,
                )
            )

        rows.append(ft.Row([field, primary_button("Guardar clave", on_click=save)], spacing=8))

        def set_model(e):
            elegido = catalogo_por_id.get(e.control.value)
            if elegido is None:
                self.store.set_pref(agent.MODEL_PREF, e.control.value)
            else:
                agent.save_model(self.store, elegido)
            self._reload()

        # SHORT LABELS, PRICE UNDERNEATH. The first version put the whole thing
        # in the option text — "Opus 5 — best, $5/$25" — and on the phone it
        # rendered as **"Opus 5 — be"**. A dropdown does not shorten a label that
        # does not fit; it cuts it. Same failure as the "Heig" height field, and
        # invisible from a desktop window. Found on a screenshot.
        opciones = [
            ft.dropdown.Option(m.id, f"{m.short} 📷" if m.vision else m.short) for m in corta
        ]
        if model not in {m.id for m in corta}:
            # Whatever he picked from the full list belongs in the dropdown too,
            # or reopening Settings silently resets him to the default.
            opciones.insert(0, ft.dropdown.Option(model, model.split("/")[-1]))

        rows.append(
            ft.Row(
                [
                    ft.Dropdown(
                        label="Modelo",
                        value=model,
                        dense=True,
                        expand=True,
                        on_change=set_model,
                        border_color=C.border,
                        color=C.text,
                        label_style=ft.TextStyle(color=C.text_secondary),
                        options=opciones,
                    ),
                    # "Ver todos", no "Los 350…". Los puntos suspensivos eran
                    # deliberados (unos 350, no exactamente 350) y en pantalla
                    # se leen como un botón al que no le cabe el texto.
                    ghost_button("Ver todos", on_click=lambda _: self._open_model_picker()),
                ],
                spacing=8,
            )
        )

        elegido = catalogo_por_id.get(model)
        precio = agent.read_price(self.store)
        if elegido is not None:
            linea = f"{elegido.name} · {elegido.price_label()} · {elegido.context:,} ctx"
        elif precio is not None:
            # Offline: the snapshot taken when it was chosen, said to be one.
            linea = f"{model} · ${precio[0]:g} / ${precio[1]:g} por M (último conocido)"
        else:
            linea = f"{model} · precio desconocido hasta que haya señal"
        if fallo_catalogo:
            linea += "  ·  sin conexión con OpenRouter"
        rows.append(ft.Text(linea, size=10, color=C.text_secondary))
        rows.append(message)
        rows.append(
            ft.Text(
                "Lo cobra OpenRouter a esa clave, por mensaje. El entrenador necesita señal; "
                "el resto de la app, no.",
                size=10,
                color=C.text_muted,
            )
        )
        return card(*rows, padding=14)

    def _guides_section(self) -> ft.Control:
        st = asset_manager.status()
        installed = st.complete
        # Three states, not two. "68 of 70" is what Alex actually had, and the
        # old label called it "~9 MB" — indistinguishable from having none.
        #
        # The empty state says the *consequence*, not the size. "~9 MB" is an
        # answer to a question nobody asked; what it needs to say is why the
        # training screen has a grey box where the photo goes, because that is
        # the only reason anyone opens this row.
        if st.complete:
            status = f"Instaladas · las {st.total}"
        elif st.present:
            status = f"faltan {st.missing} de {st.total}"
        else:
            status = "Sin descargar — las fotos no se verán"
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.CLOUD_DOWNLOAD,
                        color=C.accent if not installed else C.text_muted,
                        size=18,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    "Fotos de ejercicios",
                                    size=12,
                                    color=C.text_secondary,
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Text(status, size=10, color=C.text_secondary),
                            ],
                            spacing=1,
                            tight=True,
                        ),
                        expand=True,  # the status line is now a sentence, not a size
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=C.text_muted, size=16),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            margin=ft.margin.only(bottom=6),
            on_click=lambda _: self._open_download_dialog(),
            ink=True,
        )

    def _danger_zone(self) -> ft.Control:
        def clear_history():
            self._confirm_action(
                "Borrar historial de entrenos",
                "Borra para siempre todos los entrenos. El perfil y los pesajes se quedan.",
                "Borrar",
                self.store.clear_workouts,
            )

        def clear_all():
            def do_wipe():
                self.store.clear_all()
                # pref defaults reapply next render; reset routine to default.
                from data import set_active_routine

                set_active_routine("cambiatufisico")

            self._confirm_action(
                "Borrar todos los datos",
                "Borra perfil, pesajes, entrenos y preferencias. No se puede deshacer.",
                "Borrarlo todo",
                do_wipe,
            )

        return ft.Column(
            [
                self._danger_row(
                    ft.Icons.DELETE_SWEEP, "Borrar historial de entrenos", clear_history
                ),
                self._danger_row(ft.Icons.DELETE_FOREVER, "Borrar todos los datos", clear_all),
            ],
            spacing=0,
            tight=True,
        )

    # ── form widgets ──────────────────────────────────────────
    def _text_input(
        self,
        label: str,
        key: str,
        keyboard=ft.KeyboardType.TEXT,
        hint: str | None = None,
    ) -> ft.TextField:
        def on_change(e, k=key):
            self._form_values[k] = e.control.value

        return ft.TextField(
            label=label,
            hint_text=hint,
            value=_texto_de_campo(self._form_values.get(key)),
            keyboard_type=keyboard,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            height=52,
            # Every one of these lives inside a Row, and a TextField with no
            # `expand` takes its own preferred width instead of a share of the
            # row. Two of them side by side therefore overflowed the screen:
            # on the phone the "Altura (cm)" field was cut off mid-label, as
            # "Heig", with its input area entirely off-screen and unreachable.
            expand=True,
            on_change=on_change,
        )

    def _dropdown(self, label: str, key: str, options: list[tuple[str, str]]) -> ft.Dropdown:
        current = self._form_values.get(key, "")

        def on_change(e, k=key):
            self._form_values[k] = e.control.value

        return ft.Dropdown(
            label=label,
            value=current,
            options=[ft.dropdown.Option(key=v, text=lbl) for v, lbl in options],
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            expand=True,  # shares its Row; see the note in `_text_input`
            on_change=on_change,
        )

    # ── stats rendering ───────────────────────────────────────
    def _stat(self, label: str, value: str, sub: str = "") -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label.upper(), size=9, color=C.text_muted, weight=ft.FontWeight.W_700),
                    ft.Text(value, size=18, color=C.accent, weight=ft.FontWeight.W_900),
                    ft.Text(sub, size=10, color=C.text_secondary) if sub else ft.Container(),
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor=C.bg_page,
            border=ft.border.all(1, C.border_strong),
            border_radius=10,
            padding=10,
            expand=True,
        )

    def _metrics_row(self, profile: dict, latest_weight: float | None) -> ft.Control:
        age = age_years(profile.get("birthdate") or "")
        height = profile.get("height_cm") or 0
        sex = profile.get("sex") or ""
        activity = profile.get("activity_level") or "moderate"
        b = bmi(latest_weight, height)
        bcat = bmi_category(b)
        bmr = bmr_mifflin(latest_weight, height, age, sex)
        tdv = tdee(bmr, activity)
        prot = protein_target_range(latest_weight)
        water = water_target_l(latest_weight)

        def fmt(v, unit="", digits=0):
            if v is None:
                return "—"
            return f"{v:.{digits}f}{unit}"

        age_row = self._stat("Edad", fmt(age, "y"))
        bmi_row = self._stat("IMC", fmt(b, "", 1), bcat if bcat else "")
        bmr_row = self._stat("BMR", f"{fmt(bmr, ' kcal')}" if bmr else "—")
        tdee_row = self._stat(
            "TDEE",
            f"{fmt(tdv, ' kcal')}" if tdv else "—",
            {
                "sedentary": "sedentario",
                "light": "ligero",
                "moderate": "moderado",
                "active": "activo",
                "very_active": "muy activo",
            }.get(activity, activity),
        )
        protein_txt = f"{prot[0]:g}–{prot[1]:g} g" if prot else "—"
        prot_row = self._stat("Proteína", protein_txt, "1.6–2.2 g/kg")
        water_row = self._stat("Agua", f"{fmt(water, ' L', 1)}" if water else "—", "~35 ml/kg")

        return ft.Column(
            [
                ft.Row([age_row, bmi_row], spacing=8),
                ft.Row([bmr_row, tdee_row], spacing=8),
                ft.Row([prot_row, water_row], spacing=8),
            ],
            spacing=8,
            tight=True,
        )

    #: Shortest span the weekly rate is reported over. Under two weeks the
    #: number is mostly water: a 1 kg swing across four days reads as
    #: "-1.8 kg/week", which would have Alex cutting calories over a salty meal.
    MIN_TREND_DAYS = 14

    def _trend(self, entries: list[dict]) -> tuple[float | None, float | None]:
        """(7-day average now, kg per week) — either may be None.

        The body of this moved to `analytics.weight_trend`. It was the only
        implementation of the number the plan steers by, and it was a *private
        method on a view*: the Home screen could not import it, so the day panel
        would have made a third copy alongside the coach's. Metrics live in
        `analytics.py` (see CLAUDE.md); this stays as the name this file already
        calls in two places.
        """
        return weight_trend(entries, days=7, min_days=self.MIN_TREND_DAYS)

    def _trend_chips(self, entries: list[dict]) -> list[ft.Control]:
        media, ritmo = self._trend(entries)
        if media is None:
            return []
        chips: list[ft.Control] = [self._stat("MEDIA 7 DÍAS", f"{media:.1f} kg")]
        if ritmo is None:
            chips.append(self._stat("POR SEMANA", "—", f"a los {self.MIN_TREND_DAYS} días"))
        else:
            # No colour: whether losing is good depends on the block, and this
            # app is not the place that decides. The sign is the information.
            chips.append(self._stat("POR SEMANA", f"{ritmo:+.2f} kg", "media de 7 días"))
        return chips

    def _weight_section(self) -> ft.Control:
        entries = self.store.get_weights()
        latest = entries[-1]["kg"] if entries else None
        kgs = [e["kg"] for e in entries]
        labels = [e["date"][5:] for e in entries]

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            "Peso actual",
                            size=11,
                            color=C.text_muted,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            f"{latest:g} kg" if latest else "—",
                            size=24,
                            color=C.text,
                            weight=ft.FontWeight.W_900,
                        ),
                    ],
                    spacing=2,
                    tight=True,
                    expand=True,
                ),
                primary_button(
                    "Apuntar peso", icon=ft.Icons.ADD, on_click=lambda _: self._open_log_weight()
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        trend_chips = self._trend_chips(entries)
        trend_row = [ft.Container(height=8), ft.Row(trend_chips, spacing=8)] if trend_chips else []

        # Una línea, no barras: el peso es una serie en el tiempo y siete
        # barras sueltas esconden justo la tendencia que se mira. Y encima, de
        # puntos, la media móvil de 7 días — el peso de un día concreto se
        # mueve un kilo con la sal y la hora a la que te pesaste, varias veces
        # los ±0,3 kg/semana por los que se guía el plan, así que decidir
        # sobre el dato suelto es decidir sobre ruido.
        #
        # `baseline="auto"` (el defecto de `line_chart`): el peso vive en una
        # franja de dos kilos lejos del cero, y en un eje desde cero 2,2 kg de
        # cambio se dibujaban como tres píxeles de ciento diez.
        media = [p.get("kg") for p in moving_average(entries, days=7)] if entries else []
        grafica = (
            line_chart(kgs, labels, color=C.accent, height=130, trend=media or None)
            if entries
            else None
        )
        nota = axis_note(grafica) if grafica is not None else None

        chart = ft.Container(
            content=ft.Column(
                [grafica, ft.Text(nota, size=9, color=C.text_muted, italic=True)]
                if nota
                else [grafica],
                spacing=4,
                tight=True,
            )
            if entries
            else ft.Text("Sin pesajes todavía", size=11, color=C.text_muted, italic=True),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=12,
            padding=12,
        )

        history_rows = []
        for e in reversed(entries[-10:]):
            history_rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    e["date"],
                                    size=11,
                                    color=C.text_secondary,
                                    weight=ft.FontWeight.W_700,
                                ),
                                width=110,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    f"{e['kg']:g} kg",
                                    size=13,
                                    color=C.text,
                                    weight=ft.FontWeight.W_700,
                                ),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.DELETE_OUTLINE, color=C.text_muted, size=16
                                ),
                                on_click=lambda _, wid=e["id"]: self._delete_weight(wid),
                                ink=True,
                                padding=6,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=C.bg_surface,
                    border=ft.border.all(1, C.border),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    margin=ft.margin.only(bottom=4),
                )
            )

        # A heading with nothing under it reads as a screen that failed to
        # load. With no weigh-ins there is no history to title, so the title
        # goes too — the "Sin pesajes todavía" chip above already says it.
        history_block = (
            [
                ft.Container(height=10),
                section_title("Historial"),
                ft.Container(height=6),
                *history_rows,
            ]
            if history_rows
            else []
        )

        return ft.Column(
            [
                header,
                *trend_row,
                ft.Container(height=10),
                chart,
                *history_block,
            ],
            spacing=0,
            tight=True,
        )

    # ── main build ────────────────────────────────────────────
    def build(self) -> ft.Control:
        """Render, or say why it cannot.

        Every read on this screen goes to the shared database, and the bot in
        ../agente/ writes to the same one — a restart, a lock or a stopped
        container is a normal Tuesday here, not an exotic failure. Unguarded,
        the exception came straight out of `build()` and Settings rendered as
        nothing at all: in a gym that is indistinguishable from a crash, and it
        says none of the reassuring part — the data is in Postgres, it is not
        lost, this phone just cannot reach it right now.

        The guard wraps the **whole** render, not the first two reads. The
        weight section runs its own query further down, so a narrower try would
        have left exactly one path to the blank screen still open.
        """
        try:
            return self._build_screen()
        except Exception as exc:
            return db_error_screen("Ajustes", exc, on_retry=self._reload)

    def _build_screen(self) -> ft.Control:
        profile = self.store.get_profile()
        latest_weight = self.store.get_latest_weight()

        sex_options = [
            ("M", "Hombre"),
            ("F", "Mujer"),
            ("", "Prefiero no decirlo"),
        ]
        etiquetas_actividad = {
            "sedentary": "Sedentario",
            "light": "Ligero",
            "moderate": "Moderado",
            "active": "Activo",
            "very_active": "Muy activo",
        }
        activity_options = [(k, etiquetas_actividad.get(k, k)) for k in ACTIVITY_KEYS]

        name_field = self._text_input("Nombre", "name")
        # El formato va de `hint_text`, no en el label. Este campo ocupa media
        # fila, y "Nacimiento (AAAA-MM-DD)" no cabe en ese ancho: el label
        # flotante envolvía a dos líneas y la primera se pintaba ENCIMA del
        # borde inferior del campo Nombre, que queda justo arriba. El formato
        # solo hace falta mientras el campo está vacío, que es exactamente
        # cuando se ve el hint.
        dob_field = self._text_input(
            "Nacimiento",
            "birthdate",
            hint="AAAA-MM-DD",
        )
        height_field = self._text_input(
            "Altura (cm)",
            "height_cm",
            keyboard=ft.KeyboardType.NUMBER,
        )
        sex_field = self._dropdown("Sexo", "sex", sex_options)
        activity_field = self._dropdown("Nivel de actividad", "activity_level", activity_options)

        form = card(
            ft.Row([name_field], spacing=8),
            ft.Row([dob_field, height_field], spacing=8),
            ft.Row([sex_field, activity_field], spacing=8),
            ft.Container(height=6),
            ft.Row(
                [
                    primary_button(
                        "Guardar perfil", on_click=lambda _: self._save_form(), expand=True
                    )
                ],
            ),
            padding=14,
        )

        header = ft.Row(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text("Inicio", color=C.accent, size=12, weight=ft.FontWeight.W_700),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=lambda _: self.handle_back(),
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text("Ajustes", size=18, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(width=60),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Column(
            [
                header,
                ft.Container(height=10),
                section_title("Tus datos"),
                ft.Container(height=4),
                form,
                ft.Container(height=14),
                section_title("Métricas derivadas"),
                ft.Container(height=4),
                self._metrics_row(profile, latest_weight),
                ft.Container(height=14),
                section_title("Peso"),
                ft.Container(height=4),
                self._weight_section(),
                ft.Container(height=14),
                section_title("Apariencia"),
                ft.Container(height=4),
                self._appearance_section(),
                ft.Container(height=14),
                section_title("Cintura"),
                ft.Container(height=4),
                self._waist_section(),
                ft.Container(height=14),
                section_title("Entrenador"),
                ft.Container(height=4),
                self._coach_section(),
                ft.Container(height=14),
                section_title("Lo que recuerda de ti"),
                ft.Container(height=4),
                self._memoria_section(),
                ft.Container(height=14),
                section_title("Calendario de Google"),
                ft.Container(height=4),
                self._gcal_section(),
                ft.Container(height=14),
                *self._widget_section(),
                section_title("Copia de seguridad"),
                ft.Container(height=4),
                self._backup_section(),
                ft.Container(height=14),
                section_title("Datos"),
                ft.Container(height=4),
                self._guides_section(),
                self._danger_zone(),
                ft.Container(height=20),
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )
