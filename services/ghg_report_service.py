"""
Servicio de Informe GHG Protocol — Fase 4.

Genera un informe exportable (Excel) compatible con GHG Protocol y CSRD,
con estructura modular para añadir PDF en el futuro sin rediseñar la lógica.

Estructura del informe:
  1. Resumen ejecutivo
  2. Scope 1 — Emisiones directas
  3. Scope 2 — Electricidad comprada
  4. Scope 3 — Otras emisiones indirectas
  5. Metodología — Factores utilizados y fuentes
  6. Calidad del dato — % reales / estimados / faltantes
  7. Trazabilidad — Recálculos, modificaciones y evidencia documental

Diseño:
  - _recopilar_datos_informe() genera un dict con todos los datos del informe.
  - generar_excel() convierte ese dict en un archivo Excel con hojas separadas.
  - El dict puede usarse directamente para un futuro módulo PDF sin cambios.
"""

import io
import logging
import os
import tempfile
from datetime import date, datetime
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database.connection import get_db_connection

logger = logging.getLogger(__name__)

# Paleta corporativa
COLOR_HEADER     = "1E3C72"
COLOR_SUBHEADER  = "2A5298"
COLOR_SCOPE1     = "C0392B"
COLOR_SCOPE2     = "2980B9"
COLOR_SCOPE3     = "27AE60"
COLOR_GRAY_LIGHT = "F2F2F2"
COLOR_GRAY_MID   = "CCCCCC"


# ── Punto de entrada público ──────────────────────────────────────────────────

def generar_informe_excel(anio: str = None,
                          pais: str = None,
                          tipo_energia: str = None) -> tuple[bytes, str]:
    """
    Genera el informe GHG Protocol completo en Excel.

    Returns (bytes_excel, nombre_archivo)
    El nombre contiene el año y los filtros para facilitar la trazabilidad.
    """
    anio = anio or str(date.today().year)
    datos = _recopilar_datos_informe(anio, pais, tipo_energia)
    excel_bytes = _construir_excel(datos)

    sufijo = f"_{pais}" if pais else ""
    nombre = f"Informe_GHG_{anio}{sufijo}_{date.today().strftime('%Y%m%d')}.xlsx"
    return excel_bytes, nombre


def preview_informe(anio: str = None,
                    pais: str = None,
                    tipo_energia: str = None) -> dict:
    """
    Devuelve los datos del informe en JSON para previsualización en el frontend.
    Misma lógica que generar_informe_excel pero sin construir el Excel.
    """
    anio = anio or str(date.today().year)
    return _recopilar_datos_informe(anio, pais, tipo_energia)


# ── Recopilación de datos ─────────────────────────────────────────────────────

def _recopilar_datos_informe(anio: str, pais: str = None,
                              tipo_energia: str = None) -> dict[str, Any]:
    """
    Consulta toda la información necesaria para el informe.
    Devuelve un dict estructurado por secciones.
    Fase 5: añade sección por sociedad.
    """
    with get_db_connection() as conn:
        resumen     = _seccion_resumen(conn, anio, pais, tipo_energia)
        scopes      = _seccion_scopes(conn, anio, pais, tipo_energia)
        metodologia = _seccion_metodologia(conn, anio, pais, tipo_energia)
        calidad     = _seccion_calidad(conn, anio, pais, tipo_energia)
        trazabilidad = _seccion_trazabilidad(conn, anio, pais, tipo_energia)
        detalle     = _seccion_detalle_facturas(conn, anio, pais, tipo_energia)
        por_sociedad = _seccion_por_sociedad(conn, anio, pais, tipo_energia)
        sedes_por_sociedad = _seccion_sedes_por_sociedad(conn, anio, pais, tipo_energia)

    return {
        'meta': {
            'anio': anio,
            'pais': pais,
            'tipo_energia': tipo_energia,
            'fecha_generacion': datetime.now().isoformat(),
            'version': '1.2',
        },
        'resumen': resumen,
        'scopes': scopes,
        'metodologia': metodologia,
        'calidad': calidad,
        'trazabilidad': trazabilidad,
        'detalle_facturas': detalle,
        'por_sociedad': por_sociedad,
        'sedes_por_sociedad': sedes_por_sociedad,
    }


