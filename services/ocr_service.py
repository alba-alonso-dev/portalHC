"""
Servicio OCR: extracción de texto de PDFs con pdfplumber y PaddleOCR como fallback.
Devuelve el texto extraído junto a una puntuación de confianza media [0-1].

La confianza se usa en el servicio de extracción para decidir si un campo
requiere revisión manual.

Thread-safety
─────────────
PaddleOCR (y su backend PaddlePaddle en C++) NO es thread-safe: estado interno
compartido puede corromperse si dos hilos llaman a .ocr() simultáneamente.
Escenario de riesgo: dos usuarios lanzan lotes al mismo tiempo → dos daemon
threads → dos llamadas concurrentes a _ocr_pagina().

Solución: _ocr_lock serializa TANTO la inicialización lazy como cada inferencia.
El coste es mínimo porque la ruta rápida (pdfplumber) no adquiere el lock;
PaddleOCR solo se invoca como fallback cuando el PDF no tiene capa de texto.
"""

import logging
import os
import threading

import numpy as np
import pdfplumber

logger = logging.getLogger(__name__)

# Singleton + lock de exclusión mutua para inicialización e inferencia.
# PaddleOCR no garantiza thread-safety → serialización obligatoria.
_paddle_ocr = None
_ocr_lock = threading.Lock()

# oneDNN (aka MKL-DNN) acelera la inferencia en CPUs modernos, pero en algunos
# entornos —especialmente contenedores Docker sobre WSL2— PaddlePaddle aborta
# el proceso con SIGABRT ("ConvertPirAttribute2RuntimeAttribute not support").
# El SIGABRT es a nivel C++ y no se puede capturar con try/except Python, así
# que el worker de gunicorn muere sin que el reintento de _inferir() se ejecute.
#
# Variable de entorno PADDLE_DISABLE_MKLDNN=true:
#   Inicializa PaddleOCR sin oneDNN desde el principio, evitando el crash.
#   Es más lento pero estable. Se activa por defecto en el Dockerfile.
_sin_onednn = os.environ.get('PADDLE_DISABLE_MKLDNN', '').lower() in ('1', 'true', 'yes')

from services.plantillas_service import zonas as _zonas_yaml

# QW3 — umbral de descarte de tokens OCR de muy baja confianza. Se aplica tanto
# como parámetro nativo de PaddleOCR (si la versión instalada lo soporta en el
# constructor) como filtro explícito en _ocr_pagina (defensa en profundidad,
# no depende de que el paquete lo respete igual en todas las versiones).
_OCR_DROP_SCORE = 0.55

# El parámetro cambió de nombre entre versiones: 'drop_score' en PaddleOCR 2.x,
# 'text_rec_score_thresh' en 3.x. Se prueban por orden y se usa el primero que
# el constructor acepte.
_NOMBRES_UMBRAL = ('text_rec_score_thresh', 'drop_score')

# _sin_onednn se inicializa arriba desde la variable de entorno. El reintento
# dinámico de _inferir() puede activarlo a True si se detecta el fallo en runtime
# (caso local sin la variable activada).

# Resolución de render de páginas a imagen para OCR. 300 DPI local, 200 en
# Docker donde PaddleOCR sin oneDNN es más lento. Reducir de 300→200 acelera
# la inferencia ~2x sin pérdida significativa de precisión en facturas.
_OCR_DPI = int(os.environ.get('OCR_DPI', '200'))


