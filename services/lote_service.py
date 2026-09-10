"""
Servicio de procesamiento en lote de facturas eléctricas.

El procesamiento es secuencial (un PDF a la vez) para evitar problemas
de memoria y concurrencia con PaddleOCR.  Se ejecuta en un hilo daemon
de Python; el endpoint principal devuelve el lote_id inmediatamente y
el frontend hace polling a /api/lote/<id>/estado.

El progreso y los resultados se persisten en la tabla `lotes` (campo
resultados_json) para que el polling funcione aunque el proceso tarde.

Cambios arquitectónicos:
  P1 — Almacenamiento delegado a DocumentoStorage (Strategy pattern).
  P5 — Detección de duplicados por período y por SHA-256.
  P6 — Validaciones de calidad: fechas, consumo, anomalías (3σ).
  P2 — Audit log en carga individual y en lote.
"""

import json
import logging
import math
import os
import threading
import uuid
from datetime import datetime

from database.connection import get_db_connection
from services.extractor_service import ExtractorFactory
from services.emisiones_service import calcular_emisiones
from services.documento_service import get_documento_storage
from services.audit_service import (
    registrar_evento,
    ACCION_FACTURA_CARGADA, ACCION_FACTURA_DUPLICADO,
    ACCION_LOTE_INICIADO, ACCION_LOTE_COMPLETADO,
)
from services.validacion_service import validar_factura_completa
from services.ocr_quality_service import FIELD_WEIGHTS
import config

logger = logging.getLogger(__name__)


# ── API pública ──────────────────────────────────────────────────────────────

