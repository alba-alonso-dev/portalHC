"""
Servicio de detección de huecos y calidad de datos — Fase 3.

Responsabilidades:
  - Detectar meses sin cobertura (ni factura real ni estimación vigente).
  - Calcular indicadores de calidad de datos por sede, país y globales.
  - Registrar nuevos huecos detectados en la tabla periodos_faltantes.
  - Alimentar el dashboard con métricas de completitud.

Compatibilidad futura:
  - Diseñado para múltiples módulos (gas, agua, residuos, viajes) cuando
    se extienda el portal a otros tipos de energía.
"""

import logging
from datetime import date
from calendar import monthrange
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


# ── Detección de huecos ───────────────────────────────────────────────────────

def detectar_periodos_faltantes(pais: str = None, sede: str = None,
                                 anio: str = None,
                                 tipo_energia: str = 'electricidad') -> list[dict]:
    """
    Detecta meses sin cobertura y los registra en `periodos_faltantes`.

    Para cada sede activa (con al menos una factura real en el rango),
    genera la secuencia esperada de meses (de la primera a la última factura)
    y marca los huecos que no tienen ni factura ni estimación vigente.

    Returns la lista de periodos faltantes para los filtros indicados.
    """
    sedes = _obtener_sedes_activas(pais, sede, tipo_energia)

    for s in sedes:
        _detectar_huecos_sede(s['pais'], s['sede'], tipo_energia, anio)

    return listar_periodos_faltantes(pais, sede, anio, tipo_energia, solo_faltantes=True)


def listar_periodos_faltantes(pais: str = None, sede: str = None,
                               anio: str = None, tipo_energia: str = 'electricidad',
                               solo_faltantes: bool = False) -> list[dict]:
    cond, params = [], []
    if pais:          cond.append("pais=?");         params.append(pais.upper())
    if sede:          cond.append("sede=?");         params.append(sede)
    if anio:          cond.append("anio=?");         params.append(str(anio))
    if tipo_energia:  cond.append("tipo_energia=?"); params.append(tipo_energia)
    if solo_faltantes: cond.append("estado='faltante'")

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM periodos_faltantes {where} ORDER BY pais, sede, mes",
            params
        ).fetchall()
    return [dict(r) for r in rows]


# ── Indicadores de calidad de datos ──────────────────────────────────────────

def calcular_calidad_sede(pais: str, sede: str, anio: str,
                           tipo_energia: str = 'electricidad') -> dict:
    """
    Calcula los indicadores de calidad para una sede y año concretos.

    Returns:
      total_meses, meses_reales, meses_estimados, meses_faltantes,
      pct_real, pct_estimado, pct_faltante, completo (bool)
    """
    pais = pais.upper()
    total = 12
    with get_db_connection() as conn:
        reales = conn.execute(
            '''SELECT COUNT(DISTINCT substr(periodo_inicio,1,7)) AS n
               FROM facturas
               WHERE pais=? AND sede=? AND tipo_dato='real'
                 AND tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?''',
            (pais, sede, tipo_energia, anio)
        ).fetchone()['n']

        estimados = conn.execute(
            "SELECT COUNT(*) AS n FROM estimaciones "
            "WHERE pais=? AND sede=? AND tipo_energia=? "
            "AND substr(mes,1,4)=? AND estado='vigente'",
            (pais, sede, tipo_energia, anio)
        ).fetchone()['n']

    # También contar sustituidos (ya tienen la factura real)
    cubiertos = reales + estimados
    faltantes = max(0, total - cubiertos)

    return {
        'pais':           pais,
        'sede':           sede,
        'anio':           anio,
        'tipo_energia':   tipo_energia,
        'total_meses':    total,
        'meses_reales':   reales,
        'meses_estimados': estimados,
        'meses_faltantes': faltantes,
        'pct_real':        round(reales / total * 100, 1),
        'pct_estimado':    round(estimados / total * 100, 1),
        'pct_faltante':    round(faltantes / total * 100, 1),
        'completo':        faltantes == 0,
        'requiere_revision': faltantes > 0 or estimados > 0,
    }


