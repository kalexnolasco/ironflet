# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IronFlet — weight-training tracker whose **entire user-facing surface is Spanish** (default routine: 7-phase, 24-week periodized program from CambiaTuFísico) with a food diary on top. Built with **Flet** (`flet[all]>=0.25,<0.30`) on Python `>=3.10,<3.13`.

There is **still no translation layer** — the language flipped, the architecture did not. `i18n.py` stays deleted: no `t()`, no `ES` dict, no language toggle, no `lang` preference. All user-visible strings are plain Spanish literals in the views (Alex asked for it: "cambiemos a Español todo lo que ve el usuario"). What stays **English on purpose, because it is data contract rather than chrome**:

- **Exercise names and their keys** — `exercise_key()` values are shared with the bot's `entrenos.ejercicio` rows.
- **`TrainingDay.name`** — written verbatim to `entrenos.grupo` ("Chest-Biceps"); a Spanish day name would split History's grouping vocabulary.
- **Set-type keys** (`warmup`/`drop`/`failure`) — only `LABELS`/`SHORT_LABELS` are Spanish (the warm-up letter is **C**, not W).
- **Phase `scheme`/`rest` strings** — parsed by `parse_scheme`/`parse_prescribed_rest`.
- **Internal status literals** (`"empty"`, `"logged"`, `DateSource` names…).

Phase `name`/`subtitle`/`notes` ARE display and ARE Spanish — which is why the three prose parsers in `progression.py` (`parse_rir`, `parse_prescribed_step`, `_DELOAD_MARKS`) are **bilingual**: they must keep reading old English user-routine notes and the new Spanish built-ins alike. Losing one language there raises nothing; the RIR target just vanishes from every set row.

Two helpers that survived the old i18n purge and are **not** translation:

- `exercises.py` — `exercise_key()` (the DB key contract, see below) and `phase_color()`.
- `dates.py` — `day_name(idx)`, `month_name(idx)`, `weekday_label(idx)` and the `DAYS`/`MONTHS`/`WEEKDAYS` arrays — Spanish, lowercase on purpose ("jue, 20 ago"; capitalising them is the anglicism). Not in `data.py`, not in `home.py`.

**Storage is one SQLite file, on the phone.** As of 0.13 this is a phone-only app: the PC build, the web mode and the Telegram bot in `../agente/` were all retired, and with them the shared PostgreSQL, the hand-mirrored schema across two repos, and the rule about who may advance `recordatorios.proxima`. One app, one database, one owner.

What that retirement removed, so nobody re-adds it by pattern-matching old docs:

- No `DATABASE_URL` pointing at a server, no `docker compose`, no `psycopg`.
- No `IRONFLET_WEB`, no `flet[all]`, no vendored CanvasKit, no `scripts/vendor_canvaskit.py`, no systemd units.
- No cross-repo schema mirror and no `agente/tests/test_modelos_espejo.py` to keep in sync.
- **No skipped tests.** The suite used to skip 211 of them — everything touching storage — on any machine without a live server. They all run now, on the same engine the phone uses.

## Commands

```bash
make deps     # uv sync --group dev
make check    # lint + test, exactly what CI runs
make test     # the whole suite on SQLite — no Docker, nothing skipped
make fmt      # ruff format + ruff check --fix
make run      # the app on the desktop, against the local SQLite. Development only.
make apk      # rm -rf build && flet build apk -v (all three ABIs)
make install  # adb install -r build/apk/app-release.apk
```

`make apk` deletes `build/` first and that is not tidiness: deleting only
`build/flutter` leaves flet with half a state and it dies on a
`FileNotFoundError` that names the directory rather than the problem.

