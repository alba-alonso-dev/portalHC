"""
Servicio de gestión de datos maestros — Modo Admin.

Encapsula las operaciones CRUD sobre las tablas maestras del portal:
  - paises
  - sedes
  - comercializadoras
  - tipos_energia
  - suministros

Estas tablas NO son operativas de negocio: son catálogos de referencia.
Aun así, dado que impactan en la carga de facturas y el reporting ESG, cualquier
modificación queda registrada en `audit_log` para mantener la trazabilidad.

Principios de diseño:
  - Las operaciones son aditivas o de actualización; no se exponen borrados
    físicos destructivos sobre maestros referenciados por facturas para evitar
    dejar filas huérfanas.
  - Las bajas son lógicas (activo = 0) cuando la tabla lo soporta.
  - Cuando un borrado físico es imprescindible (catálogo limpio), se valida que
    no existan referencias activas antes de ejecutarlo.
  - Los inserts usan INSERT OR IGNORE para no duplicar filas equivalentes.
"""

import logging
from database.connection import get_db_connection
from services.audit_service import (
    registrar_evento,
    ACCION_MAESTRO_CREADO,
    ACCION_MAESTRO_ACTUALIZADO,
    ACCION_MAESTRO_ESTADO,
    ACCION_MAESTRO_BORRADO,
)

logger = logging.getLogger(__name__)


# ── Helper de normalización ───────────────────────────────────────────────────

def _normalizar_codigo_pais(codigo: str) -> str:
    """Los códigos de país se almacenan en mayúsculas."""
    return (codigo or '').upper().strip()


def _normalizar_texto(texto: str) -> str:
    """Trim básico para nombres de sede/comercializadora/tipo."""
    return (texto or '').strip()


# ── Países ───────────────────────────────────────────────────────────────────

def listar_paises(incluir_inactivos: bool = False) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT codigo, nombre, zona_horaria, activo "
            f"FROM paises "
            f"{'WHERE activo=1' if not incluir_inactivos else ''} "
            f"ORDER BY nombre"
        ).fetchall()
    return [dict(r) for r in rows]


def crear_pais(codigo: str, nombre: str, zona_horaria: str = None,
               usuario: str = 'admin') -> dict:
    codigo = _normalizar_codigo_pais(codigo)
    nombre = _normalizar_texto(nombre)
    if not codigo or not nombre:
        raise ValueError("codigo y nombre son obligatorios")

    with get_db_connection() as conn:
        # Verificar conflicto: código ya existe aunque esté inactivo
        existente = conn.execute(
            "SELECT codigo, activo FROM paises WHERE codigo=?", (codigo,)
        ).fetchone()
        if existente:
            raise ValueError(f"Ya existe un país con código '{codigo}'")

        conn.execute(
            "INSERT INTO paises (codigo, nombre, zona_horaria, activo) VALUES (?,?,?,1)",
            (codigo, nombre, zona_horaria)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='paises',
        entidad_id=None,
        detalle={'codigo': codigo, 'nombre': nombre, 'zona_horaria': zona_horaria},
    )
    return {'codigo': codigo, 'nombre': nombre, 'zona_horaria': zona_horaria, 'activo': 1}


def actualizar_pais(codigo: str, nombre: str = None, zona_horaria: str = None,
                    usuario: str = 'admin') -> dict | None:
    codigo = _normalizar_codigo_pais(codigo)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT codigo, nombre, zona_horaria, activo FROM paises WHERE codigo=?",
            (codigo,)
        ).fetchone()
        if not row:
            return None

        campos = []
        params = []
        if nombre is not None:
            campos.append("nombre=?")
            params.append(_normalizar_texto(nombre))
        if zona_horaria is not None:
            campos.append("zona_horaria=?")
            params.append(zona_horaria)
        if not campos:
            return dict(row)
        params.append(codigo)
        conn.execute(
            f"UPDATE paises SET {', '.join(campos)} WHERE codigo=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='paises',
        entidad_id=None,
        detalle={'codigo': codigo, 'cambios': {
            'nombre': nombre, 'zona_horaria': zona_horaria
        }},
    )
    return {'codigo': codigo, 'nombre': nombre or row['nombre'],
            'zona_horaria': zona_horaria or row['zona_horaria'],
            'activo': row['activo']}


