"""
Blueprint: exportación de datos a Excel con formato enriquecido (Fase 1).

El Excel incluye las 15 columnas definidas en el plan:
  País | Sede | Sociedad | Comercializadora | Dirección suministro |
  Fecha factura | Período inicio | Período fin | Días facturados |
  Consumo (kWh) | Consumo (MWh) | Factor (kg CO₂/MWh) | Fuente factor |
  Emisiones (tCO₂e) | Fecha carga

Cambios P7:
  - Solo exporta facturas activas (fecha_anulacion IS NULL).
  - Limpieza garantizada del archivo temporal (try/finally).
  - Registro en audit_log de cada exportación.
"""

import os
import tempfile
import logging
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from openpyxl.styles import Alignment, Font, PatternFill

from database.connection import get_db_connection
from routes._helpers import server_error
from services.audit_service import registrar_evento, ACCION_EXPORTACION_EXCEL

logger = logging.getLogger(__name__)

exportacion_bp = Blueprint('exportacion', __name__)


@exportacion_bp.route('/api/descargar-excel')
def descargar_excel():
    """
    Genera y devuelve un Excel con las facturas activas.
    Acepta los mismos filtros que /api/historial: pais, sede, anio.
    """
    pais    = request.args.get('pais', '').upper() or None
    sede    = request.args.get('sede') or None
    anio    = request.args.get('anio') or None
    usuario = request.args.get('usuario', 'usuario')

    condiciones: list[str] = ['f.fecha_anulacion IS NULL']
    params: list = []

    if pais:
        condiciones.append('f.pais = ?'); params.append(pais)
    if sede:
        condiciones.append('f.sede = ?'); params.append(sede)
    if anio:
        condiciones.append(
            "(strftime('%Y', f.periodo_inicio) = ? OR strftime('%Y', f.fecha_carga) = ?)"
        )
        params.extend([anio, anio])

    where = f"WHERE {' AND '.join(condiciones)}"

    ruta = None
    try:
        with get_db_connection() as conn:
            df = pd.read_sql_query(
                f'''SELECT
                       f.pais               AS "País",
                       f.sede               AS "Sede",
                       f.sociedad           AS "Sociedad",
                       f.comercializadora   AS "Comercializadora",
                       f.direccion_suministro AS "Dirección suministro",
                       f.fecha_factura      AS "Fecha factura",
                       f.periodo_inicio     AS "Período inicio",
                       f.periodo_fin        AS "Período fin",
                       f.dias_facturados    AS "Días facturados",
                       f.consumo_kwh        AS "Consumo (kWh)",
                       f.consumo_mwh        AS "Consumo (MWh)",
                       f.factor_emision     AS "Factor emisión (kg CO₂/MWh)",
                       COALESCE(fe.fuente, '') AS "Fuente factor",
                       f.emisiones_tco2e    AS "Emisiones (tCO₂e)",
                       f.importe_total      AS "Importe",
                       f.moneda             AS "Moneda",
                       f.tarifa             AS "Tarifa",
                       f.potencia_kw        AS "Potencia contratada (kW)",
                       f.contrato           AS "Ref. contrato",
                       f.distribuidora      AS "Distribuidora",
                       f.tipo_dato          AS "Tipo dato",
                       f.fecha_carga        AS "Fecha carga"
                   FROM facturas f
                   LEFT JOIN factores_emision fe ON fe.id = f.factor_version_id
                   {where}
                   ORDER BY f.fecha_carga DESC''',
                conn, params=params
            )

        if df.empty:
            return jsonify({'exito': False, 'error': 'No hay facturas para exportar'}), 400

        nombre = f"facturas_HC_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        ruta   = os.path.join(tempfile.gettempdir(), nombre)

        with pd.ExcelWriter(ruta, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Facturas Eléctricas')
            _aplicar_estilo(writer.sheets['Facturas Eléctricas'])

        logger.info(f"📥 Excel generado: {nombre}  ({len(df)} filas)")

        registrar_evento(
            accion=ACCION_EXPORTACION_EXCEL,
            usuario=usuario,
            detalle={'filas': len(df), 'filtros': {'pais': pais, 'sede': sede, 'anio': anio}},
            ip_origen=request.remote_addr,
        )

        return send_file(ruta, as_attachment=True, download_name=nombre)

    except Exception as exc:
        return server_error(exc, contexto="Exportación Excel")

    finally:
        # Garantizar limpieza del temporal incluso si send_file lanza excepción
        if ruta and os.path.exists(ruta):
            try:
                os.unlink(ruta)
            except OSError as exc_clean:
                logger.warning(f"No se pudo eliminar temporal {ruta}: {exc_clean}")


def _aplicar_estilo(ws):
    """Aplica formato visual: cabecera azul, anchos ajustados, números alineados."""
    header_fill = PatternFill(start_color='1E3C72', end_color='1E3C72', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=10)
    center      = Alignment(horizontal='center', vertical='center', wrap_text=False)

    for cell in ws[1]:
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = center

    for col in ws.columns:
        max_len = max(
            (len(str(cell.value)) if cell.value is not None else 0)
            for cell in col
        )
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 45)

    ws.freeze_panes = 'A2'
