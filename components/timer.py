"""Timer de descanso (async, sin threading)."""

from __future__ import annotations

import asyncio

import flet as ft

ACCENT = "#FF6B35"
ACCENT2 = "#FF3366"
BORDER = "#1a1a1d"


class RestTimer:
    def __init__(self, page: ft.Page):
        self.page = page
        self.seconds = 0
        self.running = False
        self.total = 0
        self._tick_id = 0

        self.display = ft.Text("REST", size=14, weight=ft.FontWeight.W_800, color=ACCENT)
        self.ring = ft.ProgressRing(
            width=56,
            height=56,
            stroke_width=4,
            color=ACCENT,
            bgcolor=BORDER,
            value=0,
        )
        self.stop_btn = ft.TextButton(
            "Stop",
            on_click=lambda _: self.stop(),
            style=ft.ButtonStyle(color=ACCENT2),
            visible=False,
        )

    def start(self, secs: int):
        self.total = secs
        self.seconds = secs
        self.running = True
        self.ring.value = 0
        self.display.value = f"{secs // 60}:{secs % 60:02d}"
        self.stop_btn.visible = True
        self._tick_id += 1
        tick_id = self._tick_id
        self.page.update()
        self.page.run_task(self._tick_loop, tick_id)

    def stop(self):
        self.running = False
        self.seconds = 0
        self.display.value = "REST"
        self.ring.value = 0
        self.stop_btn.visible = False
        self.page.update()

    async def _tick_loop(self, tick_id: int):
        while self.running and self.seconds > 0 and tick_id == self._tick_id:
            await asyncio.sleep(1)
            if tick_id != self._tick_id or not self.running:
                return
            self.seconds -= 1
            m, s = divmod(max(self.seconds, 0), 60)
            self.display.value = f"{m}:{s:02d}"
            self.ring.value = (self.total - self.seconds) / self.total if self.total else 0
            self.page.update()
        if tick_id == self._tick_id and self.seconds <= 0 and self.running:
            self.running = False
            self.display.value = "GO!"
            self.ring.value = 1
            self.stop_btn.visible = False
            self.page.update()

    def _preset(self, label: str, secs: int) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_700, color="#dddddd"),
            bgcolor="#252528",
            border=ft.border.all(1, "#242428"),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            on_click=lambda _, s=secs: self.start(s),
        )

    def build(self) -> ft.Control:
        return ft.Row(
            [
                ft.Stack(
                    [
                        self.ring,
                        ft.Container(
                            self.display,
                            alignment=ft.alignment.center,
                            width=56,
                            height=56,
                        ),
                    ],
                    width=56,
                    height=56,
                ),
                ft.Row(
                    [
                        self._preset("1m", 60),
                        self._preset("1:30", 90),
                        self._preset("2m", 120),
                        self._preset("3m", 180),
                        self.stop_btn,
                    ],
                    spacing=4,
                    wrap=True,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
