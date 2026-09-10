"""
Shims de compatibilidad instalados dentro de PostgreSQL.

El SQL de la aplicación usa funciones propias de SQLite que PostgreSQL no
trae. En lugar de reescribir las ~40 consultas afectadas, se declaran aquí
como funciones/vistas nativas de PostgreSQL con la misma firma y semántica:

  strftime(fmt, valor)   Formateo de fecha estilo SQLite ('%Y', '%Y-%m', '%m').
  julianday(valor)       Día juliano, para restas que dan días de diferencia.
  round(doble, decimales) SQLite redondea dobles con precisión; PostgreSQL solo
                         define round(numeric, int).
  group_concat(texto)    Agregado equivalente a string_agg(x, ',').
  sqlite_master          Vista con (type, name, tbl_name, sql) sobre el catálogo.

Todas las fechas se tratan como TEXT, igual que hacía SQLite. Un valor no
parseable devuelve NULL en lugar de fallar, que es también lo que hacía SQLite.

`asegurar_compat_sql()` es idempotente y se invoca al principio de las
migraciones.
"""

from __future__ import annotations

import logging

from database.connection import execute_raw

logger = logging.getLogger(__name__)

# ── Conversión tolerante a timestamp ─────────────────────────────────────────
# SQLite devuelve NULL cuando el valor no es una fecha reconocible. Aquí se
# replica capturando la excepción de casteo. 'now' se resuelve en UTC, como
# hacen strftime/julianday en SQLite.
_FN_TS = """
CREATE OR REPLACE FUNCTION sqlite_ts(valor text)
RETURNS timestamp
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    IF valor IS NULL THEN
        RETURN NULL;
    END IF;
    IF valor = 'now' THEN
        RETURN (now() AT TIME ZONE 'UTC');
    END IF;
    BEGIN
        RETURN valor::timestamp;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
END;
$fn$;
"""

_FN_STRFTIME = """
CREATE OR REPLACE FUNCTION strftime(fmt text, valor text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT to_char(
        sqlite_ts(valor),
        replace(replace(replace(replace(replace(replace(replace(replace(
            fmt,
            '%Y', 'YYYY'), '%m', 'MM'), '%d', 'DD'),
            '%H', 'HH24'), '%M', 'MI'), '%S', 'SS'),
            '%j', 'DDD'), '%W', 'WW')
    );
$fn$;
"""

_FN_JULIANDAY = """
CREATE OR REPLACE FUNCTION julianday(valor text)
RETURNS double precision
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT extract(epoch FROM sqlite_ts(valor)) / 86400.0 + 2440587.5;
$fn$;
"""

# group_concat es el nombre de SQLite; string_agg es el de PostgreSQL.
# CREATE AGGREGATE no admite OR REPLACE en versiones antiguas, así que se
# comprueba antes de crearlo.
_AGG_GROUP_CONCAT = """
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.proname = 'group_concat' AND n.nspname = 'public'
    ) THEN
        CREATE AGGREGATE group_concat(text) (
            SFUNC   = sqlite_concat_sfunc,
            STYPE   = text
        );
    END IF;
END
$do$;
"""

_FN_CONCAT_SFUNC = """
CREATE OR REPLACE FUNCTION sqlite_concat_sfunc(acc text, valor text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE
        WHEN valor IS NULL THEN acc
        WHEN acc   IS NULL THEN valor
        ELSE acc || ',' || valor
    END;
$fn$;
"""

# Vista que emula sqlite_master. El código la consulta para saber si una tabla
# existe (`SELECT 1 FROM sqlite_master WHERE type='table' AND name=?`).
_VIEW_SQLITE_MASTER = """
CREATE OR REPLACE VIEW sqlite_master AS
SELECT CASE c.relkind
           WHEN 'r' THEN 'table'
           WHEN 'p' THEN 'table'
           WHEN 'v' THEN 'view'
           WHEN 'm' THEN 'view'
           WHEN 'i' THEN 'index'
           ELSE c.relkind::text
       END::text                                        AS type,
       c.relname::text                                   AS name,
       COALESCE(dep.relname, c.relname)::text            AS tbl_name,
       0                                                 AS rootpage,
       NULL::text                                        AS sql
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_index i  ON i.indexrelid = c.oid
  LEFT JOIN pg_class dep ON dep.oid = i.indrelid
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p', 'v', 'm', 'i')
"""

_FN_ROUND = """
CREATE OR REPLACE FUNCTION round(valor double precision, decimales integer)
RETURNS double precision
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT round(valor::numeric, decimales)::double precision;
$fn$;
"""

_SENTENCIAS = (
    _FN_TS,
    _FN_STRFTIME,
    _FN_JULIANDAY,
    _FN_ROUND,
    _FN_CONCAT_SFUNC,
    _AGG_GROUP_CONCAT,
    _VIEW_SQLITE_MASTER,
)


def asegurar_compat_sql(conn) -> None:
    """
    Instala (o actualiza) los shims de compatibilidad en la base de datos.

    Idempotente: puede ejecutarse en cada arranque sin efectos secundarios.
    """
    for sentencia in _SENTENCIAS:
        execute_raw(conn, sentencia)
    logger.info("[Compat] Shims SQL de compatibilidad SQLite instalados")
