"""
Motor de recálculo de emisiones — Fase 3.

Principios de diseño:
  - INMUTABILIDAD: los valores originales (factor_emision, emisiones_tco2e) nunca
    se sobrescriben. Los recálculos se almacenan en columnas separadas y en el
    historial recalculos_historial.
  - TRAZABILIDAD: cada recálculo registra factor original, factor nuevo, versión,
    diferencia absoluta y porcentual, usuario y motivo.
  - ALCANCES: individual / sede / país / año / completo.
  - ANÁLISIS PREVIO: siempre se puede pedir un análisis de impacto antes de ejecutar.
"""

import json
import logging
import uuid
from datetime import datetime

from database.connection import get_db_connection
from services.emisiones_service import obtener_factor
from services.numeros import calcular_tco2e, tco2e, porcentaje
from services.audit_service import registrar_evento, ACCION_RECALCULO_EJECUTADO

logger = logging.getLogger(__name__)


# ── Análisis de impacto (previsualización, sin modificar BD) ──────────────────

def analizar_impacto(alcance: str, filtro_pais: str = None,
                     filtro_sede: str = None, filtro_anio: str = None,
                     filtro_factura_id: int = None) -> dict:
    """
    Calcula el impacto esperado de un recálculo SIN ejecutarlo.

    Returns un dict con:
      facturas_afectadas, paises_afectados, sedes_afectadas,
      total_emisiones_original, total_emisiones_nueva, diferencia, porcentaje_variacion,
      desglose (lista por país/año con before/after)
    """
    facturas = _obtener_facturas_para_recalculo(
        alcance, filtro_pais, filtro_sede, filtro_anio, filtro_factura_id
    )

    if not facturas:
        return {
            'facturas_afectadas': 0, 'paises_afectados': 0, 'sedes_afectadas': 0,
            'total_emisiones_original': 0.0, 'total_emisiones_nueva': 0.0,
            'diferencia': 0.0, 'porcentaje_variacion': 0.0,
            'desglose': [], 'advertencias': []
        }

    total_orig, total_nueva = 0.0, 0.0
    paises, sedes, advertencias = set(), set(), []
    desglose = {}

    for f in facturas:
        pais   = f['pais']
        anio   = _anio_factura(f)
        consumo = f['consumo_mwh'] or 0.0

        factor_nuevo, _, _, _ = obtener_factor(pais, anio)
        if factor_nuevo is None:
            advertencias.append(
                f"Sin factor disponible para {pais}/{anio} (factura #{f['id']})"
            )
            factor_nuevo = f['factor_emision'] or 0.0

        emis_orig  = f['emisiones_tco2e'] or 0.0
        emis_nueva = calcular_tco2e(consumo, factor_nuevo) or 0.0

        total_orig  += emis_orig
        total_nueva += emis_nueva
        paises.add(pais)
        sedes.add(f"{pais}/{f['sede']}")

        clave = f"{pais}/{anio}"
        if clave not in desglose:
            desglose[clave] = {'pais': pais, 'anio': anio,
                               'facturas': 0, 'original': 0.0, 'nueva': 0.0}
        desglose[clave]['facturas'] += 1
        desglose[clave]['original'] += emis_orig
        desglose[clave]['nueva']    += emis_nueva

    diferencia = round(total_nueva - total_orig, 4)
    variacion  = round((diferencia / total_orig * 100) if total_orig else 0.0, 2)

    for v in desglose.values():
        v['diferencia']  = round(v['nueva'] - v['original'], 4)
        v['original']    = round(v['original'], 4)
        v['nueva']       = round(v['nueva'], 4)

    return {
        'facturas_afectadas':       len(facturas),
        'paises_afectados':         len(paises),
        'sedes_afectadas':          len(sedes),
        'total_emisiones_original': round(total_orig, 4),
        'total_emisiones_nueva':    round(total_nueva, 4),
        'diferencia':               diferencia,
        'porcentaje_variacion':     variacion,
        'desglose':                 list(desglose.values()),
        'advertencias':             advertencias,
    }


# ── Ejecución del recálculo ───────────────────────────────────────────────────

