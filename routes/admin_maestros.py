"""
Blueprint: administración de datos maestros — Modo Admin.

Endpoints CRUD para las tablas maestras del portal:
  - /api/admin/paises
  - /api/admin/sedes
  - /api/admin/comercializadoras
  - /api/admin/tipos-energia
  - /api/admin/suministros
  - /api/admin/estado          — indica si el modo admin está habilitado

Seguridad:
  Todas las operaciones de escritura requieren la variable de entorno
  `ALLOW_ADMIN_MAESTROS=true`. Si no está activa, los endpoints de
  modificación responden 403. Los endpoints de lectura (GET) funcionan
  siempre para que la interfaz pueda mostrar el catálogo.

  Esto replica el patrón ya existente de `ALLOW_DEV_RESET` en
  `routes/configuracion.py`, aplicado a la gestión de maestros.
"""

import logging
import os
from flask import Blueprint, jsonify, request

from routes._helpers import server_error, bad_request
from services import maestros_service as svc

logger = logging.getLogger(__name__)
admin_maestros_bp = Blueprint('admin_maestros', __name__)


# ── Helper de autorización ────────────────────────────────────────────────────

def _admin_habilitado() -> bool:
    """True si la variable ALLOW_ADMIN_MAESTROS está activa."""
    return os.getenv('ALLOW_ADMIN_MAESTROS', 'false').lower() == 'true'


def _requiere_admin():
    """
    Llama desde el inicio de cualquier endpoint de escritura.
    Devuelve una respuesta 403 si el modo admin no está habilitado.
    Uso:
        err = _requiere_admin()
        if err: return err
    """
    if not _admin_habilitado():
        return jsonify({
            'exito': False,
            'error': 'Modo admin no habilitado. '
                      'Establece ALLOW_ADMIN_MAESTROS=true para modificar maestros.'
        }), 403
    return None


def _usuario_request() -> str:
    """Extrae el usuario del body o query; fallback 'admin'."""
    if request.is_json:
        datos = request.get_json(silent=True) or {}
        if datos.get('usuario'):
            return datos['usuario']
    return request.args.get('usuario', 'admin')


# ── Estado del modo admin ─────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/estado')
def estado_admin():
    """Indica si el modo admin está habilitado en este entorno."""
    return jsonify({
        'exito': True,
        'admin_habilitado': _admin_habilitado(),
        'env_var': 'ALLOW_ADMIN_MAESTROS',
    })


# ── Países ───────────────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/paises', methods=['GET'])
def listar_paises():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    return jsonify({'exito': True,
                    'paises': svc.listar_paises(incluir_inactivos=incluir),
                    'total': 0})


