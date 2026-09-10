"""
Blueprint: operaciones sobre facturas individuales y procesamiento en lote.

Endpoints:
  POST  /api/procesar              — factura individual (retrocompatible)
  POST  /api/procesar-lote         — lote de facturas (nuevo Fase 1)
  GET   /api/lote/<id>/estado      — polling de progreso del lote
  GET   /api/factura/<id>          — detalle completo de una factura (nuevo)
  GET   /api/factura/<id>/pdf      — servir PDF (usa DocumentoStorage)
  POST  /api/factura/<id>/confirmar — confirmar/corregir datos extraídos
  GET   /api/historial             — listado paginado con nuevos campos
  DELETE /api/factura/<id>         — soft-delete con audit log

Cambios arquitectónicos:
  P1 — Almacenamiento de PDFs delegado a DocumentoStorage.
  P2 — Audit log en carga, confirmación, anulación y descarga de PDF.
  P3 — Historial de cambios campo a campo en confirmar_factura.
  P6 — Validación de tipos e integridad antes del UPDATE en confirmar_factura.
"""

import json
import logging
import pathlib
from datetime import date

from flask import Blueprint, jsonify, request, send_file, redirect

from database.connection import get_db_connection
from database.migrations_campos_factura import moneda_de_pais
from routes._helpers import bad_request
from services.documento_service import get_documento_storage
from services.emisiones_service import calcular_emisiones
from services.numeros import kwh_a_mwh
from services.ocr_quality_service import recalcular_confianza_global
from services.validacion_service import validar_limite_fisico_consumo
from services.lote_service import (crear_lote, obtener_estado_lote,
                                    procesar_lote_async, procesar_factura_individual)
from services.audit_service import (
    registrar_evento, registrar_cambio_factura,
    ACCION_FACTURA_CONFIRMADA, ACCION_FACTURA_ANULADA, ACCION_PDF_DESCARGADO,
)
import config

logger = logging.getLogger(__name__)

facturas_bp = Blueprint('facturas', __name__)

# Columna de la tabla `facturas` → clave de `campos_confianza`.
#
# La confianza de un campo la fija la regla del YAML de la plantilla
# (`confianza: 0.90`) o, si no hay regla, el valor por defecto del extractor
# genérico. Es una estimación de lo fiable que es la LECTURA AUTOMÁTICA.
# Cuando una persona corrige el campo a mano en la pantalla de revisión esa
# estimación deja de tener sentido: el valor ya no viene de un patrón, viene
# de alguien que ha mirado el PDF. Por eso se sube a 1.0.
#
# Varias columnas comparten clave (las tres del período) porque la confianza
# se mide por concepto extraído, no por columna.
CAMPO_A_CONFIANZA = {
    'periodo_inicio':      'periodo',
    'periodo_fin':         'periodo',
    'dias_facturados':     'periodo',
    'fecha_factura':       'fecha_factura',
    'sociedad':            'sociedad',
    'direccion_suministro': 'direccion',
    'consumo_kwh':         'consumo',
    'importe_total':       'importe',
    'tarifa':              'tarifa',
    'contrato':            'contrato',
    'potencia_kw':         'potencia',
    'distribuidora':       'distribuidora',
}

# Un dato tecleado por una persona que está viendo la factura es la mejor
# fuente disponible: no hay nada más fiable contra lo que contrastarlo.
CONFIANZA_CORRECCION_MANUAL = 1.0

# Los campos corregibles son exactamente los que tienen mapeo de confianza.
# Derivarlo en vez de mantener dos listas evita el fallo silencioso de añadir
# un campo corregible y olvidar su clave: se corregiría a mano sin que la
# confianza dejase nunca de reflejar la lectura automática.
CAMPOS_CONFIRMABLES = frozenset(CAMPO_A_CONFIANZA)


def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'


# ── Factura individual ───────────────────────────────────────────────────────

