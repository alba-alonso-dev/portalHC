"""Blueprint: datos de configuración (sedes, países, comercializadoras).
Fase 5: endpoints de índice documental y cobertura por ejercicio.
"""

import logging
import os
from flask import Blueprint, jsonify, request
from database.connection import get_db_connection
from routes._helpers import server_error
import config

logger = logging.getLogger(__name__)
configuracion_bp = Blueprint('configuracion', __name__)


@configuracion_bp.route('/api/paises')
def get_paises():
    """Lista de países activos con sedes disponibles."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT codigo, nombre FROM paises WHERE activo=1 ORDER BY nombre"
        ).fetchall()
    if rows:
        return jsonify({'paises': [dict(r) for r in rows]})
    # Fallback a config.py si la tabla aún no se ha poblado
    return jsonify({'paises': [
        {'codigo': k, 'nombre': k}
        for k in config.SEDES_PAISES.keys()
    ]})


@configuracion_bp.route('/api/sedes/<pais>')
def get_sedes(pais):
    """Lista de sedes activas para un país (desde BD, no desde config.py)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT nombre FROM sedes WHERE pais_codigo=? AND activo=1 ORDER BY nombre",
            (pais.upper(),)
        ).fetchall()
    sedes = [r['nombre'] for r in rows]
    if not sedes:
        # Fallback a config.py si la tabla de sedes aún no se ha poblado
        sedes = config.SEDES_PAISES.get(pais.upper(), [])
    return jsonify({'sedes': sedes})


@configuracion_bp.route('/api/comercializadoras/<pais>')
def get_comercializadoras(pais):
    """Lista de comercializadoras activas para un país."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT nombre FROM comercializadoras "
            "WHERE pais_codigo=? AND tipo_energia='electricidad' AND activo=1 ORDER BY nombre",
            (pais.upper(),)
        ).fetchall()
    nombres = [r['nombre'] for r in rows]
    if not nombres:
        nombres = config.COMERCIALIZADORAS.get(pais.upper(), [])
    return jsonify({'comercializadoras': nombres})


# ──────────────────────────────────────────────────────────────
# DEV ONLY — Reset de datos de prueba
# ──────────────────────────────────────────────────────────────

@configuracion_bp.route('/api/dev/reset-datos', methods=['POST'])
def reset_datos_prueba():
    """
    Limpia todas las tablas transaccionales manteniendo los datos maestros
    (factores de emisión, fuentes, países, sedes, comercializadoras, tipos_energia).
    SOLO para uso en entornos de prueba/desarrollo.
    """
    if os.getenv('ALLOW_DEV_RESET', 'false').lower() != 'true':
        return jsonify({'exito': False, 'error': 'Operación no permitida en este entorno.'}), 403

    # Orden de borrado: primero las tablas hijas, después las padre. Las claves
    # foráneas se dejan ACTIVAS a propósito: si alguna tabla dependiente faltara
    # en esta lista, PostgreSQL abortará con un error visible en lugar de dejar
    # filas huérfanas en silencio, que es justo lo que ocurría antes.
    tablas = [
        # Dependientes de facturas
        'documentos_indice',
        'facturas_historial',
        'alertas',
        'recalculos_historial',
        'audit_log',
        # Principales
        'lotes_recalculo',
        'periodos_faltantes',
        'estimaciones',
        'facturas',
        'lotes',
        'sync_log',
    ]
    try:
        vaciadas = []
        with get_db_connection() as conn:
            for tabla in tablas:
                existe = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (tabla,)
                ).fetchone()
                if not existe:
                    continue  # tabla no presente en instancias antiguas
                conn.execute(f'DELETE FROM {tabla}')
                # Equivalente a borrar la fila de sqlite_sequence: reinicia el
                # contador de la secuencia del id para que la numeración vuelva
                # a empezar en 1. Las tablas sin columna serial se ignoran.
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), 1, false) "
                    "WHERE pg_get_serial_sequence(?, 'id') IS NOT NULL",
                    (tabla, tabla)
                )
                vaciadas.append(tabla)

            # Catálogo de métodos de estimación: sus filas son maestras, solo se
            # ponen a cero los contadores acumulados durante las estimaciones.
            conn.execute('''
                UPDATE metodo_estimacion_metricas
                   SET n_sustituciones = 0,
                       suma_error_abs  = 0,
                       suma_error_rel  = 0,
                       max_error_abs   = NULL,
                       max_error_rel   = NULL,
                       ultima_actualizacion = CURRENT_TIMESTAMP
            ''')

        logger.warning('DEV RESET ejecutado — tablas transaccionales vaciadas')
        return jsonify({'exito': True, 'tablas_vaciadas': vaciadas}), 200
    except Exception as exc:
        return server_error(exc, contexto="DEV reset datos")


# ── Fase 5: Gestión documental ─────────────────────────────────────────────

@configuracion_bp.route('/api/documentos/indice')
def indice_documentos():
    """
    Fase 5: lista el índice de documentos cargados.
    Query params: ejercicio, pais, sede
    """
    from services.documento_service import listar_documentos_por_ejercicio
    ejercicio = request.args.get('ejercicio')
    pais      = request.args.get('pais')
    sede      = request.args.get('sede')
    docs = listar_documentos_por_ejercicio(ejercicio=ejercicio, pais=pais, sede=sede)
    return jsonify({'exito': True, 'total': len(docs), 'documentos': docs})


@configuracion_bp.route('/api/documentos/cobertura')
def cobertura_documental():
    """
    Fase 5: cobertura documental por ejercicio — meses con y sin factura.
    Query params: ejercicio (obligatorio), pais, sede
    """
    from services.documento_service import cobertura_por_ejercicio
    ejercicio = request.args.get('ejercicio')
    if not ejercicio:
        return jsonify({'exito': False, 'error': 'ejercicio es obligatorio'}), 400

    pais = request.args.get('pais')
    sede = request.args.get('sede')
    resultado = cobertura_por_ejercicio(ejercicio=ejercicio, pais=pais, sede=sede)
    return jsonify({'exito': True, **resultado})
