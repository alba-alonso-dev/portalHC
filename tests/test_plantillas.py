"""
Validación formal del catálogo de plantillas YAML internacionalizadas.

Estas plantillas son la única fuente de verdad de qué sabe leer el sistema en
cada país. Un error tipográfico en un campo o una regex mal escrita degrada la
extracción en silencio: la factura se procesa "con éxito" pero con 0 kWh.
Estos tests convierten ese fallo silencioso en un fallo ruidoso.
"""
import re

import pytest

from services import plantillas_service as ps

PLANTILLAS = ps.get_plantillas()


def test_hay_plantillas_cargadas():
    assert PLANTILLAS, 'No se cargó ninguna plantilla'


def test_el_catalogo_no_tiene_incidencias():
    """`resumen_validacion` recoge typos, regex inválidas y campos sin regla."""
    incidencias = ps.resumen_validacion()
    assert incidencias == [], f'{len(incidencias)} incidencias: {incidencias[:5]}'


def test_la_clave_del_catalogo_es_pais_mas_nombre():
    """El catálogo es multipaís: indexar solo por nombre haría que una
    comercializadora argentina pisara a la española homónima."""
    for clave in PLANTILLAS:
        assert isinstance(clave, tuple) and len(clave) == 2, clave
        pais, nombre = clave
        assert re.fullmatch(r'[A-Z]{2}', pais), f'País no ISO-3166: {pais!r}'
        assert nombre and isinstance(nombre, str)


@pytest.mark.parametrize('clave', list(PLANTILLAS))
def test_campos_declarados_son_conocidos(clave):
    """Un campo desconocido en el YAML nunca se extraería y nadie avisaría."""
    declarados = PLANTILLAS[clave].get('campos_disponibles')
    if declarados is None:
        return  # omitir la clave = "todos los campos", es válido
    desconocidos = set(declarados) - ps.CAMPOS_CONOCIDOS
    assert not desconocidos, f'{clave}: campos desconocidos {desconocidos}'


@pytest.mark.parametrize('clave', list(PLANTILLAS))
def test_ninguna_plantilla_declara_lista_vacia(clave):
    """`campos_disponibles: []` desactiva toda la extracción sin error: la
    factura se guardaría con 0 kWh y 0 emisiones marcada como correcta."""
    declarados = PLANTILLAS[clave].get('campos_disponibles')
    assert declarados is None or len(declarados) > 0, clave


@pytest.mark.parametrize('clave', list(PLANTILLAS))
def test_patrones_de_deteccion_compilan(clave):
    for patron in (PLANTILLAS[clave].get('deteccion') or {}).get('patrones', []):
        try:
            re.compile(patron)
        except re.error as exc:
            pytest.fail(f'{clave}: patrón inválido {patron!r} ({exc})')


@pytest.mark.parametrize('clave', list(PLANTILLAS))
def test_reglas_de_extraccion_compilan(clave):
    for campo, regla in (PLANTILLAS[clave].get('extraccion') or {}).items():
        patrones = regla.get('patrones') or ([regla['patron']] if regla.get('patron') else [])
        for patron in patrones:
            try:
                re.compile(patron)
            except re.error as exc:
                pytest.fail(f'{clave}/{campo}: patrón inválido {patron!r} ({exc})')


def test_la_deteccion_ordena_patrones_de_mas_largo_a_mas_corto():
    """Si 'EDES' se evalúa antes que 'EDESUR', toda factura de EDESUR se
    atribuiría a la comercializadora equivocada."""
    for pais in {p for p, _ in PLANTILLAS}:
        patrones = list(ps.mapa_deteccion(pais))
        longitudes = [len(p) for p in patrones]
        assert longitudes == sorted(longitudes, reverse=True), \
            f'{pais}: patrones de detección sin ordenar por longitud'


def test_las_funciones_publicas_exigen_pais():
    """Regresión: estas firmas migraron a multipaís y sus llamadores no se
    actualizaron, lo que rompió la app en tiempo de import."""
    import inspect
    for fn in (ps.mapa_deteccion, ps.campos_disponibles, ps.categoria,
               ps.regla_extraccion_campo, ps.zonas, ps.firma):
        primero = list(inspect.signature(fn).parameters)[0]
        assert primero == 'pais', f'{fn.__name__} no recibe pais primero'
