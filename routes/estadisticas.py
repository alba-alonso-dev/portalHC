"""Blueprint: estadísticas agregadas. Excluye facturas anuladas en todas las métricas.
Fase 5: nuevos endpoints de emisiones por sede, sociedad, rankings y comparativas.
"""

import logging
from flask import Blueprint, jsonify, request
from database.connection import get_db_connection
from routes._helpers import server_error
from services.emisiones_service import (
    emisiones_por_sede, emisiones_por_sociedad,
    emisiones_por_sede_y_sociedad,
    comparativa_sedes, comparativa_sociedades,
)

logger = logging.getLogger(__name__)
estadisticas_bp = Blueprint('estadisticas', __name__)

_WHERE_ACTIVAS = "WHERE fecha_anulacion IS NULL"
_AND_ACTIVAS   = "AND fecha_anulacion IS NULL"


@estadisticas_bp.route('/api/estadisticas')
def obtener_estadisticas():
    try:
        with get_db_connection() as conn:
            total_f   = conn.execute(
                f'SELECT COUNT(*) FROM facturas {_WHERE_ACTIVAS}'
            ).fetchone()[0]
            total_emi = conn.execute(
                f'SELECT COALESCE(SUM(emisiones_tco2e),0) FROM facturas {_WHERE_ACTIVAS}'
            ).fetchone()[0]
            total_con = conn.execute(
                f'SELECT COALESCE(SUM(consumo_mwh),0) FROM facturas {_WHERE_ACTIVAS}'
            ).fetchone()[0]
            n_paises  = conn.execute(
                f'SELECT COUNT(DISTINCT pais) FROM facturas {_WHERE_ACTIVAS}'
            ).fetchone()[0]

            por_pais = [
                {'pais': r[0], 'facturas': r[1],
                 'emisiones': round(r[2] or 0, 4), 'consumo': round(r[3] or 0, 2)}
                for r in conn.execute(
                    f'''SELECT pais, COUNT(*), SUM(emisiones_tco2e), SUM(consumo_mwh)
                        FROM facturas {_WHERE_ACTIVAS}
                        GROUP BY pais ORDER BY SUM(emisiones_tco2e) DESC'''
                )
            ]

        return jsonify({
            'exito':           True,
            'total_facturas':  total_f,
            'total_emisiones': round(total_emi, 4),
            'total_consumo':   round(total_con, 2),
            'num_paises':      n_paises,
            'por_pais':        por_pais,
        }), 200

    except Exception as exc:
        return server_error(exc, contexto="Estadísticas")


# ── Fase 5: rankings y comparativas ──────────────────────────────────────────

@estadisticas_bp.route('/api/estadisticas/emisiones/sedes')
def stats_emisiones_sedes():
    """
    Fase 5: ranking de sedes por emisiones.
    Query params opcionales: anio, pais, tipo_energia
    """
    try:
        datos = emisiones_por_sede(
            anio=request.args.get('anio'),
            pais=request.args.get('pais'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, 'sedes': datos, 'total': len(datos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estadísticas emisiones/sedes")


@estadisticas_bp.route('/api/estadisticas/emisiones/sociedades')
def stats_emisiones_sociedades():
    """
    Fase 5: ranking de sociedades por emisiones.
    Query params opcionales: anio, pais, tipo_energia
    """
    try:
        datos = emisiones_por_sociedad(
            anio=request.args.get('anio'),
            pais=request.args.get('pais'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, 'sociedades': datos, 'total': len(datos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estadísticas emisiones/sociedades")


@estadisticas_bp.route('/api/estadisticas/emisiones/sedes-sociedades')
def stats_emisiones_sedes_sociedades():
    """
    Drill-down sede → sociedades: para cada sede, el desglose de emisiones
    por sociedad titular. Usa el modelo suministros.sociedad_id → sociedades
    con fallback a facturas.sociedad cuando no hay vinculación.

    Query params opcionales: anio, pais, tipo_energia
    """
    try:
        datos = emisiones_por_sede_y_sociedad(
            anio=request.args.get('anio'),
            pais=request.args.get('pais'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, 'sedes': datos, 'total': len(datos)}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estadísticas emisiones/sedes-sociedades")


@estadisticas_bp.route('/api/estadisticas/comparativa/sedes')
def stats_comparativa_sedes():
    """
    Fase 5: comparativa detallada de emisiones entre sedes.
    Query param requerido: anio
    Query params opcionales: pais, tipo_energia
    """
    anio = request.args.get('anio')
    if not anio:
        return jsonify({'exito': False, 'error': 'anio es obligatorio'}), 400
    try:
        datos = comparativa_sedes(
            anio=anio,
            pais=request.args.get('pais'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estadísticas comparativa/sedes")


@estadisticas_bp.route('/api/estadisticas/comparativa/sociedades')
def stats_comparativa_sociedades():
    """
    Fase 5: comparativa detallada de emisiones entre sociedades.
    Query param requerido: anio
    Query params opcionales: pais, tipo_energia
    """
    anio = request.args.get('anio')
    if not anio:
        return jsonify({'exito': False, 'error': 'anio es obligatorio'}), 400
    try:
        datos = comparativa_sociedades(
            anio=anio,
            pais=request.args.get('pais'),
            tipo_energia=request.args.get('tipo_energia', 'electricidad'),
        )
        return jsonify({'exito': True, **datos}), 200
    except Exception as exc:
        return server_error(exc, contexto="Estadísticas comparativa/sociedades")