def crear_lote(total_archivos: int) -> str:
    """Crea un registro de lote en BD y devuelve su UUID."""
    lote_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO lotes (id, total_archivos, estado, resultados_json)
               VALUES (?, ?, 'procesando', '[]')''',
            (lote_id, total_archivos)
        )
    return lote_id


def procesar_lote_async(lote_id: str, archivos_guardados: list, pais: str, sede: str,
                        usuario: str = 'usuario', ip_origen: str = None,
                        sociedad_manual: str = None):
    """
    Lanza el procesamiento en un hilo daemon (no bloquea el request de Flask).

    archivos_guardados: lista de dicts con claves 'nombre_original', 'ruta'
                        y opcionalmente 'doc_info' (de DocumentoStorage).
    sociedad_manual:    respaldo para cuando la plantilla no logre extraer la
                        sociedad de la factura. Nunca sustituye a la extraída.
    """
    registrar_evento(
        accion=ACCION_LOTE_INICIADO,
        usuario=usuario,
        detalle={'lote_id': lote_id, 'total': len(archivos_guardados), 'pais': pais, 'sede': sede},
        ip_origen=ip_origen,
    )
    hilo = threading.Thread(
        target=_worker,
        args=(lote_id, archivos_guardados, pais, sede, usuario, sociedad_manual),
        daemon=True,
        name=f"lote-{lote_id[:8]}"
    )
    hilo.start()
    logger.info(f"[LOTE {lote_id[:8]}] Hilo iniciado — {len(archivos_guardados)} archivos")


def obtener_estado_lote(lote_id: str) -> dict | None:
    """Devuelve el estado actual del lote para el endpoint de polling."""
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT * FROM lotes WHERE id = ?', (lote_id,)
        ).fetchone()

    if not row:
        return None

    resultados = json.loads(row['resultados_json'] or '[]')
    procesados = row['procesados_ok'] + row['procesados_error']

    return {
        'lote_id': lote_id,
        'estado': row['estado'],
        'progreso': {
            'total':     row['total_archivos'],
            'procesados': procesados,
            'ok':        row['procesados_ok'],
            'error':     row['procesados_error'],
            'pendientes': max(0, row['total_archivos'] - procesados),
        },
        'resultados': resultados,
    }


# ── Worker interno ───────────────────────────────────────────────────────────

def _worker(lote_id: str, archivos: list, pais: str, sede: str,
            usuario: str = 'usuario', sociedad_manual: str = None):
    """Procesa cada archivo del lote y actualiza la BD tras cada uno."""
    ok = 0
    error = 0
    resultados: list[dict] = []

    for info in archivos:
        nombre   = info['nombre_original']
        ruta     = info['ruta']
        doc_info = info.get('doc_info')
        try:
            logger.info(f"[LOTE {lote_id[:8]}] ⚙️  {nombre}")
            res = _procesar_una(ruta, nombre, pais, sede, lote_id,
                                doc_info=doc_info, usuario=usuario,
                                sociedad_manual=sociedad_manual)
            ok += 1
            resultados.append({
                'archivo':           nombre,
                'estado':            'ok',
                'factura_id':        res['factura_id'],
                'requiere_revision': res['requiere_revision'],
                'campos_a_revisar':  res['campos_a_revisar'],
                'advertencias':      res.get('advertencias', []),
                'resumen':           res['resumen'],
            })
        except Exception as exc:
            error += 1
            logger.error(f"[LOTE {lote_id[:8]}] ❌ {nombre}: {exc}")
            resultados.append({
                'archivo': nombre,
                'estado':  'error',
                'error':   str(exc),
            })

        _actualizar_lote(lote_id, ok, error, resultados,
                         'procesando' if (ok + error) < len(archivos) else _estado_final(ok, error))

    # Marcar finalizado
    _actualizar_lote(lote_id, ok, error, resultados, _estado_final(ok, error), cerrar=True)
    logger.info(f"[LOTE {lote_id[:8]}] ✅ Completado: {ok} OK / {error} errores")
    registrar_evento(
        accion=ACCION_LOTE_COMPLETADO,
        usuario=usuario,
        detalle={'lote_id': lote_id, 'ok': ok, 'errores': error},
    )


def _estado_final(ok: int, error: int) -> str:
    return 'completado' if error == 0 else 'completado_con_errores'


def _actualizar_lote(lote_id, ok, error, resultados, estado, cerrar=False):
    """
    Persiste el estado parcial o final del lote.

    resultados_json se trunca a MAX_RESULTADOS_JSON entradas para evitar
    O(n²) en lotes masivos: cada UPDATE reescribe el JSON completo.
    Los primeros resultados_json_offset se guardan siempre; si hay más,
    se mantienen las últimas entradas y se registra en metadata cuántos
    se omitieron. El total real (ok + error) sigue siendo correcto.
    """
    MAX_RESULTADOS_JSON = 500  # máx entradas en el blob JSON del lote

    if len(resultados) > MAX_RESULTADOS_JSON:
        omitidos = len(resultados) - MAX_RESULTADOS_JSON
        resultados_guardados = resultados[-MAX_RESULTADOS_JSON:]
        resultados_guardados.insert(0, {
            'archivo':  f'[{omitidos} resultados anteriores omitidos por límite de {MAX_RESULTADOS_JSON}]',
            'estado':   'omitido',
            'error':    None,
        })
    else:
        resultados_guardados = resultados

    extra = ', fecha_fin = CURRENT_TIMESTAMP' if cerrar else ''
    with get_db_connection() as conn:
        conn.execute(
            f'''UPDATE lotes
               SET procesados_ok = ?, procesados_error = ?,
                   estado = ?, resultados_json = ?
                   {extra}
               WHERE id = ?''',
            (ok, error, estado,
             json.dumps(resultados_guardados, ensure_ascii=False),
             lote_id)
        )


def _aplicar_sociedad_respaldo(datos, sociedad_manual: str) -> bool:
    """
    Rellena la sociedad con el valor del formulario SOLO si la extracción no
    la obtuvo. Devuelve True si se ha aplicado el respaldo.

    Nunca sustituye a la sociedad leída de la factura: una misma sede puede
    tener varios CUPS facturados a sociedades distintas, así que el dato del
    documento siempre manda sobre el del formulario.
    """
    if not sociedad_manual or not sociedad_manual.strip():
        return False
    actual = getattr(datos, 'sociedad', None)
    if actual and str(actual).strip():
        return False
    datos.sociedad = sociedad_manual.strip()
    return True


def _procesar_una(ruta: str, nombre_original: str, pais: str, sede: str,
                  lote_id: str, doc_info: dict = None,
                  usuario: str = 'usuario', ip_origen: str = None,
                  tipo_energia: str = 'electricidad',
                  sociedad_manual: str = None) -> dict:
    """
    Extrae datos, valida calidad, detecta duplicados, calcula emisiones
    y persiste una sola factura.

    Parameters
    ----------
    ruta            : ruta local al PDF (para OCR).
    nombre_original : nombre del archivo tal como lo subió el usuario.
    pais, sede      : contexto de la factura.
    lote_id         : ID del lote al que pertenece (None para cargas individuales).
    doc_info        : metadatos de DocumentoStorage (sha256, fuente_documento_id…).
                      Si es None se computa sha256 desde el archivo en disco.
    usuario, ip_origen: para audit_log.
    tipo_energia    : tipo de suministro; determina el extractor OCR a usar.
                      Default 'electricidad' — retrocompatible con llamadas antiguas.
    """
    # ── Construir doc_info si no viene del storage ────────────────────────────
    if doc_info is None:
        import hashlib
        try:
            with open(ruta, 'rb') as f_bin:
                sha256 = hashlib.sha256(f_bin.read()).hexdigest()
        except Exception:
            sha256 = None
        doc_info = {
            'archivo_nombre':  nombre_original,
            'archivo_ruta':    ruta,
            'external_source': 'local',
            'external_doc_id': None,
            'external_doc_url': None,
            'sha256':          sha256,
        }

    # ── 1. Extracción OCR (via ExtractorFactory — extensible a nuevos suministros) ──
    datos = ExtractorFactory.get(tipo_energia).extraer(ruta, pais)
    if not datos.consumo_kwh:
        raise ValueError("No se detectó consumo en kWh")

    # La sociedad indicada en el formulario es solo un respaldo: se aplica
    # cuando la plantilla no ha sabido leerla de la factura, nunca por encima
    # del valor extraído. Una sede puede facturar a varias sociedades (un CUPS
    # de cada una), así que imponer una sola desde el formulario falsearía el
    # dato en las facturas de las demás.
    if _aplicar_sociedad_respaldo(datos, sociedad_manual):
        logger.info(f"  Sociedad tomada del formulario: {datos.sociedad}")

    # ── 2. Validaciones de calidad (P6) ───────────────────────────────────────
    advertencias = _validar_calidad(datos, pais, sede, 'electricidad', doc_info.get('sha256'))

    # ── 2.5 Validación histórica avanzada (QW1) ────────────────────────────────
    # Activa services/ocr_quality_service.validar_con_historico(), que ya existía
    # implementado (13+ comprobaciones: z-score de consumo vs. histórico de sede,
    # CUPS vs. histórico por distancia de Levenshtein, solapes/huecos de período,
    # fechas imposibles, comercializadora inusual, etc.) pero nunca se invocaba
    # desde el pipeline. Muta datos.confianza_por_campo / datos.confianza_global
    # directamente, así que campos_a_revisar (más abajo) ya lo refleja sin más
    # cambios.
    try:
        incidencias, forzar_revision_por_validacion = validar_factura_completa(
            datos, pais, sede, tipo_energia
        )
        mensajes = [inc['mensaje'] for inc in incidencias if inc['mensaje'] not in advertencias]
        advertencias.extend(mensajes)
        datos.inconsistencias = list(datos.inconsistencias or []) + mensajes
        datos.advertencias = list(datos.advertencias or []) + mensajes
        datos.incidencias_estructuradas = incidencias
    except Exception as exc:
        # Defensivo: un fallo aquí no debe impedir procesar la factura, pero sí
        # debe verse en logs (a diferencia del patrón "except Exception: return []"
        # que señalamos como antipatrón en la auditoría).
        logger.error(f"  [Validación] Error en validar_factura_completa para {pais}/{sede}: {exc}", exc_info=True)
        forzar_revision_por_validacion = False

    # ── 3. Determinar año para el factor de emisión ───────────────────────────
    if datos.periodo_inicio:
        anio = datos.periodo_inicio[:4]
    elif datos.fecha_factura:
        anio = datos.fecha_factura[:4]
    else:
        anio = str(datetime.now().year)

    emisiones, factor, fuente, factor_version_id = calcular_emisiones(
        datos.consumo_mwh, pais, anio
    )
    if emisiones is None:
        raise ValueError(f"Factor de emisión no disponible para {pais}/{anio}")

    # ── 4. Estado según confianza OCR ─────────────────────────────────────────
    # `confianza_por_campo` usa None como sentinela de "este campo no aplica a
    # esta plantilla". Un campo que no aplica no puede requerir revisión, y
    # compararlo con el umbral reventaba (None < float).
    # Además se acota a los campos que la plantilla declara: los extractores
    # genéricos rellenan campos que esa factura no trae, y sin este filtro se
    # pedía al usuario "revisar" una dirección de suministro que no existe.
    aplicables = set(getattr(datos, 'campos_aplicables', None) or []) or None
    campos_a_revisar = [
        campo for campo, score in datos.confianza_por_campo.items()
        if score is not None
        and (aplicables is None or campo in aplicables)
        and score < getattr(config, 'UMBRAL_REVISION', 0.75)
    ]
    estado = 'pendiente_revision' if campos_a_revisar else 'procesada'

    # ── 4bis. Bound físico duro (QW9) — separa "¿el OCR está seguro?" de ──────
    # "¿lo que leyó es físicamente posible?". Antes, un consumo imposible con
    # alta confianza OCR podía pasar sin forzar revisión.
    if forzar_revision_por_validacion:
        if 'consumo' not in campos_a_revisar:
            campos_a_revisar.append('consumo')
        estado = 'pendiente_revision'

    # ── 5. Flag de duplicado (P5) ─────────────────────────────────────────────
    duplicado_potencial = 1 if any(
        'Duplicado' in adv for adv in advertencias
    ) else 0

    # ── 6. Obtener suministro_id ──────────────────────────────────────────────
    suministro_id = _obtener_suministro_id(pais, sede, 'electricidad',
                                           getattr(datos, 'cups', None))

    # ── 7. Insertar en BD ─────────────────────────────────────────────────────
    # Fase 5: calcular ejercicio y recopilar inconsistencias
    ejercicio = None
    for campo_fecha in (datos.periodo_inicio, datos.fecha_factura):
        if campo_fecha and len(campo_fecha) >= 4:
            ejercicio = campo_fecha[:4]
            break

    inconsistencias_json = (
        json.dumps(datos.inconsistencias, ensure_ascii=False)
        if getattr(datos, 'inconsistencias', None) else None
    )
    carpeta_relativa = doc_info.get('carpeta_relativa')

    with get_db_connection() as conn:
        cursor = conn.execute(
            '''INSERT INTO facturas
               (pais, sede, tipo_energia, archivo_nombre, archivo_ruta,
                consumo_kwh, consumo_mwh, comercializadora, cups,
                factor_emision, emisiones_tco2e, estado, datos_json,
                fecha_factura, periodo_inicio, periodo_fin, dias_facturados,
                sociedad, direccion_suministro,
                importe_total, moneda, tarifa, contrato, potencia_kw, distribuidora,
                confianza_ocr, campos_confianza,
                lote_id, factor_version_id, tipo_dato,
                sha256_documento, suministro_id, duplicado_potencial,
                external_source, external_doc_id, external_doc_url,
                fuente_documento_id, export_state,
                ejercicio, inconsistencias_json, carpeta_relativa)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                pais, sede, tipo_energia, nombre_original, doc_info['archivo_ruta'],
                datos.consumo_kwh, datos.consumo_mwh,
                datos.comercializadora, datos.cups,
                factor, emisiones, estado,
                json.dumps({'texto_preview': datos.texto_preview}, ensure_ascii=False),
                datos.fecha_factura, datos.periodo_inicio, datos.periodo_fin,
                datos.dias_facturados, datos.sociedad, datos.direccion_suministro,
                datos.importe_total, datos.moneda, datos.tarifa,
                datos.contrato, datos.potencia_kw, datos.distribuidora,
                datos.confianza_global,
                json.dumps(datos.confianza_por_campo, ensure_ascii=False),
                lote_id, factor_version_id, 'real',
                doc_info.get('sha256'),
                suministro_id,
                duplicado_potencial,
                doc_info.get('external_source', 'local'),
                doc_info.get('external_doc_id'),
                doc_info.get('external_doc_url'),
                doc_info.get('fuente_documento_id'),
                'pending',
                ejercicio, inconsistencias_json, carpeta_relativa,
            )
        )
        factura_id = cursor.lastrowid

        # Fase 5: indexar en documentos_indice
        _indexar_documento(conn, factura_id, ejercicio, pais, sede,
                           datos.sociedad, datos.mes,
                           nombre_original, carpeta_relativa,
                           doc_info['archivo_ruta'], doc_info.get('sha256'))

    # ── Fase 6: reconciliación automática estimado → real ────────────────────
    # Todas las facturas procesadas por lote_service son 'real' (ver INSERT arriba).
    # Si existe un mes determinado, intentar sustituir estimaciones vigentes.
    if datos.mes:
        try:
            from services.estimacion_service import reconciliar_automatico
            reconciliacion = reconciliar_automatico(
                pais=pais, sede=sede, mes=datos.mes,
                factura_real_id=factura_id,
                tipo_energia=tipo_energia,
            )
            if reconciliacion['reconciliadas'] > 0:
                logger.info(
                    f"[Fase6] Reconciliadas {reconciliacion['reconciliadas']} estimaciones "
                    f"para {pais}/{sede} mes {datos.mes}"
                )
        except Exception as exc:
            logger.warning(f"[Fase6] Error en reconciliación automática: {exc}")

    # ── 8. Audit log ──────────────────────────────────────────────────────────
    accion_audit = ACCION_FACTURA_DUPLICADO if duplicado_potencial else ACCION_FACTURA_CARGADA
    registrar_evento(
        accion=accion_audit,
        usuario=usuario,
        entidad='factura',
        entidad_id=factura_id,
        detalle={
            'pais': pais, 'sede': sede,
            'consumo_kwh': datos.consumo_kwh,
            'emisiones_tco2e': emisiones,
            'periodo': f"{datos.periodo_inicio}→{datos.periodo_fin}",
            'advertencias': advertencias,
            'lote_id': lote_id,
        },
        ip_origen=ip_origen,
    )

    # QW8 — orden de campos por impacto en la confianza global, para que el
    # modal de revisión muestre primero lo que más penaliza al conjunto.
    # Se excluyen los campos no aplicables (score None): no penalizan nada y
    # `1 - None` reventaba.
    campos_ordenados_por_impacto = sorted(
        [c for c, v in datos.confianza_por_campo.items() if v is not None],
        key=lambda c: (1 - datos.confianza_por_campo[c]) * FIELD_WEIGHTS.get(c, 0.05),
        reverse=True,
    )

    return {
        'factura_id':        factura_id,
        'requiere_revision': bool(campos_a_revisar),
        'campos_a_revisar':  campos_a_revisar,
        'advertencias':      advertencias,
        'resumen': {
            'consumo_kwh':          datos.consumo_kwh,
            'consumo_mwh':          datos.consumo_mwh,
            'periodo_inicio':       datos.periodo_inicio,
            'periodo_fin':          datos.periodo_fin,
            'dias_facturados':      datos.dias_facturados,
            'fecha_factura':        datos.fecha_factura,
            'comercializadora':     datos.comercializadora,
            'sociedad':             datos.sociedad,
            'direccion_suministro': datos.direccion_suministro,
            'importe_total':        datos.importe_total,
            'moneda':               datos.moneda,
            'tarifa':               datos.tarifa,
            'contrato':             datos.contrato,
            'potencia_kw':          datos.potencia_kw,
            'distribuidora':        datos.distribuidora,
            # Permite a la UI mostrar solo los campos que esta plantilla declara,
            # en vez de pintar cajas vacías de datos que esa factura no trae.
            'campos_aplicables':    datos.campos_aplicables,
            'factor_kg_co2_mwh':   factor,
            'fuente_factor':        fuente,
            'anio_factor':          anio,
            'emisiones_tco2e':      emisiones,
            'confianza_global':     datos.confianza_global,
            'confianza_por_campo':  datos.confianza_por_campo,
            'duplicado_potencial':  bool(duplicado_potencial),
            'campos_ordenados_por_impacto': campos_ordenados_por_impacto,  # QW8
        },
    }


