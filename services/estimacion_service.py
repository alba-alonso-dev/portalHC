"""
Motor de estimación de consumos para periodos sin factura real — Fase 3 + Fase 4.

Métodos soportados:
  1. media_historica          — media de todos los periodos disponibles de la sede.
  2. mismo_mes_anio_anterior  — consumo del mismo mes del año anterior.
  3. adyacente                — media de los meses inmediatamente anterior y siguiente.
  4. manual                   — valor introducido directamente por el usuario.
  5. sede_similar             — media de sedes del mismo país y tipo de energía (Fase 4).
  6. ponderado                — combinación de histórico propio + grupo + tendencia (Fase 4).

Ciclo de vida de una estimación:
  vigente → sustituida  (llega factura real)
  vigente → rechazada   (usuario descarta)

La desviación respecto al valor real se calcula automáticamente al sustituir.
Métricas de error disponibles en metricas_error() y metricas_error_por_metodo().
"""

import json
import logging
from datetime import date, datetime
from database.connection import get_db_connection
from services.emisiones_service import obtener_factor
from services.numeros import calcular_tco2e, kwh_a_mwh

logger = logging.getLogger(__name__)

METODOS_DISPONIBLES = {
    'media_historica', 'mismo_mes_anio_anterior', 'adyacente',
    'manual', 'sede_similar', 'ponderado',
    'por_dias',     # Fase 5: pro-rata basado en días de facturación
    'estacional',   # Fase 5: histórico propio con índice de estacionalidad
}


# ── Creación de estimaciones ──────────────────────────────────────────────────

def crear_estimacion(pais: str, sede: str, mes: str,
                     metodo: str, valor_manual: float = None,
                     tipo_energia: str = 'electricidad',
                     notas: str = None, creado_por: str = 'usuario') -> dict:
    """
    Genera una estimación para un mes (formato YYYY-MM).

    metodo: 'media_historica' | 'mismo_mes_anio_anterior' | 'adyacente' |
            'manual' | 'sede_similar' | 'ponderado' |
            'por_dias' (Fase 5) | 'estacional' (Fase 5)
    """
    pais = pais.upper()
    _validar_mes(mes)

    if metodo == 'manual':
        if valor_manual is None or valor_manual <= 0:
            raise ValueError("El método manual requiere valor_manual > 0")
        kwh = valor_manual
        referencias = []
        detalle = {'metodo': 'manual', 'valor_introducido': valor_manual}
    elif metodo == 'media_historica':
        kwh, referencias = _media_historica(pais, sede, tipo_energia, excluir_mes=mes)
        detalle = {'metodo': 'media_historica', 'n_facturas': len(referencias)}
    elif metodo == 'mismo_mes_anio_anterior':
        kwh, referencias = _mismo_mes_anio_anterior(pais, sede, mes, tipo_energia)
        detalle = {'metodo': 'mismo_mes_anio_anterior', 'mes_referencia': f"{str(int(mes[:4])-1)}-{mes[5:7]}"}
    elif metodo == 'adyacente':
        kwh, referencias = _adyacente(pais, sede, mes, tipo_energia)
        detalle = {'metodo': 'adyacente', 'n_meses_adyacentes': len(referencias)}
    elif metodo == 'sede_similar':
        kwh, referencias, detalle = _sede_similar(pais, sede, mes, tipo_energia)
    elif metodo == 'ponderado':
        kwh, referencias, detalle = _ponderado(pais, sede, mes, tipo_energia)
    elif metodo == 'por_dias':
        # Fase 5: pro-rata basado en días de consumo reales adyacentes
        kwh, referencias, detalle = _por_dias(pais, sede, mes, tipo_energia)
    elif metodo == 'estacional':
        # Fase 5: histórico propio con índice de estacionalidad mensual
        kwh, referencias, detalle = _estacional(pais, sede, mes, tipo_energia)
    else:
        raise ValueError(f"Método desconocido: {metodo}. "
                         f"Opciones: {sorted(METODOS_DISPONIBLES)}")

    if kwh is None or kwh <= 0:
        raise ValueError(
            f"No hay suficientes datos para estimar por el método '{metodo}' "
            f"para {pais}/{sede}/{mes}"
        )

    mwh = kwh_a_mwh(kwh)
    anio = mes[:4]
    factor, fuente, _, factor_version_id = obtener_factor(pais, anio)
    emisiones = calcular_tco2e(mwh, factor) if factor else None
    confianza = _confianza(metodo, len(referencias))
    confianza_texto = _confianza_texto(confianza)

    # Calcular periodo
    anio_int, mes_int = int(mes[:4]), int(mes[5:7])
    from calendar import monthrange
    dias = monthrange(anio_int, mes_int)[1]
    periodo_inicio = f"{mes}-01"
    periodo_fin    = f"{mes}-{dias:02d}"

    with get_db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO estimaciones
                (pais, sede, tipo_energia, periodo_inicio, periodo_fin, mes,
                 consumo_kwh_estimado, consumo_mwh_estimado, emisiones_estimadas,
                 factor_emision, factor_version_id, metodo_estimacion,
                 confianza, referencia_facturas_json, valor_manual,
                 creado_por, notas, metodo_detalle_json, confianza_texto, n_referencias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            pais, sede, tipo_energia, periodo_inicio, periodo_fin, mes,
            round(kwh, 2), mwh, emisiones,
            factor, factor_version_id, metodo,
            confianza, json.dumps(referencias, ensure_ascii=False),
            valor_manual, creado_por, notas,
            json.dumps(detalle, ensure_ascii=False),
            confianza_texto, len(referencias),
        ))
        est_id = cursor.lastrowid

        # Actualizar tabla periodos_faltantes si existe el hueco
        conn.execute('''
            UPDATE periodos_faltantes
            SET estado='estimado', estimacion_id=?, resolucion_fecha=CURRENT_TIMESTAMP
            WHERE pais=? AND sede=? AND tipo_energia=? AND mes=? AND estado='faltante'
        ''', (est_id, pais, sede, tipo_energia, mes))

    return obtener_estimacion(est_id)