def _seccion_resumen(conn, anio: str, pais: str, tipo_energia: str) -> dict:
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)

    row = conn.execute(
        f'''SELECT COUNT(*) as n_facturas,
                   COALESCE(SUM(emisiones_tco2e), 0) as total_tco2e,
                   COALESCE(SUM(consumo_mwh), 0) as total_mwh,
                   COUNT(DISTINCT pais) as n_paises,
                   COUNT(DISTINCT sede) as n_sedes
            FROM facturas f WHERE {filtro_base}''',
        params_base
    ).fetchone()

    return {
        'anio': anio,
        'n_facturas': row['n_facturas'],
        'total_emisiones_tco2e': round(row['total_tco2e'], 4),
        'total_consumo_mwh': round(row['total_mwh'], 2),
        'n_paises': row['n_paises'],
        'n_sedes': row['n_sedes'],
        'por_pais': [
            {'pais': r['pais'],
             'emisiones_tco2e': round(r['em'] or 0, 4),
             'consumo_mwh': round(r['cons'] or 0, 2),
             'n_facturas': r['n']}
            for r in conn.execute(
                f'''SELECT pais,
                           SUM(emisiones_tco2e) as em,
                           SUM(consumo_mwh) as cons,
                           COUNT(*) as n
                    FROM facturas f WHERE {filtro_base}
                    GROUP BY pais ORDER BY em DESC''',
                params_base
            )
        ],
    }


def _seccion_scopes(conn, anio: str, pais: str, tipo_energia: str) -> dict:
    """Agrupa emisiones por Scope GHG."""
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)

    # Scope por factor
    try:
        rows_scope = conn.execute(
            f'''SELECT COALESCE(fe.scope_ghg, 2) as scope,
                       COALESCE(te.nombre, f.tipo_energia) as energia,
                       SUM(f.emisiones_tco2e) as emisiones,
                       SUM(f.consumo_mwh) as consumo,
                       COUNT(*) as n_facturas
                FROM facturas f
                LEFT JOIN factores_emision fe ON fe.id = f.factor_version_id
                LEFT JOIN tipos_energia te ON te.codigo = f.tipo_energia
                WHERE {filtro_base}
                GROUP BY scope, f.tipo_energia, te.nombre
                ORDER BY scope''',
            params_base
        ).fetchall()
    except Exception:
        rows_scope = []

    scopes = {1: [], 2: [], 3: []}
    totales = {1: 0.0, 2: 0.0, 3: 0.0}

    for r in rows_scope:
        sc = r['scope'] or 2
        if sc not in scopes:
            sc = 2
        item = {
            'energia': r['energia'],
            'emisiones_tco2e': round(r['emisiones'] or 0, 4),
            'consumo_mwh': round(r['consumo'] or 0, 2),
            'n_facturas': r['n_facturas'],
        }
        scopes[sc].append(item)
        totales[sc] += r['emisiones'] or 0

    total_global = sum(totales.values())
    return {
        'scope_1': {
            'descripcion': 'Emisiones directas (combustión, procesos, etc.)',
            'total_tco2e': round(totales[1], 4),
            'detalle': scopes[1],
        },
        'scope_2': {
            'descripcion': 'Emisiones indirectas — electricidad comprada',
            'total_tco2e': round(totales[2], 4),
            'detalle': scopes[2],
        },
        'scope_3': {
            'descripcion': 'Otras emisiones indirectas (viajes, residuos, etc.)',
            'total_tco2e': round(totales[3], 4),
            'detalle': scopes[3],
        },
        'total_tco2e': round(total_global, 4),
    }


def _seccion_metodologia(conn, anio: str, pais: str, tipo_energia: str) -> dict:
    """Factores de emisión utilizados con fuente y versión."""
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)
    try:
        rows = conn.execute(
            f'''SELECT DISTINCT fe.pais, fe.tipo_energia, fe.anio,
                       fe.factor_kg_co2_mwh, fe.fuente, fe.url,
                       fe.version, fe.fecha_vigencia_desde,
                       COALESCE(fe.scope_ghg, 2) as scope_ghg,
                       COUNT(f.id) as n_facturas_usadas
                FROM facturas f
                JOIN factores_emision fe ON fe.id = f.factor_version_id
                WHERE {filtro_base}
                GROUP BY fe.id
                ORDER BY fe.pais, fe.tipo_energia, fe.anio''',
            params_base
        ).fetchall()
    except Exception:
        rows = []

    factores = [
        {
            'pais': r['pais'],
            'tipo_energia': r['tipo_energia'],
            'anio': r['anio'],
            'factor_kg_co2_mwh': r['factor_kg_co2_mwh'],
            'fuente': r['fuente'],
            'url': r['url'],
            'version': r['version'],
            'fecha_vigencia_desde': r['fecha_vigencia_desde'],
            'scope_ghg': r['scope_ghg'],
            'n_facturas_usadas': r['n_facturas_usadas'],
        }
        for r in rows
    ]

    # Nota metodológica
    nota = (
        "Las emisiones de CO₂ equivalente se calculan siguiendo el GHG Protocol "
        "Corporate Standard. Fórmula: tCO₂e = Consumo (MWh) × Factor (kg CO₂/MWh) / 1000. "
        "Los factores de emisión de electricidad son factores de red (market-based para Scope 2). "
        "Los datos reales provienen de facturas electrónicas verificadas. "
        "Los datos estimados se obtienen por extrapolación estadística de series históricas."
    )

    return {'factores': factores, 'nota_metodologica': nota}


