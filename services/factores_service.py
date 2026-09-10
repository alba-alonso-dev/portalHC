"""
Servicio de gestión de factores de emisión — Fase 2.

Principios de diseño:
  - Versionado inmutable: modificar el valor de un factor crea una nueva versión.
  - Trazabilidad completa: cada cambio queda registrado en `factores_historial`.
  - Una sola versión activa por (pais, tipo_energia, anio): al activar una nueva,
    se desactiva la anterior automáticamente.
  - Compatible con Fase 3 (recálculo histórico): las facturas almacenan
    `factor_version_id` apuntando a la versión exacta utilizada.
"""

import logging
from datetime import datetime
from database.connection import get_db_connection
from services.audit_service import (
    registrar_evento,
    ACCION_FACTOR_CREADO, ACCION_FACTOR_NUEVA_VERSION,
    ACCION_FACTOR_EDITADO, ACCION_FACTOR_ESTADO,
)

logger = logging.getLogger(__name__)


# ── Consultas ─────────────────────────────────────────────────────────────────

def listar_factores(pais: str = None, anio: str = None,
                    tipo_energia: str = None, solo_activos: bool = False,
                    solo_versiones_activas: bool = False) -> list[dict]:
    """Devuelve factores con datos de su fuente, aplicando filtros opcionales."""
    condiciones = []
    params = []

    if pais:
        condiciones.append("fe.pais = ?")
        params.append(pais.upper())
    if anio:
        condiciones.append("fe.anio = ?")
        params.append(str(anio))
    if tipo_energia:
        condiciones.append("fe.tipo_energia = ?")
        params.append(tipo_energia)
    if solo_activos:
        condiciones.append("fe.activo = 1")
    if solo_versiones_activas:
        condiciones.append("fe.es_version_activa = 1")

    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""

    sql = f'''
        SELECT fe.id, fe.pais, fe.tipo_energia, fe.anio, fe.version,
               fe.factor_kg_co2_mwh, fe.unidad, fe.descripcion,
               fe.activo, fe.es_version_activa,
               fe.fecha_vigencia_desde, fe.fecha_vigencia_hasta,
               fe.notas, fe.creado_por,
               fe.fecha_carga, fe.modificado_en,
               fe.fuente_id,
               COALESCE(fu.nombre, fe.fuente) AS fuente_nombre,
               COALESCE(fu.organizacion, '')   AS fuente_organizacion,
               COALESCE(fu.url, fe.url, '')    AS fuente_url
        FROM factores_emision fe
        LEFT JOIN fuentes_emision fu ON fu.id = fe.fuente_id
        {where}
        ORDER BY fe.pais, fe.tipo_energia, fe.anio DESC, fe.version DESC
    '''

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def obtener_factor_detalle(factor_id: int) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute('''
            SELECT fe.*, fu.nombre AS fuente_nombre, fu.organizacion, fu.url AS fuente_url,
                   fu.codigo AS fuente_codigo, fu.anio_publicacion AS fuente_anio_pub,
                   fu.notas AS fuente_notas
            FROM factores_emision fe
            LEFT JOIN fuentes_emision fu ON fu.id = fe.fuente_id
            WHERE fe.id = ?
        ''', (factor_id,)).fetchone()
    return dict(row) if row else None


