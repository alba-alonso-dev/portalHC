"""
Gestión centralizada de conexiones PostgreSQL.

Sustituye a la implementación original sobre SQLite manteniendo exactamente la
misma interfaz pública (`get_db_connection()` como context manager que hace
commit/rollback y cierra), de modo que servicios y rutas no cambian.

Configuración
─────────────
  DATABASE_URL   URL completa, p. ej.
                 postgresql://portal:portal@db:5432/portal_hc
  o bien las variables individuales:
  PGHOST (localhost) · PGPORT (5432) · PGDATABASE (portal_hc)
  PGUSER (portal) · PGPASSWORD (portal)

Notas de diseño
───────────────
* Se abre una conexión por bloque `with`, igual que hacía SQLite. No se usa un
  pool porque la app arranca con `gunicorn --preload`: un pool creado antes del
  fork dejaría sockets compartidos entre workers.
* Se usa `ClientCursor` (interpolación de parámetros en cliente) en lugar del
  binding en servidor. SQLite no tipa los parámetros, y el código pasa a veces
  int donde la columna es TEXT; con binding en servidor PostgreSQL fallaría con
  "could not determine data type of parameter".
* El SQL se traduce al vuelo en `database/sql_compat.py`.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from typing import Any, Generator, Optional, Sequence
from urllib.parse import quote

import psycopg
from psycopg import errors as pg_errors

from database.sql_compat import Row, row_factory, translate

logger = logging.getLogger(__name__)

# Excepciones reexportadas para que el resto del código no importe psycopg
# directamente (antes se capturaba sqlite3.OperationalError / IntegrityError).
DatabaseError = psycopg.DatabaseError
OperationalError = psycopg.OperationalError
IntegrityError = psycopg.IntegrityError
ProgrammingError = psycopg.ProgrammingError
UndefinedTable = pg_errors.UndefinedTable

__all__ = [
    "get_db_connection", "execute_raw", "DATABASE_URL", "DATABASE", "Row",
    "DatabaseError", "OperationalError", "IntegrityError",
    "ProgrammingError", "UndefinedTable",
]


def _build_dsn() -> str:
    """Construye el DSN desde DATABASE_URL o desde las variables PG*."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    name = os.environ.get("PGDATABASE", "portal_hc")
    user = os.environ.get("PGUSER", "portal")
    pwd = os.environ.get("PGPASSWORD", "portal")
    return f"postgresql://{quote(user)}:{quote(pwd)}@{host}:{port}/{name}"


# DSN resuelto en el momento de importar. Se usa solo para trazas: la conexión
# real llama a `_build_dsn()` en cada `connect`, para que un script pueda fijar
# DATABASE_URL después de haber importado este módulo.
DATABASE_URL = _build_dsn()

# Alias histórico: algunos módulos importaban `DATABASE` para mostrarlo en logs.
DATABASE = DATABASE_URL

_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))
# Evita que una sentencia bloqueada deje un worker colgado indefinidamente.
_STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "60000"))


def _as_text(query: Any) -> str:
    return query.decode() if isinstance(query, (bytes, bytearray)) else str(query)


_DDL_RE = re.compile(r"^\s*(?:--[^\n]*\n|\s)*(ALTER|CREATE|DROP)\b", re.I)

# Sentencias que no modifican datos. Se usa para decidir si, tras un error, la
# transacción puede descartarse sin perder nada (ver `_recuperar_transaccion`).
_SOLO_LECTURA_RE = re.compile(
    r"^\s*(?:--[^\n]*\n|\s)*(SELECT|WITH|SHOW|EXPLAIN|VALUES|TABLE)\b", re.I)
_MODIFICA_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", re.I)


def _es_solo_lectura(sql: str) -> bool:
    """
    True si la sentencia no puede haber modificado datos.

    Un CTE (`WITH`) sí puede modificar datos, por eso se comprueba además que no
    contenga ninguna palabra clave de escritura.
    """
    if not _SOLO_LECTURA_RE.match(sql):
        return False
    return not _MODIFICA_RE.search(sql)


