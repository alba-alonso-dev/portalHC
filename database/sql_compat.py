"""
Capa de compatibilidad SQL: dialecto SQLite → PostgreSQL.

Por qué existe
──────────────
El portal se escribió contra SQLite con ~460 sentencias SQL crudas repartidas
por `services/`, `routes/` y `database/`. Reescribir cada una a dialecto
PostgreSQL habría sido una intervención masiva y arriesgada. En su lugar este
módulo traduce las diferencias de dialecto en el momento de ejecutar, de forma
que el SQL de la aplicación sigue escribiéndose en el estilo original.

Qué traduce
───────────
  ?                         → %s          (placeholders posicionales)
  %                         → %%          (solo si la sentencia lleva params;
                                           psycopg interpreta % como formato)
  INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
  INSERT OR IGNORE INTO x   → INSERT INTO x ... ON CONFLICT DO NOTHING
  ALTER TABLE .. ADD COLUMN → ADD COLUMN IF NOT EXISTS   (idempotencia)
  ALTER TABLE .. DROP COLUMN→ DROP COLUMN IF EXISTS
  LIKE                      → ILIKE       (SQLite es case-insensitive en ASCII)
  PRAGMA table_info(t)      → consulta equivalente sobre information_schema
  PRAGMA foreign_key_list(t)→ consulta equivalente sobre pg_constraint
  otros PRAGMA              → no-op

Qué NO traduce (se resuelve en PostgreSQL con shims — ver pg_bootstrap.py)
  strftime(), julianday(), group_concat(), la vista sqlite_master

La traducción respeta literales de cadena, identificadores entrecomillados y
comentarios: dentro de ellos no se sustituye nada salvo el escapado de `%`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Iterator

# ── Segmentación léxica ──────────────────────────────────────────────────────
# Todo lo que casa aquí es "texto opaco": literales, identificadores
# entrecomillados y comentarios. El resto es código SQL sustituible.
_OPAQUE_RE = re.compile(
    r"""
      '(?:[^']|'')*'          # 'literal' con '' como escape
    | "(?:[^"]|"")*"          # "identificador"
    | --[^\n]*                # comentario de línea
    | /\*.*?\*/               # comentario de bloque
    """,
    re.VERBOSE | re.DOTALL,
)


def _segments(sql: str) -> Iterator[tuple[bool, str]]:
    """Trocea el SQL en (es_opaco, texto) preservando el orden."""
    pos = 0
    for m in _OPAQUE_RE.finditer(sql):
        if m.start() > pos:
            yield False, sql[pos:m.start()]
        yield True, m.group(0)
        pos = m.end()
    if pos < len(sql):
        yield False, sql[pos:]


# ── Reglas sobre código SQL (fuera de literales) ─────────────────────────────
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Clave primaria autoincremental.
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.I),
     "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bAUTOINCREMENT\b", re.I), ""),
    # En SQLite el tipo TIMESTAMP tiene afinidad NUMERIC pero CURRENT_TIMESTAMP
    # almacena texto 'YYYY-MM-DD HH:MM:SS'. El código mezcla esas columnas con
    # columnas TEXT de fecha (COALESCE(periodo_inicio, fecha_carga)), algo que
    # PostgreSQL rechaza si los tipos difieren. Declararlas TEXT reproduce el
    # comportamiento original exacto: comparación y orden lexicográficos ISO.
    (re.compile(r"\b(?:TIMESTAMP|DATETIME|DATE)\b(?!\s*\()", re.I), "TEXT"),
    (re.compile(r"\bCURRENT_TIMESTAMP\b", re.I),
     "(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"),
    (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
    # ALTER TABLE idempotente: en SQLite el código dependía de capturar el
    # error de columna duplicada; PostgreSQL lo resuelve declarativamente.
    (re.compile(r"\bADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\b)", re.I),
     "ADD COLUMN IF NOT EXISTS "),
    (re.compile(r"\bDROP\s+COLUMN\s+(?!IF\s+EXISTS\b)", re.I),
     "DROP COLUMN IF EXISTS "),
    # SQLite usa `IS` como comparación segura frente a NULL entre dos valores
    # cualesquiera (`d.cups IS f.cups`, `col IS ?`). PostgreSQL solo admite
    # `IS NULL/TRUE/FALSE/UNKNOWN` y `IS [NOT] DISTINCT FROM`.
    (re.compile(r"\bIS\s+NOT\s+(?!NULL\b|TRUE\b|FALSE\b|UNKNOWN\b|DISTINCT\b)", re.I),
     "IS DISTINCT FROM "),
    (re.compile(r"\bIS\s+(?!NOT\b|NULL\b|TRUE\b|FALSE\b|UNKNOWN\b|DISTINCT\b)", re.I),
     "IS NOT DISTINCT FROM "),
    # SQLite compara LIKE sin distinguir mayúsculas para ASCII; PostgreSQL sí.
    # ILIKE conserva el comportamiento que espera la aplicación.
    (re.compile(r"\bLIKE\b", re.I), "ILIKE"),
)

_INSERT_OR_IGNORE_RE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.I)
_INSERT_OR_REPLACE_RE = re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", re.I)
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.I)

# ── PRAGMA ───────────────────────────────────────────────────────────────────
_PRAGMA_TABLE_INFO_RE = re.compile(
    r"^\s*PRAGMA\s+table_info\s*\(\s*[\"']?(?P<t>[A-Za-z_][\w]*)[\"']?\s*\)\s*;?\s*$",
    re.I,
)
_PRAGMA_FK_LIST_RE = re.compile(
    r"^\s*PRAGMA\s+foreign_key_list\s*\(\s*[\"']?(?P<t>[A-Za-z_][\w]*)[\"']?\s*\)\s*;?\s*$",
    re.I,
)
_PRAGMA_ANY_RE = re.compile(r"^\s*PRAGMA\b", re.I)

# Reproduce las columnas de `PRAGMA table_info` en el mismo orden
# (cid, name, type, notnull, dflt_value, pk) porque el código lee row[1].
_TABLE_INFO_SQL = """
SELECT (c.ordinal_position - 1)::int                       AS cid,
       c.column_name::text                                 AS name,
       upper(c.data_type)::text                            AS type,
       (c.is_nullable = 'NO')::int                          AS notnull,
       c.column_default                                     AS dflt_value,
       COALESCE(pk.is_pk, 0)                                AS pk
  FROM information_schema.columns c
  LEFT JOIN (
        SELECT a.attname, 1 AS is_pk
          FROM pg_index i
          JOIN pg_attribute a ON a.attrelid = i.indrelid
                             AND a.attnum = ANY(i.indkey)
         WHERE i.indrelid = to_regclass('public.{t}') AND i.indisprimary
       ) pk ON pk.attname = c.column_name
 WHERE c.table_schema = 'public' AND c.table_name = '{t}'
 ORDER BY c.ordinal_position
