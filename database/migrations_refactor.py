"""
Migraciones de refactorización — Pre-Fase 4.

Mejoras aplicadas:
  1. Tablas maestras: paises, tipos_energia, sedes, comercializadoras.
  2. facturas: columnas de integración externa (external_source, external_doc_id, external_doc_url).
  3. facturas: columna fecha_anulacion para soft-delete.
  4. facturas: elimina columnas redundantes (mes, anio_factor, fuente_factor).
  5. Elimina tabla factores_emision_legacy (backup ya innecesario).
  6. Índices de rendimiento para las consultas más frecuentes.
  7. Preparación Fase 4: tablas fuentes_documentos y sync_log.

Principios:
  - Todas las operaciones son idempotentes.
  - Los datos existentes no se pierden; solo se eliminan metadatos redundantes
    cuya información ya está en factores_emision via factor_version_id.
"""

import logging
from database.connection import get_db_connection
import config

logger = logging.getLogger(__name__)


def ejecutar_migraciones_refactor():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("🔄  Refactorización BD: iniciando...")
    _crear_paises()
    _poblar_paises()
    _crear_tipos_energia()
    _poblar_tipos_energia()
    _crear_sedes()
    _poblar_sedes()
    _crear_comercializadoras()
    _poblar_comercializadoras()
    _actualizar_facturas_nuevas_cols()
    _drop_columnas_redundantes()
    _drop_tabla_legacy()
    _crear_indices()
    _crear_fuentes_documentos()
    _crear_sync_log()
    logger.info("✅  Refactorización BD completada")


# ── 1. Tabla paises ──────────────────────────────────────────────────────────

def _crear_paises():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS paises (
                codigo          TEXT PRIMARY KEY,
                nombre          TEXT NOT NULL,
                zona_horaria    TEXT,
                activo          INTEGER DEFAULT 1
            )
        ''')


def _poblar_paises():
    datos = [
        ('AR', 'Argentina',  'America/Argentina/Buenos_Aires'),
        ('CL', 'Chile',      'America/Santiago'),
        ('CO', 'Colombia',   'America/Bogota'),
        ('EC', 'Ecuador',    'America/Guayaquil'),
        ('ES', 'España',     'Europe/Madrid'),
        ('MX', 'México',     'America/Mexico_City'),
    ]
    with get_db_connection() as conn:
        for row in datos:
            conn.execute(
                'INSERT OR IGNORE INTO paises (codigo, nombre, zona_horaria) VALUES (?,?,?)',
                row
            )


# ── 2. Tabla tipos_energia ───────────────────────────────────────────────────

def _crear_tipos_energia():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tipos_energia (
                codigo          TEXT PRIMARY KEY,
                nombre          TEXT NOT NULL,
                unidad_medida   TEXT NOT NULL,
                unidad_emision  TEXT NOT NULL,
                activo          INTEGER DEFAULT 1
            )
        ''')


def _poblar_tipos_energia():
    """Electricidad activo; rest preparados para Fase 5 (activo=0 por ahora)."""
    datos = [
        ('electricidad', 'Electricidad',    'kWh',  'kg CO2eq/MWh', 1),
        ('gas',          'Gas Natural',     'm3',   'kg CO2eq/m3',  0),
        ('agua',         'Agua',            'm3',   'kg CO2eq/m3',  0),
        ('residuos',     'Residuos',        'kg',   'kg CO2eq/kg',  0),
        ('viajes',       'Viajes empresa',  'km',   'kg CO2eq/km',  0),
    ]
    with get_db_connection() as conn:
        for row in datos:
            conn.execute(
                'INSERT OR IGNORE INTO tipos_energia '
                '(codigo, nombre, unidad_medida, unidad_emision, activo) VALUES (?,?,?,?,?)',
                row
            )


# ── 3. Tabla sedes ───────────────────────────────────────────────────────────

def _crear_sedes():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sedes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pais_codigo     TEXT NOT NULL REFERENCES paises(codigo),
                nombre          TEXT NOT NULL,
                direccion       TEXT,
                activo          INTEGER DEFAULT 1,
                UNIQUE(pais_codigo, nombre)
            )
        ''')


def _poblar_sedes():
    """
    Carga desde config.SEDES_PAISES + sedes ya existentes en facturas.

    El UNIQUE(pais_codigo, nombre) de la tabla compara literales, así que por sí solo
    no impide que "Almería" (config) y "Almeria" (dato histórico en facturas)
    convivan como dos sedes distintas. Para evitarlo, la comprobación previa se hace
    con una clave insensible a tildes/mayúsculas: config.py tiene prioridad y
    cualquier variante equivalente que llegue desde facturas se descarta.
    """
    from database.migrations_sedes import clave_sede

    sedes_config = getattr(config, 'SEDES_PAISES', {})
    with get_db_connection() as conn:
        # Claves ya presentes, para no crear variantes equivalentes de la misma sede
        vistas = {
            (r['pais_codigo'], clave_sede(r['nombre']))
            for r in conn.execute('SELECT pais_codigo, nombre FROM sedes')
        }

        def _insertar(pais: str, nombre: str):
            pais = pais.upper()
            clave = (pais, clave_sede(nombre))
            if clave in vistas:
                return
            conn.execute(
                'INSERT OR IGNORE INTO sedes (pais_codigo, nombre) VALUES (?,?)',
                (pais, nombre)
            )
            vistas.add(clave)

        # Desde config.py (grafía canónica, tiene prioridad)
        for pais, lista in sedes_config.items():
            for sede in lista:
                _insertar(pais, sede)

        # Desde facturas existentes (datos reales que podrían no estar en config)
        rows = conn.execute(
            'SELECT DISTINCT pais, sede FROM facturas WHERE pais IS NOT NULL AND sede IS NOT NULL'
        ).fetchall()
        for row in rows:
            _insertar(row['pais'], row['sede'])


# ── 4. Tabla comercializadoras ───────────────────────────────────────────────

def _crear_comercializadoras():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS comercializadoras (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pais_codigo     TEXT REFERENCES paises(codigo),
                nombre          TEXT NOT NULL,
                tipo_energia    TEXT DEFAULT 'electricidad',
                activo          INTEGER DEFAULT 1,
                UNIQUE(pais_codigo, nombre, tipo_energia)
            )
        ''')


def _poblar_comercializadoras():
    comercializadoras = getattr(config, 'COMERCIALIZADORAS', {})
    with get_db_connection() as conn:
        for pais, lista in comercializadoras.items():
            for nombre in lista:
                conn.execute(
                    'INSERT OR IGNORE INTO comercializadoras '
                    '(pais_codigo, nombre, tipo_energia) VALUES (?,?,?)',
                    (pais.upper(), nombre, 'electricidad')
                )
        # Desde facturas existentes
        rows = conn.execute(
            'SELECT DISTINCT pais, comercializadora FROM facturas '
            'WHERE comercializadora IS NOT NULL'
        ).fetchall()
        for row in rows:
            conn.execute(
                'INSERT OR IGNORE INTO comercializadoras '
                '(pais_codigo, nombre, tipo_energia) VALUES (?,?,?)',
                (row['pais'].upper(), row['comercializadora'], 'electricidad')
            )


# ── 5. Nuevas columnas en facturas ───────────────────────────────────────────

def _actualizar_facturas_nuevas_cols():
    """
    Añade columnas necesarias para Fase 4 (integración SharePoint)
    y para soft-delete correcto.
    """
    nuevas = [
        ('external_source',  "TEXT DEFAULT 'local'"),  # 'local'|'sharepoint'|'api'|'manual'
        ('external_doc_id',  'TEXT'),                   # ID del documento en SharePoint/sistema externo
        ('external_doc_url', 'TEXT'),                   # URL directa al documento
        ('fecha_anulacion',  'TIMESTAMP'),              # Soft-delete timestamp
    ]
    with get_db_connection() as conn:
        existentes = {r[1] for r in conn.execute('PRAGMA table_info(facturas)')}
        for nombre, tipo in nuevas:
            if nombre not in existentes:
                conn.execute(f'ALTER TABLE facturas ADD COLUMN {nombre} {tipo}')
                logger.info(f'  + columna añadida: facturas.{nombre}')


# ── 6. Eliminar columnas redundantes ─────────────────────────────────────────

def _drop_columnas_redundantes():
    """
    Elimina columnas que duplican información ya trazable via FK:
      - mes          → redundante con periodo_inicio[:7]
      - anio_factor  → redundante con factor_version_id → factores_emision.anio
      - fuente_factor→ redundante con factor_version_id → factores_emision.fuente

    SQLite >= 3.35 soporta ALTER TABLE DROP COLUMN.
    Se comprueba la existencia antes de intentar el DROP (idempotente).
    """
    columnas_a_borrar = ['mes', 'anio_factor', 'fuente_factor']
    with get_db_connection() as conn:
        existentes = {r[1] for r in conn.execute('PRAGMA table_info(facturas)')}
        for col in columnas_a_borrar:
            if col in existentes:
                conn.execute(f'ALTER TABLE facturas DROP COLUMN {col}')
                logger.info(f'  - columna eliminada: facturas.{col}')


