#!/usr/bin/env python
"""
Vuelca los datos de la base SQLite original (`facturas_hc.db`) a PostgreSQL.

Se ejecuta una sola vez, al migrar una instalación existente. El esquema lo
crean las migraciones (`database/migrations.py`); este script solo mueve datos.

Uso
───
    # Volcado normal (las tablas destino deben estar vacías)
    python scripts/migrate_sqlite_to_pg.py

    # Indicando origen y destino explícitamente
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite facturas_hc.db \
        --dsn postgresql://portal:portal@localhost:5432/portal_hc

    # Repetir el volcado sobre una base que ya está en uso
    python scripts/migrate_sqlite_to_pg.py --vaciar

    # Ver qué haría, sin escribir nada
    python scripts/migrate_sqlite_to_pg.py --simular

Garantías
─────────
* Todo el volcado ocurre en una única transacción: si algo falla no queda una
  base a medias.
* Es seguro relanzarlo: se comprueba antes de migrar si el destino ya tenía
  datos propios y, si los tiene, aborta en lugar de pisarlos.
* Las tablas destino se vacían antes de copiar, de modo que el resultado es un
  reflejo exacto del SQLite y no una mezcla con los catálogos que siembran las
  migraciones.
* Las tablas se copian en orden de dependencias (padres antes que hijos) para
  no violar las claves foráneas.
* Al terminar se reajustan las secuencias BIGSERIAL, de modo que los INSERT
  posteriores no choquen con los ids ya importados.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Permite ejecutar el script directamente desde la raíz del proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from database.connection import CompatConnection, execute_raw  # noqa: E402
from database.sql_compat import row_factory  # noqa: E402

logger = logging.getLogger("volcado")

# Tablas que no deben copiarse: las gestiona el propio sistema de migraciones o
# son internas de SQLite.
TABLAS_EXCLUIDAS = {"schema_migrations", "sqlite_sequence", "sqlite_stat1"}


# ── Introspección ────────────────────────────────────────────────────────────

def tablas_sqlite(sq: sqlite3.Connection) -> list[str]:
    """Devuelve las tablas de usuario del fichero SQLite."""
    filas = sq.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [f[0] for f in filas if f[0] not in TABLAS_EXCLUIDAS]


def columnas_sqlite(sq: sqlite3.Connection, tabla: str) -> list[str]:
    return [f[1] for f in sq.execute(f'PRAGMA table_info("{tabla}")').fetchall()]


def columnas_pg(pg: psycopg.Connection, tabla: str) -> list[str]:
    filas = execute_raw(pg, """
        SELECT attname
          FROM pg_attribute
         WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped
         ORDER BY attnum
    """, (tabla,)).fetchall()
    return [f[0] for f in filas]


def tablas_pg(pg: psycopg.Connection) -> set[str]:
    filas = execute_raw(pg, """
        SELECT tablename FROM pg_tables WHERE schemaname = current_schema()
    """).fetchall()
    return {f[0] for f in filas}


def ordenar_por_dependencias(pg: psycopg.Connection,
                             tablas: list[str]) -> list[str]:
    """
    Ordena las tablas de forma que ninguna se copie antes que aquellas a las que
    referencia por clave foránea.

    Se usa el catálogo de PostgreSQL (y no el de SQLite) porque es el destino
    quien va a validar las restricciones. Las autorreferencias se ignoran: no
    condicionan el orden entre tablas distintas.
    """
    conjunto = set(tablas)
    dependencias: dict[str, set[str]] = {t: set() for t in tablas}

    filas = execute_raw(pg, """
        SELECT origen.relname AS hija, destino.relname AS padre
          FROM pg_constraint c
          JOIN pg_class origen  ON origen.oid  = c.conrelid
          JOIN pg_class destino ON destino.oid = c.confrelid
         WHERE c.contype = 'f'
    """).fetchall()
    for hija, padre in filas:
        if hija in conjunto and padre in conjunto and hija != padre:
            dependencias[hija].add(padre)

    ordenadas: list[str] = []
    pendientes = set(tablas)
    while pendientes:
        resueltas = set(ordenadas)
        listas = sorted(t for t in pendientes if not (dependencias[t] - resueltas))
        if not listas:
            # Ciclo de claves foráneas: se copian en orden alfabético y se deja
            # que PostgreSQL valide al final de la transacción.
            logger.warning("Ciclo de claves foráneas entre: %s",
                           ", ".join(sorted(pendientes)))
            ordenadas.extend(sorted(pendientes))
            break
        ordenadas.extend(listas)
        pendientes -= set(listas)
    return ordenadas


# ── Volcado ──────────────────────────────────────────────────────────────────

def contar(pg: psycopg.Connection, tabla: str) -> int:
    return execute_raw(pg, f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]


def copiar_tabla(sq: sqlite3.Connection, pg: psycopg.Connection,
                 tabla: str, columnas: list[str]) -> int:
    """Copia una tabla con COPY, mucho más rápido que INSERT fila a fila."""
    lista = ", ".join(f'"{c}"' for c in columnas)
    origen = sq.execute(f'SELECT {lista} FROM "{tabla}"')

    copiadas = 0
    with pg.cursor() as cur:
        with cur.copy(f'COPY "{tabla}" ({lista}) FROM STDIN') as copy:
            while True:
                lote = origen.fetchmany(1000)
                if not lote:
                    break
                for fila in lote:
                    copy.write_row(tuple(fila))
                    copiadas += 1
    return copiadas


def reajustar_secuencias(pg: psycopg.Connection, tablas: list[str]) -> None:
    """
    Pone cada secuencia BIGSERIAL por encima del id máximo importado.

    Sin esto, el primer INSERT tras la migración reutilizaría el id 1 y fallaría
    por clave primaria duplicada.
    """
    for tabla in tablas:
        filas = execute_raw(pg, """
            SELECT a.attname, pg_get_serial_sequence(%s, a.attname)
              FROM pg_attribute a
             WHERE a.attrelid = %s::regclass AND a.attnum > 0
               AND NOT a.attisdropped
               AND pg_get_serial_sequence(%s, a.attname) IS NOT NULL
        """, (tabla, tabla, tabla)).fetchall()
        for columna, secuencia in filas:
            execute_raw(pg, f'''
                SELECT setval(%s,
                              COALESCE((SELECT MAX("{columna}") FROM "{tabla}"), 0) + 1,
                              false)
            ''', (secuencia,))
            logger.info("  secuencia %s reajustada", secuencia)


# ── Programa principal ───────────────────────────────────────────────────────

def datos_previos(dsn: str) -> list[str]:
    """
    Tablas con filas en el destino *antes* de ejecutar las migraciones.

    Se comprueba antes de migrar a propósito: las migraciones siembran los
    catálogos (paises, tipos_energia, factores_emision...), así que una base
    recién migrada nunca está vacía y el aviso sería siempre falso. Si hay datos
    antes de migrar, en cambio, el destino está realmente en uso.
    """
    pg = CompatConnection.connect(dsn, row_factory=row_factory, autocommit=True)
    try:
        return [t for t in sorted(tablas_pg(pg)) if contar(pg, t) > 0]
    finally:
        pg.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vuelca los datos de SQLite a PostgreSQL.")
    parser.add_argument("--sqlite", default="facturas_hc.db",
                        help="Fichero SQLite de origen (por defecto facturas_hc.db)")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"),
                        help="Cadena de conexión PostgreSQL (por defecto DATABASE_URL)")
    parser.add_argument("--vaciar", action="store_true",
                        help="Continúa aunque el destino ya tuviera datos propios")
    parser.add_argument("--simular", action="store_true",
                        help="Muestra el plan sin escribir nada")
    parser.add_argument("--sin-migrar", dest="sin_migrar", action="store_true",
                        help="No ejecuta las migraciones de esquema previas")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    origen = Path(args.sqlite)
    if not origen.exists():
        logger.error("No existe el fichero SQLite: %s", origen)
        return 1
    if not args.dsn:
        logger.error("Falta el destino: define DATABASE_URL o usa --dsn")
        return 1

    previas = datos_previos(args.dsn)
    if previas and not args.vaciar:
        logger.error("El destino ya contiene datos propios en: %s",
                     ", ".join(previas))
        logger.error("Este script reemplaza el contenido completo de las tablas "
                     "que existan también en SQLite.")
        logger.error("Usa --vaciar si quieres continuar de todas formas, o "
                     "apunta a una base de datos limpia.")
        return 1

    if not args.sin_migrar and not args.simular:
        logger.info("Ejecutando migraciones de esquema en el destino...")
        os.environ["DATABASE_URL"] = args.dsn
        from database.migrations import ejecutar_migraciones
        ejecutar_migraciones()

    sq = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    pg = CompatConnection.connect(args.dsn, row_factory=row_factory,
                                  autocommit=False)
    try:
        disponibles = tablas_pg(pg)
        en_sqlite = tablas_sqlite(sq)
        candidatas = [t for t in en_sqlite if t in disponibles]
        ausentes = [t for t in en_sqlite if t not in disponibles]
        if ausentes:
            logger.warning("Tablas de SQLite sin equivalente en PostgreSQL "
                           "(se omiten): %s", ", ".join(ausentes))

        orden = ordenar_por_dependencias(pg, candidatas)

        if args.simular:
            for tabla in orden:
                presentes = set(columnas_pg(pg, tabla))
                comunes = [c for c in columnas_sqlite(sq, tabla) if c in presentes]
                n_origen = sq.execute(
                    f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]
                logger.info("[simulación] %-30s %6d filas · %d columnas",
                            tabla, n_origen, len(comunes))
            logger.info("Simulación terminada; no se ha escrito nada.")
            pg.rollback()
            return 0

        # Se vacían todas las tablas destino antes de copiar (en orden inverso
        # al de dependencias) para que el volcado sea un reemplazo limpio: si no,
        # los catálogos que siembran las migraciones chocarían con los de SQLite.
        for tabla in reversed(orden):
            execute_raw(pg, f'TRUNCATE TABLE "{tabla}" CASCADE')

        total = 0
        for tabla in orden:
            presentes = set(columnas_pg(pg, tabla))
            comunes = [c for c in columnas_sqlite(sq, tabla) if c in presentes]
            copiadas = copiar_tabla(sq, pg, tabla, comunes) if comunes else 0
            total += copiadas
            logger.info("%-30s %6d filas copiadas", tabla, copiadas)

        logger.info("Reajustando secuencias...")
        reajustar_secuencias(pg, orden)

        pg.commit()
        logger.info("Volcado completado: %d filas en %d tablas.", total, len(orden))
        return 0
    except Exception:
        pg.rollback()
        logger.exception("Volcado abortado; no se ha modificado el destino.")
        return 1
    finally:
        sq.close()
        pg.close()


if __name__ == "__main__":
    raise SystemExit(main())