def obtener_estimacion(est_id: int) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM estimaciones WHERE id=?", (est_id,)).fetchone()
    return dict(row) if row else None


def listar_estimaciones(pais: str = None, sede: str = None,
                        anio: str = None, estado: str = None) -> list[dict]:
    cond, params = [], []
    if pais:    cond.append("pais=?");  params.append(pais.upper())
    if sede:    cond.append("sede=?");  params.append(sede)
    if anio:    cond.append("substr(mes,1,4)=?"); params.append(str(anio))
    if estado:  cond.append("estado=?"); params.append(estado)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM estimaciones {where} ORDER BY mes DESC, pais, sede",
            params
        ).fetchall()
    return [dict(r) for r in rows]


def sustituir_por_real(estimacion_id: int, factura_real_id: int) -> dict:
    """
    Marca la estimación como sustituida cuando llega la factura real.
    Calcula la desviación porcentual entre estimado y real.
    Fase 6: actualiza métricas de precisión por método (reconciliación automática).
    """
    est = obtener_estimacion(estimacion_id)
    if not est:
        raise ValueError(f"Estimación {estimacion_id} no encontrada")
    if est['estado'] != 'vigente':
        raise ValueError(f"La estimación ya está en estado '{est['estado']}'")

    with get_db_connection() as conn:
        factura = conn.execute(
            "SELECT consumo_kwh, emisiones_tco2e FROM facturas WHERE id=?",
            (factura_real_id,)
        ).fetchone()
        if not factura:
            raise ValueError(f"Factura real {factura_real_id} no encontrada")

        # La estimación cubre el consumo de TODO el mes de la sede. Si la sede
        # tiene varios CUPS, ese mes llega en varias facturas y compararlo con
        # una sola infla artificialmente el error y descalibra las métricas de
        # precisión por método. Se agrega el mes completo.
        real_mes = conn.execute(
            '''SELECT SUM(consumo_kwh)     AS kwh,
                      SUM(emisiones_tco2e) AS emis,
                      COUNT(*)             AS n
               FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                 AND substr(periodo_inicio,1,7) = ?
                 AND fecha_anulacion IS NULL''',
            (est['pais'], est['sede'], est['tipo_energia'], est['mes'])
        ).fetchone()

        if real_mes and real_mes['n']:
            emis_real = real_mes['emis'] or 0.0
            kwh_real  = real_mes['kwh'] or 0.0
        else:
            # Sin período legible en la factura real: se compara contra ella sola.
            emis_real = factura['emisiones_tco2e'] or 0.0
            kwh_real  = factura['consumo_kwh'] or 0.0

        emis_est   = est['emisiones_estimadas'] or 0.0
        kwh_est    = est['consumo_kwh_estimado'] or 0.0

        # Errores en emisiones
        desviacion = round(
            abs(emis_est - emis_real) / emis_real * 100 if emis_real else 0.0, 2
        )
        error_abs_emis = round(abs(emis_est - emis_real), 4)

        # Errores en kWh (más precisos para calibración del modelo)
        error_abs_kwh = round(abs(kwh_est - kwh_real), 2) if kwh_real else None
        error_rel_pct = round(
            abs(kwh_est - kwh_real) / kwh_real * 100, 2
        ) if kwh_real and kwh_est else None

        conn.execute('''
            UPDATE estimaciones
            SET estado='sustituida', factura_real_id=?,
                desviacion_porcentual_real=?, error_absoluto=?,
                error_absoluto_kwh=?, error_relativo_pct=?,
                sustituida_en=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (factura_real_id, desviacion, error_abs_emis,
              error_abs_kwh, error_rel_pct, estimacion_id))

        # Actualizar periodos_faltantes
        conn.execute('''
            UPDATE periodos_faltantes
            SET estado='cubierto', factura_id=?, resolucion_fecha=CURRENT_TIMESTAMP
            WHERE estimacion_id=?
        ''', (factura_real_id, estimacion_id))

        # Fase 6: actualizar métricas acumuladas por método
        metodo = est.get('metodo', 'media_historica')
        if error_abs_kwh is not None and error_rel_pct is not None:
            try:
                conn.execute("""
                    INSERT INTO metodo_estimacion_metricas (metodo, n_sustituciones,
                        suma_error_abs, suma_error_rel, max_error_abs, max_error_rel,
                        ultima_actualizacion)
                    VALUES (?, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(metodo) DO UPDATE SET
                        n_sustituciones    = n_sustituciones + 1,
                        suma_error_abs     = suma_error_abs + excluded.suma_error_abs,
                        suma_error_rel     = suma_error_rel + excluded.suma_error_rel,
                        max_error_abs      = MAX(COALESCE(max_error_abs, 0), excluded.max_error_abs),
                        max_error_rel      = MAX(COALESCE(max_error_rel, 0), excluded.max_error_rel),
                        ultima_actualizacion = CURRENT_TIMESTAMP
                """, (metodo, error_abs_kwh, error_rel_pct,
                      error_abs_kwh, error_rel_pct))
            except Exception as exc:
                logger.warning(f"No se pudieron actualizar métricas del método {metodo}: {exc}")

    return obtener_estimacion(estimacion_id)


def rechazar_estimacion(estimacion_id: int) -> dict:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE estimaciones SET estado='rechazada' WHERE id=? AND estado='vigente'",
            (estimacion_id,)
        )
    return obtener_estimacion(estimacion_id)


# ── Métodos de cálculo ────────────────────────────────────────────────────────

def _consumos_mensuales(pais: str, sede: str, tipo_energia: str,
                        excluir_mes: str = None) -> list[dict]:
    """
    Devuelve el consumo mensual REAL de una sede, sumando todos sus CUPS.

    Una sede puede tener varios puntos de suministro (CUPS) y recibir una
    factura por cada uno en el mismo mes. El consumo del mes es la SUMA de
    todas ellas. Los métodos de estimación asumían "una factura = un mes" y
    tomaban `LIMIT 1` o promediaban factura a factura, de modo que en una sede
    con 2-3 CUPS estimaban solo la parte de uno de ellos e infravaloraban el
    consumo (y por tanto las emisiones) en proporción al número de CUPS.

    Cada elemento incluye:
      mes, total_kwh, dias (span del período, no la suma entre CUPS),
      n_facturas, n_cups, refs (ids de las facturas agregadas).
    """
    params = [pais, sede, tipo_energia]
    extra = ""
    if excluir_mes:
        extra = " AND substr(periodo_inicio,1,7) != ?"
        params.append(excluir_mes)

    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT substr(periodo_inicio,1,7) AS mes,
                       SUM(consumo_kwh)           AS total_kwh,
                       MAX(COALESCE(dias_facturados,0)) AS dias,
                       COUNT(*)                   AS n_facturas,
                       COUNT(DISTINCT COALESCE(cups,'')) AS n_cups,
                       GROUP_CONCAT(CAST(id AS TEXT)) AS ids
                FROM facturas
                WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                  AND consumo_kwh IS NOT NULL AND consumo_kwh > 0
                  AND periodo_inicio IS NOT NULL
                  AND fecha_anulacion IS NULL
                  {extra}
                GROUP BY mes
                ORDER BY mes''',
            params
        ).fetchall()

    return [{
        'mes':         r['mes'],
        'total_kwh':   r['total_kwh'],
        'dias':        r['dias'] or 0,
        'n_facturas':  r['n_facturas'],
        'n_cups':      r['n_cups'],
        'refs':        [int(x) for x in (r['ids'] or '').split(',') if x],
    } for r in rows]


