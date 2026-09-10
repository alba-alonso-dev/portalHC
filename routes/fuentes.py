"""
Blueprint: gestión de fuentes bibliográficas de factores de emisión — Fase 2.

Endpoints:
  GET  /api/fuentes          — listar fuentes
  POST /api/fuentes          — crear fuente
  GET  /api/fuentes/<id>     — detalle fuente
  PUT  /api/fuentes/<id>     — editar fuente
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error, bad_request
from services.factores_service import listar_fuentes, crear_fuente, editar_fuente
from database.connection import get_db_connection

logger = logging.getLogger(__name__)
fuentes_bp = Blueprint('fuentes', __name__)


@fuentes_bp.route('/api/fuentes', methods=['GET'])
def listar():
    try:
        solo_activas = request.args.get('solo_activas', '1') == '1'
        fuentes = listar_fuentes(solo_activas=solo_activas)
        return jsonify({'exito': True, 'fuentes': fuentes, 'total': len(fuentes)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Fuentes listar")


@fuentes_bp.route('/api/fuentes', methods=['POST'])
def crear():
    """
    Body JSON requerido: codigo, nombre
    Opcionales: organizacion, anio_publicacion, url, notas
    """
    try:
        datos = request.get_json(force=True) or {}
        fuente = crear_fuente(datos)
        return jsonify({'exito': True, 'fuente': fuente}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Fuentes crear")
    except Exception as exc:
        return server_error(exc, contexto="Fuentes crear")


@fuentes_bp.route('/api/fuentes/<int:fuente_id>', methods=['GET'])
def detalle(fuente_id):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM fuentes_emision WHERE id=?", (fuente_id,)).fetchone()
        if not row:
            return jsonify({'exito': False, 'error': 'Fuente no encontrada'}), 404
        return jsonify({'exito': True, 'fuente': dict(row)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Fuentes detalle")


@fuentes_bp.route('/api/fuentes/<int:fuente_id>', methods=['PUT'])
def editar(fuente_id):
    """
    Body JSON con campos a actualizar:
    nombre, organizacion, anio_publicacion, url, notas
    """
    try:
        datos = request.get_json(force=True) or {}
        fuente = editar_fuente(fuente_id, datos)
        return jsonify({'exito': True, 'fuente': fuente}), 200
    except ValueError as exc:
        return bad_request(exc, contexto="Fuentes editar")
    except Exception as exc:
        return server_error(exc, contexto="Fuentes editar")
