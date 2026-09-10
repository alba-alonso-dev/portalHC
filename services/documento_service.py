"""
Capa de abstracción documental — patrón Strategy (Prioridad 1).

Implementaciones disponibles:
  LocalDocumentoStorage  — almacenamiento en disco local (implementación actual).
  SharePointDocumentoStorage — esqueleto para Fase 4 (Microsoft Graph API).

Fase 5 — Organización en subcarpetas:
  Los PDFs se organizan automáticamente en:
    uploads/{YYYY}/{PAIS}/{SEDE}/{archivo}
  donde YYYY se extrae del nombre del archivo o de la fecha actual.
  La carpeta_relativa queda registrada para facilitar la localización y
  la futura migración a SharePoint.

Para añadir SharePoint en Fase 6:
  1. Implementar SharePointDocumentoStorage con el cliente de Graph API.
  2. Establecer DOCUMENTO_STORAGE=sharepoint en variables de entorno (.env).
  3. El resto del código (routes, services) NO cambia.

Uso:
    from services.documento_service import get_documento_storage

    storage = get_documento_storage()
    doc_info = storage.guardar(archivo, nombre_original, pais, sede)
    # doc_info: {archivo_nombre, archivo_ruta, carpeta_relativa,
    #            external_source, external_doc_id, external_doc_url,
    #            sha256, fuente_documento_id}
"""

import hashlib
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime

from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


# ── Interfaz abstracta ────────────────────────────────────────────────────────

class DocumentoStorage(ABC):
    """
    Contrato para almacenamiento de documentos (PDFs de facturas).
    """

    @abstractmethod
    def guardar(self, archivo, nombre_original: str, pais: str, sede: str) -> dict:
        """
        Persiste el archivo y devuelve metadatos de almacenamiento.

        Returns
        -------
        dict con claves:
          archivo_nombre      : str        — nombre original del archivo
          archivo_ruta        : str | None — ruta local para OCR (None si es remoto)
          carpeta_relativa    : str | None — ruta relativa dentro de uploads/ (Fase 5)
          external_source     : str        — 'local' | 'sharepoint' | 'api'
          external_doc_id     : str | None — ID en sistema externo
          external_doc_url    : str | None — URL directa al documento
          sha256              : str        — hex digest SHA-256 del contenido
          fuente_documento_id : int | None — FK a fuentes_documentos(id)
        """

    @abstractmethod
    def resolver_acceso(self, factura: dict) -> dict:
        """
        Indica cómo servir el documento al usuario dado el registro de la factura.

        Returns
        -------
        dict con claves:
          tipo  : 'local' | 'redirect' | 'no_disponible'
          valor : ruta local (str) si tipo='local', URL (str) si tipo='redirect'
        """

    @abstractmethod
    def eliminar(self, factura: dict) -> bool:
        """Elimina el documento del almacenamiento. Best-effort."""


# ── Implementación local ──────────────────────────────────────────────────────

class LocalDocumentoStorage(DocumentoStorage):
    """
    Almacenamiento en el sistema de archivos local.

    Fase 5: Los PDFs se organizan en subcarpetas:
      uploads/{YYYY}/{PAIS}/{SEDE}/{timestamp}_{nombre_seguro}

    El año YYYY se extrae de:
      1. El nombre del archivo si contiene un año (2020-2030).
      2. La fecha actual como fallback.

    El SHA-256 se calcula del contenido en memoria antes de escribir
    a disco, evitando una segunda lectura.
    """

    def __init__(self, upload_folder: str):
        self.upload_folder = upload_folder
        os.makedirs(upload_folder, exist_ok=True)

    def _extraer_anio_nombre(self, nombre: str) -> str:
        """Extrae el año del nombre del archivo (ej. 'factura_2025_01.pdf' → '2025')."""
        m = re.search(r'\b(20[12]\d)\b', nombre)
        return m.group(1) if m else datetime.now().strftime('%Y')

    def guardar(self, archivo, nombre_original: str, pais: str, sede: str) -> dict:
        """Guarda el PDF en subcarpeta organizada y devuelve metadatos."""
        anio = self._extraer_anio_nombre(nombre_original)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_seg = secure_filename(nombre_original)
        nombre_guardado = f"{ts}_{nombre_seg}"

        # Fase 5: subcarpeta YYYY/PAIS/SEDE/
        # Subcarpeta PAIS/SEDE/YYYY/
        sede_seg = re.sub(r'[^\w\-]', '_', sede)[:30]
        subcarpeta = os.path.join(pais.upper(), sede_seg, anio)
        carpeta_abs = os.path.join(self.upload_folder, subcarpeta)
        os.makedirs(carpeta_abs, exist_ok=True)

        ruta = os.path.join(carpeta_abs, nombre_guardado)
        carpeta_relativa = os.path.join(subcarpeta, nombre_guardado)

        # Leer contenido → calcular hash → escribir a disco (una sola lectura)
        if hasattr(archivo, 'read'):
            contenido = archivo.read()
        elif isinstance(archivo, (bytes, bytearray)):
            contenido = bytes(archivo)
        else:
            raise TypeError(f"Tipo de archivo no soportado para guardar: {type(archivo)}")

        sha256 = hashlib.sha256(contenido).hexdigest()

        with open(ruta, 'wb') as f:
            f.write(contenido)

        logger.debug(f"[LocalStorage] Guardado: {carpeta_relativa}  sha256={sha256[:16]}...")

        return {
            'archivo_nombre':      nombre_original,
            'archivo_ruta':        ruta,
            'carpeta_relativa':    carpeta_relativa,
            'external_source':     'local',
            'external_doc_id':     None,
            'external_doc_url':    None,
            'sha256':              sha256,
            'fuente_documento_id': 1,
        }

    def resolver_acceso(self, factura: dict) -> dict:
        """Devuelve la ruta local si el archivo existe en disco."""
        ruta = factura.get('archivo_ruta')
        if ruta and os.path.exists(ruta):
            return {'tipo': 'local', 'valor': ruta}
        return {'tipo': 'no_disponible', 'valor': None}

    def eliminar(self, factura: dict) -> bool:
        ruta = factura.get('archivo_ruta')
        if not ruta:
            return False
        try:
            if os.path.exists(ruta):
                os.remove(ruta)
                logger.info(f"[LocalStorage] Eliminado: {ruta}")
                # Limpiar carpeta vacía (Fase 5)
                carpeta = os.path.dirname(ruta)
                try:
                    if not os.listdir(carpeta):
                        os.rmdir(carpeta)
                except OSError:
                    pass
            return True
        except Exception as exc:
            logger.warning(f"[LocalStorage] No se pudo eliminar {ruta}: {exc}")
            return False


