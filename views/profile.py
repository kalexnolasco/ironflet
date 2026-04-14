"""Profile: user data + calculated health metrics + weight log + backup."""

from __future__ import annotations

import json
from datetime import date

import flet as ft

import asset_manager
from components.charts import bar_chart
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
from i18n import t
from storage import Storage
from theme import (
    ACCENT,
    ACCENT2,
    BORDER,
    BORDER_2,
    CARD_BG,
    DARK_BG,
    DIM,
    MUTED,
    TEXT,
    card,
    ghost_button,
    primary_button,
    section_title,
)

ACTIVITY_KEYS = list(ACTIVITY_FACTORS.keys())
SEX_KEYS = ["M", "F", ""]


class ProfileView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self._form_values: dict = {}

    def on_show(self):
        self._form_values = dict(self.store.get_profile())

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
            label=t("Weight (kg)"),
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=14,
            autofocus=True,
        )
        date_field = ft.TextField(
            label=t("Date (YYYY-MM-DD)"),
            value=date.today().isoformat(),
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=14,
        )
        err = ft.Text("", size=11, color=ACCENT2)

        def save(_):
            try:
                kg = float((kg_field.value or "").replace(",", "."))
                if kg <= 0:
                    raise ValueError("non-positive")
            except ValueError:
                err.value = t("Enter a valid weight")
                self.page.update()
                return
            dv = (date_field.value or "").strip()
            try:
                if dv:
                    date.fromisoformat(dv)
            except ValueError:
                err.value = t("Invalid date format")
                self.page.update()
                return
            self.store.save_weight(kg, dv or None)
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=CARD_BG,
            title=ft.Text(t("Log weight"), size=16, weight=ft.FontWeight.W_900, color=TEXT),
            content=ft.Container(
                content=ft.Column(
                    [kg_field, date_field, err],
                    spacing=10,
                    tight=True,
                ),
                width=320,
                height=180,
            ),
            actions=[
                ft.TextButton(
                    t("Cancel"),
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=DIM),
                ),
                ft.TextButton(t("Save"), on_click=save, style=ft.ButtonStyle(color=ACCENT)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _delete_weight(self, wid: int):
        self.store.delete_weight(wid)
        self.page.data["refresh_current"]()

    # ── backup / restore ─────────────────────────────────────
    def _open_export(self):
        dump = self.store.export_all()
        payload = json.dumps(dump, indent=2, ensure_ascii=False, sort_keys=True)
        size_kb = len(payload.encode("utf-8")) / 1024

        def _stat_row(label: str, value: str) -> ft.Control:
            return ft.Row(
                [
                    ft.Text(label, size=11, color=DIM, weight=ft.FontWeight.W_700, width=180),
                    ft.Text(value, size=13, color=TEXT, weight=ft.FontWeight.W_900),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        status = ft.Text("", size=11, color=ACCENT, weight=ft.FontWeight.W_700)

        def do_copy(_):
            self.page.set_clipboard(payload)
            status.value = t("Copied!")
            self.page.update()

        body = ft.Column(
            [
                _stat_row(t("Workouts"), str(len(dump.get("workouts") or []))),
                _stat_row(t("Weight entries"), str(len(dump.get("weights") or []))),
                _stat_row(t("Preferences"), str(len(dump.get("prefs") or {}))),
                _stat_row(t("Profile"), "✓" if (dump.get("profile") or {}).get("name") else "—"),
                _stat_row(t("Size"), f"{size_kb:.1f} KiB"),
                ft.Container(height=6),
                primary_button(
                    t("Copy to clipboard"),
                    icon=ft.Icons.CONTENT_COPY,
                    on_click=do_copy,
                    expand=True,
                ),
                status,
            ],
            spacing=10,
            tight=True,
            width=300,
        )

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=CARD_BG,
            title=ft.Text(t("Export backup"), size=16, weight=ft.FontWeight.W_900, color=TEXT),
            content=ft.Container(
                content=body, width=320, height=280, alignment=ft.alignment.top_left
            ),
            actions=[
                ft.TextButton(
                    t("Close"),
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=DIM),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _open_import(self):
        paste = ft.TextField(
            hint_text=t("Paste backup JSON below"),
            multiline=True,
            min_lines=10,
            max_lines=10,
            text_size=10,
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color="#ddd",
        )
        status = ft.Text("", size=11, color=ACCENT2)
        warn = ft.Text(
            t("This will replace all current data."),
            size=10,
            color=ACCENT2,
            weight=ft.FontWeight.W_700,
        )

        def paste_from_clipboard(_):
            try:
                val = self.page.get_clipboard() or ""
            except Exception:
                val = ""
            paste.value = val
            self.page.update()

        def do_import(_):
            raw = (paste.value or "").strip()
            if not raw:
                status.value = t("Invalid backup JSON")
                self.page.update()
                return
            try:
                data = json.loads(raw)
                counts = self.store.import_all(data, wipe=True)
            except Exception as exc:  # json error OR ValueError from import
                status.value = f"{t('Invalid backup JSON')}: {exc}"
                self.page.update()
                return
            status.color = ACCENT
            total = sum(counts.values())
            status.value = f"{t('Backup imported')} ({total})"
            self.page.update()
            # brief pause then close + refresh
            self.page.close(dlg)
            # reload language/routine from the new prefs
            import i18n
            from data import set_active_routine

            i18n.set_language(self.store.get_pref("lang", "en") or "en")
            set_active_routine(self.store.get_pref("routine", "cambiatufisico") or "cambiatufisico")
            self.page.data["refresh_current"]()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=CARD_BG,
            title=ft.Text(t("Import backup"), size=16, weight=ft.FontWeight.W_900, color=TEXT),
            content=ft.Container(
                content=ft.Column(
                    [
                        warn,
                        paste,
                        ft.TextButton(
                            t("Paste from clipboard"),
                            on_click=paste_from_clipboard,
                            style=ft.ButtonStyle(color=ACCENT),
                        ),
                        status,
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=340,
                height=360,
            ),
            actions=[
                ft.TextButton(
                    t("Cancel"),
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=DIM),
                ),
                ft.TextButton(
                    t("Replace all"), on_click=do_import, style=ft.ButtonStyle(color=ACCENT)
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _backup_section(self) -> ft.Control:
        return ft.Row(
            [
                ghost_button(t("Export"), on_click=lambda _: self._open_export(), expand=True),
                ghost_button(t("Import"), on_click=lambda _: self._open_import(), expand=True),
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
            bgcolor=CARD_BG,
            title=ft.Text(t(title_key), size=16, weight=ft.FontWeight.W_900, color=TEXT),
            content=ft.Container(
                content=ft.Text(t(message_key), size=12, color="#ddd", width=300),
                width=320,
            ),
            actions=[
                ft.TextButton(
                    t("Cancel"),
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=DIM),
                ),
                ft.TextButton(
                    t(action_key), on_click=confirmed, style=ft.ButtonStyle(color=ACCENT2)
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _danger_row(self, icon, label_key: str, on_click) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=ACCENT2, size=18),
                    ft.Container(
                        content=ft.Text(
                            t(label_key), size=12, color="#ddd", weight=ft.FontWeight.W_700
                        ),
                        width=230,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color="#555", size=16),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            margin=ft.margin.only(bottom=6),
            on_click=lambda _: on_click(),
            ink=True,
        )

    # ── exercise guides (image cache) ────────────────────────
    def _open_download_dialog(self):
        total = asset_manager.total_file_count()
        installed = asset_manager.is_installed()
        status_label = ft.Text(
            t("Installed") if installed else f"{t('Not installed')}  ·  ~9 MB",
            size=11,
            color=ACCENT if installed else DIM,
            weight=ft.FontWeight.W_700,
        )
        progress_bar = ft.ProgressBar(
            value=1 if installed else 0, bgcolor=BORDER, color=ACCENT, bar_height=6
        )
        count_label = ft.Text(f"0 / {total}", size=10, color=DIM)

        def on_progress(done: int, tot: int):
            try:
                progress_bar.value = done / tot if tot else 0
                count_label.value = f"{done} / {tot}"
                self.page.update()
            except Exception:
                pass

        async def do_download(_):
            status_label.value = t("Downloading…")
            status_label.color = ACCENT
            self.page.update()
            ok, err = await asset_manager.download_all(progress_cb=on_progress)
            if err == 0:
                status_label.value = t("Installed")
            else:
                status_label.value = f"{t('Partial')} · {ok} ok / {err} err"
            self.page.update()

        def do_clear(_):
            asset_manager.clear_cache()
            status_label.value = f"{t('Not installed')}  ·  ~9 MB"
            status_label.color = DIM
            progress_bar.value = 0
            count_label.value = f"0 / {total}"
            self.page.update()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=CARD_BG,
            title=ft.Text(t("Exercise guides"), size=16, weight=ft.FontWeight.W_900, color=TEXT),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            t(
                                "Exercise photos and instructions are downloaded "
                                "from a public fitness database (Unlicense). "
                                "Approx. 9 MB over Wi-Fi is recommended."
                            ),
                            size=11,
                            color="#ddd",
                            width=300,
                        ),
                        ft.Container(height=4),
                        status_label,
                        progress_bar,
                        count_label,
                        ft.Container(height=6),
                        ft.Row(
                            [
                                ghost_button(t("Clear cache"), on_click=do_clear, expand=True),
                                primary_button(
                                    t("Download"),
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
                width=320,
                height=280,
            ),
            actions=[
                ft.TextButton(
                    t("Close"),
                    on_click=lambda _: self.page.close(dlg),
                    style=ft.ButtonStyle(color=DIM),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _guides_section(self) -> ft.Control:
        installed = asset_manager.is_installed()
        status = t("Installed") if installed else "~9 MB"
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.CLOUD_DOWNLOAD, color=ACCENT if not installed else "#555", size=18
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    t("Exercise guides"),
                                    size=12,
                                    color="#ddd",
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Text(status, size=10, color=DIM),
                            ],
                            spacing=1,
                            tight=True,
                        ),
                        width=220,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color="#555", size=16),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            margin=ft.margin.only(bottom=6),
            on_click=lambda _: self._open_download_dialog(),
            ink=True,
        )

    def _danger_zone(self) -> ft.Control:
        def clear_history():
            self._confirm_action(
                "Clear workout history",
                "This will permanently delete all logged workouts. Profile and weight log stay.",
                "Delete",
                self.store.clear_workouts,
            )

        def clear_all():
            def do_wipe():
                self.store.clear_all()
                # pref defaults reapply next render; reset i18n/routine to defaults.
                import i18n
                from data import set_active_routine

                i18n.set_language("en")
                set_active_routine("cambiatufisico")

            self._confirm_action(
                "Clear all data",
                "This will erase profile, weight log, workouts and preferences. Cannot be undone.",
                "Erase all",
                do_wipe,
            )

        return ft.Column(
            [
                self._danger_row(ft.Icons.DELETE_SWEEP, "Clear workout history", clear_history),
                self._danger_row(ft.Icons.DELETE_FOREVER, "Clear all data", clear_all),
            ],
            spacing=0,
            tight=True,
        )

    # ── form widgets ──────────────────────────────────────────
    def _text_input(self, label: str, key: str, keyboard=ft.KeyboardType.TEXT) -> ft.TextField:
        def on_change(e, k=key):
            self._form_values[k] = e.control.value

        return ft.TextField(
            label=label,
            value=str(self._form_values.get(key, "") or ""),
            keyboard_type=keyboard,
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=14,
            height=52,
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
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=14,
            on_change=on_change,
        )

    # ── stats rendering ───────────────────────────────────────
    def _stat(self, label: str, value: str, sub: str = "") -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label.upper(), size=9, color=MUTED, weight=ft.FontWeight.W_700),
                    ft.Text(value, size=18, color=ACCENT, weight=ft.FontWeight.W_900),
                    ft.Text(sub, size=10, color=DIM) if sub else ft.Container(),
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor=DARK_BG,
            border=ft.border.all(1, BORDER_2),
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

        age_row = self._stat(t("Age"), fmt(age, "y"))
        bmi_row = self._stat(t("BMI"), fmt(b, "", 1), t(bcat) if bcat else "")
        bmr_row = self._stat(t("BMR"), f"{fmt(bmr, ' kcal')}" if bmr else "—")
        tdee_row = self._stat(t("TDEE"), f"{fmt(tdv, ' kcal')}" if tdv else "—", t(activity))
        protein_txt = f"{prot[0]:g}–{prot[1]:g} g" if prot else "—"
        prot_row = self._stat(t("Protein"), protein_txt, "1.6–2.2 g/kg")
        water_row = self._stat(t("Water"), f"{fmt(water, ' L', 1)}" if water else "—", "~35 ml/kg")

        return ft.Column(
            [
                ft.Row([age_row, bmi_row], spacing=8),
                ft.Row([bmr_row, tdee_row], spacing=8),
                ft.Row([prot_row, water_row], spacing=8),
            ],
            spacing=8,
            tight=True,
        )

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
                            t("Current weight"), size=11, color=MUTED, weight=ft.FontWeight.W_700
                        ),
                        ft.Text(
                            f"{latest:g} kg" if latest else "—",
                            size=24,
                            color=TEXT,
                            weight=ft.FontWeight.W_900,
                        ),
                    ],
                    spacing=2,
                    tight=True,
                    expand=True,
                ),
                primary_button(
                    t("Log weight"), icon=ft.Icons.ADD, on_click=lambda _: self._open_log_weight()
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        chart = ft.Container(
            content=bar_chart(kgs, labels, color="#4ECDC4", height=110)
            if entries
            else ft.Text(t("No weight logged yet"), size=11, color="#666", italic=True),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
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
                                    e["date"], size=11, color=DIM, weight=ft.FontWeight.W_700
                                ),
                                width=110,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    f"{e['kg']:g} kg",
                                    size=13,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_700,
                                ),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Icon(ft.Icons.DELETE_OUTLINE, color="#555", size=16),
                                on_click=lambda _, wid=e["id"]: self._delete_weight(wid),
                                ink=True,
                                padding=6,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=CARD_BG,
                    border=ft.border.all(1, BORDER),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    margin=ft.margin.only(bottom=4),
                )
            )

        return ft.Column(
            [
                header,
                ft.Container(height=10),
                chart,
                ft.Container(height=10),
                section_title(t("History")),
                ft.Container(height=6),
                *history_rows,
            ],
            spacing=0,
            tight=True,
        )

    # ── main build ────────────────────────────────────────────
    def build(self) -> ft.Control:
        profile = self.store.get_profile()
        latest_weight = self.store.get_latest_weight()

        sex_options = [
            ("M", t("Male")),
            ("F", t("Female")),
            ("", t("Prefer not to say")),
        ]
        activity_options = [(k, t(k)) for k in ACTIVITY_KEYS]

        name_field = self._text_input(t("Name"), "name")
        dob_field = self._text_input(
            t("Birthdate (YYYY-MM-DD)"),
            "birthdate",
        )
        height_field = self._text_input(
            t("Height (cm)"),
            "height_cm",
            keyboard=ft.KeyboardType.NUMBER,
        )
        sex_field = self._dropdown(t("Sex"), "sex", sex_options)
        activity_field = self._dropdown(t("Activity level"), "activity_level", activity_options)

        form = card(
            ft.Row([name_field], spacing=8),
            ft.Row([dob_field, height_field], spacing=8),
            ft.Row([sex_field, activity_field], spacing=8),
            ft.Container(height=6),
            ft.Row(
                [
                    primary_button(
                        t("Save profile"), on_click=lambda _: self._save_form(), expand=True
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
                            ft.Icon(ft.Icons.ARROW_BACK, color=ACCENT, size=16),
                            ft.Text(t("Home"), color=ACCENT, size=12, weight=ft.FontWeight.W_700),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=lambda _: self.handle_back(),
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text(t("Settings"), size=18, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Container(width=60),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Column(
            [
                header,
                ft.Container(height=10),
                section_title(t("Your data")),
                ft.Container(height=4),
                form,
                ft.Container(height=14),
                section_title(t("Derived metrics")),
                ft.Container(height=4),
                self._metrics_row(profile, latest_weight),
                ft.Container(height=14),
                section_title(t("Weight")),
                ft.Container(height=4),
                self._weight_section(),
                ft.Container(height=14),
                section_title(t("Backup")),
                ft.Container(height=4),
                self._backup_section(),
                ft.Container(height=14),
                section_title(t("Data")),
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