# Alias público — compatible con llamadas previas (routes/facturas.py)
procesar_factura_individual = _procesar_una


# ── Validaciones de calidad (P6) ─────────────────────────────────────────────

def _validar_calidad(datos, pais: str, sede: str, tipo_energia: str,
                     sha256: str = None) -> list[str]:
    """
    Ejecuta todas las validaciones de calidad y devuelve lista de advertencias.
    Las advertencias no bloquean la carga (se registran como metadato).
    """
    advertencias = []

    # P6a: período coherente
    if datos.periodo_inicio and datos.periodo_fin:
        if datos.periodo_inicio > datos.periodo_fin:
            advertencias.append(
                f"Período inválido: inicio {datos.periodo_inicio} > fin {datos.periodo_fin}"
            )

    # P6b: consumo positivo (ya garantizado por el check de consumo_kwh, pero por completitud)
    if datos.consumo_kwh is not None and datos.consumo_kwh <= 0:
        advertencias.append(f"Consumo no positivo: {datos.consumo_kwh} kWh")

    # P6c: consumo anómalo frente al histórico del mismo punto de suministro
    if datos.consumo_kwh:
        anomalia = _detectar_anomalia_consumo(
            pais, sede, tipo_energia, datos.consumo_kwh, getattr(datos, 'cups', None)
        )
        if anomalia:
            advertencias.append(anomalia)

    # P5: duplicados
    advertencias.extend(
        _verificar_duplicados(
            pais, sede, tipo_energia,
            datos.periodo_inicio, datos.periodo_fin, sha256,
            getattr(datos, 'cups', None)
        )
    )

    return advertencias


def _detectar_anomalia_consumo(pais: str, sede: str, tipo_energia: str,
                                consumo_kwh: float, cups: str = None) -> str | None:
    """
    Detecta si el consumo es anómalo comparado con el histórico de la sede.
    Usa el criterio MÁS RESTRICTIVO entre:
      - consumo > media + 3·σ  (distribución normal)
      - consumo > 2·media      (200% del histórico)
    Retorna un mensaje de advertencia, o None si no hay anomalía o pocos datos.

    Cuando se conoce el CUPS, el histórico se acota a ese punto de suministro.
    En una sede con varios CUPS los consumos son de órdenes muy distintos
    (p. ej. 1.850 kWh de la oficina frente a 90 kWh de un garaje): mezclarlos
    hunde la media y hace que el CUPS grande parezca anómalo todos los meses.
    """
    try:
        with get_db_connection() as conn:
            cond_cups = "AND cups = ?" if cups else ""
            params = [pais, sede, tipo_energia]
            if cups:
                params.append(cups)

            rows = conn.execute(
                f'''SELECT consumo_kwh FROM facturas
                    WHERE pais=? AND sede=? AND tipo_energia=?
                      AND tipo_dato='real' AND consumo_kwh > 0
                      AND fecha_anulacion IS NULL
                      {cond_cups}
                    ORDER BY fecha_carga DESC LIMIT 24''',
                params
            ).fetchall()

        if len(rows) < 3:
            return None  # No suficientes datos históricos

        valores = [r['consumo_kwh'] for r in rows]
        media   = sum(valores) / len(valores)
        if media <= 0:
            return None

        varianza = sum((x - media) ** 2 for x in valores) / len(valores)
        std      = math.sqrt(varianza) if varianza > 0 else 0

        umbral_sigma  = media + 3 * std if std > 0 else float('inf')
        umbral_200pct = media * 2.0

        if consumo_kwh > umbral_sigma or consumo_kwh > umbral_200pct:
            return (
                f"Consumo anómalo detectado: {consumo_kwh:.0f} kWh vs media histórica "
                f"{media:.0f} kWh (n={len(valores)} facturas, umbral 3σ={umbral_sigma:.0f})"
            )
    except Exception as exc:
        logger.warning(f"[Validación] Error en detección de anomalía: {exc}")
    return None


