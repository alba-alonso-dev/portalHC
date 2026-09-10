"""
Blueprint: estimaciones y calidad de datos — Fase 3.

Endpoints:
  GET  /api/estimaciones/gaps             — detectar periodos faltantes
  GET  /api/estimaciones/periodos         — listar todos los periodos faltantes
  POST /api/estimaciones                  — crear estimación
  GET  /api/estimaciones                  — listar estimaciones
  DELETE /api/estimaciones/<id>           — rechazar estimación
  POST /api/estimaciones/<id>/sustituir   — vincular factura real
  GET  /api/calidad                       — métricas globales de calidad
  GET  /api/calidad/sedes                 — métricas por sede
  GET  /api/calidad/sede                  — calidad de una sede concreta
"""

import logging
from flask import Blueprint, jsonify, request
from routes._helpers import server_error, bad_request
from services.estimacion_service import (
    crear_estimacion, listar_estimaciones, obtener_estimacion,
    sustituir_por_real, rechazar_estimacion,
    metricas_error, comparativa_real_vs_estimado,
    comparativa_metodos, resolver_hueco_pequeno,
    metricas_precision_por_metodo,   # Fase 6
    METODOS_DISPONIBLES,
)
from services.gaps_service import (
    detectar_periodos_faltantes, listar_periodos_faltantes,
    resumen_calidad_global, calidad_por_sede, calcular_calidad_sede
)

logger = logging.getLogger(__name__)
estimaciones_bp = Blueprint('estimaciones', __name__)

_METODOS = METODOS_DISPONIBLES


# ── Gaps ──────────────────────────────────────────────────────────────────────