@facturas_bp.route('/api/procesar', methods=['POST'])
def procesar_factura():
    """Procesa un único PDF de forma síncrona (compatible con v1)."""
    if 'archivo' not in request.files:
        return jsonify({'exito': False, 'error': 'No se subió archivo'}), 400

    archivo = request.files['archivo']
    pais    = request.form.get('pais', '').upper()
    sede    = request.form.get('sede', '')
    usuario = request.form.get('usuario', 'usuario')

    if not _allowed(archivo.filename):
        return jsonify({'exito': False, 'error': 'Solo se aceptan PDFs'}), 400
    if not pais or not sede:
        return jsonify({'exito': False, 'error': 'País y sede son obligatorios'}), 400

    # P1: delegar almacenamiento al storage
    storage  = get_documento_storage()
    doc_info = storage.guardar(archivo, archivo.filename, pais, sede)

    try:
        res = procesar_factura_individual(
            doc_info['archivo_ruta'], doc_info['archivo_nombre'],
            pais, sede, lote_id=None,
            doc_info=doc_info,
            usuario=usuario,
            ip_origen=request.remote_addr,
        )
    except ValueError as exc:
        return bad_request(exc, contexto="Facturas procesar individual")
    except Exception as exc:
        logger.error(f"Error procesando factura individual: {exc}")
        return jsonify({'exito': False, 'error': f'Error servidor: {exc}'}), 500

    return jsonify({
        'exito':             True,
        'factura_id':        res['factura_id'],
        'requiere_revision': res['requiere_revision'],
        'campos_a_revisar':  res['campos_a_revisar'],
        'advertencias':      res.get('advertencias', []),
        'resumen':           res['resumen'],
    }), 200


# ── Lote ────────────────────────────────────────────────────────────────────

@facturas_bp.route('/api/procesar-lote', methods=['POST'])
def procesar_lote():
    """
    Recibe N PDFs, los almacena vía DocumentoStorage y lanza el procesamiento
    en background. Devuelve lote_id inmediatamente para polling.
    """
    pais    = request.form.get('pais', '').upper()
    sede    = request.form.get('sede', '')
    usuario = request.form.get('usuario', 'usuario')
    sociedad_manual = (request.form.get('sociedad') or '').strip() or None

    if not pais or not sede:
        return jsonify({'exito': False, 'error': 'País y sede son obligatorios'}), 400

    archivos = request.files.getlist('archivos[]')
    pdfs = [f for f in archivos if f and _allowed(f.filename)]
    if not pdfs:
        return jsonify({'exito': False, 'error': 'No se recibieron PDFs válidos'}), 400

    # P1: guardar cada archivo vía storage y recopilar doc_info
    storage = get_documento_storage()
    archivos_guardados = []
    for f in pdfs:
        doc_info = storage.guardar(f, f.filename, pais, sede)
        archivos_guardados.append({
            'nombre_original': doc_info['archivo_nombre'],
            'ruta':            doc_info['archivo_ruta'],
            'doc_info':        doc_info,
        })

    lote_id = crear_lote(len(archivos_guardados))
    procesar_lote_async(lote_id, archivos_guardados, pais, sede,
                        usuario=usuario, ip_origen=request.remote_addr,
                        sociedad_manual=sociedad_manual)

    return jsonify({
        'exito':          True,
        'lote_id':        lote_id,
        'total_archivos': len(archivos_guardados),
        'mensaje':        f'Procesamiento iniciado para {len(archivos_guardados)} factura(s)',
    }), 202


@facturas_bp.route('/api/lote/<lote_id>/estado')
def estado_lote(lote_id):
    """Polling: devuelve progreso y resultados parciales del lote."""
    estado = obtener_estado_lote(lote_id)
    if not estado:
        return jsonify({'exito': False, 'error': 'Lote no encontrado'}), 404
    return jsonify(estado), 200


# ── Detalle de factura (nuevo endpoint) ────────────────────────────────────

@facturas_bp.route('/api/factura/<int:factura_id>', methods=['GET'])
def detalle_factura(factura_id):
    """Devuelve el detalle completo de una factura, incluyendo factor y recálculos."""
    with get_db_connection() as conn:
        row = conn.execute(
            '''SELECT f.*,
                      fe.factor_kg_co2_mwh AS factor_activo_kg_co2_mwh,
                      fe.version AS factor_version,
                      COALESCE(fu.nombre, fe.fuente) AS fuente_factor_nombre
               FROM facturas f
               LEFT JOIN factores_emision fe ON fe.id = f.factor_version_id
               LEFT JOIN fuentes_emision fu ON fu.id = fe.fuente_id
               WHERE f.id = ?''',
            (factura_id,)
        ).fetchone()
    if not row:
        return jsonify({'exito': False, 'error': 'Factura no encontrada'}), 404
    return jsonify({'exito': True, 'factura': dict(row)}), 200


