"""
Servicio del Dashboard Ejecutivo de Sostenibilidad — Fase 4.

Proporciona todos los KPIs y agregaciones necesarios para el dashboard
orientado a Rossana y al equipo de sostenibilidad.

Módulos:
  - resumen_ejecutivo()   — visión global de facturas, emisiones y cobertura.
  - kpis_emisiones()      — tCO₂e totales, por año, país y sede; comparativa anual.
  - kpis_cobertura()      — % real / estimado / faltante por sede.
  - kpis_calidad()        — OCR, consumos anómalos, duplicados, mejor/peor sede.
  - kpis_facturacion()    — total, revisadas, pendientes, duplicados.
  - evolucion_mensual()   — serie temporal mensual de emisiones.
"""

import json as _json
import logging
from datetime import date, datetime
from database.connection import get_db_connection
from services._queries import filtro_facturas
import config

logger = logging.getLogger(__name__)

_WHERE_ACTIVAS = "fecha_anulacion IS NULL"


# ── Resumen ejecutivo ─────────────────────────────────────────────────────────

def resumen_ejecutivo(anio: str = None) -> dict:
    """
    KPIs globales para la cabecera del dashboard.

    Incluye:
      - Total facturas activas y emisiones tCO₂e
      - Variación respecto al año anterior
      - Cobertura global (% real/estimado/faltante)
      - Alertas pendientes por severidad
    """
    anio_actual = anio or str(date.today().year)
    anio_ant = str(int(anio_actual) - 1)

    with get_db_connection() as conn:
        # Emisiones año actual
        r = conn.execute(
            f'''SELECT COUNT(*) as n_facturas,
                       COALESCE(SUM(emisiones_tco2e),0) as emisiones,
                       COALESCE(SUM(consumo_mwh),0) as consumo
                FROM facturas
                WHERE {_WHERE_ACTIVAS}
                  AND strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?''',
            (anio_actual,)
        ).fetchone()
        n_facturas = r['n_facturas']
        emisiones_actual = round(r['emisiones'], 4)
        consumo_actual = round(r['consumo'], 2)

        # Emisiones año anterior
        r_ant = conn.execute(
            f'''SELECT COALESCE(SUM(emisiones_tco2e),0) as emisiones
                FROM facturas
                WHERE {_WHERE_ACTIVAS}
                  AND strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?''',
            (anio_ant,)
        ).fetchone()
        emisiones_ant = round(r_ant['emisiones'], 4)
        variacion_pct = _variacion_pct(emisiones_ant, emisiones_actual)

        # Sedes activas
        n_sedes = conn.execute(
            f'''SELECT COUNT(DISTINCT sede) FROM facturas WHERE {_WHERE_ACTIVAS}'''
        ).fetchone()[0]

        n_paises = conn.execute(
            f'''SELECT COUNT(DISTINCT pais) FROM facturas WHERE {_WHERE_ACTIVAS}'''
        ).fetchone()[0]

        # Cobertura global del año actual
        cob = _cobertura_global(conn, anio_actual)

        # Alertas pendientes
        try:
            alertas = conn.execute(
                '''SELECT severidad, COUNT(*) as n FROM alertas
                   WHERE estado='pendiente' GROUP BY severidad'''
            ).fetchall()
            alertas_dict = {r['severidad']: r['n'] for r in alertas}
        except Exception:
            alertas_dict = {}

        # Sedes con periodos pendientes
        sedes_pendientes = conn.execute(
            '''SELECT COUNT(DISTINCT sede) FROM periodos_faltantes
               WHERE estado='faltante' AND anio=?''',
            (anio_actual,)
        ).fetchone()[0]

    return {
        'anio': anio_actual,
        'anio_anterior': anio_ant,
        'n_facturas': n_facturas,
        'emisiones_tco2e': emisiones_actual,
        'consumo_mwh': consumo_actual,
        'emisiones_anio_anterior': emisiones_ant,
        'variacion_emisiones_pct': variacion_pct,
        'n_sedes': n_sedes,
        'n_paises': n_paises,
        'cobertura': cob,
        'sedes_pendientes': sedes_pendientes,
        'alertas': {
            'critica': alertas_dict.get('critica', 0),
            'media': alertas_dict.get('media', 0),
            'informativa': alertas_dict.get('informativa', 0),
            'total': sum(alertas_dict.values()),
        },
    }


# ── KPIs de emisiones ─────────────────────────────────────────────────────────

