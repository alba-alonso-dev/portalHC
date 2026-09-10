"""
Migraciones de base de datos (PostgreSQL).

Todas las operaciones son aditivas (no se elimina ni modifica ninguna columna
existente) para garantizar compatibilidad con datos historicos.

Thread-safety y multi-proceso
--------------------------------
`ejecutar_migraciones()` se llama al importar app.py.

Nivel 1 - mismo proceso, hilos distintos:
  _migration_lock (threading.Lock) serializa llamadas concurrentes dentro del
  mismo proceso (Flask dev server con reloader, tests concurrentes).

Nivel 2 - procesos distintos (Gunicorn multi-worker sin --preload):
  Advisory lock de PostgreSQL (`pg_advisory_lock`). Sustituye al lock de
  fichero de la version SQLite: lo gestiona el propio servidor, se libera solo
  al cerrar la conexion y por tanto no puede quedar huerfano si un worker
  muere.

Nivel 3 - idempotencia SQL:
  CREATE TABLE IF NOT EXISTS, ALTER TABLE ADD COLUMN IF NOT EXISTS e
  INSERT ... ON CONFLICT DO NOTHING (la capa de compatibilidad traduce el
  `INSERT OR IGNORE` original). Ademas cada sentencia DDL se ejecuta dentro de
  un savepoint, de modo que un error no invalida la transaccion completa.

Recomendacion para produccion:
  gunicorn --preload --workers=4 app:app
"""

import contextlib
import json
import logging
import os
import threading

import psycopg

from database.connection import (DATABASE_URL, IntegrityError, OperationalError,
                                 execute_raw, get_db_connection)
from database.pg_bootstrap import asegurar_compat_sql
import config

logger = logging.getLogger(__name__)

# -- Nivel 1: lock de hilo --------------------------------------------------
_migration_lock = threading.Lock()

# -- Nivel 2: lock de proceso (advisory lock de PostgreSQL) -----------------
# Clave arbitraria pero estable para este proyecto. Cualquier otro proceso que
# intente migrar la misma base de datos espera aqui hasta que el primero acabe.
_ADVISORY_LOCK_KEY = 8074199001