def ejecutar_recalculo(alcance: str, usuario: str = 'usuario', motivo: str = '',
                       filtro_pais: str = None, filtro_sede: str = None,
                       filtro_anio: str = None, filtro_factura_id: int = None) -> str:
    """
    Lanza el recálculo para el alcance indicado.
    Devuelve el lote_recalculo_id para seguimiento.
    El procesamiento es SÍNCRONO (volúmenes típicos < 10 000 facturas).
    """
    lote_id = str(uuid.uuid4())
    facturas = _obtener_facturas_para_recalculo(
        alcance, filtro_pais, filtro_sede, filtro_anio, filtro_factura_id
    )

    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO lotes_recalculo
                (id, alcance, filtro_pais, filtro_sede, filtro_anio,
                 filtro_factura_id, total_facturas, estado, usuario, motivo)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', (lote_id, alcance, filtro_pais, filtro_sede, filtro_anio,
              filtro_factura_id, len(facturas), 'procesando', usuario, motivo))

    ok = err = 0
    total_orig = total_nueva = 0.0

    for f in facturas:
        try:
            res = _recalcular_una(f, lote_id, usuario, motivo)
            total_orig  += res['emisiones_originales'] or 0.0
            total_nueva += res['emisiones_recalculadas'] or 0.0
            ok += 1
        except Exception as exc:
            logger.error(f"[RECALC] Error factura #{f['id']}: {exc}")
            err += 1

    resumen = {
        'total_emisiones_original':  round(total_orig, 4),
        'total_emisiones_nueva':     round(total_nueva, 4),
        'diferencia':                round(total_nueva - total_orig, 4),
        'porcentaje_variacion':      round(
            (total_nueva - total_orig) / total_orig * 100 if total_orig else 0, 2
        ),
    }

    with get_db_connection() as conn:
        conn.execute('''
            UPDATE lotes_recalculo
            SET estado=?, procesadas_ok=?, procesadas_error=?,
                resumen_json=?, fecha_fin=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (
            'completado' if err == 0 else 'completado_con_errores',
            ok, err, json.dumps(resumen, ensure_ascii=False), lote_id
        ))

    logger.info(
        f"[RECALC] Lote {lote_id[:8]} — {ok} OK / {err} errores  "
        f"Δ {resumen['diferencia']:+.4f} tCO₂e ({resumen['porcentaje_variacion']:+.2f}%)"
    )

    registrar_evento(
        accion=ACCION_RECALCULO_EJECUTADO,
        usuario=usuario,
        entidad='lote_recalculo',
        entidad_id=None,
        detalle={
            'lote_id': lote_id,
            'alcance': alcance,
            'motivo': motivo,
            'ok': ok,
            'errores': err,
            **resumen,
        },
    )
    return lote_id


def _recalcular_una(f: dict, lote_id: str, usuario: str, motivo: str) -> dict:
    """Recalcula una sola factura, persiste historial y actualiza columnas recalc."""
    pais    = f['pais']
    anio    = _anio_factura(f)
    consumo = f['consumo_mwh'] or 0.0

    factor_nuevo, fuente_nueva, _, factor_version_id_nuevo = obtener_factor(pais, anio)
    if factor_nuevo is None:
        raise ValueError(f"Sin factor para {pais}/{anio}")

    emis_orig   = f['emisiones_tco2e'] or 0.0
    emis_nueva  = calcular_tco2e(consumo, factor_nuevo) or 0.0
    dif_abs     = tco2e(emis_nueva - emis_orig)
    dif_pct     = porcentaje((dif_abs / emis_orig * 100) if emis_orig else 0.0)

    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO recalculos_historial
                (factura_id, lote_recalculo_id,
                 emisiones_originales, factor_original, factor_version_id_original, fuente_original,
                 emisiones_recalculadas, factor_nuevo, factor_version_id_nuevo, fuente_nueva,
                 diferencia_absoluta, diferencia_porcentual, usuario, motivo)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            f['id'], lote_id,
            emis_orig, f['factor_emision'], f.get('factor_version_id'), None,
            emis_nueva, factor_nuevo, factor_version_id_nuevo, fuente_nueva,
            dif_abs, dif_pct, usuario, motivo
        ))

        conn.execute('''
            UPDATE facturas
            SET emisiones_recalculadas=?, factor_recalculado=?,
                factor_version_id_recalc=?, fecha_ultimo_recalculo=CURRENT_TIMESTAMP
            WHERE id=?
        ''', (emis_nueva, factor_nuevo, factor_version_id_nuevo, f['id']))

    return {
        'factura_id':            f['id'],
        'emisiones_originales':  emis_orig,
        'emisiones_recalculadas': emis_nueva,
        'diferencia_absoluta':   dif_abs,
        'diferencia_porcentual': dif_pct,
    }


# ── Historial de recálculos ───────────────────────────────────────────────────

def obtener_historial_recalculos(factura_id: int) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT rh.*,
                   fe_orig.pais AS _pais_orig, fe_orig.version AS version_original,
                   fe_nuevo.version AS version_nueva
            FROM recalculos_historial rh
            LEFT JOIN factores_emision fe_orig ON fe_orig.id = rh.factor_version_id_original
            LEFT JOIN factores_emision fe_nuevo ON fe_nuevo.id = rh.factor_version_id_nuevo
            WHERE rh.factura_id = ?
            ORDER BY rh.fecha_recalculo DESC
        ''', (factura_id,)).fetchall()
    return [dict(r) for r in rows]