def cambiar_estado_pais(codigo: str, activo: bool, usuario: str = 'admin') -> dict | None:
    codigo = _normalizar_codigo_pais(codigo)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT codigo FROM paises WHERE codigo=?", (codigo,)
        ).fetchone()
        if not row:
            return None
        # No desactivar país con sedes activas (rompería los desplegables)
        if not activo:
            sedes_activas = conn.execute(
                "SELECT COUNT(*) AS n FROM sedes WHERE pais_codigo=? AND activo=1",
                (codigo,)
            ).fetchone()['n']
            if sedes_activas > 0:
                raise ValueError(
                    f"No se puede desactivar el país '{codigo}' porque tiene "
                    f"{sedes_activas} sede(s) activa(s). Desactívalas primero."
                )
        conn.execute(
            "UPDATE paises SET activo=? WHERE codigo=?",
            (1 if activo else 0, codigo)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='paises',
        entidad_id=None,
        detalle={'codigo': codigo, 'activo': activo},
    )
    return {'codigo': codigo, 'activo': activo}


# ── Sedes ─────────────────────────────────────────────────────────────────────

def listar_sedes(pais_codigo: str = None, incluir_inactivos: bool = False) -> list[dict]:
    condiciones = []
    params = []
    if pais_codigo:
        condiciones.append("pais_codigo=?")
        params.append(_normalizar_codigo_pais(pais_codigo))
    if not incluir_inactivos:
        condiciones.append("activo=1")
    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, pais_codigo, nombre, direccion, activo "
            f"FROM sedes {where} ORDER BY pais_codigo, nombre",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def crear_sede(pais_codigo: str, nombre: str, direccion: str = None,
                usuario: str = 'admin') -> dict:
    pais_codigo = _normalizar_codigo_pais(pais_codigo)
    nombre = _normalizar_texto(nombre)
    if not pais_codigo or not nombre:
        raise ValueError("pais_codigo y nombre son obligatorios")

    with get_db_connection() as conn:
        # País debe existir
        pais = conn.execute(
            "SELECT codigo FROM paises WHERE codigo=?", (pais_codigo,)
        ).fetchone()
        if not pais:
            raise ValueError(f"No existe el país '{pais_codigo}'")

        # La tabla tiene UNIQUE(pais_codigo, nombre) literal. Antes de insertar
        # comprobamos de forma insensible a tildes/mayúsculas para dar un error
        # claro en lugar del OperationalError genérico de SQLite.
        from database.migrations_sedes import clave_sede
        clave = clave_sede(nombre)
        existente = conn.execute(
            "SELECT id, nombre, activo FROM sedes "
            "WHERE pais_codigo=? AND LOWER(nombre)=LOWER(?)",
            (pais_codigo, nombre)
        ).fetchone()
        if existente:
            raise ValueError(
                f"Ya existe la sede '{existente['nombre']}' para el país {pais_codigo}"
            )
        cur = conn.execute(
            "INSERT INTO sedes (pais_codigo, nombre, direccion, activo) "
            "VALUES (?,?,?,1)",
            (pais_codigo, nombre, direccion)
        )
        sede_id = cur.lastrowid
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='sedes',
        entidad_id=sede_id,
        detalle={'pais_codigo': pais_codigo, 'nombre': nombre, 'direccion': direccion},
    )
    return {'id': sede_id, 'pais_codigo': pais_codigo,
            'nombre': nombre, 'direccion': direccion, 'activo': 1}


def actualizar_sede(sede_id: int, nombre: str = None, direccion: str = None,
                    usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, pais_codigo, nombre, direccion, activo "
            "FROM sedes WHERE id=?", (sede_id,)
        ).fetchone()
        if not row:
            return None

        campos = []
        params = []
        if nombre is not None:
            nuevo_nombre = _normalizar_texto(nombre)
            if not nuevo_nombre:
                raise ValueError("nombre no puede quedar vacío")
            # Comprobar duplicado insensible (excluyendo la propia fila)
            dup = conn.execute(
                "SELECT id FROM sedes WHERE pais_codigo=? AND LOWER(nombre)=LOWER(?) "
                "AND id<>?",
                (row['pais_codigo'], nuevo_nombre, sede_id)
            ).fetchone()
            if dup:
                raise ValueError(
                    f"Ya existe otra sede con nombre equivalente en {row['pais_codigo']}"
                )
            campos.append("nombre=?")
            params.append(nuevo_nombre)
        if direccion is not None:
            campos.append("direccion=?")
            params.append(direccion)
        if not campos:
            return dict(row)
        params.append(sede_id)
        conn.execute(
            f"UPDATE sedes SET {', '.join(campos)} WHERE id=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='sedes',
        entidad_id=sede_id,
        detalle={'cambios': {'nombre': nombre, 'direccion': direccion}},
    )
    return {'id': sede_id, 'pais_codigo': row['pais_codigo'],
            'nombre': nombre or row['nombre'],
            'direccion': direccion if direccion is not None else row['direccion'],
            'activo': row['activo']}


def cambiar_estado_sede(sede_id: int, activo: bool, usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, pais_codigo, nombre, activo FROM sedes WHERE id=?", (sede_id,)
        ).fetchone()
        if not row:
            return None
        if not activo:
            facturas_activas = conn.execute(
                "SELECT COUNT(*) AS n FROM facturas WHERE sede=? "
                "AND fecha_anulacion IS NULL",
                (row['nombre'],)
            ).fetchone()['n']
            if facturas_activas > 0:
                # Avisamos pero permitimos: las facturas históricas conservan
                # el nombre en columna legacy, no se rompen por desactivar sede.
                logger.warning(
                    f"Desactivando sede '{row['nombre']}' con {facturas_activas} "
                    f"factura(s) asociada(s). Las facturas conservan el dato histórico."
                )
        conn.execute(
            "UPDATE sedes SET activo=? WHERE id=?",
            (1 if activo else 0, sede_id)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='sedes',
        entidad_id=sede_id,
        detalle={'nombre': row['nombre'], 'activo': activo},
    )
    return {'id': sede_id, 'activo': activo}


def borrar_sede(sede_id: int, usuario: str = 'admin') -> bool:
    """
    Borrado físico. Solo se permite si la sede no tiene facturas asociadas.
    En caso contrario, usar cambio de estado (activo=0).
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, pais_codigo, nombre FROM sedes WHERE id=?", (sede_id,)
        ).fetchone()
        if not row:
            return False

        # Bloquear si hay suministros activos
        suministros = conn.execute(
            "SELECT COUNT(*) AS n FROM suministros WHERE sede_id=?", (sede_id,)
        ).fetchone()['n']
        if suministros > 0:
            raise ValueError(
                f"No se puede borrar: la sede tiene {suministros} suministro(s) "
                f"asociado(s). Desactívalos primero."
            )

        # Avisar (no bloquear) si hay facturas: se borra igualmente, las facturas
        # conservan el nombre en columna legacy.
        facturas = conn.execute(
            "SELECT COUNT(*) AS n FROM facturas WHERE sede=?", (row['nombre'],)
        ).fetchone()['n']
        if facturas > 0:
            logger.warning(
                f"Borrando sede '{row['nombre']}' con {facturas} factura(s) "
                f"histórica(s). Las facturas conservan el dato en columna legacy."
            )
        conn.execute("DELETE FROM sedes WHERE id=?", (sede_id,))
    registrar_evento(
        accion=ACCION_MAESTRO_BORRADO,
        usuario=usuario,
        entidad='sedes',
        entidad_id=sede_id,
        detalle={'pais_codigo': row['pais_codigo'], 'nombre': row['nombre']},
    )
    return True


# ── Comercializadoras ─────────────────────────────────────────────────────────

def listar_comercializadoras(pais_codigo: str = None, tipo_energia: str = None,
                              incluir_inactivos: bool = False) -> list[dict]:
    condiciones = []
    params = []
    if pais_codigo:
        condiciones.append("pais_codigo=?")
        params.append(_normalizar_codigo_pais(pais_codigo))
    if tipo_energia:
        condiciones.append("tipo_energia=?")
        params.append(tipo_energia)
    if not incluir_inactivos:
        condiciones.append("activo=1")
    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, pais_codigo, nombre, tipo_energia, activo "
            f"FROM comercializadoras {where} "
            f"ORDER BY pais_codigo, tipo_energia, nombre",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def crear_comercializadora(pais_codigo: str, nombre: str,
                            tipo_energia: str = 'electricidad',
                            usuario: str = 'admin') -> dict:
    pais_codigo = _normalizar_codigo_pais(pais_codigo)
    nombre = _normalizar_texto(nombre)
    if not pais_codigo or not nombre:
        raise ValueError("pais_codigo y nombre son obligatorios")

    with get_db_connection() as conn:
        pais = conn.execute(
            "SELECT codigo FROM paises WHERE codigo=?", (pais_codigo,)
        ).fetchone()
        if not pais:
            raise ValueError(f"No existe el país '{pais_codigo}'")

        existente = conn.execute(
            "SELECT id FROM comercializadoras "
            "WHERE pais_codigo=? AND nombre=? AND tipo_energia=?",
            (pais_codigo, nombre, tipo_energia)
        ).fetchone()
        if existente:
            raise ValueError(
                f"Ya existe la comercializadora '{nombre}' "
                f"({tipo_energia}) para {pais_codigo}"
            )
        cur = conn.execute(
            "INSERT INTO comercializadoras (pais_codigo, nombre, tipo_energia, activo) "
            "VALUES (?,?,?,1)",
            (pais_codigo, nombre, tipo_energia)
        )
        com_id = cur.lastrowid
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='comercializadoras',
        entidad_id=com_id,
        detalle={'pais_codigo': pais_codigo, 'nombre': nombre,
                 'tipo_energia': tipo_energia},
    )
    return {'id': com_id, 'pais_codigo': pais_codigo,
            'nombre': nombre, 'tipo_energia': tipo_energia, 'activo': 1}


def actualizar_comercializadora(com_id: int, nombre: str = None,
                                tipo_energia: str = None,
                                usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, pais_codigo, nombre, tipo_energia, activo "
            "FROM comercializadoras WHERE id=?", (com_id,)
        ).fetchone()
        if not row:
            return None

        campos = []
        params = []
        if nombre is not None:
            nuevo_nombre = _normalizar_texto(nombre)
            if not nuevo_nombre:
                raise ValueError("nombre no puede quedar vacío")
            campos.append("nombre=?")
            params.append(nuevo_nombre)
        if tipo_energia is not None:
            campos.append("tipo_energia=?")
            params.append(tipo_energia)
        if not campos:
            return dict(row)
        params.append(com_id)
        conn.execute(
            f"UPDATE comercializadoras SET {', '.join(campos)} WHERE id=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='comercializadoras',
        entidad_id=com_id,
        detalle={'cambios': {'nombre': nombre, 'tipo_energia': tipo_energia}},
    )
    return {'id': com_id, 'pais_codigo': row['pais_codigo'],
            'nombre': nombre or row['nombre'],
            'tipo_energia': tipo_energia or row['tipo_energia'],
            'activo': row['activo']}


def cambiar_estado_comercializadora(com_id: int, activo: bool,
                                     usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, nombre FROM comercializadoras WHERE id=?", (com_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE comercializadoras SET activo=? WHERE id=?",
            (1 if activo else 0, com_id)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='comercializadoras',
        entidad_id=com_id,
        detalle={'nombre': row['nombre'], 'activo': activo},
    )
    return {'id': com_id, 'activo': activo}


def borrar_comercializadora(com_id: int, usuario: str = 'admin') -> bool:
    """Borrado físico. Permitido siempre: las facturas conservan el dato legacy."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, nombre FROM comercializadoras WHERE id=?", (com_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM comercializadoras WHERE id=?", (com_id,))
    registrar_evento(
        accion=ACCION_MAESTRO_BORRADO,
        usuario=usuario,
        entidad='comercializadoras',
        entidad_id=com_id,
        detalle={'nombre': row['nombre']},
    )
    return True


# ── Tipos de energía ──────────────────────────────────────────────────────────

def listar_tipos_energia(incluir_inactivos: bool = False) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT codigo, nombre, unidad_medida, unidad_emision, activo "
            f"FROM tipos_energia "
            f"{'WHERE activo=1' if not incluir_inactivos else ''} "
            f"ORDER BY nombre"
        ).fetchall()
    return [dict(r) for r in rows]


def crear_tipo_energia(codigo: str, nombre: str, unidad_medida: str,
                        unidad_emision: str, usuario: str = 'admin') -> dict:
    codigo = _normalizar_texto(codigo).lower()
    nombre = _normalizar_texto(nombre)
    if not codigo or not nombre or not unidad_medida or not unidad_emision:
        raise ValueError("codigo, nombre, unidad_medida y unidad_emision son obligatorios")
    with get_db_connection() as conn:
        existente = conn.execute(
            "SELECT codigo FROM tipos_energia WHERE codigo=?", (codigo,)
        ).fetchone()
        if existente:
            raise ValueError(f"Ya existe el tipo de energía '{codigo}'")
        conn.execute(
            "INSERT INTO tipos_energia (codigo, nombre, unidad_medida, unidad_emision, activo) "
            "VALUES (?,?,?, ?,1)",
            (codigo, nombre, unidad_medida, unidad_emision)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='tipos_energia',
        entidad_id=None,
        detalle={'codigo': codigo, 'nombre': nombre,
                 'unidad_medida': unidad_medida, 'unidad_emision': unidad_emision},
    )
    return {'codigo': codigo, 'nombre': nombre,
            'unidad_medida': unidad_medida, 'unidad_emision': unidad_emision,
            'activo': 1}


def actualizar_tipo_energia(codigo: str, nombre: str = None,
                            unidad_medida: str = None, unidad_emision: str = None,
                            usuario: str = 'admin') -> dict | None:
    codigo = _normalizar_texto(codigo).lower()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT codigo, nombre, unidad_medida, unidad_emision, activo "
            "FROM tipos_energia WHERE codigo=?", (codigo,)
        ).fetchone()
        if not row:
            return None
        campos = []
        params = []
        if nombre is not None:
            campos.append("nombre=?")
            params.append(_normalizar_texto(nombre))
        if unidad_medida is not None:
            campos.append("unidad_medida=?")
            params.append(unidad_medida)
        if unidad_emision is not None:
            campos.append("unidad_emision=?")
            params.append(unidad_emision)
        if not campos:
            return dict(row)
        params.append(codigo)
        conn.execute(
            f"UPDATE tipos_energia SET {', '.join(campos)} WHERE codigo=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='tipos_energia',
        entidad_id=None,
        detalle={'codigo': codigo,
                 'cambios': {'nombre': nombre, 'unidad_medida': unidad_medida,
                             'unidad_emision': unidad_emision}},
    )
    return {'codigo': codigo,
            'nombre': nombre or row['nombre'],
            'unidad_medida': unidad_medida or row['unidad_medida'],
            'unidad_emision': unidad_emision or row['unidad_emision'],
            'activo': row['activo']}


def cambiar_estado_tipo_energia(codigo: str, activo: bool,
                                usuario: str = 'admin') -> dict | None:
    codigo = _normalizar_texto(codigo).lower()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT codigo FROM tipos_energia WHERE codigo=?", (codigo,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE tipos_energia SET activo=? WHERE codigo=?",
            (1 if activo else 0, codigo)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='tipos_energia',
        entidad_id=None,
        detalle={'codigo': codigo, 'activo': activo},
    )
    return {'codigo': codigo, 'activo': activo}


# ── Suministros ───────────────────────────────────────────────────────────────

def listar_suministros(pais_codigo: str = None, sede_id: int = None,
                        tipo_energia: str = None,
                        incluir_inactivos: bool = False) -> list[dict]:
    condiciones = []
    params = []
    if sede_id:
        condiciones.append("s.sede_id=?")
        params.append(sede_id)
    if tipo_energia:
        condiciones.append("s.tipo_energia=?")
        params.append(tipo_energia)
    if not incluir_inactivos:
        condiciones.append("s.activo=1")
    if pais_codigo:
        condiciones.append("sed.pais_codigo=?")
        params.append(_normalizar_codigo_pais(pais_codigo))
    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT s.id, s.sede_id, sed.pais_codigo, sed.nombre AS sede_nombre, "
            f"s.tipo_energia, s.referencia, s.notas, s.activo, s.fecha_alta, "
            f"s.sociedad_id, soc.nombre AS sociedad_nombre, soc.cif AS sociedad_cif "
            f"FROM suministros s "
            f"JOIN sedes sed ON sed.id = s.sede_id "
            f"LEFT JOIN sociedades soc ON soc.id = s.sociedad_id "
            f"{where} "
            f"ORDER BY sed.pais_codigo, sed.nombre, s.tipo_energia",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def crear_suministro(sede_id: int, tipo_energia: str = 'electricidad',
                      referencia: str = None, notas: str = None,
                      sociedad_id: int = None,
                      usuario: str = 'admin') -> dict:
    if not sede_id:
        raise ValueError("sede_id es obligatorio")
    tipo_energia = _normalizar_texto(tipo_energia) or 'electricidad'
    referencia = _normalizar_texto(referencia) if referencia else None
    with get_db_connection() as conn:
        sede = conn.execute(
            "SELECT id FROM sedes WHERE id=?", (sede_id,)
        ).fetchone()
        if not sede:
            raise ValueError(f"No existe la sede #{sede_id}")

        # Validar sociedad si se indica
        if sociedad_id:
            soc = conn.execute(
                "SELECT id, nombre FROM sociedades WHERE id=?", (sociedad_id,)
            ).fetchone()
            if not soc:
                raise ValueError(f"No existe la sociedad #{sociedad_id}")

        # UNIQUE(sede_id, tipo_energia, referencia). NULL referencia se trata
        # como igual en SQLite, así que comprobamos duplicado explícito.
        if referencia:
            dup = conn.execute(
                "SELECT id FROM suministros WHERE sede_id=? AND tipo_energia=? "
                "AND referencia=?",
                (sede_id, tipo_energia, referencia)
            ).fetchone()
        else:
            dup = conn.execute(
                "SELECT id FROM suministros WHERE sede_id=? AND tipo_energia=? "
                "AND referencia IS NULL",
                (sede_id, tipo_energia)
            ).fetchone()
        if dup:
            raise ValueError(
                f"Ya existe un suministro {tipo_energia} con esa referencia en la sede"
            )
        cur = conn.execute(
            "INSERT INTO suministros (sede_id, tipo_energia, referencia, notas, "
            "sociedad_id, activo) VALUES (?,?,?,?,?,1)",
            (sede_id, tipo_energia, referencia, notas, sociedad_id)
        )
        sum_id = cur.lastrowid
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='suministros',
        entidad_id=sum_id,
        detalle={'sede_id': sede_id, 'tipo_energia': tipo_energia,
                 'referencia': referencia, 'notas': notas,
                 'sociedad_id': sociedad_id},
    )
    return {'id': sum_id, 'sede_id': sede_id, 'tipo_energia': tipo_energia,
            'referencia': referencia, 'notas': notas,
            'sociedad_id': sociedad_id, 'activo': 1}


def actualizar_suministro(sum_id: int, tipo_energia: str = None,
                          referencia: str = None, notas: str = None,
                          sociedad_id: int = None,
                          usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, sede_id, tipo_energia, referencia, notas, activo, "
            "sociedad_id FROM suministros WHERE id=?", (sum_id,)
        ).fetchone()
        if not row:
            return None
        campos = []
        params = []
        if tipo_energia is not None:
            campos.append("tipo_energia=?")
            params.append(_normalizar_texto(tipo_energia))
        if referencia is not None:
            campos.append("referencia=?")
            params.append(_normalizar_texto(referencia) or None)
        if notas is not None:
            campos.append("notas=?")
            params.append(notas)
        if sociedad_id is not None:
            # sociedad_id puede venir como 0 o null para desasignar
            if sociedad_id:
                soc = conn.execute(
                    "SELECT id FROM sociedades WHERE id=?", (sociedad_id,)
                ).fetchone()
                if not soc:
                    raise ValueError(f"No existe la sociedad #{sociedad_id}")
            else:
                sociedad_id = None
            campos.append("sociedad_id=?")
            params.append(sociedad_id)
        if not campos:
            return dict(row)
        params.append(sum_id)
        conn.execute(
            f"UPDATE suministros SET {', '.join(campos)} WHERE id=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='suministros',
        entidad_id=sum_id,
        detalle={'cambios': {'tipo_energia': tipo_energia,
                             'referencia': referencia, 'notas': notas,
                             'sociedad_id': sociedad_id}},
    )
    return {'id': sum_id, 'sede_id': row['sede_id'],
            'tipo_energia': tipo_energia or row['tipo_energia'],
            'referencia': referencia if referencia is not None else row['referencia'],
            'notas': notas if notas is not None else row['notas'],
            'sociedad_id': sociedad_id if sociedad_id is not None else row['sociedad_id'],
            'activo': row['activo']}


def cambiar_estado_suministro(sum_id: int, activo: bool,
                               usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM suministros WHERE id=?", (sum_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE suministros SET activo=? WHERE id=?",
            (1 if activo else 0, sum_id)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='suministros',
        entidad_id=sum_id,
        detalle={'activo': activo},
    )
    return {'id': sum_id, 'activo': activo}


