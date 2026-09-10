"""
Servicio de cálculo de emisiones de CO₂.

La tabla `factores_emision` en BD es la ÚNICA fuente de verdad.
config.FACTORES_EMISION se usa solo como semilla inicial en migrations.py.
Este servicio nunca accede a config.py para obtener factores.

Esto garantiza:
  - Trazabilidad completa (qué factor se usó en cada cálculo).
  - Recálculo histórico cuando se actualiza un factor.
  - Preparación para CSRD: cada emisión referencia su factor y su fuente.
"""

import logging
from database.connection import get_db_connection
from services.numeros import calcular_tco2e, tco2e, kwh, mwh_reporte, porcentaje, sumar

logger = logging.getLogger(__name__)


def obtener_factor(pais: str, anio: str) -> tuple:
    """
    Obtiene el factor de emisión para electricidad de un país y año.

    Prioridad:
      1. Tabla `factores_emision` en BD — versión activa del año exacto.
      2. Año más reciente disponible en BD (fallback dentro de la BD).

    Si la BD no contiene datos para el país, devuelve (None, '', '', None).
    Esto indica que las migraciones no se han ejecutado o el país no está
    configurado — es un error de setup, no un error de runtime.

    Returns
    -------
    (factor_kg_co2_mwh, fuente, anio_usado, factor_id)
    factor_id permite trazabilidad FK con factores_emision.
    """
    with get_db_connection() as conn:
        # Intentar año exacto — versión activa
        row = conn.execute(
            '''SELECT id, factor_kg_co2_mwh, fuente, anio
               FROM factores_emision
               WHERE pais = ? AND tipo_energia = 'electricidad'
                 AND anio = ? AND activo = 1 AND es_version_activa = 1''',
            (pais, anio)
        ).fetchone()
        if row:
            return row['factor_kg_co2_mwh'], row['fuente'] or '', row['anio'], row['id']

        # Fallback: versión activa del año más reciente disponible en BD
        row = conn.execute(
            '''SELECT id, factor_kg_co2_mwh, fuente, anio
               FROM factores_emision
               WHERE pais = ? AND tipo_energia = 'electricidad'
                 AND activo = 1 AND es_version_activa = 1
               ORDER BY anio DESC LIMIT 1''',
            (pais,)
        ).fetchone()
        if row:
            logger.warning(
                f"Factor {anio} no disponible para {pais}, usando {row['anio']} "
                f"(año más reciente en BD)"
            )
            return row['factor_kg_co2_mwh'], row['fuente'] or '', row['anio'], row['id']

    # BD sin datos para este país: error de configuración
    logger.error(
        f"Factor de emisión no encontrado en BD para pais='{pais}'. "
        f"Verificar que las migraciones se ejecutaron correctamente y que "
        f"config.FACTORES_EMISION incluye el país '{pais}'."
    )
    return None, '', '', None


def calcular_emisiones(
    consumo_mwh: float, pais: str, anio: str = '2025'
) -> tuple:
    """
    Calcula las emisiones de CO₂ equivalente.

    Fórmula:  tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000

    El cálculo se hace en aritmética decimal y en un solo paso, sin redondeos
    intermedios, para que el resultado sea reproducible a partir del consumo y
    el factor almacenados.

    Returns
    -------
    (emisiones_tco2e, factor_usado, fuente_factor, factor_id)
    factor_id permite trazabilidad FK con factores_emision.
    """
    factor, fuente, anio_usado, factor_id = obtener_factor(pais, anio)

    if factor is None:
        return None, None, f"Factor no disponible para {pais}/{anio}", None

    emisiones = calcular_tco2e(consumo_mwh, factor)
    logger.info(
        f"Emisiones: {consumo_mwh} MWh x {factor} kgCO2/MWh / 1000"
        f" = {emisiones} tCO2e  [{pais}/{anio_usado}] factor_id={factor_id}"
    )
    return emisiones, factor, fuente, factor_id


# ── Análisis de emisiones por sede y sociedad (Fase 5) ────────────────────────

def _condiciones_base_facturas(anio, pais, tipo_energia):
    """Construye condiciones WHERE y params para consultas sobre facturas."""
    cond, params = [], []
    if anio:
        cond.append("substr(f.periodo_inicio,1,4) = ?"); params.append(str(anio))
    if pais:
        cond.append("f.pais = ?"); params.append(pais.upper())
    if tipo_energia:
        cond.append("f.tipo_energia = ?"); params.append(tipo_energia)
    cond.append("f.fecha_anulacion IS NULL")
    cond.append("f.emisiones_tco2e IS NOT NULL")
    return " AND ".join(cond), params


