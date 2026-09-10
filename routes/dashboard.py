"""
Blueprint: Dashboard Ejecutivo de Sostenibilidad — Fase 4 / Fase 6.

Endpoints:
  GET /api/dashboard/resumen      — KPIs globales (cabecera del dashboard)
  GET /api/dashboard/emisiones    — desglose completo de emisiones
  GET /api/dashboard/cobertura    — indicadores de cobertura de datos
  GET /api/dashboard/calidad      — indicadores de calidad
  GET /api/dashboard/facturacion  — métricas de gestión de facturas
  GET /api/dashboard/evolucion    — serie temporal mensual (para Chart.js)
  GET /api/dashboard/esg          — dashboard ejecutivo ESG con semáforo (Fase 6)
  GET /api/dashboard/proyeccion   — proyección de cierre de ejercicio (Fase 6)

Query params comunes: anio, pais, sede, tipo_energia
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error
from services.dashboard_service import (
    resumen_ejecutivo, kpis_emisiones, kpis_cobertura,
    kpis_calidad, kpis_facturacion, evolucion_mensual,
    dashboard_esg, proyeccion_cierre,   # Fase 6
    calidad_ocr_por_campo,              # QW2
)

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)


def _anio(req) -> str | None:
    return req.args.get('anio') or None


@dashboard_bp.route('/api/dashboard/resumen')
def resumen():
    """
    KPIs globales para la cabecera del dashboard.
    Devuelve emisiones, cobertura, alertas y variación anual.
    """
    try:
        datos = resumen_ejecutivo(anio=_anio(request))
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard resumen")


@dashboard_bp.route('/api/dashboard/emisiones')
def emisiones():
    """
    Desglose de emisiones: total, por país, por sede, por mes, por scope.
    Fase 5: acepta filtros opcionales pais y sede.
    """
    try:
        datos = kpis_emisiones(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard emisiones")


@dashboard_bp.route('/api/dashboard/cobertura')
def cobertura():
    """
    Indicadores de cobertura de datos: % real/estimado/faltante por sede.
    Fase 5: acepta filtros opcionales pais y sede.
    """
    try:
        datos = kpis_cobertura(
            anio=_anio(request),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard cobertura")


@dashboard_bp.route('/api/dashboard/calidad')
def calidad():
    """
    Indicadores de calidad: OCR, duplicados, consumos anómalos, scores por sede.
    Fase 5: acepta filtros opcionales pais y sede.
    """
    try:
        datos = kpis_calidad(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard calidad")


@dashboard_bp.route('/api/dashboard/facturacion')
def facturacion():
    """
    Métricas de gestión: total facturas, revisadas, pendientes, duplicados.
    Fase 5: acepta filtros opcionales pais y sede.
    """
    try:
        datos = kpis_facturacion(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard facturación")


@dashboard_bp.route('/api/dashboard/evolucion')
def evolucion():
    """
    Serie temporal mensual para gráficos Chart.js.
    Incluye año actual, año anterior, real y estimado separados.
    """
    try:
        datos = evolucion_mensual(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard evolución")


@dashboard_bp.route('/api/dashboard/esg')
def esg():
    """
    Dashboard ejecutivo ESG con semáforo global (Fase 6).
    Combina KPIs de emisiones, estado de objetivos, proyección de cierre
    y sedes en riesgo en una sola llamada.
    Query params: anio, pais, sede
    """
    try:
        datos = dashboard_esg(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard ESG")


@dashboard_bp.route('/api/dashboard/proyeccion')
def proyeccion():
    """
    Proyección de cierre del ejercicio actual (Fase 6).
    Devuelve la estimación de emisiones totales al 31 de diciembre.
    Incluye diferencia frente al objetivo si está definido.
    Query params: anio, pais, sede
    """
    try:
        datos = proyeccion_cierre(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard proyección")

@dashboard_bp.route('/api/dashboard/calidad-ocr-campos')
def calidad_ocr_campos():
    """QW2 — Precisión media y % bajo umbral por campo extraído."""
    try:
        datos = calidad_ocr_por_campo(
            anio=_anio(request),
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, 'campos': datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Dashboard calidad OCR por campo")