class CompatCursor(psycopg.ClientCursor):
    """
    Cursor que traduce el SQL de dialecto SQLite y emula `lastrowid`.

    `lastrowid` no existe en psycopg. Se resuelve consultando `lastval()`, que
    devuelve el último valor generado por una secuencia en esta sesión — que es
    justamente el `id` recién insertado en las tablas con BIGSERIAL. La consulta
    se protege con un savepoint porque `lastval()` lanza error si la sesión aún
    no ha usado ninguna secuencia, y en PostgreSQL un error aborta la
    transacción completa.

    Las sentencias DDL se envuelven en un savepoint por ese mismo motivo: el
    código de migraciones fue escrito para SQLite, donde un error deja la
    transacción utilizable y el flujo continúa (`try: ALTER ... except: pass`).
    Sin savepoint, en PostgreSQL el primer error invalidaría toda la migración.
    """

    def _recuperar_transaccion(self, sql: str) -> None:
        """
        Deshace la transacción abortada cuando es seguro hacerlo.

        En SQLite una sentencia que falla deja la conexión utilizable, y el
        código se apoya en ello: hay decenas de consultas envueltas en
        `try: ... except: return []`. En PostgreSQL, en cambio, el error aborta
        la transacción entera y *todas* las sentencias siguientes fallan con
        `InFailedSqlTransaction`, de modo que un único fallo tumbaba la petición
        completa y además enmascaraba el error original.

        Se restaura la semántica de SQLite haciendo rollback, pero solo cuando
        no hay nada que perder:
          * la sentencia fallida era de solo lectura, y
          * no se ha escrito nada antes en esta transacción, y
          * no estamos dentro de un `with conn.transaction()` explícito, que ya
            gestiona su propio savepoint.
        Si hubo escrituras se deja la transacción abortada a propósito: hacer
        rollback silencioso descartaría cambios que la petición cree haber hecho.
        """
        conn = self.connection
        if conn.autocommit or getattr(conn, "_num_transactions", 0):
            return
        if getattr(conn, "_hubo_escritura", False) or not _es_solo_lectura(sql):
            return
        try:
            conn.rollback()
        except psycopg.Error:
            pass

    def execute(self, query, params=None, **kwargs):  # type: ignore[override]
        sql = translate(_as_text(query), params is not None)
        if not _es_solo_lectura(sql):
            self.connection._hubo_escritura = True
        try:
            if _DDL_RE.match(sql) and not self.connection.autocommit:
                with self.connection.transaction():
                    return super().execute(sql, params, **kwargs)
            return super().execute(sql, params, **kwargs)
        except psycopg.Error:
            self._recuperar_transaccion(sql)
            raise

    def executemany(self, query, params_seq, **kwargs):  # type: ignore[override]
        sql = translate(_as_text(query), True)
        self.connection._hubo_escritura = True
        return super().executemany(sql, params_seq, **kwargs)

    @property
    def lastrowid(self) -> Optional[int]:
        try:
            with self.connection.transaction():
                with self.connection.cursor() as cur:
                    psycopg.ClientCursor.execute(cur, "SELECT lastval()")
                    fila = cur.fetchone()
                    return int(fila[0]) if fila else None
        except psycopg.Error:
            # Ninguna secuencia usada en esta sesión (tabla sin BIGSERIAL).
            return None


class CompatConnection(psycopg.Connection):
    """
    Conexión que usa `CompatCursor` también en `conn.execute(...)`.

    Añade `executemany` a nivel de conexión: existe en `sqlite3.Connection` y el
    código de migraciones lo usa, pero psycopg solo lo ofrece en el cursor.
    """

    cursor_factory = CompatCursor

    # True en cuanto se ejecuta una sentencia que puede modificar datos. Lo usa
    # `CompatCursor._recuperar_transaccion` para no descartar cambios pendientes.
    _hubo_escritura = False

    def commit(self):
        super().commit()
        self._hubo_escritura = False

    def rollback(self):
        super().rollback()
        self._hubo_escritura = False

    def executemany(self, query, params_seq, **kwargs):
        cur = self.cursor()
        cur.executemany(query, params_seq, **kwargs)
        return cur


def execute_raw(conn: psycopg.Connection, sql: str,
                params: Optional[Sequence[Any]] = None):
    """
    Ejecuta SQL nativo de PostgreSQL sin pasar por el traductor de dialecto.

    Necesario para el SQL escrito ya en dialecto PostgreSQL (shims de
    `pg_bootstrap`, script de volcado), donde la traducción sería incorrecta:
    p. ej. convertiría el tipo TIMESTAMP de una firma de función en TEXT.
    """
    cur = conn.cursor()
    psycopg.ClientCursor.execute(cur, sql, params)
    return cur


@contextlib.contextmanager
def get_db_connection() -> Generator[psycopg.Connection, None, None]:
    """
    Context manager que abre una conexión PostgreSQL, hace commit al salir
    o rollback en caso de excepción, y siempre cierra la conexión.

    Uso:
        with get_db_connection() as conn:
            conn.execute(...)
    """
    conn = CompatConnection.connect(
        _build_dsn(),
        cursor_factory=CompatCursor,
        row_factory=row_factory,
        connect_timeout=_CONNECT_TIMEOUT,
        autocommit=False,
        options=f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