def listar_versiones_pais_anio(pais: str, anio: str, tipo_energia: str = 'electricidad') -> list[dict]:
    """Devuelve todas las versiones de un factor (pais+anio), activas e inactivas."""
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT fe.id, fe.version, fe.factor_kg_co2_mwh, fe.unidad,
                   fe.activo, fe.es_version_activa, fe.fuente,
                   COALESCE(fu.nombre, fe.fuente) AS fuente_nombre,
                   fe.fecha_carga, fe.creado_por, fe.notas
            FROM factores_emision fe
            LEFT JOIN fuentes_emision fu ON fu.id = fe.fuente_id
            WHERE fe.pais = ? AND fe.tipo_energia = ? AND fe.anio = ?
            ORDER BY fe.version DESC
        ''', (pais.upper(), tipo_energia, str(anio))).fetchall()
    return [dict(r) for r in rows]


# ── Creación / Versionado ─────────────────────────────────────────────────────

def crear_factor(datos: dict) -> dict:
    """
    Crea un nuevo factor (versión 1) para un pais+tipo+anio no existente.
    Lanza ValueError si ya existe algún factor para esa combinación.
    """
    pais        = datos['pais'].upper()
    tipo        = datos.get('tipo_energia', 'electricidad')
    anio        = str(datos['anio'])
    factor_val  = float(datos['factor_kg_co2_mwh'])
    fuente_id   = datos.get('fuente_id')
    unidad      = datos.get('unidad', 'kg CO2eq/MWh')
    descripcion = datos.get('descripcion')
    notas       = datos.get('notas')
    creado_por  = datos.get('creado_por', 'usuario')
    fecha_desde = datos.get('fecha_vigencia_desde')
    fecha_hasta = datos.get('fecha_vigencia_hasta')

    _validar_factor(factor_val, fuente_id)

    with get_db_connection() as conn:
        # Verificar que no existe ninguna versión activa
        existente = conn.execute('''
            SELECT COUNT(*) FROM factores_emision
            WHERE pais=? AND tipo_energia=? AND anio=? AND es_version_activa=1
        ''', (pais, tipo, anio)).fetchone()[0]
        if existente:
            raise ValueError(
                f"Ya existe un factor activo para {pais}/{tipo}/{anio}. "
                "Use 'crear_nueva_version' para añadir una versión actualizada."
            )

        cursor = conn.execute('''
            INSERT INTO factores_emision
                (pais, tipo_energia, anio, version, factor_kg_co2_mwh, unidad,
                 descripcion, fuente_id, notas, activo, es_version_activa,
                 fecha_vigencia_desde, fecha_vigencia_hasta, creado_por)
            VALUES (?,?,?,1,?,?,?,?,?,1,1,?,?,?)
        ''', (pais, tipo, anio, factor_val, unidad, descripcion,
              fuente_id, notas, fecha_desde, fecha_hasta, creado_por))
        factor_id = cursor.lastrowid

        _registrar_historial(conn, factor_id, 'creado', None, None, factor_val,
                             version=1, usuario=creado_por,
                             notas=f"Factor creado para {pais}/{tipo}/{anio}")

    resultado = obtener_factor_detalle(factor_id)
    registrar_evento(
        accion=ACCION_FACTOR_CREADO,
        usuario=creado_por,
        entidad='factor',
        entidad_id=factor_id,
        detalle={'pais': pais, 'tipo': tipo, 'anio': anio, 'valor': factor_val},
    )
    return resultado


def crear_nueva_version(factor_id_base: int, datos: dict) -> dict:
    """
    Crea una nueva versión inmutable a partir de un factor existente.
    La versión anterior queda con es_version_activa=0 pero NO se elimina
    (trazabilidad de facturas históricas).
    """
    base = obtener_factor_detalle(factor_id_base)
    if not base:
        raise ValueError(f"Factor {factor_id_base} no encontrado")

    pais  = base['pais']
    tipo  = base['tipo_energia']
    anio  = base['anio']
    nueva_val = float(datos['factor_kg_co2_mwh'])
    fuente_id = datos.get('fuente_id', base['fuente_id'])
    unidad    = datos.get('unidad', base['unidad'])
    notas     = datos.get('notas')
    usuario   = datos.get('creado_por', 'usuario')
    fecha_desde = datos.get('fecha_vigencia_desde')
    fecha_hasta = datos.get('fecha_vigencia_hasta')

    _validar_factor(nueva_val, fuente_id)

    with get_db_connection() as conn:
        # Obtener la versión máxima actual
        max_version = conn.execute(
            '''SELECT COALESCE(MAX(version),0) FROM factores_emision
               WHERE pais=? AND tipo_energia=? AND anio=?''',
            (pais, tipo, anio)
        ).fetchone()[0]
        nueva_version = max_version + 1

        # Desactivar versión anterior
        conn.execute('''
            UPDATE factores_emision
            SET es_version_activa=0, fecha_vigencia_hasta=?, modificado_en=CURRENT_TIMESTAMP
            WHERE pais=? AND tipo_energia=? AND anio=? AND es_version_activa=1
        ''', (datetime.now().strftime('%Y-%m-%d'), pais, tipo, anio))

        # Insertar nueva versión
        cursor = conn.execute('''
            INSERT INTO factores_emision
                (pais, tipo_energia, anio, version, factor_kg_co2_mwh, unidad,
                 descripcion, fuente_id, notas, activo, es_version_activa,
                 fecha_vigencia_desde, fecha_vigencia_hasta, creado_por)
            VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?,?)
        ''', (pais, tipo, anio, nueva_version, nueva_val, unidad,
              datos.get('descripcion', base.get('descripcion')),
              fuente_id, notas, fecha_desde, fecha_hasta, usuario))
        nuevo_id = cursor.lastrowid

        _registrar_historial(conn, nuevo_id, 'nueva_version',
                             'factor_kg_co2_mwh',
                             str(base['factor_kg_co2_mwh']), str(nueva_val),
                             version=nueva_version, usuario=usuario,
                             notas=f"Nueva versión v{nueva_version} creada desde factor id={factor_id_base}")

    resultado = obtener_factor_detalle(nuevo_id)
    registrar_evento(
        accion=ACCION_FACTOR_NUEVA_VERSION,
        usuario=usuario,
        entidad='factor',
        entidad_id=nuevo_id,
        detalle={
            'pais': pais, 'anio': anio,
            'version_anterior': max_version, 'version_nueva': nueva_version,
            'valor_anterior': base['factor_kg_co2_mwh'], 'valor_nuevo': nueva_val,
        },
    )
    return resultado


# ── Edición de metadatos ──────────────────────────────────────────────────────

def editar_metadatos(factor_id: int, datos: dict) -> dict:
    """
    Edición in-place de campos no numéricos (descripción, notas, fuente_id).
    El valor del factor NO se puede editar aquí; para eso usar crear_nueva_version.
    """
    campos_editables = ['descripcion', 'notas', 'fuente_id',
                        'fecha_vigencia_desde', 'fecha_vigencia_hasta', 'unidad']
    actual = obtener_factor_detalle(factor_id)
    if not actual:
        raise ValueError(f"Factor {factor_id} no encontrado")

    sets, params, cambios = [], [], []
    usuario = datos.get('usuario', 'usuario')

    for campo in campos_editables:
        if campo in datos:
            sets.append(f"{campo} = ?")
            params.append(datos[campo])
            cambios.append((campo, actual.get(campo), datos[campo]))

    if not sets:
        raise ValueError("No se proporcionaron campos editables")

    sets.append("modificado_en = CURRENT_TIMESTAMP")
    params.append(factor_id)

    with get_db_connection() as conn:
        conn.execute(
            f"UPDATE factores_emision SET {', '.join(sets)} WHERE id = ?",
            params
        )
        for campo, antes, despues in cambios:
            _registrar_historial(conn, factor_id, 'editado_metadatos', campo,
                                 str(antes), str(despues), usuario=usuario)

    resultado = obtener_factor_detalle(factor_id)
    registrar_evento(
        accion=ACCION_FACTOR_EDITADO,
        usuario=usuario,
        entidad='factor',
        entidad_id=factor_id,
        detalle={'campos_modificados': [c[0] for c in cambios]},
    )
    return resultado


# ── Activar / Desactivar ──────────────────────────────────────────────────────

def cambiar_estado(factor_id: int, activo: bool, usuario: str = 'usuario') -> dict:
    """
    Activa o desactiva un factor. No elimina registros físicamente.
    Si se reactiva, se marca también como es_version_activa si no hay otra
    versión activa para el mismo pais+tipo+anio.
    """
    factor = obtener_factor_detalle(factor_id)
    if not factor:
        raise ValueError(f"Factor {factor_id} no encontrado")

    with get_db_connection() as conn:
        # Si activamos, verificar que no haya otra es_version_activa diferente
        if activo:
            otra_activa = conn.execute('''
                SELECT id FROM factores_emision
                WHERE pais=? AND tipo_energia=? AND anio=? AND es_version_activa=1 AND id!=?
            ''', (factor['pais'], factor['tipo_energia'], factor['anio'], factor_id)).fetchone()
            if otra_activa:
                raise ValueError(
                    f"No se puede activar: la versión id={otra_activa['id']} ya es la versión "
                    f"activa para {factor['pais']}/{factor['tipo_energia']}/{factor['anio']}."
                )

        conn.execute('''
            UPDATE factores_emision
            SET activo=?, es_version_activa=?, modificado_en=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (1 if activo else 0, 1 if activo else 0, factor_id))

        accion = 'activado' if activo else 'desactivado'
        _registrar_historial(conn, factor_id, accion, 'activo',
                             str(factor['activo']), str(1 if activo else 0), usuario=usuario)

    resultado = obtener_factor_detalle(factor_id)
    registrar_evento(
        accion=ACCION_FACTOR_ESTADO,
        usuario=usuario,
        entidad='factor',
        entidad_id=factor_id,
        detalle={'activo': activo},
    )
    return resultado


