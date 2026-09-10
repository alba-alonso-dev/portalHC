"""
Carga, validación y consulta de plantillas de comercializadora/documento
desde config/plantillas_facturas/*.yaml.

ORGANIZACIÓN EN DISCO (v4):
  Las plantillas se agrupan en un subdirectorio por código ISO de país:

      config/plantillas_facturas/
          ES/  iberdrola.yaml, endesa.yaml, ...
          AR/  edesur.yaml
          MX/  cfe.yaml
          ...

  El directorio raíz se sigue leyendo (retrocompatibilidad con instalaciones
  que aún no han migrado), pero la carga es RECURSIVA y el nombre de la carpeta
  contenedora se contrasta con el campo 'pais' del YAML: una discrepancia es un
  aviso, porque significa que el fichero está archivado donde no corresponde y
  el catálogo dejaría de ser navegable. La carpeta NUNCA sobrescribe al campo
  'pais' — la fuente de verdad sigue siendo el propio YAML.

ARQUITECTURA (v3 — multi-país):
  - La identidad de una plantilla es (pais, nombre_canonico), NO solo
    nombre_canonico. Una misma marca puede tener formato de factura distinto
    en cada país donde opera — antes esto no estaba soportado y una
    colisión de nombres entre países se resolvía de forma no determinista
    (orden alfabético de fichero).
  - categoria           : metadato libre de agrupación/reporting. NUNCA se
                           usa en lógica de extracción.
  - campos_disponibles  : contrato funcional real.
  - reglas_extraccion   : una entrada por campo (esquema v2, anidado), con
                           compatibilidad automática con el esquema v1.
  - firma.anclas_esperadas : anclas de texto para detectar cambio de formato
                           de una plantilla ya conocida (ver
                           services/firma_plantilla_service.py).

VALIDACIÓN: los bloqueos de nombre_canonico duplicado y de alias duplicado
ahora se evalúan POR PAÍS — la misma marca en dos países distintos nunca es
un conflicto; la misma marca dos veces en el MISMO país sí lo es.
"""
import logging
import os
import re
import yaml

logger = logging.getLogger(__name__)

_DIR_PLANTILLAS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'plantillas_facturas'
)

# ── Contrato de campos de plantilla ───────────────────────────────────────────
# Se distinguen DOS categorías, porque no son lo mismo y confundirlas producía
# ruido de validación y un 'campos_aplicables' engañoso en la UI:
#
#   CAMPOS_EXTRAIBLES — el pipeline de extraccion_service TIENE implementación
#       para ellos (extractor genérico y/o regla de plantilla) y alimentan
#       columnas reales de la tabla 'facturas'. Solo estos condicionan qué se
#       intenta extraer, la confianza global y el criterio de revisión.
#
#   CAMPOS_METADATO — se declaran en las plantillas porque describen lo que la
#       factura contiene, pero HOY no los consume el pipeline ni se persisten.
#       Se aceptan como válidos (no son typos) y se ignoran en la extracción.
#       Al implementar uno, basta con moverlo al conjunto de arriba.
CAMPOS_EXTRAIBLES = {
    'consumo', 'periodo', 'fecha_factura', 'cups', 'direccion', 'sociedad',
    # Se detecta SIEMPRE antes de resolver la plantilla (es lo que la elige),
    # por lo que declararlo es redundante; pero se persiste y pondera en la
    # confianza global (FIELD_WEIGHTS), así que es extraíble a todos los efectos.
    'comercializadora',
    # Datos comerciales/técnicos del contrato. Se extraen y persisten, pero no
    # intervienen en el cálculo de emisiones ni ponderan la confianza global.
    'importe', 'tarifa', 'contrato', 'potencia', 'distribuidora',
}

# Reservado para campos que una plantilla pueda declarar como presentes en la
# factura antes de que el pipeline los implemente. Se aceptan como válidos
# (no son typos) y se ignoran en la extracción hasta promoverlos arriba.
CAMPOS_METADATO: set[str] = set()

