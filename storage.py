"""Persistencia con sqlite3 (stdlib)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class WorkoutEntry:
    date: str
    exercise: str
    muscle_group: str
    phase: int
    sets: list[dict]
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


def _db_dir() -> str:
    # Flet expone FLET_APP_STORAGE_DATA en Android; fallback a cwd en desktop.
    return os.environ.get("FLET_APP_STORAGE_DATA") or os.getcwd()


class Storage:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.path.join(_db_dir(), "ironflet.db")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    exercise TEXT NOT NULL,
                    muscle_group TEXT DEFAULT '',
                    phase INTEGER DEFAULT 0,
                    sets_json TEXT DEFAULT '[]',
                    timestamp REAL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workouts_exercise ON workouts(exercise)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prefs (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT DEFAULT '',
                    birthdate TEXT DEFAULT '',
                    height_cm REAL DEFAULT 0,
                    sex TEXT DEFAULT '',
                    activity_level TEXT DEFAULT 'moderate'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weight_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    kg REAL NOT NULL,
                    timestamp REAL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_weight_date ON weight_log(date)")

    # ── prefs ────────────────────────────────────────────────
    def get_pref(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM prefs WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_pref(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO prefs (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ── profile ─────────────────────────────────────────────
    def get_profile(self) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT name, birthdate, height_cm, sex, activity_level FROM profile WHERE id = 1"
            ).fetchone()
        if not row:
            return {
                "name": "",
                "birthdate": "",
                "height_cm": 0.0,
                "sex": "",
                "activity_level": "moderate",
            }
        return {
            "name": row[0] or "",
            "birthdate": row[1] or "",
            "height_cm": float(row[2] or 0),
            "sex": row[3] or "",
            "activity_level": row[4] or "moderate",
        }

    def set_profile(
        self, name: str, birthdate: str, height_cm: float, sex: str, activity_level: str
    ):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO profile (id, name, birthdate, height_cm, sex, activity_level) "
                "VALUES (1, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "name = excluded.name, birthdate = excluded.birthdate, "
                "height_cm = excluded.height_cm, sex = excluded.sex, "
                "activity_level = excluded.activity_level",
                (name, birthdate, height_cm, sex, activity_level),
            )

    # ── weight_log ──────────────────────────────────────────
    def save_weight(self, kg: float, date_iso: str | None = None):
        if date_iso is None:
            date_iso = date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO weight_log (date, kg, timestamp) VALUES (?, ?, ?)",
                (date_iso, kg, time.time()),
            )

    def delete_weight(self, weight_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM weight_log WHERE id = ?", (weight_id,))

    def get_weights(self, limit: int = 60) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, date, kg, timestamp FROM weight_log ORDER BY date ASC, timestamp ASC"
            ).fetchall()
        return [
            {"id": r[0], "date": r[1], "kg": float(r[2]), "timestamp": r[3]} for r in rows[-limit:]
        ]

    def get_latest_weight(self) -> float | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT kg FROM weight_log ORDER BY date DESC, timestamp DESC LIMIT 1"
            ).fetchone()
        return float(row[0]) if row else None

    # ── backup / restore ────────────────────────────────────
    BACKUP_VERSION = 1

    def export_all(self) -> dict:
        """Serialize all user data into a JSON-safe dict."""
        with self._conn() as conn:
            prefs_rows = conn.execute("SELECT key, value FROM prefs").fetchall()
            workout_rows = conn.execute(
                "SELECT date, exercise, muscle_group, phase, sets_json, timestamp "
                "FROM workouts ORDER BY id ASC"
            ).fetchall()
            weight_rows = conn.execute(
                "SELECT date, kg, timestamp FROM weight_log ORDER BY id ASC"
            ).fetchall()
        return {
            "app": "ironflet",
            "version": self.BACKUP_VERSION,
            "exported_at": time.time(),
            "profile": self.get_profile(),
            "prefs": dict(prefs_rows),
            "workouts": [
                {
                    "date": r[0],
                    "exercise": r[1],
                    "muscle_group": r[2],
                    "phase": r[3],
                    "sets": json.loads(r[4]),
                    "timestamp": r[5],
                }
                for r in workout_rows
            ],
            "weights": [{"date": r[0], "kg": float(r[1]), "timestamp": r[2]} for r in weight_rows],
        }

    def import_all(self, data: dict, *, wipe: bool = True) -> dict:
        """Restore data from an export dict. Returns counts of inserted rows."""
        if not isinstance(data, dict) or data.get("app") not in ("ironflet", "ironlog"):
            raise ValueError("Not an IronFlet backup")
        version = int(data.get("version") or 0)
        if version > self.BACKUP_VERSION:
            raise ValueError(f"Backup version {version} is newer than supported")

        counts = {"workouts": 0, "weights": 0, "prefs": 0, "profile": 0}
        with self._conn() as conn:
            if wipe:
                conn.execute("DELETE FROM workouts")
                conn.execute("DELETE FROM weight_log")
                conn.execute("DELETE FROM prefs")
                conn.execute("DELETE FROM profile")

            p = data.get("profile") or {}
            if p:
                conn.execute(
                    "INSERT INTO profile (id, name, birthdate, height_cm, sex, activity_level) "
                    "VALUES (1, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "name = excluded.name, birthdate = excluded.birthdate, "
                    "height_cm = excluded.height_cm, sex = excluded.sex, "
                    "activity_level = excluded.activity_level",
                    (
                        p.get("name", ""),
                        p.get("birthdate", ""),
                        float(p.get("height_cm") or 0),
                        p.get("sex", ""),
                        p.get("activity_level", "moderate"),
                    ),
                )
                counts["profile"] = 1

            for k, v in (data.get("prefs") or {}).items():
                conn.execute(
                    "INSERT INTO prefs (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(k), str(v)),
                )
                counts["prefs"] += 1

            for w in data.get("weights") or []:
                conn.execute(
                    "INSERT INTO weight_log (date, kg, timestamp) VALUES (?, ?, ?)",
                    (w.get("date", ""), float(w.get("kg") or 0), float(w.get("timestamp") or 0)),
                )
                counts["weights"] += 1

            for wo in data.get("workouts") or []:
                conn.execute(
                    "INSERT INTO workouts (date, exercise, muscle_group, phase, sets_json, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        wo.get("date", ""),
                        wo.get("exercise", ""),
                        wo.get("muscle_group", ""),
                        int(wo.get("phase") or 0),
                        json.dumps(wo.get("sets") or []),
                        float(wo.get("timestamp") or 0),
                    ),
                )
                counts["workouts"] += 1

        return counts

    # ── destructive operations ──────────────────────────────
    def clear_workouts(self):
        """Wipe the workouts table (keeps profile, weights, prefs)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM workouts")

    def clear_all(self):
        """Wipe everything: workouts, weights, profile, prefs."""
        with self._conn() as conn:
            conn.execute("DELETE FROM workouts")
            conn.execute("DELETE FROM weight_log")
            conn.execute("DELETE FROM profile")
            conn.execute("DELETE FROM prefs")

    # ── writes ────────────────────────────────────────────────
    def save_workout(self, entry: WorkoutEntry):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO workouts (date, exercise, muscle_group, phase, sets_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.date,
                    entry.exercise,
                    entry.muscle_group,
                    entry.phase,
                    json.dumps(entry.sets),
                    entry.timestamp,
                ),
            )

    # ── reads ─────────────────────────────────────────────────
    def _rows_to_entries(self, rows) -> list[WorkoutEntry]:
        return [
            WorkoutEntry(
                date=r[0],
                exercise=r[1],
                muscle_group=r[2],
                phase=r[3],
                sets=json.loads(r[4]),
                timestamp=r[5],
            )
            for r in rows
        ]

    def get_all(self) -> list[WorkoutEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, exercise, muscle_group, phase, sets_json, timestamp "
                "FROM workouts ORDER BY timestamp DESC"
            ).fetchall()
        return self._rows_to_entries(rows)

    def get_today(self) -> list[WorkoutEntry]:
        today = date.today().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, exercise, muscle_group, phase, sets_json, timestamp "
                "FROM workouts WHERE date = ? ORDER BY timestamp DESC",
                (today,),
            ).fetchall()
        return self._rows_to_entries(rows)

    def get_week_stats(self) -> dict:
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT sets_json FROM workouts WHERE date >= ?", (week_ago,)
            ).fetchall()
        sets_lists = [json.loads(r[0]) for r in rows]
        return {
            "sessions": len(sets_lists),
            "sets": sum(len(s) for s in sets_lists),
            "volume": sum(s["weight"] * s["reps"] for sl in sets_lists for s in sl),
        }

    def get_streak(self) -> int:
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT date FROM workouts").fetchall()
        dates_set = {r[0] for r in rows}
        streak = 0
        d = date.today()
        while d.isoformat() in dates_set:
            streak += 1
            d -= timedelta(days=1)
        return streak

    def get_last_sets(self, exercise: str) -> list[dict] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT sets_json FROM workouts WHERE exercise = ? ORDER BY timestamp DESC LIMIT 1",
                (exercise,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_exercise_history(self, exercise: str, limit: int = 20) -> list[WorkoutEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, exercise, muscle_group, phase, sets_json, timestamp "
                "FROM workouts WHERE exercise = ? ORDER BY timestamp ASC",
                (exercise,),
            ).fetchall()
        entries = self._rows_to_entries(rows)
        return entries[-limit:]

    def get_exercise_summary(self) -> list[dict]:
        summary: dict[str, dict] = {}
        for w in self.get_all():
            if w.exercise not in summary:
                summary[w.exercise] = {
                    "name": w.exercise,
                    "count": 0,
                    "last_date": w.date,
                    "max_weight": 0.0,
                }
            summary[w.exercise]["count"] += 1
            for s in w.sets:
                if s["weight"] > summary[w.exercise]["max_weight"]:
                    summary[w.exercise]["max_weight"] = s["weight"]
        return sorted(summary.values(), key=lambda x: x["count"], reverse=True)
