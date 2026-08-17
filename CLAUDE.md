# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IronFlet — **English-only** weight-training tracker (default routine: 7-phase, 24-week periodized program from CambiaTuFísico) with a food diary on top. Built with **Flet** (`flet[all]>=0.25,<0.30`) on Python `>=3.10,<3.13`.

There is no translation layer. `i18n.py` was deleted: no `t()`, no `t_exercise()`, no `ES` dict, no language toggle, no `lang` preference. All user-visible strings are plain English literals in the views. Two helpers survived that move and are **not** translation:

- `exercises.py` — `exercise_key()` (the DB key contract, see below) and `phase_color()`.
- `dates.py` — `day_name(idx)`, `month_name(idx)`, `weekday_label(idx)` and the `DAYS`/`MONTHS`/`WEEKDAYS` arrays. Not in `data.py`, not in `home.py`.

**Storage is PostgreSQL, not SQLite.** The database is shared with a Telegram coaching bot in `../agente/`, so both write the same training history, nutrition log and user routines. The app needs the database reachable — see Storage below. Desktop and web work; an offline APK does not, since it would have no database to talk to.

## Commands

```bash
# Desktop (default)
flet run                  # or: python main.py

# Web browser mode — loopback by default, port 8550
IRONFLET_WEB=1 python main.py
```

Web mode binds `IRONFLET_HOST` (default `127.0.0.1`) on `IRONFLET_PORT` (default `8550`). Both are overridable so a second instance can run for testing without stopping the `ironflet-web` systemd unit. Nothing here is meant to be reachable from the network.

Use the Makefile rather than raw commands:

```bash
make deps     # uv sync --group dev, THEN scripts/vendor_canvaskit.py (order matters)
make check    # lint + test, exactly what CI runs
make test     # .venv/bin/python -m pytest -q
make fmt      # ruff format + ruff check --fix
make run      # IRONFLET_WEB=1 python main.py
make deploy   # stops bot+panel, restarts ironflet-web, starts them back
```

`make deps` order is load-bearing: CanvasKit's ~12 MB of assets are not a Python package — `scripts/vendor_canvaskit.py` fetches them into the *installed* `flet_web` and patches `flutter_bootstrap.js`. Any reinstall of `flet_web` wipes both and the app silently goes back to downloading CanvasKit from Google, which fails in a gym with no signal.

`make deploy` stops `entrenador-bot` and `entrenador-panel` first on purpose: they hold live SQLAlchemy pools against the shared database, and a schema change would take an ACCESS EXCLUSIVE lock that blocks their next query.

