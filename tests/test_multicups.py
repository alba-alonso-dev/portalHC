"""
Tests de sedes con varios puntos de suministro (multi-CUPS).

Una sede puede tener varios CUPS y recibir una factura de cada uno en el mismo
mes. Esas facturas son complementarias: el consumo de la sede es su SUMA, no
duplicados que haya que descartar ni valores alternativos entre los que elegir.

Cubren las dos consecuencias que tenía asumir "una factura = una sede y un mes":
  - marcar como duplicada la factura de un segundo CUPS (e invitar a anularla);
  - estimar el consumo de un mes tomando una sola factura o promediando factura
    a factura, lo que infravalora la sede en proporción a su número de CUPS.
"""
import contextlib

import pytest

from database.connection import get_db_connection
from psycopg import OperationalError
from services import estimacion_service, lote_service


# ── Arnés de base de datos ───────────────────────────────────────────────────

# Esquema PostgreSQL aislado: las tablas de prueba viven aquí y se destruyen al
# terminar, sin tocar los datos reales. `public` se mantiene en el search_path
# porque ahí están las funciones de compatibilidad (strftime, julianday...).
ESQUEMA_TESTS = 'test_multicups'

SCHEMA = '''
CREATE TABLE facturas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    pais             TEXT NOT NULL,
    sede             TEXT NOT NULL,
    tipo_energia     TEXT DEFAULT 'electricidad',
    tipo_dato        TEXT DEFAULT 'real',
    cups             TEXT,
    sociedad         TEXT,
    periodo_inicio   TEXT,
    periodo_fin      TEXT,
    dias_facturados  INTEGER,
    consumo_kwh      REAL,
    consumo_mwh      REAL,
    emisiones_tco2e  REAL,
    sha256_documento TEXT,
    fecha_anulacion  TIMESTAMP,
    fecha_carga      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archivo_nombre   TEXT DEFAULT 'f.pdf'
)
'''

# Dos CUPS de la misma sede y sociedad, facturados el mismo período.
# El consumo real de cada mes es la suma de ambos.
FACTURAS = [
    # (cups,      periodo_inicio, periodo_fin,  dias, kwh)
    ('CUPS-GRANDE', '2025-01-01', '2025-01-31', 31, 1800.0),
    ('CUPS-PEQUENO', '2025-01-01', '2025-01-31', 31, 200.0),
    ('CUPS-GRANDE', '2025-02-01', '2025-02-28', 28, 1600.0),
    ('CUPS-PEQUENO', '2025-02-01', '2025-02-28', 28, 400.0),
    ('CUPS-GRANDE', '2025-03-01', '2025-03-31', 31, 2200.0),
    ('CUPS-PEQUENO', '2025-03-01', '2025-03-31', 31, 300.0),
]


@pytest.fixture
def db(monkeypatch):
    """
    Esquema temporal poblado con una sede de 2 CUPS, inyectado en los servicios.

    Se apoya en la base de datos PostgreSQL configurada (DATABASE_URL) pero
    crea sus tablas en un esquema propio, de modo que no interfiere con los
    datos reales.
    """
    @contextlib.contextmanager
    def _conexion_test():
        with get_db_connection() as conn:
            conn.execute(f'SET search_path TO {ESQUEMA_TESTS}, public')
            yield conn

    try:
        with get_db_connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS {ESQUEMA_TESTS} CASCADE')
            conn.execute(f'CREATE SCHEMA {ESQUEMA_TESTS}')
    except OperationalError:
        pytest.skip("PostgreSQL no disponible (revisa DATABASE_URL)")

    with _conexion_test() as conn:
        conn.execute(SCHEMA)
        for cups, ini, fin, dias, kwh in FACTURAS:
            conn.execute(
                '''INSERT INTO facturas
                   (pais, sede, cups, sociedad, periodo_inicio, periodo_fin,
                    dias_facturados, consumo_kwh, consumo_mwh, emisiones_tco2e)
                   VALUES ('ES','Asturias',?,'Hiberus SL',?,?,?,?,?,?)''',
                (cups, ini, fin, dias, kwh, kwh / 1000, kwh / 1000 * 0.2)
            )

    monkeypatch.setattr(estimacion_service, 'get_db_connection', _conexion_test)
    monkeypatch.setattr(lote_service, 'get_db_connection', _conexion_test)

    yield _conexion_test

    with get_db_connection() as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS {ESQUEMA_TESTS} CASCADE')


# ── Agregación mensual ───────────────────────────────────────────────────────

def test_el_consumo_del_mes_es_la_suma_de_los_cups(db):
    meses = estimacion_service._consumos_mensuales('ES', 'Asturias', 'electricidad')

    assert [m['mes'] for m in meses] == ['2025-01', '2025-02', '2025-03']
    assert meses[0]['total_kwh'] == 2000.0   # 1800 + 200
    assert meses[1]['total_kwh'] == 2000.0   # 1600 + 400
    assert meses[2]['total_kwh'] == 2500.0   # 2200 + 300


def test_la_agregacion_declara_cuantos_cups_componen_el_mes(db):
    """Sin este dato no se puede distinguir un mes incompleto de uno de un solo CUPS."""
    mes = estimacion_service._consumos_mensuales('ES', 'Asturias', 'electricidad')[0]
    assert mes['n_cups'] == 2
    assert mes['n_facturas'] == 2
    assert len(mes['refs']) == 2


def test_los_dias_del_mes_no_se_suman_entre_cups(db):
    """
    El período de un mes con 2 CUPS sigue durando 31 días, no 62. Sumarlos
    dividiría por dos el ratio kWh/día del método de estimación 'por_dias'.
    """
    mes = estimacion_service._consumos_mensuales('ES', 'Asturias', 'electricidad')[0]
    assert mes['dias'] == 31


