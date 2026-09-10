"""
Blueprint: administración de factores de emisión — Fase 2.

Endpoints:
  GET    /api/factores                          — listar (con filtros)
  POST   /api/factores                          — crear nuevo factor (versión 1)
  GET    /api/factores/<id>                     — detalle de un factor
  PUT    /api/factores/<id>/nueva-version       — crear nueva versión del factor
  PATCH  /api/factores/<id>/metadatos           — editar campos no numéricos
  PATCH  /api/factores/<id>/estado              — activar / desactivar
  GET    /api/factores/<id>/historial           — auditoría de cambios
  GET    /api/factores/<pais>/<anio>/versiones  — todas las versiones del par pais+anio
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error, bad_request
from services.factores_service import (
    listar_factores, obtener_factor_detalle, listar_versiones_pais_anio,
    crear_factor, crear_nueva_version, editar_metadatos,
    cambiar_estado, obtener_historial_factor,
)

logger = logging.getLogger(__name__)
factores_admin_bp = Blueprint('factores_admin', __name__)


# ── Listar ────────────────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores', methods=['GET'])
def listar():
    """
    Parámetros opcionales de query:
      pais, anio, tipo_energia, solo_activos (0|1), solo_versiones_activas (0|1)
    """
    try:
        factores = listar_factores(
            pais=request.args.get('pais'),
            anio=request.args.get('anio'),
            tipo_energia=request.args.get('tipo_energia'),
            solo_activos=request.args.get('solo_activos', '0') == '1',
            solo_versiones_activas=request.args.get('solo_versiones_activas', '0') == '1',
        )
        return jsonify({'exito': True, 'factores': factores, 'total': len(factores)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Factores listar")


# ── Crear ─────────────────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores', methods=['POST'])
def crear():
    """
    Body JSON requerido:
      pais, anio, factor_kg_co2_mwh, fuente_id
    Opcionales:
      tipo_energia, unidad, descripcion, notas, creado_por,
      fecha_vigencia_desde, fecha_vigencia_hasta
    """
    try:
        datos = request.get_json(force=True) or {}
        for campo in ('pais', 'anio', 'factor_kg_co2_mwh', 'fuente_id'):
            if campo not in datos:
                return jsonify({'exito': False, 'error': f"Campo obligatorio: {campo}"}), 400
        factor = crear_factor(datos)
        return jsonify({'exito': True, 'factor': factor}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Factores crear")
    except Exception as exc:
        return server_error(exc, contexto="Factores crear")


# ── Detalle ───────────────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<int:factor_id>', methods=['GET'])
def detalle(factor_id):
    try:
        factor = obtener_factor_detalle(factor_id)
        if not factor:
            return jsonify({'exito': False, 'error': 'Factor no encontrado'}), 404
        return jsonify({'exito': True, 'factor': factor}), 200
    except Exception as exc:
        return server_error(exc, contexto="Factores detalle")


# ── Nueva versión ─────────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<int:factor_id>/nueva-version', methods=['PUT'])
def nueva_version(factor_id):
    """
    Crea una versión inmutable nueva. El valor anterior queda preservado.
    Body JSON requerido: factor_kg_co2_mwh, fuente_id
    """
    try:
        datos = request.get_json(force=True) or {}
        for campo in ('factor_kg_co2_mwh', 'fuente_id'):
            if campo not in datos:
                return jsonify({'exito': False, 'error': f"Campo obligatorio: {campo}"}), 400
        factor = crear_nueva_version(factor_id, datos)
        return jsonify({'exito': True, 'factor': factor}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Factores nueva versión")
    except Exception as exc:
        return server_error(exc, contexto="Factores nueva versión")


# ── Editar metadatos ──────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<int:factor_id>/metadatos', methods=['PATCH'])
def actualizar_metadatos(factor_id):
    """
    Edita campos no numéricos sin crear nueva versión.
    Campos editables: descripcion, notas, fuente_id, unidad,
                      fecha_vigencia_desde, fecha_vigencia_hasta
    """
    try:
        datos = request.get_json(force=True) or {}
        factor = editar_metadatos(factor_id, datos)
        return jsonify({'exito': True, 'factor': factor}), 200
    except ValueError as exc:
        return bad_request(exc, contexto="Factores metadatos")
    except Exception as exc:
        return server_error(exc, contexto="Factores metadatos")


# ── Activar / Desactivar ──────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<int:factor_id>/estado', methods=['PATCH'])
def actualizar_estado(factor_id):
    """
    Body JSON: { "activo": true|false, "usuario": "nombre" }
    """
    try:
        datos = request.get_json(force=True) or {}
        if 'activo' not in datos:
            return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
        factor = cambiar_estado(factor_id, bool(datos['activo']),
                                usuario=datos.get('usuario', 'usuario'))
        return jsonify({'exito': True, 'factor': factor}), 200
    except ValueError as exc:
        return bad_request(exc, contexto="Factores estado")
    except Exception as exc:
        return server_error(exc, contexto="Factores estado")


# ── Historial ─────────────────────────────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<int:factor_id>/historial', methods=['GET'])
def historial(factor_id):
    try:
        eventos = obtener_historial_factor(factor_id)
        return jsonify({'exito': True, 'historial': eventos, 'total': len(eventos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Factores historial")


# ── Versiones de un par país + año ───────────────────────────────────────────

@factores_admin_bp.route('/api/factores/<pais>/<anio>/versiones', methods=['GET'])
def versiones_pais_anio(pais, anio):
    tipo = request.args.get('tipo_energia', 'electricidad')
    try:
        versiones = listar_versiones_pais_anio(pais, anio, tipo)
        return jsonify({'exito': True, 'versiones': versiones, 'total': len(versiones)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Factores versiones pais/año")


# ── Fase 5: estado de actualización de factores ───────────────────────────────

@factores_admin_bp.route('/api/factores/estado-actualizacion', methods=['GET'])
def estado_actualizacion():
    """
    Fase 5: devuelve el estado de actualización de todos los factores activos.
    Indica si están actualizados, necesitan revisión o están desactualizados.
    """
    try:
        from services.alertas_service import estado_factores_emision
        factores_estado = estado_factores_emision()
        desactualizados = [f for f in factores_estado if f['estado_actualizacion'] == 'desactualizado']
        revisar         = [f for f in factores_estado if f['estado_actualizacion'] == 'revisar']
        return jsonify({
            'exito': True,
            'factores': factores_estado,
            'resumen': {
                'total': len(factores_estado),
                'actualizados':    len([f for f in factores_estado if f['estado_actualizacion'] == 'actualizado']),
                'a_revisar':       len(revisar),
                'desactualizados': len(desactualizados),
            },
        }), 200
    except Exception as exc:
        return server_error(exc, contexto="Factores estado actualización")