@contextlib.contextmanager
def _lock_migraciones():
    """
    Serializa las migraciones entre procesos con un advisory lock de sesion.

    El lock vive en su propia conexion: se libera automaticamente al cerrarla,
    incluso si el proceso muere de forma abrupta.
    """
    with get_db_connection() as conn:
        execute_raw(conn, "SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            yield
        finally:
            try:
                execute_raw(conn, "SELECT pg_advisory_unlock(%s)",
                            (_ADVISORY_LOCK_KEY,))
            except psycopg.Error:
                pass  # la conexion se cierra igualmente y el lock se libera


def _alter_table_safe(conn: psycopg.Connection, sql: str) -> bool:
    """
    Ejecuta un ALTER TABLE ADD COLUMN de forma idempotente.

    La capa de compatibilidad traduce `ADD COLUMN` a `ADD COLUMN IF NOT EXISTS`,
    asÃ­ que PostgreSQL ya no lanza error si la columna existe. Se mantiene la
    captura por si el ALTER falla por otro motivo recuperable.

    Devuelve True si la sentencia se ejecutÃ³, False si la columna ya existÃ­a.
    """
    try:
        conn.execute(sql)
        return True
    except OperationalError as exc:
        if 'already exists' in str(exc).lower():
            return False  # idempotente â€” columna ya existe
        raise


def ejecutar_migraciones():
    """
    Punto de entrada principal. Ejecuta todas las migraciones en orden.
    Protegido por lock de hilo (threading.Lock) y advisory lock de PostgreSQL.
    """
    with _migration_lock:
        with _lock_migraciones():
            _instalar_compat_sql()
            _ejecutar_migraciones_interno()


def _instalar_compat_sql():
    """
    Instala en PostgreSQL las funciones que el SQL de la app hereda de SQLite
    (strftime, julianday, group_concat y la vista sqlite_master).

    Debe ejecutarse antes que cualquier migraciÃ³n, porque algunas consultan
    sqlite_master para decidir si una tabla existe.
    """
    with get_db_connection() as conn:
        asegurar_compat_sql(conn)


def _ejecutar_migraciones_interno():
    """LÃ³gica real de migraciones. Llamar siempre con _migration_lock."""
    logger.info("Iniciando migraciones de base de datos...")

    # Tabla de control de versiones. Permite saltar mÃ³dulos ya ejecutados en
    # arranques sucesivos (antes se re-ejecutaban todos en cada boot, con coste
    # notable: p. ej. _recalcular_emisiones_facturas reescribÃ­a toda la columna
    # emisiones_tco2e cada vez). La primera vez que se corre contra una BD
    # existente, los mÃ³dulos se ejecutan una Ãºltima vez (son idempotentes) y
    # quedan registrados; a partir de ahÃ­ solo se ejecutan los nuevos.
    _crear_tabla_schema_migrations()

    _ejecutar_modulo("base", _migraciones_base,
                     "Tablas base: facturas, lotes, factores_emision + seeding")

    _ejecutar_modulo("fase2", lambda conn: _importar_y_ejecutar(
        "database.migrations_fase2", "ejecutar_migraciones_fase2"),
        "Fase 2: gestiÃ³n de factores con versionado y trazabilidad")

    _ejecutar_modulo("fase3", lambda conn: _importar_y_ejecutar(
        "database.migrations_fase3", "ejecutar_migraciones_fase3"),
        "Fase 3: recÃ¡lculo, estimaciones y calidad de datos")

    _ejecutar_modulo("refactor", lambda conn: _importar_y_ejecutar(
        "database.migrations_refactor", "ejecutar_migraciones_refactor"),
        "RefactorizaciÃ³n Pre-Fase 4: tablas maestras, Ã­ndices, limpieza deuda tÃ©cnica")

    _ejecutar_modulo("mejoras", lambda conn: _importar_y_ejecutar(
        "database.migrations_mejoras", "ejecutar_migraciones_mejoras"),
        "Mejoras arquitectÃ³nicas: audit_log, facturas_historial, suministros,"
        " sha256_documento, detecciÃ³n de duplicados, escalabilidad a nuevos suministros")

    _ejecutar_modulo("fase4", lambda conn: _importar_y_ejecutar(
        "database.migrations_fase4", "ejecutar_migraciones_fase4"),
        "Fase 4: Dashboard ESG, Alertas automÃ¡ticas, Informe GHG")

    _ejecutar_modulo("fase5", lambda conn: _importar_y_ejecutar(
        "database.migrations_fase5", "ejecutar_migraciones_fase5"),
        "Fase 5: Afinado y ValidaciÃ³n â€” columnas ejercicio, cups, inconsistencias,"
        " carpeta_relativa en facturas, tabla documentos_indice")

    _ejecutar_modulo("fase6", lambda conn: _importar_y_ejecutar(
        "database.migrations_fase6", "ejecutar_migraciones_fase6"),
        "Fase 6: GestiÃ³n ESG â€” tabla objetivos_emision, mÃ©tricas de estimaciÃ³n,"
        " columnas de reconciliaciÃ³n en estimaciones")

    _ejecutar_modulo("campos_factura", lambda conn: _importar_y_ejecutar(
        "database.migrations_campos_factura", "ejecutar_migraciones_campos_factura"),
        "Campos comerciales/tÃ©cnicos de factura: importe+moneda, tarifa, contrato,"
        " potencia contratada y distribuidora")

    # NormalizaciÃ³n de sedes: fusiona las sedes que solo se diferencian en tildes,
    # mayÃºsculas o espacios (p. ej. "Almeria" vs "AlmerÃ­a"), que el UNIQUE literal
    # de la tabla no detecta y que partÃ­an las agregaciones por sede en dos.
    # Debe ir despuÃ©s de refactor, que es quien puebla la tabla.
    _ejecutar_modulo("sedes", lambda conn: _importar_y_ejecutar(
        "database.migrations_sedes", "ejecutar_migraciones_sedes"),
        "NormalizaciÃ³n de sedes (tildes, mayÃºsculas, espacios)")

    # Integridad referencial: borra las filas huÃ©rfanas que dejaban los borrados
    # masivos de datos (documentos_indice y facturas_historial apuntando a
    # facturas ya inexistentes) y aÃ±ade ON DELETE CASCADE a facturas_historial.
    # Debe ir la Ãºltima, cuando el resto de tablas ya tienen su forma final.
    _ejecutar_modulo("integridad", lambda conn: _importar_y_ejecutar(
        "database.migrations_integridad", "ejecutar_migraciones_integridad"),
        "Integridad referencial: limpieza de huÃ©rfanos y CASCADE")

    # Multi-CUPS: corrige los falsos "duplicados" de las sedes con varios puntos
    # de suministro (facturas complementarias cuyo consumo se suma) y da de alta
    # un suministro por CUPS. Va despuÃ©s de integridad y de sedes, que son quienes
    # dejan las tablas `facturas` y `sedes` en su forma final.
    _ejecutar_modulo("multicups", lambda conn: _importar_y_ejecutar(
        "database.migrations_multicups", "ejecutar_migraciones_multicups"),
        "Multi-CUPS: un suministro por CUPS, detecciÃ³n de duplicados falsos")

    # Sociedades: maestro de entidades legales (razÃ³n social + CIF) y vinculaciÃ³n
    # con suministros. Una sede puede tener varios CUPS facturados a sociedades
    # distintas del grupo; antes la sociedad era texto libre en facturas. Va
    # despuÃ©s de multi-CUPS, que es quien crea/revincula los suministros por CUPS.
    _ejecutar_modulo("sociedades", lambda conn: _importar_y_ejecutar(
        "database.migrations_sociedades", "ejecutar_migraciones_sociedades"),
        "Sociedades: maestro de entidades legales y vinculaciÃ³n con suministros")

    logger.info("Migraciones completadas")


def _crear_tabla_schema_migrations():
    """Crea la tabla de control de versiones de migraciones si no existe."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                modulo            TEXT PRIMARY KEY,
                descripcion       TEXT,
                fecha_ejecucion   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')


def _migracion_ya_ejecutada(conn: psycopg.Connection, modulo: str) -> bool:
    """Devuelve True si el mÃ³dulo ya estÃ¡ registrado en schema_migrations."""
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE modulo = ?", (modulo,)
    ).fetchone()
    return row is not None


def _marcar_migracion_completada(conn: psycopg.Connection, modulo: str,
                                  descripcion: str = ""):
    """Registra un mÃ³dulo como completado (INSERT OR IGNORE = idempotente)."""
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (modulo, descripcion) VALUES (?, ?)",
        (modulo, descripcion)
    )


def _ejecutar_modulo(modulo: str, funcion_migracion, descripcion: str = ""):
    """
    Ejecuta un mÃ³dulo de migraciÃ³n si no estÃ¡ ya registrado en schema_migrations.

    Si el mÃ³dulo ya fue ejecutado antes, se omite (no se re-ejecuta su cuerpo).
    La primera vez que se corre contra una BD existente, el mÃ³dulo se ejecuta
    una Ãºltima vez (es idempotente) y queda registrado.

    El registro se hace en la MISMA conexiÃ³n que la migraciÃ³n, de modo que si
    esta falla no quede marcada como completada (atomicidad por transacciÃ³n).
    """
    with get_db_connection() as conn:
        if _migracion_ya_ejecutada(conn, modulo):
            logger.debug("  = mÃ³dulo '%s' ya ejecutado â€” omitido", modulo)
            return
        logger.info("  â†’ ejecutando mÃ³dulo '%s'...", modulo)
        funcion_migracion(conn)
        _marcar_migracion_completada(conn, modulo, descripcion)
        logger.info("  âœ“ mÃ³dulo '%s' completado y registrado", modulo)


def _migraciones_base(conn: psycopg.Connection):
    """Migraciones base: tablas facturas, lotes y factores_emision + seeding."""
    _crear_tabla_facturas_base(conn)
    _migrar_facturas_nuevas_columnas(conn)
    _crear_tabla_lotes(conn)
    _crear_tabla_factores_emision(conn)
    _poblar_factores_emision(conn)


def _importar_y_ejecutar(modulo_path: str, funcion_nombre: str):
    """
    Importa y ejecuta una funciÃ³n de migraciÃ³n desde un mÃ³dulo externo.

    El import es diferido (dentro de la funciÃ³n) para evitar imports circulares
    y mantener el orden de inicializaciÃ³n. Las funciones de migraciÃ³n externas
    abren su propia conexiÃ³n (son idempotentes); el registro en schema_migrations
    garantiza que no se re-ejecuten en el siguiente arranque.
    """
    import importlib
    modulo = importlib.import_module(modulo_path)
    funcion = getattr(modulo, funcion_nombre)
    funcion()


# â”€â”€ Tabla facturas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _crear_tabla_facturas_base(conn: psycopg.Connection):
    """Crea la tabla facturas si no existe (schema base compatible con v1)."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS facturas (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            pais                 TEXT NOT NULL,
            sede                 TEXT NOT NULL,
            archivo_nombre       TEXT NOT NULL,
            archivo_ruta         TEXT,
            consumo_kwh          REAL,
            consumo_mwh          REAL,
            comercializadora     TEXT,
            factor_emision       REAL,
            emisiones_tco2e      REAL,
            estado               TEXT DEFAULT 'procesada',
            fecha_carga          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            datos_json           TEXT,
            notas                TEXT
        )
    ''')


def _migrar_facturas_nuevas_columnas(conn: psycopg.Connection):
    """AÃ±ade columnas de Fase 1 si aÃºn no existen. ALTER TABLE es seguro: no borra datos."""
    columnas_nuevas = [
        ("tipo_energia",          "TEXT DEFAULT 'electricidad'"),
        ("fecha_factura",         "TEXT"),
        ("periodo_inicio",        "TEXT"),
        ("periodo_fin",           "TEXT"),
        ("dias_facturados",       "INTEGER"),
        ("sociedad",              "TEXT"),
        ("direccion_suministro",  "TEXT"),
        ("cups",                  "TEXT"),
        ("confianza_ocr",         "REAL"),
        ("campos_confianza",      "TEXT"),   # JSON
        ("lote_id",               "TEXT"),
    ]

    existentes = {row[1] for row in conn.execute("PRAGMA table_info(facturas)")}
    for nombre, tipo in columnas_nuevas:
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE facturas ADD COLUMN {nombre} {tipo}")
            logger.info(f"  + columna aÃ±adida: facturas.{nombre}")


# â”€â”€ Tabla lotes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _crear_tabla_lotes(conn: psycopg.Connection):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lotes (
            id                TEXT PRIMARY KEY,
            fecha_inicio      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_fin         TIMESTAMP,
            total_archivos    INTEGER NOT NULL,
            procesados_ok     INTEGER DEFAULT 0,
            procesados_error  INTEGER DEFAULT 0,
            estado            TEXT DEFAULT 'procesando',
            resultados_json   TEXT DEFAULT '[]',
            usuario           TEXT,
            notas             TEXT
        )
    ''')