CAMPOS_CONOCIDOS = CAMPOS_EXTRAIBLES | CAMPOS_METADATO

AGREGACIONES_VALIDAS = {'primer_grupo', 'suma_grupos'}

# Orden en que la factura imprime las dos fechas del periodo. 'fin_inicio' es
# para emisores que muestran primero la lectura actual (p.ej. Edesur).
ORDENES_PERIODO_VALIDOS = {'inicio_fin', 'fin_inicio'}

_cache: dict | None = None            # clave: (pais, nombre_canonico) -> datos
_validacion_cache: list[dict] | None = None


# ── Incidencias estructuradas ─────────────────────────────────────────────

def _incidencia(gravedad: str, mensaje: str, campo: str | None = None,
                 elemento: str | None = None) -> dict:
    return {'gravedad': gravedad, 'mensaje': mensaje, 'campo': campo, 'elemento': elemento}


# ── Migración automática de esquema v1 → v2 (sin cambios respecto a antes) ─

def _migrar_esquema_v1_a_v2(datos: dict) -> dict:
    if datos.get('version_esquema', 1) >= 2:
        return datos

    reglas_v1 = datos.get('reglas_extraccion', {}) or {}
    if not reglas_v1:
        return datos

    ya_anidado = any(isinstance(v, dict) for v in reglas_v1.values())
    if ya_anidado:
        return datos

    mapeo_campo = {
        'consumo': 'patron_consumo_extra',
        'periodo': 'patron_periodo_extra',
        'cups':    'patron_cups_extra',
    }
    reglas_v2: dict = {}
    for campo, clave_patron in mapeo_campo.items():
        patron = reglas_v1.get(clave_patron)
        if not patron:
            continue
        reglas_v2[campo] = {
            'patron': patron,
            'confianza': reglas_v1.get(f'conf_{campo}_extra', 0.90),
            'agregacion': 'primer_grupo',
        }

    claves_reconocidas = set(mapeo_campo.values()) | {f'conf_{c}_extra' for c in mapeo_campo}
    resto = {k: v for k, v in reglas_v1.items() if k not in claves_reconocidas}
    if resto:
        reglas_v2['_legacy_sin_migrar'] = resto

    nuevo = dict(datos)
    nuevo['reglas_extraccion'] = reglas_v2
    return nuevo


# ── Validación estructural de una plantilla ya parseada ──────────────────
# (idéntica a la v2 — sin cambios; se muestra íntegra para que el fichero
# quede completo y copiable de una pieza)