def _seccion_calidad(conn, anio: str, pais: str, tipo_energia: str) -> dict:
    """Indicadores de calidad del dato para el informe."""
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)

    total = conn.execute(
        f'SELECT COUNT(*) FROM facturas f WHERE {filtro_base}', params_base
    ).fetchone()[0]

    reales = conn.execute(
        f"SELECT COUNT(*) FROM facturas f WHERE {filtro_base} AND f.tipo_dato='real'",
        params_base
    ).fetchone()[0]

    estimados_f = conn.execute(
        f"SELECT COUNT(*) FROM facturas f WHERE {filtro_base} AND f.tipo_dato='estimado'",
        params_base
    ).fetchone()[0]

    # Estimaciones vigentes
    cond_est = ["estado='vigente'", "substr(mes,1,4)=?"]
    p_est = [anio]
    if pais:
        cond_est.append("pais=?"); p_est.append(pais)
    if tipo_energia:
        cond_est.append("tipo_energia=?"); p_est.append(tipo_energia)

    estimados_tabla = conn.execute(
        f"SELECT COUNT(*) FROM estimaciones WHERE {' AND '.join(cond_est)}", p_est
    ).fetchone()[0]

    # Periodos faltantes
    cond_pf = ["anio=?"]
    p_pf = [anio]
    if pais:
        cond_pf.append("pais=?"); p_pf.append(pais)
    if tipo_energia:
        cond_pf.append("tipo_energia=?"); p_pf.append(tipo_energia)

    faltantes = conn.execute(
        f"SELECT COUNT(*) FROM periodos_faltantes WHERE {' AND '.join(cond_pf)} AND estado='faltante'",
        p_pf
    ).fetchone()[0]

    total_puntos = (reales + estimados_tabla + faltantes) or 1

    # OCR
    ocr_bajo = conn.execute(
        f'''SELECT COUNT(*) FROM facturas f
            WHERE {filtro_base} AND f.confianza_ocr IS NOT NULL AND f.confianza_ocr < 0.7''',
        params_base
    ).fetchone()[0]

    ocr_avg_row = conn.execute(
        f'''SELECT AVG(f.confianza_ocr) FROM facturas f
            WHERE {filtro_base} AND f.confianza_ocr IS NOT NULL''',
        params_base
    ).fetchone()[0]

    return {
        'total_facturas': total,
        'facturas_reales': reales,
        'facturas_estimadas': estimados_f + estimados_tabla,
        'periodos_faltantes': faltantes,
        'pct_real': round(reales / total_puntos * 100, 1),
        'pct_estimado': round(estimados_tabla / total_puntos * 100, 1),
        'pct_faltante': round(faltantes / total_puntos * 100, 1),
        'facturas_ocr_bajo': ocr_bajo,
        'confianza_ocr_media': round(ocr_avg_row or 0, 3),
        'nivel_calidad': _nivel_calidad(reales / total_puntos * 100),
    }


def _seccion_trazabilidad(conn, anio: str, pais: str, tipo_energia: str) -> dict:
    """Resumen de trazabilidad para auditorías."""
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)

    # Número de recálculos
    try:
        n_recalculos = conn.execute(
            f'''SELECT COUNT(*) FROM recalculos_historial rh
                JOIN facturas f ON f.id = rh.factura_id
                WHERE {filtro_base}''',
            params_base
        ).fetchone()[0]
    except Exception:
        n_recalculos = 0

    # Modificaciones manuales
    try:
        n_modificaciones = conn.execute(
            f'''SELECT COUNT(*) FROM facturas_historial fh
                JOIN facturas f ON f.id = fh.factura_id
                WHERE {filtro_base}''',
            params_base
        ).fetchone()[0]
    except Exception:
        n_modificaciones = 0

    # Facturas con documento adjunto
    n_con_doc = conn.execute(
        f'''SELECT COUNT(*) FROM facturas f
            WHERE {filtro_base}
              AND f.archivo_ruta IS NOT NULL AND f.archivo_ruta <> ''
        ''',
        params_base
    ).fetchone()[0]

    total_f = conn.execute(
        f'SELECT COUNT(*) FROM facturas f WHERE {filtro_base}', params_base
    ).fetchone()[0]

    # Estimaciones y precisión
    try:
        n_estimaciones = conn.execute(
            f"SELECT COUNT(*) FROM estimaciones WHERE substr(mes,1,4)=?", (anio,)
        ).fetchone()[0]
        estimaciones_sustituidas = conn.execute(
            f"SELECT COUNT(*) FROM estimaciones WHERE substr(mes,1,4)=? AND estado='sustituida'",
            (anio,)
        ).fetchone()[0]
        error_medio = conn.execute(
            f'''SELECT AVG(desviacion_porcentual_real) FROM estimaciones
                WHERE substr(mes,1,4)=? AND estado='sustituida'
                  AND desviacion_porcentual_real IS NOT NULL''',
            (anio,)
        ).fetchone()[0]
    except Exception:
        n_estimaciones = estimaciones_sustituidas = 0
        error_medio = None

    return {
        'n_recalculos': n_recalculos,
        'n_modificaciones_manuales': n_modificaciones,
        'n_facturas_con_documento': n_con_doc,
        'n_facturas_total': total_f,
        'pct_con_documento': round(n_con_doc / total_f * 100, 1) if total_f else 0,
        'n_estimaciones': n_estimaciones,
        'n_estimaciones_sustituidas': estimaciones_sustituidas,
        'error_medio_estimaciones_pct': round(error_medio, 2) if error_medio else None,
    }