# ── Servir PDF ────────────────────────────────────────────────────────────

@facturas_bp.route('/api/factura/<int:factura_id>/pdf')
def servir_pdf(factura_id):
    """
    Sirve el PDF de la factura.
    P1: Usa DocumentoStorage.resolver_acceso() para soportar local y SharePoint.
    P2: Registra descarga en audit_log.
    """
    from flask import abort
    usuario = request.args.get('usuario', 'anonimo')

    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT archivo_ruta, external_source, external_doc_url FROM facturas WHERE id = ?',
            (factura_id,)
        ).fetchone()

    if not row:
        abort(404)

    storage     = get_documento_storage()
    resolucion  = storage.resolver_acceso(dict(row))

    registrar_evento(
        accion=ACCION_PDF_DESCARGADO,
        usuario=usuario,
        entidad='factura',
        entidad_id=factura_id,
        ip_origen=request.remote_addr,
    )

    if resolucion['tipo'] == 'local':
        ruta = pathlib.Path(resolucion['valor'])
        # Seguridad: solo servir ficheros dentro de la carpeta uploads
        uploads_dir = pathlib.Path(config.UPLOAD_FOLDER).resolve()
        try:
            ruta.resolve().relative_to(uploads_dir)
        except ValueError:
            abort(403)
        if not ruta.exists():
            abort(404)
        return send_file(str(ruta), mimetype='application/pdf')

    elif resolucion['tipo'] == 'redirect':
        return redirect(resolucion['valor'])

    abort(404)


# ── Confirmación y corrección de datos ────────────────────────────────────

def _aplicar_confianza_manual(conn, factura_id, campos_corregidos, updates):
    """Marca como verificados los campos que una persona ha corregido a mano.

    Añade a `updates` la nueva `campos_confianza` (JSON por campo) y la
    `confianza_ocr` global recalculada, para que salgan en el mismo UPDATE que
    los datos corregidos y no puedan quedar desincronizadas con ellos.
    """
    fila = conn.execute(
        'SELECT campos_confianza FROM facturas WHERE id = ?', (factura_id,)
    ).fetchone()

    conf = {}
    if fila and fila['campos_confianza']:
        try:
            cargado = json.loads(fila['campos_confianza'])
            if isinstance(cargado, dict):
                conf = cargado
        except (ValueError, TypeError):
            # Una factura antigua con el JSON corrupto no debe impedir
            # confirmarla; se reconstruye la confianza desde lo que sí sabemos.
            logger.warning('campos_confianza ilegible en factura %s; se reinicia',
                           factura_id)

    for clave in campos_corregidos:
        conf[clave] = CONFIANZA_CORRECCION_MANUAL

    # None es el centinela de "este campo no aplica a esta plantilla" (lo pone
    # el pipeline). Esos campos no entran en el reparto de pesos: si no se
    # excluyesen, un CUPS inexistente en una factura de México penalizaría la
    # confianza global de esa factura.
    aplicables = {campo for campo, valor in conf.items() if valor is not None}

    updates['campos_confianza'] = json.dumps(conf, ensure_ascii=False)
    updates['confianza_ocr'] = recalcular_confianza_global(
        conf, campos_aplicables=aplicables
    )


