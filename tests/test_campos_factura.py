"""
Tests de los campos comerciales y técnicos de factura.

Cubren el contrato completo de `importe`, `moneda`, `tarifa`, `contrato`,
`potencia` y `distribuidora`: extracción, normalización, cotas de cordura,
divisa por país y separación respecto al cálculo de emisiones.

Son tests de unidad puros: no tocan la base de datos ni ejecutan OCR.
"""
import re

import pytest

from database.migrations_campos_factura import MONEDA_POR_PAIS, moneda_de_pais
from services import extraccion_service as ex
from services.ocr_quality_service import FIELD_WEIGHTS, recalcular_confianza_global
from services.plantillas_service import (CAMPOS_CONOCIDOS, CAMPOS_EXTRAIBLES,
                                         CAMPOS_METADATO)

CAMPOS_NUEVOS = {'importe', 'tarifa', 'contrato', 'potencia', 'distribuidora'}


# ── Contrato de campos ───────────────────────────────────────────────────────

def test_los_cinco_campos_son_extraibles():
    """Si un campo se declara en un YAML, el pipeline debe implementarlo."""
    assert CAMPOS_NUEVOS <= CAMPOS_EXTRAIBLES


def test_campos_conocidos_es_la_union():
    assert CAMPOS_CONOCIDOS == CAMPOS_EXTRAIBLES | CAMPOS_METADATO


def test_extraibles_y_metadato_son_disjuntos():
    assert not (CAMPOS_EXTRAIBLES & CAMPOS_METADATO)


def test_datosfactura_expone_los_campos():
    d = ex.DatosFactura()
    for attr in ('importe_total', 'moneda', 'tarifa', 'contrato',
                 'potencia_kw', 'distribuidora'):
        assert hasattr(d, attr), attr
        assert getattr(d, attr) is None


# ── Divisa ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('pais,esperado', [
    ('ES', 'EUR'), ('AR', 'ARS'), ('CO', 'COP'),
    ('EC', 'USD'), ('MX', 'MXN'),
])
def test_moneda_se_deriva_del_pais(pais, esperado):
    """La divisa nunca sale del símbolo que lee el OCR: '$' es ambiguo entre
    ARS, COP, MXN y USD."""
    assert moneda_de_pais(pais) == esperado


def test_moneda_es_case_insensitive_y_tolera_espacios():
    assert moneda_de_pais(' es ') == 'EUR'


def test_moneda_de_pais_desconocido_no_inventa_divisa():
    """Etiquetar como EUR un importe de país no dado de alta lo mezclaría en
    los totales europeos sin dejar rastro."""
    assert moneda_de_pais('ZZ') is None
    assert moneda_de_pais(None) is None
    assert moneda_de_pais('') is None


def test_todas_las_monedas_son_iso_4217():
    for pais, moneda in MONEDA_POR_PAIS.items():
        assert re.fullmatch(r'[A-Z]{3}', moneda), f'{pais} -> {moneda}'


# ── Normalización numérica (importe y potencia comparten helper) ─────────────

@pytest.mark.parametrize('bruto,esperado', [
    ('1.234,56', 1234.56),    # formato ES
    ('1,234.56', 1234.56),    # formato anglosajón
    ('81.600,00', 81600.0),   # miles con coma decimal
    ('929', 929.0),
])
def test_normalizacion_de_importes(bruto, esperado):
    assert ex._normalizar_consumo(bruto) == pytest.approx(esperado)


# ── Cotas de cordura ─────────────────────────────────────────────────────────

def test_importe_descarta_lecturas_absurdas():
    """Una lectura de contador colada como importe debe rechazarse en vez de
    persistirse como un importe de 40 millones."""
    valor, conf = ex.extraer_importe('TOTAL FACTURA 40.000.000,00 EUR', None, 'ES')
    assert valor is None
    assert conf == 0.0


def test_potencia_descarta_valores_imposibles():
    valor, conf = ex.extraer_potencia('Potencia contratada 999.999 kW', None, 'ES')
    assert valor is None
    assert conf == 0.0


def test_extractores_toleran_texto_vacio():
    for fn in (ex.extraer_importe, ex.extraer_potencia, ex.extraer_tarifa,
               ex.extraer_contrato, ex.extraer_distribuidora):
        valor, conf = fn('', None, 'ES')
        assert valor is None, fn.__name__
        assert conf == 0.0, fn.__name__


# ── Aislamiento respecto al cálculo de emisiones ─────────────────────────────

def test_los_campos_nuevos_no_ponderan_la_confianza():
    """La confianza global mide cuánto nos fiamos del dato que alimenta la
    huella de carbono. Si la referencia de contrato pesara, una factura con el
    consumo perfectamente leído bajaría de confianza sin motivo."""
    assert not (CAMPOS_NUEVOS & set(FIELD_WEIGHTS))


def test_confianza_identica_con_y_sin_campos_comerciales():
    base = {'consumo': 0.9, 'periodo': 0.8, 'cups': 0.7, 'sede': 1.0}
    aplicables = {'consumo', 'periodo', 'cups'}

    con_extras = dict(base, importe=0.0, tarifa=0.0, contrato=0.0,
                      potencia=0.0, distribuidora=0.0)

    assert (recalcular_confianza_global(base, aplicables)
            == recalcular_confianza_global(con_extras, aplicables))


def test_campo_no_aplicable_no_penaliza():
    """None es el sentinela de 'no aplica': debe ignorarse, no contar como 0."""
    solo_consumo = {'consumo': 1.0, 'periodo': None, 'cups': None, 'sede': 1.0}
    assert recalcular_confianza_global(solo_consumo, {'consumo'}) == 1.0