CI (`.github/workflows/ci.yml`) runs, on Python 3.12:

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q          # 1742 tests, 1 skipped (a network test, opt-in)
```

## Architecture

### Navigation & view contract

`main.py` owns the only routing. It constructs **ten** views once, wires a five-slot `NavigationBar`, and exposes an imperative API via `page.data`.

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
| 8 | Backup & data | `DataView` | no |
| 9 | Coach | `AgentView` | no |
| 10 | Fotos | `PhotosView` | no |

```python
NAV_TABS = (0, 1, 2, 6, 4)
```

Browse, Profile, Routines, Backup and Coach are reached from inside other screens. Adding a bar destination means appending to both the `destinations` list and `NAV_TABS`, in the same slot order — never renumber the view list.

`page.data` carries five entries:

- `navigate_to(idx, refresh=True)` — switch view, sync the bar if `idx in NAV_TABS`, call `on_show()`, rebuild
- `refresh_current()` — re-render the active view in place
- `store` — shared `Storage` instance
- `set_routine(rid)` — set the active routine, persist the `routine` pref, reset workout/plan flow state, re-render
- `edit_routine(pk)` — jump straight into a routine in the editor (`navigate_to(7, refresh=False)` then `open_routine(pk)`), skipping the library screen

Every one of the ten view classes implements:

- `build() -> ft.Control` — pure render from `self.*` state; called on every refresh
- `on_show()` — hook for tab activation (most are no-ops; `build` reads storage each render)
- `handle_back() -> bool` — consume Esc/Android back; return `True` to absorb, `False` to let `main` fall back to Home

**State lives on the view instance** (e.g. `self.selected_phase_idx`, `self.ex_idx`, `self.sets`). Navigation inside a tab is done by mutating that state and calling `refresh_current()` — views do **not** push/pop routes. When adding a sub-screen, extend `handle_back()` to unwind one level of state per back press.

### Storage

`storage.py` uses **SQLAlchemy 2.x over one SQLite file**. `resolve_db_url()` decides: an explicit argument, then `DATABASE_URL` (which the tests use to name a temporary file — an app that cannot be told "use THIS database" cannot be debugged), then `sqlite_path()`. On Android that is the app's private storage; on the desktop, next to the project.

SQLAlchemy is overkill for one SQLite and stays anyway: it is written, tested and costs nothing, and rewriting it to raw `sqlite3` would trade working code for code that needs re-proving. What is NOT optional is `create_db_engine`'s tuning — SQLite ships foreign keys **disabled**, and this schema has real `ON DELETE` cascades. A test fixture that built its engine with a bare `create_engine()` is exactly how a food-log row survived pointing at a deleted food; the fixture now goes through `create_db_engine` like the app does.

Views never touch the ORM; they go through `Storage` methods and the module-level facades in `nutrition.py` / `routine_builder.py`. Tables are created via `Base.metadata.create_all` on every `Storage()` instantiation. **Thirteen tables are declared on this repo's side**, spread over three modules that all share `storage.Base`:

`storage.py`
- `entrenos` — one row per exercise and date. `series` is JSON: a `list[dict]` with `{"weight": float, "reps": int}` plus **optional** `"rir"` (reps in reserve) and **optional** `"type"` (see `set_types.py`). Neither key is guaranteed — read with `.get()`, never assume presence.
- `pesos` — body weight, one row per day (the date is the primary key, so a second weigh-in corrects the first instead of duplicating it).
- `perfil` — single row (id = 1) with name, birthdate, height, sex, activity level.
- `preferencias` — key-value store (`get_pref`, `set_pref`). Holds `routine`, the workout draft, and the coach's settings.
- `fotos` — one progress photo per day (date PK). The row stores a bare FILENAME resolved against `fotos.directorio()`; the JPEG bytes live on disk, compressed by `fotos.guardar()` (Pillow, ≤1600 px). Backups carry the metadata; the bytes travel in the separate photos zip (`fotos.exportar_zip`).

##### `SECRET_PREF_KEYS` — the prefs that must never leave the device

`preferencias` is a general bag and **both** exporters copy every row into the backup document verbatim. That was harmless while the only key was `routine`; it stopped being harmless when the in-app coach put an Anthropic API key there, because a backup is a plain JSON file that gets sent over a chat app.

`storage.SECRET_PREF_KEYS` is excluded on all four paths — `Storage.export_all()`, `backup.export_all()`, and both importers — and a `wipe=True` restore **keeps** it: the key belongs to the device, not to the document, and a restore is exactly what someone does on a new phone. It is a separate tuple from `workout_draft.EPHEMERAL_PREF_KEYS` on purpose: that one is about staleness, this one about a credential, and merging them would leave a name that describes neither.

Adding a pref that holds a secret means adding it to that tuple. Nothing warns you.

`nutrition.py` — `foods`, `servings`, `food_log`, `nutrition_targets`.

`routine_builder.py` — `user_routines`, `user_routine_phases`, `user_routine_days`, `user_routine_exercises`. Declared on `storage.Base`, but `ensure_tables(store)` also runs `create_all` lazily (guarded by a `WeakSet` of engines) because `Storage.__init__` may fire before this module is imported.

#### Migrations: `create_all()` will not add a column

**Nobody runs migrations.** `Storage()` calls `create_all()` at start-up, which creates missing *tables* and **never touches a table that already exists**. That is the sharp edge, and it bit once: `entrenos.nota` worked on every fresh database — every test, every clean install — and broke every database already out there, on the first read. On a desktop that is one `ALTER TABLE`; **on the phone there is no console**, the APK's SQLite file survives app updates, and the only other route was export/uninstall/reinstall/restore.

So `storage.add_missing_columns()` runs right after `create_all()`. Deliberately narrow, because a migration that guesses is worse than none — it **only ADDs**, never drops, renames or retypes, and it **skips `NOT NULL` and `server_default` columns** rather than half-applying them, because those need a considered migration. `tests/test_column_migration.py` builds a pre-notes database on purpose: the rest of the suite is blind to this by construction, since a fresh database is exactly the case that never breaks.

Adding a `NOT NULL` column still needs a hand-written migration, and the app will fail loudly until it exists.

Until 0.12 this section opened with a harder rule — the schema was declared **twice**, here and in the bot's `modelos.py`, and a column changed on one side only would take the other process down mid-query. That is gone with the bot: one declaration, one database. The migration discipline above stays, because it was never about the mirror.

Other rules that outlived the shared database:

- Keep set dicts open to extra keys. Anything reading sets must tolerate keys it does not know, and must not rewrite rows it did not create — old rows from the bot era have no `"type"` and are real work.
- `delete_weight()` takes the **date**, not a numeric id: one weigh-in per day.
- **`entrenos.grupo` holds the routine *day's* name, not a catalogue group.** `views/workout.py` writes `muscle_group=day.name` — "Chest-Biceps", "Shoulder-Leg". Anything else writing a row must use the same vocabulary (`agent.muscle_group_for()` does); the column takes any string, so a second vocabulary raises nothing and just groups the same session twice in History. Metrics are unaffected — `analytics.resolve_muscles()` goes through `exercise_details.py`, never this column.
- **`save_workout()` always INSERTs; `replace_workout()` is the upsert.** There is no unique constraint on `(fecha, ejercicio)` — a superset legitimately writes two rows under different names — so a second save of the same exercise on the same day silently doubles every metric that sums it. The training screen owns the session it writes and calls `save_workout()`; anything re-submittable (the coach's confirmation card, where Alex can Save, spot a typo and Save again) must call `replace_workout()`.

#### Metrics live in analytics.py

`storage.py` computes nothing itself. `get_week_stats()` delegates to `analytics.session_count()`, `working_sets()` and `total_volume()`; `get_streak()` delegates to `analytics.training_streak()`. Two definitions differ from what an older reader might expect:

- **`get_streak()` returns consecutive WEEKS, not days.** A week counts when it holds at least `min_sessions` distinct training days; the current unfinished week is skipped rather than failed. Counting days cannot describe a plan with rest days — the old version reset every weekend by design.
- `min_sessions` defaults to `weekly_session_minimum()`, derived from the **active routine's** lightest phase (`days_by_phase`, not `week_rotation`). Any hardcoded number is wrong in some phase of some routine.
- `sessions` counts distinct training *days*, not rows — `entrenos` holds one row per exercise, so a six-exercise session used to render as "6 Sessions". Sets and volume exclude warm-ups.

### The six analysis/data modules

None of them import Flet or open a database on import: plain data in, plain data out, so they unit-test without a running app and the Telegram coach can reuse them.

**`analytics.py`** — the single implementation of every training metric. Epley 1RM (`estimated_1rm`, `best_e1rm`, `e1rm_progression`), typed personal records (`PRKind`, `Record`, `PersonalRecords`, `personal_records`, `all_personal_records`, `detect_new_records`), sets per muscle group (`resolve_muscles`, `MuscleVolume`, `sets_per_muscle_group`), `session_count`, `training_streak`, `week_stats`, `moving_average` for body weight, plus `working_sets`/`volume`/`total_volume`/`is_warmup`. Use it for **anything numeric about training**; do not recompute a metric in a view. `views/workout.py` uses `detect_new_records`, `views/history.py` the rest.

**`nutrition.py`** — food catalogue, named servings, meal diary and versioned targets. Views use the module-level facade (`search_foods`, `favourite_foods`, `log_food`, `delete_entry`, `day_entries`, `day_totals`, `targets_for`, `copy_previous_day`), which resolves a per-store `Nutrition` instance; the class is there for the bot. Two invariants you must not "clean up":
- **Macros in `food_log` are frozen at insert time** — the row stores that portion's kcal/protein/fat/carbs/fibre and the food name, not a pointer to the catalogue. Editing a food next month must not rewrite last Tuesday's lunch.
- **Targets are versioned by start date**, never overwritten; `targets_for(day)` picks the newest row already in effect. The plan changes intake mid-course, and a mutable row would retroactively falsify past adherence.
- Everything is per 100 g on the **European label convention**: `carbs` excludes fibre. USDA "carbohydrate, by difference" includes it — subtract fibre before copying a USDA number in, or carb totals come out ~10 % high.

**`set_types.py`** — `SetType` (`warmup` / `normal` / `drop` / `failure`), stored under the optional `"type"` key, plus automatic rest. `parse_set_type`, `set_type_of`, `counts_as_work`, `working_sets`, `warmup_sets`, `count_by_type`, `tag_set`, `label_for`, `next_set_type`; rest via `parse_prescribed_rest`, `rest_seconds`, `rest_seconds_for_phase`, `format_rest`, `is_compound`. Two rules: **absent `"type"` means normal** (every pre-existing row, and everything the bot writes, has no type and is real work), and **only warm-ups are discounted** — a drop set and a set to failure are work; the label says *how*, not *whether*. Rest defaults (`REST_COMPOUND_S = 180`, `REST_ISOLATION_S = 90`) used to be mirrored in the retired bot's `sesion_viva.py`, and `tests/test_set_types.py` still compares against it **when that file happens to be on disk** (`skipif` otherwise). With the bot gone these are the only definition; the comparison is a leftover that costs nothing and will skip itself the day `../agente/` is deleted.

**`gym_tools.py`** — the barbell arithmetic. `plate_breakdown` (which plates per side, honest about a target that cannot be assembled: `exact`, `delta`, `describe()`), `loadable_options` (the nearest assemblable weights *with* their breakdowns — what the set row shows), `round_to_loadable`, `warmup_plan` (percentage ramp, every rung a weight the room can actually build), `bar_for_exercise` (the EZ bar is 7.5 kg, not 20), `percentage_table` / `weight_for_reps` / `predicted_reps`. Two rules: the inventory is counted in **pairs**, because a widowed 20 kg plate cannot be loaded; and the internal arithmetic is in integer centi-kilos, because `2.5 + 1.25 + 1.25` in binary float stops being 5.0 after a few additions and the solver compares totals.

**`progression.py`** — Alex's own rule, which lived in prose inside `data.py` ("Double progression: hit the top of the rep range on every set, then add 2.5 kg upper / 5 kg lower"), turned into code. `recommend` / `recommend_from_store` return a `Recommendation` carrying an `Action`, a weight, per-set targets, a `Confidence` and a `reason` written in English that quotes the actual previous session. `prescribed_target` produces the "5-8 reps @ RIR 2-3" the set row shows; `parse_scheme` reads the `[4×5-8]` bracket; `weight_step` picks the increment by equipment; `is_deload` stops a recovery week being read as a week of PRs. **It refuses to answer rather than guess**: no history is `BASELINE` with no weight, a three-week gap is `HOLD_STALE`, a deload is `HOLD_DELOAD`.

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
- **It used to be a cross-program contract.** The retired Telegram bot wrote the same column, and `tests/test_exercise_key.py` still checks its 28 exercises resolve to keys this function produces — `skipif` when `../agente/` is not there. The contract is dead; the normalisation rule it protected is not.

If the normalisation drifts, **nothing raises**. Rows simply stop matching: the app writes one key, the bot another, and the history the whole plan depends on quietly splits in two.

`tests/test_exercise_key.py` freezes it — `CADENAS_ESPERADAS = 219`, `CLAVES_ESPERADAS = 100`, idempotence, no leftover brackets or `*`, and a cross-repo check that every bot exercise exists in the app's routines (reading the bot's file with `ast`, never importing it, so production `.env` credentials stay out of the pytest process). Treat a failure there as a data-integrity incident, not a formatting nit.

### The in-app coach — `agent.py` + `openrouter.py`

`agent.py` is the coach behind `views/agent_view.py`, talking to **OpenRouter**. It imports no Flet and unit-tests with no network, no key and no PostgreSQL.

**The invariant: nothing here can write.** The model has no tool that touches the database. Logging is a *proposal* — `propose_workout_log` validates and returns a `WorkoutProposal`, the view draws it as a card, and `commit_proposal()` writes only when Alex taps Save. `commit_proposal()` is the single writing function in the feature and no tool can reach it, so the guarantee is structural rather than prompted. `tests/test_agent.py::test_ninguna_herramienta_escribe` runs every tool against a store that raises on every write.

Three more rules that are not obvious:

- **A name that is not already a known key is refused, and so is an ambiguous one.** `entrenos.ejercicio` is shared with the Telegram coach, so an invented name starts a silent parallel history (trap #3). `resolve_exercise()` therefore returns `(None, options)` rather than picking: `"press banca"` scored a confident match on **Leg Press** on one shared word, and `"bench press"` preferred *Smith* over *Barbell* because the string was two characters shorter. Both would have written the wrong lift.
- **The recommendation is `progression.py`'s, relayed.** The training screen shows that number; a second opinion from the model leaves Alex unsure which one the plan meant. `exercise_history` hands it over as a fact and says so.
- **It talks to OpenRouter, in the OpenAI wire format.** One key, ~350 tool-capable models, chosen from a dropdown priced off the live public catalogue (`openrouter.py`) — no price is written down in this repo, and `usage.cost` is read back rather than estimated. Four things differ from the Anthropic format and all of them fail *quietly*: the system prompt is a `messages` entry; tools are `{"type":"function","function":{…,"parameters"}}`; `function.arguments` is a JSON **string**; each result is its own `{"role":"tool","tool_call_id"}` message. The transport is plain `httpx` rather than an SDK, which is what keeps the Android dependency list free of compiled code.

Adding a tool means adding it to `_READ_TOOLS` **or** `_PROPOSE_TOOLS` and to `tool_schemas()`; `test_las_herramientas_declaradas_existen_todas` fails if the two drift.

Vision and the weekly meal plan (0.12.0):

- `Coach.ask(text, image_path=None)` attaches ONE photo as an OpenAI-shape multipart turn (base64 data URL). After a successful reply the multipart turn is **collapsed to a text marker** (`_collapse_image`) so later turns do not re-upload — and re-bill — the same image. `openrouter.Model.vision` (from `architecture.input_modalities`) is snapshotted into the `agent_model_vision` pref by `save_model`; `model_sees_images()` returns None for pre-0.12 choices and the UI then lets the provider decide.
- `progress_photos` is a READ tool returning dates + nearby measurements, never bytes or paths — a tool that read JPEGs on the model's demand would turn every turn into an upload the user did not choose.
- `propose_week_targets` is a PROPOSE tool: the card writes versioned `nutrition_targets` via `commit_proposal` on Save, defaulting to next Monday. Same structural guarantee as ever: no tool writes.

### Reminders → Android notifications — `notificaciones.py`

Flet 0.28.3 exposes no notification API to Python, so the bridge is a file:
`notificaciones.py` expands every active `recordatorios` row into the next 30
days of **absolute UTC instants** (Madrid wall-clock, so `45 6 * * *` is 06:45
all year and the UTC instant shifts with DST) and atomically writes
`notifications.json` into `FLET_APP_STORAGE_DATA`. The forked template's
`main.dart` polls the file's mtime every 3 s and cancels-all + reschedules via
`flutter_local_notifications` — exact alarms when `canScheduleExactNotifications`
says yes, inexact otherwise, and a boot receiver survives restarts.

The split is deliberate: **all recurrence arithmetic lives in Python**, where
the tests are; Dart knows nothing of cron or weekdays, it schedules a flat
list. The app only *writes* two cron shapes — `M H * * *` and `M H * * d,d`
(vixie convention, 0/7 = Sunday, same dialect the bot parses) — and only
*expands* those two; a richer bot-written cron falls back to its single
`proxima` occurrence rather than being guessed at.

**One scheduler per database, never two.** Shared PostgreSQL: the bot delivers
via Telegram and owns `proxima` — `sync()` must not touch it there (it checks
`is_sqlite_url`). Phone SQLite: Android delivers and the app refreshes
`proxima` via `touch_reminder()` so a fired daily reminder doesn't read
"¡ya!" forever on Home. Dart also writes `notif_status.json` (`{granted, exact}`) back after every
sync — the only window Python has onto system permissions. `notificaciones.
estado_android()` reads it and Home's reminders dialog turns a missing
permission into instructions instead of silence. The manifest carries
`USE_EXACT_ALARM` (auto-granted; sideload-only app) so exact alarms work
without a settings trip on Android 14+; `exact_alarm_asked.flag` keeps the
one-time `requestExactAlarmsPermission()` fallback from looping.

`bot_delivers_reminders()` (né `reminders_available()`)
answers *who delivers*; it is no longer a gate — the reminders card renders on
both backends, and `Storage` grew the user CRUD (`add_reminder`,
`delete_reminder`, `set_reminder_active`, `get_all_reminders`), which refuses
to delete `origen="fijo"` rows because the bot would just re-seed them.

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
- `views/shared_ui.py` — the three things every screen needs and none should own, each here because it shipped broken in more than one file: `plural()` ("1 sets" and "Copied 1 items" both reached the screen), `dialog_width(page)` / `dialog_height(page, preferred)` (every dialog was pinned to 340 px on the theory that "the phone is 420 px wide"; it is not, and the text was clipped), and `db_error_card()` / `db_error_screen()` (an unreachable database rendered as a blank screen everywhere except `data_view.py`). **Use these; do not retype them.** A hand-agreed plural is how one of eight copies stayed wrong.
- `guides.py` — in-app reference tips (training, nutrition), rendered by `views/guide_dialog.py`. `views/home.py` builds one card per entry, so adding or dropping a guide needs no layout change.
- `exercise_details.py` — per-exercise metadata; `analytics.resolve_muscles()` reads it to attribute sets to muscle groups.

### Exercise images

`exercise_images.EXERCISE_IMAGE` maps canonical English exercise names to Free Exercise DB slugs (github.com/yuhonas/free-exercise-db, Unlicense / public domain).

**Images are not committed** — `.gitignore` excludes `assets/exercises/`. `asset_manager.py` downloads one tarball attached to a GitHub Release and extracts it into `assets/exercises/<slug>/`; `views/profile.py` drives that download and shows progress.

#### Views call `image_props()`, never `image_for()`

`image_props(key, frame=0)` returns **kwargs for `ft.Image`** — `{"src": ...}` or `{"src_base64": ...}`, or `{}` when there is no image. Every view must use it:

```python
props = image_props(name)
if props:
    ft.Image(**props, fit=ft.ImageFit.COVER, cache_width=..., cache_height=...)
