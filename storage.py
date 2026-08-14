"""Persistencia sobre PostgreSQL, compartida con el entrenador de Telegram.

Antes esto era `sqlite3` de la stdlib con su propio fichero. Ahora la base es
única: lo que Alex apunta aquí lo ve el bot al instante, y al revés.

La API pública (`Storage` y sus métodos) no ha cambiado, así que las vistas
siguen igual. Lo que cambia es que la app necesita la base en marcha:

    docker compose up -d        # en ../

La URL sale de `DATABASE_URL`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import analytics
from data import active_routine

DEFAULT_URL = "postgresql+psycopg://entrenador@127.0.0.1:5432/entrenador"


def weekly_session_minimum(routine=None) -> int:
    """Sessions a week must hold to extend the streak, read off the routine.

    A routine does not train the same number of days from start to finish.
    CambiaTuFísico — the default — prescribes 3 days a week in phases 1-4
    (weeks 1 to 10), 5 in phases 5-6 and 6 in phase 7; `push-pull-legs` and
    `women-home` are 3-day routines throughout. So any fixed number lies in
    some phase of some routine: the 4 that used to be hardcoded here is
    unreachable during the first ten weeks of the default routine, which is
    why a perfectly adherent user saw 🔥 0 and nothing else.

    Grading each week against the phase it belonged to is not possible: no
    routine start date is stored, so a past calendar week cannot be mapped
    onto a phase. The honest fallback is the lightest phase's prescription —
    the one number every phase of this routine can reach. Consequences,
    stated so nobody has to guess:

    * perfect adherence can never read 0, in any phase of any routine;
    * heavier phases keep slack, which is what the old "4 of 5" was after:
      one missed session does not erase months of consistency;
    * deload phases, the lightest by design, stay inside the streak.

    `days_by_phase` is the source, not `week_rotation`. For the three
    CambiaTuFísico phases that rotate, the rotation trains 4 days a week off
    3 day templates, so the template count is the lower — and therefore the
    safe — of the two.

    Falls back to 1 for a routine with no days at all (a half-built custom
    one), because a 0 minimum would make every week of doing nothing count.
    """
    routine = routine or active_routine()
    counts = [len(days) for days in routine.days_by_phase.values() if days]
    return max(1, min(counts, default=1))


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


class Base(DeclarativeBase):
    pass


class Entreno(Base):
    __tablename__ = "entrenos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    ejercicio: Mapped[str] = mapped_column(String(120), index=True)
    grupo: Mapped[str] = mapped_column(String(120), default="")
    fase: Mapped[int] = mapped_column(Integer, default=0)
    series: Mapped[list] = mapped_column(JSON, default=list)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Peso(Base):
    __tablename__ = "pesos"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    kg: Mapped[float] = mapped_column(Float)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Preferencia(Base):
    __tablename__ = "preferencias"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)


class Perfil(Base):
    __tablename__ = "perfil"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    nacimiento: Mapped[str] = mapped_column(String(20), default="")
    altura_cm: Mapped[float] = mapped_column(Float, default=0)
    sexo: Mapped[str] = mapped_column(String(20), default="")
    actividad: Mapped[str] = mapped_column(String(30), default="moderate")


def _hoy() -> date:
    return date.today()


def _fecha(valor: str | date) -> date:
    return date.fromisoformat(valor) if isinstance(valor, str) else valor


class Storage:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or os.environ.get("DATABASE_URL") or DEFAULT_URL
        self._engine = create_engine(self.db_url, pool_pre_ping=True)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._init_db()

    def _init_db(self):
        Base.metadata.create_all(self._engine)

    # ── prefs ────────────────────────────────────────────────
    def get_pref(self, key: str, default: str | None = None) -> str | None:
        with self._Session() as s:
            fila = s.get(Preferencia, key)
        return fila.valor if fila else default

    def set_pref(self, key: str, value: str):
        with self._Session() as s:
            fila = s.get(Preferencia, key)
            if fila:
                fila.valor = value
            else:
                s.add(Preferencia(clave=key, valor=value))
            s.commit()

    # ── profile ─────────────────────────────────────────────
    def get_profile(self) -> dict:
        with self._Session() as s:
            fila = s.get(Perfil, 1)
        if not fila:
            return {
                "name": "",
                "birthdate": "",
                "height_cm": 0.0,
                "sex": "",
                "activity_level": "moderate",
            }
        return {
            "name": fila.nombre or "",
            "birthdate": fila.nacimiento or "",
            "height_cm": float(fila.altura_cm or 0),
            "sex": fila.sexo or "",
            "activity_level": fila.actividad or "moderate",
        }

    def set_profile(
        self, name: str, birthdate: str, height_cm: float, sex: str, activity_level: str
    ):
        with self._Session() as s:
            fila = s.get(Perfil, 1)
            if fila is None:
                fila = Perfil(id=1)
                s.add(fila)
            fila.nombre, fila.nacimiento = name, birthdate
            fila.altura_cm, fila.sexo, fila.actividad = height_cm, sex, activity_level
            s.commit()

    # ── weight_log ──────────────────────────────────────────
    def save_weight(self, kg: float, date_iso: str | None = None):
        """Un pesaje por día: el segundo del mismo día corrige al primero."""
        dia = _fecha(date_iso) if date_iso else _hoy()
        with self._Session() as s:
            fila = s.get(Peso, dia)
            if fila:
                fila.kg = float(kg)
                fila.creado = datetime.now().astimezone()
            else:
                s.add(Peso(fecha=dia, kg=float(kg), creado=datetime.now().astimezone()))
            s.commit()

    def delete_weight(self, weight_id):
        """El id es la fecha: la tabla tiene una fila por día."""
        with self._Session() as s:
            s.execute(delete(Peso).where(Peso.fecha == _fecha(weight_id)))
            s.commit()

    def get_weights(self, limit: int = 60) -> list[dict]:
        with self._Session() as s:
            filas = list(s.scalars(select(Peso).order_by(Peso.fecha)))
        return [
            {
                "id": p.fecha.isoformat(),
                "date": p.fecha.isoformat(),
                "kg": float(p.kg),
                "timestamp": p.creado.timestamp(),
            }
            for p in filas[-limit:]
        ]

    def get_latest_weight(self) -> float | None:
        with self._Session() as s:
            fila = s.scalar(select(Peso).order_by(Peso.fecha.desc()).limit(1))
        return float(fila.kg) if fila else None

    # ── backup / restore ────────────────────────────────────
    BACKUP_VERSION = 2

    def export_all(self) -> dict:
        with self._Session() as s:
            prefs = {p.clave: p.valor for p in s.scalars(select(Preferencia))}
            entrenos = list(s.scalars(select(Entreno).order_by(Entreno.id)))
            pesos = list(s.scalars(select(Peso).order_by(Peso.fecha)))
        return {
            "app": "ironflet",
            "version": self.BACKUP_VERSION,
            "exported_at": time.time(),
            "profile": self.get_profile(),
            "prefs": prefs,
            "workouts": [
                {
                    "date": e.fecha.isoformat(),
                    "exercise": e.ejercicio,
                    "muscle_group": e.grupo,
                    "phase": e.fase,
                    "sets": e.series,
                    "timestamp": e.creado.timestamp(),
                }
                for e in entrenos
            ],
            "weights": [
                {"date": p.fecha.isoformat(), "kg": float(p.kg), "timestamp": p.creado.timestamp()}
                for p in pesos
            ],
        }

    def import_all(self, data: dict, *, wipe: bool = True) -> dict:
        if not isinstance(data, dict) or data.get("app") not in ("ironflet", "ironlog"):
            raise ValueError("Not an IronFlet backup")
        if int(data.get("version") or 0) > self.BACKUP_VERSION:
            raise ValueError(f"Backup version {data.get('version')} is newer than supported")

        counts = {"workouts": 0, "weights": 0, "prefs": 0, "profile": 0}
        with self._Session() as s:
            if wipe:
                s.execute(delete(Entreno))
                s.execute(delete(Peso))
                s.execute(delete(Preferencia))
                s.execute(delete(Perfil))
                s.commit()

            p = data.get("profile") or {}
            if p:
                s.add(
                    Perfil(
                        id=1,
                        nombre=p.get("name", ""),
                        nacimiento=p.get("birthdate", ""),
                        altura_cm=float(p.get("height_cm") or 0),
                        sexo=p.get("sex", ""),
                        actividad=p.get("activity_level", "moderate"),
                    )
                )
                counts["profile"] = 1

            for k, v in (data.get("prefs") or {}).items():
                s.merge(Preferencia(clave=str(k), valor=str(v)))
                counts["prefs"] += 1

            for w in data.get("weights") or []:
                s.merge(
                    Peso(
                        fecha=_fecha(w.get("date")),
                        kg=float(w.get("kg") or 0),
                        creado=datetime.fromtimestamp(
                            float(w.get("timestamp") or time.time())
                        ).astimezone(),
                    )
                )
                counts["weights"] += 1

            for wo in data.get("workouts") or []:
                s.add(
                    Entreno(
                        fecha=_fecha(wo.get("date")),
                        ejercicio=wo.get("exercise", ""),
                        grupo=wo.get("muscle_group", ""),
                        fase=int(wo.get("phase") or 0),
                        series=wo.get("sets") or [],
                        creado=datetime.fromtimestamp(
                            float(wo.get("timestamp") or time.time())
                        ).astimezone(),
                    )
                )
                counts["workouts"] += 1
            s.commit()
        return counts

    # ── destructive operations ──────────────────────────────
    def clear_workouts(self):
        with self._Session() as s:
            s.execute(delete(Entreno))
            s.commit()

    def clear_all(self):
        with self._Session() as s:
            for modelo in (Entreno, Peso, Perfil, Preferencia):
                s.execute(delete(modelo))
            s.commit()

    # ── writes ────────────────────────────────────────────────
    def save_workout(self, entry: WorkoutEntry):
        with self._Session() as s:
            s.add(
                Entreno(
                    fecha=_fecha(entry.date),
                    ejercicio=entry.exercise,
                    grupo=entry.muscle_group,
                    fase=entry.phase,
                    series=entry.sets,
                    creado=datetime.fromtimestamp(entry.timestamp).astimezone(),
                )
            )
            s.commit()

    # ── reads ─────────────────────────────────────────────────
    @staticmethod
    def _to_entries(filas) -> list[WorkoutEntry]:
        return [
            WorkoutEntry(
                date=f.fecha.isoformat(),
                exercise=f.ejercicio,
                muscle_group=f.grupo,
                phase=f.fase,
                sets=f.series or [],
                timestamp=f.creado.timestamp(),
            )
            for f in filas
        ]

    def get_all(self) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(select(Entreno).order_by(Entreno.fecha.desc(), Entreno.id.desc()))
            )
        return self._to_entries(filas)

    def get_today(self) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(
                    select(Entreno).where(Entreno.fecha == _hoy()).order_by(Entreno.id.desc())
                )
            )
        return self._to_entries(filas)

    def get_week_stats(self) -> dict:
        """Sessions / sets / volume over the trailing 7 days.

        The keys are unchanged (`views/home.py` reads all three), but two of
        the values used to lie:

        * `sessions` counted table rows, and `entrenos` holds one row per
          exercise, so a normal six-exercise session was rendered as
          "6 Sessions". It now counts distinct training days, via
          `analytics.session_count`.
        * `sets` and `volume` counted warm-ups as work. Both now go through
          `analytics`, which drops sets flagged `type="warmup"` — warming up
          with the empty bar is not tonnage.

        Rows dated in the future are also excluded now, so a mistyped date
        cannot inflate the week.
        """
        today = _hoy()
        since = today - timedelta(days=7)
        with self._Session() as s:
            rows = list(
                s.scalars(select(Entreno).where(Entreno.fecha >= since, Entreno.fecha <= today))
            )
        entries = self._to_entries(rows)
        return {
            "sessions": analytics.session_count(entries),
            "sets": sum(len(analytics.working_sets(e.sets)) for e in entries),
            "volume": analytics.total_volume(entries),
        }

    def get_streak(self, *, min_sessions: int | None = None) -> int:
        """Consecutive **weeks** hitting a session minimum — weeks, not days.

        The unit changed. This used to count consecutive calendar days with
        any entry, walking back from today, which cannot describe a plan with
        rest days: the streak reset every weekend by design, and returned 0 on
        both rest days after a flawless Mon–Fri week.

        A week now counts when it holds at least `min_sessions` distinct
        training days, and the current, unfinished week is skipped rather than
        failed. See `analytics.training_streak` for the full reasoning.

        `min_sessions` defaults to the **active routine's** own minimum rather
        than a fixed number — see `weekly_session_minimum` for why a fixed one
        cannot be right. Pass it explicitly to grade against something else.
        """
        if min_sessions is None:
            min_sessions = weekly_session_minimum()
        with self._Session() as s:
            dates = list(s.scalars(select(func.distinct(Entreno.fecha))))
        return analytics.training_streak(dates, min_sessions=min_sessions)

    def get_last_sets(self, exercise: str) -> list[dict] | None:
        with self._Session() as s:
            fila = s.scalar(
                select(Entreno)
                .where(Entreno.ejercicio == exercise)
                .order_by(Entreno.fecha.desc(), Entreno.id.desc())
                .limit(1)
            )
        return (fila.series or []) if fila else None

    def get_exercise_history(self, exercise: str, limit: int = 20) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(
                    select(Entreno).where(Entreno.ejercicio == exercise).order_by(Entreno.fecha)
                )
            )
        return self._to_entries(filas)[-limit:]

    def get_exercise_summary(self) -> list[dict]:
        resumen: dict[str, dict] = {}
        for w in self.get_all():
            if w.exercise not in resumen:
                resumen[w.exercise] = {
                    "name": w.exercise,
                    "count": 0,
                    "last_date": w.date,
                    "max_weight": 0.0,
                }
            resumen[w.exercise]["count"] += 1
            for x in w.sets:
                peso = x.get("weight") or 0
                if peso > resumen[w.exercise]["max_weight"]:
                    resumen[w.exercise]["max_weight"] = peso
        return sorted(resumen.values(), key=lambda x: x["count"], reverse=True)
