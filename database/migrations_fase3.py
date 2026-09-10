"""
Migraciones de base de datos — Fase 3: Recálculo, Estimaciones y Calidad de Datos.

Nuevas tablas:
  1. `lotes_recalculo`       — trabajos de recálculo masivo.
  2. `recalculos_historial`  — trazabilidad de cada recálculo individual.
  3. `estimaciones`          — consumos estimados para periodos sin factura real.
  4. `periodos_faltantes`    — detección y seguimiento de huecos de cobertura.

Nuevas columnas en `facturas`:
  - tipo_dato                TEXT DEFAULT 'real'   ('real' | 'estimado')
  - emisiones_recalculadas   REAL                  (último recálculo; nunca reemplaza al original)
  - factor_recalculado       REAL
  - factor_version_id_recalc INTEGER FK → factores_emision
  - fecha_ultimo_recalculo   TIMESTAMP

Principio de diseño:
  NINGÚN valor histórico original se sobreescribe. Todo cambio se registra en tablas
  de historial separadas, permitiendo auditoría completa para CSRD y huella de carbono.
"""

import logging
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ejecutar_migraciones_fase3():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("🗄️  Fase 3: iniciando migraciones de recálculo y estimaciones...")
    _migrar_facturas_fase3()
    _crear_lotes_recalculo()
    _crear_recalculos_historial()
    _crear_estimaciones()
    _crear_periodos_faltantes()
    logger.info("✅ Migraciones Fase 3 completadas")


# ── 1. Nuevas columnas en facturas ────────────────────────────────────────────

def _migrar_facturas_fase3():
    """
    Añade columnas de Fase 3 a la tabla facturas.
    El campo tipo_dato distingue registros reales de estimados.
    Los campos *_recalculado guardan el último recálculo sin tocar los originales.
    """
    nuevas = [
        ("tipo_dato",                "TEXT DEFAULT 'real'"),          # 'real' | 'estimado'
        ("emisiones_recalculadas",   "REAL"),
        ("factor_recalculado",       "REAL"),
        ("factor_version_id_recalc", "INTEGER"),
        ("fecha_ultimo_recalculo",   "TIMESTAMP"),
    ]
    with get_db_connection() as conn:
        existentes = {r[1] for r in conn.execute("PRAGMA table_info(facturas)")}
        for nombre, tipo in nuevas:
            if nombre not in existentes:
                conn.execute(f"ALTER TABLE facturas ADD COLUMN {nombre} {tipo}")
                logger.info(f"  + columna añadida: facturas.{nombre}")


# ── 2. Tabla lotes_recalculo ──────────────────────────────────────────────────

def _crear_lotes_recalculo():
    """
    Registra cada trabajo de recálculo masivo.
    alcance: 'individual' | 'sede' | 'pais' | 'anio' | 'completo'
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS lotes_recalculo (
                id                  TEXT PRIMARY KEY,
                alcance             TEXT NOT NULL,
                filtro_pais         TEXT,
                filtro_sede         TEXT,
                filtro_anio         TEXT,
                filtro_factura_id   INTEGER,
                total_facturas      INTEGER DEFAULT 0,
                procesadas_ok       INTEGER DEFAULT 0,
                procesadas_error    INTEGER DEFAULT 0,
                estado              TEXT DEFAULT 'pendiente',
                usuario             TEXT DEFAULT 'usuario',
                motivo              TEXT,
                fecha_inicio        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_fin           TIMESTAMP,
                resumen_json        TEXT DEFAULT '{}',
                notas               TEXT
            )
        ''')


# ── 3. Tabla recalculos_historial ─────────────────────────────────────────────

def _crear_recalculos_historial():
    """
    Cada fila representa un evento de recálculo sobre una factura concreta.
    Se preservan los valores originales y los nuevos, permitiendo:
      - Auditoría CSRD: "¿con qué factor se calculó y por qué cambió?"
      - Reconstrucción de series históricas.
      - Comparación de versiones de factores.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS recalculos_historial (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                factura_id                  INTEGER NOT NULL,
                lote_recalculo_id           TEXT,
                emisiones_originales        REAL,
                factor_original             REAL,
                factor_version_id_original  INTEGER,
                fuente_original             TEXT,
                emisiones_recalculadas      REAL,
                factor_nuevo                REAL,
                factor_version_id_nuevo     INTEGER,
                fuente_nueva                TEXT,
                diferencia_absoluta         REAL,
                diferencia_porcentual       REAL,
                usuario                     TEXT DEFAULT 'usuario',
                motivo                      TEXT,
                fecha_recalculo             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notas                       TEXT
            )
        ''')


# ── 4. Tabla estimaciones ─────────────────────────────────────────────────────

def _crear_estimaciones():
    """
    Almacena consumos y emisiones estimados para periodos sin factura real.

    Ciclo de vida de una estimación:
      vigente   → sustituida  (llega factura real → factura_real_id se rellena)
      vigente   → rechazada   (usuario decide no usarla)

    El campo desviacion_porcentual_real se calcula cuando llega la factura real,
    permitiendo medir la calidad de cada método de estimación.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS estimaciones (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                pais                        TEXT NOT NULL,
                sede                        TEXT NOT NULL,
                tipo_energia                TEXT NOT NULL DEFAULT 'electricidad',
                periodo_inicio              TEXT NOT NULL,
                periodo_fin                 TEXT NOT NULL,
                mes                         TEXT NOT NULL,
                consumo_kwh_estimado        REAL NOT NULL,
                consumo_mwh_estimado        REAL NOT NULL,
                emisiones_estimadas         REAL,
                factor_emision              REAL,
                factor_version_id           INTEGER,
                metodo_estimacion           TEXT NOT NULL,
                confianza                   REAL DEFAULT 0.5,
                referencia_facturas_json    TEXT DEFAULT '[]',
                valor_manual                REAL,
                estado                      TEXT DEFAULT 'vigente',
                factura_real_id             INTEGER,
                desviacion_porcentual_real  REAL,
                creado_por                  TEXT DEFAULT 'sistema',
                fecha_carga                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notas                       TEXT
            )
        ''')


# ── 5. Tabla periodos_faltantes ───────────────────────────────────────────────

def _crear_periodos_faltantes():
    """
    Catálogo de huecos de cobertura por sede.

    estado:
      'faltante'  → mes sin datos (ni real ni estimado)
      'estimado'  → cubierto por estimacion_id
      'cubierto'  → cubierto por factura real (factura_id)
      'excluido'  → marcado manualmente como no aplicable

    Esta tabla alimenta los indicadores de calidad de datos y el dashboard.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS periodos_faltantes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pais            TEXT NOT NULL,
                sede            TEXT NOT NULL,
                tipo_energia    TEXT NOT NULL DEFAULT 'electricidad',
                anio            TEXT NOT NULL,
                mes             TEXT NOT NULL,
                estado          TEXT DEFAULT 'faltante',
                factura_id      INTEGER,
                estimacion_id   INTEGER,
                deteccion_fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolucion_fecha TIMESTAMP,
                notas           TEXT,
                UNIQUE(pais, sede, tipo_energia, mes)
            )
        ''')