CI (`.github/workflows/ci.yml`) runs, on Python 3.12:

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q          # 340 tests
```

## Architecture

### Navigation & view contract

`main.py` owns the only routing. It constructs **eight** views once, wires a five-slot `NavigationBar`, and exposes an imperative API via `page.data`.

View indices are frozen — `views/home.py` calls `navigate_to(2)` and `navigate_to(5)` by number — so the bar does not index the view list directly. `NAV_TABS` maps a bar slot to a view index:

| idx | view | class | on the bar? |
|-----|------|-------|-------------|
| 0 | Home | `HomeView` | slot 0 "Home" |
| 1 | Plan | `PlanView` | slot 1 "Plan" |
| 2 | Train | `WorkoutView` | slot 2 "Train" |
| 3 | Browse | `BrowseView` | no |
| 4 | History | `HistoryView` | slot 4 "History" |
| 5 | Profile | `ProfileView` | no |
| 6 | Nutrition | `NutritionView` | slot 3 "Food" |
| 7 | Routines | `RoutineEditorView` | no |

```python
NAV_TABS = (0, 1, 2, 6, 4)
```

Browse, Profile and Routines are reached from inside other screens. Adding a bar destination means appending to both the `destinations` list and `NAV_TABS`, in the same slot order — never renumber the view list.

`page.data` carries five entries:

- `navigate_to(idx, refresh=True)` — switch view, sync the bar if `idx in NAV_TABS`, call `on_show()`, rebuild
- `refresh_current()` — re-render the active view in place
- `store` — shared `Storage` instance
- `set_routine(rid)` — set the active routine, persist the `routine` pref, reset workout/plan flow state, re-render
- `edit_routine(pk)` — jump straight into a routine in the editor (`navigate_to(7, refresh=False)` then `open_routine(pk)`), skipping the library screen

Every one of the eight view classes implements:

- `build() -> ft.Control` — pure render from `self.*` state; called on every refresh
- `on_show()` — hook for tab activation (most are no-ops; `build` reads storage each render)
- `handle_back() -> bool` — consume Esc/Android back; return `True` to absorb, `False` to let `main` fall back to Home

**State lives on the view instance** (e.g. `self.selected_phase_idx`, `self.ex_idx`, `self.sets`). Navigation inside a tab is done by mutating that state and calling `refresh_current()` — views do **not** push/pop routes. When adding a sub-screen, extend `handle_back()` to unwind one level of state per back press.

### Storage

`storage.py` uses **SQLAlchemy 2.x over PostgreSQL 17**. The URL comes from `DATABASE_URL`, falling back to `postgresql+psycopg://entrenador@127.0.0.1:5432/entrenador`. The container is defined in `../docker-compose.yml` and listens on loopback only.

```bash
cd .. && docker compose up -d
```

Views never touch the ORM; they go through `Storage` methods and the module-level facades in `nutrition.py` / `routine_builder.py`. Tables are created via `Base.metadata.create_all` on every `Storage()` instantiation. **Twelve tables are declared on this repo's side**, spread over three modules that all share `storage.Base`:

`storage.py`
- `entrenos` — one row per exercise and date. `series` is JSON: a `list[dict]` with `{"weight": float, "reps": int}` plus **optional** `"rir"` (reps in reserve) and **optional** `"type"` (see `set_types.py`). Neither key is guaranteed — read with `.get()`, never assume presence.
- `pesos` — body weight, one row per day (the date is the primary key, so a second weigh-in corrects the first instead of duplicating it).
- `perfil` — single row (id = 1) with name, birthdate, height, sex, activity level.
- `preferencias` — key-value store (`get_pref`, `set_pref`). The only key in use is `routine`.

`nutrition.py` — `foods`, `servings`, `food_log`, `nutrition_targets`.

`routine_builder.py` — `user_routines`, `user_routine_phases`, `user_routine_days`, `user_routine_exercises`. Declared on `storage.Base`, but `ensure_tables(store)` also runs `create_all` lazily (guarded by a `WeakSet` of engines) because `Storage.__init__` may fire before this module is imported.

#### THE CRITICAL RULE: the schema is duplicated by hand

The database is one, but the SQLAlchemy models exist **twice**: here, and in `../agente/entrenador/modelos.py`, which mirrors all twelve tables (plus six of its own: `recordatorios`, `medidas`, `adherencia`, `sesiones`, `checkins`, `conversacion`).

**Nobody runs migrations.** Each program calls `create_all()` at start-up and whichever arrives first creates the table. If the two declarations differ, `create_all` neither detects nor repairs it — it stays silent, and the other process dies later with an `UndefinedColumn` halfway through a query.

So: **change a column here, change it there in the same commit.** This is now watched by `../agente/tests/test_modelos_espejo.py`, which compares *metadata* — columns, types, nullability, defaults, primary keys, foreign keys with their ON DELETE, unique constraints and indexes — for every table present on both sides, and asserts no app table is left undeclared in the bot. When it fails, sync the two files. Never relax the comparison.

Other consequences of the shared database:

- Keep set dicts open to extra keys. Anything reading sets must tolerate keys it does not know, and must not rewrite rows it did not create.
- `delete_weight()` takes the **date**, not a numeric id: one weigh-in per day.
- Rows written by the bot have no `"type"` on their sets. They are real work; treating an untyped set as anything but normal rewrites history.