"""

# Reproduce `PRAGMA foreign_key_list`: (id, seq, table, from, to, on_update,
# on_delete, match).
_FK_LIST_SQL = """
SELECT (row_number() OVER (ORDER BY con.oid) - 1)::int      AS id,
       0                                                    AS seq,
       cl.relname::text                                      AS "table",
       att.attname::text                                     AS "from",
       fatt.attname::text                                     AS "to",
       CASE con.confupdtype WHEN 'c' THEN 'CASCADE'
                            WHEN 'r' THEN 'RESTRICT'
                            WHEN 'n' THEN 'SET NULL'
                            WHEN 'd' THEN 'SET DEFAULT'
                            ELSE 'NO ACTION' END::text        AS on_update,
       CASE con.confdeltype WHEN 'c' THEN 'CASCADE'
                            WHEN 'r' THEN 'RESTRICT'
                            WHEN 'n' THEN 'SET NULL'
                            WHEN 'd' THEN 'SET DEFAULT'
                            ELSE 'NO ACTION' END::text        AS on_delete,
       'NONE'::text                                           AS match,
       con.conname::text                                      AS constraint_name
  FROM pg_constraint con
  JOIN pg_class cl   ON cl.oid = con.confrelid
  JOIN pg_attribute att  ON att.attrelid = con.conrelid  AND att.attnum  = con.conkey[1]
  JOIN pg_attribute fatt ON fatt.attrelid = con.confrelid AND fatt.attnum = con.confkey[1]
 WHERE con.contype = 'f' AND con.conrelid = to_regclass('public.{t}')
