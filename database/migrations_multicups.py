"""
Migraciones multi-CUPS — sedes con varios puntos de suministro.

Contexto:
  Una sede puede tener varios CUPS (puntos de suministro) y recibir una factura
  por cada uno en el mismo mes. Esas facturas son complementarias: el consumo de
  la sede es su SUMA. El sistema asumía "una factura por sede y mes", con dos
  consecuencias sobre los datos ya cargados:

    1. Toda factura de un segundo CUPS quedaba marcada `duplicado_potencial=1`,
       con su alerta invitando a "revisar y anular si procede". Anularlas habría
       borrado consumo real del cómputo de emisiones.
    2. Todas las facturas de una sede colgaban del mismo `suministro_id`
       (se elegía con `LIMIT 1`), de modo que la tabla `suministros` no
       distinguía los puntos de suministro pese a tener la UNIQUE preparada.

Principios:
  - Idempotente — seguro ejecutar múltiples veces.
  - No borra facturas ni consumo: solo corrige banderas y vínculos.
"""

import logging
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ejecutar_migraciones_multicups():
    """Punto de entrada. Idempotente."""
    logger.info("Multi-CUPS: iniciando migraciones de puntos de suministro...")
    _limpiar_falsos_duplicados()
    _backfill_suministros_por_cups()
    _crear_indices_multicups()
    logger.info("Migraciones multi-CUPS completadas")


def _limpiar_falsos_duplicados():
    """
    Desmarca las facturas marcadas como duplicado que en realidad son de otro
    CUPS de la misma sede.

    Una factura sigue siendo duplicado potencial solo si existe OTRA factura
    viva con el mismo período y el mismo CUPS, o con el mismo SHA-256.
    """
    with get_db_connection() as conn:
        falsos = conn.execute(
            '''SELECT f.id, f.sede, f.cups, substr(f.periodo_inicio,1,7) AS mes
               FROM facturas f
               WHERE f.duplicado_potencial = 1
                 AND f.fecha_anulacion IS NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM facturas d
                     WHERE d.id <> f.id
                       AND d.fecha_anulacion IS NULL
                       AND d.pais = f.pais AND d.sede = f.sede
                       AND d.tipo_energia = f.tipo_energia
                       AND d.periodo_inicio = f.periodo_inicio
                       AND d.periodo_fin = f.periodo_fin
                       AND d.cups IS f.cups
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM facturas h
                     WHERE h.id <> f.id
                       AND h.fecha_anulacion IS NULL
                       AND h.sha256_documento IS NOT NULL
                       AND h.sha256_documento = f.sha256_documento
                 )'''
        ).fetchall()

        if not falsos:
            logger.info("  Sin falsos duplicados por CUPS que corregir")
            return

        ids = [r['id'] for r in falsos]
        marcas = ','.join('?' * len(ids))
        conn.execute(
            f"UPDATE facturas SET duplicado_potencial = 0 WHERE id IN ({marcas})",
            ids
        )

        # Cierra las alertas que invitaban a anular esas facturas legítimas.
        nota = ("Falso duplicado: factura de otro CUPS de la misma sede. "
                "Su consumo se suma, no se anula.")
        cerradas = conn.execute(
            f'''UPDATE alertas
                SET estado='resuelta',
                    fecha_resolucion=CURRENT_TIMESTAMP,
                    resuelta_por='sistema',
                    notas_resolucion=?
                WHERE tipo='calidad' AND subtipo='duplicado_potencial'
                  AND estado='pendiente'
                  AND entidad='factura' AND entidad_id IN ({marcas})''',
            [nota] + ids
        ).rowcount

        for r in falsos:
            logger.info(f"  Factura #{r['id']} ({r['sede']}, {r['mes']}, "
                        f"CUPS {r['cups']}): desmarcada como duplicado")
        logger.info(f"  {len(ids)} falso(s) duplicado(s) corregido(s), "
                    f"{cerradas} alerta(s) cerrada(s)")


def _backfill_suministros_por_cups():
    """
    Da de alta un suministro por cada CUPS conocido y revincula sus facturas.

    Solo actúa sobre sedes existentes en la tabla `sedes`; las facturas de sedes
    no catalogadas conservan `suministro_id = NULL`, como hasta ahora.
    """
    creados = revinculadas = 0
    with get_db_connection() as conn:
        combinaciones = conn.execute(
            '''SELECT DISTINCT f.pais, f.sede, f.tipo_energia, f.cups
               FROM facturas f
               WHERE f.cups IS NOT NULL AND f.cups <> ''
                 AND f.fecha_anulacion IS NULL'''
        ).fetchall()

        for c in combinaciones:
            sede_row = conn.execute(
                "SELECT id FROM sedes WHERE pais_codigo=? AND nombre=?",
                (c['pais'], c['sede'])
            ).fetchone()
            if not sede_row:
                continue
            sede_id = sede_row['id']

            row = conn.execute(
                '''SELECT id FROM suministros
                   WHERE sede_id=? AND tipo_energia=? AND referencia=?''',
                (sede_id, c['tipo_energia'], c['cups'])
            ).fetchone()

            if row:
                suministro_id = row['id']
            else:
                suministro_id = conn.execute(
                    '''INSERT INTO suministros (sede_id, tipo_energia, referencia, notas)
                       VALUES (?,?,?,?)''',
                    (sede_id, c['tipo_energia'], c['cups'],
                     'Alta automática (migración multi-CUPS)')
                ).lastrowid
                creados += 1

            revinculadas += conn.execute(
                '''UPDATE facturas SET suministro_id=?
                   WHERE pais=? AND sede=? AND tipo_energia=? AND cups=?
                     AND (suministro_id IS NULL OR suministro_id <> ?)''',
                (suministro_id, c['pais'], c['sede'], c['tipo_energia'],
                 c['cups'], suministro_id)
            ).rowcount

    if creados or revinculadas:
        logger.info(f"  {creados} suministro(s) creado(s) por CUPS, "
                    f"{revinculadas} factura(s) revinculada(s)")
    else:
        logger.info("  Suministros por CUPS ya actualizados")


def _crear_indices_multicups():
    """Índices para las consultas de agregación mensual y detección por CUPS."""
    with get_db_connection() as conn:
        conn.execute(
            '''CREATE INDEX IF NOT EXISTS idx_facturas_sede_mes
               ON facturas(pais, sede, tipo_energia, periodo_inicio)'''
        )
        conn.execute(
            '''CREATE INDEX IF NOT EXISTS idx_facturas_cups_periodo
               ON facturas(cups, periodo_inicio, periodo_fin)'''
        )
