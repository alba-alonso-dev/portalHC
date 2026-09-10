"""
Migraciones de sociedades — maestro de entidades legales.

Contexto:
  El campo `facturas.sociedad` hasta ahora era texto libre, sin catálogo. Eso
  impedía normalizar el caso de uso real: una sede puede tener varios CUPS
  (puntos de suministro), cada uno facturado a una sociedad distinta del grupo.

  Esta migración:
    1. Crea la tabla maestra `sociedades` (razón social, CIF/NIF, país, activa).
    2. Puebla el maestro a partir de los valores distintos ya presentes en
       `facturas.sociedad` y, si aplica, de `config.SOCIEDADES_CONOCIDAS`.
    3. Añade `sociedad_id` (FK → sociedades.id, nullable) a `suministros`,
       porque el titular del suministro/CUPS es la sociedad, no la sede.
    4. Hace backfill de `suministros.sociedad_id` cuando es posible inferirlo
       a partir de las facturas asociadas a ese suministro.

  Diseño:
    - Mantiene `facturas.sociedad` (texto) intacta: no rompe consultas, reportes
      ni auditoría existentes. La columna `sociedad_id` en `suministros` es la
      nueva vía relacional, recomendada para reporting futuro.
    - Es aditiva e idempotente.
    - No elimina ni reescribe datos.
"""

import logging
from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)
import config

logger = logging.getLogger(__name__)


def ejecutar_migraciones_sociedades():
    """Punto de entrada. Idempotente."""
    logger.info("Sociedades: iniciando migraciones...")
    _crear_tabla_sociedades()
    _deduplicar_sociedades()
    _asegurar_indice_unico_nombre_null()
    _poblar_sociedades()
    _anadir_socio_suministro()
    _backfill_suministros_sociedad()
    _inferir_pais_sociedades()
    _crear_indices_sociedades()
    logger.info("Migraciones de sociedades completadas")


def _crear_tabla_sociedades():
    """Tabla maestra de sociedades del grupo (entidades legales)."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sociedades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre          TEXT NOT NULL,
                cif             TEXT,
                pais_codigo     TEXT REFERENCES paises(codigo),
                activo          INTEGER DEFAULT 1,
                fecha_alta      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(nombre, cif)
            )
        ''')
    logger.info("  ✓ tabla sociedades")


def _deduplicar_sociedades():
    """
    Elimina sociedades duplicadas por nombre cuando cif es NULL.

    Motivo: SQLite trata los NULL como distintos en constraints UNIQUE, por lo
    que `UNIQUE(nombre, cif)` NO impide duplicados cuando cif es NULL. Esta
    función se ejecuta siempre para limpiar duplicados históricos y prevenir
    acumulación.

    Conserva el registro con menor id (el original) y repunta las FKs de
    suministros.sociedad_id al registro conservado.
    """
    with get_db_connection() as conn:
        # Buscar grupos de duplicados por nombre (con cif NULL o igual)
        duplicados = conn.execute(
            """
            SELECT nombre, COALESCE(cif, '') AS cif_norm, COUNT(*) AS n
            FROM sociedades
            GROUP BY nombre, COALESCE(cif, '')
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        if not duplicados:
            return

        total_eliminados = 0
        for dup in duplicados:
            nombre = dup['nombre']
            cif_norm = dup['cif_norm']  # '' si era NULL
            cif_where = "cif IS NULL" if cif_norm == '' else "cif = ?"

            # El bueno es el de menor id
            params = [nombre] + ([] if cif_norm == '' else [cif_norm])
            bueno = conn.execute(
                f"SELECT id FROM sociedades WHERE nombre = ? AND {cif_where} "
                f"ORDER BY id LIMIT 1",
                params
            ).fetchone()
            if not bueno:
                continue
            bueno_id = bueno['id']

            # Los malos: el resto
            malos_params = [bueno_id, nombre] + ([] if cif_norm == '' else [cif_norm])
            malos = conn.execute(
                f"SELECT id FROM sociedades WHERE id <> ? AND nombre = ? AND {cif_where}",
                malos_params
            ).fetchall()

            for malo in malos:
                # Repuntar FKs de suministros al bueno
                conn.execute(
                    "UPDATE suministros SET sociedad_id = ? WHERE sociedad_id = ?",
                    (bueno_id, malo['id'])
                )
                conn.execute("DELETE FROM sociedades WHERE id = ?", (malo['id'],))
                total_eliminados += 1

        if total_eliminados:
            logger.info(f"  ✓ {total_eliminados} sociedades duplicadas eliminadas")


