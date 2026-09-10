# -*- coding: utf-8 -*-
"""
Detección de comercializadora tolerante al espaciado + plantilla de la
Universidad de Cantabria.

Contexto: los PDF escaneados llegan por OCR con un token por línea, así que
'UNIVERSIDAD DE CANTABRIA' aparece como 'Universidad\\nde Cantabria'. La
detección usaba re.escape(), que exige el espacio literal, y esos documentos
quedaban clasificados como "sin plantilla" pese a tenerla.
"""
import re

import pytest

from services import extraccion_service as ex


# ── _regex_alias ─────────────────────────────────────────────────────────────

def test_regex_alias_acepta_salto_de_linea():
    """El caso real del OCR: el alias partido en dos líneas."""
    patron = ex._regex_alias("UNIVERSIDAD DE CANTABRIA")
    assert re.search(patron, "UC I\nUniversidad\nde Cantabria\n", re.IGNORECASE)


def test_regex_alias_acepta_espacios_multiples():
    """pdfplumber inserta espacios de más al reconstruir columnas."""
    patron = ex._regex_alias("FENIE ENERGIA")
    assert re.search(patron, "Fenie   Energia", re.IGNORECASE)


def test_regex_alias_sigue_exigiendo_separacion():
    """
    \\s+ exige AL MENOS un espacio: el alias no debe casar con el texto
    pegado, porque eso cambiaría el significado del patrón declarado.
    """
    patron = ex._regex_alias("UNIVERSIDAD DE GRANADA")
    assert not re.search(patron, "UNIVERSIDADDEGRANADA", re.IGNORECASE)


def test_regex_alias_escapa_metacaracteres():
    """Un alias con '.' no debe convertirse en comodín."""
    patron = ex._regex_alias("E.ON")
    assert re.search(patron, "E.ON", re.IGNORECASE)
    assert not re.search(patron, "EXON", re.IGNORECASE)


def test_regex_alias_alias_de_una_palabra():
    patron = ex._regex_alias("ENDESA")
    assert re.search(patron, "endesa", re.IGNORECASE)


# ── Detección extremo a extremo ──────────────────────────────────────────────

TEXTO_OCR_CANTABRIA = """Consumos de Energía
UC I
Universidad
de Cantabria
Usuario:
FASE A MODULO 211
Centro:
Edificio CDTUC
INFORME CREADO:
04/02/2026 17:13:11
Desde:
01/01/2026 00:00:00
Hasta:
01/02/2026 00:00:00
TÉRMINO DE ENERGÍA VARIABLE:
P1:
122,63
kWh
X
0.18796503
EUR/kW
23,05
Euros
P2:
51,59
kWh
X
0,15272983
EUR/kW
7,88
Euros
P3:
0
kWh
X
0,11632456
EUR/kW
0
Euros
P4:
0
kWh
X
0,13982155
EUR/kW
0
Euros
P5:
0
kWh
X
0,11701426
EUR/kW
0
Euros
P6:
9.15
kWh
X
0,10770452
EUR/kW
0,99
Euros
TÉRMINO DE POTENCIA FIJO:
P1:
1
kW
X
35,81039528
EUR/kW
35,81
Euros
"""


def test_detecta_cantabria_en_texto_ocr():
    com, conf = ex.extraer_comercializadora(TEXTO_OCR_CANTABRIA, 'ES')
    assert com == "Universidad de Cantabria"
    assert conf > 0.9


def test_consumo_cantabria_suma_los_seis_periodos():
    """122,63 + 51,59 + 0 + 0 + 0 + 9,15 = 183,37 kWh."""
    com, _ = ex.extraer_comercializadora(TEXTO_OCR_CANTABRIA, 'ES')
    consumo, conf = ex.extraer_consumo(TEXTO_OCR_CANTABRIA, com, 'ES')
    assert consumo == pytest.approx(183.37, abs=0.01)
    assert conf >= 0.85


def test_consumo_cantabria_ignora_el_termino_de_potencia():
    """
    El bloque de POTENCIA reutiliza las etiquetas P1..P6 pero en kW. Si el
    patrón las confundiera, el total se dispararía.
    """
    com, _ = ex.extraer_comercializadora(TEXTO_OCR_CANTABRIA, 'ES')
    consumo, _ = ex.extraer_consumo(TEXTO_OCR_CANTABRIA, com, 'ES')
    assert consumo < 200


def test_periodo_cantabria_via_regla_de_plantilla():
    """
    Los 8 patrones genéricos no casan este formato ('Desde:'/'Hasta:' en
    líneas sueltas); debe rescatarlo la regla declarada en el YAML.
    """
    com, _ = ex.extraer_comercializadora(TEXTO_OCR_CANTABRIA, 'ES')
    ini, fin, dias, conf = ex._extraer_periodo_regla(TEXTO_OCR_CANTABRIA, com, 'ES')
    assert (ini, fin, dias) == ('2026-01-01', '2026-02-01', 32)
    assert conf >= 0.85


def test_fecha_factura_cantabria():
    com, _ = ex.extraer_comercializadora(TEXTO_OCR_CANTABRIA, 'ES')
    fecha, conf = ex.extraer_fecha_factura(TEXTO_OCR_CANTABRIA, com, 'ES')
    assert fecha == '2026-02-04'
    assert conf > 0