```

`image_for()` / `image_frames()` still return the assets-relative string and are still correct **in web and desktop only**. They are what a view reaches for by name, and reaching for them is the bug below.

**The URL only resolves where Flet is serving the file.** That holds in web mode (Flet serves `assets/` over HTTP) and on desktop. It does not hold in the APK, and the failure is silent and total:

* the frames download to `FLET_APP_STORAGE_DATA/assets/exercises/<slug>/`
* the APK's Flutter asset bundle is somewhere else entirely
* `ft.Image` paints an empty grey box for a source it cannot resolve

So on the phone **no image could ever appear**, no matter how many times they downloaded — 140 files verified on the device, 0 rendered. It was reported as "the images don't download". Re-downloading, clearing the cache and reinstalling all leave it identical, because none of them is the problem. `url_is_served()` decides by asking whether the download directory is inside the served `assets/` dir; when it is not, the bytes go inline as base64, which is **verified to render on Android**.

**Always set `cache_width`/`cache_height` on a thumbnail.** The source frames are 850×567 photos and `width`/`height` only scale the *drawing*: a 44 px thumbnail still decodes a 1.9 MB bitmap. Browse lists ~100 exercises, i.e. ~180 MB of bitmaps and an out-of-memory kill on the phone.

**Never go back to `file://` URLs.** They worked on desktop and made every image invisible in web mode, which is how this app is actually used: the browser refuses with *"Not allowed to load local resource"* and each exercise renders as blank space that reads like a layout bug. Under `assets/` Flet serves the frames over HTTP from the page's own origin. `tests/test_exercise_images.py` fails if a `file://` ever comes back.