def kpis_emisiones(anio: str = None, pais: str = None, sede: str = None) -> dict:
    """
    Desglose completo de emisiones para el dashboard.
    Fase 5: filtro opcional por pais y sede.

    Returns:
      - total_tco2e, por_pais[], por_sede[], por_mes[], comparativa_anual[]
    """
    anio_actual = anio or str(date.today().year)
    anio_ant = str(int(anio_actual) - 1)

    # Filtro de facturas activas por año (helper compartido con ghg_report)
    where_base, params_base = filtro_facturas(anio_actual, pais, sede)

    with get_db_connection() as conn:
        # Por país — año actual
        por_pais = [
            {
                'pais': r['pais'],
                'emisiones': round(r['emisiones'] or 0, 4),
                'consumo_mwh': round(r['consumo'] or 0, 2),
                'n_facturas': r['n'],
            }
            for r in conn.execute(
                f'''SELECT pais,
                           SUM(emisiones_tco2e) as emisiones,
                           SUM(consumo_mwh) as consumo,
                           COUNT(*) as n
                    FROM facturas
                    WHERE {where_base}
                    GROUP BY pais ORDER BY emisiones DESC''',
                params_base
            )
        ]

        # Por sede — año actual (top 20 por emisiones)
        por_sede = [
            {
                'pais': r['pais'],
                'sede': r['sede'],
                'emisiones': round(r['emisiones'] or 0, 4),
                'consumo_mwh': round(r['consumo'] or 0, 2),
            }
            for r in conn.execute(
                f'''SELECT pais, sede,
                           SUM(emisiones_tco2e) as emisiones,
                           SUM(consumo_mwh) as consumo
                    FROM facturas
                    WHERE {where_base}
                    GROUP BY pais, sede ORDER BY emisiones DESC LIMIT 20''',
                params_base
            )
        ]

        # Desglose por sociedad dentro de cada sede (drill-down).
        # Usa el modelo suministros.sociedad_id → sociedades con fallback a
        # facturas.sociedad (texto libre) cuando no hay vinculación.
        # Solo se calcula para las sedes del top (por rendimiento).
        sedes_top = [(s['pais'], s['sede']) for s in por_sede]
        soc_por_sede = _drilldown_sociedades_sedes(
            conn, anio_actual, sedes_top, tipo_energia=None
        )
        for s in por_sede:
            s['sociedades'] = soc_por_sede.get((s['pais'], s['sede']), [])
            # Marca si la sede tiene más de una sociedad (caso de revisión)
            s['multi_sociedad'] = len(s['sociedades']) > 1

        # Comparativa mensual — año actual vs anterior
        meses_actual = _emisiones_mensuales(conn, anio_actual, pais=pais, sede=sede)
        meses_ant    = _emisiones_mensuales(conn, anio_ant,    pais=pais, sede=sede)

        total_actual = sum(m['emisiones'] for m in meses_actual)
        total_ant    = sum(m['emisiones'] for m in meses_ant)

        # Scope GHG (si hay datos de scope)
        por_scope = _emisiones_por_scope(conn, anio_actual)

    return {
        'anio': anio_actual,
        'total_tco2e': round(total_actual, 4),
        'total_tco2e_anio_anterior': round(total_ant, 4),
        'variacion_pct': _variacion_pct(total_ant, total_actual),
        'por_pais': por_pais,
        'por_sede': por_sede,
        'por_mes': meses_actual,
        'por_mes_anio_anterior': meses_ant,
        'por_scope': por_scope,
    }


# ── KPIs de cobertura ─────────────────────────────────────────────────────────