def _validar_estructura_plantilla(nombre_fichero: str, datos: dict) -> list[dict]:
    incidencias: list[dict] = []

    if 'nombre_canonico' not in datos:
        incidencias.append(_incidencia('bloqueante',
            f"{nombre_fichero}: falta 'nombre_canonico' — plantilla ignorada.",
            elemento='plantilla'))
        return incidencias

    nombre = datos['nombre_canonico']
    pais = (datos.get('pais') or 'ES').upper()
    campos_decl = set(datos.get('campos_disponibles') or [])

    for campo in campos_decl:
        if campo not in CAMPOS_CONOCIDOS:
            incidencias.append(_incidencia('aviso',
                f"{nombre} ({pais}): campo '{campo}' en campos_disponibles no es un campo "
                f"conocido ({sorted(CAMPOS_CONOCIDOS)}) — ¿typo?"))

    # Guardrail: una lista vacía EXPLÍCITA no es lo mismo que omitir la clave.
    # Omitirla => se usan los campos por defecto. Declararla vacía dejaría el
    # conjunto de campos aplicables a cero y la factura se daría por buena sin
    # haber extraído nada (consumo 0 => emisiones 0, en silencio).
    if isinstance(datos.get('campos_disponibles'), list) and not campos_decl:
        incidencias.append(_incidencia('aviso',
            f"{nombre} ({pais}): campos_disponibles está declarado pero VACÍO — se "
            f"ignorará y se usarán los campos por defecto. Omite la clave si esa "
            f"era la intención."))
    elif campos_decl and not (campos_decl & CAMPOS_EXTRAIBLES):
        incidencias.append(_incidencia('aviso',
            f"{nombre} ({pais}): campos_disponibles solo declara metadatos "
            f"({sorted(campos_decl)}), ningún campo extraíble — se usarán los "
            f"campos por defecto para no descartar la factura en silencio."))

    reglas = datos.get('reglas_extraccion', {}) or {}
    for campo, regla in reglas.items():
        if campo == '_legacy_sin_migrar':
            continue
        if not isinstance(regla, dict):
            incidencias.append(_incidencia('bloqueante',
                f"{nombre} ({pais}): reglas_extraccion.{campo} no tiene formato esperado "
                f"(debe ser {{patron, confianza, agregacion}}).",
                campo=campo, elemento='regla'))
            continue

        patron = regla.get('patron')
        if patron:
            try:
                re.compile(patron, re.IGNORECASE)
            except re.error as e:
                incidencias.append(_incidencia('bloqueante',
                    f"{nombre} ({pais}): regex inválida en reglas_extraccion.{campo}: {e}",
                    campo=campo, elemento='regla'))
                continue

        agregacion = regla.get('agregacion', 'primer_grupo')
        if agregacion not in AGREGACIONES_VALIDAS:
            incidencias.append(_incidencia('bloqueante',
                f"{nombre} ({pais}): agregacion '{agregacion}' en reglas_extraccion.{campo} "
                f"no reconocida ({sorted(AGREGACIONES_VALIDAS)}).",
                campo=campo, elemento='regla'))
            continue

        # 'orden' solo es significativo en 'periodo' (indica que la factura
        # imprime la lectura actual antes que la anterior). Un valor mal
        # escrito se trataría como 'inicio_fin' y produciría periodos
        # invertidos que el pipeline descarta en silencio.
        orden = regla.get('orden')
        if orden is not None:
            if campo != 'periodo':
                incidencias.append(_incidencia('aviso',
                    f"{nombre} ({pais}): 'orden' en reglas_extraccion.{campo} se ignora; "
                    f"solo tiene efecto en 'periodo'."))
            elif orden not in ORDENES_PERIODO_VALIDOS:
                incidencias.append(_incidencia('bloqueante',
                    f"{nombre} ({pais}): orden '{orden}' en reglas_extraccion.{campo} "
                    f"no reconocido ({sorted(ORDENES_PERIODO_VALIDOS)}).",
                    campo=campo, elemento='regla'))

        if agregacion == 'suma_grupos' and campo in ('periodo', 'cups'):
            incidencias.append(_incidencia('aviso',
                f"{nombre} ({pais}): agregacion 'suma_grupos' en '{campo}' no tiene sentido."))

        if campos_decl and campo not in campos_decl:
            incidencias.append(_incidencia('aviso',
                f"{nombre} ({pais}): hay regla para '{campo}' pero no está en "
                f"campos_disponibles — la regla no se usará."))

    # Un campo EXTRAÍBLE sin regla ni zona no es un problema: el pipeline tiene
    # extractor genérico para todos ellos, la regla es solo un refuerzo. En
    # cambio un METADATO sin regla ni zona es letra muerta: nadie lo obtendrá.
    for campo in campos_decl:
        if campo in CAMPOS_EXTRAIBLES:
            continue
        tiene_regla = campo in reglas
        tiene_zona = campo in (datos.get('zona') or {})
        if not tiene_regla and not tiene_zona:
            incidencias.append(_incidencia('aviso',
                f"{nombre} ({pais}): '{campo}' es un metadato declarado sin regla ni "
                f"zona — no se obtendrá de ninguna forma; elimínalo o dale una regla."))

    zona = datos.get('zona', {}) or {}
    for campo, bbox in zona.items():
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            incidencias.append(_incidencia('bloqueante',
                f"{nombre} ({pais}): zona.{campo} no tiene 4 coordenadas.",
                campo=campo, elemento='zona'))
            continue
        x0, top, x1, bottom = bbox
        if not all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in bbox):
            incidencias.append(_incidencia('bloqueante',
                f"{nombre} ({pais}): zona.{campo}={bbox} fuera de rango [0,1].",
                campo=campo, elemento='zona'))
            continue
        if (x0, top, x1, bottom) == (0.0, 0.0, 0.0, 0.0):
            gravedad_bbox = 'aviso'
            if campo in campos_decl:
                incidencias.append(_incidencia(gravedad_bbox,
                    f"{nombre} ({pais}): zona.{campo}=[0,0,0,0] pero '{campo}' SÍ está en "
                    f"campos_disponibles — bbox probablemente olvidado sin rellenar."))
            else:
                incidencias.append(_incidencia(gravedad_bbox,
                    f"{nombre} ({pais}): zona.{campo}=[0,0,0,0] — si '{campo}' no aplica, "
                    f"mejor omitir la clave."))
        elif x0 >= x1 or top >= bottom:
            incidencias.append(_incidencia('bloqueante',
                f"{nombre} ({pais}): zona.{campo}={bbox} inválida (x0>=x1 o top>=bottom).",
                campo=campo, elemento='zona'))

    # Validación de firma (nuevo — opcional)
    firma = datos.get('firma', {}) or {}
    anclas = firma.get('anclas_esperadas', [])
    if anclas and not isinstance(anclas, list):
        incidencias.append(_incidencia('bloqueante',
            f"{nombre} ({pais}): firma.anclas_esperadas debe ser una lista.",
            elemento='plantilla'))
    elif anclas:
        for i, ancla in enumerate(anclas):
            if not isinstance(ancla, dict) or not ancla.get('texto'):
                incidencias.append(_incidencia('aviso',
                    f"{nombre} ({pais}): firma.anclas_esperadas[{i}] mal formada "
                    f"(debe tener al menos 'texto')."))

    return incidencias