# ── 7. Eliminar tabla legacy ─────────────────────────────────────────────────

def _drop_tabla_legacy():
    """Elimina el backup de pre-Fase 2. Ya no tiene valor operativo."""
    with get_db_connection() as conn:
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if 'factores_emision_legacy' in tablas:
            conn.execute('DROP TABLE factores_emision_legacy')
            logger.info('  - tabla eliminada: factores_emision_legacy')


# ── 8. Índices de rendimiento ────────────────────────────────────────────────

def _crear_indices():
    """
    Crea índices para las queries más frecuentes del portal.
    Sin índices, todas las queries hacen full table scan (crítico a >10k filas).
    """
    indices = [
        # facturas — consultas de historial y estadísticas
        ('idx_facturas_pais_tipo',
         'CREATE INDEX IF NOT EXISTS idx_facturas_pais_tipo ON facturas(pais, tipo_energia)'),
        ('idx_facturas_periodo',
         'CREATE INDEX IF NOT EXISTS idx_facturas_periodo ON facturas(periodo_inicio)'),
        ('idx_facturas_sede_periodo',
         'CREATE INDEX IF NOT EXISTS idx_facturas_sede_periodo ON facturas(sede, periodo_inicio)'),
        ('idx_facturas_estado',
         'CREATE INDEX IF NOT EXISTS idx_facturas_estado ON facturas(estado)'),
        ('idx_facturas_tipo_dato',
         'CREATE INDEX IF NOT EXISTS idx_facturas_tipo_dato ON facturas(tipo_dato)'),
        ('idx_facturas_external_doc',
         'CREATE UNIQUE INDEX IF NOT EXISTS idx_facturas_external_doc ON facturas(external_doc_id) '
         'WHERE external_doc_id IS NOT NULL'),
        # factores_emision — lookup crítico en cada cálculo
        ('idx_factores_lookup',
         'CREATE INDEX IF NOT EXISTS idx_factores_lookup '
         'ON factores_emision(pais, tipo_energia, anio, es_version_activa)'),
        # periodos_faltantes — gaps detection
        ('idx_periodos_lookup',
         'CREATE INDEX IF NOT EXISTS idx_periodos_lookup '
         'ON periodos_faltantes(pais, sede, tipo_energia, mes)'),
        # recalculos_historial — consultas de auditoría
        ('idx_recalculos_factura',
         'CREATE INDEX IF NOT EXISTS idx_recalculos_factura '
         'ON recalculos_historial(factura_id)'),
        # estimaciones — consultas de calidad y estimación
        ('idx_estimaciones_lookup',
         'CREATE INDEX IF NOT EXISTS idx_estimaciones_lookup '
         'ON estimaciones(pais, sede, tipo_energia, mes)'),
        # factores_historial — auditoría de cambios
        ('idx_fhist_factor',
         'CREATE INDEX IF NOT EXISTS idx_fhist_factor ON factores_historial(factor_id)'),
    ]
    with get_db_connection() as conn:
        for nombre, sql in indices:
            conn.execute(sql)
            logger.debug(f'  ✓ índice: {nombre}')
    logger.info(f'  ✓ {len(indices)} índices creados/verificados')


# ── 9. Preparación Fase 4: fuentes de documentos ────────────────────────────

def _crear_fuentes_documentos():
    """
    Registra las fuentes desde donde se importan documentos:
    SharePoint libraries, SFTP, directorios locales, APIs externas.
    Necesario para la integración Fase 4.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fuentes_documentos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo            TEXT NOT NULL,  -- 'sharepoint'|'sftp'|'local'|'api'
                nombre          TEXT NOT NULL,
                configuracion   TEXT,           -- JSON: site_url, library_path, credenciales_ref...
                activo          INTEGER DEFAULT 1,
                ultima_sync     TIMESTAMP,
                creado_en       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')


def _crear_sync_log():
    """
    Log de cada sincronización con fuentes externas.
    Permite auditar qué documentos llegaron, cuándo y con qué resultado.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_log (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                fuente_id               INTEGER REFERENCES fuentes_documentos(id),
                fecha_inicio            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_fin               TIMESTAMP,
                documentos_nuevos       INTEGER DEFAULT 0,
                documentos_duplicados   INTEGER DEFAULT 0,
                documentos_error        INTEGER DEFAULT 0,
                estado                  TEXT DEFAULT 'procesando',
                log_json                TEXT
            )
        ''')
