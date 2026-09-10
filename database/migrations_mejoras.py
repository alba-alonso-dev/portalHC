"""
Migraciones de mejoras arquitectónicas — Pre-Fase 4.

Nuevas tablas:
  1. audit_log          — registro transversal de TODAS las acciones de usuario/sistema.
  2. facturas_historial — trazabilidad campo a campo de modificaciones manuales.
  3. suministros        — entidad raíz para puntos de suministro (gas, agua, residuos…).

Nuevas columnas en facturas:
  - sha256_documento     TEXT     — hash SHA-256 del PDF para detección de duplicados.
  - suministro_id        INTEGER  — FK a suministros(id); reemplaza pais+sede+tipo en futuro.
  - duplicado_potencial  INTEGER  — flag 0|1 de advertencia (no bloquea la carga).

Migración de datos (backfill idempotente):
  - Crea un suministro por cada combinación única (sede_id, tipo_energia) en facturas.
  - Rellena facturas.suministro_id por retrocompatibilidad.

Principios:
  - Todas las operaciones son idempotentes.
  - No se elimina ni modifica ninguna columna histórica.
  - Las columnas 'pais', 'sede', 'tipo_energia' en facturas se mantienen como LEGACY
    hasta que la migración a suministros sea completa.
"""

import logging
from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)

logger = logging.getLogger(__name__)


def ejecutar_migraciones_mejoras():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("Mejoras arquitectonicas: iniciando migraciones...")
    _crear_audit_log()
    _crear_facturas_historial()
    _crear_suministros()
    _actualizar_facturas_nuevas_cols()
    _backfill_suministros()
    _backfill_suministro_id()
    _crear_indices_mejoras()
    # v2 — columnas para CDC, GHG scope y multi-suministro
    _mejoras_v2()
    # v3 — fuente_documento_id FK, export_state, indices CDC/Databricks
    _mejoras_v3()
    logger.info("Migraciones de mejoras completadas")


# ── 1. audit_log ──────────────────────────────────────────────────────────────

def _crear_audit_log():
    """
    Log transversal de auditoría.

    accion   : constante definida en services/audit_service.py
    entidad  : nombre de la tabla afectada ('factura', 'factor', 'estimacion'…)
    entidad_id: PK del registro afectado (NULL para acciones sin entidad concreta)
    detalle_json: snapshot antes/después u otros datos de contexto
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario       TEXT NOT NULL DEFAULT 'sistema',
                accion        TEXT NOT NULL,
                entidad       TEXT,
                entidad_id    INTEGER,
                detalle_json  TEXT,
                ip_origen     TEXT,
                sesion_id     TEXT
            )
        ''')
    logger.info("  ✓ tabla audit_log")


# ── 2. facturas_historial ─────────────────────────────────────────────────────

def _crear_facturas_historial():
    """
    Trazabilidad campo a campo de modificaciones manuales en facturas.

    Registra antes/después de cada campo modificado mediante confirmar_factura
    u otras operaciones que alteren datos de una factura ya procesada.
    Necesario para auditorías CSRD: "¿quién cambió qué y cuándo?"
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS facturas_historial (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                factura_id     INTEGER NOT NULL REFERENCES facturas(id),
                campo          TEXT NOT NULL,
                valor_anterior TEXT,
                valor_nuevo    TEXT,
                usuario        TEXT NOT NULL DEFAULT 'usuario',
                fecha_cambio   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                motivo         TEXT
            )
        ''')
    logger.info("  ✓ tabla facturas_historial")


# ── 3. suministros ────────────────────────────────────────────────────────────

def _crear_suministros():
    """
    Entidad raíz para puntos de suministro.

    Un suministro representa un contador/punto de consumo físico:
      sede_id      → FK a sedes (qué edificio)
      tipo_energia → qué suministro (electricidad, gas, agua…)
      referencia   → CUPS, NIF contador, matrícula…(NULL si no aplica)

    Diseño Fase 4+:
      - Cuando una sede tenga múltiples CUPS de electricidad, cada uno será
        un suministro diferente con referencia=CUPS.
      - En el modelo actual (Fases 1-3), existe exactamente un suministro
        por (sede, tipo_energia) hasta que los CUPS se capturen sistemáticamente.

    Las columnas legacy 'pais', 'sede', 'tipo_energia' en facturas se
    mantienen hasta completar la migración al modelo suministro_id.
    """
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS suministros (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sede_id       INTEGER NOT NULL REFERENCES sedes(id),
                tipo_energia  TEXT NOT NULL DEFAULT 'electricidad',
                referencia    TEXT,
                notas         TEXT,
                activo        INTEGER DEFAULT 1,
                fecha_alta    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sede_id, tipo_energia, referencia)
            )
        ''')
    logger.info("  ✓ tabla suministros")


