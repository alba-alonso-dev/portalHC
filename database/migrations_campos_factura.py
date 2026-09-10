"""
Migración: campos comerciales y técnicos de la factura
=======================================================

Añade a `facturas` los campos que las plantillas ya declaraban en
`campos_disponibles` pero que hasta ahora no se extraían ni se persistían
(eran letra muerta: generaban avisos de validación y nada más).

    importe_total   REAL  — importe facturado
    moneda          TEXT  — divisa del importe (multipaís: EUR/ARS/COP/USD/MXN)
    tarifa          TEXT  — peaje de acceso (2.0TD, 3.0TD, 6.1TD...)
    contrato        TEXT  — referencia de contrato de suministro
    potencia_kw     REAL  — potencia contratada en kW
    distribuidora   TEXT  — empresa distribuidora (distinta de la comercializadora)

Notas de diseño:

* `importe_total` va SIEMPRE acompañado de `moneda`. Guardar un importe sin
  divisa es el mismo error de fondo que guardar un consumo sin unidad: en
  cuanto entran facturas de Argentina o México, sumar la columna produce un
  número sin significado. La divisa se deriva del país de la factura.

* Ninguno de estos campos interviene en el cálculo de emisiones. Son datos
  de gestión y de validación cruzada (p.ej. detectar un consumo absurdo
  comparándolo con el importe), no entradas del GHG Protocol.

* ALTER TABLE ADD COLUMN es seguro e idempotente: no reescribe la tabla ni
  toca los datos existentes. Las filas previas quedan con NULL, que es
  semánticamente correcto ("no se extrajo"), no 0.
"""

import logging

from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)

logger = logging.getLogger(__name__)


COLUMNAS_FACTURA = [
    ("importe_total",  "REAL"),
    ("moneda",         "TEXT"),
    ("tarifa",         "TEXT"),
    ("contrato",       "TEXT"),
    ("potencia_kw",    "REAL"),
    ("distribuidora",  "TEXT"),
]

# Divisa por país. Se centraliza aquí para que exista un único sitio donde
# darla de alta al incorporar un nuevo país.
MONEDA_POR_PAIS = {
    'ES': 'EUR',
    'PT': 'EUR',
    'AR': 'ARS',
    'CO': 'COP',
    'EC': 'USD',
    'MX': 'MXN',
    'CL': 'CLP',
    'PE': 'PEN',
}


def moneda_de_pais(pais: str | None) -> str | None:
    """
    Divisa ISO-4217 del país, o None si no está dado de alta.

    Deliberadamente NO hay divisa por defecto: etiquetar como EUR el importe de
    un país desconocido es peor que dejarlo sin divisa, porque el importe se
    agregaría junto a los europeos y falsearía los totales en silencio. Sin
    moneda, el dato queda visiblemente incompleto y el país se puede dar de
    alta aquí.
    """
    return MONEDA_POR_PAIS.get((pais or '').strip().upper())


def ejecutar_migraciones_campos_factura():
    logger.info("Campos comerciales de factura: iniciando migraciones...")

    with get_db_connection() as conn:
        existentes = {row[1] for row in conn.execute("PRAGMA table_info(facturas)")}
        añadidas = 0
        for nombre, tipo in COLUMNAS_FACTURA:
            if nombre in existentes:
                continue
            try:
                conn.execute(f"ALTER TABLE facturas ADD COLUMN {nombre} {tipo}")
                logger.info(f"  + columna añadida: facturas.{nombre}")
                añadidas += 1
            except OperationalError as exc:
                # Carrera entre procesos: otro worker la creó entremedias.
                if 'already exists' not in str(exc).lower():
                    raise

        # Backfill de moneda solo donde ya hay un importe pero falta la divisa.
        # No se rellena moneda en filas sin importe: sería inventar un dato.
        conn.execute(
            """UPDATE facturas
                  SET moneda = CASE UPPER(COALESCE(pais, ''))
                                   WHEN 'ES' THEN 'EUR'
                                   WHEN 'PT' THEN 'EUR'
                                   WHEN 'AR' THEN 'ARS'
                                   WHEN 'CO' THEN 'COP'
                                   WHEN 'EC' THEN 'USD'
                                   WHEN 'MX' THEN 'MXN'
                                   WHEN 'CL' THEN 'CLP'
                                   WHEN 'PE' THEN 'PEN'
                                   ELSE 'EUR'
                               END
                WHERE importe_total IS NOT NULL AND moneda IS NULL"""
        )

        # Índice para los filtros por tarifa del futuro reporting de compras.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_facturas_tarifa ON facturas(tarifa)"
        )

        if añadidas:
            logger.info(f"  ✓ {añadidas} columnas nuevas en facturas")
        else:
            logger.info("  columnas ya presentes — nada que migrar")

    logger.info("Migraciones de campos comerciales completadas")
