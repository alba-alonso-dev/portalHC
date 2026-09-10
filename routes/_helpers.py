"""
Helpers compartidos para blueprints de Flask.

Centraliza el manejo de errores HTTP para evitar los 217 `str(exc)` que
filtraban detalles internos de SQLite (nombres de tablas, columnas,
constraints) al cliente. En producción se devuelve un mensaje genérico;
el detalle queda en el log del servidor.

Fase 1 — Refactor de bajo riesgo.
"""

import logging
import os

from flask import jsonify

logger = logging.getLogger(__name__)

# En modo debug (FLASK_DEBUG=true) se mantiene el detalle del error para
# facilitar el desarrollo. En producción se devuelve un mensaje genérico.
_DEBUG = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")


def error_response(exc: Exception, status: int = 500,
                   contexto: str = "") -> tuple:
    """
    Genera una respuesta JSON de error estándar.

    En producción (FLASK_DEBUG no activo) devuelve un mensaje genérico para
    no filtrar detalles internos. El detalle completo se registra en el log.

    Args:
        exc: Excepción capturada.
        status: Código HTTP (default 500).
        contexto: Descripción corta del endpoint/operación para el log.

    Returns:
        (jsonify(...), status) — tupla lista para `return` en un endpoint.
    """
    prefix = f"{contexto}: " if contexto else ""
    logger.error(f"{prefix}{exc}", exc_info=True)
    if _DEBUG:
        msg = str(exc)
    else:
        msg = "Error interno del servidor" if status == 500 else "Solicitud inválida"
    return jsonify({"exito": False, "error": msg}), status


def bad_request(exc: Exception, contexto: str = "") -> tuple:
    """Atajo para error 400 (solicitud inválida)."""
    return error_response(exc, status=400, contexto=contexto)


def server_error(exc: Exception, contexto: str = "") -> tuple:
    """Atajo para error 500 (error interno)."""
    return error_response(exc, status=500, contexto=contexto)