`tests/test_image_delivery.py` guards all of the above. It exists because `tests/test_exercise_images.py` passed throughout the outage: it asked whether the *string* was sane, and the string was always sane.

Composite/superset names (containing `+`, or prefixed `Bi-set:` / `SS:` / `Triset:`) deliberately get no image — they render blank space, which is correct.

`EXERCISE_IMAGE` is also the key into `exercise_details.py`: `details_for()` looks the slug up there. So changing a slug moves the photo **and** the muscle data, and a slug the details table does not carry silently drops that exercise out of `sets_per_muscle_group`. Change one, check the other — that is how `Behind-Neck Lat Pulldown` briefly lost its muscles while gaining the right photo. `Bulgarian Split Squat` maps to nothing on purpose: the 500-exercise source has no such movement, and a confidently wrong photo is worse than none.

## Traps

Things that break quietly if you do not know them:

1. **Renumbering views.** `home.py` hardcodes `navigate_to(2)` and `navigate_to(5)`. Reorder `view_list` and the app navigates to the wrong screen with no error. Add to the end; adjust `NAV_TABS`, never the indices.
2. **Touching `exercise_key()` normalisation.** Silent history split, no exception. Frozen in tests for exactly this reason.
3. **Assuming set keys exist.** `"rir"` and `"type"` are both optional and both absent on every row written before they existed — and on everything the retired bot wrote.
4. **Treating an untyped set as a warm-up.** Absent means *normal*. The inverse rewrites Alex's tonnage.
5. **Writing a hex in a view**, or reintroducing a module-level colour constant. Both bypass the palette and break dark mode.
6. **Reimplementing a metric in a view.** `analytics.py` is the single implementation; `storage.py` only fetches rows and supplies arguments.
7. **Expecting `get_streak()` in days.** It is weeks.
8. **Rebinding `data.ROUTINES`** instead of slice-assigning. `views/plan.py` holds a reference to the list object.
9. **Rest defaults have no second copy any more.** `set_types.REST_COMPOUND_S` / `REST_ISOLATION_S` used to be mirrored in the bot's `sesion_viva.py` and a test compared them. The bot is gone; these are now the only definition.
10. **Using `image_for()` in a view.** Blank on the phone — the APK cannot resolve an assets URL. Views call `image_props()`; see the delivery note above.
11. **An `ft.Image` thumbnail without `cache_width`/`cache_height`.** Draws small, decodes huge.
12. **Building the APK from a clean git worktree.** `assets/exercises/` is gitignored, so the worktree has no frames — which is fine (they download at runtime) but means the build cannot be used to check anything about images.
13. **Reading `get_last_sets()` without a date while back-dating.** It returns the newest row in the table, so logging Monday on Wednesday prefills from Wednesday. Pass `before=` the date being logged.
14. **Giving the coach a tool that writes.** The whole safety story of that feature is that no tool can reach the database — a *proposal* goes on screen and Alex's tap is what writes. One helpful tool that saves directly deletes the guarantee, and nothing fails.
15. **Adding a pref that holds a secret without listing it in `SECRET_PREF_KEYS`.** Both exporters copy `preferencias` verbatim into a file people mail themselves.
16. **Calling `save_workout()` from anything re-submittable.** It always INSERTs. Use `replace_workout()`; see the note in Storage.
17. **Reading `function.arguments` as an object.** OpenRouter sends it as a JSON **string**. Parse it, or every tool runs with no arguments and the coach reports that it cannot find the exercise — which reads like a matching bug, not a parsing one.
18. **Putting the system prompt in a top-level `system` field.** That is the Anthropic shape. OpenRouter ignores it, and you get a coach with no instructions rather than an error.
19. **Restricting `target_arch` to two architectures.** serious_python packages `libpythonsitepackages.so` for the **first entry only**, so `["arm64-v8a", "x86_64"]` ships an x86_64 slice with a CPython and no site-packages. The build reports success and the app opens on *"ModuleNotFoundError: No module named 'certifi'"*. All three, or exactly one. See the note in `[tool.flet.android]`.
20. **Trusting logcat to tell you the app crashed.** Flet renders a Python traceback *into the UI*, so `adb logcat | grep Traceback` comes back empty while the phone shows a purple error page. Screenshot the thing.
21. **Assuming a second writer on the database.** There is none any more: the
    app is alone with its SQLite. `notificaciones.sync()` refreshing `proxima`
    used to be gated on the backend for that reason; the gate can stay, the
    fear behind it is gone.
