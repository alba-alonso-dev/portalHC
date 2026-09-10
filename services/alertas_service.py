"""
Servicio de Alertas Automáticas — Fase 4.

Genera, lista y gestiona alertas sobre:
  - Cobertura: facturas faltantes del mes anterior.
  - Calidad: OCR bajo, consumos anómalos, duplicados.
  - Emisiones: factores no actualizados, recálculos pendientes.
  - Documentación: documentos no encontrados.

Uso:
    from services.alertas_service import generar_alertas_automaticas, listar_alertas
    generar_alertas_automaticas()  # ejecutar periódicamente o al cargar el dashboard
"""

import json
import logging
from datetime import date, datetime
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


# ── Generación automática de alertas ─────────────────────────────────────────

def generar_alertas_automaticas() -> dict:
    """
    Analiza el estado actual del sistema y genera alertas donde proceda.
    Evita duplicados: no crea una alerta si ya existe una pendiente del mismo
    tipo/subtipo/entidad_id.

    Returns estadísticas de alertas generadas.
    """
    generadas = 0
    generadas += _alertas_cobertura_mes_anterior()
    generadas += _alertas_ocr_bajo()
    generadas += _alertas_consumo_anomalo()
    generadas += _alertas_duplicados()
    generadas += _alertas_factores_no_actualizados()
    generadas += _alertas_factores_version_antigua()   # Fase 5
    generadas += _alertas_documentos_no_encontrados()
    generadas += _alertas_recalculo_pendiente()
    # Fase 6: detección avanzada de anomalías
    generadas += _alertas_consumo_zscore()
    generadas += _alertas_cambio_interanual_brusco()
    generadas += _alertas_periodo_anomalo()
    generadas += _alertas_ocr_incoherente()

    logger.info(f"Alertas automáticas: {generadas} nuevas alertas generadas")
    return {'generadas': generadas}


# ── Cobertura: factura del mes anterior faltante ──────────────────────────────

def _alertas_cobertura_mes_anterior() -> int:
    """
    Para cada sede activa, verifica que existe al menos una factura real
    o estimación vigente del mes anterior al día de hoy.
    """
    hoy = date.today()
    mes_ant_mes = hoy.month - 1 if hoy.month > 1 else 12
    mes_ant_anio = hoy.year if hoy.month > 1 else hoy.year - 1
    mes_ant = f"{mes_ant_anio:04d}-{mes_ant_mes:02d}"

    n = 0
    with get_db_connection() as conn:
        # Obtener configuración de alerta
        cfg = _get_config(conn, 'cobertura', 'factura_mes_anterior')
        if not cfg or not cfg['activa']:
            return 0

        sedes = conn.execute(
            '''SELECT DISTINCT pais, sede, tipo_energia FROM facturas
               WHERE fecha_anulacion IS NULL'''
        ).fetchall()

        for row in sedes:
            p, s, te = row['pais'], row['sede'], row['tipo_energia']

            # ¿Tiene datos del mes anterior?
            tiene_real = conn.execute(
                '''SELECT COUNT(*) FROM facturas
                   WHERE pais=? AND sede=? AND tipo_energia=?
                     AND fecha_anulacion IS NULL AND tipo_dato='real'
                     AND substr(COALESCE(periodo_inicio,''),1,7) = ?''',
                (p, s, te, mes_ant)
            ).fetchone()[0]

            tiene_est = conn.execute(
                '''SELECT COUNT(*) FROM estimaciones
                   WHERE pais=? AND sede=? AND tipo_energia=?
                     AND estado='vigente' AND mes=?''',
                (p, s, te, mes_ant)
            ).fetchone()[0]

            if tiene_real or tiene_est:
                continue

            # Verificar si ya hay alerta pendiente
            if _existe_alerta_pendiente(conn, 'cobertura', 'factura_mes_anterior',
                                         pais=p, sede=s, mes=mes_ant):
                continue

            _insertar_alerta(conn, {
                'tipo': 'cobertura',
                'subtipo': 'factura_mes_anterior',
                'severidad': cfg['severidad'],
                'titulo': f"Falta factura de {mes_ant} — {s} ({p})",
                'descripcion': (
                    f"La sede {s} ({p}) no tiene factura real ni estimación "
                    f"para {mes_ant} ({te})."
                ),
                'entidad': 'sede',
                'pais': p,
                'sede': s,
                'mes': mes_ant,
                'datos_json': json.dumps({'tipo_energia': te}),
            })
            n += 1
    return n