# ── 4. Nuevas columnas en facturas ────────────────────────────────────────────

def _actualizar_facturas_nuevas_cols():
    """
    sha256_documento    — hash SHA-256 del PDF para detección de duplicados exactos.
    suministro_id       — FK a suministros; reemplazará pais+sede+tipo_energia a futuro.
    duplicado_potencial — 0|1; avisa al usuario sin bloquear la carga.

    Usa _alter_safe() para ser resiliente a ejecuciones concurrentes (T4):
    captura OperationalError("duplicate column name") en lugar de
    depender solo del PRAGMA pre-check, que no es atómico en multi-proceso.
    """

    nuevas = [
        ('sha256_documento',    'TEXT'),
        ('suministro_id',       'INTEGER REFERENCES suministros(id)'),
        ('duplicado_potencial', 'INTEGER DEFAULT 0'),
    ]
    with get_db_connection() as conn:
        for nombre, tipo in nuevas:
            try:
                conn.execute(f'ALTER TABLE facturas ADD COLUMN {nombre} {tipo}')
                logger.info(f'  + columna añadida: facturas.{nombre}')
            except OperationalError as exc:
                if 'already exists' not in str(exc).lower():
                    raise
                logger.info(f'  + columna añadida: facturas.{nombre}')


# ── 5. Backfill tabla suministros ─────────────────────────────────────────────

def _backfill_suministros():
    """
    Crea un suministro por cada combinación única (sede_id, tipo_energia)
    que exista en facturas. Idempotente: salta si ya hay registros.

    Ignora facturas cuya sede no esté en la tabla sedes (migraciones_refactor
    debe haberse ejecutado previamente para que esto funcione correctamente).
    """
    with get_db_connection() as conn:
        # Verificar que sedes existe (creada en migrations_refactor)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if 'sedes' not in tablas:
            logger.warning("  ⚠️ tabla 'sedes' no encontrada — backfill suministros omitido")
            return

        n_existentes = conn.execute("SELECT COUNT(*) FROM suministros").fetchone()[0]
        if n_existentes > 0:
            logger.info(f"  suministros: {n_existentes} existentes — backfill omitido")
            return

        conn.execute('''
            INSERT OR IGNORE INTO suministros (sede_id, tipo_energia)
            SELECT DISTINCT s.id, COALESCE(f.tipo_energia, 'electricidad')
            FROM facturas f
            JOIN sedes s ON s.pais_codigo = f.pais AND s.nombre = f.sede
            WHERE f.pais IS NOT NULL AND f.sede IS NOT NULL
        ''')
        insertados = conn.execute("SELECT COUNT(*) FROM suministros").fetchone()[0]
        logger.info(f"  ✓ {insertados} suministros creados por backfill")


# ── 6. Backfill facturas.suministro_id ────────────────────────────────────────

def _backfill_suministro_id():
    """
    Rellena facturas.suministro_id para registros previos sin este campo.
    Matching por (pais, sede, tipo_energia).
    """
    with get_db_connection() as conn:
        pendientes = conn.execute(
            "SELECT COUNT(*) FROM facturas WHERE suministro_id IS NULL"
        ).fetchone()[0]

        if pendientes == 0:
            logger.info("  suministro_id: ya relleno en todos los registros")
            return

        conn.execute('''
            UPDATE facturas
            SET suministro_id = (
                SELECT su.id
                FROM suministros su
                JOIN sedes s ON s.id = su.sede_id
                WHERE s.pais_codigo = facturas.pais
                  AND s.nombre      = facturas.sede
                  AND su.tipo_energia = COALESCE(facturas.tipo_energia, 'electricidad')
                LIMIT 1
            )
            WHERE suministro_id IS NULL
        ''')
        actualizadas = conn.execute(
            "SELECT COUNT(*) FROM facturas WHERE suministro_id IS NOT NULL"
        ).fetchone()[0]
        logger.info(f"  ✓ facturas.suministro_id: {actualizadas} registros enlazados")


