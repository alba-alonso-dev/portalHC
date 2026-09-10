"""
Aritmética decimal para importes, consumos y emisiones.

Los cálculos monetarios y de reporting no deben hacerse con coma flotante ni con
la función ``round()`` de Python, por dos motivos:

1. ``round()`` aplica **redondeo bancario** (al par más cercano): ``round(2.675, 2)``
   devuelve ``2.67``, no ``2.68``. La convención en reporting financiero y de
   emisiones es redondear al alza en el punto medio (ROUND_HALF_UP).
2. Encadenar redondeos intermedios acumula desviación. Convertir kWh a MWh
   redondeando a 3 decimales y multiplicar después por el factor introduce un
   error que ya no es recuperable.

Este módulo centraliza la conversión a ``Decimal`` y el redondeo, de modo que una
misma magnitud se redondee siempre con el mismo criterio y con la misma precisión
en todo el portal, y que las cifras almacenadas se puedan reproducir entre sí:
las emisiones guardadas son exactamente el resultado de multiplicar el consumo y
el factor guardados.

Las columnas siguen almacenándose como ``REAL`` en SQLite; lo que cambia es que la
aritmética se hace en decimal y solo se convierte a ``float`` al final.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

Numero = Union[int, float, str, Decimal, None]

# Precisión de cada magnitud, unificada para todo el portal.
PREC_IMPORTE   = Decimal('0.01')        # dinero: 2 decimales
PREC_KWH       = Decimal('0.01')        # consumo en kWh
PREC_MWH       = Decimal('0.000001')    # consumo en MWh: 6 decimales para que la
                                        # conversión desde kWh sea exacta y no
                                        # pierda información al dividir por 1000
PREC_MWH_REPORTE = Decimal('0.001')     # MWh agregados, para presentación
PREC_EMISIONES = Decimal('0.0001')      # tCO₂e: 4 decimales
PREC_PORCENTAJE = Decimal('0.01')


def a_decimal(valor: Numero) -> Optional[Decimal]:
    """
    Convierte un valor a ``Decimal`` sin arrastrar la representación binaria.

    Se pasa por ``str()`` a propósito: ``Decimal(0.1)`` daría
    ``0.1000000000000000055511151231257827``, mientras que ``Decimal('0.1')`` es
    exactamente una décima.

    Devuelve None si el valor es None o no es convertible.
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def redondear(valor: Numero, precision: Decimal) -> Optional[float]:
    """Redondea a la precisión indicada con ROUND_HALF_UP y devuelve un float."""
    decimal = a_decimal(valor)
    if decimal is None:
        return None
    return float(decimal.quantize(precision, rounding=ROUND_HALF_UP))


# ── Atajos por magnitud ─────────────────────────────────────────────────────

def importe(valor: Numero) -> Optional[float]:
    """Redondea un importe monetario a 2 decimales."""
    return redondear(valor, PREC_IMPORTE)


def kwh(valor: Numero) -> Optional[float]:
    """Redondea un consumo en kWh a 2 decimales."""
    return redondear(valor, PREC_KWH)


def mwh(valor: Numero) -> Optional[float]:
    """Redondea un consumo en MWh a 6 decimales."""
    return redondear(valor, PREC_MWH)


def mwh_reporte(valor: Numero) -> Optional[float]:
    """Redondea un total de MWh a 3 decimales, para mostrar en informes."""
    return redondear(valor, PREC_MWH_REPORTE)


def tco2e(valor: Numero) -> Optional[float]:
    """Redondea unas emisiones en tCO₂e a 4 decimales."""
    return redondear(valor, PREC_EMISIONES)


def porcentaje(valor: Numero) -> Optional[float]:
    """Redondea un porcentaje a 2 decimales."""
    return redondear(valor, PREC_PORCENTAJE)


# ── Conversiones y fórmulas del dominio ─────────────────────────────────────

def kwh_a_mwh(consumo_kwh: Numero) -> Optional[float]:
    """
    Convierte kWh a MWh sin pérdida.

    Con 6 decimales la división por 1000 es exacta para cualquier lectura de
    consumo con hasta 3 decimales, que cubre de sobra lo que devuelve el OCR.
    """
    decimal = a_decimal(consumo_kwh)
    if decimal is None:
        return None
    return float((decimal / 1000).quantize(PREC_MWH, rounding=ROUND_HALF_UP))


def calcular_tco2e(consumo_mwh: Numero, factor_kg_co2_mwh: Numero) -> Optional[float]:
    """
    Calcula las emisiones en tCO₂e a partir del consumo y el factor de emisión.

    Fórmula (GHG Protocol):  tCO₂e = MWh × kgCO₂/MWh ÷ 1000

    Se resuelve en un único paso decimal, sin redondeos intermedios, y solo se
    redondea el resultado final. Devuelve None si falta cualquiera de los dos
    operandos.
    """
    consumo = a_decimal(consumo_mwh)
    factor  = a_decimal(factor_kg_co2_mwh)
    if consumo is None or factor is None:
        return None
    return float((consumo * factor / 1000).quantize(
        PREC_EMISIONES, rounding=ROUND_HALF_UP
    ))


def sumar(valores, precision: Decimal = PREC_EMISIONES) -> float:
    """
    Suma una secuencia de valores en decimal, ignorando los nulos.

    Evita la deriva de acumular floats cuando se agregan muchas filas en Python
    (las agregaciones hechas con SUM() en SQLite siguen siendo de coma flotante).
    """
    total = Decimal('0')
    for valor in valores:
        decimal = a_decimal(valor)
        if decimal is not None:
            total += decimal
    return float(total.quantize(precision, rounding=ROUND_HALF_UP))