def emisiones_por_sede_y_sociedad(anio: str = None, pais: str = None,
                                    tipo_energia: str = 'electricidad') -> list[dict]:
    """
    Drill-down sede → sociedades.

    Devuelve, para cada sede, el desglose de emisiones por sociedad titular.
    Usa el nuevo modelo: facturas → suministros.sociedad_id → sociedades.
    Si un suministro no tiene sociedad_id, hace fallback a facturas.sociedad
    (texto libre) para no perder emisiones en el desglose.

    Estructura de cada item:
      {
        'pais': 'ES', 'sede': 'Asturias',
        'total_emisiones': 12.34, 'total_mwh': 100.5, 'n_facturas': 5,
        'sociedades': [
          {'sociedad': 'Hiberus...', 'cif': 'B123...', 'emisiones': 8.0, 'mwh': 65.0, 'n_facturas': 3, 'pct': 64.8},
          ...
        ]
      }
    """
    where, params = _condiciones_base_facturas(anio, pais, tipo_energia)

    sql = f"""
        SELECT f.pais, f.sede,
               COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad), ''), 'Sin identificar') AS sociedad,
               soc.cif AS sociedad_cif,
               SUM(f.emisiones_tco2e) AS emisiones,
               SUM(f.consumo_kwh)      AS total_kwh,
               SUM(f.consumo_mwh)      AS total_mwh,
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

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

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
                'sociedades': []
            }
        s = sedes_map[key]
        em = r['emisiones'] or 0
        s['total_emisiones'] += em
        s['total_mwh'] += r['total_mwh'] or 0
        s['n_facturas'] += r['n_facturas']
        s['sociedades'].append({
            'sociedad': r['sociedad'],
            'cif': r['sociedad_cif'],
            'emisiones': tco2e(em),
            'mwh': mwh_reporte(r['total_mwh'] or 0),
            'kwh': kwh(r['total_kwh'] or 0),
            'n_facturas': r['n_facturas'],
        })

    # Redondear totales y calcular porcentaje de cada sociedad
    resultado = []
    for s in sedes_map.values():
        s['total_emisiones'] = tco2e(s['total_emisiones'])
        s['total_mwh'] = mwh_reporte(s['total_mwh'])
        total_e = s['total_emisiones'] or 0
        for soc in s['sociedades']:
            soc['pct'] = porcentaje(soc['emisiones'] / total_e * 100) if total_e else 0
        resultado.append(s)

    # Ordenar por emisiones totales descendente
    resultado.sort(key=lambda x: x['total_emisiones'], reverse=True)
    return resultado


def emisiones_por_sede(anio: str = None, pais: str = None,
                        tipo_energia: str = 'electricidad') -> list[dict]:
    """
    Fase 5: agrega emisiones (tCO2e) y consumo (kWh) por sede.
    Incluye tanto facturas reales como estimaciones vigentes.
    Devuelve ranking ordenado por emisiones descendente.
    """
    cond, params = [], []
    if anio:
        cond.append("substr(periodo_inicio,1,4) = ?"); params.append(str(anio))
    if pais:
        cond.append("pais = ?"); params.append(pais.upper())
    if tipo_energia:
        cond.append("tipo_energia = ?"); params.append(tipo_energia)

    cond.append("fecha_anulacion IS NULL")
    cond.append("emisiones_tco2e IS NOT NULL")
    where = "WHERE " + " AND ".join(cond)

    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT pais, sede,
                   SUM(emisiones_tco2e)  AS total_emisiones,
                   SUM(consumo_kwh)       AS total_kwh,
                   SUM(consumo_mwh)       AS total_mwh,
                   COUNT(*)               AS n_facturas,
                   AVG(emisiones_tco2e)   AS media_emisiones_mensual
            FROM facturas
            {where}
            GROUP BY pais, sede
            ORDER BY total_emisiones DESC
        """, params).fetchall()

    resultado = []
    for i, r in enumerate(rows):
        d = dict(r)
        d['ranking'] = i + 1
        d['total_emisiones']        = tco2e(d['total_emisiones'] or 0)
        d['total_kwh']              = kwh(d['total_kwh'] or 0)
        d['total_mwh']              = mwh_reporte(d['total_mwh'] or 0)
        d['media_emisiones_mensual']= tco2e(d['media_emisiones_mensual'] or 0)
        resultado.append(d)
    return resultado