def _asegurar_indice_unico_nombre_null():
    """
    Crea un índice UNIQUE parcial sobre `sociedades(nombre) WHERE cif IS NULL`.

    SQLite trata los NULL como distintos en constraints UNIQUE, por lo que la
    constraint `UNIQUE(nombre, cif)` de la tabla NO impide duplicados cuando
    cif es NULL. Este índice parcial sí lo garantiza.

    Se crea DESPUÉS de la deduplicación (para que no falle) y ANTES de poblar
    (para que INSERT OR IGNORE funcione correctamente sobre los NULL).
    """
    with get_db_connection() as conn:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sociedades_nombre_cif_null "
            "ON sociedades(nombre) WHERE cif IS NULL"
        )


def _poblar_sociedades():
    """
    Puebla el maestro desde dos orígenes:
      1. config.SOCIEDADES_CONOCIDAS (CIF → nombre), si existe y tiene entradas.
      2. Valores distintos de facturas.sociedad (texto libre ya cargado).

    Usa INSERT OR IGNORE para no duplicar. Los nombres se normalizan con trim().
    El CIF se deja NULL cuando solo conocemos el nombre (caso de facturas
    históricas).
    """
    # 1. Desde config (CIF conocido)
    conocidas = getattr(config, 'SOCIEDADES_CONOCIDAS', {}) or {}
    with get_db_connection() as conn:
        for cif, nombre in conocidas.items():
            if not nombre:
                continue
            conn.execute(
                'INSERT OR IGNORE INTO sociedades (nombre, cif) VALUES (?,?)',
                (nombre.strip(), cif.strip())
            )
        # 2. Desde facturas.sociedad (texto libre histórico)
        rows = conn.execute(
            "SELECT DISTINCT sociedad FROM facturas "
            "WHERE sociedad IS NOT NULL AND sociedad <> ''"
        ).fetchall()
        for row in rows:
            nombre = row['sociedad'].strip()
            if not nombre:
                continue
            conn.execute(
                'INSERT OR IGNORE INTO sociedades (nombre, cif) VALUES (?,?)',
                (nombre, None)
            )
    logger.info("  ✓ sociedades pobladas desde config + facturas históricas")


def _anadir_socio_suministro():
    """
    Añade columna `sociedad_id` a `suministros`.

    El titular del suministro (CUPS) es la sociedad a la que se factura, no la
    sede. Por eso la FK va aquí y no en `sedes`. Nullable para no romper
    suministros ya dados de alta sin sociedad conocida.
    """
    with get_db_connection() as conn:
        existentes = {row[1] for row in conn.execute("PRAGMA table_info(suministros)")}
        if 'sociedad_id' in existentes:
            logger.info("  suministros.sociedad_id ya existe — omitiendo")
            return
        conn.execute(
            'ALTER TABLE suministros ADD COLUMN sociedad_id INTEGER REFERENCES sociedades(id)'
        )
    logger.info("  + columna añadida: suministros.sociedad_id")