def borrar_suministro(sum_id: int, usuario: str = 'admin') -> bool:
    """
    Borrado físico. Solo se permite si no hay facturas que lo referencien.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM suministros WHERE id=?", (sum_id,)
        ).fetchone()
        if not row:
            return False
        facturas = conn.execute(
            "SELECT COUNT(*) AS n FROM facturas WHERE suministro_id=?", (sum_id,)
        ).fetchone()['n']
        if facturas > 0:
            raise ValueError(
                f"No se puede borrar: hay {facturas} factura(s) que referencian "
                f"este suministro. Desactívalo en su lugar."
            )
        conn.execute("DELETE FROM suministros WHERE id=?", (sum_id,))
    registrar_evento(
        accion=ACCION_MAESTRO_BORRADO,
        usuario=usuario,
        entidad='suministros',
        entidad_id=sum_id,
        detalle={},
    )
    return True


# ── Sociedades ────────────────────────────────────────────────────────────────

def listar_sociedades(pais_codigo: str = None, incluir_inactivos: bool = False) -> list[dict]:
    """
    Lista sociedades (entidades legales del grupo).

    Una sede puede tener varios CUPS, cada uno facturado a una sociedad distinta;
    por eso `sociedad_id` es un atributo del suministro, no de la sede.
    """
    condiciones = []
    params = []
    if pais_codigo:
        condiciones.append("pais_codigo=?")
        params.append(_normalizar_codigo_pais(pais_codigo))
    if not incluir_inactivos:
        condiciones.append("activo=1")
    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, nombre, cif, pais_codigo, activo, fecha_alta "
            f"FROM sociedades {where} ORDER BY nombre",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def crear_sociedad(nombre: str, cif: str = None, pais_codigo: str = None,
                    usuario: str = 'admin') -> dict:
    nombre = _normalizar_texto(nombre)
    cif = _normalizar_texto(cif) if cif else None
    if not nombre:
        raise ValueError("nombre es obligatorio")

    if pais_codigo:
        pais_codigo = _normalizar_codigo_pais(pais_codigo)
        with get_db_connection() as conn:
            pais = conn.execute(
                "SELECT codigo FROM paises WHERE codigo=?", (pais_codigo,)
            ).fetchone()
            if not pais:
                raise ValueError(f"No existe el país '{pais_codigo}'")

    with get_db_connection() as conn:
        # UNIQUE(nombre, cif): dos sociedades con mismo nombre solo se
        # diferencian por CIF. Si no hay CIF, el nombre debe ser único.
        if cif:
            existente = conn.execute(
                "SELECT id FROM sociedades WHERE nombre=? AND cif=?",
                (nombre, cif)
            ).fetchone()
        else:
            existente = conn.execute(
                "SELECT id FROM sociedades WHERE nombre=? AND (cif IS NULL OR cif='')",
                (nombre,)
            ).fetchone()
        if existente:
            raise ValueError(
                f"Ya existe la sociedad '{nombre}'"
                + (f" con CIF '{cif}'" if cif else " sin CIF")
            )
        cur = conn.execute(
            "INSERT INTO sociedades (nombre, cif, pais_codigo, activo) "
            "VALUES (?,?,?,1)",
            (nombre, cif, pais_codigo)
        )
        soc_id = cur.lastrowid
    registrar_evento(
        accion=ACCION_MAESTRO_CREADO,
        usuario=usuario,
        entidad='sociedades',
        entidad_id=soc_id,
        detalle={'nombre': nombre, 'cif': cif, 'pais_codigo': pais_codigo},
    )
    return {'id': soc_id, 'nombre': nombre, 'cif': cif,
            'pais_codigo': pais_codigo, 'activo': 1}


def actualizar_sociedad(soc_id: int, nombre: str = None, cif: str = None,
                        pais_codigo: str = None, usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, nombre, cif, pais_codigo, activo "
            "FROM sociedades WHERE id=?", (soc_id,)
        ).fetchone()
        if not row:
            return None

        campos = []
        params = []
        if nombre is not None:
            nuevo_nombre = _normalizar_texto(nombre)
            if not nuevo_nombre:
                raise ValueError("nombre no puede quedar vacío")
            campos.append("nombre=?")
            params.append(nuevo_nombre)
        if cif is not None:
            nuevo_cif = _normalizar_texto(cif) or None
            campos.append("cif=?")
            params.append(nuevo_cif)
        if pais_codigo is not None:
            nuevo_pais = _normalizar_codigo_pais(pais_codigo) or None
            if nuevo_pais:
                pais = conn.execute(
                    "SELECT codigo FROM paises WHERE codigo=?", (nuevo_pais,)
                ).fetchone()
                if not pais:
                    raise ValueError(f"No existe el país '{nuevo_pais}'")
            campos.append("pais_codigo=?")
            params.append(nuevo_pais)
        if not campos:
            return dict(row)
        params.append(soc_id)
        conn.execute(
            f"UPDATE sociedades SET {', '.join(campos)} WHERE id=?", params
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='sociedades',
        entidad_id=soc_id,
        detalle={'cambios': {'nombre': nombre, 'cif': cif,
                              'pais_codigo': pais_codigo}},
    )
    return {'id': soc_id,
            'nombre': nombre or row['nombre'],
            'cif': cif if cif is not None else row['cif'],
            'pais_codigo': pais_codigo if pais_codigo is not None else row['pais_codigo'],
            'activo': row['activo']}


def cambiar_estado_sociedad(soc_id: int, activo: bool,
                             usuario: str = 'admin') -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, nombre FROM sociedades WHERE id=?", (soc_id,)
        ).fetchone()
        if not row:
            return None
        # Avisar (no bloquear) si hay suministros activos vinculados
        if not activo:
            suministros = conn.execute(
                "SELECT COUNT(*) AS n FROM suministros "
                "WHERE sociedad_id=? AND activo=1", (soc_id,)
            ).fetchone()['n']
            if suministros > 0:
                logger.warning(
                    f"Desactivando sociedad '{row['nombre']}' con {suministros} "
                    f"suministro(s) activo(s)."
                )
        conn.execute(
            "UPDATE sociedades SET activo=? WHERE id=?",
            (1 if activo else 0, soc_id)
        )
    registrar_evento(
        accion=ACCION_MAESTRO_ESTADO,
        usuario=usuario,
        entidad='sociedades',
        entidad_id=soc_id,
        detalle={'nombre': row['nombre'], 'activo': activo},
    )
    return {'id': soc_id, 'activo': activo}


def borrar_sociedad(soc_id: int, usuario: str = 'admin') -> bool:
    """
    Borrado físico. Solo se permite si no hay suministros que lo referencien.
    En caso contrario, usar cambio de estado (activo=0).
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, nombre FROM sociedades WHERE id=?", (soc_id,)
        ).fetchone()
        if not row:
            return False
        suministros = conn.execute(
            "SELECT COUNT(*) AS n FROM suministros WHERE sociedad_id=?", (soc_id,)
        ).fetchone()['n']
        if suministros > 0:
            raise ValueError(
                f"No se puede borrar: hay {suministros} suministro(s) "
                f"vinculado(s) a esta sociedad. Desactívala en su lugar."
            )
        conn.execute("DELETE FROM sociedades WHERE id=?", (soc_id,))
    registrar_evento(
        accion=ACCION_MAESTRO_BORRADO,
        usuario=usuario,
        entidad='sociedades',
        entidad_id=soc_id,
        detalle={'nombre': row['nombre']},
    )
    return True