def resumen_calidad_global(anio: str = None,
                            tipo_energia: str = 'electricidad') -> dict:
    """
    Métricas globales de calidad de datos para el dashboard.
    Si anio es None usa el año en curso.
    """
    if not anio:
        anio = str(date.today().year)

    with get_db_connection() as conn:
        # Total facturas reales en el año
        total_reales = conn.execute(
            '''SELECT COUNT(*) FROM facturas
               WHERE tipo_dato='real' AND tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?''',
            (tipo_energia, anio)
        ).fetchone()[0]

        # Total estimaciones vigentes
        total_estimados = conn.execute(
            "SELECT COUNT(*) FROM estimaciones "
            "WHERE tipo_energia=? AND substr(mes,1,4)=? AND estado='vigente'",
            (tipo_energia, anio)
        ).fetchone()[0]

        # Total faltantes aún no cubiertos
        total_faltantes = conn.execute(
            "SELECT COUNT(*) FROM periodos_faltantes "
            "WHERE tipo_energia=? AND anio=? AND estado='faltante'",
            (tipo_energia, anio)
        ).fetchone()[0]

        # Sedes activas en el año
        sedes_activas = conn.execute(
            '''SELECT COUNT(DISTINCT pais||'/'||sede) FROM facturas
               WHERE tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?''',
            (tipo_energia, anio)
        ).fetchone()[0]

        # Emisiones totales y recalculadas
        emis_orig = conn.execute(
            '''SELECT COALESCE(SUM(emisiones_tco2e),0) FROM facturas
               WHERE tipo_dato='real' AND tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?''',
            (tipo_energia, anio)
        ).fetchone()[0]

        emis_recalc = conn.execute(
            '''SELECT COALESCE(SUM(emisiones_recalculadas),0) FROM facturas
               WHERE tipo_dato='real' AND tipo_energia=?
                 AND emisiones_recalculadas IS NOT NULL
                 AND substr(periodo_inicio,1,4)=?''',
            (tipo_energia, anio)
        ).fetchone()[0]

        emis_estimadas = conn.execute(
            "SELECT COALESCE(SUM(emisiones_estimadas),0) FROM estimaciones "
            "WHERE tipo_energia=? AND substr(mes,1,4)=? AND estado='vigente'",
            (tipo_energia, anio)
        ).fetchone()[0]

        # Recálculos realizados
        recalculos = conn.execute(
            '''SELECT COUNT(*) FROM recalculos_historial rh
               JOIN facturas f ON f.id=rh.factura_id
               WHERE strftime('%Y', rh.fecha_recalculo)=?''',
            (anio,)
        ).fetchone()[0]

        # Periodos con recálculo activo (column not null)
        facturas_recalc = conn.execute(
            '''SELECT COUNT(*) FROM facturas
               WHERE emisiones_recalculadas IS NOT NULL AND tipo_dato='real'
                 AND tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?''',
            (tipo_energia, anio)
        ).fetchone()[0]

    total_cobertura = total_reales + total_estimados + total_faltantes
    return {
        'anio':               anio,
        'tipo_energia':       tipo_energia,
        'total_reales':       total_reales,
        'total_estimados':    total_estimados,
        'total_faltantes':    total_faltantes,
        'sedes_activas':      sedes_activas,
        'pct_real':           round(total_reales / total_cobertura * 100, 1) if total_cobertura else 0,
        'pct_estimado':       round(total_estimados / total_cobertura * 100, 1) if total_cobertura else 0,
        'pct_faltante':       round(total_faltantes / total_cobertura * 100, 1) if total_cobertura else 0,
        'emisiones_originales':  round(emis_orig, 4),
        'emisiones_recalculadas': round(emis_recalc, 4),
        'emisiones_estimadas':   round(emis_estimadas, 4),
        'facturas_con_recalculo': facturas_recalc,
        'total_recalculos':      recalculos,
    }