def kpis_cobertura(anio: str = None, tipo_energia: str = 'electricidad',
                   pais: str = None, sede: str = None) -> dict:
    """
    Indicadores de cobertura de datos para el dashboard.
    Fase 5: filtro opcional por pais y sede.

    Returns:
      - pct_real, pct_estimado, pct_faltante
      - sedes_completas, sedes_incompletas
      - detalle por sede
    """
    anio_actual = anio or str(date.today().year)

    extra_cond = ""
    extra_params: list = []
    if pais:
        extra_cond += " AND pais = ?"
        extra_params.append(pais.upper())
    if sede:
        extra_cond += " AND sede = ?"
        extra_params.append(sede)

    with get_db_connection() as conn:
        # Sedes con datos en ese año
        sedes_rows = conn.execute(
            f'''SELECT DISTINCT pais, sede FROM facturas
                WHERE {_WHERE_ACTIVAS}
                  AND tipo_energia=?
                  AND strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?
                  {extra_cond}''',
            [tipo_energia, anio_actual] + extra_params
        ).fetchall()

        detalle_sedes = []
        total_meses = 0
        total_reales = 0
        total_estimados = 0
        total_faltantes = 0

        for row in sedes_rows:
            p, s = row['pais'], row['sede']
            reales = conn.execute(
                '''SELECT COUNT(DISTINCT substr(periodo_inicio,1,7))
                   FROM facturas
                   WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                     AND fecha_anulacion IS NULL
                     AND strftime('%Y', periodo_inicio) = ?''',
                (p, s, tipo_energia, anio_actual)
            ).fetchone()[0]

            estimados = conn.execute(
                '''SELECT COUNT(*) FROM estimaciones
                   WHERE pais=? AND sede=? AND tipo_energia=? AND estado='vigente'
                     AND substr(mes,1,4) = ?''',
                (p, s, tipo_energia, anio_actual)
            ).fetchone()[0]

            faltantes = conn.execute(
                '''SELECT COUNT(*) FROM periodos_faltantes
                   WHERE pais=? AND sede=? AND tipo_energia=? AND estado='faltante'
                     AND anio=?''',
                (p, s, tipo_energia, anio_actual)
            ).fetchone()[0]

            t = reales + estimados + faltantes or 12
            detalle_sedes.append({
                'pais': p, 'sede': s,
                'meses_reales': reales,
                'meses_estimados': estimados,
                'meses_faltantes': faltantes,
                'total_meses': t,
                'pct_real': round(reales / t * 100, 1),
                'pct_estimado': round(estimados / t * 100, 1),
                'pct_faltante': round(faltantes / t * 100, 1),
                'completo': faltantes == 0,
            })
            total_meses += t
            total_reales += reales
            total_estimados += estimados
            total_faltantes += faltantes

        tot = total_meses or 1
        sedes_completas = sum(1 for s in detalle_sedes if s['completo'])

    return {
        'anio': anio_actual,
        'tipo_energia': tipo_energia,
        'n_sedes': len(detalle_sedes),
        'sedes_completas': sedes_completas,
        'sedes_incompletas': len(detalle_sedes) - sedes_completas,
        'pct_real': round(total_reales / tot * 100, 1),
        'pct_estimado': round(total_estimados / tot * 100, 1),
        'pct_faltante': round(total_faltantes / tot * 100, 1),
        'total_meses_esperados': total_meses,
        'total_meses_reales': total_reales,
        'total_meses_estimados': total_estimados,
        'total_meses_faltantes': total_faltantes,
        'detalle_sedes': sorted(detalle_sedes, key=lambda x: x['pct_faltante'], reverse=True),
    }


# ── KPIs de calidad ───────────────────────────────────────────────────────────