def _consumo_del_mes(pais: str, sede: str, tipo_energia: str,
                     mes: str) -> dict | None:
    """Consumo total (todos los CUPS) de un mes concreto, o None si no hay datos."""
    for m in _consumos_mensuales(pais, sede, tipo_energia):
        if m['mes'] == mes:
            return m
    return None


def _media_historica(pais: str, sede: str, tipo_energia: str,
                     excluir_mes: str = None) -> tuple[float | None, list]:
    """Media del consumo MENSUAL histórico (cada mes ya suma todos sus CUPS)."""
    meses = _consumos_mensuales(pais, sede, tipo_energia, excluir_mes)
    if not meses:
        return None, []
    media = round(sum(m['total_kwh'] for m in meses) / len(meses), 2)
    refs  = [fid for m in meses for fid in m['refs']]
    return media, refs


def _mismo_mes_anio_anterior(pais: str, sede: str, mes: str,
                              tipo_energia: str) -> tuple[float | None, list]:
    anio_ant = str(int(mes[:4]) - 1)
    mes_ant  = f"{anio_ant}-{mes[5:7]}"
    dato = _consumo_del_mes(pais, sede, tipo_energia, mes_ant)
    if not dato or not dato['total_kwh']:
        return None, []
    return round(dato['total_kwh'], 2), dato['refs']