# ── 7. Índices de rendimiento ─────────────────────────────────────────────────

def _crear_indices_mejoras():
    indices = [
        # audit_log — consultas frecuentes por acción, por entidad y por usuario
        ('idx_audit_accion_ts',
         'CREATE INDEX IF NOT EXISTS idx_audit_accion_ts '
         'ON audit_log(accion, timestamp)'),
        ('idx_audit_entidad',
         'CREATE INDEX IF NOT EXISTS idx_audit_entidad '
         'ON audit_log(entidad, entidad_id)'),
        ('idx_audit_usuario',
         'CREATE INDEX IF NOT EXISTS idx_audit_usuario '
         'ON audit_log(usuario, timestamp)'),
        # facturas_historial — por factura, para mostrar el historial de cambios
        ('idx_fhist_factura',
         'CREATE INDEX IF NOT EXISTS idx_fhist_factura '
         'ON facturas_historial(factura_id, fecha_cambio)'),
        # facturas — sha256 único (índice parcial: solo filas con sha256 != NULL)
        ('idx_facturas_sha256',
         'CREATE UNIQUE INDEX IF NOT EXISTS idx_facturas_sha256 '
         'ON facturas(sha256_documento) WHERE sha256_documento IS NOT NULL'),
        # facturas — por suministro para futura consulta por punto de suministro
        ('idx_facturas_suministro',
         'CREATE INDEX IF NOT EXISTS idx_facturas_suministro '
         'ON facturas(suministro_id, periodo_inicio)'),
        # suministros — lookup por sede
        ('idx_suministros_sede',
         'CREATE INDEX IF NOT EXISTS idx_suministros_sede '
         'ON suministros(sede_id, tipo_energia)'),
    ]
    with get_db_connection() as conn:
        for _, sql in indices:
            conn.execute(sql)
    logger.info(f'  ✓ {len(indices)} índices de mejoras creados/verificados')


# ── v2: CDC, GHG scope y consumo genérico ────────────────────────────────────

