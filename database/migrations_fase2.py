"""
Migraciones de base de datos — Fase 2: Gestión de Factores de Emisión.

Cambios introducidos:
  1. Nueva tabla `fuentes_emision`    — gestión de fuentes bibliográficas.
  2. Recreación de `factores_emision` — soporte de versionado inmutable.
  3. Nueva tabla `factores_historial` — trazabilidad completa de cambios.
  4. Columna `factor_version_id`       — FK en `facturas` → `factores_emision`.

Principio de diseño: NINGUNA operación elimina datos históricos.
La tabla original se renombra a `factores_emision_legacy` antes de ser reemplazada.
"""

import json
import logging
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ejecutar_migraciones_fase2():
    """Punto de entrada. Las funciones son idempotentes — se puede llamar múltiples veces."""
    logger.info("🗄️  Fase 2: iniciando migraciones de factores...")
    _crear_fuentes_emision()
    _poblar_fuentes_iniciales()
    _migrar_factores_emision_v2()
    _crear_factores_historial()
    _migrar_facturas_fase2()
    _poblar_historial_inicial()
    logger.info("✅ Migraciones Fase 2 completadas")


# ── 1. Tabla fuentes_emision ──────────────────────────────────────────────────

def _crear_fuentes_emision():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fuentes_emision (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo              TEXT UNIQUE NOT NULL,
                nombre              TEXT NOT NULL,
                organizacion        TEXT,
                anio_publicacion    TEXT,
                url                 TEXT,
                notas               TEXT,
                activo              INTEGER DEFAULT 1,
                fecha_carga         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modificado_en       TIMESTAMP
            )
        ''')


def _poblar_fuentes_iniciales():
    """Inserta las fuentes de los factores ya existentes (idempotente)."""
    fuentes_iniciales = [
        ('MITECO_2024', 'MITECO v32',      'Ministerio para la Transición Ecológica y el Reto Demográfico', '2024',
         'https://www.miteco.gob.es/', 'Factor de emisión de electricidad para España.'),
        ('SNIGEIAR_2024', 'SNIGEIAR',      'Sistema Nacional de Inventario de GEI Argentina', '2024',
         'https://www.minem.gob.ar/snigeiar', None),
        ('UPME_2024',  'UPME',             'Unidad de Planeación Minero Energética de Colombia', '2024',
         'https://www1.upme.gov.co/', None),
        ('ARCONEL_2024','ARCONEL',         'Agencia de Regulación y Control de Electricidad Ecuador', '2024',
         'https://www.regulacionelectrica.gob.ec/', None),
        ('CRE_2024',   'CRE',              'Comisión Reguladora de Energía de México', '2024',
         'https://datos.cre.gob.mx/', None),
        ('DEFRA_2024', 'DEFRA',            'UK Department for Environment, Food & Rural Affairs', '2024',
         'https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024', None),
        ('IPCC_AR6',   'IPCC AR6',         'Intergovernmental Panel on Climate Change — Sixth Assessment Report', '2021',
         'https://www.ipcc.ch/report/ar6/', 'Factores globales de referencia para cálculos GHG Protocol.'),
        ('EPA_2024',   'EPA eGRID 2024',   'United States Environmental Protection Agency', '2024',
         'https://www.epa.gov/egrid', None),
    ]
    with get_db_connection() as conn:
        for row in fuentes_iniciales:
            conn.execute('''
                INSERT OR IGNORE INTO fuentes_emision
                    (codigo, nombre, organizacion, anio_publicacion, url, notas)
                VALUES (?,?,?,?,?,?)
            ''', row)


# ── 2. Recrear factores_emision con versionado ───────────────────────────────

def _migrar_factores_emision_v2():
    """
    Recrea la tabla factores_emision con soporte de versionado inmutable.

    Estrategia SQLite (no soporta DROP CONSTRAINT):
      a) Verificar si ya migrada (columna 'version' existe) → saltar.
      b) Renombrar tabla actual a factores_emision_legacy.
      c) Crear nueva tabla con esquema v2.
      d) Migrar datos existentes como versión 1 (es_version_activa=1).
    """
    with get_db_connection() as conn:
        cols_actuales = {r[1] for r in conn.execute("PRAGMA table_info(factores_emision)")}
        if 'version' in cols_actuales:
            logger.info("  factores_emision ya está en versión v2 — omitiendo migración")
            return

        # Respaldar datos existentes
        filas_legacy = conn.execute("SELECT * FROM factores_emision").fetchall()
        filas_legacy = [dict(r) for r in filas_legacy]
        logger.info(f"  Respaldando {len(filas_legacy)} factores existentes...")

        # Renombrar tabla original
        conn.execute("ALTER TABLE factores_emision RENAME TO factores_emision_legacy")

        # Crear nueva tabla con esquema completo
        conn.execute('''
            CREATE TABLE factores_emision (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                pais                TEXT NOT NULL,
                tipo_energia        TEXT NOT NULL DEFAULT 'electricidad',
                anio                TEXT NOT NULL,
                version             INTEGER NOT NULL DEFAULT 1,
                factor_kg_co2_mwh   REAL NOT NULL,
                unidad              TEXT NOT NULL DEFAULT 'kg CO2eq/MWh',
                descripcion         TEXT,
                fuente_id           INTEGER REFERENCES fuentes_emision(id),
                fuente              TEXT,
                url                 TEXT,
                notas               TEXT,
                activo              INTEGER DEFAULT 1,
                es_version_activa   INTEGER DEFAULT 1,
                fecha_vigencia_desde TEXT,
                fecha_vigencia_hasta TEXT,
                creado_por          TEXT DEFAULT 'sistema',
                fecha_carga         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modificado_en       TIMESTAMP,
                UNIQUE(pais, tipo_energia, anio, version)
            )
        ''')

        # Resolver fuente_id para cada factor migrado
        fuentes_map = {}
        for row in conn.execute("SELECT id, nombre FROM fuentes_emision"):
            fuentes_map[row['nombre']] = row['id']

        # Migrar datos como versión 1
        for f in filas_legacy:
            fuente_id = fuentes_map.get(f.get('fuente'), None)
            conn.execute('''
                INSERT INTO factores_emision
                    (id, pais, tipo_energia, anio, version, factor_kg_co2_mwh,
                     fuente_id, fuente, url, activo, es_version_activa, fecha_carga)
                VALUES (?,?,?,?,1,?,?,?,?,?,1,?)
            ''', (
                f['id'], f['pais'], f['tipo_energia'], f['anio'],
                f['factor_kg_co2_mwh'], fuente_id,
                f.get('fuente'), f.get('url'),
                f.get('activo', 1), f.get('fecha_carga')
            ))

        logger.info(f"  ✅ {len(filas_legacy)} factores migrados a esquema v2")


# ── 3. Tabla factores_historial ───────────────────────────────────────────────

def _crear_factores_historial():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS factores_historial (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_id           INTEGER NOT NULL,
                accion              TEXT NOT NULL,
                campo               TEXT,
                valor_anterior      TEXT,
                valor_nuevo         TEXT,
                version_resultante  INTEGER,
                usuario             TEXT DEFAULT 'sistema',
                fecha_cambio        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notas               TEXT
            )
        ''')