def calidad_por_sede(anio: str = None,
                     tipo_energia: str = 'electricidad') -> list[dict]:
    """Lista de sedes con sus indicadores de calidad para el año dado."""
    if not anio:
        anio = str(date.today().year)

    with get_db_connection() as conn:
        sedes = conn.execute(
            '''SELECT DISTINCT pais, sede FROM facturas
               WHERE tipo_energia=?
                 AND substr(periodo_inicio,1,4)=?
               ORDER BY pais, sede''',
            (tipo_energia, anio)
        ).fetchall()

    return [
        calcular_calidad_sede(s['pais'], s['sede'], anio, tipo_energia)
        for s in sedes
    ]


# ── Helpers privados ──────────────────────────────────────────────────────────

def _obtener_sedes_activas(pais: str = None, sede: str = None,
                            tipo_energia: str = 'electricidad') -> list[dict]:
    cond = ["tipo_dato='real'", "tipo_energia=?"]
    params = [tipo_energia]
    if pais: cond.append("pais=?"); params.append(pais.upper())
    if sede: cond.append("sede=?"); params.append(sede)

    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT pais, sede FROM facturas WHERE {' AND '.join(cond)}",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def _detectar_huecos_sede(pais: str, sede: str, tipo_energia: str, anio: str = None):
    """Registra en periodos_faltantes los meses sin cobertura para una sede."""
    with get_db_connection() as conn:
        # Rango de meses con facturas reales
        row = conn.execute(
            '''SELECT MIN(substr(periodo_inicio,1,7)) AS desde,
                      MAX(substr(periodo_inicio,1,7)) AS hasta
               FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                 AND periodo_inicio IS NOT NULL''',
            (pais, sede, tipo_energia)
        ).fetchone()

    if not row or not row['desde']:
        return

    desde = row['desde']
    hasta  = row['hasta']

    if anio:
        desde = max(desde, f"{anio}-01")
        hasta  = min(hasta, f"{anio}-12")

    # Generar secuencia mensual
    meses_esperados = _rango_meses(desde, hasta)

    with get_db_connection() as conn:
        # Meses cubiertos por facturas reales
        real_rows = conn.execute(
            '''SELECT DISTINCT substr(periodo_inicio,1,7) AS m
               FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                 AND periodo_inicio IS NOT NULL''',
            (pais, sede, tipo_energia)
        ).fetchall()
        reales = {r['m'] for r in real_rows}

        # Meses cubiertos por estimaciones
        est_rows = conn.execute(
            "SELECT DISTINCT mes FROM estimaciones "
            "WHERE pais=? AND sede=? AND tipo_energia=? AND estado IN ('vigente','sustituida')",
            (pais, sede, tipo_energia)
        ).fetchall()
        estimados = {r['mes'] for r in est_rows}

        for mes in meses_esperados:
            if mes in reales or mes in estimados:
                # Si el periodo existe en periodos_faltantes como faltante, actualizarlo
                conn.execute(
                    '''UPDATE periodos_faltantes SET estado='cubierto', resolucion_fecha=CURRENT_TIMESTAMP
                       WHERE pais=? AND sede=? AND tipo_energia=? AND mes=? AND estado='faltante' ''',
                    (pais, sede, tipo_energia, mes)
                )
            else:
                conn.execute(
                    '''INSERT OR IGNORE INTO periodos_faltantes
                           (pais, sede, tipo_energia, anio, mes)
                       VALUES (?,?,?,?,?)''',
                    (pais, sede, tipo_energia, mes[:4], mes)
                )


def _rango_meses(desde: str, hasta: str) -> list[str]:
    """Genera lista ['YYYY-MM', ...] entre desde y hasta inclusive."""
    resultado = []
    anio, mes = int(desde[:4]), int(desde[5:7])
    anio_fin, mes_fin = int(hasta[:4]), int(hasta[5:7])
    while (anio, mes) <= (anio_fin, mes_fin):
        resultado.append(f"{anio:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1; anio += 1
    return resultado