def _seccion_detalle_facturas(conn, anio: str, pais: str, tipo_energia: str) -> list:
    """Detalle de facturas para la hoja de datos completos del Excel."""
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia)
    rows = conn.execute(
        f'''SELECT f.pais, f.sede, f.sociedad, f.comercializadora,
                   f.tipo_energia, f.periodo_inicio, f.periodo_fin,
                   f.consumo_kwh, f.consumo_mwh,
                   f.factor_emision, f.emisiones_tco2e,
                   COALESCE(fe.scope_ghg, 2) as scope_ghg,
                   fe.fuente as fuente_factor, fe.version as version_factor,
                   f.tipo_dato, f.confianza_ocr, f.estado,
                   f.fecha_carga
            FROM facturas f
            LEFT JOIN factores_emision fe ON fe.id = f.factor_version_id
            WHERE {filtro_base}
            ORDER BY f.pais, f.sede, f.periodo_inicio''',
        params_base
    ).fetchall()
    return [dict(r) for r in rows]


# ── Constructor Excel ─────────────────────────────────────────────────────────

def _construir_excel(datos: dict) -> bytes:
    """Construye el workbook Excel a partir del dict de datos del informe."""
    wb = Workbook()
    wb.remove(wb.active)  # eliminar hoja por defecto

    _hoja_resumen(wb, datos)
    _hoja_emisiones_scope(wb, datos)
    _hoja_metodologia(wb, datos)
    _hoja_calidad(wb, datos)
    _hoja_trazabilidad(wb, datos)
    _hoja_detalle(wb, datos)
    _hoja_por_sociedad(wb, datos)
    _hoja_sedes_por_sociedad(wb, datos)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _hoja_resumen(wb: Workbook, datos: dict):
    ws = wb.create_sheet("1. Resumen Ejecutivo")
    m = datos['meta']
    r = datos['resumen']
    s = datos['scopes']
    c = datos['calidad']

    _titulo(ws, 1, 1, f"INFORME GHG PROTOCOL — AÑO {m['anio']}", span=6)
    _subtitulo(ws, 2, 1, f"Generado: {m['fecha_generacion'][:10]}  |  Portal de Datos Ambientales")

    ws.append([])
    _seccion_header(ws, ws.max_row + 1, 1, "RESUMEN EJECUTIVO", span=4)

    datos_res = [
        ("Año analizado", m['anio']),
        ("País / Filtro", m['pais'] or "Todos"),
        ("Tipo energía", m['tipo_energia'] or "Todos"),
        ("Nº de facturas", r['n_facturas']),
        ("Nº de países", r['n_paises']),
        ("Nº de sedes", r['n_sedes']),
        ("", ""),
        ("EMISIONES TOTALES (tCO₂e)", r['total_emisiones_tco2e']),
        ("  Scope 1 (directo)", s['scope_1']['total_tco2e']),
        ("  Scope 2 (electricidad)", s['scope_2']['total_tco2e']),
        ("  Scope 3 (indirecto)", s['scope_3']['total_tco2e']),
        ("", ""),
        ("CONSUMO TOTAL (MWh)", r['total_consumo_mwh']),
        ("", ""),
        ("CALIDAD DEL DATO", ""),
        ("  % Datos reales", f"{c['pct_real']}%"),
        ("  % Datos estimados", f"{c['pct_estimado']}%"),
        ("  % Datos faltantes", f"{c['pct_faltante']}%"),
        ("  Nivel de calidad", c['nivel_calidad']),
    ]
    for label, value in datos_res:
        row = ws.max_row + 1
        ws.cell(row, 1, label).font = Font(bold=bool(label and not label.startswith(" ")))
        ws.cell(row, 2, value)

    # Por país
    if r['por_pais']:
        ws.append([])
        _seccion_header(ws, ws.max_row + 1, 1, "EMISIONES POR PAÍS", span=4)
        _fila_cabecera(ws, ws.max_row + 1, ["País", "tCO₂e", "MWh", "Facturas"])
        for pp in r['por_pais']:
            ws.append([pp['pais'], pp['emisiones_tco2e'], pp['consumo_mwh'], pp['n_facturas']])

    _autofit(ws)


