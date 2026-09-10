"""
Blueprint: Informe GHG Protocol — Fase 4 / Fase 5.

Endpoints:
  GET /api/ghg/informe              — descarga Excel del informe GHG Protocol completo
  GET /api/ghg/preview              — previsualización JSON del informe (sin descargar)
  GET /api/ghg/ranking/sociedades   — ranking de emisiones por sociedad/empresa (Fase 5)

Query params comunes: anio, pais, tipo_energia

El Excel incluye (Fase 5 añade hoja 7):
  Hoja 1: Resumen Ejecutivo
  Hoja 2: Emisiones por Scope (1/2/3)
  Hoja 3: Metodología (factores, fuentes, versiones)
  Hoja 4: Calidad del Dato
  Hoja 5: Trazabilidad
  Hoja 6: Detalle Facturas
  Hoja 7: Emisiones por Sociedad (Fase 5)
"""

import logging
from flask import Blueprint, jsonify, request, send_file
import io

from routes._helpers import server_error
from services.ghg_report_service import (
    generar_informe_excel,
    preview_informe,
    _seccion_por_sociedad,
    _filtros_base,
)
from services.audit_service import registrar_evento
from database.connection import get_db_connection

logger = logging.getLogger(__name__)
ghg_report_bp = Blueprint('ghg_report', __name__)


@ghg_report_bp.route('/api/ghg/informe')
def descargar_informe():
    """
    Genera y descarga el informe GHG Protocol en formato Excel.
    Query params: anio (def. año actual), pais (opcional), tipo_energia (opcional)
    """
    anio         = request.args.get('anio') or None
    pais         = request.args.get('pais') or None
    tipo_energia = request.args.get('tipo_energia') or None

    try:
        excel_bytes, nombre_archivo = generar_informe_excel(
            anio=anio, pais=pais, tipo_energia=tipo_energia
        )

        # Registrar en audit log
        try:
            registrar_evento(
                accion='exportacion_ghg_excel',
                entidad='informe_ghg',
                detalle={'anio': anio, 'pais': pais, 'tipo_energia': tipo_energia,
                         'archivo': nombre_archivo},
            )
        except Exception:
            pass  # No bloquear la descarga si el audit falla

        return send_file(
            io.BytesIO(excel_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=nombre_archivo,
        )
    except Exception as exc:
        return server_error(exc, contexto="GHG informe")


@ghg_report_bp.route('/api/ghg/preview')
def preview():
    """
    Devuelve los datos del informe en JSON para previsualización.
    Permite construir vistas previas sin descargar el Excel.
    """
    anio         = request.args.get('anio') or None
    pais         = request.args.get('pais') or None
    tipo_energia = request.args.get('tipo_energia') or None

    try:
        datos = preview_informe(anio=anio, pais=pais, tipo_energia=tipo_energia)
        return jsonify({'exito': True, 'informe': datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="GHG preview")


@ghg_report_bp.route('/api/ghg/ranking/sociedades')
def ranking_sociedades():
    """
    Ranking de emisiones por sociedad/empresa (Fase 5).
    Query params: anio (def. año actual), pais (opcional), tipo_energia (opcional)
    """
    anio         = request.args.get('anio') or None
    pais         = request.args.get('pais') or None
    tipo_energia = request.args.get('tipo_energia') or None

    from datetime import date as _date
    anio = anio or str(_date.today().year)

    try:
        with get_db_connection() as conn:
            ranking = _seccion_por_sociedad(conn, anio, pais, tipo_energia)
        return jsonify({
            'exito': True,
            'anio': anio,
            'pais': pais,
            'tipo_energia': tipo_energia,
            'ranking': ranking,
            'n_sociedades': len(ranking),
        }), 200
    except Exception as exc:
        return server_error(exc, contexto="GHG ranking sociedades")