22. **Translating a data-contract string.** Exercise names/keys, `TrainingDay.name`
    (→ `entrenos.grupo`), set-type keys, phase `scheme`/`rest`. The UI is Spanish;
    those are not UI. See the Project section's list before touching any literal.
23. **Bumping `flutter_local_notifications` or `timezone` separately in the
    template's pubspec.** They are a matched pair (fln 19 ⇢ timezone ^0.10; fln
    18 ⇢ ^0.9). Mismatch them and pub does not error — it silently resolves fln
    down to some ancient version whose API breaks `main.dart` at compile time
    ("uiLocalNotificationDateInterpretation must be provided" = you got fln ≤18).
24. **Adding phase prose only one parser understands.** `parse_rir`,
    `parse_prescribed_step` and `_DELOAD_MARKS` are bilingual (es/en). New
    Spanish phrasing that no regex matches doesn't raise — the RIR target or the
    prescribed step just silently vanishes. `tests/test_progression.py` pins the
    shipped phases.
25. **Adding a package to `[project] dependencies` that carries compiled code.** That list is pip-installed into the APK against `pypi.flet.dev`. The list is currently free of third-party binaries and that is worth keeping: it means no upgrade can be blocked by a missing wheel for an ABI almost nobody targets. If you must, check for a `cp312-…-android_24_arm64_v8a` wheel there *first* and pin so the resolver cannot wander off it.
26. **Translating a dictionary KEY along with the label above it.** Trap 22's
    quietest form, and it shipped: `views/home.py` read
    `totals.get("proteína")` from a `nutrition` dict whose key is `"protein"`.
    `.get()` of an absent key returns `None`, not an error, so the card painted
    "Proteína 0 g" with 42 g logged — a number wrong enough to act on and
    plausible enough not to question. When a Spanish label sits next to a
    lookup, the label is the only half that is text. `tests/test_home_view.py`
    now asserts every key the card asks for exists in what `nutrition`
    returns, and takes the dicts from the module rather than typing them out.
27. **`wrap=True` inside a `Row`.** Wrapping needs a bounded width, and a child
    of an unbounded `Row` gets infinite. It does not error, it does not wrap,
    it just runs off the right edge — the rest timer's Stop button, cut in
    half, for one release. Either `expand=True` on the wrapping child or put it
    in a `Column`, which is bounded already (`build_large` was always fine for
    that reason).
28. **`ft.Text(value=…)` for anything a model wrote.** The coach answers in
    markdown and the bubble rendered it raw, asterisks included. Views that
    show model output go through `views/agent_view.spans_markdown()`. Asking
    the model for plain text in the prompt is not a fix — the model is a
    dropdown with ~350 entries in it.

### Flet version caveat

Pinned to `flet[all]>=0.25,<0.30` — `flet[all]`, not plain `flet`, because web mode needs `flet-web` and a bare `uv sync` would otherwise uninstall it. The API (`ft.Colors`, `ft.Icons`, `page.run_task`, `ft.NavigationBarDestination`, `ft.ColorScheme`) matches 0.25–0.29. If a newer Flet release renames something, update the pin rather than silently adapting to a new API.

## Tests

`.venv/bin/python -m pytest -q` — **1742 tests**, `testpaths = ["tests"]`, `asyncio_mode = "auto"`:

