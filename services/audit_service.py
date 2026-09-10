"""
Servicio de auditoría transversal — Prioridad 2.

registrar_evento() es el único punto de entrada para escribir en audit_log.
Nunca propaga excepciones para no interrumpir el flujo principal de negocio.

registrar_cambio_factura() registra un cambio de campo en facturas_historial
dentro de una transacción activa (recibe el conn para garantizar atomicidad).

Constantes ACCION_* para consistencia de nombres entre módulos.
"""

import json
import logging
from database.connection import get_db_connection

logger = logging.getLogger(__name__)

# ── Constantes de acciones ────────────────────────────────────────────────────
# Facturas
ACCION_FACTURA_CARGADA        = 'factura_cargada'
ACCION_FACTURA_CONFIRMADA     = 'factura_confirmada'
ACCION_FACTURA_ANULADA        = 'factura_anulada'
ACCION_FACTURA_DUPLICADO      = 'factura_duplicado_detectado'

# Factores de emisión
ACCION_FACTOR_CREADO          = 'factor_creado'
ACCION_FACTOR_NUEVA_VERSION   = 'factor_nueva_version'
ACCION_FACTOR_EDITADO         = 'factor_editado'
ACCION_FACTOR_ESTADO          = 'factor_cambio_estado'

# Recálculo
ACCION_RECALCULO_EJECUTADO    = 'recalculo_ejecutado'
ACCION_RECALCULO_ANALIZADO    = 'recalculo_analizado'

# Estimaciones
ACCION_ESTIMACION_CREADA      = 'estimacion_creada'
ACCION_ESTIMACION_SUSTITUIDA  = 'estimacion_sustituida'
ACCION_ESTIMACION_RECHAZADA   = 'estimacion_rechazada'

# Lotes de carga
ACCION_LOTE_INICIADO          = 'lote_iniciado'
ACCION_LOTE_COMPLETADO        = 'lote_completado'

# Exportación y acceso a documentos
ACCION_EXPORTACION_EXCEL      = 'exportacion_excel'
ACCION_PDF_DESCARGADO         = 'pdf_descargado'

# Datos maestros (modo admin)
ACCION_MAESTRO_CREADO         = 'maestro_creado'
ACCION_MAESTRO_ACTUALIZADO   = 'maestro_actualizado'
ACCION_MAESTRO_ESTADO         = 'maestro_cambio_estado'
ACCION_MAESTRO_BORRADO        = 'maestro_borrado'


# ── Registro de eventos ───────────────────────────────────────────────────────

def registrar_evento(
    accion: str,
    usuario: str = 'sistema',
    entidad: str = None,
    entidad_id: int = None,
    detalle: dict = None,
    ip_origen: str = None,
    sesion_id: str = None,
) -> None:
    """
    Registra un evento en audit_log.

    SILENCIOSO: nunca propaga excepciones para no interrumpir el flujo principal.
    Si falla el registro, solo se escribe en el log de aplicación.

    Parameters
    ----------
    accion      : constante ACCION_* definida en este módulo.
    usuario     : identificador del usuario que realiza la acción.
                  Futuro: extraer del JWT token en lugar del body.
    entidad     : nombre de la tabla/entidad afectada ('factura', 'factor'…).
    entidad_id  : PK de la entidad afectada. None para acciones sin entidad concreta.
    detalle     : dict con contexto adicional (snapshot antes/después, parámetros…).
                  Se serializa a JSON. Los valores no serializables usan str().
    ip_origen   : IP del cliente. Disponible en rutas como request.remote_addr.
                  None en llamadas desde servicios sin contexto HTTP.
    sesion_id   : Futuro: JWT jti para rastrear sesiones de usuario.
    """
    try:
        detalle_json = (
            json.dumps(detalle, ensure_ascii=False, default=str)
            if detalle else None
        )
        with get_db_connection() as conn:
            conn.execute(
                '''INSERT INTO audit_log
                       (usuario, accion, entidad, entidad_id,
                        detalle_json, ip_origen, sesion_id)
                   VALUES (?,?,?,?,?,?,?)''',
                (usuario, accion, entidad, entidad_id,
                 detalle_json, ip_origen, sesion_id)
            )
    except Exception as exc:
        logger.error(f"[AuditLog] No se pudo registrar '{accion}' "
                     f"(entidad={entidad}, id={entidad_id}): {exc}")


# ── Trazabilidad de cambios en facturas ───────────────────────────────────────

def registrar_cambio_factura(
    conn,
    factura_id: int,
    campo: str,
    valor_anterior,
    valor_nuevo,
    usuario: str = 'usuario',
    motivo: str = None,
) -> None:
    """
    Registra un cambio de campo en facturas_historial dentro de una transacción.

    Debe llamarse con el conn activo del bloque `with get_db_connection()` que
    también ejecuta el UPDATE de la factura, garantizando atomicidad.

    Parameters
    ----------
    conn           : conexión SQLite activa (del contexto get_db_connection).
    factura_id     : ID de la factura modificada.
    campo          : nombre del campo modificado.
    valor_anterior : valor antes del cambio (se convierte a str; None → NULL).
    valor_nuevo    : valor después del cambio.
    usuario        : quién realizó el cambio.
    motivo         : razón del cambio (opcional, para auditorías).
    """
    try:
        conn.execute(
            '''INSERT INTO facturas_historial
                   (factura_id, campo, valor_anterior, valor_nuevo, usuario, motivo)
               VALUES (?,?,?,?,?,?)''',
            (
                factura_id,
                campo,
                str(valor_anterior) if valor_anterior is not None else None,
                str(valor_nuevo)    if valor_nuevo    is not None else None,
                usuario,
                motivo,
            )
        )
    except Exception as exc:
        logger.error(
            f"[FacturasHistorial] Error registrando cambio "
            f"factura #{factura_id}.{campo}: {exc}"
        )