def _purgar_elementos_bloqueantes(datos: dict, incidencias: list[dict]) -> dict:
    reglas = datos.get('reglas_extraccion', {}) or {}
    zona = datos.get('zona', {}) or {}
    for inc in incidencias:
        if inc['gravedad'] != 'bloqueante':
            continue
        if inc['elemento'] == 'regla' and inc['campo'] in reglas:
            del reglas[inc['campo']]
        elif inc['elemento'] == 'zona' and inc['campo'] in zona:
            del zona[inc['campo']]
    datos['reglas_extraccion'] = reglas
    datos['zona'] = zona
    return datos


# ── Descubrimiento de ficheros (recursivo, un subdirectorio por país) ─────

_RE_COD_PAIS = re.compile(r'^[A-Z]{2}$')


def _listar_ficheros_plantilla() -> list[tuple[str, str]]:
    """
    [(ruta_absoluta, nombre_relativo)] de todos los YAML bajo el directorio de
    plantillas, a cualquier profundidad y en orden estable.

    Se recorre en profundidad para soportar la organización por país
    (ES/, AR/, MX/…) sin romper las instalaciones que todavía tienen los
    ficheros sueltos en la raíz.
    """
    encontrados: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(_DIR_PLANTILLAS):
        # Ignorar directorios de herramientas (.idea, .git, __pycache__…)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(('.', '__')))
        for fname in sorted(filenames):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            ruta = os.path.join(dirpath, fname)
            encontrados.append((ruta, os.path.relpath(ruta, _DIR_PLANTILLAS)))
    return sorted(encontrados, key=lambda t: t[1])


def _pais_de_carpeta(ruta: str) -> str | None:
    """
    Código de país deducido del directorio contenedor, o None si el fichero
    está en la raíz (organización legacy) o la carpeta no es un código ISO.
    """
    carpeta = os.path.basename(os.path.dirname(os.path.abspath(ruta)))
    if os.path.abspath(os.path.dirname(ruta)) == os.path.abspath(_DIR_PLANTILLAS):
        return None
    carpeta = carpeta.upper()
    return carpeta if _RE_COD_PAIS.match(carpeta) else None


