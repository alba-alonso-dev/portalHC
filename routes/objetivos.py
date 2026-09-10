"""
Blueprint: Objetivos de Reducción de Emisiones — Fase 6.

Endpoints:
  POST   /api/objetivos               — crear objetivo
  GET    /api/objetivos               — listar objetivos (filtros: anio, pais, sociedad, sede)
  GET    /api/objetivos/<id>          — detalle de un objetivo
  PUT    /api/objetivos/<id>          — actualizar objetivo
  DELETE /api/objetivos/<id>          — desactivar objetivo (soft delete)
  GET    /api/objetivos/<id>/seguimiento — seguimiento real vs objetivo
  GET    /api/objetivos/seguimiento   — seguimiento de todos (filtros opcionales)
  GET    /api/objetivos/resumen-esg   — resumen ESG con semáforo global
"""

import logging
from flask import Blueprint, jsonify, request

from routes._helpers import server_error, bad_request
from services.objetivos_service import (
    crear_objetivo,
    actualizar_objetivo,
    eliminar_objetivo,
    listar_objetivos,
    seguimiento_objetivo,
    seguimiento_todos,
    resumen_esg,
)

logger = logging.getLogger(__name__)
objetivos_bp = Blueprint('objetivos', __name__)


# ── CRUD ─────────────────────────────────────────────────────────────────────

@objetivos_bp.route('/api/objetivos', methods=['POST'])
def crear():
    """Crea un nuevo objetivo de reducción."""
    data = request.get_json(force=True) or {}
    required = ['anio']
    for f in required:
        if f not in data:
            return jsonify({'exito': False, 'error': f"Campo requerido: {f}"}), 400

    try:
        obj = crear_objetivo(
            anio=int(data['anio']),
            pais=data.get('pais') or None,
            sociedad=data.get('sociedad') or None,
            sede=data.get('sede') or None,
            tipo_energia=data.get('tipo_energia', 'electricidad'),
            emisiones_objetivo_tco2e=_float_opt(data.get('emisiones_objetivo_tco2e')),
            pct_reduccion_objetivo=_float_opt(data.get('pct_reduccion_objetivo')),
            anio_base=_int_opt(data.get('anio_base')),
            emisiones_anio_base_tco2e=_float_opt(data.get('emisiones_anio_base_tco2e')),
            observaciones=data.get('observaciones') or None,
        )
        return jsonify({'exito': True, 'objetivo': obj}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Objetivos crear")
    except Exception as exc:
        return server_error(exc, contexto="Objetivos crear")


@objetivos_bp.route('/api/objetivos', methods=['GET'])
def listar():
    """Lista objetivos con filtros opcionales."""
    try:
        objs = listar_objetivos(
            anio=_int_opt(request.args.get('anio')),
            pais=request.args.get('pais') or None,
            sociedad=request.args.get('sociedad') or None,
            sede=request.args.get('sede') or None,
            solo_activos=request.args.get('solo_activos', 'true').lower() != 'false',
        )
        return jsonify({'exito': True, 'objetivos': objs, 'total': len(objs)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Objetivos listar")


@objetivos_bp.route('/api/objetivos/<int:obj_id>', methods=['GET'])
def detalle(obj_id):
    """Devuelve el detalle de un objetivo."""
    try:
        objs = listar_objetivos(solo_activos=False)
        obj = next((o for o in objs if o['id'] == obj_id), None)
        if not obj:
            return jsonify({'exito': False, 'error': 'Objetivo no encontrado'}), 404
        return jsonify({'exito': True, 'objetivo': obj}), 200
    except Exception as exc:
        return server_error(exc, contexto="Objetivos detalle")
def actualizar(obj_id):
    """Actualiza campos de un objetivo existente."""
    data = request.get_json(force=True) or {}
    try:
        obj = actualizar_objetivo(obj_id, **{
            k: v for k, v in data.items()
            if k in {'emisiones_objetivo_tco2e', 'pct_reduccion_objetivo',
                     'anio_base', 'emisiones_anio_base_tco2e', 'observaciones', 'activo'}
        })
        return jsonify({'exito': True, 'objetivo': obj}), 200
    except ValueError as exc:
        return bad_request(exc, contexto="Objetivos actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Objetivos actualizar")


@objetivos_bp.route('/api/objetivos/<int:obj_id>', methods=['DELETE'])
def eliminar(obj_id):
    """Desactiva (soft delete) un objetivo."""
    try:
        eliminar_objetivo(obj_id)
        return jsonify({'exito': True, 'mensaje': f'Objetivo {obj_id} desactivado'}), 200
    except Exception as exc:
        return server_error(exc, contexto="Objetivos eliminar")


# ── Seguimiento ───────────────────────────────────────────────────────────────

@objetivos_bp.route('/api/objetivos/<int:obj_id>/seguimiento', methods=['GET'])
def seguimiento_uno(obj_id):
    """
    Seguimiento de un objetivo concreto.
    Devuelve: real acumulado, desviación, % cumplimiento, semáforo, proyección cierre.
    """
    try:
        seg = seguimiento_objetivo(obj_id)
        return jsonify({'exito': True, **seg}), 200
    except ValueError as exc:
        return jsonify({'exito': False, 'error': str(exc)}), 404
    except Exception as exc:
        return server_error(exc, contexto="Objetivos seguimiento uno")


@objetivos_bp.route('/api/objetivos/seguimiento', methods=['GET'])
def seguimiento_global():
    """
    Seguimiento de todos los objetivos activos.
    Query params: anio, pais, sociedad, sede
    """
    try:
        segs = seguimiento_todos(
            anio=_int_opt(request.args.get('anio')),
            pais=request.args.get('pais') or None,
            sociedad=request.args.get('sociedad') or None,
            sede=request.args.get('sede') or None,
        )
        return jsonify({'exito': True, 'seguimientos': segs, 'total': len(segs)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Objetivos seguimiento global")


@objetivos_bp.route('/api/objetivos/resumen-esg', methods=['GET'])
def resumen():
    """
    Resumen ejecutivo ESG con semáforo global.
    Devuelve: n_verde, n_amarillo, n_rojo, % cumplimiento global, sedes en riesgo.
    """
    try:
        anio = _int_opt(request.args.get('anio'))
        datos = resumen_esg(anio=anio)
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Objetivos resumen ESG")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _float_opt(val) -> float | None:
    try:
        return float(val) if val is not None and val != '' else None
    except (TypeError, ValueError):
        return None


def _int_opt(val) -> int | None:
    try:
        return int(val) if val is not None and val != '' else None
    except (TypeError, ValueError):
        return None