@facturas_bp.route('/api/factura/<int:factura_id>/confirmar', methods=['POST'])
def confirmar_factura(factura_id):
    """
    Permite corregir campos extraídos con baja confianza antes de confirmar.

    P3: Registra cada campo modificado en facturas_historial (valor antes/después).
    P6: Valida tipos e integridad antes del UPDATE.
    P2: Registra acción en audit_log.
    """
    data = request.get_json(silent=True) or {}
    usuario = data.get('usuario', 'usuario')
    motivo  = data.get('motivo', 'Confirmación manual')

    # Campos corregibles: CAMPOS_CONFIRMABLES (constante de módulo).
    # Incluye 'consumo_kwh', el ÚNICO corregible que entra en el cálculo de
    # emisiones. Se admite porque el objetivo de esta pantalla es confirmar que
    # la extracción es correcta, y el consumo es justo el dato a confirmar; al
    # aceptarlo hay que recalcular consumo_mwh y emisiones_tco2e (más abajo),
    # porque guardar un consumo corregido junto a las emisiones antiguas
    # dejaría la factura internamente incoherente.
    # 'moneda' NO se expone: se deriva del país; dejar que se teclee libremente
    # reintroduciría el problema que evita tenerla.
    updates = {k: v for k, v in data.items()
               if k in CAMPOS_CONFIRMABLES and v is not None}

    # P6: validar tipos e integridad antes del UPDATE
    errores = _validar_campos_confirmar(updates)
    if errores:
        return jsonify({'exito': False, 'errores': errores}), 400

    # Calcular días si se dan inicio y fin pero no días
    if ('periodo_inicio' in updates and 'periodo_fin' in updates
            and 'dias_facturados' not in updates):
        try:
            ini = date.fromisoformat(updates['periodo_inicio'])
            fin = date.fromisoformat(updates['periodo_fin'])
            updates['dias_facturados'] = (fin - ini).days + 1
        except Exception:
            pass

    if not updates:
        return jsonify({'exito': False, 'error': 'No se proporcionaron campos válidos'}), 400

    with get_db_connection() as conn:
        # Si se corrige el consumo a mano hay que rehacer el cálculo de
        # emisiones con el mismo criterio que el pipeline: el año del factor
        # sale del período (o de la fecha de factura), no de hoy. Se usan los
        # valores ya corregidos en esta misma petición si los hay.
        if 'consumo_kwh' in updates:
            fila_ctx = conn.execute(
                'SELECT pais, periodo_inicio, fecha_factura FROM facturas WHERE id = ?',
                (factura_id,)
            ).fetchone()
            if not fila_ctx:
                return jsonify({'exito': False, 'error': 'Factura no encontrada'}), 404

            periodo_ini = updates.get('periodo_inicio') or fila_ctx['periodo_inicio']
            fecha_fac   = updates.get('fecha_factura')  or fila_ctx['fecha_factura']
            anio = (periodo_ini or fecha_fac or '')[:4] or str(date.today().year)

            consumo_mwh = kwh_a_mwh(float(updates['consumo_kwh']))
            emisiones, factor, _fuente, factor_version_id = calcular_emisiones(
                consumo_mwh, fila_ctx['pais'], anio
            )
            if emisiones is None:
                return jsonify({
                    'exito': False,
                    'error': f"Factor de emisión no disponible para "
                             f"{fila_ctx['pais']}/{anio}; no se puede recalcular",
                }), 400

            updates['consumo_mwh']       = consumo_mwh
            updates['emisiones_tco2e']   = emisiones
            updates['factor_emision']    = factor
            updates['factor_version_id'] = factor_version_id

        # Si se corrige el importe a mano, la divisa debe acompañarlo. Se deriva
        # del país de la factura en vez de aceptarla del cliente: un importe sin
        # moneda (o con una moneda tecleada a capricho) no es agregable.
        if 'importe_total' in updates:
            fila_pais = conn.execute(
                'SELECT pais FROM facturas WHERE id = ?', (factura_id,)
            ).fetchone()
            if fila_pais:
                updates['moneda'] = moneda_de_pais(fila_pais['pais'])

        # Leer valores actuales para el historial (P3)
        fila_actual = conn.execute(
            f"SELECT {', '.join(updates.keys())} FROM facturas WHERE id = ?",
            (factura_id,)
        ).fetchone()
        if not fila_actual:
            return jsonify({'exito': False, 'error': 'Factura no encontrada'}), 404

        # Registrar historial campo a campo
        campos_corregidos = set()
        for campo, nuevo_valor in updates.items():
            valor_anterior = fila_actual[campo]
            if str(valor_anterior) != str(nuevo_valor):
                registrar_cambio_factura(
                    conn, factura_id, campo,
                    valor_anterior, nuevo_valor,
                    usuario=usuario, motivo=motivo,
                )
                # Solo cuenta como corrección manual si el valor CAMBIA. Abrir
                # el modal y guardar sin tocar nada no convierte una lectura
                # dudosa en un dato verificado, así que no infla la confianza.
                clave = CAMPO_A_CONFIANZA.get(campo)
                if clave:
                    campos_corregidos.add(clave)

        if campos_corregidos:
            _aplicar_confianza_manual(conn, factura_id, campos_corregidos, updates)

        # Ejecutar UPDATE
        set_clause = ', '.join(f'{k} = ?' for k in updates)
        updates['estado'] = 'confirmada'
        set_clause += ', estado = ?'
        valores = list(updates.values()) + [factura_id]

        affected = conn.execute(
            f'UPDATE facturas SET {set_clause} WHERE id = ?', valores
        ).rowcount

    if affected == 0:
        return jsonify({'exito': False, 'error': 'Factura no encontrada'}), 404

    registrar_evento(
        accion=ACCION_FACTURA_CONFIRMADA,
        usuario=usuario,
        entidad='factura',
        entidad_id=factura_id,
        detalle={'campos_modificados': list(updates.keys()), 'motivo': motivo},
        ip_origen=request.remote_addr,
    )

    return jsonify({
        'exito':      True,
        'factura_id': factura_id,
        'mensaje':    'Datos confirmados y guardados correctamente',
        # Devueltos para que la UI pueda mostrar la confianza ya actualizada
        # sin tener que releer la factura.
        'campos_verificados': sorted(campos_corregidos),
        'confianza_ocr':      updates.get('confianza_ocr'),
    }), 200


