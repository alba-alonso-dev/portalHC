"""
Migraciones Fase 4 — Dashboard ESG, Alertas Automáticas e Informe GHG.

Nuevas tablas:
  1. alertas                  — sistema de alertas automáticas y manuales.
  2. alertas_config            — configuración de reglas de alerta por tipo.

Nuevas columnas en estimaciones:
  - metodo_detalle_json       — detalle del método (datos usados, fuentes).
  - confianza_texto           — descripción legible del nivel de confianza.
  - error_absoluto            — |real - estimado| al sustituir por factura real.

Principios:
  - Idempotente — seguro ejecutar múltiples veces.
  - No elimina ni modifica columnas existentes.
"""

import logging
from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)

logger = logging.getLogger(__name__)


def ejecutar_migraciones_fase4():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("Fase 4: iniciando migraciones de dashboard y alertas...")
    _crear_alertas()
    _crear_alertas_config()
    _migrar_estimaciones_fase4()
    _crear_indices_fase4()
    logger.info("Migraciones Fase 4 completadas")


# ── 1. Tabla alertas ──────────────────────────────────────────────────────────

def _crear_alertas():
    """
    Registro centralizado de alertas automáticas y manuales.

    tipo:
      'cobertura'    — falta factura del mes anterior, periodos sin datos.
      'calidad'      — OCR bajo, consumo anómalo, duplicado potencial.
      'emisiones'    — factor no actualizado, recálculo pendiente.
      'documentacion'— documento no encontrado, sin trazabilidad.

    severidad:
      'critica'      — requiere acción inmediata.
      'media'        — revisar en los próximos días.
      'informativa'  — para conocimiento.

    estado:
      'pendiente'    — sin resolver.
      'resuelta'     — resuelta por usuario o sistema.
      'ignorada'     — usuario decide no actuar.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS alertas (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo              TEXT NOT NULL,
                subtipo           TEXT,
                severidad         TEXT NOT NULL DEFAULT 'media',
                titulo            TEXT NOT NULL,
                descripcion       TEXT,
                entidad           TEXT,
                entidad_id        INTEGER,
                pais              TEXT,
                sede              TEXT,
                mes               TEXT,
                estado            TEXT NOT NULL DEFAULT 'pendiente',
                fecha_creacion    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_resolucion  TIMESTAMP,
                resuelta_por      TEXT,
                notas_resolucion  TEXT,
                datos_json        TEXT,
                auto_generada     INTEGER DEFAULT 1
            )
        ''')
    logger.info("  ✓ tabla alertas")


# ── 2. Tabla alertas_config ───────────────────────────────────────────────────

def _crear_alertas_config():
    """
    Configuración de reglas de alertas.
    Permite activar/desactivar tipos de alerta y ajustar umbrales.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS alertas_config (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo          TEXT NOT NULL,
                subtipo       TEXT NOT NULL,
                activa        INTEGER DEFAULT 1,
                severidad     TEXT NOT NULL DEFAULT 'media',
                umbral_valor  REAL,
                descripcion   TEXT,
                UNIQUE(tipo, subtipo)
            )
        ''')
        # Poblar configuración por defecto (idempotente)
        defaults = [
            ('cobertura',     'factura_mes_anterior',    1, 'media',     None),
            ('calidad',       'ocr_bajo',                1, 'media',     0.60),
            ('calidad',       'consumo_anomalo',         1, 'critica',   200.0),
            ('calidad',       'duplicado_potencial',     1, 'critica',   None),
            ('emisiones',     'factor_no_actualizado',   1, 'informativa', None),
            ('emisiones',     'recalculo_pendiente',     1, 'media',     None),
            ('documentacion', 'documento_no_encontrado', 1, 'media',     None),
        ]
        conn.executemany('''
            INSERT OR IGNORE INTO alertas_config
                (tipo, subtipo, activa, severidad, umbral_valor)
            VALUES (?,?,?,?,?)
        ''', defaults)
    logger.info("  ✓ tabla alertas_config")


# ── 3. Nuevas columnas en estimaciones ────────────────────────────────────────

def _migrar_estimaciones_fase4():
    """
    Añade columnas para mejorar el seguimiento y calidad de las estimaciones.
    """
    nuevas = [
        ('metodo_detalle_json', 'TEXT'),
        ('confianza_texto',     'TEXT'),
        ('error_absoluto',      'REAL'),
        ('n_referencias',       'INTEGER DEFAULT 0'),
    ]
    with get_db_connection() as conn:
        for nombre, tipo in nuevas:
            try:
                conn.execute(f'ALTER TABLE estimaciones ADD COLUMN {nombre} {tipo}')
                logger.info(f'  + columna añadida: estimaciones.{nombre}')
            except OperationalError as exc:
                if 'already exists' not in str(exc).lower():
                    raise


# ── 4. Índices de rendimiento ─────────────────────────────────────────────────

def _crear_indices_fase4():
    indices = [
        'CREATE INDEX IF NOT EXISTS idx_alertas_estado '
        'ON alertas(estado, severidad, fecha_creacion)',
        'CREATE INDEX IF NOT EXISTS idx_alertas_tipo '
        'ON alertas(tipo, subtipo, estado)',
        'CREATE INDEX IF NOT EXISTS idx_alertas_pais_sede '
        'ON alertas(pais, sede, mes)',
        'CREATE INDEX IF NOT EXISTS idx_alertas_entidad '
        'ON alertas(entidad, entidad_id)',
    ]
    with get_db_connection() as conn:
        for sql in indices:
            conn.execute(sql)
    logger.info(f'  ✓ {len(indices)} índices fase 4 creados/verificados')