#### Metrics live in analytics.py

`storage.py` computes nothing itself. `get_week_stats()` delegates to `analytics.session_count()`, `working_sets()` and `total_volume()`; `get_streak()` delegates to `analytics.training_streak()`. Two definitions differ from what an older reader might expect:

- **`get_streak()` returns consecutive WEEKS, not days.** A week counts when it holds at least `min_sessions` distinct training days; the current unfinished week is skipped rather than failed. Counting days cannot describe a plan with rest days — the old version reset every weekend by design.
- `min_sessions` defaults to `weekly_session_minimum()`, derived from the **active routine's** lightest phase (`days_by_phase`, not `week_rotation`). Any hardcoded number is wrong in some phase of some routine.
- `sessions` counts distinct training *days*, not rows — `entrenos` holds one row per exercise, so a six-exercise session used to render as "6 Sessions". Sets and volume exclude warm-ups.

### The four analysis/data modules

None of them import Flet or open a database on import: plain data in, plain data out, so they unit-test without a running app and the Telegram coach can reuse them.

**`analytics.py`** — the single implementation of every training metric. Epley 1RM (`estimated_1rm`, `best_e1rm`, `e1rm_progression`), typed personal records (`PRKind`, `Record`, `PersonalRecords`, `personal_records`, `all_personal_records`, `detect_new_records`), sets per muscle group (`resolve_muscles`, `MuscleVolume`, `sets_per_muscle_group`), `session_count`, `training_streak`, `week_stats`, `moving_average` for body weight, plus `working_sets`/`volume`/`total_volume`/`is_warmup`. Use it for **anything numeric about training**; do not recompute a metric in a view. `views/workout.py` uses `detect_new_records`, `views/history.py` the rest.

**`nutrition.py`** — food catalogue, named servings, meal diary and versioned targets. Views use the module-level facade (`search_foods`, `favourite_foods`, `log_food`, `delete_entry`, `day_entries`, `day_totals`, `targets_for`, `copy_previous_day`), which resolves a per-store `Nutrition` instance; the class is there for the bot. Two invariants you must not "clean up":
- **Macros in `food_log` are frozen at insert time** — the row stores that portion's kcal/protein/fat/carbs/fibre and the food name, not a pointer to the catalogue. Editing a food next month must not rewrite last Tuesday's lunch.
- **Targets are versioned by start date**, never overwritten; `targets_for(day)` picks the newest row already in effect. The plan changes intake mid-course, and a mutable row would retroactively falsify past adherence.
- Everything is per 100 g on the **European label convention**: `carbs` excludes fibre. USDA "carbohydrate, by difference" includes it — subtract fibre before copying a USDA number in, or carb totals come out ~10 % high.

**`set_types.py`** — `SetType` (`warmup` / `normal` / `drop` / `failure`), stored under the optional `"type"` key, plus automatic rest. `parse_set_type`, `set_type_of`, `counts_as_work`, `working_sets`, `warmup_sets`, `count_by_type`, `tag_set`, `label_for`, `next_set_type`; rest via `parse_prescribed_rest`, `rest_seconds`, `rest_seconds_for_phase`, `format_rest`, `is_compound`. Two rules: **absent `"type"` means normal** (every pre-existing row, and everything the bot writes, has no type and is real work), and **only warm-ups are discounted** — a drop set and a set to failure are work; the label says *how*, not *whether*. Rest defaults (`REST_COMPOUND_S = 180`, `REST_ISOLATION_S = 90`) must match `../agente/entrenador/sesion_viva.py::descanso_de`; `tests/test_set_types.py` loads the coach's constants and compares, so a divergence fails a test instead of showing Alex two different rests.