def _validar_campos_confirmar(data: dict) -> list[str]:
    """
    Validaciones de integridad para confirmar_factura (P6).
    Retorna lista de mensajes de error; vacía si todo es correcto.
    """
    errores = []

    # Validar formato ISO en campos de fecha
    for campo_fecha in ('periodo_inicio', 'periodo_fin', 'fecha_factura'):
        if campo_fecha in data and data[campo_fecha]:
            try:
                date.fromisoformat(str(data[campo_fecha]))
            except ValueError:
                errores.append(
                    f"Fecha inválida en '{campo_fecha}': '{data[campo_fecha]}'. "
                    "Use formato YYYY-MM-DD."
                )

    # Validar coherencia de período
    if 'periodo_inicio' in data and 'periodo_fin' in data:
        try:
            ini = date.fromisoformat(str(data['periodo_inicio']))
            fin = date.fromisoformat(str(data['periodo_fin']))
            if ini > fin:
                errores.append(
                    f"periodo_inicio ({data['periodo_inicio']}) "
                    f"no puede ser posterior a periodo_fin ({data['periodo_fin']})"
                )
        except (ValueError, TypeError):
            pass  # ya detectado arriba

    # Validar dias_facturados
    if 'dias_facturados' in data:
        try:
            dias = int(data['dias_facturados'])
            if dias <= 0 or dias > 366:
                errores.append(
                    f"dias_facturados debe ser un entero entre 1 y 366 (recibido: {dias})"
                )
        except (ValueError, TypeError):
            errores.append(
                f"dias_facturados debe ser un entero (recibido: {data['dias_facturados']!r})"
            )

    # Validar longitud de strings
    for campo_str in ('sociedad', 'direccion_suministro'):
        if campo_str in data and data[campo_str]:
            if len(str(data[campo_str])) > 200:
                errores.append(f"'{campo_str}' excede el máximo de 200 caracteres")

    for campo_str, maximo in (('tarifa', 20), ('contrato', 60), ('distribuidora', 120)):
        if campo_str in data and data[campo_str]:
            if len(str(data[campo_str])) > maximo:
                errores.append(f"'{campo_str}' excede el máximo de {maximo} caracteres")

    # Validar numéricos comerciales. Se aplican las mismas cotas de cordura que
    # en la extracción automática: no tendría sentido rechazar por OCR un valor
    # y aceptarlo por corrección manual.
    for campo_num, minimo, maximo in (
        ('importe_total', 0, 10_000_000),
        ('potencia_kw',   0, 100_000),
        ('consumo_kwh',   0, 100_000_000),
    ):
        if campo_num in data and data[campo_num] is not None:
            try:
                valor = float(data[campo_num])
            except (ValueError, TypeError):
                errores.append(
                    f"'{campo_num}' debe ser numérico (recibido: {data[campo_num]!r})"
                )
                continue
            if not (minimo < valor <= maximo):
                errores.append(
                    f"'{campo_num}' debe estar entre {minimo} y {maximo} (recibido: {valor})"
                )

    # Mismo bound físico de kWh/día que aplica el pipeline (QW9). Corregir el
    # consumo a mano no debe poder colar un valor que la extracción automática
    # habría vetado por imposible.
    if 'consumo_kwh' in data and data.get('dias_facturados'):
        try:
            incidencia = validar_limite_fisico_consumo(
                float(data['consumo_kwh']), int(data['dias_facturados'])
            )
            if incidencia:
                errores.append(incidencia['mensaje'])
        except (ValueError, TypeError):
            pass  # el error de tipo ya se ha reportado arriba

    return errores