def test_las_facturas_anuladas_no_cuentan(db):
    with db() as conn:
        conn.execute("UPDATE facturas SET fecha_anulacion=CURRENT_TIMESTAMP "
                     "WHERE cups='CUPS-PEQUENO' AND periodo_inicio='2025-01-01'")

    meses = estimacion_service._consumos_mensuales('ES', 'Asturias', 'electricidad')
    assert meses[0]['total_kwh'] == 1800.0
    assert meses[0]['n_cups'] == 1


# ── Métodos de estimación ────────────────────────────────────────────────────

def test_la_media_historica_promedia_meses_no_facturas(db):
    """
    Con 2 CUPS hay 6 facturas y 3 meses. Promediar facturas daría 1083 kWh
    (el consumo de un punto de suministro medio); la sede consume 2166 al mes.
    """
    media, refs = estimacion_service._media_historica('ES', 'Asturias', 'electricidad')

    assert media == pytest.approx((2000 + 2000 + 2500) / 3, abs=0.01)
    assert len(refs) == 6, "debe referenciar todas las facturas agregadas"


def test_el_mismo_mes_del_anio_anterior_suma_los_cups(db):
    """Antes tomaba `LIMIT 1`: estimaba el mes con el consumo de un solo CUPS."""
    valor, refs = estimacion_service._mismo_mes_anio_anterior(
        'ES', 'Asturias', '2026-01', 'electricidad')

    assert valor == 2000.0
    assert len(refs) == 2


def test_el_metodo_adyacente_suma_los_cups_de_cada_mes(db):
    """Media de 2025-01 (2000) y 2025-03 (2500) = 2250."""
    valor, refs = estimacion_service._adyacente(
        'ES', 'Asturias', '2025-02', 'electricidad')

    assert valor == 2250.0
    assert len(refs) == 4


def test_el_ratio_por_dias_usa_el_consumo_agregado(db):
    """
    El ratio del mes es 2000 kWh / 31 días, no el de una factura suelta.
    Para febrero (28 días) los meses cercanos son enero y marzo.
    """
    valor, refs, detalle = estimacion_service._por_dias(
        'ES', 'Asturias', '2025-02', 'electricidad')

    esperado = (2000 / 31 + 2500 / 31) / 2 * 28
    assert valor == pytest.approx(esperado, abs=0.01)
    assert detalle['n_referencias'] == 2


def test_la_estacionalidad_exige_doce_meses_no_doce_facturas(db):
    """
    Con 2 CUPS, 12 facturas son solo 6 meses de histórico: insuficiente para
    calcular índices de estacionalidad fiables.
    """
    valor, refs, detalle = estimacion_service._estacional(
        'ES', 'Asturias', '2025-04', 'electricidad')

    assert valor is None
    assert 'meses' in detalle['error']


# ── Detección de duplicados ──────────────────────────────────────────────────

def test_dos_cups_en_el_mismo_periodo_no_son_duplicados(db):
    """El caso que marcaba como duplicadas facturas legítimas de otro CUPS."""
    advertencias = lote_service._verificar_duplicados(
        'ES', 'Asturias', 'electricidad',
        '2025-01-01', '2025-01-31', sha256=None, cups='CUPS-NUEVO')

    assert advertencias == []


def test_el_mismo_cups_en_el_mismo_periodo_si_es_duplicado(db):
    advertencias = lote_service._verificar_duplicados(
        'ES', 'Asturias', 'electricidad',
        '2025-01-01', '2025-01-31', sha256=None, cups='CUPS-GRANDE')

    assert len(advertencias) == 1
    assert 'Duplicado por período' in advertencias[0]
    assert 'CUPS-GRANDE' in advertencias[0]


def test_sin_cups_solo_se_compara_con_facturas_sin_cups(db):
    """
    Tratar un CUPS ilegible como "el mismo" que cualquier otro reintroduciría
    los falsos duplicados en las sedes multi-CUPS.
    """
    advertencias = lote_service._verificar_duplicados(
        'ES', 'Asturias', 'electricidad',
        '2025-01-01', '2025-01-31', sha256=None, cups=None)

    assert advertencias == []


def test_el_mismo_pdf_sigue_siendo_duplicado_aunque_cambie_el_cups(db):
    """La regla de SHA-256 es independiente del punto de suministro."""
    with db() as conn:
        conn.execute("UPDATE facturas SET sha256_documento='abc123' WHERE id=1")

    advertencias = lote_service._verificar_duplicados(
        'ES', 'Asturias', 'electricidad',
        '2024-05-01', '2024-05-31', sha256='abc123', cups='OTRO-CUPS')

    assert len(advertencias) == 1
    assert 'contenido PDF' in advertencias[0]


# ── Anomalías de consumo ─────────────────────────────────────────────────────

def test_la_anomalia_se_mide_contra_el_historico_del_mismo_cups(db):
    """
    El CUPS grande (~1800 kWh) no es anómalo aunque supere con creces la media
    mezclada de la sede (~1083 kWh), que incluye al CUPS pequeño.
    """
    aviso = lote_service._detectar_anomalia_consumo(
        'ES', 'Asturias', 'electricidad', 1900.0, cups='CUPS-GRANDE')

    assert aviso is None


def test_un_consumo_desbocado_del_propio_cups_si_se_detecta(db):
    aviso = lote_service._detectar_anomalia_consumo(
        'ES', 'Asturias', 'electricidad', 9000.0, cups='CUPS-PEQUENO')

    assert aviso is not None
    assert 'anómalo' in aviso