def _consumo_fuera_de_limite_fisico(consumo_kwh: float, dias_facturados: int | None) -> str | None:
    """
    QW9 — Bound físico absoluto de kWh/día, independiente de la confianza OCR
    y del histórico de la sede (que es lo que ya cubre _detectar_anomalia_consumo
    y validar_con_historico). Protege contra el caso en que el OCR lee con
    ALTA confianza un número físicamente imposible — p. ej. un error de
    separador decimal que el regex igual matchea con seguridad, o donde no
    hay histórico previo de la sede con el que comparar (sede nueva).
    """
    if not consumo_kwh or not dias_facturados or dias_facturados <= 0:
        return None
    kwh_dia = consumo_kwh / dias_facturados
    limite_min = getattr(config, 'CONSUMO_KWH_DIA_MIN', 0.05)
    limite_max = getattr(config, 'CONSUMO_KWH_DIA_MAX', 10000.0)
    if kwh_dia < limite_min:
        return (f"Consumo fuera de límite físico: {kwh_dia:.3f} kWh/día "
                f"(< {limite_min} kWh/día). Revisión obligatoria.")
    if kwh_dia > limite_max:
        return (f"Consumo fuera de límite físico: {kwh_dia:.1f} kWh/día "
                f"(> {limite_max} kWh/día). Revisión obligatoria.")
    return None