# ── Historial ─────────────────────────────────────────────────────────────────

def obtener_historial_factor(factor_id: int) -> list[dict]:
    """Devuelve el historial completo de auditoría de un factor."""
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT id, factor_id, accion, campo,
                   valor_anterior, valor_nuevo, version_resultante,
                   usuario, fecha_cambio, notas
            FROM factores_historial
            WHERE factor_id = ?
            ORDER BY fecha_cambio DESC
        ''', (factor_id,)).fetchall()
    return [dict(r) for r in rows]


# ── Fuentes ───────────────────────────────────────────────────────────────────

def listar_fuentes(solo_activas: bool = True) -> list[dict]:
    sql = "SELECT * FROM fuentes_emision"
    if solo_activas:
        sql += " WHERE activo = 1"
    sql += " ORDER BY nombre"
    with get_db_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def crear_fuente(datos: dict) -> dict:
    codigo = datos.get('codigo', '').strip().upper()
    nombre = datos.get('nombre', '').strip()
    if not codigo or not nombre:
        raise ValueError("código y nombre son obligatorios")

    with get_db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO fuentes_emision
                (codigo, nombre, organizacion, anio_publicacion, url, notas)
            VALUES (?,?,?,?,?,?)
        ''', (codigo, nombre, datos.get('organizacion'), datos.get('anio_publicacion'),
              datos.get('url'), datos.get('notas')))
        fuente_id = cursor.lastrowid
        return dict(conn.execute("SELECT * FROM fuentes_emision WHERE id=?", (fuente_id,)).fetchone())