def _backfill_suministros_sociedad():
    """
    Intenta rellenar `suministros.sociedad_id` para los suministros que ya
    existen y que tengan facturas con un único valor de sociedad.

    Si un suministro tiene facturas con sociedades distintas (caso posible pero
    raro), no se asigna nada: queda para revisión manual desde el admin.
    """
    with get_db_connection() as conn:
        # Suministros sin sociedad_id
        suministros = conn.execute(
            "SELECT id, sede_id, tipo_energia, referencia "
            "FROM suministros WHERE sociedad_id IS NULL"
        ).fetchall()
        if not suministros:
            logger.info("  suministros.sociedad_id: nada que backfillar")
            return

        actualizados = 0
        pendientes = 0
        for s in suministros:
            # Buscar facturas de ese suministro con sociedad no vacía
            sociedades = conn.execute(
                '''SELECT DISTINCT f.sociedad
                   FROM facturas f
                   WHERE f.suministro_id = ?
                     AND f.sociedad IS NOT NULL AND f.sociedad <> '' ''',
                (s['id'],)
            ).fetchall()

            # Fallback: si no hay facturas vinculadas por suministro_id, intentar
            # por la combinación sede + tipo_energia + cups (referencia)
            if not sociedades and s['referencia']:
                sociedades = conn.execute(
                    '''SELECT DISTINCT f.sociedad
                       FROM facturas f
                       WHERE f.cups = ?
                         AND f.tipo_energia = ?
                         AND f.sociedad IS NOT NULL AND f.sociedad <> '' ''',
                    (s['referencia'], s['tipo_energia'])
                ).fetchall()

            if len(sociedades) == 0:
                continue  # sin info de sociedad — queda pendiente

            if len(sociedades) > 1:
                pendientes += 1
                logger.warning(
                    f"  suministro #{s['id']}: {len(sociedades)} sociedades "
                    f"distintas — requiere revisión manual"
                )
                continue

            nombre_sociedad = sociedades[0]['sociedad'].strip()
            soc_row = conn.execute(
                "SELECT id FROM sociedades WHERE nombre = ?", (nombre_sociedad,)
            ).fetchone()
            if not soc_row:
                # Debería existir por _poblar_sociedades, pero por seguridad
                conn.execute(
                    'INSERT OR IGNORE INTO sociedades (nombre, cif) VALUES (?,?)',
                    (nombre_sociedad, None)
                )
                soc_row = conn.execute(
                    "SELECT id FROM sociedades WHERE nombre = ?", (nombre_sociedad,)
                ).fetchone()
            if soc_row:
                conn.execute(
                    "UPDATE suministros SET sociedad_id = ? WHERE id = ?",
                    (soc_row['id'], s['id'])
                )
                actualizados += 1

        logger.info(f"  suministros.sociedad_id: {actualizados} asignado(s), "
                    f"{pendientes} pendiente(s) por revisión")


def _inferir_pais_sociedades():
    """
    Infiere el país de cada sociedad a partir del país de la sede de sus
    suministros. Solo rellena las sociedades con pais_codigo NULL.

    Lógica: si todos los suministros de una sociedad pertenecen a sedes de un
    mismo país, se asigna ese país. Si hay sedes de países distintos, se deja
    NULL para revisión manual (caso de una sociedad que opere en varios países).
    """
    with get_db_connection() as conn:
        # Verificar que sedes tiene la columna pais_codigo
        cols_sedes = {row[1] for row in conn.execute("PRAGMA table_info(sedes)")}
        if 'pais_codigo' not in cols_sedes:
            logger.warning("  sedes no tiene columna pais_codigo — no se infiere país")
            return

        sociedades_sin_pais = conn.execute(
            "SELECT id FROM sociedades WHERE pais_codigo IS NULL OR pais_codigo = ''"
        ).fetchall()
        if not sociedades_sin_pais:
            return

        actualizadas = 0
        pendientes = 0
        for soc in sociedades_sin_pais:
            paises = conn.execute(
                """
                SELECT DISTINCT se.pais_codigo
                FROM suministros su
                JOIN sedes se ON su.sede_id = se.id
                WHERE su.sociedad_id = ?
                  AND se.pais_codigo IS NOT NULL AND se.pais_codigo <> ''
                """,
                (soc['id'],)
            ).fetchall()

            if len(paises) == 1:
                conn.execute(
                    "UPDATE sociedades SET pais_codigo = ? WHERE id = ?",
                    (paises[0]['pais_codigo'], soc['id'])
                )
                actualizadas += 1
            elif len(paises) > 1:
                pendientes += 1
                logger.warning(
                    f"  sociedad #{soc['id']}: opera en {len(paises)} países "
                    f"distintos — pais_codigo requiere revisión manual"
                )

        if actualizadas or pendientes:
            logger.info(f"  pais_codigo: {actualizadas} inferido(s), "
                        f"{pendientes} pendiente(s) por revisión")


def _crear_indices_sociedades():
    """Índices para consultas por sociedad."""
    with get_db_connection() as conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sociedades_pais ON sociedades(pais_codigo)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sociedades_nombre ON sociedades(nombre)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_suministros_sociedad "
            "ON suministros(sociedad_id) WHERE sociedad_id IS NOT NULL"
        )
    logger.info("  ✓ índices de sociedades creados/verificados")
