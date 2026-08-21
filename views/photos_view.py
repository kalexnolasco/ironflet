"""Galería de fotos de progreso, con comparador A/B sobre datos medidos.

Tres pantallas en una vista (el patrón del repo: estado en la instancia,
`refresh_current()` para moverse, `handle_back()` desandando un nivel):

* **rejilla** — miniaturas por fecha, la más nueva primero;
* **detalle** — una foto a tamaño de pantalla con sus medidas cercanas,
  su nota y el borrado;
* **comparar** — dos fotos lado a lado y, debajo, la diferencia REAL de peso
  y cintura entre sus fechas. Esa resta es toda la "detección de mejoras"
  que unos datos locales pueden afirmar sin inventar; la opinión con ojos la
  da el coach, que puede recibir estas mismas fotos (agent_view).

Las miniaturas llevan `cache_width` SIEMPRE (trampa 15: una rejilla de fotos
de cámara sin decode-small es un out-of-memory en el móvil). Las fotos ya
llegan comprimidas a ≤1600 px por `fotos.guardar`, pero 60 de esas también
son demasiado bitmap para una rejilla.
"""

from __future__ import annotations

from datetime import date

import flet as ft

import fotos
from theme import C, Radius, Space, card, ghost_button, muted_text, primary_button, section_title
from views.shared_ui import db_error_screen

#: Columnas de la rejilla. Tres a 420 px deja miniaturas de ~120 px — se ve
#: la silueta, que es lo que una foto de progreso tiene que enseñar.
_COLUMNAS = 3
_THUMB_PX = 132