# ── Carga completa + validación cross-fichero (POR PAÍS) ─────────────────

def _cargar_todas() -> tuple[dict, list[dict]]:
    plantillas: dict = {}            # (pais, nombre) -> datos
    incidencias_totales: list[dict] = []

    if not os.path.isdir(_DIR_PLANTILLAS):
        logger.warning(f"[plantillas_service] Directorio no encontrado: {_DIR_PLANTILLAS}")
        return plantillas, incidencias_totales

    # Claves de cross-check AHORA incluyen el país — la misma marca en dos
    # países distintos NUNCA es una colisión.
    plantillas_por_clave: dict[tuple[str, str], list[str]] = {}
    alias_por_clave: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for ruta, fname in _listar_ficheros_plantilla():
        carpeta_pais = _pais_de_carpeta(ruta)

        try:
            with open(ruta, encoding='utf-8') as f:
                datos = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            incidencias_totales.append(_incidencia('bloqueante',
                f"{fname}: YAML inválido, plantilla IGNORADA — {exc}", elemento='plantilla'))
            continue
        except Exception as exc:
            incidencias_totales.append(_incidencia('bloqueante',
                f"{fname}: error inesperado leyendo fichero — {exc}", elemento='plantilla'))
            continue

        if not datos or 'nombre_canonico' not in datos:
            incidencias_totales.append(_incidencia('bloqueante',
                f"{fname}: sin 'nombre_canonico', plantilla IGNORADA.", elemento='plantilla'))
            continue

        datos = _migrar_esquema_v1_a_v2(datos)
        incidencias = _validar_estructura_plantilla(fname, datos)
        incidencias_totales.extend(incidencias)
        datos = _purgar_elementos_bloqueantes(datos, incidencias)

        nombre = datos['nombre_canonico']
        pais = (datos.get('pais') or 'ES').upper()
        clave = (pais, nombre)

        # El YAML manda; la carpeta solo debe reflejarlo. Si no coinciden, el
        # catálogo sigue cargando con el país correcto pero se avisa, porque
        # un fichero archivado en el país equivocado es invisible para quien
        # navegue el directorio buscando las plantillas de ese país.
        if carpeta_pais and carpeta_pais != pais:
            incidencias_totales.append(_incidencia('aviso',
                f"{fname}: está en la carpeta '{carpeta_pais}/' pero declara "
                f"pais: {pais} — muévelo a '{pais}/' o corrige el campo 'pais'.",
                elemento='plantilla'))

        plantillas_por_clave.setdefault(clave, []).append(fname)
        for patron in datos.get('patrones_deteccion', []):
            alias_por_clave.setdefault((pais, patron), []).append((nombre, fname))

        plantillas[clave] = datos

    # Cross-check 1: nombre_canonico duplicado DENTRO DEL MISMO PAÍS
    for (pais, nombre), ficheros in plantillas_por_clave.items():
        if len(ficheros) > 1:
            incidencias_totales.append(_incidencia('bloqueante',
                f"nombre_canonico '{nombre}' (país {pais}) declarado en {len(ficheros)} "
                f"ficheros distintos: {ficheros}. NINGUNO se carga — resolver manualmente.",
                elemento='plantilla'))
            plantillas.pop((pais, nombre), None)

    # Cross-check 2: alias de detección duplicado DENTRO DEL MISMO PAÍS
    # (el mismo alias en países distintos es perfectamente válido: cada país
    # tiene su propio mapa_deteccion(pais), nunca se mezclan)
    alias_bloqueados: set[tuple[str, str]] = set()
    for (pais, patron), ocurrencias in alias_por_clave.items():
        nombres_distintos = {n for n, _ in ocurrencias}
        if len(nombres_distintos) > 1:
            incidencias_totales.append(_incidencia('bloqueante',
                f"Alias '{patron}' (país {pais}) declarado para {len(nombres_distintos)} "
                f"comercializadoras distintas: {ocurrencias}. Se EXCLUYE de la detección "
                f"en {pais} hasta resolver manualmente.", elemento='plantilla'))
            alias_bloqueados.add((pais, patron))

    if alias_bloqueados:
        for (pais, _nombre), datos in plantillas.items():
            datos['patrones_deteccion'] = [
                p for p in datos.get('patrones_deteccion', [])
                if (pais, p) not in alias_bloqueados
            ]

    for inc in incidencias_totales:
        nivel = logger.error if inc['gravedad'] == 'bloqueante' else logger.warning
        prefijo = '[PLANTILLA:BLOQUEO]' if inc['gravedad'] == 'bloqueante' else '[PLANTILLA:AVISO]'
        nivel(f"{prefijo} {inc['mensaje']}")

    n_bloq = sum(1 for i in incidencias_totales if i['gravedad'] == 'bloqueante')
    n_aviso = sum(1 for i in incidencias_totales if i['gravedad'] == 'aviso')
    n_paises = len({p for p, _ in plantillas.keys()})
    logger.info(f"[plantillas_service] {len(plantillas)} plantillas activas cargadas "
                f"en {n_paises} país(es) ({n_bloq} bloqueo(s), {n_aviso} aviso(s))")

    return plantillas, incidencias_totales


