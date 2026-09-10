"""
Tests de la sociedad de respaldo del formulario de carga.

El campo "Sociedad" de la pantalla de carga es un respaldo, no la clave de
agrupacion: una misma sede puede tener varios CUPS facturados a sociedades
distintas, asi que el valor leido de la factura siempre manda sobre el que se
teclee en el formulario.
"""
import types

from services.lote_service import _aplicar_sociedad_respaldo


def _datos(sociedad=None):
    return types.SimpleNamespace(sociedad=sociedad)


def test_rellena_cuando_la_extraccion_no_encuentra_sociedad():
    d = _datos(None)
    assert _aplicar_sociedad_respaldo(d, 'HIBERUS DIGITAL S.L.') is True
    assert d.sociedad == 'HIBERUS DIGITAL S.L.'


def test_rellena_cuando_la_extraccion_devuelve_cadena_vacia():
    d = _datos('   ')
    assert _aplicar_sociedad_respaldo(d, 'HIBERUS DIGITAL S.L.') is True
    assert d.sociedad == 'HIBERUS DIGITAL S.L.'


def test_no_pisa_la_sociedad_extraida_de_la_factura():
    """Asturias tiene CUPS de dos sociedades: el formulario no puede unificarlas."""
    d = _datos('HIBERUS IT DEVELOPMENT SERVICES SL')
    assert _aplicar_sociedad_respaldo(d, 'Hiberus Tecnologias de la Informacion SL') is False
    assert d.sociedad == 'HIBERUS IT DEVELOPMENT SERVICES SL'


def test_sin_valor_en_el_formulario_no_hace_nada():
    d = _datos(None)
    assert _aplicar_sociedad_respaldo(d, None) is False
    assert d.sociedad is None
    assert _aplicar_sociedad_respaldo(d, '   ') is False
    assert d.sociedad is None


def test_recorta_espacios_del_formulario():
    d = _datos(None)
    _aplicar_sociedad_respaldo(d, '  HIBERUS DIGITAL S.L.  ')
    assert d.sociedad == 'HIBERUS DIGITAL S.L.'
