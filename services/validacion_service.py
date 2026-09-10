"""
Punto único de validación del pipeline de extracción (Mejora #4).

Antes existían 3 motores de detección de inconsistencias sin relación entre
sí, con umbrales a veces distintos para el mismo concepto:
  1. extraccion_service.detectar_inconsistencias()   — en el momento de extracción.
  2. ocr_quality_service.validar_con_historico()      — contra histórico de sede.
  3. alertas_service.py                                — asíncrono, post-persistencia.

Este módulo no sustituye a alertas_service.py (los detectores cross-factura
como el z-score global sí tienen sentido como job periódico), pero unifica
los pasos 1 y 2 —los que deben correr SIEMPRE antes de persistir una
factura— en un único punto de entrada con umbrales compartidos desde
config.py.
"""
import logging
from database.connection import get_db_connection
from services.extraccion_service import detectar_inconsistencias
from services.ocr_quality_service import validar_con_historico, crear_incidencia
import config

logger = logging.getLogger(__name__)


def validar_limite_fisico_consumo(consumo_kwh: float, dias_facturados: int | None) -> dict | None:
    """
    Bound físico absoluto de kWh/día, independiente de la confianza OCR y del
    histórico de sede (que ya cubren detectar_inconsistencias/validar_con_historico).
    Ver justificación completa en el plan de mejora, Sección 3 ("consumo imposible").
    """
    if not consumo_kwh or not dias_facturados or dias_facturados <= 0:
        return None
    kwh_dia = consumo_kwh / dias_facturados
    limite_min = getattr(config, 'CONSUMO_KWH_DIA_MIN', 0.05)
    limite_max = getattr(config, 'CONSUMO_KWH_DIA_MAX', 10000.0)
    if kwh_dia < limite_min or kwh_dia > limite_max:
        return crear_incidencia(
            tipo="consumo_limite_fisico",
            campo="consumo",
            severidad="critica",
            mensaje=(f"Consumo fuera de límite físico: {kwh_dia:.2f} kWh/día "
                     f"(rango válido: {limite_min}-{limite_max}). Revisión obligatoria."),
            penalizacion=0.0,  # no penaliza confianza: es un veto duro, no una señal de duda
            evidencia={"kwh_dia": round(kwh_dia, 3), "limite_min": limite_min, "limite_max": limite_max},
        )
    return None


def validar_factura_completa(datos, pais: str, sede: str,
                              tipo_energia: str = 'electricidad',
                              conn=None) -> tuple[list[dict], bool]:
    """
    Ejecuta, en orden, todas las validaciones síncronas (baratas → históricas)
    que deben correr ANTES de persistir una factura.

    Parameters
    ----------
    datos : DatosFactura ya extraída (ExtractorFactory.get(...).extraer(...)).
    conn  : conexión SQLite activa opcional. Si no se pasa, se abre una nueva
            (uso típico fuera del flujo de lote_service, p.ej. en un script).

    Returns
    -------
    (incidencias, forzar_revision)
      incidencias      : lista de dicts estructurados (crear_incidencia), ya
                          incluye las de extraccion_service + histórico + límite físico.
      forzar_revision  : True si alguna incidencia es de severidad 'critica'.
    """
    incidencias: list[dict] = list(getattr(datos, 'incidencias_estructuradas', None) or [])
    # Si extraccion_service.detectar_inconsistencias ya corrió dentro de
    # extraer_datos_factura() (caso normal en el pipeline actual), sus
    # incidencias ya están en datos.incidencias_estructuradas (ver QW7).
    # Si no (uso directo de este módulo, p.ej. en tests), se ejecuta aquí:
    if not incidencias:
        incidencias = detectar_inconsistencias(datos)

    def _ejecutar_con_conn(c):
        incidencias.extend(validar_con_historico(datos, c, pais, sede, tipo_energia))

    if conn is not None:
        _ejecutar_con_conn(conn)
    else:
        with get_db_connection() as conn_local:
            _ejecutar_con_conn(conn_local)

    limite = validar_limite_fisico_consumo(datos.consumo_kwh, datos.dias_facturados)
    if limite:
        incidencias.append(limite)

    forzar_revision = any(inc.get('severidad') == 'critica' for inc in incidencias)
    return incidencias, forzar_revision