def _poblar_historial_inicial():
    """Registra el evento 'importado' para todos los factores migrados sin historial."""
    with get_db_connection() as conn:
        factores_sin_historial = conn.execute(
            '''SELECT f.id, f.pais, f.anio, f.version
               FROM factores_emision f
               LEFT JOIN factores_historial h ON h.factor_id = f.id
               WHERE h.id IS NULL'''
        ).fetchall()

        for f in factores_sin_historial:
            conn.execute('''
                INSERT INTO factores_historial
                    (factor_id, accion, version_resultante, notas)
                VALUES (?, 'importado', ?, 'Migrado desde esquema Fase 1')
            ''', (f['id'], f['version']))

        if factores_sin_historial:
            logger.info(f"  📋 {len(factores_sin_historial)} eventos 'importado' creados en historial")


# ── 4. Columna factor_version_id en facturas ─────────────────────────────────

def _migrar_facturas_fase2():
    """
    Añade `factor_version_id` a la tabla facturas para trazabilidad completa.
    Permite la pregunta: "¿Con qué versión exacta del factor se calculó esta emisión?"
    """
    with get_db_connection() as conn:
        existentes = {r[1] for r in conn.execute("PRAGMA table_info(facturas)")}
        if 'factor_version_id' not in existentes:
            conn.execute(
                "ALTER TABLE facturas ADD COLUMN factor_version_id INTEGER REFERENCES factores_emision(id)"
            )
            logger.info("  + columna añadida: facturas.factor_version_id")

            # Retrocompatibilidad: vincular facturas existentes al factor más
            # reciente activo que coincida con pais + anio de la factura.
            conn.execute('''
                UPDATE facturas
                SET factor_version_id = (
                    SELECT fe.id
                    FROM factores_emision fe
                    WHERE fe.pais = facturas.pais
                      AND fe.tipo_energia = COALESCE(facturas.tipo_energia, 'electricidad')
                      AND fe.anio = COALESCE(
                              substr(facturas.periodo_inicio, 1, 4),
                              strftime('%Y', facturas.fecha_carga))
                      AND fe.es_version_activa = 1
                    LIMIT 1
                )
                WHERE factor_version_id IS NULL
            ''')
            logger.info("  ✅ facturas.factor_version_id rellenado por retrocompatibilidad")
