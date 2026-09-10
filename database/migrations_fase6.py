"""
Migraciones Fase 6 — Gestión ESG y Toma de Decisiones.

Nuevas tablas:
  - objetivos_emision     : targets de reducción por sociedad/sede/país y año
  - metodo_estimacion_metricas : métricas acumuladas de precisión por método (para reconciliación)

Nuevas columnas en estimaciones:
  - error_absoluto_kwh    : diferencia |real - estimado| cuando se sustituye
  - error_relativo_pct    : error porcentual relativo cuando se sustituye
  - sustituida_en         : timestamp de cuando llegó la factura real

Principios:
  - Idempotente — seguro ejecutar múltiples veces.
  - No elimina ni modifica columnas existentes.
"""

import logging
from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)

logger = logging.getLogger(__name__)


def ejecutar_migraciones_fase6():
    """Punto de entrada. Idempotente."""
    logger.info("Fase 6: iniciando migraciones de gestión ESG...")
    _crear_objetivos_emision()
    _crear_metodo_estimacion_metricas()
    _migrar_estimaciones_fase6()
    _crear_indices_fase6()
    _corregir_indice_sha256()
    _corregir_factores_unidad()
    _recalcular_emisiones_facturas()
    logger.info("Migraciones Fase 6 completadas")


def _crear_objetivos_emision():
    """
    Tabla de objetivos de reducción de emisiones.

    Ámbito:
      - Si se rellenan sociedad + sede → objetivo de sede específica
      - Si solo sociedad              → objetivo de sociedad
      - Si solo pais                  → objetivo de país
      - Si todo es NULL               → objetivo global corporativo

    Los campos son inclusivos: se puede definir objetivo a cualquier granularidad.
    """
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS objetivos_emision (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                anio                 INTEGER NOT NULL,
                pais                 TEXT,
                sociedad             TEXT,
                sede                 TEXT,
                tipo_energia         TEXT DEFAULT 'electricidad',

                -- Target absoluto
                emisiones_objetivo_tco2e  REAL,

                -- Target relativo (% reducción respecto al año base)
                pct_reduccion_objetivo    REAL,
                anio_base                 INTEGER,
                emisiones_anio_base_tco2e REAL,

                -- Metadatos
                observaciones        TEXT,
                creado_en            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modificado_en        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activo               INTEGER NOT NULL DEFAULT 1,

                -- Restricción: no duplicar objetivo para el mismo ámbito+año
                UNIQUE(anio, pais, sociedad, sede, tipo_energia)
            )
        """)
    logger.info("  ✓ tabla objetivos_emision")


def _crear_metodo_estimacion_metricas():
    """
    Métricas acumuladas de precisión por método de estimación.
    Se actualiza automáticamente cuando llega una factura real que sustituye
    una estimación (reconciliación automática Fase 6).
    """
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metodo_estimacion_metricas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                metodo          TEXT NOT NULL UNIQUE,
                n_sustituciones INTEGER NOT NULL DEFAULT 0,
                suma_error_abs  REAL    NOT NULL DEFAULT 0,
                suma_error_rel  REAL    NOT NULL DEFAULT 0,
                max_error_abs   REAL,
                max_error_rel   REAL,
                ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Inicializar filas para todos los métodos conocidos
        metodos = [
            'media_historica', 'mismo_mes_anio_anterior', 'adyacente',
            'manual', 'sede_similar', 'ponderado', 'por_dias', 'estacional',
        ]
        for m in metodos:
            conn.execute(
                "INSERT OR IGNORE INTO metodo_estimacion_metricas (metodo) VALUES (?)",
                (m,)
            )
    logger.info("  ✓ tabla metodo_estimacion_metricas")


def _migrar_estimaciones_fase6():
    """Añade columnas de reconciliación a la tabla estimaciones."""
    nuevas = [
        "ALTER TABLE estimaciones ADD COLUMN error_absoluto_kwh REAL",
        "ALTER TABLE estimaciones ADD COLUMN error_relativo_pct REAL",
        "ALTER TABLE estimaciones ADD COLUMN sustituida_en      TIMESTAMP",
    ]
    with get_db_connection() as conn:
        for sql in nuevas:
            try:
                conn.execute(sql)
                col = sql.split("ADD COLUMN")[1].strip().split()[0]
                logger.info(f"  + columna añadida: estimaciones.{col}")
            except OperationalError as exc:
                if 'already exists' in str(exc).lower():
                    pass
                else:
                    raise


def _crear_indices_fase6():
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_objetivos_anio        ON objetivos_emision(anio)",
        "CREATE INDEX IF NOT EXISTS idx_objetivos_pais_sede   ON objetivos_emision(pais, sede)",
        "CREATE INDEX IF NOT EXISTS idx_objetivos_sociedad    ON objetivos_emision(sociedad)",
        "CREATE INDEX IF NOT EXISTS idx_estimaciones_sustit   ON estimaciones(estado, pais, sede)",
    ]
    with get_db_connection() as conn:
        for sql in indices:
            try:
                conn.execute(sql)
            except OperationalError:
                pass
    logger.info("  ✓ índices Fase 6")


def _corregir_indice_sha256():
    """
    Reemplaza el UNIQUE INDEX en sha256_documento por un índice normal.

    El índice UNIQUE bloquea el INSERT cuando llega una factura duplicada, en vez
    de permitir que la capa de aplicación la marque con duplicado_potencial=1.
    La detección de duplicados ya está implementada en lote_service._verificar_duplicados()
    y añade la advertencia correspondiente antes del INSERT.
    """
    with get_db_connection() as conn:
        try:
            conn.execute("DROP INDEX IF EXISTS idx_facturas_sha256")
        except Exception:
            pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facturas_sha256 "
                "ON facturas(sha256_documento) WHERE sha256_documento IS NOT NULL"
            )
        except Exception:
            pass
    logger.info("  ✓ idx_facturas_sha256: UNIQUE INDEX → índice normal")


def _corregir_factores_unidad():
    """
    Corrige factores de emisión almacenados en tCO₂/MWh en lugar de kgCO₂/MWh.

    La columna se llama factor_kg_co2_mwh y la fórmula espera kgCO₂/MWh:
        tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000

    Los factores cargados para ES/AR/CO/EC/MX eran valores MITECO/oficiales en
    tCO₂/MWh (p.ej. ES=0.187 t/MWh). Deben ser 187 kg/MWh.

    Regla segura: ningún factor real en kgCO₂/MWh es < 1.0 (el mínimo mundial
    ronda los 10-20 kg/MWh para redes casi 100% renovables).
    Francia ya tiene 57.8 kg/MWh → correcto, no se modifica.
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, pais, anio, factor_kg_co2_mwh "
            "FROM factores_emision WHERE factor_kg_co2_mwh < 1.0"
        ).fetchall()
        n = 0
        for r in rows:
            nuevo = round(r['factor_kg_co2_mwh'] * 1000, 4)
            conn.execute(
                "UPDATE factores_emision SET factor_kg_co2_mwh=? WHERE id=?",
                (nuevo, r['id'])
            )
            logger.info(
                f"    Factor {r['pais']}/{r['anio']}: "
                f"{r['factor_kg_co2_mwh']} t/MWh → {nuevo} kg/MWh"
            )
            n += 1
    logger.info(f"  ✓ {n} factores corregidos a kgCO₂/MWh")


def _recalcular_emisiones_facturas():
    """
    Recalcula emisiones_tco2e para todas las facturas usando el factor corregido.

    Utiliza factor_version_id (FK a factores_emision) que ya está registrado en
    cada factura para obtener exactamente el factor que se usó (ahora en kg/MWh).
    Sólo actualiza facturas con consumo_mwh y factor_version_id conocidos.
    """
    with get_db_connection() as conn:
        n = conn.execute(
            """
            UPDATE facturas
            SET emisiones_tco2e = ROUND(
                (SELECT fe.factor_kg_co2_mwh
                 FROM factores_emision fe
                 WHERE fe.id = facturas.factor_version_id)
                * facturas.consumo_mwh / 1000.0,
                4)
            WHERE consumo_mwh IS NOT NULL
              AND consumo_mwh > 0
              AND factor_version_id IS NOT NULL
              AND fecha_anulacion IS NULL
            """
        ).rowcount
    logger.info(f"  ✓ {n} facturas con emisiones_tco2e recalculadas")
