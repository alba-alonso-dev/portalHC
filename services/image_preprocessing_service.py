"""
Preprocesado de imagen antes de PaddleOCR: deskew, binarización adaptativa y
reducción de ruido. Solo se aplica en la ruta PaddleOCR (páginas sin capa de
texto digital); pdfplumber no lo necesita.

Requiere opencv-python-headless. Si no está instalado, el preprocesado se
desactiva automáticamente y se usa la imagen original — nunca debe romper
el pipeline de OCR, es una mejora, no una dependencia dura.
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    _CV2_DISPONIBLE = True
except ImportError:
    _CV2_DISPONIBLE = False
    logger.warning(
        "[image_preprocessing_service] opencv no instalado; "
        "preprocesado de imagen desactivado (fallback: imagen original)."
    )


def preprocesar_para_ocr(img_array: np.ndarray) -> np.ndarray:
    """
    Aplica deskew + reducción de ruido + binarización adaptativa sobre una
    imagen (array numpy RGB, tal como la produce pagina.to_image().original).
    Devuelve la imagen preprocesada, o la original si opencv no está
    disponible o si el preprocesado falla.
    """
    if not _CV2_DISPONIBLE:
        return img_array
    try:
        gris = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        gris = _deskew(gris)
        gris = cv2.fastNlMeansDenoising(gris, h=10)
        binaria = cv2.adaptiveThreshold(
            gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
        )
        return cv2.cvtColor(binaria, cv2.COLOR_GRAY2RGB)
    except Exception as exc:
        logger.warning(f"[image_preprocessing_service] Fallo en preprocesado, "
                        f"se usa imagen original: {exc}")
        return img_array


def _deskew(imagen_gris: np.ndarray) -> np.ndarray:
    """
    Corrige inclinaciones de pocos grados (escaneos ligeramente torcidos).
    Complementa (no sustituye) a use_doc_orientation_classify de PaddleOCR,
    que corrige 0/90/180/270° pero no ángulos intermedios.
    """
    _, binaria = cv2.threshold(imagen_gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binaria > 0))
    if coords.shape[0] < 50:
        return imagen_gris  # muy poco texto detectado, no fiable estimar ángulo
    angulo = cv2.minAreaRect(coords)[-1]
    angulo = -(90 + angulo) if angulo < -45 else -angulo
    if abs(angulo) < 0.3:
        return imagen_gris  # ya está prácticamente recta
    h, w = imagen_gris.shape[:2]
    matriz = cv2.getRotationMatrix2D((w // 2, h // 2), angulo, 1.0)
    return cv2.warpAffine(imagen_gris, matriz, (w, h),
                           flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)