def _verificar_duplicados(pais: str, sede: str, tipo_energia: str,
                           periodo_inicio: str, periodo_fin: str,
                           sha256: str, cups: str = None) -> list[str]:
    """
    Verifica si ya existe una factura con el mismo período o el mismo PDF.
    Retorna lista de advertencias (vacía si no hay duplicados).

    El CUPS forma parte de la identidad del duplicado: una sede puede tener
    varios puntos de suministro y recibir una factura por CUPS en el mismo mes.
    Esas facturas son legítimas y complementarias (su consumo se SUMA), no
    duplicados. Comparar solo por período las marcaba como duplicadas e invitaba
    a anularlas, lo que habría eliminado consumo real del cómputo de emisiones.
    """
    advertencias = []
    try:
        with get_db_connection() as conn:
            # Regla 1: duplicado por período exacto DEL MISMO punto de suministro
            if periodo_inicio and periodo_fin:
                # Si no se pudo leer el CUPS, solo se compara contra facturas que
                # tampoco lo tienen: asumir que un CUPS ilegible es "el mismo"
                # que otro reintroduciría los falsos positivos en sedes multi-CUPS.
                cond_cups = "AND cups = ?" if cups else "AND (cups IS NULL OR cups = '')"
                params = [pais, sede, tipo_energia, periodo_inicio, periodo_fin]
                if cups:
                    params.append(cups)

                dup_periodo = conn.execute(
                    f'''SELECT id FROM facturas
                        WHERE pais=? AND sede=? AND tipo_energia=?
                          AND periodo_inicio=? AND periodo_fin=?
                          AND fecha_anulacion IS NULL
                          {cond_cups}
                        LIMIT 1''',
                    params
                ).fetchone()
                if dup_periodo:
                    detalle_cups = f", CUPS {cups}" if cups else ""
                    advertencias.append(
                        f"Duplicado por período: ya existe la factura "
                        f"#{dup_periodo['id']} para {sede} "
                        f"({periodo_inicio}→{periodo_fin}{detalle_cups})"
                    )

            # Regla 2: duplicado por SHA-256 del PDF
            if sha256:
                dup_hash = conn.execute(
                    '''SELECT id FROM facturas
                       WHERE sha256_documento=? AND fecha_anulacion IS NULL
                       LIMIT 1''',
                    (sha256,)
                ).fetchone()
                if dup_hash:
                    advertencias.append(
                        f"Duplicado por contenido PDF: ya existe la factura "
                        f"#{dup_hash['id']} con el mismo archivo (SHA-256 idéntico)"
                    )
    except Exception as exc:
        logger.warning(f"[Validación] Error verificando duplicados: {exc}")
    return advertencias


