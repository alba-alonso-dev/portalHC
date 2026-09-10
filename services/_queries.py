"""
Helpers de consultas SQL compartidos entre servicios.

Centraliza patrones repetidos (p. ej. el filtro de facturas activas por año)
que antes se duplicaban en dashboard_service (~30 veces) y ghg_report_service.

Fase 1 — Refactor de bajo riesgo.
"""

from typing import Optional


def filtro_facturas(
    anio: str,
    pais: Optional[str] = None,
    sede: Optional[str] = None,
    tipo_energia: Optional[str] = None,
    alias: str = "",
) -> tuple[str, list]:
    """
    Genera la cláusula WHERE para filtrar facturas activas por año.

    Incluye:
      - fecha_anulacion IS NULL  (facturas no anuladas)
      - strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = anio
      - Filtros opcionales por pais (uppercase), sede y tipo_energia

    Args:
        anio: Año a filtrar (obligatorio).
        pais: Código de país ISO (se normaliza a mayúsculas).
        sede: Nombre de sede (exacto).
        tipo_energia: Tipo de energía ('electricidad', 'gas', ...).
        alias: Prefijo de tabla para JOINs (p. ej. 'f' → 'f.pais').
               Cadena vacía = sin alias.

    Returns:
        (where_clause, params) — lista de condiciones unidas con AND,
        y lista de parámetros positional para sqlite3.

    Uso:
        where, params = filtro_facturas(anio, pais, sede)
        sql = f"SELECT ... FROM facturas WHERE {where}"
        conn.execute(sql, params)

    Para añadir condiciones extra:
        where += " AND estado = 'confirmada'"
    """
    a = f"{alias}." if alias else ""
    cond = [
        f"{a}fecha_anulacion IS NULL",
        f"strftime('%Y', COALESCE({a}periodo_inicio, {a}fecha_carga)) = ?",
    ]
    params: list = [anio]
    if pais:
        cond.append(f"{a}pais = ?")
        params.append(pais.upper())
    if sede:
        cond.append(f"{a}sede = ?")
        params.append(sede)
    if tipo_energia:
        cond.append(f"{a}tipo_energia = ?")
        params.append(tipo_energia)
    return " AND ".join(cond), params