def _hoja_emisiones_scope(wb: Workbook, datos: dict):
    ws = wb.create_sheet("2. Emisiones por Scope")
    m, s = datos['meta'], datos['scopes']
    _titulo(ws, 1, 1, f"EMISIONES POR SCOPE GHG — {m['anio']}", span=5)

    scope_info = [
        ('scope_1', 'SCOPE 1 — EMISIONES DIRECTAS', COLOR_SCOPE1),
        ('scope_2', 'SCOPE 2 — ELECTRICIDAD COMPRADA', COLOR_SCOPE2),
        ('scope_3', 'SCOPE 3 — EMISIONES INDIRECTAS', COLOR_SCOPE3),
    ]

    for key, titulo, color in scope_info:
        scope_data = s[key]
        ws.append([])
        row = ws.max_row + 1
        cell = ws.cell(row, 1, titulo)
        cell.font = Font(bold=True, color="FFFFFF", size=12)
        cell.fill = PatternFill("solid", fgColor=color)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        cell.alignment = Alignment(horizontal='center')

        desc_row = ws.max_row + 1
        ws.cell(desc_row, 1, scope_data['descripcion'])
        ws.cell(desc_row, 2, f"Total: {scope_data['total_tco2e']} tCO₂e").font = Font(bold=True)

        if scope_data['detalle']:
            _fila_cabecera(ws, ws.max_row + 1, ["Tipo Energía", "tCO₂e", "MWh", "Facturas"])
            for item in scope_data['detalle']:
                ws.append([item['energia'], item['emisiones_tco2e'],
                           item['consumo_mwh'], item['n_facturas']])

    _autofit(ws)


def _hoja_metodologia(wb: Workbook, datos: dict):
    ws = wb.create_sheet("3. Metodología")
    m, met = datos['meta'], datos['metodologia']
    _titulo(ws, 1, 1, f"METODOLOGÍA — FACTORES DE EMISIÓN {m['anio']}", span=7)

    ws.append([])
    _fila_cabecera(ws, ws.max_row + 1, [
        "País", "Tipo energía", "Año", "Factor (kg CO₂/MWh)",
        "Fuente", "Vigencia desde", "Scope", "Facturas usadas"
    ])

    for f in met['factores']:
        ws.append([f['pais'], f['tipo_energia'], f['anio'],
                   f['factor_kg_co2_mwh'], f['fuente'] or '', f['fecha_vigencia_desde'] or '',
                   f"Scope {f['scope_ghg']}", f['n_facturas_usadas']])

    ws.append([])
    nota_row = ws.max_row + 1
    ws.cell(nota_row, 1, "NOTA METODOLÓGICA").font = Font(bold=True)
    ws.append([])
    nota_txt_row = ws.max_row + 1
    ws.cell(nota_txt_row, 1, met['nota_metodologica'])
    ws.cell(nota_txt_row, 1).alignment = Alignment(wrap_text=True, vertical='top')
    ws.row_dimensions[nota_txt_row].height = 80

    _autofit(ws)


def _hoja_calidad(wb: Workbook, datos: dict):
    ws = wb.create_sheet("4. Calidad del Dato")
    m, c = datos['meta'], datos['calidad']
    _titulo(ws, 1, 1, f"CALIDAD DEL DATO — {m['anio']}", span=3)

    items = [
        ("Total facturas analizadas", c['total_facturas']),
        ("Facturas con datos reales", c['facturas_reales']),
        ("Facturas/periodos estimados", c['facturas_estimadas']),
        ("Periodos faltantes", c['periodos_faltantes']),
        ("", ""),
        ("% Datos reales", f"{c['pct_real']}%"),
        ("% Datos estimados", f"{c['pct_estimado']}%"),
        ("% Datos faltantes", f"{c['pct_faltante']}%"),
        ("Nivel de calidad global", c['nivel_calidad']),
        ("", ""),
        ("Facturas con OCR bajo (<0.7)", c['facturas_ocr_bajo']),
        ("Confianza OCR media", c['confianza_ocr_media']),
    ]
    for label, value in items:
        row = ws.max_row + 1
        ws.cell(row, 1, label).font = Font(bold=not label.startswith(" ") and bool(label))
        ws.cell(row, 2, value)

    _autofit(ws)