@admin_maestros_bp.route('/api/admin/paises', methods=['POST'])
def crear_pais():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        pais = svc.crear_pais(
            codigo=datos.get('codigo'),
            nombre=datos.get('nombre'),
            zona_horaria=datos.get('zona_horaria'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'pais': pais}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin paises crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin paises crear")


@admin_maestros_bp.route('/api/admin/paises/<codigo>', methods=['PUT'])
def actualizar_pais(codigo):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        pais = svc.actualizar_pais(
            codigo=codigo,
            nombre=datos.get('nombre'),
            zona_horaria=datos.get('zona_horaria'),
            usuario=_usuario_request(),
        )
        if not pais:
            return jsonify({'exito': False, 'error': 'País no encontrado'}), 404
        return jsonify({'exito': True, 'pais': pais})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin paises actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin paises actualizar")


@admin_maestros_bp.route('/api/admin/paises/<codigo>/estado', methods=['PATCH'])
def cambiar_estado_pais(codigo):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        pais = svc.cambiar_estado_pais(
            codigo=codigo,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not pais:
            return jsonify({'exito': False, 'error': 'País no encontrado'}), 404
        return jsonify({'exito': True, 'pais': pais})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin paises estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin paises estado")


# ── Sedes ─────────────────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/sedes', methods=['GET'])
def listar_sedes():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    sedes = svc.listar_sedes(
        pais_codigo=request.args.get('pais'),
        incluir_inactivos=incluir,
    )
    return jsonify({'exito': True, 'sedes': sedes, 'total': len(sedes)})


@admin_maestros_bp.route('/api/admin/sedes', methods=['POST'])
def crear_sede():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        sede = svc.crear_sede(
            pais_codigo=datos.get('pais_codigo'),
            nombre=datos.get('nombre'),
            direccion=datos.get('direccion'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'sede': sede}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sedes crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin sedes crear")


@admin_maestros_bp.route('/api/admin/sedes/<int:sede_id>', methods=['PUT'])
def actualizar_sede(sede_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        sede = svc.actualizar_sede(
            sede_id=sede_id,
            nombre=datos.get('nombre'),
            direccion=datos.get('direccion'),
            usuario=_usuario_request(),
        )
        if not sede:
            return jsonify({'exito': False, 'error': 'Sede no encontrada'}), 404
        return jsonify({'exito': True, 'sede': sede})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sedes actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin sedes actualizar")


@admin_maestros_bp.route('/api/admin/sedes/<int:sede_id>/estado', methods=['PATCH'])
def cambiar_estado_sede(sede_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        sede = svc.cambiar_estado_sede(
            sede_id=sede_id,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not sede:
            return jsonify({'exito': False, 'error': 'Sede no encontrada'}), 404
        return jsonify({'exito': True, 'sede': sede})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sedes estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin sedes estado")


@admin_maestros_bp.route('/api/admin/sedes/<int:sede_id>', methods=['DELETE'])
def borrar_sede(sede_id):
    err = _requiere_admin()
    if err:
        return err
    try:
        ok = svc.borrar_sede(sede_id, usuario=_usuario_request())
        if not ok:
            return jsonify({'exito': False, 'error': 'Sede no encontrada'}), 404
        return jsonify({'exito': True, 'mensaje': f'Sede {sede_id} borrada'})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sedes borrar")
    except Exception as exc:
        return server_error(exc, contexto="Admin sedes borrar")


# ── Comercializadoras ────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/comercializadoras', methods=['GET'])
def listar_comercializadoras():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    coms = svc.listar_comercializadoras(
        pais_codigo=request.args.get('pais'),
        tipo_energia=request.args.get('tipo_energia'),
        incluir_inactivos=incluir,
    )
    return jsonify({'exito': True, 'comercializadoras': coms,
                    'total': len(coms)})


@admin_maestros_bp.route('/api/admin/comercializadoras', methods=['POST'])
def crear_comercializadora():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        com = svc.crear_comercializadora(
            pais_codigo=datos.get('pais_codigo'),
            nombre=datos.get('nombre'),
            tipo_energia=datos.get('tipo_energia', 'electricidad'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'comercializadora': com}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin comercializadoras crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin comercializadoras crear")


@admin_maestros_bp.route('/api/admin/comercializadoras/<int:com_id>', methods=['PUT'])
def actualizar_comercializadora(com_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        com = svc.actualizar_comercializadora(
            com_id=com_id,
            nombre=datos.get('nombre'),
            tipo_energia=datos.get('tipo_energia'),
            usuario=_usuario_request(),
        )
        if not com:
            return jsonify({'exito': False, 'error': 'Comercializadora no encontrada'}), 404
        return jsonify({'exito': True, 'comercializadora': com})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin comercializadoras actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin comercializadoras actualizar")


@admin_maestros_bp.route('/api/admin/comercializadoras/<int:com_id>/estado', methods=['PATCH'])
def cambiar_estado_comercializadora(com_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        com = svc.cambiar_estado_comercializadora(
            com_id=com_id,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not com:
            return jsonify({'exito': False, 'error': 'Comercializadora no encontrada'}), 404
        return jsonify({'exito': True, 'comercializadora': com})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin comercializadoras estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin comercializadoras estado")


@admin_maestros_bp.route('/api/admin/comercializadoras/<int:com_id>', methods=['DELETE'])
def borrar_comercializadora(com_id):
    err = _requiere_admin()
    if err:
        return err
    try:
        ok = svc.borrar_comercializadora(com_id, usuario=_usuario_request())
        if not ok:
            return jsonify({'exito': False, 'error': 'Comercializadora no encontrada'}), 404
        return jsonify({'exito': True, 'mensaje': f'Comercializadora {com_id} borrada'})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin comercializadoras borrar")
    except Exception as exc:
        return server_error(exc, contexto="Admin comercializadoras borrar")


# ── Tipos de energía ─────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/tipos-energia', methods=['GET'])
def listar_tipos_energia():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    tipos = svc.listar_tipos_energia(incluir_inactivos=incluir)
    return jsonify({'exito': True, 'tipos_energia': tipos, 'total': len(tipos)})


@admin_maestros_bp.route('/api/admin/tipos-energia', methods=['POST'])
def crear_tipo_energia():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        tipo = svc.crear_tipo_energia(
            codigo=datos.get('codigo'),
            nombre=datos.get('nombre'),
            unidad_medida=datos.get('unidad_medida'),
            unidad_emision=datos.get('unidad_emision'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'tipo_energia': tipo}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin tipos-energia crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin tipos-energia crear")


@admin_maestros_bp.route('/api/admin/tipos-energia/<codigo>', methods=['PUT'])
def actualizar_tipo_energia(codigo):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        tipo = svc.actualizar_tipo_energia(
            codigo=codigo,
            nombre=datos.get('nombre'),
            unidad_medida=datos.get('unidad_medida'),
            unidad_emision=datos.get('unidad_emision'),
            usuario=_usuario_request(),
        )
        if not tipo:
            return jsonify({'exito': False, 'error': 'Tipo de energía no encontrado'}), 404
        return jsonify({'exito': True, 'tipo_energia': tipo})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin tipos-energia actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin tipos-energia actualizar")


@admin_maestros_bp.route('/api/admin/tipos-energia/<codigo>/estado', methods=['PATCH'])
def cambiar_estado_tipo_energia(codigo):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        tipo = svc.cambiar_estado_tipo_energia(
            codigo=codigo,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not tipo:
            return jsonify({'exito': False, 'error': 'Tipo de energía no encontrado'}), 404
        return jsonify({'exito': True, 'tipo_energia': tipo})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin tipos-energia estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin tipos-energia estado")


# ── Suministros ───────────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/suministros', methods=['GET'])
def listar_suministros():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    sums = svc.listar_suministros(
        pais_codigo=request.args.get('pais'),
        sede_id=request.args.get('sede_id', type=int),
        tipo_energia=request.args.get('tipo_energia'),
        incluir_inactivos=incluir,
    )
    return jsonify({'exito': True, 'suministros': sums, 'total': len(sums)})


@admin_maestros_bp.route('/api/admin/suministros', methods=['POST'])
def crear_suministro():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        sum_obj = svc.crear_suministro(
            sede_id=datos.get('sede_id'),
            tipo_energia=datos.get('tipo_energia', 'electricidad'),
            referencia=datos.get('referencia'),
            notas=datos.get('notas'),
            sociedad_id=datos.get('sociedad_id'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'suministro': sum_obj}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin suministros crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin suministros crear")


@admin_maestros_bp.route('/api/admin/suministros/<int:sum_id>', methods=['PUT'])
def actualizar_suministro(sum_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        sum_obj = svc.actualizar_suministro(
            sum_id=sum_id,
            tipo_energia=datos.get('tipo_energia'),
            referencia=datos.get('referencia'),
            notas=datos.get('notas'),
            sociedad_id=datos.get('sociedad_id'),
            usuario=_usuario_request(),
        )
        if not sum_obj:
            return jsonify({'exito': False, 'error': 'Suministro no encontrado'}), 404
        return jsonify({'exito': True, 'suministro': sum_obj})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin suministros actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin suministros actualizar")


@admin_maestros_bp.route('/api/admin/suministros/<int:sum_id>/estado', methods=['PATCH'])
def cambiar_estado_suministro(sum_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        sum_obj = svc.cambiar_estado_suministro(
            sum_id=sum_id,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not sum_obj:
            return jsonify({'exito': False, 'error': 'Suministro no encontrado'}), 404
        return jsonify({'exito': True, 'suministro': sum_obj})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin suministros estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin suministros estado")


@admin_maestros_bp.route('/api/admin/suministros/<int:sum_id>', methods=['DELETE'])
def borrar_suministro(sum_id):
    err = _requiere_admin()
    if err:
        return err
    try:
        ok = svc.borrar_suministro(sum_id, usuario=_usuario_request())
        if not ok:
            return jsonify({'exito': False, 'error': 'Suministro no encontrado'}), 404
        return jsonify({'exito': True, 'mensaje': f'Suministro {sum_id} borrado'})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin suministros borrar")
    except Exception as exc:
        return server_error(exc, contexto="Admin suministros borrar")


# ── Sociedades ────────────────────────────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/sociedades', methods=['GET'])
def listar_sociedades():
    incluir = request.args.get('incluir_inactivos', '0') == '1'
    socs = svc.listar_sociedades(
        pais_codigo=request.args.get('pais'),
        incluir_inactivos=incluir,
    )
    return jsonify({'exito': True, 'sociedades': socs, 'total': len(socs)})


@admin_maestros_bp.route('/api/admin/sociedades', methods=['POST'])
def crear_sociedad():
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        soc = svc.crear_sociedad(
            nombre=datos.get('nombre'),
            cif=datos.get('cif'),
            pais_codigo=datos.get('pais_codigo'),
            usuario=_usuario_request(),
        )
        return jsonify({'exito': True, 'sociedad': soc}), 201
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sociedades crear")
    except Exception as exc:
        return server_error(exc, contexto="Admin sociedades crear")


@admin_maestros_bp.route('/api/admin/sociedades/<int:soc_id>', methods=['PUT'])
def actualizar_sociedad(soc_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    try:
        soc = svc.actualizar_sociedad(
            soc_id=soc_id,
            nombre=datos.get('nombre'),
            cif=datos.get('cif'),
            pais_codigo=datos.get('pais_codigo'),
            usuario=_usuario_request(),
        )
        if not soc:
            return jsonify({'exito': False, 'error': 'Sociedad no encontrada'}), 404
        return jsonify({'exito': True, 'sociedad': soc})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sociedades actualizar")
    except Exception as exc:
        return server_error(exc, contexto="Admin sociedades actualizar")


@admin_maestros_bp.route('/api/admin/sociedades/<int:soc_id>/estado', methods=['PATCH'])
def cambiar_estado_sociedad(soc_id):
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    if 'activo' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'activo' requerido"}), 400
    try:
        soc = svc.cambiar_estado_sociedad(
            soc_id=soc_id,
            activo=bool(datos['activo']),
            usuario=_usuario_request(),
        )
        if not soc:
            return jsonify({'exito': False, 'error': 'Sociedad no encontrada'}), 404
        return jsonify({'exito': True, 'sociedad': soc})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sociedades estado")
    except Exception as exc:
        return server_error(exc, contexto="Admin sociedades estado")


@admin_maestros_bp.route('/api/admin/sociedades/<int:soc_id>', methods=['DELETE'])
def borrar_sociedad(soc_id):
    err = _requiere_admin()
    if err:
        return err
    try:
        ok = svc.borrar_sociedad(soc_id, usuario=_usuario_request())
        if not ok:
            return jsonify({'exito': False, 'error': 'Sociedad no encontrada'}), 404
        return jsonify({'exito': True, 'mensaje': f'Sociedad {soc_id} borrada'})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin sociedades borrar")
    except Exception as exc:
        return server_error(exc, contexto="Admin sociedades borrar")


# ── Vinculación suministro ↔ sociedad ────────────────────────────────────────

@admin_maestros_bp.route('/api/admin/suministros/<int:sum_id>/sociedad', methods=['PUT'])
def vincular_suministro_sociedad(sum_id):
    """
    Asigna la sociedad titular a un suministro (CUPS).

    Caso de uso: una sede puede tener varios CUPS, cada uno facturado a una
    sociedad distinta del grupo. El titular del punto de suministro es la
    sociedad, no la sede.
    """
    err = _requiere_admin()
    if err:
        return err
    datos = request.get_json(force=True) or {}
    # sociedad_id puede ser null (desvincular) o un entero
    if 'sociedad_id' not in datos:
        return jsonify({'exito': False, 'error': "Campo 'sociedad_id' requerido"}), 400
    sociedad_id_raw = datos.get('sociedad_id')
    sociedad_id = int(sociedad_id_raw) if sociedad_id_raw is not None else None
    try:
        resultado = svc.vincular_suministro_sociedad(
            sum_id=sum_id,
            sociedad_id=sociedad_id,
            usuario=_usuario_request(),
        )
        if not resultado:
            return jsonify({'exito': False, 'error': 'Suministro no encontrado'}), 404
        return jsonify({'exito': True, 'suministro': resultado})
    except ValueError as exc:
        return bad_request(exc, contexto="Admin vincular suministro-sociedad")
    except Exception as exc:
        return server_error(exc, contexto="Admin vincular suministro-sociedad")
