"""
Tests de la pantalla de revisión de datos extraídos.

Cubren el contrato del endpoint de confirmación: qué campos son corregibles a
mano y qué validaciones se les aplican. El foco está en `consumo_kwh`, que es
el único campo corregible que entra en el cálculo de emisiones.

Son tests de unidad puros: no tocan la base de datos.
"""
from routes.facturas import (CAMPO_A_CONFIANZA, CAMPOS_CONFIRMABLES,
                             CONFIANZA_CORRECCION_MANUAL,
                             _validar_campos_confirmar)


def _campos_permitidos() -> set:
    return set(CAMPOS_CONFIRMABLES)


# ── Contrato de campos corregibles ───────────────────────────────────────────

def test_los_campos_de_identificacion_son_corregibles():
    """Son los que el usuario revisa en la pantalla de revisión."""
    permitidos = _campos_permitidos()
    for campo in ('periodo_inicio', 'periodo_fin', 'dias_facturados',
                  'fecha_factura', 'sociedad', 'direccion_suministro'):
        assert campo in permitidos, campo


def test_el_consumo_es_corregible():
    """Es el dato que se revisa de verdad: si está mal, la huella está mal."""
    assert 'consumo_kwh' in _campos_permitidos()


def test_los_campos_derivados_no_son_corregibles_a_mano():
    """
    consumo_mwh, emisiones y el factor los recalcula el servidor a partir del
    consumo. Aceptarlos del cliente permitiría publicar unas emisiones que no
    se corresponden con el consumo guardado.
    """
    permitidos = _campos_permitidos()
    for campo in ('consumo_mwh', 'emisiones_tco2e', 'factor_emision',
                  'factor_version_id', 'moneda'):
        assert campo not in permitidos, campo


# ── Validación del consumo ───────────────────────────────────────────────────

def test_consumo_negativo_o_cero_se_rechaza():
    assert _validar_campos_confirmar({'consumo_kwh': -5})
    assert _validar_campos_confirmar({'consumo_kwh': 0})


def test_consumo_no_numerico_se_rechaza():
    errores = _validar_campos_confirmar({'consumo_kwh': 'mucho'})
    assert any('numérico' in e for e in errores)


def test_consumo_valido_se_acepta():
    assert _validar_campos_confirmar({'consumo_kwh': 1790.0}) == []


def test_consumo_imposible_por_dia_se_rechaza():
    """
    Mismo bound físico que aplica el pipeline (QW9): corregir a mano no puede
    colar un valor que la extracción automática habría vetado por imposible.
    """
    errores = _validar_campos_confirmar(
        {'consumo_kwh': 50_000_000, 'dias_facturados': 30}
    )
    assert any('límite físico' in e for e in errores)


def test_consumo_alto_pero_posible_se_acepta():
    """Una industria grande consume mucho; el bound es por kWh/día, no absoluto."""
    assert _validar_campos_confirmar(
        {'consumo_kwh': 200_000, 'dias_facturados': 30}
    ) == []


# -- Confianza tras correccion manual ----------------------------------------

def test_todo_campo_corregible_tiene_clave_de_confianza():
    """Invariante: si se puede corregir, la correccion debe poder marcarse.

    Un campo corregible sin clave de confianza se corregiria a mano sin que su
    porcentaje dejase nunca de describir la lectura automatica: la pantalla
    seguiria pidiendo revisar un dato ya verificado por una persona.
    """
    assert set(CAMPOS_CONFIRMABLES) == set(CAMPO_A_CONFIANZA)


def test_las_tres_columnas_del_periodo_comparten_clave():
    """La confianza se mide por concepto extraido, no por columna."""
    assert (CAMPO_A_CONFIANZA['periodo_inicio']
            == CAMPO_A_CONFIANZA['periodo_fin']
            == CAMPO_A_CONFIANZA['dias_facturados']
            == 'periodo')


def test_direccion_y_consumo_usan_la_clave_del_pipeline():
    """Las columnas de BD no se llaman igual que las claves de confianza."""
    assert CAMPO_A_CONFIANZA['direccion_suministro'] == 'direccion'
    assert CAMPO_A_CONFIANZA['consumo_kwh'] == 'consumo'
    assert CAMPO_A_CONFIANZA['importe_total'] == 'importe'


def test_la_correccion_manual_vale_el_maximo():
    """Un dato tecleado viendo el PDF no tiene nada mas fiable que lo contraste."""
    assert CONFIANZA_CORRECCION_MANUAL == 1.0


def test_los_campos_derivados_no_tienen_clave_de_confianza():
    """Se recalculan en servidor; nadie los teclea, no hay nada que verificar."""
    for campo in ('consumo_mwh', 'emisiones_tco2e', 'factor_emision',
                  'factor_version_id', 'moneda'):
        assert campo not in CAMPO_A_CONFIANZA, campo