def kpis_calidad(anio: str = None, pais: str = None, sede: str = None) -> dict:
    """
    Indicadores de calidad de datos.
    Fase 5: filtro opcional por pais y sede.

    Returns:
      - facturas con OCR bajo, consumos anómalos, duplicados
      - sedes con mejor/peor calidad
      - score de calidad global
    """
    anio_actual = anio or str(date.today().year)

    where_base, params_base = filtro_facturas(anio_actual, pais, sede)

    with get_db_connection() as conn:
        # OCR bajo (< 0.60)
        ocr_bajo = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base} AND confianza_ocr IS NOT NULL
                  AND confianza_ocr < 0.60''',
            params_base
        ).fetchone()[0]

        # Duplicados potenciales
        duplicados = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base} AND duplicado_potencial = 1''',
            params_base
        ).fetchone()[0]

        # Total facturas del año
        total_facturas = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base}''',
            params_base
        ).fetchone()[0]

        # Consumos anómalos (> 3x media de la sede)
        consumos_anomalos = _detectar_consumos_anomalos(conn, anio_actual)

        # Sedes con mejor/peor calidad (basado en periodos faltantes)
        sedes_calidad = conn.execute(
            '''SELECT pais, sede,
                      SUM(CASE WHEN estado='faltante' THEN 1 ELSE 0 END) as faltantes,
                      COUNT(*) as total
               FROM periodos_faltantes WHERE anio=?
               GROUP BY pais, sede
               ORDER BY faltantes ASC''',
            (anio_actual,)
        ).fetchall()

        mejores = [{'pais': r['pais'], 'sede': r['sede'],
                    'faltantes': r['faltantes'],
                    'pct_cobertura': round((r['total'] - r['faltantes']) / r['total'] * 100, 1)}
                   for r in sedes_calidad[:5]]
        peores = [{'pais': r['pais'], 'sede': r['sede'],
                   'faltantes': r['faltantes'],
                   'pct_cobertura': round((r['total'] - r['faltantes']) / r['total'] * 100, 1)}
                  for r in reversed(sedes_calidad[-5:])]

        # Score calidad global
        score = _calcular_score_calidad(total_facturas, ocr_bajo, duplicados, consumos_anomalos)

        # OCR medio
        ocr_media_row = conn.execute(
            f'''SELECT AVG(confianza_ocr) FROM facturas
                WHERE {_WHERE_ACTIVAS} AND confianza_ocr IS NOT NULL
                  AND strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?''',
            (anio_actual,)
        ).fetchone()[0]
        ocr_media = round(ocr_media_row, 3) if ocr_media_row is not None else None

    return {
        'anio': anio_actual,
        'total_facturas': total_facturas,
        'facturas_ocr_bajo': ocr_bajo,
        'duplicados_detectados': duplicados,
        'consumos_anomalos': consumos_anomalos,
        'pct_ocr_bajo': round(ocr_bajo / total_facturas * 100, 1) if total_facturas else 0,
        'score_calidad_global': score,
        'confianza_ocr_media': ocr_media,
        'sedes_mejor_calidad': mejores,
        'sedes_peor_calidad': peores,
    }


# ── KPIs de facturación ───────────────────────────────────────────────────────

def kpis_facturacion(anio: str = None, pais: str = None, sede: str = None) -> dict:
    """
    Métricas de gestión de facturas.
    Fase 5: filtro opcional por pais y sede.
    """
    anio_actual = anio or str(date.today().year)

    where_base, params_base = filtro_facturas(anio_actual, pais, sede)

    with get_db_connection() as conn:
        total = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base}''',
            params_base
        ).fetchone()[0]

        revisadas = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base} AND estado='confirmada' ''',
            params_base
        ).fetchone()[0]

        pendientes_revision = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base} AND estado='pendiente_revision' ''',
            params_base
        ).fetchone()[0]

        duplicados = conn.execute(
            f'''SELECT COUNT(*) FROM facturas
                WHERE {where_base} AND duplicado_potencial=1''',
            params_base
        ).fetchone()[0]

        por_estado = [
            {'estado': r['estado'], 'n': r['n']}
            for r in conn.execute(
                f'''SELECT estado, COUNT(*) as n FROM facturas
                    WHERE {where_base}
                    GROUP BY estado ORDER BY n DESC''',
                params_base
            )
        ]

    return {
        'anio': anio_actual,
        'total': total,
        'revisadas': revisadas,
        'pendientes_revision': pendientes_revision,
        'duplicados_detectados': duplicados,
        'pct_revisadas': round(revisadas / total * 100, 1) if total else 0,
        'por_estado': por_estado,
    }


# ── Evolución mensual ─────────────────────────────────────────────────────────

def evolucion_mensual(anio: str = None, pais: str = None, sede: str = None) -> dict:
    """
    Serie temporal mensual de emisiones para gráficos de línea/barras.
    Incluye datos reales + estimados, y el año anterior para comparativa.
    """
    anio_actual = anio or str(date.today().year)
    anio_ant = str(int(anio_actual) - 1)

    with get_db_connection() as conn:
        meses_actual = _emisiones_mensuales(conn, anio_actual, pais, sede)
        meses_ant = _emisiones_mensuales(conn, anio_ant, pais, sede)
        # Estimaciones del año actual
        est_meses = _estimaciones_mensuales(conn, anio_actual, pais, sede)

    # Combinar reales + estimados por mes
    meses_labels = [f"{anio_actual}-{m:02d}" for m in range(1, 13)]
    reales = {m['mes']: m['emisiones'] for m in meses_actual}
    estimados = {m['mes']: m['emisiones'] for m in est_meses}
    anteriores = {m['mes']: m['emisiones'] for m in meses_ant}

    serie = []
    for mes in meses_labels:
        serie.append({
            'mes': mes,
            'real': reales.get(mes, 0),
            'estimado': estimados.get(mes, 0),
            'total': round((reales.get(mes, 0) or 0) + (estimados.get(mes, 0) or 0), 4),
            'anio_anterior': anteriores.get(mes.replace(anio_actual, anio_ant), 0),
        })

    return {
        'anio': anio_actual,
        'pais': pais,
        'sede': sede,
        'serie': serie,
        'total_actual': round(sum(m['total'] for m in serie), 4),
        'total_anterior': round(sum(m['anio_anterior'] for m in serie), 4),
    }

    # QW2 — Agrega services/dashboard_service.py