# ── Calidad: OCR bajo ─────────────────────────────────────────────────────────

def _alertas_ocr_bajo() -> int:
    """Genera alertas para facturas con confianza OCR < umbral (defecto 0.60)."""
    n = 0
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'calidad', 'ocr_bajo')
        if not cfg or not cfg['activa']:
            return 0
        umbral = cfg['umbral_valor'] or 0.60

        facturas = conn.execute(
            '''SELECT id, pais, sede, archivo_nombre, confianza_ocr
               FROM facturas
               WHERE fecha_anulacion IS NULL
                 AND confianza_ocr IS NOT NULL AND confianza_ocr < ?''',
            (umbral,)
        ).fetchall()

        for f in facturas:
            if _existe_alerta_pendiente(conn, 'calidad', 'ocr_bajo',
                                         entidad='factura', entidad_id=f['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'calidad',
                'subtipo': 'ocr_bajo',
                'severidad': cfg['severidad'],
                'titulo': f"OCR bajo en {f['archivo_nombre']} ({round(f['confianza_ocr'],2)})",
                'descripcion': (
                    f"La factura {f['archivo_nombre']} tiene confianza OCR de "
                    f"{round(f['confianza_ocr'],2)} (umbral: {umbral}). "
                    "Revisar manualmente los datos extraídos."
                ),
                'entidad': 'factura',
                'entidad_id': f['id'],
                'pais': f['pais'],
                'sede': f['sede'],
                'datos_json': json.dumps({'confianza_ocr': f['confianza_ocr'],
                                          'umbral': umbral}),
            })
            n += 1
    return n


# ── Calidad: consumo anómalo ──────────────────────────────────────────────────

