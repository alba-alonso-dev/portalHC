"""
Migración de integridad referencial.

Corrige y previene las filas huérfanas —filas hijas que apuntan a un padre que
ya no existe— que dejaban los borrados masivos de datos.

Origen del problema
-------------------
El endpoint ``POST /api/dev/reset-datos`` vaciaba las tablas transaccionales
con ``PRAGMA foreign_keys = OFF`` y una lista fija de tablas que **no incluía
documentos_indice**. Al borrar ``facturas`` con las claves foráneas desactivadas
SQLite no ejecutaba el ``ON DELETE CASCADE`` de ``documentos_indice`` ni se
quejaba de las referencias rotas, así que el índice documental sobrevivía
apuntando a facturas inexistentes.

Este módulo actúa en dos capas:

1. **Corrección**: borra las filas huérfanas que ya están en la base de datos.
2. **Prevención**: añade ``ON DELETE CASCADE`` a ``facturas_historial.factura_id``
   para que la propia base de datos garantice la limpieza al borrar una factura,
   en lugar de depender de que el código recuerde vaciar la tabla.

La causa raíz se corrigió además en ``routes/configuracion.py``, que ya no
desactiva las claves foráneas al resetear los datos.

Es idempotente: en una base de datos ya limpia no hace nada.
"""

import logging

from database.connection import get_db_connection

logger = logging.getLogger(__name__)

# Tablas cuyas filas carecen de sentido sin su fila padre: una fila huérfana
# aquí es siempre residuo de un borrado incompleto, nunca un dato a conservar.
TABLAS_DEPENDIENTES = (
    'documentos_indice',
    'facturas_historial',
)


def _tabla_existe(conn, nombre: str) -> bool:
    """Indica si la tabla existe en la base de datos."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
    ).fetchone() is not None


# ── 1. Corrección: borrar las filas huérfanas existentes ────────────────────

def limpiar_huerfanos() -> int:
    """
    Borra las filas de TABLAS_DEPENDIENTES que referencian un padre inexistente.

    Recorre las claves foráneas declaradas por cada tabla en lugar de asumirlas,
    de modo que sigue funcionando si el esquema cambia.

    Returns:
        Número total de filas borradas.
    """
    total = 0

    with get_db_connection() as conn:
        for tabla in TABLAS_DEPENDIENTES:
            if not _tabla_existe(conn, tabla):
                continue

            for fk in conn.execute(f'PRAGMA foreign_key_list("{tabla}")').fetchall():
                tabla_padre = fk['table']
                col_hija    = fk['from']
                col_padre   = fk['to'] or 'id'

                if not _tabla_existe(conn, tabla_padre):
                    continue

                # Las filas con la clave a NULL no son huérfanas: la referencia
                # es opcional y NULL satisface la restricción.
                borradas = conn.execute(
                    f'DELETE FROM "{tabla}" '
                    f'WHERE "{col_hija}" IS NOT NULL '
                    f'  AND NOT EXISTS ('
                    f'      SELECT 1 FROM "{tabla_padre}" p '
                    f'      WHERE p."{col_padre}" = "{tabla}"."{col_hija}")'
                ).rowcount

                if borradas:
                    total += borradas
                    logger.info(
                        "Integridad: %d filas huérfanas borradas de %s "
                        "(%s -> %s.%s)",
                        borradas, tabla, col_hija, tabla_padre, col_padre
                    )

    if total == 0:
        logger.info("Integridad: sin filas huérfanas que limpiar")

    return total


# ── 2. Prevención: ON DELETE CASCADE en facturas_historial ──────────────────

def reforzar_cascade_facturas_historial() -> bool:
    """
    Declara ON DELETE CASCADE en facturas_historial.factura_id.

    En SQLite esto obligaba a recrear la tabla entera (copiar datos, renombrar
    y recrear índices) porque ALTER TABLE no permite tocar una clave foránea.
    PostgreSQL sí lo permite: basta sustituir la restricción, lo que es
    instantáneo y no mueve datos.

    Returns:
        True si se ha modificado la restricción, False si ya estaba correcta.
    """
    with get_db_connection() as conn:
        if not _tabla_existe(conn, 'facturas_historial'):
            return False

        restriccion = None
        for fk in conn.execute(
            'PRAGMA foreign_key_list("facturas_historial")'
        ).fetchall():
            if fk['from'] != 'factura_id':
                continue
            if (fk['on_delete'] or '').upper() == 'CASCADE':
                return False
            restriccion = fk['constraint_name']

        if restriccion:
            conn.execute(
                f'ALTER TABLE facturas_historial DROP CONSTRAINT "{restriccion}"'
            )

        conn.execute(
            'ALTER TABLE facturas_historial '
            'ADD CONSTRAINT facturas_historial_factura_id_fkey '
            'FOREIGN KEY (factura_id) REFERENCES facturas(id) ON DELETE CASCADE'
        )

    logger.info(
        "Integridad: facturas_historial.factura_id ahora es ON DELETE CASCADE"
    )
    return True


# ── Punto de entrada ────────────────────────────────────────────────────────

def ejecutar_migraciones_integridad() -> None:
    """Ejecuta la limpieza de huérfanos y el refuerzo del esquema."""
    logger.info("Ejecutando migraciones de integridad referencial...")
    limpiar_huerfanos()
    reforzar_cascade_facturas_historial()
    logger.info("Migraciones de integridad completadas")