def emisiones_por_sociedad(anio: str = None, pais: str = None,
                            tipo_energia: str = 'electricidad') -> list[dict]:
    """
    Fase 5: agrega emisiones y consumo por sociedad (razón social del titular).
    Las facturas sin sociedad se agrupan bajo 'Sin identificar'.
    """
    cond, params = [], []
    if anio:
        cond.append("substr(periodo_inicio,1,4) = ?"); params.append(str(anio))
    if pais:
        cond.append("pais = ?"); params.append(pais.upper())
    if tipo_energia:
        cond.append("tipo_energia = ?"); params.append(tipo_energia)

    cond.append("fecha_anulacion IS NULL")
    cond.append("emisiones_tco2e IS NOT NULL")
    where = "WHERE " + " AND ".join(cond)

    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT COALESCE(sociedad, 'Sin identificar') AS sociedad,
                   SUM(emisiones_tco2e)  AS total_emisiones,
                   SUM(consumo_kwh)       AS total_kwh,
                   SUM(consumo_mwh)       AS total_mwh,
                   COUNT(*)               AS n_facturas,
                   COUNT(DISTINCT sede)   AS n_sedes,
                   COUNT(DISTINCT pais)   AS n_paises
            FROM facturas
            {where}
            GROUP BY COALESCE(sociedad, 'Sin identificar')
            ORDER BY total_emisiones DESC
        """, params).fetchall()

    resultado = []
    for i, r in enumerate(rows):
        d = dict(r)
        d['ranking']        = i + 1
        d['total_emisiones']= tco2e(d['total_emisiones'] or 0)
        d['total_kwh']      = kwh(d['total_kwh'] or 0)
        d['total_mwh']      = mwh_reporte(d['total_mwh'] or 0)
        resultado.append(d)
    return resultado


def comparativa_sedes(anio: str, pais: str = None,
                       tipo_energia: str = 'electricidad') -> dict:
    """
    Fase 5: comparativa de emisiones entre sedes con estadísticas descriptivas.
    Incluye: ranking, media, desviación, sede con más/menos emisiones.
    """
    sedes = emisiones_por_sede(anio=anio, pais=pais, tipo_energia=tipo_energia)
    if not sedes:
        return {'anio': anio, 'sedes': [], 'estadisticas': None}

    valores = [s['total_emisiones'] for s in sedes if s['total_emisiones']]
    media   = tco2e(sumar(valores) / len(valores)) if valores else 0
    varianza = sum((v - media) ** 2 for v in valores) / len(valores) if valores else 0
    import math
    desviacion = tco2e(math.sqrt(varianza))

    return {
        'anio': anio,
        'pais': pais,
        'sedes': sedes,
        'estadisticas': {
            'n_sedes':          len(sedes),
            'total_emisiones':  sumar(valores),
            'media_por_sede':   media,
            'desviacion_std':   desviacion,
            'sede_mayor':       sedes[0]['sede'] if sedes else None,
            'emisiones_mayor':  sedes[0]['total_emisiones'] if sedes else None,
            'sede_menor':       sedes[-1]['sede'] if sedes else None,
            'emisiones_menor':  sedes[-1]['total_emisiones'] if sedes else None,
        },
    }


def comparativa_sociedades(anio: str, pais: str = None,
                            tipo_energia: str = 'electricidad') -> dict:
    """Fase 5: comparativa de emisiones entre sociedades."""
    sociedades = emisiones_por_sociedad(anio=anio, pais=pais, tipo_energia=tipo_energia)
    if not sociedades:
        return {'anio': anio, 'sociedades': [], 'estadisticas': None}

    valores = [s['total_emisiones'] for s in sociedades if s['total_emisiones']]
    total   = sumar(valores)

    # Añadir porcentaje del total
    for s in sociedades:
        s['pct_total'] = porcentaje(s['total_emisiones'] / total * 100) if total else 0

    return {
        'anio': anio,
        'pais': pais,
        'sociedades': sociedades,
        'estadisticas': {
            'n_sociedades':    len(sociedades),
            'total_emisiones': total,
            'sociedad_mayor':  sociedades[0]['sociedad'] if sociedades else None,
            'emisiones_mayor': sociedades[0]['total_emisiones'] if sociedades else None,
        },
    }
