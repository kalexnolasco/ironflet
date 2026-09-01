"""The coach screen: a conversation, and a card he has to tap before anything is written.

The whole safety story of this feature is in `agent.py` — the model has no tool
that touches the database, so the worst a bad turn can do is put a wrong card on
this screen. What this file owns is making that card **legible**: the numbers
big, the date spelled out, the word "Save" on the only control that writes.

Two failure modes this layout is shaped around:

* **A card that reads as a receipt.** If it says "Bench Press 60×8 ✓" Alex taps
  Save without reading, which throws away the entire point of the confirmation
  step. So the card leads with the sets, in the largest type on the screen, and
  the button says what it is about to do rather than "OK".
* **A card that scrolls away.** It is pinned under the composer instead of
  living in the message list, because a proposal that has scrolled off the top
  is one he answers by not answering.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date

import flet as ft

import agent
from storage import Storage
from theme import C, card, ghost_button, primary_button
from views.shared_ui import db_error_screen, plural

#: `**negrita**`, `*cursiva*`, y una almohadilla de encabezado al principio de
#: línea. Nada más: el resto del markdown (tablas, enlaces, bloques de código)
#: no aparece en una respuesta de tres frases sobre press banca, y un
#: renderizador completo aquí sería más superficie de la que este chat necesita.
_MD = re.compile(r"\*\*(?P<fuerte>.+?)\*\*|(?<!\*)\*(?P<enfasis>[^*\n]+?)\*(?!\*)", re.S)
_MD_ENCABEZADO = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)


def spans_markdown(texto: str) -> list[ft.TextSpan]:
    """El markdown ligero del modelo, como spans con estilo.

    El chat pintaba `ft.Text(b.text)` a pelo y el modelo responde en markdown,
    así que en el móvil se leía literalmente «Hoy toca **Pecho-Bíceps + Abs**»,
    asteriscos incluidos. Pedirle texto plano en el prompt ayuda pero no
    garantiza nada — un modelo distinto en el desplegable vuelve a formatear —,
    así que la burbuja aprende a leerlo en vez de confiar en que no llegue.

    Devuelve la lista de spans en orden; el llamante pone color y tamaño en el
    `ft.Text` que los contiene, que es lo que mantiene el tema al mando.
    """
    limpio = _MD_ENCABEZADO.sub("", texto or "")
    spans: list[ft.TextSpan] = []
    fin = 0
    for m in _MD.finditer(limpio):
        if m.start() > fin:
            spans.append(ft.TextSpan(limpio[fin : m.start()]))
        fuerte = m.group("fuerte")
        if fuerte is not None:
            spans.append(ft.TextSpan(fuerte, ft.TextStyle(weight=ft.FontWeight.W_700)))
        else:
            spans.append(ft.TextSpan(m.group("enfasis"), ft.TextStyle(italic=True)))
        fin = m.end()
    if fin < len(limpio):
        spans.append(ft.TextSpan(limpio[fin:]))
    return spans


#: What the empty screen offers. Written in Spanish because these are things
#: *he* would say, and he says them in Spanish — unlike the app's own chrome,
#: which is English by the rule in CLAUDE.md. The distinction is the point: the
#: labels are the app talking, these are him talking.
STARTERS = (
    "¿Qué toca hoy?",
    "¿Cómo voy con el press banca?",
    "Hice 4 series de sentadilla a 80 por 8",
    "¿Cómo ha ido la semana?",
)


@dataclass
class Bubble:
    """One line in the transcript. `who` is "me", "coach" or "error"."""

    who: str
    text: str


class AgentView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.coach: agent.Coach | None = None
        self.bubbles: list[Bubble] = []
        self.pending: agent.Proposal | None = None
        self.busy = False
        self.last_cost = 0.0
        self._input = ft.TextField()
        #: Ruta de la foto adjunta al próximo envío, o None. Se limpia al enviar.
        self.attach_path: str | None = None
        self.attach_date: str = ""

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_show(self):
        # The conversation is per-process on purpose (see `agent.Coach`), but
        # the Coach object also caches the system prompt, which embeds the
        # profile. Rebuilding it when the key changes is what makes "paste the
        # key in Settings, come back here" work without a restart.
        if self.coach is None:
            self.coach = agent.Coach(self.store)

    def handle_back(self) -> bool:
        # An un-answered proposal is unfinished business: backing out of the
        # screen with a card on it should dismiss the card, not the screen.
        # Anything else means the next visit opens with a stale card describing
        # a conversation he no longer remembers.
        if self.pending is not None:
            self.pending = None
            return True
        self.page.data["navigate_to"](0)
        return True

    def hides_nav(self) -> bool:
        """Give the keyboard the whole screen while he is typing.

        Same call the training screen's zen mode makes. A five-slot navigation
        bar under an on-screen keyboard leaves about two lines of conversation
        visible on a phone.
        """
        return False

    # ── sending ───────────────────────────────────────────────────────────

    async def _send(self, text: str):
        """One turn. Runs the blocking SDK call off the UI thread.

        `asyncio.to_thread` rather than a raw call: `messages.create` is
        synchronous and can take several seconds with tool rounds, and holding
        the Flet event loop for that long freezes the whole app — including the
        rest timer, which is running on the same loop while he is in the gym.
        """
        self.busy = True
        adjunto = self.attach_path
        etiqueta = self.attach_date
        self.attach_path = None
        self.attach_date = ""
        self.bubbles.append(Bubble("me", f"📷 {etiqueta} · {text}" if adjunto else text))
        self.pending = None
        self._render()

        assert self.coach is not None
        try:
            reply = await asyncio.to_thread(self.coach.ask, text, adjunto)
        except Exception as exc:  # pragma: no cover - `ask` is already total
            reply = agent.Reply(text="", error=f"Algo ha fallado: {exc}")

        self.busy = False
        if reply.error:
            self.bubbles.append(Bubble("error", reply.error))
        elif reply.text:
            self.bubbles.append(Bubble("coach", reply.text))
        else:
            self.bubbles.append(Bubble("error", "El entrenador no dijo nada."))

        self.pending = reply.proposal
        # `priced_model` rather than the id: `estimate_cost` prefers the number
        # OpenRouter actually billed and only falls back to arithmetic, and the
        # arithmetic needs a price. The snapshot saved when the model was chosen
        # is what makes that work with no signal.
        self.last_cost = agent.estimate_cost(reply, agent.priced_model(self.store))
        self._render()

    def _toggle_attach(self, _=None):
        """Adjunta la foto de progreso más reciente, o quita la adjunta.

        La "última" y no un selector: el caso real es "mírame HOY", y la foto
        de hoy es la última en cuanto existe. Para comparar fechas concretas
        el coach ya sabe cuáles hay (`progress_photos`) y puede pedir la que
        le falte. Sin fotos aún, el error dice dónde se crea la primera.
        """
        import fotos as _fotos

        if self.attach_path:
            self.attach_path = None
            self.attach_date = ""
            self.page.data["refresh_current"]()
            return
        try:
            filas = [f for f in _fotos.listar(self.store) if f["path"]]
        except Exception:
            filas = []
        if not filas:
            self.bubbles.append(
                Bubble(
                    "error",
                    "No hay fotos de progreso todavía — añade la de hoy desde "
                    "Inicio (tarjeta FOTO) y vuelve a intentarlo.",
                )
            )
            self.page.data["refresh_current"]()
            return
        self.attach_path = filas[0]["path"]
        self.attach_date = filas[0]["date"]
        self.page.data["refresh_current"]()

    def _on_submit(self, _=None):
        text = (self._input.value or "").strip()
        if not text or self.busy:
            return
        self._input.value = ""
        self.page.run_task(self._send, text)

    def _accept(self, _=None):
        """The only path in this feature that writes to the database."""
        proposal = self.pending
        if proposal is None:
            return
        try:
            said = agent.commit_proposal(self.store, proposal)
        except Exception as exc:
            self.bubbles.append(Bubble("error", f"No se pudo guardar: {exc}"))
            self._render()
            return
        self.pending = None
        self.bubbles.append(Bubble("coach", said))
        self._render()

    def _discard(self, _=None):
        self.pending = None
        self.bubbles.append(Bubble("coach", "Descartado — no se escribió nada."))
        self._render()

    def _clear(self, _=None):
        if self.coach is not None:
            self.coach.reset()
        self.bubbles = []
        self.pending = None
        self.last_cost = 0.0
        self._render()

    def _render(self):
        self.page.data["refresh_current"]()

    # ── rendering ─────────────────────────────────────────────────────────

    def _bubble(self, b: Bubble) -> ft.Control:
        mine = b.who == "me"
        bad = b.who == "error"
        # Flet no tiene max-width: un Container suelto en un Row crece con la
        # línea y una respuesta larga se salía de la pantalla del móvil (se
        # vio en el emulador: "…indica Smith Be" cortado). Fijar el ancho solo
        # cuando el texto no cabe deja las burbujas cortas ("Con barra") a su
        # medida y da a las largas todo el ancho útil para envolver.
        ancho = None
        if len(b.text) > 42:
            try:
                ancho = min((self.page.width or 420) - 56, 640)
            except Exception:
                ancho = 364
        return ft.Row(
            [
                ft.Container(
                    # `spans`, no `value`: lo que escribe Alex es texto plano y
                    # lo que responde el modelo es markdown. Un solo camino
                    # sirve para los dos — sin marcas, `spans_markdown` devuelve
                    # un único span con el texto tal cual.
                    content=ft.Text(
                        spans=spans_markdown(b.text),
                        size=13,
                        color=C.on_accent if mine else (C.danger if bad else C.text),
                        selectable=True,
                    ),
                    width=ancho,
                    bgcolor=C.accent if mine else (C.bg_sunken if bad else C.bg_surface),
                    border=None if mine else ft.border.all(1, C.danger if bad else C.border),
                    border_radius=12,
                    padding=ft.padding.symmetric(horizontal=12, vertical=9),
                )
            ],
            alignment=ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START,
        )

    def _proposal_card(self) -> ft.Control:
        """The confirmation. Numbers first, then what it will do, then buttons."""
        p = self.pending
        assert p is not None

        if isinstance(p, agent.WorkoutProposal):
            title = p.exercise
            when = p.day
            body = p.summary()
            detail = plural(len(p.sets), "serie")
            warn = (
                f"{p.exercise} ya está registrado ese día — guardar lo reemplaza."
                if p.replaces
                else ""
            )
            note = p.note or ""
        elif isinstance(p, agent.CalendarEventProposal):
            title = "Evento en Google Calendar"
            when = p.day
            body = p.title
            detail = p.summary()
            warn = ""
            note = p.description or ""
        elif isinstance(p, agent.ReminderProposal):
            title = "Aviso nuevo"
            when = date.today()
            body = p.texto
            detail = p.summary()
            warn = ""
            note = ""
        elif isinstance(p, agent.MemoryProposal):
            # El cuerpo es la frase entera y a tamaño grande, como los números
            # de las otras tarjetas: esto es exactamente lo que hay que leer
            # antes de guardar, porque a partir de aquí viaja en cada
            # conversación y corregirlo es ir a buscarlo a Ajustes.
            import memoria as _memoria

            title = "Que lo recuerde"
            when = date.today()
            body = p.texto
            detail = _memoria.Hecho(texto=p.texto, categoria=p.categoria).etiqueta().lower()
            warn = ""
            note = "Lo tendré presente en todas las conversaciones. Se edita en Ajustes."
        else:
            title = "Peso corporal"
            when = p.day
            body = p.summary()
            detail = ""
            warn = "Ya hay un pesaje ese día — guardar lo corrige." if p.replaces else ""
            note = ""

        when_text = "hoy" if when == date.today() else when.strftime("%d/%m/%Y")

        rows: list[ft.Control] = [
            ft.Row(
                [
                    ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, size=16, color=C.accent),
                    ft.Text(
                        "Nada guardado aún — revísalo",
                        size=11,
                        weight=ft.FontWeight.W_800,
                        color=C.accent,
                    ),
                ],
                spacing=6,
            ),
            ft.Text(title, size=14, weight=ft.FontWeight.W_900, color=C.text),
            # The numbers are the largest thing on the card. This is the line he
            # is being asked to verify, so it should be readable at arm's length
            # with the phone on a bench.
            ft.Text(body, size=20, weight=ft.FontWeight.W_900, color=C.text),
            ft.Text(
                f"{when_text}{' · ' + detail if detail else ''}",
                size=12,
                color=C.text_secondary,
            ),
        ]
        if note:
            rows.append(ft.Text(f"Nota: {note}", size=11, color=C.text_secondary))
        if warn:
            rows.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=14, color=C.warning),
                        ft.Text(warn, size=11, color=C.warning, expand=True),
                    ],
                    spacing=6,
                )
            )
        rows.append(ft.Container(height=4))
        rows.append(
            ft.Row(
                [
                    ghost_button("Descartar", on_click=self._discard),
                    primary_button(
                        "Reemplazar" if warn else "Guardar",
                        on_click=self._accept,
                        expand=True,
                    ),
                ],
                spacing=8,
            )
        )
        return card(*rows, padding=14)

    def _no_key_card(self) -> ft.Control:
        return card(
            ft.Text(
                "El entrenador no está configurado",
                size=14,
                weight=ft.FontWeight.W_900,
                color=C.text,
            ),
            ft.Text(
                "Funciona con OpenRouter y necesita tu clave — una sola, ~350 modelos a elegir. "
                "Ajustes → Entrenador: pégala una vez. Vive en el almacenamiento privado "
                "de la app, nunca en el fichero instalado ni en una copia.",
                size=12,
                color=C.text_secondary,
            ),
            ft.Container(height=6),
            primary_button(
                "Abrir Ajustes",
                on_click=lambda _: self.page.data["navigate_to"](5),
                expand=True,
            ),
            padding=14,
        )

    #: Lo que se le envía al coach cuando Alex toca «Que me conozcas». Es un
    #: mensaje suyo, no una instrucción escondida: aparece en la conversación
    #: como cualquier otro y se puede leer, corregir y repetir.
    ENTREVISTA = (
        "Quiero que me conozcas. Pregúntame lo que te haga falta saber de mí para "
        "entrenarme mejor — de una en una, no todo de golpe — y ve ofreciéndome guardar "
        "lo que valga la pena recordar."
    )

    def _invitacion_a_conocerte(self, ask) -> list[ft.Control]:
        """La entrevista inicial, ofrecida solo mientras no sepa nada.

        Desaparece con el primer hecho guardado. Un botón que sigue ahí después
        de usarlo invita a repetir la entrevista, y la segunda vuelta es el
        coach preguntando cosas que ya tiene apuntadas.
        """
        try:
            import memoria

            if not memoria.vacia(self.store):
                return []
        except Exception:
            return []

        return [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Todavía no sé nada de ti",
                            size=13,
                            weight=ft.FontWeight.W_800,
                            color=C.text,
                        ),
                        ft.Text(
                            "Veo tus entrenos y tu comida, pero no a qué hora entrenas, "
                            "qué no comes o qué te molesta. Cuéntamelo una vez y no "
                            "vuelvo a preguntarlo.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        ft.Container(height=8),
                        primary_button("Que me conozcas", on_click=ask(self.ENTREVISTA)),
                    ],
                    spacing=2,
                    tight=True,
                ),
                bgcolor=C.accent_soft,
                border_radius=10,
                padding=12,
            ),
            ft.Container(height=10),
        ]

    def _starters(self) -> ft.Control:
        def ask(text):
            def go(_):
                if not self.busy:
                    self.page.run_task(self._send, text)

            return go

        return ft.Column(
            [
                *self._invitacion_a_conocerte(ask),
                ft.Text(
                    "Pregunta por tu entreno, o cuenta qué has hecho.",
                    size=12,
                    color=C.text_secondary,
                ),
                ft.Container(height=6),
                *[
                    ft.Container(
                        content=ft.Text(s, size=12, color=C.text),
                        bgcolor=C.bg_surface,
                        border=ft.border.all(1, C.border),
                        border_radius=10,
                        padding=ft.padding.symmetric(horizontal=12, vertical=9),
                        on_click=ask(s),
                        ink=True,
                    )
                    for s in STARTERS
                ],
            ],
            spacing=6,
        )

    def build(self) -> ft.Control:
        try:
            ready = agent.has_key(self.store)
        except Exception as exc:
            return db_error_screen("Entrenador", exc, on_retry=self._render)

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
                ft.Text("Entrenador", size=18, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(
                    content=ft.Icon(ft.Icons.REFRESH_ROUNDED, size=18, color=C.text_secondary),
                    on_click=self._clear,
                    padding=6,
                    ink=True,
                    tooltip="Empezar conversación nueva",
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        if not ready:
            return ft.Column(
                [header, ft.Container(height=10), self._no_key_card()],
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                expand=True,
                spacing=0,
                tight=True,
            )

        transcript: list[ft.Control] = []
        if not self.bubbles:
            transcript.append(self._starters())
        else:
            transcript.extend(self._bubble(b) for b in self.bubbles)
        if self.busy:
            transcript.append(
                ft.Row(
                    [
                        ft.ProgressRing(width=14, height=14, stroke_width=2, color=C.accent),
                        ft.Text("Pensando…", size=12, color=C.text_secondary),
                    ],
                    spacing=8,
                )
            )

        self._input = ft.TextField(
            hint_text="Pregunta, o dime qué has hecho",
            dense=True,
            expand=True,
            multiline=False,
            disabled=self.busy,
            on_submit=self._on_submit,
            border_color=C.border,
            color=C.text,
            hint_style=ft.TextStyle(color=C.text_muted),
        )

        composer = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ADD_A_PHOTO_OUTLINED,
                    icon_color=C.accent if self.attach_path else C.text_muted,
                    disabled=self.busy,
                    tooltip="Adjuntar la última foto de progreso",
                    on_click=self._toggle_attach,
                ),
                self._input,
                ft.IconButton(
                    icon=ft.Icons.SEND_ROUNDED,
                    icon_color=C.accent,
                    disabled=self.busy,
                    on_click=self._on_submit,
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        below: list[ft.Control] = []
        if self.attach_path:
            below.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PHOTO, size=14, color=C.accent),
                        ft.Text(
                            f"Foto del {self.attach_date} adjunta — se envía con tu mensaje",
                            size=11,
                            color=C.text_secondary,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_size=14,
                            icon_color=C.text_muted,
                            tooltip="Quitar la foto",
                            on_click=self._toggle_attach,
                        ),
                    ],
                    spacing=4,
                )
            )
        if self.pending is not None:
            below.append(self._proposal_card())
            below.append(ft.Container(height=8))
        below.append(composer)
        if self.last_cost:
            # Visible on purpose. This is billed per message to Alex's own card,
            # separately from any subscription, and a running cost nobody can
            # see is one discovered on a statement.
            below.append(
                ft.Text(f"Última respuesta ≈ ${self.last_cost:.3f}", size=10, color=C.text_muted)
            )

        return ft.Column(
            [
                header,
                ft.Container(height=8),
                ft.Column(
                    transcript,
                    scroll=ft.ScrollMode.AUTO,
                    auto_scroll=True,
                    expand=True,
                    spacing=8,
                ),
                ft.Container(height=8),
                *below,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )
