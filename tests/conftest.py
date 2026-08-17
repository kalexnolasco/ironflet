"""One PostgreSQL database per pytest process.

Every test file already honours `TEST_DATABASE_URL`, but nothing set it, so
they all landed on the same `entrenador_test` — and their fixtures wipe rows
(and used to drop tables) before each test. Two pytest processes on the same
machine therefore deleted each other's data mid-query: red runs with a
different set of failures each time, in files unrelated to whatever was being
changed. It cost one session five red runs to identify, and it makes correct
work look broken, which is worse than a plain failure.

So: unless the caller names a database explicitly, each process gets its own,
named after its pid, created here and dropped on the way out. Tests that skip
without a database keep skipping — this only fills in `TEST_DATABASE_URL` when
there is already a server to talk to.

Opting out is deliberate and easy: set `TEST_DATABASE_URL` yourself and this
does nothing. That is the path CI takes, where the runner is alone anyway.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_PLANTILLA = "postgres"  # base de mantenimiento: CREATE/DROP no pueden correr sobre la propia


def _url_de_servidor(url: str) -> str:
    """La misma URL apuntando a `postgres`, para poder crear y borrar bases."""
    # render_as_string(hide_password=False), nunca str(): str() enmascara la
    # contraseña con *** y la conexión falla con "password authentication failed".
    return make_url(url).set(database=_PLANTILLA).render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def base_por_proceso():
    """Crea `ironflet_test_<pid>` para esta ejecución y la borra al terminar."""
    if os.environ.get("TEST_DATABASE_URL"):
        yield  # el llamante ya eligió: no tocamos nada
        return

    base = os.environ.get("DATABASE_URL")
    if not base:
        yield  # sin servidor no hay nada que aislar; los tests se saltan solos
        return

    nombre = f"ironflet_test_{os.getpid()}"
    url = make_url(base).set(database=nombre).render_as_string(hide_password=False)

    # AUTOCOMMIT es obligatorio: CREATE DATABASE no puede ir en una transacción.
    motor = create_engine(_url_de_servidor(base), isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{nombre}"'))
            con.execute(text(f'CREATE DATABASE "{nombre}"'))
    except Exception:
        # Sin permiso para crear bases (o sin servidor): se sigue con la
        # compartida. Peor aislamiento, pero mejor que no poder ejecutar nada.
        motor.dispose()
        yield
        return

    os.environ["TEST_DATABASE_URL"] = url
    try:
        yield
    finally:
        os.environ.pop("TEST_DATABASE_URL", None)
        with motor.connect() as con:
            # Cerrar las conexiones vivas primero: DROP DATABASE falla mientras
            # quede una abierta, y los pools de los tests pueden seguirlo estando.
            con.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": nombre},
            )
            con.execute(text(f'DROP DATABASE IF EXISTS "{nombre}"'))
        motor.dispose()