@estimaciones_bp.route('/api/estimaciones/gaps', methods=['GET'])
def detectar_gaps():
    """
    Detecta y registra periodos faltantes.
    Query params: pais, sede, anio, tipo_energia
    """
    try:
        faltantes = detectar_periodos_faltantes(
            pais=request.args.get('pais'),
            sede=request.args.get('sede'),
            anio=request.args.get('anio'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, 'faltantes': faltantes, 'total': len(faltantes)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones detectar gaps")


@estimaciones_bp.route('/api/estimaciones/periodos', methods=['GET'])
def listar_periodos():
    """Lista periodos faltantes ya registrados (sin re-detectar)."""
    try:
        periodos = listar_periodos_faltantes(
            pais=request.args.get('pais'),
            sede=request.args.get('sede'),
            anio=request.args.get('anio'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
            solo_faltantes=request.args.get('solo_faltantes', '0') == '1',
        )
        return jsonify({'exito': True, 'periodos': periodos, 'total': len(periodos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones listar periodos")

@estimaciones_bp.route('/api/estimaciones', methods=['GET'])
def listar():
    try:
        estimaciones = listar_estimaciones(
            pais=request.args.get('pais'),
            sede=request.args.get('sede'),
            anio=request.args.get('anio'),
            estado=request.args.get('estado'),
        )
        return jsonify({'exito': True, 'estimaciones': estimaciones,
                        'total': len(estimaciones)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones listar")


@estimaciones_bp.route('/api/estimaciones', methods=['POST'])
def crear():
    """
    Body JSON requerido: pais, sede, mes (YYYY-MM), metodo
    Opcionales: tipo_energia, valor_manual, notas, creado_por
    """
    data = request.get_json(force=True) or {}
    for campo in ('pais', 'sede', 'mes', 'metodo'):
        if not data.get(campo):
            return jsonify({'exito': False, 'error': f"Campo obligatorio: {campo}"}), 400
    if data['metodo'] not in _METODOS:
        return jsonify({'exito': False,
                        'error': f"Método inválido. Opciones: {sorted(_METODOS)}"}), 400
    try:
        est = crear_estimacion(
            pais=data['pais'],
            sede=data['sede'],
            mes=data['mes'],
            metodo=data['metodo'],
            valor_manual=data.get('valor_manual'),
            tipo_energia=data.get('tipo_energia', 'electricidad'),
            notas=data.get('notas'),
            creado_por=data.get('creado_por', 'usuario'),
        )
        return jsonify({'exito': True, 'estimacion': est}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Estimaciones crear")
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones crear")


@estimaciones_bp.route('/api/estimaciones/<int:est_id>', methods=['DELETE'])
def rechazar(est_id):
    try:
        est = rechazar_estimacion(est_id)
        if not est:
            return jsonify({'exito': False, 'error': 'Estimación no encontrada'}), 404
        return jsonify({'exito': True, 'estimacion': est}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones rechazar")


@estimaciones_bp.route('/api/estimaciones/<int:est_id>/sustituir', methods=['POST'])
def sustituir(est_id):
    """
    Vincula una factura real a una estimación existente.
    Body JSON: { "factura_real_id": <int> }
    """
    data = request.get_json(force=True) or {}
    if not data.get('factura_real_id'):
        return jsonify({'exito': False, 'error': 'factura_real_id requerido'}), 400
    try:
        est = sustituir_por_real(est_id, int(data['factura_real_id']))
        return jsonify({'exito': True, 'estimacion': est}), 200
    except ValueError as exc:
        return bad_request(exc, contexto="Estimaciones sustituir")
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones sustituir")


# ── Calidad de datos ──────────────────────────────────────────────────────────

@estimaciones_bp.route('/api/calidad', methods=['GET'])
def calidad_global():
    """Métricas globales de calidad para el dashboard. Query params: anio, tipo_energia."""
    try:
        metrics = resumen_calidad_global(
            anio=request.args.get('anio'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, **metrics}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones calidad global")


@estimaciones_bp.route('/api/calidad/sedes', methods=['GET'])
def calidad_sedes():
    """Indicadores de calidad por sede. Query params: anio, tipo_energia."""
    try:
        sedes = calidad_por_sede(
            anio=request.args.get('anio'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, 'sedes': sedes, 'total': len(sedes)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones calidad sedes")


@estimaciones_bp.route('/api/calidad/sede', methods=['GET'])
def calidad_sede():
    """
    Indicadores de calidad para una sede específica.
    Query params requeridos: pais, sede, anio
    """
    pais = request.args.get('pais', '').upper()
    sede = request.args.get('sede', '')
    anio = request.args.get('anio', '')
    if not pais or not sede or not anio:
        return jsonify({'exito': False,
                        'error': 'pais, sede y anio son obligatorios'}), 400
    try:
        metrics = calcular_calidad_sede(pais, sede, anio,
                                        request.args.get('tipo_energia', 'electricidad'))
        return jsonify({'exito': True, **metrics}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones calidad sede")

@estimaciones_bp.route('/api/estimaciones/metricas-error', methods=['GET'])
def metricas_error_endpoint():
    """
    Métricas de precisión del motor de estimación.
    Basado en estimaciones ya validadas con factura real.
    Query params opcionales: pais, sede, anio
    """
    try:
        datos = metricas_error(
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
            anio=request.args.get('anio') or None,
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones métricas error")


@estimaciones_bp.route('/api/estimaciones/comparativa', methods=['GET'])
def comparativa():
    """
    Comparativa real vs estimado para estimaciones ya sustituidas.
    Query params opcionales: pais, sede, anio
    """
    try:
        datos = comparativa_real_vs_estimado(
            pais=request.args.get('pais') or None,
            sede=request.args.get('sede') or None,
            anio=request.args.get('anio') or None,
        )
        return jsonify({'exito': True, 'comparativa': datos, 'total': len(datos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones comparativa")


# ── Fase 5: nuevos endpoints ──────────────────────────────────────────────────

@estimaciones_bp.route('/api/estimaciones/comparativa-metodos', methods=['GET'])
def comparativa_metodos_endpoint():
    """
    Fase 5: calcula todos los métodos disponibles para un mes y devuelve comparativa.
    Permite al usuario elegir el método más apropiado antes de persistir.
    Query params requeridos: pais, sede, mes (YYYY-MM)
    Query params opcionales: tipo_energia
    """
    pais = request.args.get('pais', '').upper()
    sede = request.args.get('sede', '')
    mes  = request.args.get('mes', '')
    if not pais or not sede or not mes:
        return jsonify({'exito': False, 'error': 'pais, sede y mes son obligatorios'}), 400
    try:
        resultados = comparativa_metodos(
            pais=pais, sede=sede, mes=mes,
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        disponibles = [r for r in resultados if r.get('disponible')]
        return jsonify({
            'exito': True,
            'pais': pais, 'sede': sede, 'mes': mes,
            'metodos': resultados,
            'n_disponibles': len(disponibles),
            'recomendado': disponibles[0]['metodo'] if disponibles else None,
        }), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones comparativa-metodos")


@estimaciones_bp.route('/api/estimaciones/resolver-hueco', methods=['POST'])
def resolver_hueco():
    """
    Fase 5: resuelve automáticamente un hueco pequeño de cobertura.
    Body JSON: { pais, sede, mes, tipo_energia?, umbral_dias?, creado_por? }
    """
    data = request.get_json(force=True) or {}
    for campo in ('pais', 'sede', 'mes'):
        if not data.get(campo):
            return jsonify({'exito': False, 'error': f'Campo obligatorio: {campo}'}), 400
    try:
        est = resolver_hueco_pequeno(
            pais=data['pais'], sede=data['sede'], mes=data['mes'],
            tipo_energia=data.get('tipo_energia', 'electricidad'),
            umbral_dias=int(data.get('umbral_dias', 5)),
            creado_por=data.get('creado_por', 'usuario'),
        )
        if est is None:
            return jsonify({
                'exito': False,
                'error': 'El hueco no es pequeño o ya existen datos para ese mes',
            }), 400
        return jsonify({'exito': True, 'estimacion': est}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Estimaciones resolver-hueco")
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones resolver-hueco")


@estimaciones_bp.route('/api/estimaciones/metricas-precision', methods=['GET'])
def metricas_precision():
    """
    Fase 6: métricas de precisión acumuladas por método de estimación.
    Se actualizan automáticamente con cada reconciliación estimado → real.
    Devuelve MAE (error medio absoluto kWh) y MAPE (% error medio) por método,
    ordenados de mejor a peor precisión.
    """
    try:
        datos = metricas_precision_por_metodo()
        return jsonify({'exito': True, 'metricas': datos, 'total': len(datos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estimaciones métricas precisión")