def _adyacente(pais: str, sede: str, mes: str,
               tipo_energia: str) -> tuple[float | None, list]:
    """Media de los meses inmediatamente anterior y siguiente."""
    anio_int, mes_int = int(mes[:4]), int(mes[5:7])

    def mes_offset(delta: int) -> str:
        m = mes_int + delta
        a = anio_int
        if m < 1:   a -= 1; m += 12
        if m > 12:  a += 1; m -= 12
        return f"{a:04d}-{m:02d}"

    por_mes = {m['mes']: m for m in _consumos_mensuales(pais, sede, tipo_energia)}

    valores, refs = [], []
    for delta in (-1, 1):
        dato = por_mes.get(mes_offset(delta))
        if dato and dato['total_kwh']:
            valores.append(dato['total_kwh'])
            refs.extend(dato['refs'])

    if not valores:
        return None, []
    return round(sum(valores) / len(valores), 2), refs


def _confianza(metodo: str, n_referencias: int) -> float:
    base = {
        'mismo_mes_anio_anterior': 0.85,
        'estacional':              0.82,  # Fase 5
        'por_dias':                0.80,  # Fase 5
        'adyacente':               0.75,
        'ponderado':               0.70,
        'media_historica':         0.65,
        'sede_similar':            0.55,
        'manual':                  0.50,
    }.get(metodo, 0.50)
    # Bonus por más datos históricos (máx +0.10)
    bonus = min(n_referencias * 0.02, 0.10) if n_referencias > 0 else 0
    return round(min(base + bonus, 1.0), 2)


def _confianza_texto(confianza: float) -> str:
    if confianza >= 0.85:
        return "Alta"
    if confianza >= 0.70:
        return "Media-Alta"
    if confianza >= 0.55:
        return "Media"
    return "Baja"


def _validar_mes(mes: str):
    try:
        anio, m = mes.split('-')
        assert 2000 <= int(anio) <= 2100 and 1 <= int(m) <= 12
    except Exception:
        raise ValueError(f"Formato de mes inválido: '{mes}'. Use YYYY-MM.")


# ── Método 5: sede_similar (Fase 4) ──────────────────────────────────────────

