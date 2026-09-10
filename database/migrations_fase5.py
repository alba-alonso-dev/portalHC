"""
Migraciones Fase 5 — Afinado y Validación.

Cambios en tabla facturas:
  - ejercicio              : año del período de facturación (YYYY, índice de búsqueda)
  - carpeta_relativa       : ruta relativa dentro de la estructura organizada de uploads
  - inconsistencias_json   : lista de inconsistencias detectadas durante la extracción
  - cups                   : CUPS extraído (si no existía ya la columna)

Nueva tabla documentos_indice:
  Índice de documentos cargados por ejercicio/país/sede para facilitar
  la localización, detección de huecos y preparación para SharePoint.

Principios:
  - Idempotente — seguro ejecutar múltiples veces.
  - No elimina ni modifica columnas existentes.
"""

import logging
from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)

logger = logging.getLogger(__name__)


def ejecutar_migraciones_fase5():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("Fase 5: iniciando migraciones de afinado y validación...")
    _migrar_facturas_fase5()
    _crear_documentos_indice()
    _crear_indices_fase5()
    logger.info("Migraciones Fase 5 completadas")


def _migrar_facturas_fase5():
    """Añade columnas de Fase 5 a la tabla facturas (idempotente)."""
    nuevas_columnas = [
        "ALTER TABLE facturas ADD COLUMN ejercicio TEXT",
        "ALTER TABLE facturas ADD COLUMN carpeta_relativa TEXT",
        "ALTER TABLE facturas ADD COLUMN inconsistencias_json TEXT",
        "ALTER TABLE facturas ADD COLUMN cups TEXT",
    ]
    with get_db_connection() as conn:
        for sql in nuevas_columnas:
            try:
                conn.execute(sql)
                col = sql.split("ADD COLUMN")[1].strip().split()[0]
                logger.info(f"  ✓ facturas.{col}")
            except OperationalError as exc:
                if 'already exists' in str(exc).lower():
                    pass  # ya existe
                else:
                    raise

        # Poblar ejercicio en registros existentes (backfill)
        conn.execute("""
            UPDATE facturas
            SET ejercicio = substr(COALESCE(periodo_inicio, fecha_carga, fecha_factura), 1, 4)
            WHERE ejercicio IS NULL
              AND COALESCE(periodo_inicio, fecha_carga, fecha_factura) IS NOT NULL
        """)
    logger.info("  ✓ backfill facturas.ejercicio")


def _crear_documentos_indice():
    """
    Índice de documentos por ejercicio/país/sede.

    Permite:
      - Ver qué meses/facturas están cargadas por ejercicio.
      - Detectar huecos de cobertura.
      - Preparar migración a SharePoint (cada row = un documento a subir).

    estado:
      'disponible'  — documento accesible en disco local.
      'migrado'     — migrado a SharePoint (Fase 6+).
      'no_encontrado' — registro en BD pero archivo no localizado en disco.
    """
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documentos_indice (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                factura_id        INTEGER REFERENCES facturas(id) ON DELETE CASCADE,
                ejercicio         TEXT NOT NULL,
                pais              TEXT NOT NULL,
                sede              TEXT NOT NULL,
                sociedad          TEXT,
                mes               TEXT,
                archivo_nombre    TEXT NOT NULL,
                carpeta_relativa  TEXT,
                archivo_ruta      TEXT,
                sha256            TEXT,
                estado            TEXT NOT NULL DEFAULT 'disponible',
                fecha_indexado    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notas             TEXT
            )
        """)
    logger.info("  ✓ tabla documentos_indice")


def _crear_indices_fase5():
    """Índices de rendimiento para las nuevas columnas."""
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_facturas_ejercicio ON facturas(ejercicio)",
        "CREATE INDEX IF NOT EXISTS idx_documentos_indice_ejercicio ON documentos_indice(ejercicio, pais, sede)",
        "CREATE INDEX IF NOT EXISTS idx_documentos_indice_estado ON documentos_indice(estado)",
        "CREATE INDEX IF NOT EXISTS idx_facturas_cups ON facturas(cups)",
    ]
    with get_db_connection() as conn:
        for sql in indices:
            try:
                conn.execute(sql)
            except OperationalError:
                pass  # índice ya existe
    logger.info("  ✓ índices Fase 5")