def editar_fuente(fuente_id: int, datos: dict) -> dict:
    campos = ['nombre', 'organizacion', 'anio_publicacion', 'url', 'notas']
    sets, params = [], []
    for c in campos:
        if c in datos:
            sets.append(f"{c} = ?")
            params.append(datos[c])
    if not sets:
        raise ValueError("Nada que actualizar")
    sets.append("modificado_en = CURRENT_TIMESTAMP")
    params.append(fuente_id)
    with get_db_connection() as conn:
        conn.execute(f"UPDATE fuentes_emision SET {', '.join(sets)} WHERE id=?", params)
        return dict(conn.execute("SELECT * FROM fuentes_emision WHERE id=?", (fuente_id,)).fetchone())


# ── Helpers privados ──────────────────────────────────────────────────────────

def _validar_factor(valor: float, fuente_id):
    if valor <= 0:
        raise ValueError("El valor del factor debe ser positivo")
    if fuente_id is None:
        raise ValueError("Es obligatorio indicar una fuente (fuente_id)")


def _registrar_historial(conn, factor_id: int, accion: str, campo: str | None,
                         valor_anterior, valor_nuevo,
                         version: int = None, usuario: str = 'sistema', notas: str = None):
    conn.execute('''
        INSERT INTO factores_historial
            (factor_id, accion, campo, valor_anterior, valor_nuevo,
             version_resultante, usuario, notas)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (factor_id, accion, campo, valor_anterior, valor_nuevo, version, usuario, notas))
