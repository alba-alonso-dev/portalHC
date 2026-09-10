"""
Tests del servicio OCR: compatibilidad entre versiones de PaddleOCR.

Contexto del fallo que cubren
─────────────────────────────
Con PaddleOCR 3.7 instalado, el servicio construia la instancia pasando
`drop_score`, que esa version ya no acepta. El constructor lanzaba ValueError,
pero el codigo solo capturaba TypeError, asi que la excepcion subia hasta el
`except Exception` de `_ocr_pagina` y se registraba como un simple warning.

Efecto: TODO PDF escaneado devolvia 0 caracteres en silencio y acababa
clasificado como "documento sin plantilla", ocultando que el problema real era
que el OCR no llegaba a ejecutarse nunca.
"""
import sys

import pytest

from services import ocr_service


# ── Normalizacion del resultado (formato 2.x vs 3.x) ─────────────────────────

class _ResultadoV3(dict):
    """Imita el OCRResult de PaddleOCR 3.x: un mapeo con listas paralelas."""


def test_normaliza_formato_3x():
    res = [_ResultadoV3(rec_texts=['EDP', '1.234 kWh'], rec_scores=[0.99, 0.87])]
    assert ocr_service._lineas_de_resultado(res) == [('EDP', 0.99), ('1.234 kWh', 0.87)]


def test_normaliza_formato_2x():
    res = [[
        [[[0, 0], [1, 0], [1, 1], [0, 1]], ('EDP', 0.99)],
        [[[0, 2], [1, 2], [1, 3], [0, 3]], ('1.234 kWh', 0.87)],
    ]]
    assert ocr_service._lineas_de_resultado(res) == [('EDP', 0.99), ('1.234 kWh', 0.87)]


def test_resultado_vacio_no_revienta():
    assert ocr_service._lineas_de_resultado(None) == []
    assert ocr_service._lineas_de_resultado([]) == []
    assert ocr_service._lineas_de_resultado([[]]) == []


def test_texto_sin_score_no_se_pierde():
    """Un score ausente no debe descartar texto legible."""
    res = [_ResultadoV3(rec_texts=['EDP', 'Iberdrola'], rec_scores=[0.99])]
    assert ocr_service._lineas_de_resultado(res) == [('EDP', 0.99), ('Iberdrola', 1.0)]


def test_formato_2x_con_lineas_corruptas_se_saltan():
    res = [[
        [[[0, 0]], ('EDP', 0.99)],
        ['basura'],
        [[[0, 2]], ('Naturgy', 0.91)],
    ]]
    assert ocr_service._lineas_de_resultado(res) == [('EDP', 0.99), ('Naturgy', 0.91)]


# ── Constructor tolerante al nombre del umbral ───────────────────────────────

def _fake_paddle(monkeypatch, acepta):
    """Instala un PaddleOCR falso que solo admite los kwargs de `acepta`."""
    registro = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            extra = set(kwargs) - acepta
            if extra:
                raise ValueError(f"Unknown argument: {sorted(extra)[0]}")
            registro.update(kwargs)

    modulo = type(sys)('paddleocr')
    modulo.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, 'paddleocr', modulo)
    return registro


def test_usa_el_umbral_moderno_si_esta_disponible(monkeypatch):
    base = {'lang', 'use_textline_orientation'}
    reg = _fake_paddle(monkeypatch, base | {'text_rec_score_thresh'})
    ocr_service._construir_ocr()
    assert reg['text_rec_score_thresh'] == ocr_service._OCR_DROP_SCORE


def test_cae_a_drop_score_en_versiones_antiguas(monkeypatch):
    base = {'lang', 'use_textline_orientation'}
    reg = _fake_paddle(monkeypatch, base | {'drop_score'})
    ocr_service._construir_ocr()
    assert reg['drop_score'] == ocr_service._OCR_DROP_SCORE


def test_construye_aunque_no_acepte_ningun_umbral(monkeypatch):
    """Este es el caso que rompia: no debe propagar la excepcion."""
    reg = _fake_paddle(monkeypatch, {'lang', 'use_textline_orientation'})
    ocr_service._construir_ocr()
    assert 'drop_score' not in reg and 'text_rec_score_thresh' not in reg
    assert reg['lang'] == 'es'


def test_permite_desactivar_onednn(monkeypatch):
    base = {'lang', 'use_textline_orientation', 'enable_mkldnn'}
    reg = _fake_paddle(monkeypatch, base | {'text_rec_score_thresh'})
    ocr_service._construir_ocr(enable_mkldnn=False)
    assert reg['enable_mkldnn'] is False
