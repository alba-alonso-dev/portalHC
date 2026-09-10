"""
Blueprint: Sistema de Alertas Automáticas — Fase 4.

Endpoints:
  POST /api/alertas/generar           — genera alertas automáticas (trigger manual)
  GET  /api/alertas                   — lista todas las alertas (filtros: estado, severidad, tipo)
  GET  /api/alertas/pendientes        — alertas pendientes, ordenadas por severidad
  GET  /api/alertas/resueltas         — alertas resueltas
  GET  /api/alertas/resumen           — contadores por estado y severidad
  POST /api/alertas/<id>/resolver     — marcar alerta como resuelta
  POST /api/alertas/<id>/ignorar      — marcar alerta como ignorada
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error
from services.alertas_service import (
    generar_alertas_automaticas, listar_alertas,
    resolver_alerta, ignorar_alerta, resumen_alertas,
)

logger = logging.getLogger(__name__)
alertas_bp = Blueprint('alertas', __name__)


@alertas_bp.route('/api/alertas/generar', methods=['POST'])
def generar():
    """
    Dispara el análisis automático de alertas.
    Útil para pruebas o para forzar una actualización sin esperar al cron.
    """
    try:
        resultado = generar_alertas_automaticas()
        return jsonify({'exito': True, **resultado}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas generar")


@alertas_bp.route('/api/alertas')
def listar():
    """
    Lista todas las alertas.
    Query params: estado, severidad, tipo, pais, sede
    """
    try:
        alertas = listar_alertas(
            estado=request.args.get('estado') or None,
            severidad=request.args.get('severidad') or None,
            tipo=request.args.get('tipo') or None,
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
            limit=int(request.args.get('limit', 200)),
        )
        return jsonify({'exito': True, 'alertas': alertas, 'total': len(alertas)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas listar")


@alertas_bp.route('/api/alertas/pendientes')
def pendientes():
    """Alertas pendientes ordenadas por severidad (crítica → media → informativa)."""
    try:
        alertas = listar_alertas(estado='pendiente',
                                  severidad=request.args.get('severidad') or None,
                                  tipo=request.args.get('tipo') or None,
                                  pais=request.args.get('pais') or None)
        return jsonify({'exito': True, 'alertas': alertas, 'total': len(alertas)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas pendientes")
def resueltas():
    """Alertas ya resueltas o ignoradas."""
    try:
        todas = (
            listar_alertas(estado='resuelta') +
            listar_alertas(estado='ignorada')
        )
        todas.sort(key=lambda x: x.get('fecha_resolucion') or '', reverse=True)
        return jsonify({'exito': True, 'alertas': todas, 'total': len(todas)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas resueltas")
def resumen():
    """Contadores de alertas por estado y severidad para el dashboard."""
    try:
        datos = resumen_alertas()
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas resumen")


@alertas_bp.route('/api/alertas/<int:alerta_id>/resolver', methods=['POST'])
def resolver(alerta_id: int):
    """
    Marca una alerta como resuelta.
    Body JSON opcional: { "notas": "...", "resuelta_por": "..." }
    """
    data = request.get_json(silent=True) or {}
    try:
        alerta = resolver_alerta(
            alerta_id,
            resuelta_por=data.get('resuelta_por', 'usuario'),
            notas=data.get('notas'),
        )
        if not alerta:
            return jsonify({'exito': False, 'error': 'Alerta no encontrada o ya resuelta'}), 404
        return jsonify({'exito': True, 'alerta': alerta}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas resolver")


@alertas_bp.route('/api/alertas/<int:alerta_id>/ignorar', methods=['POST'])
def ignorar(alerta_id: int):
    """Marca una alerta como ignorada."""
    data = request.get_json(silent=True) or {}
    try:
        alerta = ignorar_alerta(alerta_id, resuelta_por=data.get('resuelta_por', 'usuario'))
        if not alerta:
            return jsonify({'exito': False, 'error': 'Alerta no encontrada'}), 404
        return jsonify({'exito': True, 'alerta': alerta}), 200
    except Exception as exc:
        return server_error(exc, contexto="Alertas ignorar")