def _construir_ocr(enable_mkldnn: bool | None = None):
    """Crea la instancia de PaddleOCR adaptándose a la versión instalada.

    Se desactivan los 3 modelos de preprocesamiento de documento que PaddleOCR 3.x
    carga por defecto (orientación de documento, enderezado UVDoc, orientación de
    líneas de texto). Estas etapas son innecesarias para facturas —PDFs escaneados
    correctamente orientados— y en Docker sin oneDNN causan lentitud extrema
    (minutos por página) o cuelgues. Reducir de 5 modelos a 2 (det+rec).
    """
    from paddleocr import PaddleOCR

    base = {
        'lang': 'es',
        'use_doc_orientation_classify': False,
        'use_doc_unwarping': False,
        'use_textline_orientation': False,
    }
    if enable_mkldnn is not None:
        base['enable_mkldnn'] = enable_mkldnn

    for nombre in _NOMBRES_UMBRAL:
        try:
            return PaddleOCR(**base, **{nombre: _OCR_DROP_SCORE})
        except (TypeError, ValueError):
            # Esta versión no conoce ese nombre de parámetro. No es un fallo:
            # el filtro manual de _ocr_pagina cubre el mismo objetivo.
            continue

    logger.warning("PaddleOCR no acepta ningún umbral de confianza en el constructor; "
                   "se aplica solo el filtro manual (QW3).")
    return PaddleOCR(**base)


def _get_ocr():
    """
    Devuelve la instancia singleton de PaddleOCR.
    DEBE llamarse siempre con _ocr_lock adquirido (lo garantiza _ocr_pagina).
    El patrón double-checked locking es seguro aquí porque _ocr_lock ya está
    sostenido por el llamador.
    """
    global _paddle_ocr
    if _paddle_ocr is None:
        logger.info("Inicializando PaddleOCR (primer uso)...")
        _paddle_ocr = _construir_ocr(enable_mkldnn=False if _sin_onednn else None)
    return _paddle_ocr


def extract_pdf_text(pdf_path: str) -> tuple[str, float]:
    """
    Extrae el texto de todas las páginas de un PDF.

    Estrategia:
      1. pdfplumber: extracción directa (PDF con capa de texto).
         Confianza asignada: 0.95 (texto digital, sin ambigüedad).
      2. PaddleOCR: renderiza la página como imagen y aplica OCR.
         Confianza: media de los scores por token que devuelve PaddleOCR.

    Returns
    -------
    texto : str
        Todo el texto extraído, páginas separadas por newline.
    confianza_media : float
        Puntuación media de confianza en [0, 1].
    """
    texto_total = ""
    scores: list[float] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for num_pagina, pagina in enumerate(pdf.pages):
                try:
                    texto_directo = pagina.extract_text()
                    if texto_directo and len(texto_directo.strip()) > 30:
                        texto_total += texto_directo + "\n"
                        # Texto digital → confianza alta
                        scores.append(0.95)
                    else:
                        logger.info(f"  → Pág. {num_pagina + 1}: usando PaddleOCR")
                        texto_ocr, scores_ocr = _ocr_pagina(pagina)
                        texto_total += texto_ocr
                        scores.extend(scores_ocr)
                except Exception as e:
                    logger.warning(f"  ⚠️ Error pág. {num_pagina + 1}: {e}")
    except Exception as e:
        logger.error(f"Error abriendo PDF: {e}")
        raise

    confianza = float(np.mean(scores)) if scores else 0.0
    return texto_total, round(confianza, 3)


def _lineas_de_resultado(resultado) -> list[tuple[str, float]]:
    """
    Normaliza la salida de PaddleOCR a [(texto, score)].

    Hay dos formatos según la versión instalada:
      - 2.x: [[ [poly, (texto, score)], ... ]]
      - 3.x: [OCRResult]  — objeto tipo dict con 'rec_texts' y 'rec_scores'
    """
    if not resultado:
        return []

    primero = resultado[0]

    # Formato 3.x: mapeo con listas paralelas de textos y scores.
    if hasattr(primero, 'get') and 'rec_texts' in primero:
        textos = list(primero.get('rec_texts') or [])
        scores = list(primero.get('rec_scores') or [])
        # Si faltasen scores, no se descarta el texto: se le asigna 1.0 para no
        # perder contenido legible por un dato de calidad ausente.
        scores += [1.0] * (len(textos) - len(scores))
        return list(zip(textos, (float(s) for s in scores)))

    # Formato 2.x
    lineas = []
    for linea in (primero or []):
        try:
            lineas.append((linea[1][0], float(linea[1][1])))
        except (IndexError, TypeError, ValueError):
            continue
    return lineas