def _obtener_suministro_id(pais: str, sede: str, tipo_energia: str,
                            cups: str = None) -> int | None:
    """
    Resuelve el suministro (punto de suministro) al que pertenece la factura.

    El CUPS identifica el punto de suministro: una sede con varios CUPS tiene
    varios suministros. Antes se cogía el primero de la sede con `LIMIT 1`, de
    modo que todas las facturas de la sede colgaban del mismo suministro y la
    tabla `suministros` (que ya tiene UNIQUE(sede_id, tipo_energia, referencia))
    no llegaba a distinguirlos.

    Si el CUPS no tiene todavía suministro registrado, se crea.
    """
    try:
        with get_db_connection() as conn:
            sede_row = conn.execute(
                "SELECT id FROM sedes WHERE pais_codigo=? AND nombre=?",
                (pais, sede)
            ).fetchone()
            if not sede_row:
                return None
            sede_id = sede_row['id']

            if cups:
                row = conn.execute(
                    '''SELECT id FROM suministros
                       WHERE sede_id=? AND tipo_energia=? AND referencia=?''',
                    (sede_id, tipo_energia, cups)
                ).fetchone()
                if row:
                    return row['id']

                # Alta automática del nuevo punto de suministro.
                cur = conn.execute(
                    '''INSERT INTO suministros (sede_id, tipo_energia, referencia, notas)
                       VALUES (?,?,?,?)''',
                    (sede_id, tipo_energia, cups, 'Alta automática desde factura')
                )
                logger.info(f"  Nuevo suministro registrado: {sede} ({pais}) CUPS {cups}")
                return cur.lastrowid

            # Sin CUPS legible: se usa el suministro genérico de la sede si existe.
            row = conn.execute(
                '''SELECT id FROM suministros
                   WHERE sede_id=? AND tipo_energia=?
                   ORDER BY referencia IS NOT NULL, id
                   LIMIT 1''',
                (sede_id, tipo_energia)
            ).fetchone()
            return row['id'] if row else None
    except Exception as exc:
        logger.warning(f"[Suministro] No se pudo resolver para {pais}/{sede}: {exc}")
        return None


def _indexar_documento(conn, factura_id: int, ejercicio: str,
                        pais: str, sede: str, sociedad: str,
                        mes: str, archivo_nombre: str,
                        carpeta_relativa: str, archivo_ruta: str,
                        sha256: str):
    """
    Fase 5: inserta el índice de documentos para facilitar la localización,
    detección de huecos y futura migración a SharePoint.

    Nota: la sentencia original era `INSERT OR REPLACE`, pero documentos_indice
    solo tiene como restricción única su `id` autogenerado, que nunca se aporta
    aquí. Es decir, en SQLite nunca llegaba a reemplazar nada y siempre
    insertaba una fila nueva. Se conserva ese comportamiento exacto.
    """
    try:
        conn.execute("""
            INSERT INTO documentos_indice
                (factura_id, ejercicio, pais, sede, sociedad, mes,
                 archivo_nombre, carpeta_relativa, archivo_ruta, sha256, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'disponible')
        """, (factura_id, ejercicio, pais, sede, sociedad, mes,
              archivo_nombre, carpeta_relativa, archivo_ruta, sha256))
    except Exception as exc:
        logger.warning(f"[Fase5] No se pudo indexar documento factura_id={factura_id}: {exc}")