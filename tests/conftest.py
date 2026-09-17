"""Un fichero SQLite por proceso de pytest.

Antes esto creaba una base PostgreSQL por pid, porque los tests compartían
servidor y se borraban las filas unos a otros — un mismo cambio daba rojos
distintos en cada ejecución. Desde 0.13 no hay servidor: la app es solo el
móvil y su SQLite, así que el aislamiento sale gratis dándole a cada proceso
su propio fichero en el temporal del sistema.

El efecto secundario es el que importa: **ya no se salta ningún test**. Con
PostgreSQL, 211 de ellos — todo lo que tocaba almacenamiento — se saltaban en
cualquier máquina sin `docker compose up`, y una suite verde que se saltaba
211 tests no había verificado nada sobre la persistencia. Ahora corren
siempre, en el mismo motor que usa el móvil de verdad.

Quien quiera apuntar a otra base sigue pudiendo: `TEST_DATABASE_URL` manda y
esto no toca nada.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def base_por_proceso():
    """`TEST_DATABASE_URL` → un SQLite propio de esta ejecución."""
    if os.environ.get("TEST_DATABASE_URL"):
        yield  # el llamante ya eligió: no tocamos nada
        return

    carpeta = tempfile.mkdtemp(prefix=f"ironflet_test_{os.getpid()}_")
    os.environ["TEST_DATABASE_URL"] = f"sqlite+pysqlite:///{carpeta}/test.db"
    try:
        yield
    finally:
        os.environ.pop("TEST_DATABASE_URL", None)
        shutil.rmtree(carpeta, ignore_errors=True)