**`routine_builder.py`** — user-created routines in the database, so Alex can write one instead of only reading `data.py`'s four constants. `new_draft`, `draft_from_builtin`, `load_draft`, `save_draft`, `delete_routine`, `duplicate_builtin` / `duplicate_user_routine` / `duplicate_routine`, `list_user_drafts`, `list_user_routines`, `sync_user_routines`, plus `parse_exercise` / `format_exercise` / `canonical_name`. The design point: `_materialize()` does **not** wrap rows in a lookalike — it builds real `data.Routine` / `data.Phase` / `data.TrainingDay` dataclasses, so a stored routine *is* a `Routine` and no view can tell the difference. `sync_user_routines()` splices them into `data.ROUTINES` by **slice assignment**, not rebinding, because `views/plan.py` does `from data import ROUTINES` and holds a reference to that list object. Stored routines get ids namespaced `user:<pk>` (`is_user_routine`, `routine_pk`).

### Routines & static program data

`data.py` exposes `ROUTINES: list[Routine]` — each `Routine` bundles its own `phases`, `days_by_phase` and (optionally) `week_rotation`. The active routine is a module-level global set via `set_active_routine(rid)`; views call `active_routine()`. Four are shipped as constants, and `sync_user_routines()` appends any stored ones:

- `"cambiatufisico"` — 7-phase/24-week periodized (default). The only one with `week_rotation`.
- `"upper-lower"` — 4-day split, 2 phases, 12 weeks.
- `"push-pull-legs"` — 6-day split, 2 phases, 12 weeks.
- `"recomp-ppl-ul"` — 5-day PPL + Upper/Lower, 3 phases, 6 weeks. Lean bulk; the routine the Telegram coach follows.

There were eight until 0.2.0, when the four `women-*` routines went: this is a single-user app and Alex is the user. That is what moved the key counts below. Only four exercises stopped being prescribed by any routine — `HIIT Intervals`, `Hyperextensions`, `Leg Raises` and `Triceps Kickback` — and all four are still in `EXERCISE_CATALOG`, so Browse and the routine editor still offer them.

Exercise strings in `days_by_phase` can carry trailing `[scheme]` brackets (`"Squat [5×12,10,8,8,8]"`) and tag brackets like `[comp]` or `[triple drop]`, plus a trailing `*`. `exercises.exercise_key()` strips all of it to produce the DB key. Plan's "Distribution" tab renders only when the active routine has a `week_rotation` **and** the selected phase id is in `(1, 2, 3)`.

When adding a routine: append to `ROUTINES`, keep exercise names spelled exactly as existing ones (see the key contract), and — if images are wanted — make sure the name exists in `exercise_images.EXERCISE_IMAGE`. Adding exercises changes the counts frozen in `tests/test_exercise_key.py`; update those constants deliberately, never to make a red test go green.

### `exercise_key()` — the most fragile contract in the system

`exercises.exercise_key()` turns `"Squat [5×12,10,8,8,8]"` into `"Squat"`, and **that stripped name is the value stored in `entrenos.ejercicio`**. It strips trailing `[..]` bracket groups and a trailing `*`, then rstrips.

Why it matters:

- **219 distinct routine strings across the four routines collapse into exactly 100 keys.** That collapse *is* the progression: `Squat [4×8-10]` in phase 2 and `Squat [5×5]` in phase 6 are the same exercise and must aggregate into one history.
- **The Telegram coach writes the same column.** Its 28 exercises in `../agente/entrenador/entrenos.py` (`EJERCICIOS`, via `a_canonico()`) all resolve to keys this function produces.

If the normalisation drifts, **nothing raises**. Rows simply stop matching: the app writes one key, the bot another, and the history the whole plan depends on quietly splits in two.

`tests/test_exercise_key.py` freezes it — `CADENAS_ESPERADAS = 219`, `CLAVES_ESPERADAS = 100`, idempotence, no leftover brackets or `*`, and a cross-repo check that every bot exercise exists in the app's routines (reading the bot's file with `ast`, never importing it, so production `.env` credentials stay out of the pytest process). Treat a failure there as a data-integrity incident, not a formatting nit.

### Theme

`theme.py` no longer exports loose colour constants. **The compatibility aliases (`ACCENT`, `CARD_BG`, `TEXT`, …) were deleted** — being module constants bound to `LIGHT` at import time, any view importing one silently stopped following the active palette.

- `Palette` — a frozen dataclass whose field names describe the **role**, never the colour: `bg_page`, `bg_surface`, `bg_sunken`, `bg_nav`, `border`, `border_strong`, `text`, `text_secondary`, `text_muted`, `accent`, `accent_2`, `accent_soft`, `on_accent`, `success`, `warning`, `danger`, `chart_bar`, `shadow`, `phase` (a 7-tuple).
- `LIGHT` is **the default** — this app is used in daylight, in a gym, on a phone. `DARK` also exists and also passes AA.
- `C` — a proxy that reads through to the active palette at *attribute-access* time. Views do `from theme import C` at import; `set_palette()` then takes effect without reimporting anything.
- `set_palette(palette)` / `apply_theme(page, palette=LIGHT)`. Use `apply_theme`: it sets the palette, `page.theme_mode`, `page.bgcolor` **and** an explicit `ft.ColorScheme`. Skip the ColorScheme and Flet derives a tonal Material 3 palette from a seed, so every dialog, text field and dropdown comes out in shades matching nothing.

**No view may write a hex value.** Every colour goes through `C`, including phase colours — `exercises.phase_color(phase_id)` indexes `C.phase`, so the phase is the *index* and the theme decides the shade (`Phase.color` in `data.py` still holds the original black-background values; `#FFD93D` is 1.38:1 on a white card, i.e. invisible). Factory helpers `card`, `chip`, `primary_button`, `ghost_button`, `section_title`, `muted_text` resolve their defaults **inside the call** for the same reason — a default evaluated in the `def` would freeze the import-time palette.

`tests/test_theme.py` recomputes WCAG contrast for every foreground/background pair in both palettes (AA: 4.5:1 body, 3:1 large text and UI edges; worst pair in LIGHT is 4.59:1), checks the phase hues stay mutually distinguishable, checks the proxy follows `set_palette`, and checks the helpers do not freeze the default colour.

### Components & other modules

- `components/timer.py` — `RestTimer` uses `page.run_task` with a `_tick_id` generation counter to cancel stale loops when restarted (no threads).
- `components/charts.py` — `bar_chart` composed purely from `ft.Container` heights; deliberately avoids external plotting deps.
- `health.py` — age, BMI, BMR, TDEE, protein target. All inputs optional; returns `None` on missing/invalid input.
- `guides.py` — in-app reference tips (training, nutrition), rendered by `views/guide_dialog.py`. `views/home.py` builds one card per entry, so adding or dropping a guide needs no layout change.
- `exercise_details.py` — per-exercise metadata; `analytics.resolve_muscles()` reads it to attribute sets to muscle groups.

### Exercise images

`exercise_images.EXERCISE_IMAGE` maps canonical English exercise names to Free Exercise DB slugs (github.com/yuhonas/free-exercise-db, Unlicense / public domain).

**Images are not committed** — `.gitignore` excludes `assets/exercises/`. `asset_manager.py` downloads one tarball attached to a GitHub Release and extracts it into `assets/exercises/<slug>/`; `views/profile.py` drives that download and shows progress.

`image_for(key)` returns an **assets-relative** path — `/exercises/<slug>/0.jpg` — or `None`; `image_frames(key)` returns two frames for animation, falling back to frame 0 twice when a slug only ships one.

**Never go back to `file://` URLs.** They worked on desktop and made every image invisible in web mode, which is how this app is actually used: the browser refuses with *"Not allowed to load local resource"* and each exercise renders as blank space that reads like a layout bug. Under `assets/` Flet serves the frames over HTTP from the page's own origin. `tests/test_exercise_images.py` fails if a `file://` ever comes back.