class PhotosView:
    def __init__(self, page: ft.Page, store):
        self.page = page
        self.store = store
        #: "grid" | "detail" | "compare"
        self.mode = "grid"
        self.selected: str | None = None  # fecha ISO en detalle
        #: Selección del comparador, en orden de toque. Máximo dos.
        self.compare: list[str] = []
        self.picking_compare = False
        self._picker: ft.FilePicker | None = None
        self._error: str = ""

    # ── ciclo de vida ────────────────────────────────────────

    def on_show(self):
        self._error = ""

    def handle_back(self) -> bool:
        if self.mode in ("detail", "compare"):
            self.mode = "grid"
            self.selected = None
            self.page.data["refresh_current"]()
            return True
        if self.picking_compare:
            self.picking_compare = False
            self.compare = []
            self.page.data["refresh_current"]()
            return True
        return False

    # ── añadir / cambiar la foto de un día ───────────────────

    def _ensure_picker(self) -> ft.FilePicker:
        """El FilePicker vive en `page.overlay`, y solo uno.

        Se crea perezoso porque `build()` puede correr antes de que la página
        esté lista para overlays, y se re-usa porque cada `append` duplicado
        es un control fantasma más que Flet tiene que serializar.
        """
        if self._picker is None or self._picker not in self.page.overlay:
            self._picker = ft.FilePicker(on_result=self._picked)
            self.page.overlay.append(self._picker)
            self.page.update()
        return self._picker

    def pick_today(self, _=None):
        """Elegir imagen para HOY desde la galería del sistema.

        El Photo Picker de Android no dispara la cámara: la foto se hace con
        la app de cámara y aquí se elige. Es un paso más, pero no requiere
        permiso de cámara ni un plugin nuevo en la plantilla forkeada.
        """
        self._ensure_picker().pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.IMAGE,
            dialog_title="Foto de progreso de hoy",
        )

    def _picked(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        ruta = e.files[0].path
        if not ruta:
            # Modo web: el navegador no da ruta local. Este flujo es del
            # móvil/escritorio; en web la galería es de solo lectura.
            self._error = "Este navegador no da acceso al archivo — usa la app."
            self.page.data["refresh_current"]()
            return
        try:
            fotos.guardar(self.store, ruta)
            self._error = ""
        except Exception as exc:
            self._error = f"No se pudo guardar la foto: {exc}"
        self.mode = "grid"
        self.page.data["refresh_current"]()

    # ── acciones ─────────────────────────────────────────────

    def _open_detail(self, fecha: str):
        if self.picking_compare:
            if fecha in self.compare:
                self.compare.remove(fecha)
            elif len(self.compare) < 2:
                self.compare.append(fecha)
            if len(self.compare) == 2:
                self.mode = "compare"
                self.picking_compare = False
        else:
            self.mode = "detail"
            self.selected = fecha
        self.page.data["refresh_current"]()

    def _delete(self, fecha: str):
        def confirmar(_):
            fotos.borrar(self.store, fecha)
            self.page.close(dlg)
            self.mode = "grid"
            self.selected = None
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=C.bg_surface,
            title=ft.Text("¿Borrar esta foto?", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Text(
                f"La foto del {fecha} se borra del móvil. No hay deshacer.",
                size=12,
                color=C.text_secondary,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                ft.TextButton("Borrar", on_click=confirmar, style=ft.ButtonStyle(color=C.danger)),
            ],
        )
        self.page.open(dlg)

    # ── piezas ───────────────────────────────────────────────

    def _thumb(self, fila: dict) -> ft.Control:
        fecha = fila["date"]
        marcada = fecha in self.compare
        if fila["path"]:
            imagen: ft.Control = ft.Image(
                src=fila["path"],
                fit=ft.ImageFit.COVER,
                width=_THUMB_PX,
                height=_THUMB_PX,
                cache_width=_THUMB_PX * 2,
                border_radius=Radius.sm,
            )
        else:
            # La fila existe y el JPEG no (copia restaurada sin su zip):
            # decirlo en la propia celda es lo que evita "la galería borró
            # mis fotos" cuando lo que falta es importar el zip.
            imagen = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, color=C.text_muted, size=22),
                        ft.Text("falta el archivo", size=8, color=C.text_muted),
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                width=_THUMB_PX,
                height=_THUMB_PX,
                bgcolor=C.bg_sunken,
                border_radius=Radius.sm,
            )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Stack(
                        [
                            imagen,
                            *(
                                [
                                    ft.Container(
                                        content=ft.Icon(
                                            ft.Icons.CHECK_CIRCLE, color=C.accent, size=20
                                        ),
                                        alignment=ft.alignment.top_right,
                                        padding=4,
                                    )
                                ]
                                if marcada
                                else []
                            ),
                        ]
                    ),
                    ft.Text(fecha, size=9, color=C.text_secondary),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            on_click=lambda _, f=fecha: self._open_detail(f),
            ink=True,
            border=ft.border.all(2, C.accent) if marcada else None,
            border_radius=Radius.sm,
            padding=2,
        )

    def _medidas_linea(self, fecha: str) -> str:
        m = fotos.medidas_para(self.store, fecha)
        partes = []
        if "kg" in m:
            partes.append(f"{m['kg']:g} kg ({m['kg_date']})")
        if "waist" in m:
            partes.append(f"cintura {m['waist']:g} cm ({m['waist_date']})")
        return " · ".join(partes)

    # ── pantallas ────────────────────────────────────────────

    def _grid(self, filas: list[dict]) -> ft.Control:
        celdas = [self._thumb(f) for f in filas]
        rejilla = ft.GridView(
            controls=celdas,
            runs_count=_COLUMNAS,
            max_extent=_THUMB_PX + 22,
            child_aspect_ratio=0.82,
            spacing=6,
            run_spacing=6,
            expand=True,
        )
        hoy = date.today().isoformat()
        hay_de_hoy = any(f["date"] == hoy for f in filas)
        cab_comparar = (
            f"Toca {2 - len(self.compare)} foto(s) para comparar"
            if self.picking_compare
            else "Comparar dos fechas"
        )

        def alterna_comparar(_):
            self.picking_compare = not self.picking_compare
            self.compare = []
            self.page.data["refresh_current"]()

        cuerpo: list[ft.Control] = [
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(
                            "Inicio", color=C.accent, size=12, weight=ft.FontWeight.W_700
                        ),
                        on_click=lambda _: self.page.data["navigate_to"](0),
                        ink=True,
                        padding=6,
                    ),
                    ft.Text(
                        "Fotos de progreso",
                        size=20,
                        weight=ft.FontWeight.W_900,
                        color=C.text,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(width=52),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=Space.x1),
            # En Row, no sueltos: un botón con expand directamente en la Column
            # expandida se estira en VERTICAL (visto en el emulador como dos
            # óvalos a media pantalla). La Row lo acota a su altura natural.
            ft.Row(
                [
                    primary_button(
                        "Cambiar la foto de hoy" if hay_de_hoy else "Añadir la foto de hoy",
                        icon=ft.Icons.ADD_A_PHOTO,
                        on_click=self.pick_today,
                        expand=True,
                    )
                ]
            ),
            ft.Container(height=Space.x1),
            ft.Row(
                [
                    ghost_button(
                        "Salir de la comparación" if self.picking_compare else cab_comparar,
                        on_click=alterna_comparar,
                        expand=True,
                    )
                ]
            ),
        ]
        if self.picking_compare:
            cuerpo.append(muted_text(cab_comparar))
        if self._error:
            cuerpo.append(ft.Text(self._error, size=11, color=C.danger))
        if not filas:
            cuerpo.append(ft.Container(height=Space.x4))
            cuerpo.append(
                card(
                    ft.Text(
                        "Aún no hay fotos. Hazte la primera hoy: misma hora, misma "
                        "luz, misma pose — dentro de un mes la comparación se hace sola.",
                        size=12,
                        color=C.text_secondary,
                    )
                )
            )
        else:
            cuerpo.append(ft.Container(height=Space.x1))
            cuerpo.append(rejilla)
        return ft.Column(cuerpo, spacing=0, expand=True)

    def _detail(self) -> ft.Control:
        fila = fotos.para_fecha(self.store, self.selected) if self.selected else None
        if fila is None:
            self.mode = "grid"
            return self._grid(fotos.listar(self.store))
        medidas = self._medidas_linea(fila["date"])
        cuerpo: list[ft.Control] = [
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(
                            "Fotos", color=C.accent, size=12, weight=ft.FontWeight.W_700
                        ),
                        on_click=lambda _: self.handle_back() and self.page.update(),
                        ink=True,
                        padding=6,
                    ),
                    ft.Text(
                        fila["date"],
                        size=18,
                        weight=ft.FontWeight.W_900,
                        color=C.text,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        icon_color=C.danger,
                        tooltip="Borrar esta foto",
                        on_click=lambda _, f=fila["date"]: self._delete(f),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]
        if fila["path"]:
            cuerpo.append(
                ft.Image(
                    src=fila["path"],
                    fit=ft.ImageFit.CONTAIN,
                    width=float("inf"),
                    cache_width=1200,
                    border_radius=Radius.md,
                )
            )
        else:
            cuerpo.append(card(muted_text("El archivo de esta foto no está en este dispositivo.")))
        if medidas:
            cuerpo.append(ft.Container(height=Space.x1))
            cuerpo.append(card(ft.Text(f"Ese día: {medidas}", size=12, color=C.text_secondary)))
        if fila.get("note"):
            cuerpo.append(ft.Container(height=Space.x1))
            cuerpo.append(card(ft.Text(fila["note"], size=12, color=C.text)))
        return ft.Column(cuerpo, spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def _compare(self) -> ft.Control:
        a, b = sorted(self.compare)  # cronológico: antes a la izquierda
        fa = fotos.para_fecha(self.store, a)
        fb = fotos.para_fecha(self.store, b)
        if not fa or not fb:
            self.mode = "grid"
            self.compare = []
            return self._grid(fotos.listar(self.store))

        def _media_foto(f: dict) -> ft.Control:
            if f["path"]:
                return ft.Image(
                    src=f["path"],
                    fit=ft.ImageFit.COVER,
                    expand=True,
                    height=380,
                    cache_width=800,
                    border_radius=Radius.sm,
                )
            return ft.Container(
                content=muted_text("falta el archivo"),
                expand=True,
                height=380,
                bgcolor=C.bg_sunken,
                alignment=ft.alignment.center,
            )

        ma = fotos.medidas_para(self.store, a)
        mb = fotos.medidas_para(self.store, b)
        dias = (date.fromisoformat(b) - date.fromisoformat(a)).days
        lineas: list[str] = [f"{dias} días entre las dos fotos"]
        if "kg" in ma and "kg" in mb:
            delta = mb["kg"] - ma["kg"]
            lineas.append(f"Peso: {ma['kg']:g} → {mb['kg']:g} kg ({delta:+.1f} kg)")
        if "waist" in ma and "waist" in mb:
            delta = mb["waist"] - ma["waist"]
            lineas.append(f"Cintura: {ma['waist']:g} → {mb['waist']:g} cm ({delta:+.1f} cm)")
        if len(lineas) == 1:
            lineas.append(
                "Sin peso ni cintura cerca de ambas fechas — los números salen al medirte."
            )

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(
                                "Fotos", color=C.accent, size=12, weight=ft.FontWeight.W_700
                            ),
                            on_click=lambda _: self.handle_back() and self.page.update(),
                            ink=True,
                            padding=6,
                        ),
                        ft.Text(
                            "Comparación",
                            size=18,
                            weight=ft.FontWeight.W_900,
                            color=C.text,
                            expand=True,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(width=52),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=Space.x1),
                ft.Row(
                    [_media_foto(fa), _media_foto(fb)],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    [
                        ft.Text(a, size=11, color=C.text_secondary, expand=True),
                        ft.Text(b, size=11, color=C.text_secondary),
                    ]
                ),
                ft.Container(height=Space.x1),
                card(
                    section_title("Lo medido entre medias"),
                    *[ft.Text(t, size=13, color=C.text) for t in lineas],
                ),
            ],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # ── build ────────────────────────────────────────────────

    def build(self) -> ft.Control:
        try:
            if self.mode == "detail":
                return self._detail()
            if self.mode == "compare" and len(self.compare) == 2:
                return self._compare()
            return self._grid(fotos.listar(self.store))
        except Exception as exc:
            return db_error_screen("Fotos de progreso", exc, on_retry=lambda: None)