# ── Historial de cambios campo a campo (facturas_historial) ──────────────────

@facturas_bp.route('/api/factura/<int:factura_id>/historial-cambios')
def historial_cambios_factura(factura_id):
    """
    Devuelve el historial completo de modificaciones manuales de una factura,
    registradas en facturas_historial por confirmar_factura.

    Útil para auditorías CSRD: "¿quién cambió qué campo y cuándo?"
    """
    with get_db_connection() as conn:
        # Verificar que la factura existe
        existe = conn.execute(
            'SELECT id FROM facturas WHERE id = ?', (factura_id,)
        ).fetchone()
        if not existe:
            return jsonify({'exito': False, 'error': 'Factura no encontrada'}), 404

        filas = conn.execute(
            '''SELECT campo, valor_anterior, valor_nuevo, usuario,
                      fecha_cambio, motivo
               FROM facturas_historial
               WHERE factura_id = ?
               ORDER BY fecha_cambio ASC''',
            (factura_id,)
        ).fetchall()

    return jsonify({
        'exito':      True,
        'factura_id': factura_id,
        'total':      len(filas),
        'historial':  [dict(r) for r in filas],
    }), 200


# ── Historial ────────────────────────────────────────────────────────────────

@facturas_bp.route('/api/historial')
def obtener_historial():
    """
    Historial paginado. Solo incluye facturas activas (sin anuladas).
    Query params: pais, sede, anio, page (1-based), per_page (max 200).
    """
    pais     = request.args.get('pais', '').upper() or None
    sede     = request.args.get('sede') or None
    anio     = request.args.get('anio') or None
    page     = max(1, int(request.args.get('page', 1)))
    per_page = min(max(1, int(request.args.get('per_page', 50))), 200)
    offset   = (page - 1) * per_page

    condiciones: list[str] = ['fecha_anulacion IS NULL']
    params: list = []

    if pais:
        condiciones.append('pais = ?'); params.append(pais)
    if sede:
        condiciones.append('sede = ?'); params.append(sede)
    if anio:
        condiciones.append(
            "(strftime('%Y', periodo_inicio) = ? OR strftime('%Y', fecha_carga) = ?)"
        )
        params.extend([anio, anio])

    where = f"WHERE {' AND '.join(condiciones)}"

    with get_db_connection() as conn:
        total = conn.execute(
            f'SELECT COUNT(*) FROM facturas {where}', params
        ).fetchone()[0]

        filas = conn.execute(
            f'''SELECT id, pais, sede, sociedad, comercializadora,
                       direccion_suministro, fecha_factura,
                       periodo_inicio, periodo_fin, dias_facturados,
                       consumo_kwh, consumo_mwh,
                       factor_emision, emisiones_tco2e,
                       importe_total, moneda, tarifa, contrato,
                       potencia_kw, distribuidora,
                       estado, archivo_nombre, fecha_carga, confianza_ocr,
                       duplicado_potencial, tipo_dato
                FROM facturas {where}
                ORDER BY fecha_carga DESC
                LIMIT ? OFFSET ?''',
            params + [per_page, offset]
        ).fetchall()

    return jsonify({
        'historial': [dict(row) for row in filas],
        'total':     total,
        'page':      page,
        'per_page':  per_page,
    }), 200


# ── Consumo mensual agregado por sede (suma de CUPS) ────────────────────────

