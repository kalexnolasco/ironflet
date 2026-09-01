"""Browse: filterable catalog of all exercises with details on tap."""

from __future__ import annotations

import contextlib

import flet as ft

from data import EXERCISE_CATALOG, MUSCLE_GROUPS
from exercise_details import details_for
from exercise_images import image_props
from storage import Storage
from theme import C
from views.exercise_dialog import open_exercise_detail
from views.shared_ui import plural


class BrowseView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected_group: str | None = None  # None = all
        #: Lo escrito en el buscador. Con 875 ejercicios, es la vía principal
        #: para llegar a uno; los chips solo acotan la familia.
        self.query: str = ""

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        if self.selected_group is not None:
            self.selected_group = None
            self.page.data["refresh_current"]()
            return True
        if self.query:
            self.query = ""
            self.page.data["refresh_current"]()
            return True
        return False

    def _back_to_home(self, _=None):
        # Browse is not a bar tab any more: it is entered from Home's
        # "Exercises" button, so without this header the only way out was Esc —
        # a key the phone browser does not have.
        self.page.data["navigate_to"](0)

    def _set_group(self, group: str | None):
        self.selected_group = group
        self.page.data["refresh_current"]()

    def _group_chip(self, group: str | None, label: str) -> ft.Container:
        active = self.selected_group == group
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_700,
                color=C.accent if active else C.text_secondary,
            ),
            bgcolor=C.accent_soft if active else C.bg_surface,
            border=ft.border.all(1, C.accent if active else C.border),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=lambda _, g=group: self._set_group(g),
            ink=True,
        )

    def _pedir_miniaturas(self, nombres: list[str]):
        """Baja las miniaturas de lo que hay en pantalla, sin bloquear.

        Solo lo visible — sesenta filas son ~600 KB. Bajar las 875 de golpe
        para enseñar sesenta sería gastar la conexión de alguien que está
        mirando ejercicios en el metro.
        """
        import asset_manager
        import catalogo

        faltan = [
            s
            for s in {catalogo.slug_de(n) for n in nombres}
            if s and asset_manager.thumb_path(s) is None
        ]
        if not faltan:
            return

        async def _bajar():
            if await asset_manager.descargar_miniaturas(faltan):
                self.page.data["refresh_current"]()

        with contextlib.suppress(Exception):
            self.page.run_task(_bajar)

    def _exercise_row(self, ex_name: str) -> ft.Control:
        # `image_props`, not `image_for`: on the phone an assets-relative URL
        # resolves to nothing and the thumbnail is a silent grey square. See
        # the delivery note in exercise_images.py.
        thumb_props = image_props(ex_name, thumb=True)
        has_detail = details_for(ex_name) is not None

        thumb: ft.Control
        if thumb_props:
            thumb = ft.Container(
                content=ft.Image(
                    **thumb_props,
                    fit=ft.ImageFit.COVER,
                    width=44,
                    height=44,
                    # DECODE SMALL. The source frames are 850×567 photos, and
                    # `width`/`height` only scale the drawing — without these
                    # each 44 px thumbnail still decodes to a full 1.9 MB
                    # bitmap. This screen lists ~100 exercises, which is about
                    # 180 MB of bitmaps and an out-of-memory kill on a phone.
                    # 2× the display size covers a 2x-density screen.
                    cache_width=88,
                    cache_height=88,
                    # A frame that fails to decode falls back to the same icon
                    # the no-image case uses, instead of an empty square that
                    # reads as a missing exercise.
                    error_content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=20),
                ),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            thumb = ft.Container(
                content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=20),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                alignment=ft.alignment.center,
            )

        name_widget = ft.Container(
            content=ft.Text(
                ex_name,
                size=12,
                color=C.text,
                weight=ft.FontWeight.W_500,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            # `expand`, not a fixed width: a long name on a narrow phone was
            # being clipped by a number chosen against a wider screen.
            expand=True,
            alignment=ft.alignment.center_left,
        )

        trailing = (
            ft.Icon(ft.Icons.INFO_OUTLINE, color=C.accent, size=16)
            if has_detail
            else ft.Container(width=16)
        )

        return ft.Container(
            content=ft.Row(
                [thumb, name_widget, trailing],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=10,
            margin=ft.margin.only(bottom=6),
            on_click=(lambda _, k=ex_name: open_exercise_detail(self.page, k))
            if has_detail
            else None,
            ink=has_detail,
        )

    #: Cuántos se pintan de una vez. Con 875 en el catálogo, construirlos
    #: todos es una pantalla que tarda segundos en aparecer y se lleva la
    #: memoria por delante; y nadie recorre 875 filas con el pulgar. Por eso
    #: hay buscador: es la forma de llegar al 876.
    MAX_FILAS = 60

    def _exercises_for_selected(self) -> list[str]:
        """Lo que se pinta: el catálogo grande, buscado y acotado.

        Antes eran los 67 nombres escritos a mano de `EXERCISE_CATALOG`. El
        catálogo grande los incluye —los marca como «de casa» y los pone
        primero— y trae otros 808 encima.
        """
        import catalogo

        encontrados = catalogo.buscar(self.query, self.selected_group or "", limite=self.MAX_FILAS)
        if encontrados:
            return [e.nombre for e in encontrados]

        # Sin catálogo grande (fichero perdido), los de siempre. Degradar es
        # correcto; una pantalla vacía porque falta un JSON, no.
        if self.selected_group is None:
            vistos: set[str] = set()
            ordenados: list[str] = []
            for grupo in MUSCLE_GROUPS:
                for ex in EXERCISE_CATALOG[grupo]:
                    if ex not in vistos:
                        vistos.add(ex)
                        ordenados.append(ex)
            return ordenados
        return EXERCISE_CATALOG.get(self.selected_group, [])

    def build(self) -> ft.Control:
        chips = [self._group_chip(None, "Todos")]
        chips += [self._group_chip(g, g) for g in MUSCLE_GROUPS]

        exercises = self._exercises_for_selected()
        count = len(exercises)
        self._pedir_miniaturas(exercises)

        def _buscar(e):
            self.query = e.control.value or ""
            self.page.data["refresh_current"]()

        campo = ft.TextField(
            value=self.query,
            hint_text="Busca entre 875: curl, press, plancha…",
            dense=True,
            prefix_icon=ft.Icons.SEARCH,
            border_color=C.border,
            color=C.text,
            text_size=12,
            on_submit=_buscar,
            on_blur=_buscar,
        )

        return ft.Column(
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
                    on_click=self._back_to_home,
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text("Ejercicios", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Text("Toca un ejercicio para ver el detalle", size=11, color=C.text_secondary),
                ft.Container(height=8),
                campo,
                ft.Container(height=8),
                ft.Row(chips, spacing=6, wrap=True, run_spacing=6),
                ft.Container(height=10),
                ft.Text(
                    # «60 ejercicios» a secas mentiría por omisión cuando hay
                    # 875 detrás y solo caben los primeros.
                    f"{plural(count, 'ejercicio')}, los primeros"
                    if count >= self.MAX_FILAS
                    else plural(count, "ejercicio"),
                    size=11,
                    color=C.text_secondary,
                    weight=ft.FontWeight.W_700,
                ),
                ft.Container(height=6),
                *[self._exercise_row(ex) for ex in exercises],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )
