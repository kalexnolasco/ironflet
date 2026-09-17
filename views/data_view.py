"""Data: file-based backup export/import, plus the exercise image cache.

Backup used to be a clipboard round-trip (`views/profile.py`): dump JSON, tap
"Copy", paste it somewhere. That is unusable on the phone this app is being
built for — a few months of training is hundreds of KiB, Android clipboards
truncate large payloads without saying so, and there is nowhere to paste it to
anyway. This screen writes and reads a real `.json` file through `backup.py`,
which covers all twelve tables (the clipboard path covered four).

Two platform facts shape the whole design, both checked against Flet 0.28's
`FilePicker`:

* `save_file()` opens the *native* save dialog. On desktop that dialog exists
  and hands back a real filesystem path we can write to. On Android it is a
  Storage Access Framework sheet at best and a no-op at worst — Flet's Python
  API cannot pass the bytes down, so the plugin has nothing to write, and
  `on_result` may never fire. Therefore this screen **always writes its own
  copy into app storage first** and only then opens the picker. Nobody is ever
  left with a dialog that quietly did nothing and no file anywhere.
* `pick_files()` returns `path=None` in web mode — the browser gives a name and
  a size and expects an upload. That is reported on screen instead of crashing
  on `open(None)`.

Anything that can fail here (a full disk, a truncated file, a database that is
not reachable) surfaces in the status banner at the top of the screen. On a
phone nobody watches a console, so a swallowed exception and silent data loss
are the same event.
"""

from __future__ import annotations

import contextlib
import os
from datetime import date, datetime
from pathlib import Path

import flet as ft

import asset_manager
import backup
from backup import BACKUP_VERSION, BackupError, export_all, import_all
from storage import Storage
from theme import C, card, ghost_button, muted_text, primary_button, section_title
from views.shared_ui import plural

# Display order and grouping of `backup.TABLES`. Keys not listed here still get
# rendered — `ordered_counts()` appends them under "Other" — so a table added to
# backup.py appears on screen even before anyone updates this tuple.
TABLE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Entreno",
        (
            "workouts",
            "session_notes",
            "session_durations",
            "weights",
            "photos",
            "profile",
            "prefs",
        ),
    ),
    # La nutrición se retiró en 0.21 y estas cuatro tablas se quedaron: siguen
    # en la base de quien ya usaba la app, y la copia se las lleva para que un
    # móvil nuevo no las pierda. El grupo dice eso — enseñar «Nutrición» a secas
    # en una app que ya no la tiene se lee como que la función sigue ahí y no
    # se encuentra.
    ("Comida (función retirada)", ("foods", "servings", "food_log", "nutrition_targets")),
    ("Rutinas", ("routines", "routine_phases", "routine_days", "routine_exercises")),
)

TABLE_LABELS = {
    "workouts": "Entrenos",
    "session_notes": "Notas de sesión",
    "session_durations": "Tiempos de sesión",
    "weights": "Peso corporal",
    "photos": "Fotos (metadatos)",
    "profile": "Perfil",
    "prefs": "Preferencias",
    "foods": "Alimentos",
    "servings": "Raciones",
    "food_log": "Diario de comida",
    "nutrition_targets": "Objetivos de macros",
    "routines": "Rutinas",
    "routine_phases": "Fases de rutina",
    "routine_days": "Días de rutina",
    "routine_exercises": "Ejercicios de rutina",
}

# Tables whose entire content is one row: printing "5" for a profile that has
# five columns would be nonsense.
SINGLE_ROW_KEYS = frozenset({"profile"})

IMAGE_BUNDLE_LABEL = "≈9 MB"


# ── document counting ────────────────────────────────────────

# Every table `count_document` below actually knows how to find in a document.
# A table appearing in `backup.TABLES` and not here would otherwise be reported
# as a permanent zero on the one screen whose job is to show what a backup
# covers — which is precisely the bug that made the v2 backup lose the food
# diary in silence. `UNCOUNTED_TABLES` puts that on screen instead of hiding it.
#
# It is empty today and that is the point. `photos`, `session_notes` and
# `session_durations` sat outside it for three versions, each printing a "0"
# under a warning that named them in snake_case — so the screen said "no
# photos" and "I am not counting photos" at the same time, and the zero is the
# half a reader believes. They are flat top-level lists in the document; the
# three lines below are all it ever took.
COUNTED_TABLES = frozenset(
    {
        "workouts",
        "session_notes",
        "session_durations",
        "photos",
        "weights",
        "profile",
        "prefs",
        "foods",
        "servings",
        "food_log",
        "nutrition_targets",
        "routines",
        "routine_phases",
        "routine_days",
        "routine_exercises",
    }
)
UNCOUNTED_TABLES = tuple(t for t in backup.TABLES if t not in COUNTED_TABLES)


def _grouped_keys() -> tuple[str, ...]:
    return tuple(key for _group, keys in TABLE_GROUPS for key in keys)


def count_document(data: dict) -> dict[str, int]:
    """Rows per table for a backup document, keyed like `backup.TABLES`.

    The document is *nested* — servings live inside their food, days inside
    their phase — precisely so no primary key has to travel. That nesting is
    invisible to a user deciding whether to overwrite their phone, so it is
    flattened back into the twelve counts the importer will report.

    Tolerant by construction: a v2 document has no `nutrition` or `routines`
    section at all, and a truncated one may have a string where a list belongs.
    Neither may stop the preview from rendering — the preview is what warns the
    user *before* the wipe, so it has to survive worse input than the importer.
    """
    counts = dict.fromkeys(backup.TABLES, 0)
    if not isinstance(data, dict):
        return counts

    def rows(value) -> list:
        return value if isinstance(value, list) else []

    counts["workouts"] = len(rows(data.get("workouts")))
    counts["weights"] = len(rows(data.get("weights")))
    # Las tres secciones planas de nivel superior. `.get()` tolera un documento
    # v2/v3 que no las lleva: `rows()` devuelve [] y el conteo es un 0 honesto.
    counts["session_notes"] = len(rows(data.get("session_notes")))
    counts["session_durations"] = len(rows(data.get("session_durations")))
    counts["photos"] = len(rows(data.get("photos")))
    counts["prefs"] = len(data["prefs"]) if isinstance(data.get("prefs"), dict) else 0

    profile = data.get("profile")
    if isinstance(profile, dict):
        # A profile of empty strings is what `_export_profile` writes when the
        # row does not exist. Reporting it as 1 would promise data that is not
        # there.
        counts["profile"] = 1 if any(v not in (None, "", 0, 0.0) for v in profile.values()) else 0

    nutrition = data.get("nutrition")
    if isinstance(nutrition, dict):
        foods = rows(nutrition.get("foods"))
        counts["foods"] = len(foods)
        counts["servings"] = sum(len(rows(f.get("servings"))) for f in foods if isinstance(f, dict))
        counts["food_log"] = len(rows(nutrition.get("food_log")))
        # The document spells it "targets"; the importer counts it under
        # "nutrition_targets", which is the table name. Both are right in their
        # own file — this is the one place they meet.
        counts["nutrition_targets"] = len(rows(nutrition.get("targets")))

    routines = rows(data.get("routines"))
    counts["routines"] = len(routines)
    for routine in routines:
        if not isinstance(routine, dict):
            continue
        phases = rows(routine.get("phases"))
        counts["routine_phases"] += len(phases)
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            days = rows(phase.get("days"))
            counts["routine_days"] += len(days)
            for day in days:
                if isinstance(day, dict):
                    counts["routine_exercises"] += len(rows(day.get("exercises")))
    return counts


def ordered_counts(counts: dict[str, int]) -> list[tuple[str, str, int]]:
    """`(group, key, count)` in display order, unknown tables last under Other.

    Driven by the counts dict rather than a hardcoded list, so a thirteenth
    table appearing in `backup.TABLES` shows up here without an edit.
    """
    known = _grouped_keys()
    out = [
        (group, key, int(counts.get(key) or 0))
        for group, keys in TABLE_GROUPS
        for key in keys
        if key in counts
    ]
    out += [("Otros", k, int(counts[k] or 0)) for k in sorted(counts) if k not in known]
    return out


def label_of(key: str) -> str:
    return TABLE_LABELS.get(key, key.replace("_", " ").capitalize())


def display_count(key: str, n: int) -> str:
    return ("✓" if n else "—") if key in SINGLE_ROW_KEYS else str(n)


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    kib = num_bytes / 1024
    return f"{kib:.1f} KiB" if kib < 1024 else f"{kib / 1024:.1f} MiB"