def obtener_lote_recalculo(lote_id: str) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM lotes_recalculo WHERE id=?", (lote_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d['resumen'] = json.loads(d.get('resumen_json') or '{}')
    except Exception:
        d['resumen'] = {}
    return d


def listar_lotes_recalculo(limit: int = 20) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT id, alcance, filtro_pais, filtro_sede, filtro_anio,
                   total_facturas, procesadas_ok, procesadas_error,
                   estado, usuario, motivo, fecha_inicio, fecha_fin, resumen_json
            FROM lotes_recalculo
            ORDER BY fecha_inicio DESC LIMIT ?
        ''', (limit,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['resumen'] = json.loads(d.get('resumen_json') or '{}')
        except Exception:
            d['resumen'] = {}
        result.append(d)
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _obtener_facturas_para_recalculo(alcance: str,
                                     filtro_pais: str = None,
                                     filtro_sede: str = None,
                                     filtro_anio: str = None,
                                     filtro_factura_id: int = None) -> list[dict]:
    """Devuelve las facturas que corresponden al alcance solicitado."""
    # Prefijo f. obligatorio: el LEFT JOIN con factores_emision comparte columnas
    # pais, id y fecha_carga, por lo que sin alias SQLite devuelve "ambiguous column".
    cond, params = ["f.tipo_dato = 'real'"], []

    if alcance == 'individual' and filtro_factura_id:
        cond.append("f.id = ?");  params.append(filtro_factura_id)
    elif alcance == 'sede':
        if filtro_pais: cond.append("f.pais = ?");  params.append(filtro_pais.upper())
        if filtro_sede: cond.append("f.sede = ?");  params.append(filtro_sede)
    elif alcance == 'pais':
        if filtro_pais: cond.append("f.pais = ?");  params.append(filtro_pais.upper())
    elif alcance == 'anio':
        if filtro_pais: cond.append("f.pais = ?");  params.append(filtro_pais.upper())
        if filtro_anio:
            cond.append(
                "(strftime('%Y', f.periodo_inicio) = ? OR strftime('%Y', f.fecha_carga) = ?)"
            )
            params += [filtro_anio, filtro_anio]
    # 'completo': sin filtros adicionales

    where = "WHERE " + " AND ".join(cond)
    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT f.id, f.pais, f.sede, f.consumo_mwh, f.emisiones_tco2e,
                       f.factor_emision, f.factor_version_id,
                       f.periodo_inicio, f.fecha_carga
                FROM facturas f
                {where}
                ORDER BY f.fecha_carga''',
            params
        ).fetchall()
    return [dict(r) for r in rows]


def _anio_factura(f: dict) -> str:
    if f.get('periodo_inicio') and len(str(f['periodo_inicio'])) >= 4:
        return str(f['periodo_inicio'])[:4]
    if f.get('fecha_carga') and len(str(f['fecha_carga'])) >= 4:
        return str(f['fecha_carga'])[:4]
    return str(datetime.now().year)