# ── Placeholder para SharePoint (Fase 6+) ─────────────────────────────────────

class SharePointDocumentoStorage(DocumentoStorage):
    """
    FASE 6 — Implementación con Microsoft Graph API.

    Esqueleto para guiar la implementación futura.
    Activar estableciendo DOCUMENTO_STORAGE=sharepoint en variables de entorno.
    """

    def guardar(self, archivo, nombre_original: str, pais: str, sede: str) -> dict:
        raise NotImplementedError(
            "SharePointDocumentoStorage no implementado. "
            "Ver documentación de Fase 6 para integración con Microsoft Graph API."
        )

    def resolver_acceso(self, factura: dict) -> dict:
        url = factura.get('external_doc_url')
        if url:
            return {'tipo': 'redirect', 'valor': url}
        return {'tipo': 'no_disponible', 'valor': None}

    def eliminar(self, factura: dict) -> bool:
        raise NotImplementedError("SharePointDocumentoStorage no implementado.")


# ── Factory (singleton) ───────────────────────────────────────────────────────

_storage_instance: DocumentoStorage | None = None


def get_documento_storage() -> DocumentoStorage:
    """
    Devuelve la implementación activa de DocumentoStorage (singleton).

    Selección por variable de entorno DOCUMENTO_STORAGE:
      'local'      → LocalDocumentoStorage (por defecto)
      'sharepoint' → SharePointDocumentoStorage (Fase 6+)
    """
    global _storage_instance
    if _storage_instance is None:
        import config
        storage_type = os.getenv('DOCUMENTO_STORAGE', 'local').lower()
        if storage_type == 'sharepoint':
            _storage_instance = SharePointDocumentoStorage()
            logger.info("[DocumentoStorage] Usando SharePointDocumentoStorage")
        else:
            _storage_instance = LocalDocumentoStorage(config.UPLOAD_FOLDER)
            logger.info(
                f"[DocumentoStorage] Usando LocalDocumentoStorage: {config.UPLOAD_FOLDER}"
            )
    return _storage_instance


def _reset_storage():
    """Solo para tests. Fuerza reinicialización del singleton."""
    global _storage_instance
    _storage_instance = None


# ── Utilidades de índice (Fase 5) ─────────────────────────────────────────────

def listar_documentos_por_ejercicio(ejercicio: str = None,
                                     pais: str = None,
                                     sede: str = None) -> list[dict]:
    """
    Lista los documentos indexados, filtrando por ejercicio/país/sede.
    Permite identificar rápidamente qué facturas están disponibles y qué períodos faltan.
    """
    from database.connection import get_db_connection
    cond, params = [], []
    if ejercicio:
        cond.append("ejercicio = ?"); params.append(ejercicio)
    if pais:
        cond.append("pais = ?"); params.append(pais.upper())
    if sede:
        cond.append("sede = ?"); params.append(sede)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"""SELECT di.*, f.periodo_inicio, f.periodo_fin, f.consumo_kwh
                FROM documentos_indice di
                LEFT JOIN facturas f ON f.id = di.factura_id
                {where}
                ORDER BY di.ejercicio DESC, di.pais, di.sede, di.mes""",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def cobertura_por_ejercicio(ejercicio: str, pais: str = None,
                             sede: str = None) -> dict:
    """
    Calcula el porcentaje de cobertura documental para un ejercicio.
    Devuelve los meses cubiertos y los que faltan.
    """
    from database.connection import get_db_connection
    meses_anio = [f"{ejercicio}-{m:02d}" for m in range(1, 13)]

    cond = ["substr(f.periodo_inicio, 1, 4) = ?"]
    params: list = [ejercicio]
    if pais:
        cond.append("f.pais = ?"); params.append(pais.upper())
    if sede:
        cond.append("f.sede = ?"); params.append(sede)

    where = "WHERE " + " AND ".join(cond)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT substr(f.periodo_inicio, 1, 7) as mes, f.pais, f.sede
                FROM facturas f
                {where} AND f.fecha_anulacion IS NULL""",
            params
        ).fetchall()

    meses_cubiertos = {r['mes'] for r in rows}
    meses_faltantes = [m for m in meses_anio if m not in meses_cubiertos]

    return {
        'ejercicio':        ejercicio,
        'meses_cubiertos':  sorted(meses_cubiertos),
        'meses_faltantes':  meses_faltantes,
        'cobertura_pct':    round(len(meses_cubiertos) / 12 * 100, 1),
        'total_docs':       len(rows),
    }