def _hoja_trazabilidad(wb: Workbook, datos: dict):
    ws = wb.create_sheet("5. Trazabilidad")
    m, t = datos['meta'], datos['trazabilidad']
    _titulo(ws, 1, 1, f"TRAZABILIDAD — {m['anio']}", span=3)

    items = [
        ("Número de recálculos realizados", t['n_recalculos']),
        ("Modificaciones manuales registradas", t['n_modificaciones_manuales']),
        ("Facturas con documento PDF adjunto", t['n_facturas_con_documento']),
        ("Total facturas", t['n_facturas_total']),
        ("% con evidencia documental", f"{t['pct_con_documento']}%"),
        ("", ""),
        ("Estimaciones generadas", t['n_estimaciones']),
        ("Estimaciones validadas con dato real", t['n_estimaciones_sustituidas']),
        ("Error medio estimaciones (%)", t['error_medio_estimaciones_pct'] or 'N/D'),
    ]
    for label, value in items:
        row = ws.max_row + 1
        ws.cell(row, 1, label).font = Font(bold=bool(label))
        ws.cell(row, 2, value)

    _autofit(ws)


def _hoja_detalle(wb: Workbook, datos: dict):
    ws = wb.create_sheet("6. Detalle Facturas")
    m = datos['meta']
    _titulo(ws, 1, 1, f"DETALLE FACTURAS — {m['anio']}", span=10)

    cabecera = [
        "País", "Sede", "Sociedad", "Comercializadora", "Tipo Energía",
        "Periodo Inicio", "Periodo Fin", "Consumo kWh", "Consumo MWh",
        "Factor (kg CO₂/MWh)", "Emisiones (tCO₂e)", "Scope GHG",
        "Fuente Factor", "Versión Factor", "Tipo Dato", "Confianza OCR",
        "Estado", "Fecha Carga"
    ]
    _fila_cabecera(ws, ws.max_row + 1, cabecera)

    for f in datos['detalle_facturas']:
        ws.append([
            f.get('pais'), f.get('sede'), f.get('sociedad'),
            f.get('comercializadora'), f.get('tipo_energia'),
            f.get('periodo_inicio'), f.get('periodo_fin'),
            f.get('consumo_kwh'), f.get('consumo_mwh'),
            f.get('factor_emision'), f.get('emisiones_tco2e'),
            f"Scope {f.get('scope_ghg', 2)}",
            f.get('fuente_factor'), f.get('version_factor'),
            f.get('tipo_dato'), f.get('confianza_ocr'),
            f.get('estado'), f.get('fecha_carga'),
        ])

    _autofit(ws)


# ── Helpers Excel ─────────────────────────────────────────────────────────────

def _titulo(ws, row: int, col: int, texto: str, span: int = 1):
    cell = ws.cell(row, col, texto)
    cell.font = Font(bold=True, size=14, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=COLOR_HEADER)
    cell.alignment = Alignment(horizontal='center', vertical='center')
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col + span - 1)
    ws.row_dimensions[row].height = 30


def _subtitulo(ws, row: int, col: int, texto: str):
    cell = ws.cell(row, col, texto)
    cell.font = Font(italic=True, color="666666")
    cell.fill = PatternFill("solid", fgColor=COLOR_GRAY_LIGHT)


def _seccion_header(ws, row: int, col: int, texto: str, span: int = 1):
    cell = ws.cell(row, col, texto)
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=COLOR_SUBHEADER)
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col + span - 1)


def _fila_cabecera(ws, row: int, columnas: list):
    for i, col in enumerate(columnas, 1):
        cell = ws.cell(row, i, col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=COLOR_SUBHEADER)
        cell.alignment = Alignment(horizontal='center')


def _autofit(ws, max_width: int = 40):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 2, max_width)


# ── Helpers de filtros ────────────────────────────────────────────────────────

def _filtros_base(anio: str, pais: str = None,
                   tipo_energia: str = None, alias: str = 'f') -> tuple[str, list]:
    """
    Genera condiciones WHERE con alias de tabla para evitar ambigüedades en JOINs.
    """
    a = f"{alias}." if alias else ""
    cond = [
        f"{a}fecha_anulacion IS NULL",
        f"strftime('%Y', COALESCE({a}periodo_inicio, {a}fecha_carga)) = ?",
    ]
    params: list = [anio]
    if pais:
        cond.append(f"{a}pais = ?"); params.append(pais.upper())
    if tipo_energia:
        cond.append(f"{a}tipo_energia = ?"); params.append(tipo_energia)
    return " AND ".join(cond), params


def _nivel_calidad(pct_real: float) -> str:
    if pct_real >= 90:
        return "Excelente (≥90% datos reales)"
    if pct_real >= 70:
        return "Bueno (70-90% datos reales)"
    if pct_real >= 50:
        return "Aceptable (50-70% datos reales)"
    return "Insuficiente (<50% datos reales)"