def _inferir(img_array):
    """
    Ejecuta la inferencia reconstruyendo sin oneDNN si el backend aborta.

    Debe llamarse con _ocr_lock adquirido.
    """
    global _paddle_ocr, _sin_onednn

    motor = _get_ocr()
    metodo = motor.predict if hasattr(motor, 'predict') else motor.ocr
    try:
        return metodo(img_array)
    except NotImplementedError as e:
        # Backend oneDNN incompatible con el modelo. Reintento único con oneDNN
        # desactivado; a partir de aquí la instancia queda fijada en ese modo.
        if _sin_onednn:
            raise
        logger.warning(f"PaddleOCR abortó con oneDNN ({e}); reintentando sin oneDNN.")
        _sin_onednn = True
        _paddle_ocr = None
        motor = _get_ocr()
        metodo = motor.predict if hasattr(motor, 'predict') else motor.ocr
        return metodo(img_array)


def _ocr_pagina(pagina) -> tuple[str, list[float]]:
    """
    Aplica PaddleOCR a una página y devuelve (texto, lista_scores).

    El lock _ocr_lock se adquiere aquí, garantizando que:
      1. La inicialización lazy es atómica (un solo hilo crea la instancia).
      2. La llamada a .ocr() es exclusiva (PaddleOCR no es thread-safe).
    El impacto en rendimiento es nulo para la ruta normal (pdfplumber con
    PDFs digitales); solo afecta a PDFs escaneados que requieren OCR.
    """
    texto = ""
    scores: list[float] = []
    try:
        # Preparar imagen ANTES de adquirir el lock (pdfplumber es thread-safe)
        imagen = pagina.to_image(resolution=_OCR_DPI)
        img_array = np.array(imagen.original)

        with _ocr_lock:
            resultado = _inferir(img_array)

        lineas_ocr = _lineas_de_resultado(resultado)
        if lineas_ocr:
            lineas = []
            descartados = 0
            for texto_linea, score_linea in lineas_ocr:
                if score_linea < _OCR_DROP_SCORE:   # QW3
                    descartados += 1
                    continue
                lineas.append(texto_linea)
                scores.append(score_linea)
            texto = "\n".join(lineas) + "\n"
            if descartados:
                logger.debug(f"  [QW3] {descartados} token(s) OCR descartados por baja confianza "
                             f"(<{_OCR_DROP_SCORE})")
    except Exception as e:
        # Antes era warning: un OCR caído dejaba el PDF en 0 caracteres y el
        # documento acababa clasificado como "sin plantilla" sin rastro del
        # motivo real. Se registra como error para que no pase inadvertido.
        logger.error(f"  PaddleOCR falló en una página: {type(e).__name__}: {e}")
    return texto, scores


def extract_pdf_zone_text(pdf_path: str, comercializadora: str | None,
                          pais: str = 'ES') -> dict[str, str]:
    """
    Extrae texto por zonas de la PRIMERA página para campos críticos del OCR.
    Se usa como refuerzo para comercializadoras frecuentes.
    """
    if not comercializadora:
        return {}
    zonas = _zonas_yaml((pais or 'ES').upper(), comercializadora)
    if not zonas:
        return {}

    textos: dict[str, str] = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return {}
            page = pdf.pages[0]
            w, h = page.width, page.height

            for campo, (rx0, rtop, rx1, rbottom) in zonas.items():
                try:
                    bbox = (rx0 * w, rtop * h, rx1 * w, rbottom * h)
                    texto = page.crop(bbox).extract_text() or ""
                    textos[campo] = texto.strip()
                except Exception:
                    textos[campo] = ""
    except Exception as exc:
        logger.debug(f"[OCR zonas] No se pudieron extraer zonas de {pdf_path}: {exc}")
        return {}
    return textos