# â”€â”€ Tabla factores_emision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _crear_tabla_factores_emision(conn: psycopg.Connection):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS factores_emision (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            pais                  TEXT NOT NULL,
            tipo_energia          TEXT NOT NULL DEFAULT 'electricidad',
            anio                  TEXT NOT NULL,
            factor_kg_co2_mwh     REAL NOT NULL,
            fuente                TEXT,
            url                   TEXT,
            activo                INTEGER DEFAULT 1,
            fecha_carga           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pais, tipo_energia, anio)
        )
    ''')


def _poblar_factores_emision(conn: psycopg.Connection):
    """Carga en BD los factores definidos en config.py (ignora si ya existen)."""
    factores = getattr(config, 'FACTORES_EMISION', {})
    if not factores:
        return

    for pais, datos in factores.items():
        fuente = datos.get('fuente', '')
        url = datos.get('url', '')
        for clave, valor in datos.items():
            if clave.isdigit() and isinstance(valor, (int, float)):
                try:
                    conn.execute('''
                        INSERT OR IGNORE INTO factores_emision
                            (pais, tipo_energia, anio, factor_kg_co2_mwh, fuente, url)
                        VALUES (?, 'electricidad', ?, ?, ?, ?)
                    ''', (pais, clave, float(valor), fuente, url))
                except Exception as e:
                    logger.warning(f"Factor {pais}/{clave}: {e}")