`test_agent.py`, `test_analytics.py`, `test_asset_manager.py`, `test_backup.py`, `test_chart_baseline.py`, `test_column_migration.py`, `test_day_screen.py`, `test_data_view_counts.py`, `test_dialog_layout.py`, `test_draft_dates.py`, `test_draft_substitution.py`, `test_exercise_images.py`, `test_exercise_key.py`, `test_flet_reconnect.py`, `test_fotos.py`, `test_gcal.py`, `test_gym_tools.py`, `test_health.py`, `test_help_dialog.py`, `test_history_notes.py`, `test_history_view.py`, `test_home_view.py`, `test_image_delivery.py`, `test_layout_movil.py`, `test_notificaciones.py`, `test_nutrition.py`, `test_nutrition_view.py`, `test_percent_table.py`, `test_prefill_por_fecha.py`, `test_profile_db_down.py`, `test_program_week.py`, `test_progression.py`, `test_routine_builder.py`, `test_session_duration.py`, `test_session_plan.py`, `test_set_types.py`, `test_shared_ui.py`, `test_smoke.py`, `test_sqlite_backend.py`, `test_storage_metrics.py`, `test_substitutions.py`, `test_theme.py`, `test_timer_sound.py`, `test_weight_trend.py`, `test_workout_date.py`, `test_workout_draft.py`, `test_workout_exercise_date.py`, `test_workout_notes.py`, `test_workout_notes_swap.py`, `test_workout_plan_rows.py`, `test_workout_resume.py`, `test_workout_session_time.py`, `test_workout_tools.py`, `test_workout_zen.py`.

A clean run is `1742 passed, 1 skipped` and needs **nothing installed but the dev group** — no Docker, no server. The single skip is a network test in `test_asset_manager.py` (opt in with `IRONFLET_NETWORK_TESTS=1`). Until 0.12 this section warned to judge a run by its skip count, because 211 tests — everything touching storage — skipped silently without PostgreSQL; that trap is gone with the server.

`tests/conftest.py` gives each pytest process its own SQLite file in the system temp dir, for the same reason it used to create a database per pid: the fixtures wipe rows, and two concurrent runs deleting each other's data mid-query produced red runs with a different set of failures each time, in files unrelated to whatever was being changed.

`test_agent.py` is deliberately the one file that never needs either: SQLite in `tmp_path` and a stubbed model, because a suite that needs a paid API is a suite that stops being run.

There is no second suite to run any more. The bot's 117 tests in `../agente/` still exist on disk but guard a program that no longer runs, and nothing in this repo depends on them.