def _mejoras_v2():
    """
    Segunda ronda de mejoras arquitectónicas. Idempotente.

    1. updated_at en facturas, sedes y suministros
       - Necesario para Change Data Capture (Databricks / Data Lake).
       - Trigger AFTER UPDATE para mantenimiento automático.
       - factores_emision ya tiene 'modificado_en' — se añade su trigger.

    2. scope_ghg en factores_emision
       - GHG Protocol: 1=Scope1 (directo), 2=Scope2 (electricidad), 3=Scope3.
       - Valor por defecto 2 (electricidad comprada = Scope 2).
       - Requerido para reportes CSRD / ESG.

    3. consumo_valor + consumo_unidad en facturas
       - Abstracción de consumo independiente del tipo de suministro.
       - consumo_kwh/consumo_mwh permanecen como legacy para electricidad.
       - Gas → m3 / MWh; Agua → m3; Residuos → t; Viajes → km.
       - Backfill: consumo_valor=consumo_kwh, consumo_unidad='kWh'.
    """
    with get_db_connection() as conn:
        existentes_facturas    = {r[1] for r in conn.execute('PRAGMA table_info(facturas)')}
        existentes_sedes       = {r[1] for r in conn.execute('PRAGMA table_info(sedes)')}
        existentes_suministros = {r[1] for r in conn.execute('PRAGMA table_info(suministros)')}
        existentes_factores    = {r[1] for r in conn.execute('PRAGMA table_info(factores_emision)')}

        # ── 1a. updated_at en facturas ──────────────────────────────────────
        if 'updated_at' not in existentes_facturas:
            conn.execute("ALTER TABLE facturas ADD COLUMN updated_at TIMESTAMP")
            conn.execute(
                "UPDATE facturas SET updated_at = COALESCE(fecha_carga, CURRENT_TIMESTAMP)"
            )
            logger.info('  + facturas.updated_at (CDC)')

        # ── 1b. updated_at en sedes ─────────────────────────────────────────
        if 'updated_at' not in existentes_sedes:
            conn.execute("ALTER TABLE sedes ADD COLUMN updated_at TIMESTAMP")
            conn.execute("UPDATE sedes SET updated_at = CURRENT_TIMESTAMP")
            logger.info('  + sedes.updated_at (CDC)')

        # ── 1c. updated_at en suministros ───────────────────────────────────
        if 'updated_at' not in existentes_suministros:
            conn.execute("ALTER TABLE suministros ADD COLUMN updated_at TIMESTAMP")
            conn.execute(
                "UPDATE suministros SET updated_at = COALESCE(fecha_alta, CURRENT_TIMESTAMP)"
            )
            logger.info('  + suministros.updated_at (CDC)')

        # ── 1d. Triggers para mantener updated_at ───────────────────────────
        # En SQLite eran triggers AFTER UPDATE que relanzaban un UPDATE sobre
        # la propia tabla (posible porque recursive_triggers está desactivado).
        # PostgreSQL necesita una función de trigger; se usa BEFORE UPDATE, que
        # además es más eficiente: modifica la fila en vuelo en lugar de
        # provocar una segunda escritura.
        conn.execute('''
            CREATE OR REPLACE FUNCTION set_updated_at()
            RETURNS trigger
            LANGUAGE plpgsql AS $trg$
            BEGIN
                NEW.updated_at := to_char(now() AT TIME ZONE 'UTC',
                                          'YYYY-MM-DD HH24:MI:SS');
                RETURN NEW;
            END;
            $trg$
        ''')
        conn.execute('''
            CREATE OR REPLACE FUNCTION set_modificado_en()
            RETURNS trigger
            LANGUAGE plpgsql AS $trg$
            BEGIN
                NEW.modificado_en := to_char(now() AT TIME ZONE 'UTC',
                                             'YYYY-MM-DD HH24:MI:SS');
                RETURN NEW;
            END;
            $trg$
        ''')

        triggers = [
            ('trg_facturas_updated_at',     'facturas',         'set_updated_at'),
            ('trg_sedes_updated_at',        'sedes',            'set_updated_at'),
            ('trg_suministros_updated_at',  'suministros',      'set_updated_at'),
            ('trg_factores_modificado_en',  'factores_emision', 'set_modificado_en'),
        ]
        for nombre, tabla, funcion in triggers:
            # DROP + CREATE en lugar de IF NOT EXISTS: PostgreSQL no admite esa
            # cláusula en CREATE TRIGGER, y así la definición queda actualizada.
            conn.execute(f'DROP TRIGGER IF EXISTS {nombre} ON {tabla}')
            conn.execute(
                f'CREATE TRIGGER {nombre} BEFORE UPDATE ON {tabla} '
                f'FOR EACH ROW EXECUTE FUNCTION {funcion}()'
            )
        logger.info(f'  + {len(triggers)} triggers updated_at/modificado_en')

        # ── 2. scope_ghg en factores_emision ───────────────────────────────
        if 'scope_ghg' not in existentes_factores:
            conn.execute(
                "ALTER TABLE factores_emision ADD COLUMN scope_ghg INTEGER DEFAULT 2"
            )
            # Electricidad comprada → siempre Scope 2
            conn.execute(
                "UPDATE factores_emision SET scope_ghg = 2"
                " WHERE tipo_energia = 'electricidad' OR scope_ghg IS NULL"
            )
            logger.info('  + factores_emision.scope_ghg (GHG Protocol, default=2)')

        # ── 3. consumo_valor + consumo_unidad en facturas ───────────────────
        if 'consumo_valor' not in existentes_facturas:
            conn.execute(
                "ALTER TABLE facturas ADD COLUMN consumo_valor REAL"
            )
            conn.execute(
                "UPDATE facturas SET consumo_valor = consumo_kwh"
                " WHERE consumo_valor IS NULL AND consumo_kwh IS NOT NULL"
            )
            logger.info('  + facturas.consumo_valor (genérico multi-suministro)')

        if 'consumo_unidad' not in existentes_facturas:
            conn.execute(
                "ALTER TABLE facturas ADD COLUMN consumo_unidad TEXT DEFAULT 'kWh'"
            )
            conn.execute(
                "UPDATE facturas SET consumo_unidad = 'kWh'"
                " WHERE consumo_unidad IS NULL AND tipo_energia = 'electricidad'"
            )
            logger.info('  + facturas.consumo_unidad (kWh/m3/t/km segun suministro)')

    logger.info('  v2 completadas (CDC + GHG scope + consumo generico)')