# ── Sección por sociedad (Fase 5) ─────────────────────────────────────────────

def _seccion_por_sociedad(conn, anio: str, pais: str,
                           tipo_energia: str) -> list[dict]:
    """
    Devuelve un ranking de emisiones por sociedad para el informe GHG.

    Usa el modelo suministros.sociedad_id → sociedades (tabla maestra) con
    fallback a facturas.sociedad (texto libre) cuando no hay vinculación.
    """
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia, alias='f')
    rows = conn.execute(
        f'''SELECT COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar') AS sociedad,
                   soc.cif AS sociedad_cif,
                   COUNT(*) AS n_facturas,
                   COALESCE(SUM(f.consumo_mwh), 0) AS consumo_mwh,
                   COALESCE(SUM(f.consumo_kwh), 0) AS consumo_kwh,
                   COALESCE(SUM(f.emisiones_tco2e), 0) AS emisiones_tco2e,
                   COUNT(DISTINCT f.sede) AS n_sedes,
                   COUNT(DISTINCT f.pais) AS n_paises
            FROM facturas f
            LEFT JOIN suministros su ON su.id = f.suministro_id
            LEFT JOIN sociedades soc ON soc.id = su.sociedad_id
            WHERE {filtro_base}
            GROUP BY 1, 2
            ORDER BY emisiones_tco2e DESC''',
        params_base
    ).fetchall()

    total_emisiones = sum(r['emisiones_tco2e'] for r in rows) or 1
    return [
        {
            'sociedad': r['sociedad'],
            'cif': r['sociedad_cif'],
            'n_facturas': r['n_facturas'],
            'consumo_mwh': round(r['consumo_mwh'], 2),
            'consumo_kwh': round(r['consumo_kwh'], 2),
            'emisiones_tco2e': round(r['emisiones_tco2e'], 4),
            'pct_total': round(r['emisiones_tco2e'] / total_emisiones * 100, 1),
            'n_sedes': r['n_sedes'],
            'n_paises': r['n_paises'],
        }
        for r in rows
    ]


def _seccion_sedes_por_sociedad(conn, anio: str, pais: str,
                                  tipo_energia: str) -> list[dict]:
    """
    Drill-down sede → sociedades para el informe GHG.

    Devuelve, para cada sede, el desglose de emisiones por sociedad titular.
    Usa el modelo suministros.sociedad_id → sociedades con fallback a
    facturas.sociedad.
    """
    filtro_base, params_base = _filtros_base(anio, pais, tipo_energia, alias='f')
    rows = conn.execute(
        f'''SELECT f.pais, f.sede,
                   COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar') AS sociedad,
                   soc.cif AS sociedad_cif,
                   COUNT(*) AS n_facturas,
                   COALESCE(SUM(f.consumo_mwh), 0) AS consumo_mwh,
                   COALESCE(SUM(f.emisiones_tco2e), 0) AS emisiones_tco2e
            FROM facturas f
            LEFT JOIN suministros su ON su.id = f.suministro_id
            LEFT JOIN sociedades soc ON soc.id = su.sociedad_id
            WHERE {filtro_base}
            GROUP BY f.pais, f.sede,
                     COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar'),
                     soc.cif
            ORDER BY f.pais, f.sede, emisiones_tco2e DESC''',
        params_base
    ).fetchall()

    # Agrupar por (pais, sede)
    sedes_map: dict[tuple, dict] = {}
    for r in rows:
        key = (r['pais'], r['sede'])
        if key not in sedes_map:
            sedes_map[key] = {
                'pais': r['pais'],
                'sede': r['sede'],
                'total_emisiones': 0.0,
                'total_mwh': 0.0,
                'n_facturas': 0,
                'n_sociedades': 0,
                'sociedades': []
            }
        s = sedes_map[key]
        em = r['emisiones_tco2e'] or 0
        s['total_emisiones'] += em
        s['total_mwh'] += r['consumo_mwh'] or 0
        s['n_facturas'] += r['n_facturas']
        s['sociedades'].append({
            'sociedad': r['sociedad'],
            'cif': r['sociedad_cif'],
            'n_facturas': r['n_facturas'],
            'consumo_mwh': round(r['consumo_mwh'] or 0, 2),
            'emisiones_tco2e': round(em, 4),
        })

    resultado = []
    for s in sedes_map.values():
        s['total_emisiones'] = round(s['total_emisiones'], 4)
        s['total_mwh'] = round(s['total_mwh'], 2)
        s['n_sociedades'] = len(s['sociedades'])
        total_e = s['total_emisiones'] or 1
        for soc in s['sociedades']:
            soc['pct'] = round(soc['emisiones_tco2e'] / total_e * 100, 1)
        resultado.append(s)
    resultado.sort(key=lambda x: x['total_emisiones'], reverse=True)
    return resultado