Composite/superset names (containing `+`, or prefixed `Bi-set:` / `SS:` / `Triset:`) deliberately get no image — they render blank space, which is correct.

`EXERCISE_IMAGE` is also the key into `exercise_details.py`: `details_for()` looks the slug up there. So changing a slug moves the photo **and** the muscle data, and a slug the details table does not carry silently drops that exercise out of `sets_per_muscle_group`. Change one, check the other — that is how `Behind-Neck Lat Pulldown` briefly lost its muscles while gaining the right photo. `Bulgarian Split Squat` maps to nothing on purpose: the 500-exercise source has no such movement, and a confidently wrong photo is worse than none.

## Traps

Things that break quietly if you do not know them:

1. **Renumbering views.** `home.py` hardcodes `navigate_to(2)` and `navigate_to(5)`. Reorder `view_list` and the app navigates to the wrong screen with no error. Add to the end; adjust `NAV_TABS`, never the indices.
2. **Editing a model on one side only.** See the critical rule above. `create_all()` will not save you; `agente/tests/test_modelos_espejo.py` will.
3. **Touching `exercise_key()` normalisation.** Silent history split, no exception. Frozen in tests for exactly this reason.
4. **Assuming set keys exist.** `"rir"` and `"type"` are both optional and both absent on everything the bot writes.
5. **Treating an untyped set as a warm-up.** Absent means *normal*. The inverse rewrites Alex's tonnage.
6. **Writing a hex in a view**, or reintroducing a module-level colour constant. Both bypass the palette and break dark mode.
7. **Reimplementing a metric in a view.** `analytics.py` is the single implementation; `storage.py` only fetches rows and supplies arguments.
8. **Expecting `get_streak()` in days.** It is weeks.
9. **Rebinding `data.ROUTINES`** instead of slice-assigning. `views/plan.py` holds a reference to the list object.
10. **Editing rest defaults on one side.** `set_types.REST_COMPOUND_S` / `REST_ISOLATION_S` must match the coach's `sesion_viva.py`.
11. **`uv sync` after `vendor_canvaskit.py`.** It reinstalls `flet_web` and wipes the vendored CanvasKit. Run `make deps`, which orders them correctly.
12. **Schema changes while the bot is running.** Stop `entrenador-bot` and `entrenador-panel` first (`make deploy` does).
13. **Importing anything from `../agente/`** in a test. `entrenador.config` loads the production `.env` and puts real credentials and the production `DATABASE_URL` in the environment. Parse the file with `ast`, as `tests/test_exercise_key.py` does.

### Flet version caveat

Pinned to `flet[all]>=0.25,<0.30` — `flet[all]`, not plain `flet`, because web mode needs `flet-web` and a bare `uv sync` would otherwise uninstall it. The API (`ft.Colors`, `ft.Icons`, `page.run_task`, `ft.NavigationBarDestination`, `ft.ColorScheme`) matches 0.25–0.29. If a newer Flet release renames something, update the pin rather than silently adapting to a new API.

## Tests

`.venv/bin/python -m pytest -q` — **340 tests**, `testpaths = ["tests"]`, `asyncio_mode = "auto"`:

`test_analytics.py`, `test_exercise_images.py`, `test_exercise_key.py`, `test_health.py`, `test_nutrition.py`, `test_nutrition_view.py`, `test_routine_builder.py`, `test_set_types.py`, `test_smoke.py`, `test_storage_metrics.py`, `test_theme.py`.

Without `DATABASE_URL` the run is `238 passed, 102 skipped`: the skips are every test that needs PostgreSQL. Judge a run by the skip count, not the pass count — a green suite that skipped 102 tests has verified nothing about storage.

The bot's suite in `../agente/` (**82 tests**, pytest available there via its own `requirements-dev.txt`) includes `test_modelos_espejo.py`, the cross-repo schema guard. Anything that changes a shared table must be run against both.