# ── v3: fuente_documento_id FK, export_state, índices CDC/Databricks ─────────

def _mejoras_v3():
    """
    Tercera ronda de mejoras arquitectónicas. Idempotente.

    1. fuentes_documentos — registro de entrada 'local' por defecto.
       Necesario para el backfill de facturas.fuente_documento_id.

    2. facturas.fuente_documento_id — FK a fuentes_documentos.
       Normaliza el origen documental: una factura sabe desde qué fuente llegó.
       Coexiste con external_source (legacy) hasta migración completa.
       Backfill automático para facturas con external_source='local'.

    3. facturas.export_state — estado de exportación para Databricks CDC.
       'pending' → pendiente de exportar.
       'exported' → ya exportado al Data Lake.
       'error' → falló la exportación (requiere reintento).
       Permite incremental loads sin necesidad de comparar updated_at.

    4. Índices para CDC / Databricks:
       - idx_facturas_updated_at : para queries "dame todo lo modificado desde X".
       - idx_facturas_export_state: para queries "dame todo lo pendiente de exportar".
       - idx_fuentes_documentos_tipo: para joins rápidos por tipo de fuente.
    """

    with get_db_connection() as conn:
        existentes = {r[1] for r in conn.execute('PRAGMA table_info(facturas)')}

        # ── 1. Asegurar entrada 'local' en fuentes_documentos ───────────────
        conn.execute(
            '''INSERT OR IGNORE INTO fuentes_documentos
               (id, tipo, nombre, activo)
               VALUES (1, 'local', 'Almacenamiento local (uploads/)', 1)'''
        )
        logger.info('  fuentes_documentos: entrada local id=1 asegurada')

        # ── 2. fuente_documento_id en facturas ──────────────────────────────
        if 'fuente_documento_id' not in existentes:
            try:
                conn.execute(
                    'ALTER TABLE facturas ADD COLUMN '
                    'fuente_documento_id INTEGER REFERENCES fuentes_documentos(id)'
                )
                logger.info('  + facturas.fuente_documento_id FK -> fuentes_documentos')
            except OperationalError as exc:
                if 'already exists' not in str(exc).lower():
                    raise

        # Backfill: facturas con external_source='local' → fuente_documento_id=1
        n_backfill = conn.execute(
            '''UPDATE facturas SET fuente_documento_id = 1
               WHERE (external_source = 'local' OR external_source IS NULL)
                 AND fuente_documento_id IS NULL'''
        ).rowcount
        if n_backfill:
            logger.info(f'  backfill fuente_documento_id: {n_backfill} facturas -> id=1')

        # ── 3. export_state en facturas ─────────────────────────────────────
        if 'export_state' not in existentes:
            try:
                conn.execute(
                    "ALTER TABLE facturas ADD COLUMN export_state TEXT"
                )
                conn.execute(
                    "UPDATE facturas SET export_state = 'pending' "
                    "WHERE export_state IS NULL"
                )
                logger.info('  + facturas.export_state (CDC Databricks)')
            except OperationalError as exc:
                if 'already exists' not in str(exc).lower():
                    raise

    # ── 4. Índices CDC/Databricks ────────────────────────────────────────────
    indices_v3 = [
        ('idx_facturas_updated_at',
         'CREATE INDEX IF NOT EXISTS idx_facturas_updated_at '
         'ON facturas(updated_at)'),
        ('idx_facturas_export_state',
         'CREATE INDEX IF NOT EXISTS idx_facturas_export_state '
         'ON facturas(export_state) WHERE export_state IS NOT NULL'),
        ('idx_facturas_fuente_doc',
         'CREATE INDEX IF NOT EXISTS idx_facturas_fuente_doc '
         'ON facturas(fuente_documento_id)'),
        ('idx_fuentes_documentos_tipo',
         'CREATE INDEX IF NOT EXISTS idx_fuentes_documentos_tipo '
         'ON fuentes_documentos(tipo, activo)'),
    ]
    with get_db_connection() as conn:
        for _, sql in indices_v3:
            conn.execute(sql)

    logger.info(f'  v3 completadas (fuente_documento_id + export_state + {len(indices_v3)} indices CDC)')
