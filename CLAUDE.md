# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IronLog — bilingual (EN/ES) weight-training tracker (7-phase, 24-week periodized routine from CambiaTuFísico). Built with **Flet** (`>=0.25,<0.30`) on Python `>=3.10,<3.13`. Targets desktop and Android; no backend.

All source strings are **canonical English**. Spanish is provided via the `ES` dict in `i18n.py`; the UI has a language toggle (home header) that persists in the `prefs` table.

## Commands

```bash
# Desktop (default)
flet run                  # or: python main.py

# Web browser mode (port 8550, binds 0.0.0.0)
IRONLOG_WEB=1 python main.py

# Android build (package: com.ironlog.app, configured in pyproject.toml)
flet build apk
```

No tests, linter, or formatter are configured — do not invent commands for them.

## Architecture

### Navigation & view contract

`main.py` owns the only routing. It constructs the four views once, wires a `NavigationBar`, and exposes an imperative API via `page.data`:

- `page.data["navigate_to"](idx)` — switch tab and rebuild
- `page.data["refresh_current"]()` — re-render the active view in place
- `page.data["store"]` — shared `Storage` instance

Each view class (`HomeView`, `PlanView`, `WorkoutView`, `HistoryView`) must implement:

- `build() -> ft.Control` — pure render from `self.*` state; called on every refresh
- `on_show()` — hook for tab activation (most are no-ops; `build` reads storage each render)
- `handle_back() -> bool` — consume Esc/Android back; return `True` to absorb, `False` to let `main` fall back to Home

**State lives on the view instance** (e.g., `self.selected_phase_idx`, `self.ex_idx`, `self.sets`). Navigation inside a tab is done by mutating that state and calling `refresh_current()` — views do **not** push/pop routes. When adding a new sub-screen, extend `handle_back()` to unwind one level of state per back press.

### Storage

`storage.py` uses **only** `sqlite3` from stdlib (a design choice — no ORM, no external DB deps). DB path resolution:

1. `$FLET_APP_STORAGE_DATA` if set (Flet provides this on Android)
2. Otherwise `cwd/ironlog.db`

Two tables, both created via `CREATE TABLE IF NOT EXISTS` on every `Storage()` instantiation:

- `workouts` — rows keyed by `exercise` (canonical English name, no brackets/stars) + date. Sets stored as JSON in `sets_json`. `WorkoutEntry.sets` is a `list[dict]` with `{"weight": float, "reps": int}`.
- `prefs` — simple key-value store (`get_pref`, `set_pref`). Currently used for `lang`.

**Important**: the exercise DB key is the bare name returned by `i18n.exercise_key()` — trailing `[..]` brackets and `*` markers are stripped before insert. This aggregates progression across Phase 5/6/7 (same exercise, different scheme).

### i18n

`i18n.py` is a flat dict-based translator. Code uses English literals; `ES` maps them to Spanish. Active language is a module-level global set by `i18n.set_language(lang)`; changing it requires re-rendering views (done by `page.data["set_language"]` which updates nav labels and calls `refresh_current`).

Three helpers to know:
- `t(text)` — plain string translation; returns input unchanged if no entry.
- `t_exercise(s)` — splits trailing `[..]` brackets and `*` off the name, translates the name via `t()`, and reattaches. Also translates in-bracket tokens (`max ↔ máx`, `failure ↔ fallo`, `triple drop ↔ triple desc`).
- `exercise_key(s)` — strips brackets/`*` to produce the canonical DB key.

Day/month abbreviations use `day_name(idx)`, `month_name(idx)`, `weekday_label(idx)` — per-language arrays live in `i18n.py`, **not** in `data.py` or `home.py`.

### Routines & static program data

`data.py` exposes `ROUTINES: list[Routine]` — each `Routine` bundles its own `phases`, `days_by_phase`, and (optionally) `week_rotation`. The active routine is a module-level global set via `set_active_routine(rid)`; views call `active_routine()` to read it. Currently two:

- `"cambiatufisico"` — 7-phase/24-week periodized (default).
- `"upper-lower"` — 4-day split, 2 phases, 12 weeks. No `week_rotation`.

When adding a routine: append to `ROUTINES`, add day-name translations to `i18n.ES`, and (if images are wanted) ensure exercise names already exist in `exercise_images.EXERCISE_IMAGE`.

Exercise strings in `days_by_phase` can include trailing `[scheme]` brackets (e.g. `"Squat [5×12,10,8,8,8]"`) and additional tag brackets like `[comp]` or `[triple drop]`. `i18n.t_exercise()` splits them off, translates the name, and reattaches; `i18n.exercise_key()` produces the canonical DB key by stripping brackets and `*`. Plan's "Distribution" tab is shown only when the active routine has a `week_rotation` **and** the selected phase id is in 1–3.

### Exercise images

`exercise_images.EXERCISE_IMAGE` maps canonical English exercise names to Free Exercise DB slugs (github.com/yuhonas/free-exercise-db, Unlicense / public domain). Images live in `assets/exercises/<slug>/0.jpg` — only the first frame per exercise to keep the APK lean (~4.4 MB). `image_for(key)` returns an assets-relative path (`"/exercises/<slug>/0.jpg"`) or `None`. Flet serves `assets/` thanks to `ft.app(main, assets_dir="assets")`.

Adding a new exercise that needs an image: pick a slug that exists in the DB's `dist/exercises.json`, download `exercises/<slug>/0.jpg` into `assets/exercises/<slug>/`, and add the mapping entry. Composite/superset names (contain `+` or prefixed `Bi-set:`/`SS:`/`Triset:`) deliberately don't get an image — they render blank space, which is correct.

### Theme & components

- `theme.py` — color constants (`ACCENT`, `CARD_BG`, etc.) plus factory helpers (`card`, `chip`, `primary_button`, `ghost_button`, `section_title`, `muted_text`). Reuse these instead of building raw `ft.Container`s so the dark palette stays consistent.
- `components/timer.py` — `RestTimer` uses `page.run_task` with a `_tick_id` generation counter to cancel stale loops when restarted (no threads).
- `components/charts.py` — bar chart composed purely from `ft.Container` heights; deliberately avoids external plotting deps.

### Flet version caveat

Pinned to `flet<0.30`. The API (`ft.Colors`, `ft.Icons`, `page.run_task`, `ft.NavigationBarDestination`) matches 0.25–0.29. If a newer Flet release renames something, update the pin rather than silently adapting to a new API.
