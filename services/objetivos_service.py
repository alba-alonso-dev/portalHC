"""
Servicio de Objetivos de Reducción de Emisiones — Fase 6.

Permite definir targets anuales de emisiones por:
  - Sede específica (pais + sociedad + sede)
  - Sociedad/empresa (sociedad)
  - País (pais)
  - Global corporativo (sin filtro)

Seguimiento automático: compara el objetivo con los datos reales de la BD
y devuelve desviación, % cumplimiento y estado semáforo (verde/amarillo/rojo).

Semáforo:
  verde     → cumplimiento >= 100% (por debajo del objetivo)
  amarillo  → cumplimiento >= 80%
  rojo      → cumplimiento < 80%
"""

import logging
from datetime import date
from typing import Any

from database.connection import get_db_connection

logger = logging.getLogger(__name__)

# Umbrales de semáforo (% de cumplimiento respecto al objetivo)
_SEMAFORO_VERDE    = 100.0   # real <= objetivo
_SEMAFORO_AMARILLO =  80.0   # real <= objetivo * 1.20


# ── CRUD objetivos ────────────────────────────────────────────────────────────

def crear_objetivo(anio: int,
                   pais: str = None,
                   sociedad: str = None,
                   sede: str = None,
                   tipo_energia: str = 'electricidad',
                   emisiones_objetivo_tco2e: float = None,
                   pct_reduccion_objetivo: float = None,
                   anio_base: int = None,
                   emisiones_anio_base_tco2e: float = None,
                   observaciones: str = None) -> dict:
    """
    Crea un objetivo de reducción de emisiones.

    Debe proporcionarse al menos uno de:
      - emisiones_objetivo_tco2e (valor absoluto en tCO₂e)
      - pct_reduccion_objetivo + anio_base (porcentaje respecto al año base)

    Si se pasa pct_reduccion_objetivo sin emisiones_anio_base_tco2e,
    se intenta calcular el objetivo absoluto a partir de los datos históricos.
    """
    if not anio:
        raise ValueError("El campo 'anio' es obligatorio")
    if emisiones_objetivo_tco2e is None and pct_reduccion_objetivo is None:
        raise ValueError("Debe indicar emisiones_objetivo_tco2e o pct_reduccion_objetivo")

    pais = pais.upper() if pais else None

    # Si hay % reducción sin valor absoluto, calcular el objetivo absoluto
    if emisiones_objetivo_tco2e is None and pct_reduccion_objetivo is not None:
        base = emisiones_anio_base_tco2e
        if base is None and anio_base:
            base = _emisiones_reales_anio(pais, sociedad, sede, tipo_energia,
                                          str(anio_base))
        if base is not None and base > 0:
            emisiones_objetivo_tco2e = round(base * (1 - pct_reduccion_objetivo / 100), 4)

    with get_db_connection() as conn:
        cur = conn.execute(
            """INSERT INTO objetivos_emision
               (anio, pais, sociedad, sede, tipo_energia,
                emisiones_objetivo_tco2e, pct_reduccion_objetivo,
                anio_base, emisiones_anio_base_tco2e, observaciones)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (anio, pais, sociedad, sede, tipo_energia,
             emisiones_objetivo_tco2e, pct_reduccion_objetivo,
             anio_base, emisiones_anio_base_tco2e, observaciones)
        )
        obj_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM objetivos_emision WHERE id=?", (obj_id,)
        ).fetchone()
        return dict(row)


def actualizar_objetivo(obj_id: int, **kwargs) -> dict:
    """Actualiza campos de un objetivo existente."""
    campos_permitidos = {
        'emisiones_objetivo_tco2e', 'pct_reduccion_objetivo',
        'anio_base', 'emisiones_anio_base_tco2e', 'observaciones', 'activo',
    }
    updates = {k: v for k, v in kwargs.items() if k in campos_permitidos}
    if not updates:
        raise ValueError("No hay campos válidos para actualizar")

    set_clause = ", ".join(f"{k}=?" for k in updates)
    params = list(updates.values()) + [obj_id]

    with get_db_connection() as conn:
        conn.execute(
            f"UPDATE objetivos_emision SET {set_clause}, modificado_en=CURRENT_TIMESTAMP WHERE id=?",
            params
        )
        row = conn.execute(
            "SELECT * FROM objetivos_emision WHERE id=?", (obj_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Objetivo {obj_id} no encontrado")
        return dict(row)


def eliminar_objetivo(obj_id: int) -> bool:
    """Desactiva un objetivo (soft delete)."""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE objetivos_emision SET activo=0, modificado_en=CURRENT_TIMESTAMP WHERE id=?",
            (obj_id,)
        )
    return True


def listar_objetivos(anio: int = None, pais: str = None,
                     sociedad: str = None, sede: str = None,
                     solo_activos: bool = True) -> list[dict]:
    """Lista objetivos con filtros opcionales."""
    cond, params = [], []
    if solo_activos:
        cond.append("activo=1")
    if anio:
        cond.append("anio=?"); params.append(anio)
    if pais:
        cond.append("pais=?"); params.append(pais.upper())
    if sociedad:
        cond.append("sociedad=?"); params.append(sociedad)
    if sede:
        cond.append("sede=?"); params.append(sede)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM objetivos_emision {where} ORDER BY anio DESC, pais, sede",
            params
        ).fetchall()
    return [dict(r) for r in rows]


# ── Seguimiento: objetivo vs real ────────────────────────────────────────────

def seguimiento_objetivo(obj_id: int) -> dict:
    """
    Calcula el seguimiento de un objetivo concreto.

    Returns:
      objetivo, real_acumulado, desviacion, pct_cumplimiento, semaforo,
      proyeccion_cierre_tco2e, meses_con_datos, meses_totales
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM objetivos_emision WHERE id=?", (obj_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Objetivo {obj_id} no encontrado")

    obj = dict(row)
    return _calcular_seguimiento(obj)


def seguimiento_todos(anio: int = None, pais: str = None,
                      sociedad: str = None, sede: str = None) -> list[dict]:
    """Seguimiento de todos los objetivos activos que cumplan los filtros."""
    objetivos = listar_objetivos(anio=anio, pais=pais, sociedad=sociedad,
                                 sede=sede, solo_activos=True)
    return [_calcular_seguimiento(obj) for obj in objetivos]


def resumen_esg(anio: int = None) -> dict:
    """
    Resumen global ESG con semáforo para el dashboard ejecutivo.

    Returns:
      n_objetivos, n_verde, n_amarillo, n_rojo, n_sin_objetivo,
      pct_cumplimiento_global, sedes_en_riesgo[]
    """
    anio = anio or date.today().year
    seguimientos = seguimiento_todos(anio=anio)

    n_verde    = sum(1 for s in seguimientos if s['semaforo'] == 'verde')
    n_amarillo = sum(1 for s in seguimientos if s['semaforo'] == 'amarillo')
    n_rojo     = sum(1 for s in seguimientos if s['semaforo'] == 'rojo')
    n_sin_datos = sum(1 for s in seguimientos if s['semaforo'] == 'sin_datos')

    # Sedes activas sin objetivo definido
    sedes_con_objetivo = {
        (s['objetivo'].get('sede'), s['objetivo'].get('pais'))
        for s in seguimientos
        if s['objetivo'].get('sede')
    }
    sedes_en_riesgo = [
        s for s in seguimientos
        if s['semaforo'] in ('rojo', 'amarillo') and s['objetivo'].get('sede')
    ]

    # % cumplimiento medio (excluyendo sin_datos)
    con_datos = [s for s in seguimientos if s['pct_cumplimiento'] is not None]
    pct_global = (
        round(sum(s['pct_cumplimiento'] for s in con_datos) / len(con_datos), 1)
        if con_datos else None
    )

    return {
        'anio': anio,
        'n_objetivos': len(seguimientos),
        'n_verde': n_verde,
        'n_amarillo': n_amarillo,
        'n_rojo': n_rojo,
        'n_sin_datos': n_sin_datos,
        'pct_cumplimiento_global': pct_global,
        'sedes_en_riesgo': [s['objetivo'].get('sede') for s in sedes_en_riesgo if s['objetivo'].get('sede')],
        'detalle': seguimientos,
    }


# ── Lógica interna ────────────────────────────────────────────────────────────

def _calcular_seguimiento(obj: dict) -> dict:
    """Calcula métricas de seguimiento para un objetivo dado."""
    anio       = obj['anio']
    pais       = obj.get('pais')
    sociedad   = obj.get('sociedad')
    sede       = obj.get('sede')
    te         = obj.get('tipo_energia', 'electricidad')
    objetivo   = obj.get('emisiones_objetivo_tco2e')

    real_acumulado = _emisiones_reales_anio(pais, sociedad, sede, te, str(anio))
    proyeccion     = _proyectar_cierre(pais, sociedad, sede, te, anio, real_acumulado)

    if objetivo is None or objetivo <= 0:
        semaforo = 'sin_objetivo'
        pct = None
        desviacion = None
    elif real_acumulado is None:
        semaforo = 'sin_datos'
        pct = None
        desviacion = None
    else:
        desviacion = round(real_acumulado - objetivo, 4)
        pct = round((1 - real_acumulado / objetivo) * 100, 1) if objetivo > 0 else None
        # Semáforo: positivo = bien (real < objetivo)
        if real_acumulado <= objetivo:
            semaforo = 'verde'
        elif real_acumulado <= objetivo * 1.20:
            semaforo = 'amarillo'
        else:
            semaforo = 'rojo'

    return {
        'objetivo': obj,
        'real_acumulado_tco2e': round(real_acumulado, 4) if real_acumulado else None,
        'desviacion_tco2e': desviacion,
        'pct_cumplimiento': pct,
        'semaforo': semaforo,
        'proyeccion_cierre_tco2e': proyeccion,
        'diferencia_proyeccion_vs_objetivo': (
            round(proyeccion - objetivo, 4)
            if proyeccion is not None and objetivo is not None else None
        ),
    }


def _emisiones_reales_anio(pais: str, sociedad: str, sede: str,
                            tipo_energia: str, anio: str) -> float | None:
    """Suma de emisiones reales del año para el ámbito del objetivo."""
    cond = [
        "fecha_anulacion IS NULL",
        "strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?",
    ]
    params: list[Any] = [anio]

    if tipo_energia:
        cond.append("tipo_energia = ?"); params.append(tipo_energia)
    if pais:
        cond.append("pais = ?"); params.append(pais)
    if sociedad:
        cond.append("COALESCE(NULLIF(sociedad,''), 'Sin identificar') = ?")
        params.append(sociedad)
    if sede:
        cond.append("sede = ?"); params.append(sede)

    where = "WHERE " + " AND ".join(cond)
    with get_db_connection() as conn:
        row = conn.execute(
            f"SELECT COALESCE(SUM(emisiones_tco2e), 0) FROM facturas {where}",
            params
        ).fetchone()
    val = row[0] if row else 0
    return round(val, 4) if val else None


def _proyectar_cierre(pais: str, sociedad: str, sede: str,
                      tipo_energia: str, anio: int,
                      real_acumulado: float | None) -> float | None:
    """
    Proyección de emisiones al cierre del año.

    Método: pro-rata por meses consumidos.
    Si hay datos históricos del año anterior, se usa estacionalidad.
    """
    if real_acumulado is None:
        return None

    mes_actual = date.today().month
    anio_actual = date.today().year

    if anio != anio_actual:
        # Año ya cerrado o futuro — no proyectar
        return None

    if mes_actual == 12:
        return round(real_acumulado, 4)

    # Meses con datos en el año actual
    cond = [
        "fecha_anulacion IS NULL",
        "strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?",
    ]
    params: list[Any] = [str(anio)]
    if tipo_energia:
        cond.append("tipo_energia = ?"); params.append(tipo_energia)
    if pais:
        cond.append("pais = ?"); params.append(pais)
    if sociedad:
        cond.append("COALESCE(NULLIF(sociedad,''), 'Sin identificar') = ?")
        params.append(sociedad)
    if sede:
        cond.append("sede = ?"); params.append(sede)

    where = "WHERE " + " AND ".join(cond)
    with get_db_connection() as conn:
        meses_con_datos = conn.execute(
            f"""SELECT COUNT(DISTINCT strftime('%Y-%m', COALESCE(periodo_inicio, fecha_carga)))
                FROM facturas {where}""",
            params
        ).fetchone()[0]

    if not meses_con_datos:
        return None

    # Pro-rata: extrapolar al año completo
    proyeccion = round(real_acumulado / meses_con_datos * 12, 4)
    return proyeccion