def calidad_ocr_por_campo(anio: str = None, pais: str = None, sede: str = None) -> list[dict]:
    """
    Precisión media y % de facturas bajo umbral, desglosado por campo extraído.
    No requiere ningún cambio en la extracción: agrega facturas.campos_confianza,
    que ya se persiste en cada carga. Primera pieza del dashboard de calidad OCR.
    """
    anio_actual = anio or str(date.today().year)
    where_base, params_base = filtro_facturas(anio_actual, pais, sede)

    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT campos_confianza FROM facturas
                WHERE {where_base} AND campos_confianza IS NOT NULL''',
            params_base
        ).fetchall()

    umbral = getattr(config, 'UMBRAL_REVISION', 0.75)
    acumulado: dict[str, list[float]] = {}
    for r in rows:
        try:
            conf = _json.loads(r['campos_confianza'])
        except Exception:
            continue
        for campo, valor in conf.items():
            if isinstance(valor, (int, float)):
                acumulado.setdefault(campo, []).append(valor)

    resultado = [
        {
            'campo': campo,
            'n_facturas': len(valores),
            'confianza_media': round(sum(valores) / len(valores), 3),
            'pct_bajo_umbral': round(
                len([v for v in valores if v < umbral]) / len(valores) * 100, 1
            ),
        }
        for campo, valores in acumulado.items()
    ]
    resultado.sort(key=lambda x: x['confianza_media'])
    return resultado

# ── Helpers internos ──────────────────────────────────────────────────────────

def _cobertura_global(conn, anio: str) -> dict:
    reales = conn.execute(
        '''SELECT COUNT(DISTINCT pais||'|'||sede||'|'||substr(periodo_inicio,1,7))
           FROM facturas WHERE fecha_anulacion IS NULL AND tipo_dato='real'
           AND strftime('%Y', periodo_inicio) = ?''',
        (anio,)
    ).fetchone()[0]
    estimados = conn.execute(
        "SELECT COUNT(*) FROM estimaciones WHERE estado='vigente' AND substr(mes,1,4)=?",
        (anio,)
    ).fetchone()[0]
    faltantes = conn.execute(
        "SELECT COUNT(*) FROM periodos_faltantes WHERE estado='faltante' AND anio=?",
        (anio,)
    ).fetchone()[0]
    total = reales + estimados + faltantes or 1
    return {
        'pct_real': round(reales / total * 100, 1),
        'pct_estimado': round(estimados / total * 100, 1),
        'pct_faltante': round(faltantes / total * 100, 1),
        'meses_reales': reales,
        'meses_estimados': estimados,
        'meses_faltantes': faltantes,
    }


def _emisiones_mensuales(conn, anio: str, pais: str = None, sede: str = None) -> list:
    cond = [
        "fecha_anulacion IS NULL",
        "strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?"
    ]
    params = [anio]
    if pais:
        cond.append("pais=?"); params.append(pais)
    if sede:
        cond.append("sede=?"); params.append(sede)
    where = "WHERE " + " AND ".join(cond)
    rows = conn.execute(
        f'''SELECT strftime('%Y-%m', COALESCE(periodo_inicio, fecha_carga)) as mes,
                   COALESCE(SUM(emisiones_tco2e),0) as emisiones,
                   COALESCE(SUM(consumo_mwh),0) as consumo,
                   COUNT(*) as n
            FROM facturas {where}
            GROUP BY mes ORDER BY mes''',
        params
    ).fetchall()
    return [{'mes': r['mes'], 'emisiones': round(r['emisiones'], 4),
             'consumo': round(r['consumo'], 2), 'n': r['n']} for r in rows]


def _estimaciones_mensuales(conn, anio: str, pais: str = None, sede: str = None) -> list:
    cond = ["estado='vigente'", "substr(mes,1,4)=?"]
    params = [anio]
    if pais:
        cond.append("pais=?"); params.append(pais)
    if sede:
        cond.append("sede=?"); params.append(sede)
    where = "WHERE " + " AND ".join(cond)
    rows = conn.execute(
        f'''SELECT mes, COALESCE(SUM(emisiones_estimadas),0) as emisiones
            FROM estimaciones {where} GROUP BY mes ORDER BY mes''',
        params
    ).fetchall()
    return [{'mes': r['mes'], 'emisiones': round(r['emisiones'], 4)} for r in rows]


def _emisiones_por_scope(conn, anio: str) -> list:
    """Agrupa emisiones por scope GHG si hay datos disponibles."""
    try:
        rows = conn.execute(
            '''SELECT fe.scope_ghg as scope,
                      COALESCE(SUM(f.emisiones_tco2e),0) as emisiones
               FROM facturas f
               JOIN factores_emision fe ON fe.id = f.factor_version_id
               WHERE f.fecha_anulacion IS NULL
                 AND strftime('%Y', COALESCE(f.periodo_inicio, f.fecha_carga)) = ?
               GROUP BY fe.scope_ghg''',
            (anio,)
        ).fetchall()
        labels = {1: 'Scope 1 — Directo', 2: 'Scope 2 — Electricidad', 3: 'Scope 3 — Indirecto'}
        return [{'scope': r['scope'], 'label': labels.get(r['scope'], f"Scope {r['scope']}"),
                 'emisiones': round(r['emisiones'], 4)} for r in rows]
    except Exception:
        return []


def _detectar_consumos_anomalos(conn, anio: str) -> int:
    """Cuenta facturas con consumo > 3x la media de su sede en el año."""
    try:
        rows = conn.execute(
            f'''SELECT f.id,
                       f.consumo_mwh,
                       AVG(f2.consumo_mwh) as media_sede
                FROM facturas f
                JOIN facturas f2 ON f2.pais=f.pais AND f2.sede=f.sede
                  AND f2.tipo_energia=f.tipo_energia
                  AND f2.fecha_anulacion IS NULL
                  AND f2.consumo_mwh > 0
                WHERE f.{_WHERE_ACTIVAS} AND f.consumo_mwh > 0
                  AND strftime('%Y', COALESCE(f.periodo_inicio, f.fecha_carga)) = ?
                GROUP BY f.id, f.consumo_mwh
                HAVING f.consumo_mwh > AVG(f2.consumo_mwh) * 3''',
            (anio,)
        ).fetchall()
        return len(rows)
    except Exception:
        return 0


def _drilldown_sociedades_sedes(conn, anio: str,
                                  sedes: list[tuple[str, str]],
                                  tipo_energia: str = None) -> dict[tuple, list]:
    """
    Para cada (pais, sede) en `sedes`, devuelve el desglose de emisiones por
    sociedad titular. Usa el modelo suministros.sociedad_id → sociedades, con
    fallback a facturas.sociedad cuando no hay vinculación.

    Returns: {(pais, sede): [{sociedad, cif, emisiones, mwh, n_facturas, pct}, ...]}
    """
    if not sedes:
        return {}

    where_parts = [
        "f.fecha_anulacion IS NULL",
        "f.emisiones_tco2e IS NOT NULL",
        "strftime('%Y', COALESCE(f.periodo_inicio, f.fecha_carga)) = ?",
    ]
    params: list = [anio]
    if tipo_energia:
        where_parts.append("f.tipo_energia = ?")
        params.append(tipo_energia)

    # Filtro por (pais, sede) — OR de pares
    placeholders = []
    for pais, sede in sedes:
        placeholders.append("(f.pais = ? AND f.sede = ?)")
        params.extend([pais, sede])
    where_parts.append("(" + " OR ".join(placeholders) + ")")
    where = " AND ".join(where_parts)

    sql = f"""
        SELECT f.pais, f.sede,
               COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar') AS sociedad,
               soc.cif AS sociedad_cif,
               SUM(f.emisiones_tco2e) AS emisiones,
               SUM(f.consumo_mwh)      AS consumo_mwh,
               COUNT(*)                AS n_facturas
        FROM facturas f
        LEFT JOIN suministros su ON su.id = f.suministro_id
        LEFT JOIN sociedades soc ON soc.id = su.sociedad_id
        WHERE {where}
        GROUP BY f.pais, f.sede,
                 COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar'),
                 soc.cif
        ORDER BY f.pais, f.sede, emisiones DESC
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        logger.exception("Error en _drilldown_sociedades_sedes")
        return {}

    # Agrupar por (pais, sede) y calcular porcentajes
    out: dict[tuple, list] = {}
    totales: dict[tuple, float] = {}
    for r in rows:
        key = (r['pais'], r['sede'])
        if key not in out:
            out[key] = []
            totales[key] = 0.0
        em = r['emisiones'] or 0
        totales[key] += em
        out[key].append({
            'sociedad': r['sociedad'],
            'cif': r['sociedad_cif'],
            'emisiones': round(em, 4),
            'consumo_mwh': round(r['consumo_mwh'] or 0, 2),
            'n_facturas': r['n_facturas'],
        })
    # Calcular pct de cada sociedad sobre el total de la sede
    for key, socs in out.items():
        total = totales.get(key, 0) or 1
        for s in socs:
            s['pct'] = round(s['emisiones'] / total * 100, 1)
    return out


def _calcular_score_calidad(total: int, ocr_bajo: int,
                             duplicados: int, anomalos: int) -> float:
    """Score de calidad 0-100."""
    if total == 0:
        return 100.0
    penalizacion = (ocr_bajo * 2 + duplicados * 5 + anomalos * 3) / total * 100
    return round(max(0.0, 100.0 - penalizacion), 1)


def _variacion_pct(anterior: float, actual: float) -> float | None:
    """Variación porcentual entre dos valores. None si no hay dato anterior."""
    if not anterior:
        return None
    return round((actual - anterior) / anterior * 100, 2)


# ── Dashboard ejecutivo ESG — Fase 6 ─────────────────────────────────────────

def dashboard_esg(anio: str = None, pais: str = None, sede: str = None) -> dict:
    """
    Dashboard ejecutivo ESG con semáforo, KPIs de objetivos y proyección de cierre.

    Combina:
      - KPIs de emisiones actuales (acumulado y tendencia)
      - Estado respecto a objetivos (semáforo ESG)
      - Proyección de cierre de ejercicio
      - Sedes en riesgo
      - Comparativa interanual

    Diseñado para el panel ejecutivo de dirección corporativa y sostenibilidad.
    """
    from services.objetivos_service import resumen_esg, seguimiento_todos
    anio_actual = anio or str(date.today().year)
    anio_int = int(anio_actual)
    anio_ant = str(anio_int - 1)

    # KPIs básicos de emisiones
    kpis = kpis_emisiones(anio=anio_actual, pais=pais, sede=sede)

    # Estado de objetivos
    try:
        esg = resumen_esg(anio=anio_int)
    except Exception:
        esg = {}

    # Proyección de cierre (global o filtrada)
    proyeccion = proyeccion_cierre(anio=anio_actual, pais=pais, sede=sede)

    # Semáforo global derivado de la proyección vs objetivos
    semaforo_global = _semaforo_global(esg, proyeccion)

    return {
        'anio': anio_actual,
        'filtros': {'pais': pais, 'sede': sede},

        # Emisiones acumuladas
        'emisiones_acumuladas_tco2e': kpis.get('total_tco2e'),
        'consumo_acumulado_mwh': kpis.get('total_mwh'),
        'comparativa_anual': kpis.get('comparativa_anual', []),

        # Objetivos ESG
        'n_objetivos_total': esg.get('n_objetivos', 0),
        'n_verde': esg.get('n_verde', 0),
        'n_amarillo': esg.get('n_amarillo', 0),
        'n_rojo': esg.get('n_rojo', 0),
        'pct_cumplimiento_global': esg.get('pct_cumplimiento_global'),
        'sedes_en_riesgo': esg.get('sedes_en_riesgo', []),
        'n_sedes_en_riesgo': len(esg.get('sedes_en_riesgo', [])),

        # Semáforo ESG global
        'semaforo_global': semaforo_global,

        # Proyección de cierre
        'proyeccion': proyeccion,
    }


def proyeccion_cierre(anio: str = None, pais: str = None,
                      sede: str = None) -> dict:
    """
    Proyección de emisiones al cierre del ejercicio actual.

    Métodos:
      1. Pro-rata por meses consumidos (primario)
      2. Ajuste por estacionalidad si hay histórico del año anterior

    Returns:
      emisiones_proyectadas_tco2e, meses_con_datos, meses_restantes,
      metodo, confianza, diferencia_vs_objetivo_tco2e
    """
    from services.objetivos_service import seguimiento_todos
    anio_actual = anio or str(date.today().year)
    anio_int    = int(anio_actual)
    mes_actual  = date.today().month

    where_base, params_base = filtro_facturas(anio_actual, pais, sede)
    where_ant, params_ant = filtro_facturas(str(anio_int - 1), pais, sede)

    with get_db_connection() as conn:
        r = conn.execute(
            f"""SELECT COALESCE(SUM(emisiones_tco2e), 0)     AS total_tco2e,
                       COUNT(DISTINCT strftime('%Y-%m',
                         COALESCE(periodo_inicio, fecha_carga))) AS meses_con_datos
                FROM facturas
                WHERE {where_base}""",
            params_base
        ).fetchone()

        total_tco2e    = round(r['total_tco2e'] or 0, 4)
        meses_con_datos = r['meses_con_datos'] or 0

        # Emisiones mismo período año anterior (para ajuste estacional)
        r_ant = conn.execute(
            f"""SELECT COALESCE(SUM(emisiones_tco2e), 0) AS total_ant,
                       COUNT(DISTINCT strftime('%Y-%m',
                         COALESCE(periodo_inicio, fecha_carga))) AS meses_ant
                FROM facturas
                WHERE {where_ant}""",
            params_ant
        ).fetchone()

        total_ant   = r_ant['total_ant'] or 0
        meses_ant   = r_ant['meses_ant'] or 0

    if meses_con_datos == 0:
        return {
            'disponible': False,
            'motivo': 'Sin datos para el período seleccionado',
        }

    meses_restantes = max(0, 12 - meses_con_datos)
    metodo = 'pro_rata'
    confianza = 0.70

    # Pro-rata simple
    proyeccion_simple = round(total_tco2e / meses_con_datos * 12, 4)

    # Ajuste estacional si hay suficiente histórico año anterior
    proyeccion_estacional = None
    if total_ant > 0 and meses_ant >= 6:
        # Factor de escala: relación entre año actual y anterior hasta mismo mes
        factor_escala = total_tco2e / (total_ant / meses_ant * meses_con_datos) if total_ant else 1
        proyeccion_estacional = round(total_ant * factor_escala, 4)
        metodo = 'estacional'
        confianza = 0.80

    proyeccion_final = proyeccion_estacional or proyeccion_simple

    # Diferencia vs objetivo (si existe objetivo global)
    dif_objetivo = None
    try:
        segs = seguimiento_todos(anio=int(anio_actual), pais=pais, sede=sede)
        if segs:
            objetivo_sum = sum(
                s['objetivo'].get('emisiones_objetivo_tco2e') or 0
                for s in segs
                if s['objetivo'].get('emisiones_objetivo_tco2e')
            )
            if objetivo_sum > 0:
                dif_objetivo = round(proyeccion_final - objetivo_sum, 4)
    except Exception:
        pass

    return {
        'disponible': True,
        'anio': anio_actual,
        'emisiones_acumuladas_tco2e': total_tco2e,
        'meses_con_datos': meses_con_datos,
        'meses_restantes': meses_restantes,
        'emisiones_proyectadas_tco2e': proyeccion_final,
        'proyeccion_pro_rata': proyeccion_simple,
        'proyeccion_estacional': proyeccion_estacional,
        'metodo': metodo,
        'confianza': confianza,
        'diferencia_vs_objetivo_tco2e': dif_objetivo,
    }


def _semaforo_global(esg: dict, proyeccion: dict) -> str:
    """
    Calcula el semáforo global ESG a partir del estado de los objetivos
    y la proyección de cierre.

    verde    → mayoría de objetivos en verde y proyección favorable
    amarillo → algún objetivo en amarillo o proyección ligeramente sobre objetivo
    rojo     → objetivos en rojo o proyección muy sobre objetivo
    gris     → sin datos suficientes
    """
    if not esg or not esg.get('n_objetivos'):
        return 'gris'

    n_rojo     = esg.get('n_rojo', 0)
    n_amarillo = esg.get('n_amarillo', 0)
    n_total    = esg.get('n_objetivos', 1)
    pct_cumpl  = esg.get('pct_cumplimiento_global')

    if n_rojo / n_total > 0.3:
        return 'rojo'
    if pct_cumpl is not None and pct_cumpl < 0:
        return 'rojo'
    if n_rojo > 0 or n_amarillo / n_total > 0.3:
        return 'amarillo'
    if pct_cumpl is not None and pct_cumpl < 10:
        return 'amarillo'

    # Comprobar proyección
    dif = (proyeccion or {}).get('diferencia_vs_objetivo_tco2e')
    if dif is not None and dif > 0:
        return 'amarillo' if dif / max(proyeccion.get('emisiones_proyectadas_tco2e', 1), 1) < 0.20 else 'rojo'

    return 'verde'