"""

_PRAGMA_NOOP_SQL = "SELECT 1 WHERE false"


class UnsupportedSQLError(NotImplementedError):
    """SQL de SQLite sin equivalencia automática en PostgreSQL."""


def _translate_pragma(sql: str) -> str | None:
    """Devuelve el SQL equivalente si `sql` es un PRAGMA, o None si no lo es."""
    m = _PRAGMA_TABLE_INFO_RE.match(sql)
    if m:
        return _TABLE_INFO_SQL.format(t=m.group("t"))
    m = _PRAGMA_FK_LIST_RE.match(sql)
    if m:
        return _FK_LIST_SQL.format(t=m.group("t"))
    if _PRAGMA_ANY_RE.match(sql):
        # journal_mode, foreign_keys, busy_timeout... no aplican en PostgreSQL.
        return _PRAGMA_NOOP_SQL
    return None


@lru_cache(maxsize=2048)
def translate(sql: str, has_params: bool = False) -> str:
    """
    Traduce una sentencia SQLite a PostgreSQL.

    Args:
        sql: sentencia en dialecto SQLite.
        has_params: True si se van a pasar parámetros. psycopg solo interpreta
            `%` como marcador de formato cuando hay parámetros, así que el
            escapado a `%%` únicamente se aplica en ese caso.

    Returns:
        Sentencia equivalente en dialecto PostgreSQL.
    """
    pragma = _translate_pragma(sql)
    if pragma is not None:
        return pragma

    if _INSERT_OR_REPLACE_RE.search(sql):
        raise UnsupportedSQLError(
            "INSERT OR REPLACE no tiene traducción automática: PostgreSQL "
            "necesita un destino de conflicto explícito. Reescribe la "
            "sentencia como INSERT ... ON CONFLICT (cols) DO UPDATE SET ..."
        )

    add_on_conflict = bool(_INSERT_OR_IGNORE_RE.search(sql))

    out: list[str] = []
    for opaque, text in _segments(sql):
        # El escapado de `%` va SIEMPRE antes de introducir los `%s`, para no
        # escapar los placeholders recién generados.
        if has_params:
            text = text.replace("%", "%%")
        if not opaque:
            text = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", text)
            for pattern, repl in _RULES:
                text = pattern.sub(repl, text)
            text = text.replace("?", "%s")
        out.append(text)

    result = "".join(out)

    if add_on_conflict:
        result = result.rstrip().rstrip(";")
        # ON CONFLICT debe preceder a RETURNING si la sentencia ya lo trae.
        m = _RETURNING_RE.search(result)
        if m:
            result = (result[:m.start()] + " ON CONFLICT DO NOTHING "
                      + result[m.start():])
        else:
            result += " ON CONFLICT DO NOTHING"
    return result


# ── Filas compatibles con sqlite3.Row ────────────────────────────────────────
class Row(Mapping):
    """
    Fila accesible por nombre (`row['col']`) y por posición (`row[0]`),
    igual que `sqlite3.Row`.

    psycopg ofrece `dict_row`, pero pierde el acceso posicional que usa el
    código existente (p. ej. `row[1]` al recorrer PRAGMA table_info, o
    `fetchone()[0]` en los COUNT). Esta clase soporta ambos y además conserva
    columnas duplicadas en el acceso posicional, cosa que un dict no puede.
    """

    __slots__ = ("_cols", "_values", "_index")

    def __init__(self, cols: Sequence[str], values: Sequence[Any]):
        self._cols = cols
        self._values = tuple(values)
        self._index = None  # se construye perezosamente

    def _name_index(self) -> dict[str, int]:
        if self._index is None:
            idx: dict[str, int] = {}
            for i, name in enumerate(self._cols):
                idx.setdefault(name, i)  # con duplicados gana la primera
            self._index = idx
        return self._index

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._name_index()[key]]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[Any]:
        """
        Itera sobre los *valores*, no sobre los nombres.

        Es lo que hace `sqlite3.Row`, y de lo que depende el código existente al
        hacer `tuple(fila)` o `a, b = fila`. Se aparta de `Mapping`, cuyo
        `__iter__` recorrería las claves, así que `values()` e `items()` se
        redefinen abajo para seguir siendo coherentes. `dict(fila)` sigue
        funcionando porque el constructor de dict usa `keys()`.
        """
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return list(self._cols)

    def values(self) -> tuple:
        return self._values

    def items(self):
        return list(zip(self._cols, self._values))

    def __contains__(self, key: Any) -> bool:
        return key in self._name_index()

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._cols, self._values))!r})"


def row_factory(cursor):
    """Row factory de psycopg que produce objetos `Row`."""
    desc = cursor.description
    if desc is None:
        return lambda values: values
    cols = [c.name for c in desc]
    return lambda values: Row(cols, values)