def _alertas_consumo_anomalo() -> int:
    """Genera alertas para facturas con consumo > umbral% sobre la media de la sede."""
    n = 0
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'calidad', 'consumo_anomalo')
        if not cfg or not cfg['activa']:
            return 0
        pct_umbral = (cfg['umbral_valor'] or 200.0) / 100.0  # 200% → 3x la media

        # El histórico de referencia se acota al mismo punto de suministro
        # (`f2.cups IS f.cups`, comparación NULL-safe en SQLite). Una sede puede
        # tener varios CUPS con consumos de órdenes muy distintos; promediarlos
        # juntos hacía que el CUPS grande superase siempre la media mezclada y
        # generase una alerta de "consumo anómalo" todos los meses.
        rows = conn.execute(
            '''SELECT f.id, f.pais, f.sede, f.tipo_energia, f.archivo_nombre,
                      f.cups, f.consumo_mwh,
                      AVG(f2.consumo_mwh) as media_ref,
                      COUNT(f2.id)        as n_ref
               FROM facturas f
               JOIN facturas f2 ON f2.pais=f.pais AND f2.sede=f.sede
                 AND f2.tipo_energia=f.tipo_energia
                 AND f2.cups IS f.cups
                 AND f2.fecha_anulacion IS NULL AND f2.consumo_mwh > 0
               WHERE f.fecha_anulacion IS NULL AND f.consumo_mwh > 0
               GROUP BY f.id
               HAVING COUNT(f2.id) >= 3
                  AND f.consumo_mwh > AVG(f2.consumo_mwh) * ?''',
            (1 + pct_umbral,)
        ).fetchall()

        for r in rows:
            if _existe_alerta_pendiente(conn, 'calidad', 'consumo_anomalo',
                                         entidad='factura', entidad_id=r['id']):
                continue
            media = round(r['media_ref'] or 0, 2)
            desv = round((r['consumo_mwh'] - media) / media * 100, 1) if media else 0
            ambito = f"el CUPS {r['cups']}" if r['cups'] else f"la sede {r['sede']}"
            _insertar_alerta(conn, {
                'tipo': 'calidad',
                'subtipo': 'consumo_anomalo',
                'severidad': cfg['severidad'],
                'titulo': f"Consumo anómalo en {r['archivo_nombre']} (+{desv}%)",
                'descripcion': (
                    f"Consumo {r['consumo_mwh']} MWh supera en {desv}% la media "
                    f"histórica de {ambito} en {r['sede']} ({r['pais']}) "
                    f"de {media} MWh (n={r['n_ref']} facturas)."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'datos_json': json.dumps({'consumo_mwh': r['consumo_mwh'],
                                          'cups': r['cups'],
                                          'media_cups': media,
                                          'n_referencias': r['n_ref'],
                                          'desviacion_pct': desv}),
            })
            n += 1
    return n


# ── Calidad: duplicados ───────────────────────────────────────────────────────

def _alertas_duplicados() -> int:
    """Genera alertas para facturas marcadas como duplicado potencial."""
    n = 0
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'calidad', 'duplicado_potencial')
        if not cfg or not cfg['activa']:
            return 0

        rows = conn.execute(
            '''SELECT id, pais, sede, archivo_nombre FROM facturas
               WHERE fecha_anulacion IS NULL AND duplicado_potencial=1'''
        ).fetchall()

        for r in rows:
            if _existe_alerta_pendiente(conn, 'calidad', 'duplicado_potencial',
                                         entidad='factura', entidad_id=r['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'calidad',
                'subtipo': 'duplicado_potencial',
                'severidad': cfg['severidad'],
                'titulo': f"Posible duplicado: {r['archivo_nombre']}",
                'descripcion': (
                    f"La factura {r['archivo_nombre']} ha sido marcada como "
                    "posible duplicado. Revisar y anular si procede."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
            })
            n += 1
    return n


# ── Emisiones: factores no actualizados ──────────────────────────────────────

def _alertas_factores_no_actualizados() -> int:
    """Detecta países donde el factor del año actual no existe en BD."""
    n = 0
    anio_actual = str(date.today().year)
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'emisiones', 'factor_no_actualizado')
        if not cfg or not cfg['activa']:
            return 0

        # Países con facturas este año
        paises = conn.execute(
            '''SELECT DISTINCT pais FROM facturas
               WHERE fecha_anulacion IS NULL
                 AND strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?''',
            (anio_actual,)
        ).fetchall()

        for row in paises:
            p = row['pais']
            tiene_factor = conn.execute(
                '''SELECT COUNT(*) FROM factores_emision
                   WHERE pais=? AND anio=? AND activo=1''',
                (p, anio_actual)
            ).fetchone()[0]
            if tiene_factor:
                continue
            if _existe_alerta_pendiente(conn, 'emisiones', 'factor_no_actualizado',
                                         pais=p, mes=anio_actual):
                continue
            _insertar_alerta(conn, {
                'tipo': 'emisiones',
                'subtipo': 'factor_no_actualizado',
                'severidad': cfg['severidad'],
                'titulo': f"Factor {anio_actual} no disponible para {p}",
                'descripcion': (
                    f"No existe factor de emisión para {p} en el año {anio_actual}. "
                    "Las emisiones se calculan con el factor más reciente disponible."
                ),
                'entidad': 'factor',
                'pais': p,
                'mes': anio_actual,
            })
            n += 1
    return n


# ── Documentación: documentos no encontrados ─────────────────────────────────