@facturas_bp.route('/api/consumo-mensual')
def consumo_mensual():
    """
    Consumo mensual por sede, sumando todos sus puntos de suministro (CUPS).

    Una sede puede tener varios CUPS y recibir una factura por cada uno en el
    mismo mes: el consumo del mes es la suma de todas ellas. Este endpoint
    devuelve ese total junto al desglose por CUPS, para poder comprobar que
    ninguna factura se ha quedado fuera del cómputo.

    Query params: pais, sede, anio.
    """
    pais = request.args.get('pais', '').upper() or None
    sede = request.args.get('sede') or None
    anio = request.args.get('anio') or None

    condiciones = ['fecha_anulacion IS NULL', 'periodo_inicio IS NOT NULL']
    params: list = []
    if pais:
        condiciones.append('pais = ?'); params.append(pais)
    if sede:
        condiciones.append('sede = ?'); params.append(sede)
    if anio:
        condiciones.append("substr(periodo_inicio,1,4) = ?"); params.append(anio)

    where = f"WHERE {' AND '.join(condiciones)}"

    with get_db_connection() as conn:
        filas = conn.execute(
            f'''SELECT id, pais, sede, sociedad, cups, archivo_nombre,
                       substr(periodo_inicio,1,7) AS mes,
                       periodo_inicio, periodo_fin, dias_facturados,
                       consumo_kwh, consumo_mwh, emisiones_tco2e
                FROM facturas {where}
                ORDER BY pais, sede, mes, cups''',
            params
        ).fetchall()

    # Agrupa en memoria: el volumen por sede/año es pequeño y así el desglose
    # por CUPS viaja junto a su total sin una segunda consulta.
    grupos: dict = {}
    for f in filas:
        clave = (f['pais'], f['sede'], f['mes'])
        g = grupos.setdefault(clave, {
            'pais': f['pais'], 'sede': f['sede'], 'mes': f['mes'],
            'consumo_kwh': 0.0, 'consumo_mwh': 0.0, 'emisiones_tco2e': 0.0,
            'sociedades': [], 'detalle': [],
        })
        g['consumo_kwh']     += f['consumo_kwh'] or 0.0
        g['consumo_mwh']     += f['consumo_mwh'] or 0.0
        g['emisiones_tco2e'] += f['emisiones_tco2e'] or 0.0
        if f['sociedad'] and f['sociedad'] not in g['sociedades']:
            g['sociedades'].append(f['sociedad'])
        g['detalle'].append({
            'id': f['id'], 'cups': f['cups'], 'sociedad': f['sociedad'],
            'archivo_nombre': f['archivo_nombre'],
            'periodo_inicio': f['periodo_inicio'], 'periodo_fin': f['periodo_fin'],
            'dias_facturados': f['dias_facturados'],
            'consumo_kwh': f['consumo_kwh'], 'emisiones_tco2e': f['emisiones_tco2e'],
        })

    meses = []
    for g in grupos.values():
        cups_distintos = {d['cups'] for d in g['detalle'] if d['cups']}
        g['consumo_kwh']     = round(g['consumo_kwh'], 2)
        g['consumo_mwh']     = round(g['consumo_mwh'], 4)
        g['emisiones_tco2e'] = round(g['emisiones_tco2e'], 4)
        g['n_facturas']      = len(g['detalle'])
        g['n_cups']          = len(cups_distintos)
        g['multi_cups']      = len(cups_distintos) > 1
        meses.append(g)

    meses.sort(key=lambda g: (g['pais'], g['sede'], g['mes']))

    return jsonify({
        'meses':            meses,
        'total_meses':      len(meses),
        'meses_multi_cups': sum(1 for g in meses if g['multi_cups']),
    }), 200


# ── Eliminar registro (soft-delete) ─────────────────────────────────────────

@facturas_bp.route('/api/factura/<int:factura_id>', methods=['DELETE'])
def eliminar_factura(factura_id):
    """
    Soft delete: marca la factura como anulada sin borrar el registro.
    P2: Registra en audit_log quién la anuló y cuándo.
    """
    data    = request.get_json(silent=True) or {}
    usuario = data.get('usuario', 'usuario')
    motivo  = data.get('motivo', '')

    with get_db_connection() as conn:
        affected = conn.execute(
            "UPDATE facturas SET estado='anulada', fecha_anulacion=CURRENT_TIMESTAMP "
            "WHERE id=? AND fecha_anulacion IS NULL",
            (factura_id,)
        ).rowcount

    if affected == 0:
        return jsonify({'exito': False, 'error': 'Factura no encontrada o ya anulada'}), 404

    registrar_evento(
        accion=ACCION_FACTURA_ANULADA,
        usuario=usuario,
        entidad='factura',
        entidad_id=factura_id,
        detalle={'motivo': motivo},
        ip_origen=request.remote_addr,
    )

    return jsonify({'exito': True, 'mensaje': f'Factura {factura_id} anulada'}), 200