# ── API pública (todas las funciones dependientes de comercializadora ─────
#     ahora requieren 'pais' como primer argumento — cambio de firma) ──────

def get_plantillas() -> dict:
    """Devuelve TODO el catálogo, clave (pais, nombre_canonico) -> datos."""
    global _cache, _validacion_cache
    if _cache is None:
        _cache, _validacion_cache = _cargar_todas()
    return _cache


def recargar_plantillas() -> dict:
    global _cache, _validacion_cache
    _cache, _validacion_cache = _cargar_todas()
    return _cache


def resumen_validacion() -> list[dict]:
    get_plantillas()
    return _validacion_cache or []


def mapa_deteccion(pais: str) -> dict:
    """
    {patron_busqueda: nombre_canonico} — SOLO para el país indicado.
    Sustituye tanto a _COMERCIALIZADORAS_ES (antes solo ES) como al antiguo
    diccionario 'mapa_otros' hardcodeado en extraccion_service.py (AR/CO/EC/MX).

    Los patrones se devuelven ordenados de más largo a más corto para que el
    más específico gane siempre: si 'EDES' se evaluara antes que 'EDESUR',
    toda factura de EDESUR se atribuiría a la comercializadora equivocada.
    Se garantiza aquí, en la fuente, para que lo hereden todos los llamadores.
    """
    pais = (pais or 'ES').upper()
    resultado = {}
    for (p, nombre), datos in get_plantillas().items():
        if p != pais:
            continue
        for patron in datos.get('patrones_deteccion', []):
            resultado[patron] = nombre
    return {k: resultado[k] for k in sorted(resultado, key=len, reverse=True)}


def campos_disponibles(pais: str, nombre_comercializadora: str) -> list[str] | None:
    p = get_plantillas().get(((pais or 'ES').upper(), nombre_comercializadora))
    return (p or {}).get('campos_disponibles')


def categoria(pais: str, nombre_comercializadora: str) -> str | None:
    p = get_plantillas().get(((pais or 'ES').upper(), nombre_comercializadora))
    return (p or {}).get('categoria')


def regla_extraccion_campo(pais: str, nombre_comercializadora: str, campo: str) -> dict | None:
    p = get_plantillas().get(((pais or 'ES').upper(), nombre_comercializadora))
    reglas = (p or {}).get('reglas_extraccion', {})
    return reglas.get(campo)


def zonas(pais: str, nombre_comercializadora: str) -> dict:
    p = get_plantillas().get(((pais or 'ES').upper(), nombre_comercializadora))
    zona_dict = (p or {}).get('zona')
    if not zona_dict:
        return {}
    return {campo: tuple(coords) for campo, coords in zona_dict.items()}


def firma(pais: str, nombre_comercializadora: str) -> dict:
    p = get_plantillas().get(((pais or 'ES').upper(), nombre_comercializadora))
    return (p or {}).get('firma', {})