def _hoja_por_sociedad(wb: Workbook, datos: dict):
    """Hoja GHG: Emisiones por Sociedad/Empresa."""
    ws = wb.create_sheet("7. Emisiones por Sociedad")
    m = datos['meta']
    _titulo(ws, 1, 1, f"EMISIONES POR SOCIEDAD — {m['anio']}", span=9)

    cabecera = [
        "Sociedad / Empresa",
        "CIF/NIF",
        "Nº Facturas",
        "Consumo (MWh)",
        "Consumo (kWh)",
        "Emisiones (tCO₂e)",
        "% del Total",
        "Nº Sedes",
        "Nº Países",
    ]
    _fila_cabecera(ws, ws.max_row + 1, cabecera)

    socs = datos.get('por_sociedad', [])
    for i, s in enumerate(socs):
        fill = PatternFill("solid", fgColor=COLOR_GRAY_LIGHT) if i % 2 == 0 else None
        row_idx = ws.max_row + 1
        values = [
            s['sociedad'], s.get('cif') or '', s['n_facturas'], s['consumo_mwh'],
            s['consumo_kwh'], s['emisiones_tco2e'],
            f"{s['pct_total']}%", s['n_sedes'], s['n_paises'],
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row_idx, col, val)
            if fill:
                cell.fill = fill

    # Fila de totales
    if socs:
        ws.append([])
        row_tot = ws.max_row + 1
        cell = ws.cell(row_tot, 1, "TOTAL")
        cell.font = Font(bold=True)
        ws.cell(row_tot, 4, round(sum(s['consumo_mwh'] for s in socs), 2)).font = Font(bold=True)
        ws.cell(row_tot, 5, round(sum(s['consumo_kwh'] for s in socs), 2)).font = Font(bold=True)
        ws.cell(row_tot, 6, round(sum(s['emisiones_tco2e'] for s in socs), 4)).font = Font(bold=True)
        ws.cell(row_tot, 7, "100%").font = Font(bold=True)

    _autofit(ws)


def _hoja_sedes_por_sociedad(wb: Workbook, datos: dict):
    """
    Hoja GHG: Desglose por sede y sociedad titular.

    Para cada sede, lista las sociedades que tienen CUPS facturados en ella,
    con sus emisiones, consumo y porcentaje sobre el total de la sede. Permite
    ver el reparto cuando una sede tiene varios CUPS de sociedades distintas.
    """
    ws = wb.create_sheet("8. Desglose Sede-Sociedad")
    m = datos['meta']
    _titulo(ws, 1, 1, f"DESGLOSE SEDE → SOCIEDAD — {m['anio']}", span=7)

    cabecera = [
        "País", "Sede", "Sociedad", "CIF/NIF",
        "Nº Facturas", "Consumo (MWh)", "Emisiones (tCO₂e)", "% Sede",
    ]
    _fila_cabecera(ws, ws.max_row + 1, cabecera)

    sedes = datos.get('sedes_por_sociedad', [])
    for i, s in enumerate(sedes):
        sede_fill = PatternFill("solid", fgColor=COLOR_GRAY_MID)
        # Fila de cabecera de sede (resumen)
        row_idx = ws.max_row + 1
        ws.cell(row_idx, 1, s['pais']).fill = sede_fill
        ws.cell(row_idx, 2, s['sede']).fill = sede_fill
        ws.cell(row_idx, 2).font = Font(bold=True)
        ws.cell(row_idx, 3, f"TOTAL SEDE ({s['n_sociedades']} sociedades)").fill = sede_fill
        ws.cell(row_idx, 3).font = Font(bold=True)
        ws.cell(row_idx, 6, s['total_mwh']).fill = sede_fill
        ws.cell(row_idx, 6).font = Font(bold=True)
        ws.cell(row_idx, 7, s['total_emisiones']).fill = sede_fill
        ws.cell(row_idx, 7).font = Font(bold=True)
        ws.cell(row_idx, 8, "100%").fill = sede_fill
        ws.cell(row_idx, 8).font = Font(bold=True)

        # Filas de cada sociedad
        for j, soc in enumerate(s['sociedades']):
            soc_fill = PatternFill("solid", fgColor=COLOR_GRAY_LIGHT) if j % 2 == 0 else None
            r = ws.max_row + 1
            values = [
                '', '', soc['sociedad'], soc.get('cif') or '',
                soc['n_facturas'], soc['consumo_mwh'],
                soc['emisiones_tco2e'], f"{soc['pct']}%",
            ]
            for col, val in enumerate(values, 1):
                cell = ws.cell(r, col, val)
                if soc_fill:
                    cell.fill = soc_fill

    _autofit(ws)