def _sede_similar(pais: str, sede: str, mes: str,
                  tipo_energia: str) -> tuple[float | None, list, dict]:
    """
    Estima el consumo usando la media de sedes del mismo país y tipo de energía.
    Se usa cuando la sede no tiene suficiente histórico propio.

    Excluye la propia sede del cálculo.
    Requiere al menos 2 sedes similares con datos.

    La referencia es el consumo MENSUAL de cada sede (suma de sus CUPS), no la
    media por factura: una sede con 3 CUPS tiene 3 facturas al mes, y promediar
    factura a factura devolvía el consumo de un punto de suministro medio en vez
    del de una sede.
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            '''SELECT sede, AVG(total_mes) as media, COUNT(*) as n
               FROM (
                   SELECT sede, substr(periodo_inicio,1,7) as mes,
                          SUM(consumo_kwh) as total_mes
                   FROM facturas
                   WHERE pais=? AND tipo_energia=? AND sede != ?
                     AND tipo_dato='real'
                     AND consumo_kwh IS NOT NULL AND consumo_kwh > 0
                     AND periodo_inicio IS NOT NULL
                     AND fecha_anulacion IS NULL
                   GROUP BY sede, mes
               )
               GROUP BY sede
               HAVING n >= 3
               ORDER BY n DESC
               LIMIT 5''',
            (pais, tipo_energia, sede)
        ).fetchall()

    if len(rows) < 2:
        return None, [], {'error': 'Menos de 2 sedes similares con suficientes datos'}

    valores = [r['media'] for r in rows]
    media = round(sum(valores) / len(valores), 2)
    refs_sedes = [r['sede'] for r in rows]

    detalle = {
        'metodo': 'sede_similar',
        'pais': pais,
        'sedes_referencia': refs_sedes,
        'n_sedes': len(rows),
        'media_calculada_kwh': media,
    }
    return media, refs_sedes, detalle


# ── Método 6: ponderado (Fase 4) ─────────────────────────────────────────────

def _ponderado(pais: str, sede: str, mes: str,
               tipo_energia: str) -> tuple[float | None, list, dict]:
    """
    Estimación ponderada que combina:
      - 50%: histórico propio (media_historica de la sede)
      - 30%: mismo mes años anteriores (promedio de los últimos 3 años)
      - 20%: media del grupo (sede_similar)

    Si algún componente no está disponible, redistribuye el peso.
    """
    propio, refs_propio = _media_historica(pais, sede, tipo_energia, excluir_mes=mes)
    propio_mes, refs_mes_ant = _mismo_mes_anio_anterior(pais, sede, mes, tipo_energia)

    # Media del grupo
    grupo_result = _sede_similar(pais, sede, mes, tipo_energia)
    grupo = grupo_result[0] if grupo_result[0] else None
    refs_grupo = grupo_result[1] if grupo_result[0] else []

    componentes = []
    if propio:
        componentes.append(('historico_propio', propio, 0.50))
    if propio_mes:
        componentes.append(('mismo_mes_anterior', propio_mes, 0.30))
    if grupo:
        componentes.append(('grupo_sedes', grupo, 0.20))

    if not componentes:
        return None, [], {'error': 'No hay datos suficientes para ningún componente'}

    # Renormalizar pesos
    total_peso = sum(c[2] for c in componentes)
    valor_final = sum(c[1] * (c[2] / total_peso) for c in componentes)
    valor_final = round(valor_final, 2)

    todas_refs = refs_propio + (refs_mes_ant or []) + (refs_grupo or [])
    detalle = {
        'metodo': 'ponderado',
        'componentes': [
            {'nombre': c[0], 'valor_kwh': c[1], 'peso_original': c[2],
             'peso_normalizado': round(c[2] / total_peso, 3)}
            for c in componentes
        ],
        'valor_final_kwh': valor_final,
    }
    return valor_final, todas_refs, detalle


# ── Método 7: por_dias — pro-rata (Fase 5) ────────────────────────────────────

def _por_dias(pais: str, sede: str, mes: str,
              tipo_energia: str) -> tuple[float | None, list, dict]:
    """
    Estimación pro-rata basada en días de consumo.

    Estrategia:
      1. Tomar los 3 meses adyacentes con datos reales.
      2. Calcular el ratio kWh/día de cada uno.
      3. Aplicar la media de ese ratio a los días del mes a estimar.

    Ventaja sobre 'adyacente': normaliza por longitud de período, reduciendo
    el error cuando los períodos de facturación tienen distinto número de días.
    Requiere que las facturas tengan dias_facturados registrado.

    El ratio se calcula sobre el consumo mensual agregado (todos los CUPS de la
    sede) dividido por la duración del período, no por la suma de días de cada
    factura: sumar los días de 3 CUPS del mismo mes daría ~90 días para un mes
    natural y dividiría el ratio por tres.
    """
    from calendar import monthrange
    anio_int, mes_int = int(mes[:4]), int(mes[5:7])
    dias_mes = monthrange(anio_int, mes_int)[1]

    def meses_cercanos() -> list[str]:
        result = []
        for delta in (-2, -1, 1, 2, -3, 3):
            m = mes_int + delta
            a = anio_int
            if m < 1:  a -= 1; m += 12
            if m > 12: a += 1; m -= 12
            result.append(f"{a:04d}-{m:02d}")
        return result

    por_mes = {m['mes']: m for m in _consumos_mensuales(pais, sede, tipo_energia)}

    ratios, refs = [], []
    for m_cercano in meses_cercanos():
        dato = por_mes.get(m_cercano)
        if dato and dato['total_kwh'] > 0 and dato['dias'] > 0:
            ratios.append(dato['total_kwh'] / dato['dias'])
            refs.extend(dato['refs'])
        if len(ratios) >= 3:
            break

    if not ratios:
        return None, [], {'error': 'Sin datos de kWh/día en meses cercanos'}

    kwh_dia_medio = sum(ratios) / len(ratios)
    kwh_estimado = round(kwh_dia_medio * dias_mes, 2)

    detalle = {
        'metodo': 'por_dias',
        'dias_mes': dias_mes,
        'kwh_dia_medio': round(kwh_dia_medio, 4),
        'n_referencias': len(ratios),
        'ratios_kwh_dia': [round(r, 4) for r in ratios],
    }
    return kwh_estimado, refs, detalle


# ── Método 8: estacional (Fase 5) ─────────────────────────────────────────────

def _estacional(pais: str, sede: str, mes: str,
                tipo_energia: str) -> tuple[float | None, list, dict]:
    """
    Estimación con índice de estacionalidad calculado desde el histórico propio.

    Algoritmo:
      1. Calcular la media anual de todos los años disponibles.
      2. Para cada mes, calcular su índice = consumo_mes / media_anual.
      3. Aplicar el índice medio del mes objetivo a la media histórica global.

    Ejemplo: si históricamente enero representa el 130% de la media,
    la estimación para enero será media_global × 1.30.

    Requiere al menos 2 ciclos completos (≥ 12 meses) para ser fiable.

    Trabaja sobre meses agregados (suma de todos los CUPS de la sede). Antes
    contaba facturas: una sede con 3 CUPS alcanzaba el mínimo de 12 con solo 4
    meses reales de histórico y calculaba índices de estacionalidad sobre
    consumos de puntos de suministro sueltos.
    """
    mes_num = mes[5:7]  # "01".."12"

    meses = _consumos_mensuales(pais, sede, tipo_energia, excluir_mes=mes)

    if len(meses) < 12:
        return None, [], {'error': f'Insuficientes datos para estacionalidad (n={len(meses)} meses, mínimo 12)'}

    # Agrupar por mes del año (1-12) → listas de consumos mensuales
    por_mes: dict[str, list[float]] = {}
    for m in meses:
        por_mes.setdefault(m['mes'][5:7], []).append(m['total_kwh'])

    # Media global (de todos los meses disponibles)
    media_global = sum(m['total_kwh'] for m in meses) / len(meses)
    if media_global <= 0:
        return None, [], {'error': 'Media global nula'}

    # Índice de estacionalidad del mes objetivo
    consumos_mes_objetivo = por_mes.get(mes_num, [])
    if not consumos_mes_objetivo:
        return None, [], {'error': f'Sin histórico para el mes {mes_num}'}

    media_mes = sum(consumos_mes_objetivo) / len(consumos_mes_objetivo)
    indice = media_mes / media_global

    kwh_estimado = round(media_global * indice, 2)
    refs = [fid for m in meses for fid in m['refs']]

    detalle = {
        'metodo': 'estacional',
        'media_global_kwh': round(media_global, 2),
        'media_mes_kwh': round(media_mes, 2),
        'indice_estacionalidad': round(indice, 4),
        'n_meses_historico': len(meses),
        'n_total_facturas': sum(m['n_facturas'] for m in meses),
        'n_meses_mes_objetivo': len(consumos_mes_objetivo),
    }
    return kwh_estimado, refs, detalle


# ── Gestión de huecos pequeños (Fase 5) ──────────────────────────────────────

def resolver_hueco_pequeno(pais: str, sede: str, mes: str,
                            tipo_energia: str = 'electricidad',
                            umbral_dias: int = 5,
                            creado_por: str = 'sistema') -> dict | None:
    """
    Detecta y resuelve automáticamente huecos de cobertura pequeños (≤ umbral_dias días).

    Un hueco pequeño ocurre cuando el período sin datos es tan corto que
    el método 'por_dias' puede estimarlo con alta confianza sin intervención manual.

    Returns None si el hueco no es pequeño o no se puede resolver.
    Returns la estimación creada si se resolvió.
    """
    from calendar import monthrange

    # Verificar si ya hay datos para este mes
    with get_db_connection() as conn:
        existente = conn.execute(
            '''SELECT COUNT(*) FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=? AND tipo_dato='real'
                 AND substr(periodo_inicio,1,7) = ? AND fecha_anulacion IS NULL''',
            (pais, sede, tipo_energia, mes)
        ).fetchone()[0]

    if existente > 0:
        return None  # Ya hay datos reales, no hacer nada

    # Calcular días en el mes
    anio_int, mes_int = int(mes[:4]), int(mes[5:7])
    dias_mes = monthrange(anio_int, mes_int)[1]

    if dias_mes > umbral_dias:
        return None  # Hueco demasiado grande

    # Hueco pequeño: usar por_dias
    try:
        return crear_estimacion(
            pais=pais, sede=sede, mes=mes,
            metodo='por_dias', tipo_energia=tipo_energia,
            notas=f'Hueco pequeño ({dias_mes} días) resuelto automáticamente',
            creado_por=creado_por,
        )
    except ValueError:
        return None


def comparativa_metodos(pais: str, sede: str, mes: str,
                         tipo_energia: str = 'electricidad') -> list[dict]:
    """
    Fase 5: calcula la estimación con todos los métodos disponibles para un mes
    y devuelve una comparativa de resultados sin persistir nada.

    Útil para que el usuario elija el método más apropiado.
    """
    resultados = []
    metodos_a_probar = [
        'media_historica', 'mismo_mes_anio_anterior', 'adyacente',
        'ponderado', 'por_dias', 'estacional', 'sede_similar',
    ]

    for metodo in metodos_a_probar:
        try:
            if metodo == 'media_historica':
                kwh, refs = _media_historica(pais, sede, tipo_energia, excluir_mes=mes)
                detalle: dict = {'n': len(refs)}
            elif metodo == 'mismo_mes_anio_anterior':
                kwh, refs = _mismo_mes_anio_anterior(pais, sede, mes, tipo_energia)
                detalle = {'n': len(refs)}
            elif metodo == 'adyacente':
                kwh, refs = _adyacente(pais, sede, mes, tipo_energia)
                detalle = {'n': len(refs)}
            elif metodo == 'ponderado':
                kwh, refs, detalle = _ponderado(pais, sede, mes, tipo_energia)
            elif metodo == 'por_dias':
                kwh, refs, detalle = _por_dias(pais, sede, mes, tipo_energia)
            elif metodo == 'estacional':
                kwh, refs, detalle = _estacional(pais, sede, mes, tipo_energia)
            elif metodo == 'sede_similar':
                kwh, refs, detalle = _sede_similar(pais, sede, mes, tipo_energia)
            else:
                continue

            if kwh and kwh > 0:
                confianza = _confianza(metodo, len(refs))
                resultados.append({
                    'metodo': metodo,
                    'kwh_estimado': kwh,
                    'confianza': confianza,
                    'confianza_texto': _confianza_texto(confianza),
                    'n_referencias': len(refs),
                    'detalle': detalle,
                    'disponible': True,
                })
            else:
                resultados.append({'metodo': metodo, 'disponible': False, 'razon': 'Sin datos suficientes'})
        except Exception as exc:
            resultados.append({'metodo': metodo, 'disponible': False, 'razon': str(exc)})

    # Ordenar por confianza descendente
    resultados.sort(key=lambda x: (x.get('disponible', False), x.get('confianza', 0)), reverse=True)
    return resultados


# ── Métricas de error ─────────────────────────────────────────────────────────

def metricas_error(pais: str = None, sede: str = None,
                   anio: str = None) -> dict:
    """
    Calcula métricas de precisión del motor de estimación.

    Basado en estimaciones 'sustituidas' (validadas con factura real).
    Returns: error_medio_pct, error_mediano_pct, n_validadas, por_metodo[], por_sede[]
    """
    cond, params = ["estado='sustituida'",
                    "desviacion_porcentual_real IS NOT NULL"], []
    if pais:
        cond.append("pais=?"); params.append(pais.upper())
    if sede:
        cond.append("sede=?"); params.append(sede)
    if anio:
        cond.append("substr(mes,1,4)=?"); params.append(str(anio))

    where = "WHERE " + " AND ".join(cond)

    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT pais, sede, metodo_estimacion,
                       desviacion_porcentual_real, error_absoluto
                FROM estimaciones {where}''',
            params
        ).fetchall()

    if not rows:
        return {
            'n_validadas': 0,
            'error_medio_pct': None,
            'error_mediano_pct': None,
            'por_metodo': [],
            'por_sede': [],
        }

    desviaciones = [r['desviacion_porcentual_real'] for r in rows]
    error_medio = round(sum(desviaciones) / len(desviaciones), 2)

    sorted_dev = sorted(desviaciones)
    n = len(sorted_dev)
    if n % 2 == 0:
        mediana = (sorted_dev[n // 2 - 1] + sorted_dev[n // 2]) / 2
    else:
        mediana = sorted_dev[n // 2]

    # Por método
    metodos: dict = {}
    for r in rows:
        m = r['metodo_estimacion']
        if m not in metodos:
            metodos[m] = []
        metodos[m].append(r['desviacion_porcentual_real'])

    por_metodo = sorted([
        {
            'metodo': m,
            'n': len(v),
            'error_medio_pct': round(sum(v) / len(v), 2),
            'error_min_pct': round(min(v), 2),
            'error_max_pct': round(max(v), 2),
        }
        for m, v in metodos.items()
    ], key=lambda x: x['error_medio_pct'])

    # Por sede
    sedes_d: dict = {}
    for r in rows:
        key = f"{r['pais']}|{r['sede']}"
        if key not in sedes_d:
            sedes_d[key] = {'pais': r['pais'], 'sede': r['sede'], 'vals': []}
        sedes_d[key]['vals'].append(r['desviacion_porcentual_real'])

    por_sede = sorted([
        {
            'pais': v['pais'],
            'sede': v['sede'],
            'n': len(v['vals']),
            'error_medio_pct': round(sum(v['vals']) / len(v['vals']), 2),
        }
        for v in sedes_d.values()
    ], key=lambda x: x['error_medio_pct'], reverse=True)

    return {
        'n_validadas': len(rows),
        'error_medio_pct': error_medio,
        'error_mediano_pct': round(mediana, 2),
        'por_metodo': por_metodo,
        'por_sede': por_sede[:20],  # top 20 sedes con peor precisión
    }


def comparativa_real_vs_estimado(pais: str = None, sede: str = None,
                                  anio: str = None) -> list[dict]:
    """
    Devuelve el detalle de cada estimación sustituida con su valor real y error.
    Útil para el gráfico 'Real vs Estimado' del dashboard.
    """
    cond, params = ["e.estado='sustituida'"], []
    if pais:
        cond.append("e.pais=?"); params.append(pais.upper())
    if sede:
        cond.append("e.sede=?"); params.append(sede)
    if anio:
        cond.append("substr(e.mes,1,4)=?"); params.append(str(anio))

    where = "WHERE " + " AND ".join(cond)
    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT e.pais, e.sede, e.mes, e.metodo_estimacion,
                       e.emisiones_estimadas, e.confianza, e.confianza_texto,
                       e.desviacion_porcentual_real, e.error_absoluto,
                       f.emisiones_tco2e as emisiones_reales,
                       f.archivo_nombre
                FROM estimaciones e
                LEFT JOIN facturas f ON f.id = e.factura_real_id
                {where}
                ORDER BY e.pais, e.sede, e.mes''',
            params
        ).fetchall()
    return [dict(r) for r in rows]


# ── Fase 6: Reconciliación automática y métricas por método ──────────────────

def metricas_precision_por_metodo() -> list[dict]:
    """
    Devuelve las métricas de precisión acumuladas por método de estimación.
    Se actualiza automáticamente con cada reconciliación estimado → real.

    Returns para cada método:
      metodo, n_sustituciones, mae_kwh (error medio absoluto),
      mape_pct (error porcentual medio), max_error_abs, max_error_rel
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT metodo, n_sustituciones, suma_error_abs, suma_error_rel,
                      max_error_abs, max_error_rel, ultima_actualizacion
               FROM metodo_estimacion_metricas
               ORDER BY metodo"""
        ).fetchall()

    resultado = []
    for r in rows:
        n = r['n_sustituciones'] or 0
        mae  = round(r['suma_error_abs'] / n, 2) if n > 0 else None
        mape = round(r['suma_error_rel'] / n, 2) if n > 0 else None
        resultado.append({
            'metodo': r['metodo'],
            'n_sustituciones': n,
            'mae_kwh': mae,
            'mape_pct': mape,
            'max_error_abs_kwh': round(r['max_error_abs'] or 0, 2),
            'max_error_rel_pct': round(r['max_error_rel'] or 0, 2),
            'ultima_actualizacion': r['ultima_actualizacion'],
            'calidad': _calidad_metodo(mape),
        })

    # Ordenar por precisión (menor MAPE = mejor)
    resultado.sort(key=lambda x: (x['mape_pct'] or 999))
    return resultado


def reconciliar_automatico(pais: str, sede: str, mes: str,
                            factura_real_id: int,
                            tipo_energia: str = 'electricidad') -> dict:
    """
    Reconciliación automática: detecta estimaciones vigentes para el mismo
    período y sede, las sustituye por la factura real y actualiza las métricas.

    Llamar desde lote_service después de guardar cada factura nueva.

    Returns:
      reconciliadas: número de estimaciones sustituidas
      detalle: lista de estimaciones procesadas
    """
    pais = pais.upper()

    with get_db_connection() as conn:
        # Buscar estimaciones vigentes para esta sede y período
        estimaciones = conn.execute(
            """SELECT id FROM estimaciones
               WHERE pais=? AND sede=? AND tipo_energia=?
                 AND mes=? AND estado='vigente'""",
            (pais, sede, tipo_energia, mes[:7])  # YYYY-MM
        ).fetchall()

    reconciliadas = 0
    detalle = []
    for est_row in estimaciones:
        try:
            result = sustituir_por_real(est_row['id'], factura_real_id)
            reconciliadas += 1
            detalle.append({
                'estimacion_id': est_row['id'],
                'estado': 'reconciliada',
                'error_relativo_pct': result.get('error_relativo_pct'),
            })
        except Exception as exc:
            detalle.append({
                'estimacion_id': est_row['id'],
                'estado': 'error',
                'motivo': str(exc),
            })

    return {
        'reconciliadas': reconciliadas,
        'detalle': detalle,
    }


def _calidad_metodo(mape: float | None) -> str:
    """Clasifica la calidad de un método por su MAPE."""
    if mape is None:
        return 'sin_datos'
    if mape <= 5:
        return 'excelente'
    if mape <= 10:
        return 'bueno'
    if mape <= 20:
        return 'aceptable'
    return 'mejorable'