def _alertas_documentos_no_encontrados() -> int:
    """Detecta facturas sin documento PDF asociado."""
    import os
    n = 0
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'documentacion', 'documento_no_encontrado')
        if not cfg or not cfg['activa']:
            return 0

        rows = conn.execute(
            '''SELECT id, pais, sede, archivo_nombre, archivo_ruta FROM facturas
               WHERE fecha_anulacion IS NULL
                 AND archivo_ruta IS NOT NULL AND archivo_ruta <> ''
            '''
        ).fetchall()

        for r in rows:
            ruta = r['archivo_ruta']
            if os.path.exists(ruta):
                continue
            if _existe_alerta_pendiente(conn, 'documentacion', 'documento_no_encontrado',
                                         entidad='factura', entidad_id=r['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'documentacion',
                'subtipo': 'documento_no_encontrado',
                'severidad': cfg['severidad'],
                'titulo': f"Documento no encontrado: {r['archivo_nombre']}",
                'descripcion': (
                    f"El fichero PDF {r['archivo_nombre']} no existe en la ruta "
                    f"registrada: {ruta}."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'datos_json': json.dumps({'ruta': ruta}),
            })
            n += 1
    return n



# ── Emisiones: recálculo pendiente ───────────────────────────────────────────

def _alertas_recalculo_pendiente() -> int:
    """
    Detecta facturas cuyo factor_version_id no coincide con el factor activo
    más reciente disponible para su país/tipo_energía/año.
    Estas facturas necesitan ser recalculadas con el factor actualizado.
    """
    n = 0
    with get_db_connection() as conn:
        cfg = _get_config(conn, 'emisiones', 'recalculo_pendiente')
        if not cfg or not cfg['activa']:
            return 0

        try:
            rows = conn.execute(
                '''SELECT f.id, f.pais, f.sede, f.archivo_nombre,
                          f.factor_version_id,
                          fe_actual.id as factor_actual_id,
                          fe_actual.anio as factor_anio
                   FROM facturas f
                   JOIN factores_emision fe_actual
                     ON fe_actual.pais = f.pais
                    AND fe_actual.tipo_energia = f.tipo_energia
                    AND fe_actual.activo = 1
                    AND fe_actual.anio = strftime('%Y',
                        COALESCE(f.periodo_inicio, f.fecha_carga))
                   WHERE f.fecha_anulacion IS NULL
                     AND f.factor_version_id IS NOT NULL
                     AND f.factor_version_id != fe_actual.id'''
            ).fetchall()
        except Exception:
            return 0

        for r in rows:
            if _existe_alerta_pendiente(conn, 'emisiones', 'recalculo_pendiente',
                                         entidad='factura', entidad_id=r['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'emisiones',
                'subtipo': 'recalculo_pendiente',
                'severidad': cfg['severidad'],
                'titulo': f"Recálculo pendiente: {r['archivo_nombre']}",
                'descripcion': (
                    f"La factura {r['archivo_nombre']} ({r['sede']}, {r['pais']}) "
                    f"usa el factor #{r['factor_version_id']} pero existe un factor "
                    f"activo más reciente (#{r['factor_actual_id']}, año {r['factor_anio']}). "
                    "Ejecutar recálculo para actualizar las emisiones."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'datos_json': json.dumps({
                    'factor_version_id_actual': r['factor_version_id'],
                    'factor_version_id_nuevo': r['factor_actual_id'],
                }),
            })
            n += 1
    return n


def _alertas_factores_version_antigua() -> int:
    """
    Fase 5: detecta factores de emisión cuya versión activa tiene más de 12 meses
    sin actualizar (fecha_carga o modificado_en > 1 año atrás).

    Genera una alerta 'informativa' para recordar revisar las fuentes oficiales.
    """
    n = 0
    with get_db_connection() as conn:
        try:
            rows = conn.execute(
                """SELECT id, pais, tipo_energia, anio,
                          factor_kg_co2_mwh, fuente,
                          COALESCE(modificado_en, fecha_carga) AS ultima_actualizacion
                   FROM factores_emision
                   WHERE activo=1 AND es_version_activa=1
                     AND (
                       julianday('now') - julianday(COALESCE(modificado_en, fecha_carga))
                     ) > 365
                   ORDER BY pais, anio"""
            ).fetchall()
        except Exception:
            return 0

        for r in rows:
            if _existe_alerta_pendiente(conn, 'emisiones', 'factor_version_antigua',
                                         entidad='factor', entidad_id=r['id']):
                continue
            dias_sin_actualizar = None
            try:
                from datetime import datetime as _dt
                ua = r['ultima_actualizacion']
                if ua:
                    dias_sin_actualizar = (
                        _dt.now() - _dt.fromisoformat(ua[:19])
                    ).days
            except Exception:
                pass

            _insertar_alerta(conn, {
                'tipo': 'emisiones',
                'subtipo': 'factor_version_antigua',
                'severidad': 'informativa',
                'titulo': f"Factor {r['pais']}/{r['anio']} sin actualizar ({dias_sin_actualizar or '?'} días)",
                'descripcion': (
                    f"El factor de emisión de {r['pais']} para el año {r['anio']} "
                    f"(tipo: {r['tipo_energia']}, valor: {r['factor_kg_co2_mwh']} kgCO2/MWh, "
                    f"fuente: {r['fuente'] or 'sin fuente'}) "
                    f"lleva más de 12 meses sin actualizar. "
                    "Revisar si existe una versión más reciente en la fuente oficial."
                ),
                'entidad': 'factor',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'datos_json': json.dumps({
                    'factor_id': r['id'],
                    'anio': r['anio'],
                    'valor_actual': r['factor_kg_co2_mwh'],
                    'fuente': r['fuente'],
                    'dias_sin_actualizar': dias_sin_actualizar,
                }),
            })
            n += 1
    return n


def estado_factores_emision() -> list[dict]:
    """
    Fase 5: devuelve el estado de todos los factores de emisión activos,
    indicando si están actualizados, desactualizados o sin fuente asignada.
    Útil para el panel de administración de factores.
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT fe.id, fe.pais, fe.tipo_energia, fe.anio, fe.version,
                      fe.factor_kg_co2_mwh, fe.fuente,
                      COALESCE(fu.nombre, fe.fuente, 'Sin fuente') AS fuente_nombre,
                      COALESCE(fu.url, fe.url, '') AS fuente_url,
                      COALESCE(fe.modificado_en, fe.fecha_carga) AS ultima_actualizacion,
                      CAST(
                        julianday('now') - julianday(
                          COALESCE(fe.modificado_en, fe.fecha_carga)
                        ) AS INTEGER
                      ) AS dias_sin_actualizar
               FROM factores_emision fe
               LEFT JOIN fuentes_emision fu ON fu.id = fe.fuente_id
               WHERE fe.activo=1 AND fe.es_version_activa=1
               ORDER BY fe.pais, fe.anio DESC"""
        ).fetchall()

    resultado = []
    for r in rows:
        d = dict(r)
        dias = d.get('dias_sin_actualizar') or 0
        if dias <= 180:
            d['estado_actualizacion'] = 'actualizado'
        elif dias <= 365:
            d['estado_actualizacion'] = 'revisar'
        else:
            d['estado_actualizacion'] = 'desactualizado'
        resultado.append(d)
    return resultado


def listar_alertas(estado: str = None, severidad: str = None,
                   tipo: str = None, pais: str = None,
                   sede: str = None, limit: int = 200) -> list[dict]:
    """Lista alertas con filtros opcionales."""
    cond, params = [], []
    if estado:
        cond.append("estado=?"); params.append(estado)
    if severidad:
        cond.append("severidad=?"); params.append(severidad)
    if tipo:
        cond.append("tipo=?"); params.append(tipo)
    if pais:
        cond.append("pais=?"); params.append(pais.upper())
    if sede:
        cond.append("sede=?"); params.append(sede)

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT * FROM alertas {where}
                ORDER BY
                  CASE severidad WHEN 'critica' THEN 1 WHEN 'media' THEN 2 ELSE 3 END,
                  fecha_creacion DESC
                LIMIT ?''',
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


def resolver_alerta(alerta_id: int, resuelta_por: str = 'usuario',
                    notas: str = None) -> dict | None:
    """Marca una alerta como resuelta."""
    with get_db_connection() as conn:
        conn.execute(
            '''UPDATE alertas
               SET estado='resuelta', fecha_resolucion=CURRENT_TIMESTAMP,
                   resuelta_por=?, notas_resolucion=?
               WHERE id=? AND estado='pendiente' ''',
            (resuelta_por, notas, alerta_id)
        )
        row = conn.execute("SELECT * FROM alertas WHERE id=?", (alerta_id,)).fetchone()
    return dict(row) if row else None


def ignorar_alerta(alerta_id: int, resuelta_por: str = 'usuario') -> dict | None:
    """Marca una alerta como ignorada."""
    with get_db_connection() as conn:
        conn.execute(
            '''UPDATE alertas SET estado='ignorada', fecha_resolucion=CURRENT_TIMESTAMP,
               resuelta_por=? WHERE id=? AND estado='pendiente' ''',
            (resuelta_por, alerta_id)
        )
        row = conn.execute("SELECT * FROM alertas WHERE id=?", (alerta_id,)).fetchone()
    return dict(row) if row else None


def resumen_alertas() -> dict:
    """Resumen de alertas por estado y severidad para el dashboard."""
    with get_db_connection() as conn:
        rows = conn.execute(
            '''SELECT estado, severidad, COUNT(*) as n
               FROM alertas GROUP BY estado, severidad'''
        ).fetchall()

    pendientes = {'critica': 0, 'media': 0, 'informativa': 0}
    resueltas = 0
    ignoradas = 0

    for r in rows:
        if r['estado'] == 'pendiente':
            pendientes[r['severidad']] = r['n']
        elif r['estado'] == 'resuelta':
            resueltas += r['n']
        elif r['estado'] == 'ignorada':
            ignoradas += r['n']

    return {
        'pendientes': pendientes,
        'total_pendientes': sum(pendientes.values()),
        'resueltas': resueltas,
        'ignoradas': ignoradas,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_config(conn, tipo: str, subtipo: str) -> dict | None:
    try:
        row = conn.execute(
            'SELECT * FROM alertas_config WHERE tipo=? AND subtipo=?',
            (tipo, subtipo)
        ).fetchone()
        return dict(row) if row else {'activa': 1, 'severidad': 'media', 'umbral_valor': None}
    except Exception:
        return {'activa': 1, 'severidad': 'media', 'umbral_valor': None}


def _existe_alerta_pendiente(conn, tipo: str, subtipo: str,
                               entidad: str = None, entidad_id: int = None,
                               pais: str = None, sede: str = None,
                               mes: str = None) -> bool:
    cond = ["tipo=?", "subtipo=?", "estado='pendiente'"]
    params = [tipo, subtipo]
    if entidad:
        cond.append("entidad=?"); params.append(entidad)
    if entidad_id is not None:
        cond.append("entidad_id=?"); params.append(entidad_id)
    if pais:
        cond.append("pais=?"); params.append(pais)
    if sede:
        cond.append("sede=?"); params.append(sede)
    if mes:
        cond.append("mes=?"); params.append(mes)
    where = "WHERE " + " AND ".join(cond)
    n = conn.execute(f"SELECT COUNT(*) FROM alertas {where}", params).fetchone()[0]
    return n > 0


def _insertar_alerta(conn, datos: dict) -> int:
    cursor = conn.execute(
        '''INSERT INTO alertas
               (tipo, subtipo, severidad, titulo, descripcion,
                entidad, entidad_id, pais, sede, mes, datos_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (
            datos.get('tipo'), datos.get('subtipo'), datos.get('severidad', 'media'),
            datos.get('titulo'), datos.get('descripcion'),
            datos.get('entidad'), datos.get('entidad_id'),
            datos.get('pais'), datos.get('sede'), datos.get('mes'),
            datos.get('datos_json'),
        )
    )
    return cursor.lastrowid


# ── Fase 6: Detección avanzada de anomalías ────────────────────────────────────

def _alertas_consumo_zscore() -> int:
    """
    Detecta consumos estadísticamente anómalos usando z-score por sede.
    Alerta cuando |z| > 2.5 (aproximadamente top/bottom 1.2% de la distribución).

    Más robusto que el umbral fijo porque se adapta a la variabilidad de cada sede.
    """
    import math
    n = 0
    with get_db_connection() as conn:
        # Calcular media y desviación estándar por sede
        stats_rows = conn.execute(
            """SELECT pais, sede, tipo_energia,
                      AVG(consumo_mwh) AS media,
                      AVG(consumo_mwh * consumo_mwh) - AVG(consumo_mwh) * AVG(consumo_mwh) AS varianza,
                      COUNT(*) AS n
               FROM facturas
               WHERE fecha_anulacion IS NULL AND consumo_mwh > 0 AND tipo_dato='real'
               GROUP BY pais, sede, tipo_energia
               HAVING n >= 6"""
        ).fetchall()

        for stat in stats_rows:
            std = math.sqrt(max(stat['varianza'] or 0, 0))
            if std == 0:
                continue
            umbral_z = 2.5

            facturas = conn.execute(
                """SELECT id, archivo_nombre, consumo_mwh, periodo_inicio, pais, sede
                   FROM facturas
                   WHERE fecha_anulacion IS NULL AND consumo_mwh > 0 AND tipo_dato='real'
                     AND pais=? AND sede=? AND tipo_energia=?""",
                (stat['pais'], stat['sede'], stat['tipo_energia'])
            ).fetchall()

            for f in facturas:
                z = abs(f['consumo_mwh'] - stat['media']) / std
                if z <= umbral_z:
                    continue
                if _existe_alerta_pendiente(conn, 'anomalia', 'zscore_consumo',
                                             entidad='factura', entidad_id=f['id']):
                    continue
                direccion = 'alto' if f['consumo_mwh'] > stat['media'] else 'bajo'
                _insertar_alerta(conn, {
                    'tipo': 'anomalia',
                    'subtipo': 'zscore_consumo',
                    'severidad': 'media',
                    'titulo': f"Consumo estadísticamente anómalo ({direccion}, z={z:.1f}) — {f['archivo_nombre']}",
                    'descripcion': (
                        f"La factura {f['archivo_nombre']} ({f['sede']}) tiene consumo {f['consumo_mwh']:.1f} MWh "
                        f"que se desvía {z:.1f} desviaciones estándar de la media de la sede "
                        f"({stat['media']:.1f} MWh ± {std:.1f}). "
                        f"Revisar si es un período atípico o un error de extracción."
                    ),
                    'entidad': 'factura',
                    'entidad_id': f['id'],
                    'pais': f['pais'],
                    'sede': f['sede'],
                    'datos_json': json.dumps({
                        'z_score': round(z, 2),
                        'consumo_mwh': f['consumo_mwh'],
                        'media_sede': round(stat['media'], 2),
                        'std_sede': round(std, 2),
                        'direccion': direccion,
                    }),
                })
                n += 1
    return n


def _alertas_cambio_interanual_brusco() -> int:
    """
    Detecta cambios bruscos entre el mismo mes de años consecutivos (>80% de variación).
    Filtra sedes con al menos 12 meses de histórico para evitar falsos positivos.
    """
    n = 0
    umbral_pct = 80.0  # % de variación máxima aceptable
    anio_actual = str(date.today().year)

    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT f1.id,
                      f1.pais, f1.sede, f1.tipo_energia,
                      f1.archivo_nombre,
                      f1.consumo_mwh AS consumo_actual,
                      f2.consumo_mwh AS consumo_anterior,
                      strftime('%Y-%m', COALESCE(f1.periodo_inicio, f1.fecha_carga)) AS mes_fact
               FROM facturas f1
               JOIN facturas f2
                 ON f2.pais = f1.pais AND f2.sede = f1.sede
                  AND f2.tipo_energia = f1.tipo_energia
                  AND strftime('%m', COALESCE(f2.periodo_inicio, f2.fecha_carga))
                      = strftime('%m', COALESCE(f1.periodo_inicio, f1.fecha_carga))
                  AND strftime('%Y', COALESCE(f2.periodo_inicio, f2.fecha_carga))
                      = CAST(CAST(strftime('%Y', COALESCE(f1.periodo_inicio, f1.fecha_carga)) AS INT) - 1 AS TEXT)
                  AND f2.fecha_anulacion IS NULL AND f2.consumo_mwh > 0
               WHERE f1.fecha_anulacion IS NULL
                 AND f1.consumo_mwh > 0
                 AND f1.tipo_dato = 'real'
                 AND strftime('%Y', COALESCE(f1.periodo_inicio, f1.fecha_carga)) = ?""",
            (anio_actual,)
        ).fetchall()

        for r in rows:
            if not r['consumo_anterior']:
                continue
            variacion_pct = abs(r['consumo_actual'] - r['consumo_anterior']) / r['consumo_anterior'] * 100
            if variacion_pct <= umbral_pct:
                continue
            if _existe_alerta_pendiente(conn, 'anomalia', 'cambio_interanual',
                                         entidad='factura', entidad_id=r['id']):
                continue
            direccion = '↑' if r['consumo_actual'] > r['consumo_anterior'] else '↓'
            _insertar_alerta(conn, {
                'tipo': 'anomalia',
                'subtipo': 'cambio_interanual',
                'severidad': 'media' if variacion_pct < 150 else 'critica',
                'titulo': (
                    f"Cambio interanual brusco {direccion}{variacion_pct:.0f}% — "
                    f"{r['sede']} ({r['mes_fact']})"
                ),
                'descripcion': (
                    f"Consumo {r['consumo_actual']:.1f} MWh vs {r['consumo_anterior']:.1f} MWh "
                    f"del mismo mes del año anterior (variación {variacion_pct:.0f}%). "
                    f"Factura: {r['archivo_nombre']}."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'mes': r['mes_fact'],
                'datos_json': json.dumps({
                    'consumo_actual': r['consumo_actual'],
                    'consumo_anterior': r['consumo_anterior'],
                    'variacion_pct': round(variacion_pct, 1),
                }),
            })
            n += 1
    return n


def _alertas_periodo_anomalo() -> int:
    """
    Detecta facturas con períodos de facturación anómalos:
      - Demasiado cortos: < 15 días (puede ser períodos parciales o errores OCR)
      - Demasiado largos: > 45 días (pueden acumular consumo de varios meses)
    """
    n = 0
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT id, pais, sede, archivo_nombre,
                      periodo_inicio, periodo_fin,
                      CAST(
                        julianday(periodo_fin) - julianday(periodo_inicio)
                      AS INTEGER) AS dias_periodo
               FROM facturas
               WHERE fecha_anulacion IS NULL
                 AND periodo_inicio IS NOT NULL
                 AND periodo_fin IS NOT NULL
                 AND periodo_fin > periodo_inicio"""
        ).fetchall()

        for r in rows:
            dias = r['dias_periodo']
            if dias is None:
                continue

            if 15 <= dias <= 45:
                continue

            subtipo   = 'periodo_corto' if dias < 15 else 'periodo_largo'
            severidad = 'informativa' if 10 <= dias <= 50 else 'media'
            if _existe_alerta_pendiente(conn, 'calidad', subtipo,
                                         entidad='factura', entidad_id=r['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'calidad',
                'subtipo': subtipo,
                'severidad': severidad,
                'titulo': (
                    f"Período {'corto' if dias < 15 else 'largo'} ({dias} días) — "
                    f"{r['archivo_nombre']}"
                ),
                'descripcion': (
                    f"La factura {r['archivo_nombre']} ({r['sede']}) cubre {dias} días "
                    f"({r['periodo_inicio']} → {r['periodo_fin']}). "
                    f"Un período {'inferior a 15' if dias < 15 else 'superior a 45'} días puede indicar "
                    f"un error de extracción OCR o una situación especial de suministro."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'datos_json': json.dumps({
                    'dias_periodo': dias,
                    'periodo_inicio': r['periodo_inicio'],
                    'periodo_fin': r['periodo_fin'],
                }),
            })
            n += 1
    return n


def _alertas_ocr_incoherente() -> int:
    """
    Detecta facturas donde los campos extraídos por OCR parecen internamente incoherentes.
    Criterios:
      - Consumo kWh y MWh no concuerdan (diferencia > 1%)
      - Fecha de factura anterior al inicio del período de facturación
      - CUPS con longitud incorrecta (debe tener 20-22 caracteres en España)
    """
    n = 0
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT id, pais, sede, archivo_nombre,
                      consumo_kwh, consumo_mwh,
                      fecha_factura, periodo_inicio, periodo_fin,
                      cups
               FROM facturas
               WHERE fecha_anulacion IS NULL"""
        ).fetchall()

        for r in rows:
            incoherencias = []

            # Incoherencia kWh / MWh
            if r['consumo_kwh'] and r['consumo_mwh']:
                esperado_mwh = r['consumo_kwh'] / 1000.0
                if abs(r['consumo_mwh'] - esperado_mwh) / max(esperado_mwh, 0.001) > 0.01:
                    incoherencias.append(
                        f"kWh ({r['consumo_kwh']}) y MWh ({r['consumo_mwh']}) no concuerdan"
                    )

            # Fecha factura anterior al período
            if r['fecha_factura'] and r['periodo_fin']:
                if r['fecha_factura'] < r['periodo_fin']:
                    incoherencias.append(
                        f"Fecha factura ({r['fecha_factura']}) anterior al fin del período ({r['periodo_fin']})"
                    )

            # CUPS con longitud incorrecta (España: 20 chars)
            if r['cups'] and r['pais'] == 'ES':
                cups_clean = r['cups'].replace(' ', '')
                if not (18 <= len(cups_clean) <= 22):
                    incoherencias.append(
                        f"CUPS con longitud inusual: {len(cups_clean)} caracteres (esperado 20)"
                    )

            if not incoherencias:
                continue
            if _existe_alerta_pendiente(conn, 'calidad', 'ocr_incoherente',
                                         entidad='factura', entidad_id=r['id']):
                continue
            _insertar_alerta(conn, {
                'tipo': 'calidad',
                'subtipo': 'ocr_incoherente',
                'severidad': 'media',
                'titulo': f"Datos OCR incoherentes — {r['archivo_nombre']}",
                'descripcion': (
                    f"Se detectaron {len(incoherencias)} incoherencias en {r['archivo_nombre']} "
                    f"({r['sede']}): {'; '.join(incoherencias)}. Revisar extracción manual."
                ),
                'entidad': 'factura',
                'entidad_id': r['id'],
                'pais': r['pais'],
                'sede': r['sede'],
                'datos_json': json.dumps({'incoherencias': incoherencias}),
            })
            n += 1
    return n
