"""
Blueprint: recálculo de emisiones — Fase 3.

Endpoints:
  GET  /api/recalculo/impacto              — análisis previo sin ejecutar
  POST /api/recalculo/ejecutar             — lanzar recálculo
  GET  /api/recalculo/lotes               — historial de trabajos de recálculo
  GET  /api/recalculo/lote/<id>           — estado de un trabajo concreto
  GET  /api/recalculo/historial/<fid>     — historial de recálculos de una factura
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error
from services.recalculo_service import (
    analizar_impacto, ejecutar_recalculo,
    obtener_historial_recalculos, obtener_lote_recalculo, listar_lotes_recalculo
)

logger = logging.getLogger(__name__)
recalculo_bp = Blueprint('recalculo', __name__)

_ALCANCES_VALIDOS = {'individual', 'sede', 'pais', 'anio', 'completo'}


@recalculo_bp.route('/api/recalculo/impacto', methods=['GET'])
def impacto():
    """
    Calcula el impacto esperado de un recálculo sin modificar la base de datos.
    Query params: alcance, pais, sede, anio, factura_id
    """
    alcance = request.args.get('alcance', 'completo')
    if alcance not in _ALCANCES_VALIDOS:
        return jsonify({'exito': False,
                        'error': f"alcance inválido. Opciones: {_ALCANCES_VALIDOS}"}), 400
    try:
        resultado = analizar_impacto(
            alcance=alcance,
            filtro_pais=request.args.get('pais'),
            filtro_sede=request.args.get('sede'),
            filtro_anio=request.args.get('anio'),
            filtro_factura_id=request.args.get('factura_id', type=int),
        )
        return jsonify({'exito': True, **resultado}), 200
    except Exception as exc:
        return server_error(exc, contexto="Recálculo impacto")


@recalculo_bp.route('/api/recalculo/ejecutar', methods=['POST'])
def ejecutar():
    """
    Lanza el recálculo para el alcance indicado.
    Body JSON:
      alcance   (requerido): 'individual' | 'sede' | 'pais' | 'anio' | 'completo'
      pais, sede, anio, factura_id  (según alcance)
      usuario, motivo  (opcionales)
    """
    data = request.get_json(force=True) or {}
    alcance = data.get('alcance', 'completo')
    if alcance not in _ALCANCES_VALIDOS:
        return jsonify({'exito': False,
                        'error': f"alcance inválido. Opciones: {_ALCANCES_VALIDOS}"}), 400
    try:
        lote_id = ejecutar_recalculo(
            alcance=alcance,
            usuario=data.get('usuario', 'usuario'),
            motivo=data.get('motivo', ''),
            filtro_pais=data.get('pais'),
            filtro_sede=data.get('sede'),
            filtro_anio=data.get('anio'),
            filtro_factura_id=data.get('factura_id'),
        )
        lote = obtener_lote_recalculo(lote_id)
        return jsonify({'exito': True, 'lote_recalculo_id': lote_id, 'lote': lote}), 200
    except Exception as exc:
        return server_error(exc, contexto="Recálculo ejecutar")


@recalculo_bp.route('/api/recalculo/lotes', methods=['GET'])
def listar_lotes():
    try:
        limit = request.args.get('limit', 20, type=int)
        lotes = listar_lotes_recalculo(limit=limit)
        return jsonify({'exito': True, 'lotes': lotes, 'total': len(lotes)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Recálculo listar lotes")


@recalculo_bp.route('/api/recalculo/lote/<lote_id>', methods=['GET'])
def estado_lote(lote_id):
    try:
        lote = obtener_lote_recalculo(lote_id)
        if not lote:
            return jsonify({'exito': False, 'error': 'Lote no encontrado'}), 404
        return jsonify({'exito': True, 'lote': lote}), 200
    except Exception as exc:
        return server_error(exc, contexto="Recálculo estado lote")


@recalculo_bp.route('/api/recalculo/historial/<int:factura_id>', methods=['GET'])
def historial_factura(factura_id):
    try:
        historial = obtener_historial_recalculos(factura_id)
        return jsonify({'exito': True, 'historial': historial, 'total': len(historial)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Recálculo historial factura")