def format_timestamp(data: dict) -> str:
    """When the document was written, from whichever stamp it carries.

    v3 writes both `exported_at_iso` (localised, for humans) and `exported_at`
    (epoch float, for code); v2 wrote only the float. Never raises: a corrupt
    stamp must not hide the counts the user is here to read.
    """
    iso = data.get("exported_at_iso")
    if isinstance(iso, str) and iso:
        with contextlib.suppress(ValueError):
            # `fromisoformat` before 3.11 chokes on a trailing Z.
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        return iso
    stamp = data.get("exported_at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        with contextlib.suppress(ValueError, OSError, OverflowError):
            return datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d %H:%M")
    return "unknown"


def backup_dir() -> Path:
    """Where this screen keeps its own copy of every export.

    `FLET_APP_STORAGE_DATA` is the per-app directory Flet sets on Android and
    iOS, and the only place a packaged app can always write. Unset on desktop
    and web, where the working directory is used. Deliberately *not* under
    `assets/`, unlike the exercise frames: a backup must never be reachable
    over HTTP when the app runs in web mode.
    """
    base = os.environ.get("FLET_APP_STORAGE_DATA") or os.getcwd()
    d = Path(base) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


class DataView:
    """Backup screen. State lives on the instance; `build()` renders from it."""

    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store

        # Snapshot of the database, refreshed by on_show().
        self._counts: dict[str, int] = dict.fromkeys(backup.TABLES, 0)
        self._counts_bytes = 0
        self._counts_error: str | None = None

        # (level, message), level in {"info", "success", "error"}. On the
        # instance so it survives the rebuild an action triggers: an error the
        # user never sees is, to them, an error that did not happen.
        self._status: tuple[str, str] | None = None

        # Bytes waiting for the save dialog to name a destination.
        self._pending_export: bytes | None = None
        self._last_export: Path | None = None

        self._dialog: ft.AlertDialog | None = None

        self._dl_running = False
        self._dl_done = 0
        self._dl_total = 0
        self._progress: ft.ProgressBar | None = None
        self._progress_label: ft.Text | None = None

        # One picker per direction. Sharing a single control would let a stale
        # `on_result` from a cancelled save be read as an open.
        self._save_picker = ft.FilePicker(on_result=self._on_save_result)
        self._open_picker = ft.FilePicker(on_result=self._on_open_result)
        self._zip_save_picker = ft.FilePicker(on_result=self._on_zip_save_result)
        self._zip_open_picker = ft.FilePicker(on_result=self._on_zip_open_result)

    # ── view contract ────────────────────────────────────────
    def on_show(self):
        self._attach_pickers()
        self._load_counts()  # deliberately does NOT clear self._status

    def handle_back(self) -> bool:
        # A dialog on top of us eats the back press first, or Android's back
        # button would leave the confirm dialog floating over another screen.
        if self._dialog is not None:
            self._close_dialog()
            return True
        self.page.data["navigate_to"](5)  # Profile, where this screen is entered from
        return True

    def build(self) -> ft.Control:
        self._attach_pickers()
        children: list[ft.Control] = [self._header(), ft.Container(height=8)]
        banner = self._status_banner()
        if banner is not None:
            children += [banner, ft.Container(height=10)]
        children += [
            self._current_data_card(),
            ft.Container(height=10),
            self._export_card(),
            ft.Container(height=10),
            self._import_card(),
            ft.Container(height=10),
            self._photos_zip_card(),
            ft.Container(height=10),
            self._images_card(),
            ft.Container(height=16),
        ]
        return ft.Column(
            children,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )

    # ── plumbing ─────────────────────────────────────────────
    def _attach_pickers(self):
        """Pickers must sit in `page.overlay` to exist on the Flutter side.

        Done here instead of in `main.py` so the feature stays in one file, and
        guarded by a membership test because `build()` runs on every refresh and
        the same control cannot be added twice.

        The `page.update()` is the load-bearing part: appending to the overlay
        only registers the control on the *next* update, and calling
        `save_file()` before that raises "FilePicker Control must be added to
        the page first" — which the user would read as "this device has no save
        dialog". Pushing it immediately means the picker is live before any
        button on this screen can be tapped.
        """
        overlay = getattr(self.page, "overlay", None)
        if overlay is None:
            return
        added = False
        try:
            for picker in (
                self._save_picker,
                self._open_picker,
                self._zip_save_picker,
                self._zip_open_picker,
            ):
                if picker not in overlay:
                    overlay.append(picker)
                    added = True
        except (AttributeError, TypeError):
            return  # a test double for `page` need not behave like a list
        if added:
            with contextlib.suppress(Exception):
                self.page.update()

    def _set_status(self, level: str, message: str):
        self._status = (level, message)

    def _refresh(self):
        with contextlib.suppress(KeyError, TypeError, AttributeError):
            self.page.data["refresh_current"]()

    def _close_dialog(self):
        if self._dialog is not None:
            self.page.close(self._dialog)
            self._dialog = None

    def _load_counts(self):
        """Count the live database by exporting it.

        Counting through `export_all` means the "on device" column and the "in
        file" column come out of the same function, so they cannot disagree
        about what a row is. It does serialise everything to measure the size —
        see `pendiente`: a cheap `backup.counts(store)` would avoid that.
        """
        try:
            dump = export_all(self.store)
            self._counts = count_document(dump)
            self._counts_bytes = len(backup.dumps(dump).encode("utf-8"))
            self._counts_error = None
        except Exception as exc:  # database down, driver missing, anything
            self._counts = dict.fromkeys(backup.TABLES, 0)
            self._counts_bytes = 0
            self._counts_error = str(exc)

    # ── export ───────────────────────────────────────────────
    def _export(self, _=None):
        try:
            dump = export_all(self.store)
            payload = backup.dumps(dump).encode("utf-8")
        except Exception as exc:
            self._set_status("error", f"No se pudo leer la base de datos: {exc}")
            self._refresh()
            return

        name = backup.default_filename()
        # Write our copy BEFORE opening the dialog: on Android the dialog may
        # never come back, and this way the backup exists regardless and the
        # user is told exactly where it is.
        local_error: str | None = None
        try:
            local = backup_dir() / name
            local.write_bytes(payload)
            self._last_export = local
        except OSError as exc:
            self._last_export = None
            local_error = str(exc)

        self._pending_export = payload
        # Count the dump just taken, not the cached snapshot: the Telegram coach
        # writes to the same database and may have added rows since on_show().
        rows = sum(count_document(dump).values())

        if local_error:
            self._set_status(
                "error",
                f"No se pudo escribir en el almacenamiento de la app ({local_error}). "
                "Elige un destino en el diálogo para guardar la copia.",
            )
        else:
            self._set_status(
                "success",
                f"{rows} filas · {format_size(len(payload))} guardado en {self._last_export}. "
                "Elige un destino para guardar una segunda copia.",
            )
        self._refresh()

        try:
            self._save_picker.save_file(
                dialog_title="Guardar copia de IronFlet",
                file_name=name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
            )
        except Exception as exc:
            # A platform with no native save dialog can throw here. The copy
            # above already landed, so this is a downgrade, not a failure.
            if not local_error:
                self._set_status(
                    "info",
                    f"Copia guardada en {self._last_export}. Este dispositivo no tiene diálogo de guardado ({exc}).",
                )
                self._refresh()

    def _explicar_fallo_al_guardar(self, target: Path, exc: OSError) -> str:
        """Por qué falló el segundo guardado — y que el primero sigue ahí.

        Dos cosas que este mensaje tiene que hacer y antes no hacía.

        **No dejar creer que no hay copia.** El texto era «No se pudo escribir
        {nombre}: {error}», y pisaba el mensaje de éxito de la copia local que
        se escribe *antes* de abrir el diálogo justamente por esto. En el
        emulador se leía como "la exportación ha fallado" con 28 KB de JSON
        perfectamente guardados en el almacenamiento de la app.

        **Nombrar el fichero vacío.** En Android el diálogo del sistema crea el
        fichero en cuanto eliges el nombre y nos devuelve un URI del Storage
        Access Framework (`/document/12`), que no es una ruta y que
        `write_bytes` no puede abrir. El resultado es un `.json` de 0 bytes en
        Descargas con el nombre correcto — que es peor que ningún fichero,
        porque parece una copia. No podemos borrarlo (el URI no se resuelve a
        una ruta), así que al menos se dice.
        """
        parece_saf = str(target).startswith(("/document/", "/tree/", "content:"))
        if parece_saf:
            detalle = (
                f"Android no dejó escribir en el destino que elegiste — devolvió "
                f"«{target}», que no es una carpeta real. El archivo que veas ahí "
                "con ese nombre está VACÍO: bórralo."
            )
        else:
            detalle = f"No se pudo escribir {target.name}: {exc}"

        if self._last_export:
            return f"{detalle}  ·  Tu copia completa SÍ está guardada en {self._last_export}"
        return f"{detalle}  ·  Y tampoco se pudo escribir la copia interna: no hay copia."

    def _on_save_result(self, e: ft.FilePickerResultEvent):
        payload = self._pending_export
        self._pending_export = None
        if not e.path:
            # Cancelled, or a platform that silently declines. Not an error:
            # the app-storage copy written before the dialog is intact.
            if self._last_export:
                self._set_status(
                    "info", f"Sin segunda copia. La copia queda en {self._last_export}"
                )
            else:
                self._set_status(
                    "error", "Exportación cancelada y no se pudo escribir ninguna copia."
                )
            self._refresh()
            return
        if payload is None:
            self._set_status("error", "No queda nada que escribir — vuelve a Exportar.")
            self._refresh()
            return

        target = Path(e.path)
        # GTK and some Windows dialogs return literally what was typed,
        # extension filter or not. A backup called "june" still imports, but it
        # is invisible to a ".json" filter on the way back in.
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        try:
            target.write_bytes(payload)
        except OSError as exc:
            self._set_status("error", self._explicar_fallo_al_guardar(target, exc))
        else:
            self._set_status("success", f"Copia guardada en {target}")
        self._refresh()

    # ── import ───────────────────────────────────────────────
    def _pick_import(self, _=None):
        try:
            # ANY, not CUSTOM + ["json"]: Android turns the extension filter
            # into MIME types, and `.json` frequently maps to nothing — leaving
            # the user in a picker where every file is greyed out. The content
            # check below is the one that actually matters anyway.
            self._open_picker.pick_files(
                dialog_title="Abrir copia de IronFlet",
                allow_multiple=False,
                file_type=ft.FilePickerFileType.ANY,
            )
        except Exception as exc:
            self._set_status("error", f"No se pudo abrir el selector de archivos: {exc}")
            self._refresh()

    def _on_open_result(self, e: ft.FilePickerResultEvent):
        files = e.files or []
        if not files:
            self._set_status("info", "Importación cancelada. No se cambió nada.")
            self._refresh()
            return
        picked = files[0]
        if not picked.path:
            # Web mode: the browser gives a name and a size but never a path;
            # the bytes would have to be uploaded. Say so rather than fail on
            # open(None).
            self._set_status(
                "error",
                "Esta versión no puede leer un archivo elegido en el navegador. "
                "Importa desde la app de Android o de escritorio.",
            )
            self._refresh()
            return

        try:
            raw = Path(picked.path).read_bytes()
            data = backup.loads(raw)  # BackupError on truncated/corrupt JSON
        except (OSError, BackupError) as exc:
            self._set_status("error", f"No se pudo leer {picked.name}: {exc}")
            self._refresh()
            return

        self._open_import_preview(picked.name, len(raw), data)

    def _import_blocker(self, data: dict) -> str | None:
        """Reasons to refuse before showing a button that wipes the database.

        `import_all` validates far more thoroughly and does it before writing
        anything, so this is not the safety net — it is the difference between
        "IronFlet said no" and letting the user arm a destructive action that
        was never going to work.
        """
        app_id = data.get("app")
        if app_id not in backup.ACCEPTED_APPS:
            return f"Este archivo lo escribió '{app_id or 'otra cosa'}', no IronFlet."
        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            return "Esta copia no tiene un número de versión legible."
        if version > BACKUP_VERSION:
            return (
                f"El formato v{version} de la copia es más nuevo de lo que esta app entiende "
                f"(v{BACKUP_VERSION}). Actualiza IronFlet primero."
            )
        if not any(count_document(data).values()):
            return "Esta copia no contiene datos."
        return None

    def _open_import_preview(self, filename: str, size_bytes: int, data: dict):
        """Show what the file holds, what it replaces, and make the user say yes.

        Two steps on purpose — read the comparison, then tick the acknowledgement
        — because `wipe=True` deletes every row in the database, and one mistap
        on a phone must not be able to do that.
        """
        file_counts = count_document(data)
        blocker = self._import_blocker(data)
        losing = sum(self._counts.values())

        rows: list[ft.Control] = [
            ft.Row(
                [
                    ft.Text("", width=132),
                    ft.Text(
                        "EN EL ARCHIVO",
                        size=9,
                        width=54,
                        color=C.text_muted,
                        weight=ft.FontWeight.W_800,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                    ft.Text(
                        "EN EL MÓVIL",
                        size=9,
                        width=64,
                        color=C.text_muted,
                        weight=ft.FontWeight.W_800,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                spacing=4,
            )
        ]
        seen: set[str] = set()
        for group, key, in_file in ordered_counts(file_counts):
            if group not in seen:
                seen.add(group)
                rows.append(ft.Container(height=5))
                rows.append(
                    ft.Text(group.upper(), size=9, color=C.text_muted, weight=ft.FontWeight.W_800)
                )
            on_device = int(self._counts.get(key) or 0)
            rows.append(
                ft.Row(
                    [
                        ft.Text(label_of(key), size=11, color=C.text_secondary, width=132),
                        ft.Text(
                            display_count(key, in_file),
                            size=12,
                            width=54,
                            color=C.text if in_file else C.text_muted,
                            weight=ft.FontWeight.W_800,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                        # Red is not decoration here: this column is what the
                        # import deletes.
                        ft.Text(
                            display_count(key, on_device),
                            size=12,
                            width=64,
                            color=C.danger if on_device else C.text_muted,
                            weight=ft.FontWeight.W_800,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=4,
                )
            )

        # Both the button and the acknowledgement say what this particular
        # import will do. "Erase" over an empty database is a lie the user
        # learns to click through, and then it is not a warning any more.
        confirm = ft.TextButton(
            "Borrar e importar" if losing else "Importar",
            disabled=True,
            style=ft.ButtonStyle(color=C.danger if losing else C.accent),
            on_click=lambda _: self._do_import(data),
        )

        def toggle(e):
            confirm.disabled = not bool(e.control.value)
            self.page.update()

        ack = ft.Checkbox(
            label=(
                "Entiendo que los datos de este dispositivo se borrarán"
                if losing
                else "Restaurar esta copia en este dispositivo"
            ),
            value=False,
            on_change=toggle,
            label_style=ft.TextStyle(size=11, color=C.text_secondary),
            fill_color=C.danger if losing else C.accent,
            check_color=C.on_accent,
        )

        header = ft.Column(
            [
                ft.Text(
                    filename,
                    size=12,
                    color=C.text,
                    weight=ft.FontWeight.W_800,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                muted_text(
                    f"Exportada {format_timestamp(data)}"
                    f"  ·  v{data.get('version', '?')}"
                    f"  ·  {data.get('engine', '?')}"
                    f"  ·  {format_size(size_bytes)}",
                    size=10,
                ),
            ],
            spacing=2,
            tight=True,
        )

        body: list[ft.Control] = [header, ft.Container(height=6)]
        if blocker:
            body += [
                ft.Container(
                    content=ft.Text(blocker, size=12, color=C.danger, weight=ft.FontWeight.W_700),
                    bgcolor=C.bg_sunken,
                    border=ft.border.all(1, C.danger),
                    border_radius=8,
                    padding=10,
                ),
                ft.Container(height=6),
            ]
        body += rows
        if not blocker:
            # Restoring onto a fresh phone is the main use case and destroys
            # nothing. Shouting "there is no undo" at an empty database trains
            # the user to tap past the warning that does matter.
            if losing:
                tone = C.danger
                warning = (
                    f"Importar borra {plural(losing, 'fila')} de este dispositivo y las "
                    "reemplaza con el archivo. No hay deshacer."
                )
            else:
                tone = C.warning
                warning = (
                    "Este dispositivo aún no tiene datos, así que no se pierde nada — "
                    "el contenido del archivo se escribe tal cual."
                )
            body += [
                ft.Container(height=10),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=tone, size=18),
                            ft.Text(
                                warning,
                                size=11,
                                color=tone,
                                weight=ft.FontWeight.W_700,
                                expand=True,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    bgcolor=C.bg_sunken,
                    border=ft.border.all(1, tone),
                    border_radius=8,
                    padding=10,
                ),
                ft.Container(height=4),
                ack,
            ]

        dlg = ft.AlertDialog(
            modal=True,  # a wipe is not something to dismiss by tapping outside
            bgcolor=C.bg_surface,
            title=ft.Text("Importar copia", size=16, weight=ft.FontWeight.W_900, color=C.text),
            content=ft.Container(
                content=ft.Column(body, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO),
                width=330,
                height=400,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self._cancel_import(),
                    style=ft.ButtonStyle(color=C.text_secondary),
                ),
                *([] if blocker else [confirm]),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._dialog = dlg
        self.page.open(dlg)

    def _cancel_import(self):
        self._close_dialog()
        self._set_status("info", "Importación cancelada. No se cambió nada.")
        self._refresh()

    def _do_import(self, data: dict):
        self._close_dialog()
        try:
            counts = import_all(self.store, data, wipe=True)
        except BackupError as exc:
            # backup.py parses the whole document before it opens a session, and
            # keeps the wipe inside the write transaction — so "nothing was
            # replaced" is a promise the module makes, not optimism here.
            self._set_status("error", f"Importación rechazada, no se reemplazó nada: {exc}")
            self._refresh()
            return
        except Exception as exc:
            self._set_status("error", f"La importación falló, no se reemplazó nada: {exc}")
            self._refresh()
            return

        # import_all() already re-synced data.ROUTINES and the active routine
        # pref; re-doing it here would only risk disagreeing with it.
        self._set_status("success", f"Restaurado: {backup.summary_line(counts)}.")
        self._load_counts()
        self._refresh()

    # ── exercise images ──────────────────────────────────────
    def _on_dl_progress(self, done: int, total: int):
        self._dl_done, self._dl_total = done, total or 0
        bar, label = self._progress, self._progress_label
        if bar is None or label is None:
            return
        bar.value = (done / total) if total else 0
        label.value = f"{done} / {total}"
        # The view may have been rebuilt or navigated away from mid-download.
        # Progress is cosmetic and must never take the download task with it.
        with contextlib.suppress(Exception):
            self.page.update()

    async def _download_images(self, _=None):
        if self._dl_running:
            return
        self._dl_running = True
        self._dl_done = 0
        self._dl_total = asset_manager.total_file_count()
        self._set_status("info", f"Descargando imágenes de ejercicios ({IMAGE_BUNDLE_LABEL})…")
        self._refresh()
        try:
            ok, failed = await asset_manager.download_all(progress_cb=self._on_dl_progress)
        except Exception as exc:
            self._dl_running = False
            self._set_status("error", f"Falló la descarga de imágenes: {exc}")
            self._refresh()
            return
        self._dl_running = False
        if ok and not failed:
            self._set_status("success", f"{ok} imágenes de ejercicios instaladas.")
        elif ok:
            self._set_status(
                "error", f"Descarga parcial: {ok} guardadas, {failed} faltan. Reintenta."
            )
        else:
            # download_all swallows network errors and returns (0, total).
            self._set_status("error", "Falló la descarga. Revisa la conexión y reintenta.")
        self._refresh()

    def _clear_images(self, _=None):
        try:
            asset_manager.clear_cache()
        except OSError as exc:
            self._set_status("error", f"No se pudo vaciar la caché de imágenes: {exc}")
        else:
            self._dl_done = 0
            self._set_status(
                "info", f"Imágenes de ejercicios borradas ({IMAGE_BUNDLE_LABEL} liberados)."
            )
        self._refresh()

    # ── sections ─────────────────────────────────────────────
    def _header(self) -> ft.Control:
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text("Ajustes", color=C.accent, size=12, weight=ft.FontWeight.W_700),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=lambda _: self.page.data["navigate_to"](5),
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text("Copia y datos", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Text(
                    "Mueve todo entre tu móvil y tu ordenador.",
                    size=11,
                    color=C.text_secondary,
                ),
            ],
            spacing=2,
            tight=True,
        )

    def _status_banner(self) -> ft.Control | None:
        if self._status is None:
            return None
        level, message = self._status
        tone = {"error": C.danger, "success": C.success}.get(level, C.text_secondary)
        icon = {
            "error": ft.Icons.ERROR_OUTLINE,
            "success": ft.Icons.CHECK_CIRCLE_OUTLINE,
        }.get(level, ft.Icons.INFO_OUTLINE)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=tone, size=18),
                    ft.Text(
                        message,
                        size=11,
                        color=tone,
                        weight=ft.FontWeight.W_700,
                        expand=True,
                        selectable=True,  # so a path can be copied off the screen
                    ),
                    ft.Container(
                        content=ft.Icon(ft.Icons.CLOSE, color=C.text_muted, size=14),
                        on_click=lambda _: self._dismiss_status(),
                        padding=4,
                        ink=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, tone),
            border_radius=10,
            padding=10,
        )

    def _dismiss_status(self):
        self._status = None
        self._refresh()

    def _current_data_card(self) -> ft.Control:
        if self._counts_error:
            return card(
                section_title("En este dispositivo"),
                ft.Text(
                    f"No se pudo leer la base de datos: {self._counts_error}",
                    size=11,
                    color=C.danger,
                    weight=ft.FontWeight.W_700,
                ),
                muted_text(
                    "Exportar e importar seguirán sin funcionar hasta que responda.", size=10
                ),
                border_color=C.danger,
            )

        rows: list[ft.Control] = []
        current_group: str | None = None
        for group, key, value in ordered_counts(self._counts):
            if group != current_group:
                current_group = group
                rows.append(ft.Container(height=6))
                rows.append(
                    ft.Text(group.upper(), size=9, color=C.text_muted, weight=ft.FontWeight.W_800)
                )
            rows.append(
                ft.Row(
                    [
                        ft.Text(label_of(key), size=11, color=C.text_secondary, expand=True),
                        ft.Text(
                            display_count(key, value),
                            size=12,
                            color=C.text if value else C.text_muted,
                            weight=ft.FontWeight.W_800,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
            )

        if UNCOUNTED_TABLES:
            # backup.py grew a table this screen cannot read out of a document.
            # Both columns would show 0 for it forever, so say so out loud.
            rows.append(ft.Container(height=6))
            rows.append(
                ft.Text(
                    "Sin contar en esta pantalla: " + ", ".join(UNCOUNTED_TABLES),
                    size=10,
                    color=C.warning,
                    weight=ft.FontWeight.W_700,
                )
            )

        return card(
            ft.Row(
                [
                    section_title("En este dispositivo"),
                    ft.Text(
                        f"{sum(self._counts.values())} filas · {format_size(self._counts_bytes)}",
                        size=10,
                        color=C.text_muted,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            muted_text(f"Las {len(self._counts)} tablas que lleva una copia, una a una.", size=10),
            *rows,
        )

    def _export_card(self) -> ft.Control:
        children: list[ft.Control] = [
            section_title("Exportar"),
            ft.Text(
                "El archivo se escribe primero en el almacenamiento de la app y luego "
                "eliges dónde copiarlo. Si no se abre ningún diálogo, este "
                "dispositivo no tiene selector de carpetas — la copia interna ya es "
                "una copia completa.",
                size=11,
                color=C.text_secondary,
            ),
        ]
        if self._last_export is not None:
            children += [
                ft.Container(height=4),
                ft.Text(
                    "Última exportación", size=9, color=C.text_muted, weight=ft.FontWeight.W_800
                ),
                ft.Text(
                    str(self._last_export),
                    size=10,
                    color=C.text_secondary,
                    selectable=True,
                    max_lines=3,
                ),
            ]
        children += [
            ft.Container(height=8),
            primary_button(
                "Exportar a archivo", icon=ft.Icons.SAVE_ALT, on_click=self._export, expand=True
            ),
        ]
        return card(*children)

    def _import_card(self) -> ft.Control:
        return card(
            section_title("Importar"),
            ft.Text(
                "Restaura un archivo de copia. Ves lo que trae y lo que reemplaza "
                "antes de tocar nada.",
                size=11,
                color=C.text_secondary,
            ),
            ft.Container(height=8),
            ghost_button("Elegir archivo de copia…", on_click=self._pick_import, expand=True),
        )

    def _photos_zip_card(self) -> ft.Control:
        """Los BYTES de las fotos de progreso, aparte del backup de texto.

        La copia JSON lleva solo los metadatos (fecha → nombre de fichero):
        meses de JPEG en base64 la dejarían inenviable por chat, que es como
        estas copias viajan. Este zip es la otra mitad; en un móvil nuevo se
        restaura la copia y luego este zip, y la galería vuelve entera.
        """
        try:
            import fotos as _fotos

            total = len([f for f in _fotos.listar(self.store) if f["path"]])
        except Exception:
            total = 0
        return card(
            section_title("Fotos de progreso"),
            ft.Text(
                "La copia de arriba guarda las fechas; los archivos JPEG van en "
                "un zip aparte. Expórtalo de vez en cuando y guárdalo con la copia.",
                size=11,
                color=C.text_secondary,
            ),
            ft.Container(height=4),
            muted_text(f"{plural(total, 'foto')} en este dispositivo", size=10),
            ft.Container(height=8),
            ft.Row(
                [
                    ghost_button(
                        "Exportar fotos (zip)", on_click=self._export_photos_zip, expand=True
                    ),
                    ghost_button(
                        "Importar fotos (zip)", on_click=self._import_photos_zip, expand=True
                    ),
                ],
                spacing=8,
            ),
        )

    def _export_photos_zip(self, _):
        """Igual que el backup: primero al almacenamiento de la app, luego elige."""
        import fotos as _fotos

        nombre = f"ironflet-fotos-{date.today().isoformat()}.zip"
        destino = backup_dir() / nombre
        try:
            contadas = _fotos.exportar_zip(self.store, destino)
        except Exception as exc:
            self._set_status("error", f"No se pudo crear el zip: {exc}")
            self._refresh()
            return
        self._last_photos_zip = destino
        self._set_status(
            "success",
            f"{plural(contadas, 'foto')} en {destino}. Elige un destino para una segunda copia.",
        )
        self._refresh()
        with contextlib.suppress(Exception):
            self._zip_save_picker.save_file(
                dialog_title="Guardar fotos de IronFlet",
                file_name=nombre,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
            )

    def _on_zip_save_result(self, e: ft.FilePickerResultEvent):
        origen = getattr(self, "_last_photos_zip", None)
        if not e.path or origen is None:
            return
        destino = Path(e.path)
        try:
            destino.write_bytes(Path(origen).read_bytes())
            self._set_status("success", f"Fotos guardadas en {destino}")
        except OSError as exc:
            # Mismo URI del Storage Access Framework que en `_on_save_result`,
            # mismo `.zip` de 0 bytes en Descargas, misma necesidad de decir
            # que el zip bueno sí existe.
            parece_saf = str(destino).startswith(("/document/", "/tree/", "content:"))
            if parece_saf:
                self._set_status(
                    "error",
                    f"Android no dejó escribir en «{destino}». El archivo con ese "
                    f"nombre está VACÍO: bórralo.  ·  El zip completo está en {origen}",
                )
            else:
                self._set_status(
                    "error",
                    f"No se pudo escribir {destino.name}: {exc}  ·  El zip está en {origen}",
                )
        self._refresh()

    def _import_photos_zip(self, _):
        try:
            self._zip_open_picker.pick_files(
                dialog_title="Abrir zip de fotos de IronFlet",
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
            )
        except Exception as exc:
            self._set_status("error", f"No se pudo abrir el selector de archivos: {exc}")
            self._refresh()

    def _on_zip_open_result(self, e: ft.FilePickerResultEvent):
        import fotos as _fotos

        if not e.files or not e.files[0].path:
            return
        try:
            contadas = _fotos.importar_zip(self.store, e.files[0].path)
            self._set_status("success", f"{plural(contadas, 'foto')} restauradas del zip.")
        except Exception as exc:
            self._set_status("error", f"No se pudo importar el zip: {exc}")
        self._load_counts()
        self._refresh()

    def _images_card(self) -> ft.Control:
        installed = asset_manager.is_installed()
        total = self._dl_total or asset_manager.total_file_count()
        done_fraction = (self._dl_done / total) if total else 0
        self._progress = ft.ProgressBar(
            value=1 if (installed and not self._dl_running) else done_fraction,
            bgcolor=C.border,
            color=C.accent,
            bar_height=6,
        )
        self._progress_label = ft.Text(
            f"{self._dl_done} / {total}" if self._dl_running else "",
            size=10,
            color=C.text_secondary,
        )
        # Three states, not two. "Installed / Not installed" cannot express the
        # one that actually happened: 68 of 70 present, so `is_installed()` says
        # no and the label said "Not installed · ~9 MB" — indistinguishable from
        # having none, and it hides that a single re-download fixes two files
        # rather than fetching the whole bundle again.
        #
        # `asset_manager.missing_summary()` was written to say exactly this and
        # had no caller anywhere.
        faltan = asset_manager.missing_summary()
        if installed:
            state, tone = "Instaladas", C.success
        elif self._dl_running:
            state, tone = "Descargando…", C.accent
        elif faltan and asset_manager.status().present:
            state, tone = faltan, C.warning
        else:
            state, tone = f"Sin instalar · {IMAGE_BUNDLE_LABEL}", C.text_secondary

        buttons: list[ft.Control] = []
        if installed:
            buttons.append(ghost_button("Borrar", on_click=self._clear_images, expand=True))
        buttons.append(
            primary_button(
                "Volver a descargar" if installed else "Descargar",
                icon=ft.Icons.CLOUD_DOWNLOAD,
                on_click=self._download_images,
                expand=True,
            )
        )

        return card(
            section_title("Imágenes de ejercicios"),
            ft.Text(
                "Las fotos no van dentro de la app — se descargan una vez "
                f"({IMAGE_BUNDLE_LABEL}), así que usa Wi-Fi. No forman parte de la copia: "
                "descárgalas de nuevo en un dispositivo nuevo.",
                size=11,
                color=C.text_secondary,
            ),
            ft.Container(height=6),
            ft.Text(state, size=11, color=tone, weight=ft.FontWeight.W_700),
            self._progress,
            self._progress_label,
            ft.Container(height=6),
            ft.Row(buttons, spacing=8),
        )