def vincular_suministro_sociedad(sum_id: int, sociedad_id: int | None,
                                  usuario: str = 'admin') -> dict | None:
    """
    Asigna la sociedad titular a un suministro (CUPS).

    Es la operación clave para el modelo "una sede → varios CUPS → varias
    sociedades": el titular del punto de suministro es la sociedad, no la sede.

    Si ``sociedad_id`` es ``None``, desvincula el suministro (lo deja sin
    sociedad titular, por ejemplo cuando una revisión manual detecta que
    hay facturas de varias sociedades y debe revisarse).
    """
    with get_db_connection() as conn:
        sum_row = conn.execute(
            "SELECT id FROM suministros WHERE id=?", (sum_id,)
        ).fetchone()
        if not sum_row:
            return None
        soc_nombre = None
        if sociedad_id is not None:
            soc_row = conn.execute(
                "SELECT id, nombre FROM sociedades WHERE id=?", (sociedad_id,)
            ).fetchone()
            if not soc_row:
                raise ValueError(f"No existe la sociedad #{sociedad_id}")
            soc_nombre = soc_row['nombre']
        conn.execute(
            "UPDATE suministros SET sociedad_id=? WHERE id=?",
            (sociedad_id, sum_id)
        )
    detalle = {'sociedad_id': sociedad_id}
    if soc_nombre:
        detalle['sociedad_nombre'] = soc_nombre
    registrar_evento(
        accion=ACCION_MAESTRO_ACTUALIZADO,
        usuario=usuario,
        entidad='suministros',
        entidad_id=sum_id,
        detalle=detalle,
    )
    return {'id': sum_id, 'sociedad_id': sociedad_id,
            'sociedad_nombre': soc_nombre}
