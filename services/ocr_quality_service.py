"""
Servicios de calidad OCR:
  - Confianza global derivada de confianza por campo
  - Validaciones históricas por sede
  - Detección y registro estructurado de incidencias
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime
import unicodedata

import config  # QW5


def _normalizar_texto(s: str) -> str:
    """Uppercase sin tildes ni espacios extra, para comparación robusta.

    Así "Edesur", "EDESUR", "Edénor" y "EDENOR" coinciden entre sí.
    """
    if not s:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(s))
    sin_tildes = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sin_tildes.upper().strip()


# ── Comercializadoras conocidas por país ─────────────────────────────────────
# Combina config.COMERCIALIZADORAS (semilla por país) con marcas adicionales
# que aparecen en facturas reales pero no en el catálogo de config.
# El check de "comercializadora no reconocida" usa el set DEL PAÍS de la
# factura, no el global: así "Edesur" (AR) no penaliza en Argentina aunque
# no sea una comercializadora española.
_MARCAS_ADICIONALES_ES = {
    "NATURGY",       # marca de Naturgas
    "REPSOL",
    "TOTALENERGIES",
    "PLENITUDE",     # marca de Eni
    "HOLALUZ",
    "OCTOPUS",
    "ACCIONA",
    "FACTOR ENERGIA",
    "AUDAX",
    "NEXUS",
}


def _construir_comercializadoras_por_pais() -> dict[str, set[str]]:
    """Construye {pais: {nombres normalizados}} desde config + marcas extra."""
    resultado: dict[str, set[str]] = {}
    for pais, lista in getattr(config, 'COMERCIALIZADORAS', {}).items():
        resultado[pais] = {_normalizar_texto(n) for n in lista}
    # Añadir marcas adicionales de España que no están en config
    resultado.setdefault("ES", set())
    resultado["ES"] |= _MARCAS_ADICIONALES_ES
    return resultado


KNOWN_COMERCIALIZADORAS_BY_PAIS: dict[str, set[str]] = _construir_comercializadoras_por_pais()

# Set plano (todos los países) — retrocompatible con código que lo use directo.
KNOWN_COMERCIALIZADORAS: set[str] = set().union(*KNOWN_COMERCIALIZADORAS_BY_PAIS.values()) if KNOWN_COMERCIALIZADORAS_BY_PAIS else set()

FIELD_WEIGHTS = {
    "consumo": 0.27,
    "periodo": 0.23,
    "fecha_factura": 0.11,
    "cups": 0.13,
    "comercializadora": 0.10,
    "direccion": 0.06,
    "sociedad": 0.06,
    "sede": 0.04,
}

REQUIRED_FIELDS = (
    "consumo",
    "periodo",
    "fecha_factura",
    "cups",
    "comercializadora",
    "direccion",
    "sociedad",
    "sede",
)


def recalcular_confianza_global(confianza_por_campo: dict,
                                 campos_aplicables: set[str] | None = None) -> float:
    """
    Si campos_aplicables es None: comportamiento legacy, se usan todos los
    FIELD_WEIGHTS tal cual (retrocompatible con plantillas sin
    campos_disponibles declarado, o con llamadas antiguas al método).

    Si se pasa campos_aplicables: los pesos se RENORMALIZAN solo sobre esos
    campos (+ 'sede', que siempre aplica porque viene del formulario de
    carga, no de la extracción). Un campo estructuralmente no aplicable
    (p.ej. CUPS en un documento de repercusión) no penaliza la confianza
    global — antes sí lo hacía, de forma injusta.
    """
    pesos = FIELD_WEIGHTS
    if campos_aplicables is not None:
        campos_efectivos = campos_aplicables | {'sede'}
        pesos = {c: p for c, p in FIELD_WEIGHTS.items() if c in campos_efectivos}
        suma_pesos = sum(pesos.values()) or 1.0
        pesos = {c: p / suma_pesos for c, p in pesos.items()}

    total = 0.0
    for campo, peso in pesos.items():
        valor = confianza_por_campo.get(campo)
        if valor is None:
            continue  # None = campo no aplicable, no penaliza
        total += float(valor) * peso
    return round(total, 3)

def normalizar_cups(cups: str | None) -> str | None:
    if not cups:
        return None
    normalizado = re.sub(r"[^A-Za-z0-9]", "", str(cups)).upper()
    return normalizado or None

# NOTA: el algoritmo de abajo es el estándar publicado (mod 529, mismo 
# alfabeto de 23 letras que el dígito de control del DNI/NIE). Validadlo 
# una muestra de CUPS reales conocidos antes de activarlo en modo 
# bloqueante — por eso se añade con un flag verificar_digito_control 
# que por defecto es False (modo "solo disponible", no activo)

# QW6 — Tabla de letras de control CUPS. Mismo alfabeto de 23 letras que el
# dígito de control del DNI/NIE español. Verificar con vectores de prueba
# reales antes de depender de esto en modo bloqueante (ver nota arriba).
_TABLA_LETRAS_CONTROL_CUPS = "TRWAGMYFPDXBNJZSQVHLCKE"


def calcular_digito_control_cups(cuerpo_16_digitos: str) -> str | None:
    """
    Calcula las 2 letras de control de un CUPS a partir de su cuerpo numérico
    de 16 dígitos (posiciones 3-18 del CUPS, justo tras 'ES').
    Algoritmo: N mod 529 (23²); primera letra = tabla[cociente // 23],
    segunda letra = tabla[resto % 23].
    """
    if not cuerpo_16_digitos or not cuerpo_16_digitos.isdigit() or len(cuerpo_16_digitos) != 16:
        return None
    n = int(cuerpo_16_digitos)
    resto = n % 529
    return _TABLA_LETRAS_CONTROL_CUPS[resto // 23] + _TABLA_LETRAS_CONTROL_CUPS[resto % 23]


def cups_digito_control_valido(cups: str | None) -> bool | None:
    """
    Verifica el dígito de control real (no solo el formato) de un CUPS.
    Devuelve None si el CUPS no tiene longitud suficiente para evaluarlo
    (evita falsos negativos sobre CUPS truncados por el OCR).
    """
    c = normalizar_cups(cups)
    if not c or len(c) < 20 or not c.startswith("ES"):
        return None
    cuerpo = c[2:18]
    letras_actuales = c[18:20]
    esperado = calcular_digito_control_cups(cuerpo)
    if esperado is None:
        return None
    return letras_actuales == esperado


def cups_valido(cups: str | None, verificar_digito_control: bool = False) -> bool:
    c = normalizar_cups(cups)
    if not c:
        return False
    formato_ok = re.match(r"^ES\d{16}[A-Z0-9]{0,2}$", c) is not None
    if not formato_ok:
        return False
    if verificar_digito_control:  # QW6 — desactivado por defecto, ver nota arriba
        resultado_dc = cups_digito_control_valido(c)
        if resultado_dc is False:
            return False
    return True


def crear_incidencia(
    tipo: str,
    campo: str,
    severidad: str,
    mensaje: str,
    penalizacion: float = 0.0,
    evidencia: dict | None = None,
) -> dict:
    return {
        "tipo": tipo,
        "campo": campo,
        "severidad": severidad,
        "mensaje": mensaje,
        "penalizacion_confianza": round(float(penalizacion or 0.0), 3),
        "evidencia": evidencia or {},
    }


def aplicar_penalizacion(conf: dict, campo: str, delta: float) -> None:
    actual = float(conf.get(campo, 0.0) or 0.0)
    conf[campo] = round(max(0.0, actual - float(delta)), 3)


def _parse_iso(fecha_iso: str | None):
    if not fecha_iso:
        return None
    try:
        return date.fromisoformat(str(fecha_iso))
    except ValueError:
        return None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(ins, delete, replace))
        prev = curr
    return prev[-1]


def validar_con_historico(
    datos,
    conn,
    pais: str,
    sede: str,
    tipo_energia: str = "electricidad",
    campos_aplicables: set[str] | None = None,
) -> list[dict]:
    """
    campos_aplicables=None → comportamiento legacy (todos los checks, igual
    que hoy). Si se pasa, los checks de un campo que no aplica se OMITEN por
    completo (no se ejecutan, no penalizan, no generan incidencias) en vez
    de evaluarse contra un valor vacío que nunca podría haber sido correcto.
    """

    """
    Valida un resultado OCR contra histórico y penaliza confianza por campo.
    `datos` debe exponer: consumo_kwh, cups, comercializadora, periodo_*, fecha_factura,
    confianza_por_campo.
    """
    incidencias: list[dict] = []
    conf = dict(getattr(datos, "confianza_por_campo", {}) or {})

    def _aplica(campo: str) -> bool:
        return campos_aplicables is None or campo in campos_aplicables

    for campo in REQUIRED_FIELDS:
        if not _aplica(campo):
            conf[campo] = None
            continue
        conf.setdefault(campo, 0.0)

    if sede:
        conf["sede"] = max(float(conf.get("sede", 0.0) or 0.0), 1.0) 

    # 1) Reglas directas de coherencia.
    if _aplica("consumo") and datos.consumo_kwh is not None and float(datos.consumo_kwh) <= 0:
        penal = 0.55
        incidencias.append(
            crear_incidencia(
                "consumo_negativo",
                "consumo",
                "critica",
                f"Consumo no válido: {datos.consumo_kwh}",
                penal,
            )
        )
        aplicar_penalizacion(conf, "consumo", penal)

    if _aplica("cups") and not cups_valido(datos.cups):
        penal = 0.35
        incidencias.append(
            crear_incidencia(
                "cups_invalido",
                "cups",
                "alta",
                "CUPS ausente o con formato inválido",
                penal,
                {"cups": datos.cups},
            )
        )
        aplicar_penalizacion(conf, "cups", penal)

    ini = _parse_iso(datos.periodo_inicio)
    fin = _parse_iso(datos.periodo_fin)
    fecha_factura = _parse_iso(datos.fecha_factura)
    hoy = date.today()

    periodo_dias_min = getattr(config, 'PERIODO_DIAS_MIN', 15)   # QW5
    periodo_dias_max = getattr(config, 'PERIODO_DIAS_MAX', 95)   # QW5
    if _aplica("periodo"):
        if ini and fin:
            dias = (fin - ini).days + 1
            if dias < periodo_dias_min:
                penal = 0.22
                incidencias.append(
                    crear_incidencia(
                        "periodo_corto",
                        "periodo",
                        "media",
                        f"Período muy corto: {dias} días",
                        penal,
                    )
                )
                aplicar_penalizacion(conf, "periodo", penal)
            elif dias > periodo_dias_max:
                penal = 0.32
                incidencias.append(
                    crear_incidencia(
                        "periodo_largo",
                        "periodo",
                        "alta",
                        f"Período excesivamente largo: {dias} días",
                        penal,
                    )
                )
                aplicar_penalizacion(conf, "periodo", penal)
        else:
            penal = 0.30
            incidencias.append(
                crear_incidencia(
                    "periodo_ausente",
                    "periodo",
                    "alta",
                    "No se detectó período de facturación completo",
                    penal,
                )
            )
            aplicar_penalizacion(conf, "periodo", penal)

    if fecha_factura and fin:
        if fecha_factura < fin:
            penal = 0.28
            incidencias.append(
                crear_incidencia(
                    "fecha_incoherente",
                    "fecha_factura",
                    "alta",
                    f"Fecha factura {fecha_factura} anterior al fin del período {fin}",
                    penal,
                )
            )
            aplicar_penalizacion(conf, "fecha_factura", penal)
        if (fecha_factura - fin).days > 120:
            penal = 0.18
            incidencias.append(
                crear_incidencia(
                    "fecha_incoherente",
                    "fecha_factura",
                    "media",
                    "Fecha factura excesivamente posterior al período",
                    penal,
                    {"dias_diferencia": (fecha_factura - fin).days},
                )
            )
            aplicar_penalizacion(conf, "fecha_factura", penal)

    for campo, valor in (
        ("consumo", datos.consumo_kwh),
        ("fecha_factura", datos.fecha_factura),
        ("cups", datos.cups),
        ("comercializadora", datos.comercializadora),
        ("direccion", datos.direccion_suministro),
        ("sociedad", datos.sociedad),
    ):
        if not _aplica(campo):
            continue
        if valor is None or str(valor).strip() == "":
            penal = 0.25 if campo in ("consumo", "periodo", "cups") else 0.15
            incidencias.append(
                crear_incidencia(
                    "dato_obligatorio_ausente",
                    campo,
                    "alta" if campo in ("consumo", "cups") else "media",
                    f"Campo obligatorio ausente: {campo}",
                    penal,
                )
            )
            aplicar_penalizacion(conf, campo, penal)

    # 2) Histórico de la sede.
    rows = conn.execute(
        """SELECT consumo_kwh, cups, comercializadora, periodo_inicio, periodo_fin
           FROM facturas
           WHERE pais=? AND sede=? AND tipo_energia=?
             AND fecha_anulacion IS NULL
             AND consumo_kwh IS NOT NULL
           ORDER BY fecha_carga DESC
           LIMIT 36""",
        (pais, sede, tipo_energia),
    ).fetchall()

    historico_consumos = [float(r["consumo_kwh"]) for r in rows if r["consumo_kwh"]]
    if historico_consumos and datos.consumo_kwh:
        media = sum(historico_consumos) / len(historico_consumos)
        var = sum((x - media) ** 2 for x in historico_consumos) / len(historico_consumos)
        std = math.sqrt(var) if var > 0 else 0.0
        nuevo = float(datos.consumo_kwh)

        umbral_sigma = media + 3 * std if std > 0 else media * 2.2
        umbral_min = max(0.1, media * 0.15)
        if nuevo > umbral_sigma or nuevo < umbral_min:
            penal = 0.24
            incidencias.append(
                crear_incidencia(
                    "consumo_anomalo_historico",
                    "consumo",
                    "alta",
                    "Consumo anómalo frente al histórico de la sede",
                    penal,
                    {"consumo": nuevo, "media": round(media, 2), "std": round(std, 2)},
                )
            )
            aplicar_penalizacion(conf, "consumo", penal)

        # Error típico OCR de separador: miles/decimales desplazados.
        if media > 0:
            candidatos = [nuevo / 10.0, nuevo / 100.0, nuevo / 1000.0]
            if nuevo > media * 4 and any(abs(c - media) / media < 0.35 for c in candidatos):
                penal = 0.20
                incidencias.append(
                    crear_incidencia(
                        "separador_decimal_sospechoso",
                        "consumo",
                        "media",
                        "Posible error OCR en separadores decimales/miles del consumo",
                        penal,
                        {"consumo_extraido": nuevo, "media_historica": round(media, 2)},
                    )
                )
                aplicar_penalizacion(conf, "consumo", penal)

    historico_cups = [normalizar_cups(r["cups"]) for r in rows if r["cups"]]
    historico_cups = [c for c in historico_cups if c]
    cups_actual = normalizar_cups(datos.cups)
    if cups_actual and historico_cups:
        if cups_actual not in historico_cups:
            distancias = sorted((_levenshtein(cups_actual, c), c) for c in set(historico_cups))
            mejor_dist, mejor_cups = distancias[0]
            penal = 0.18 if mejor_dist <= 2 else 0.10
            incidencias.append(
                crear_incidencia(
                    "cups_incoherente_historico",
                    "cups",
                    "alta" if mejor_dist <= 2 else "media",
                    "CUPS distinto al histórico de la sede",
                    penal,
                    {"cups_actual": cups_actual, "cups_historico_cercano": mejor_cups, "distancia": mejor_dist},
                )
            )
            aplicar_penalizacion(conf, "cups", penal)

    hist_comers = [str(r["comercializadora"]).strip() for r in rows if r["comercializadora"]]
    if datos.comercializadora:
        nombre = str(datos.comercializadora).strip()
        if hist_comers:
            top, top_count = Counter(hist_comers).most_common(1)[0]
            if top_count >= 4 and nombre != top:
                penal = 0.12
                incidencias.append(
                    crear_incidencia(
                        "comercializadora_incoherente_historico",
                        "comercializadora",
                        "media",
                        f"Comercializadora difiere de la habitual de la sede ({top})",
                        penal,
                    )
                )
                aplicar_penalizacion(conf, "comercializadora", penal)
        # Check por país: solo penaliza si no es conocida PARA EL PAÍS de la
        # factura. Antes usábamos un set global solo con marcas españolas, así
        # que "Edesur" (AR) o "CFE" (MX) penalizaban unjustamente con -0.20.
        nombre_norm = _normalizar_texto(nombre)
        conocidas_pais = KNOWN_COMERCIALIZADORAS_BY_PAIS.get(pais)
        conocidas = conocidas_pais if conocidas_pais else KNOWN_COMERCIALIZADORAS
        if nombre_norm not in conocidas:
            penal = 0.20
            incidencias.append(
                crear_incidencia(
                    "comercializadora_no_reconocida",
                    "comercializadora",
                    "media",
                    f"Comercializadora no reconocida para {pais}: {nombre}",
                    penal,
                )
            )
            aplicar_penalizacion(conf, "comercializadora", penal)
    else:
        penal = 0.30
        incidencias.append(
            crear_incidencia(
                "comercializadora_no_reconocida",
                "comercializadora",
                "alta",
                "No se detectó comercializadora",
                penal,
            )
        )
        aplicar_penalizacion(conf, "comercializadora", penal)

    # Solapes y huecos por período.
    if ini and fin:
        overlaps = conn.execute(
            """SELECT id, periodo_inicio, periodo_fin
               FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=?
                 AND fecha_anulacion IS NULL
                 AND periodo_inicio IS NOT NULL AND periodo_fin IS NOT NULL
                 AND NOT (periodo_fin < ? OR periodo_inicio > ?)
               ORDER BY fecha_carga DESC LIMIT 3""",
            (pais, sede, tipo_energia, datos.periodo_inicio, datos.periodo_fin),
        ).fetchall()
        if overlaps:
            penal = 0.22
            incidencias.append(
                crear_incidencia(
                    "periodo_solapado",
                    "periodo",
                    "alta",
                    "Período solapado con facturas previas de la sede",
                    penal,
                    {"facturas_relacionadas": [r["id"] for r in overlaps]},
                )
            )
            aplicar_penalizacion(conf, "periodo", penal)

        prev = conn.execute(
            """SELECT periodo_fin FROM facturas
               WHERE pais=? AND sede=? AND tipo_energia=?
                 AND fecha_anulacion IS NULL
                 AND periodo_fin < ?
               ORDER BY periodo_fin DESC LIMIT 1""",
            (pais, sede, tipo_energia, datos.periodo_inicio),
        ).fetchone()
        if prev and prev["periodo_fin"]:
            prev_fin = _parse_iso(prev["periodo_fin"])
            if prev_fin:
                hueco = (ini - prev_fin).days - 1
                if hueco > 40:
                    penal = 0.10
                    incidencias.append(
                        crear_incidencia(
                            "periodo_con_hueco",
                            "periodo",
                            "media",
                            f"Hueco temporal de {hueco} días respecto a la factura anterior",
                            penal,
                        )
                    )
                    aplicar_penalizacion(conf, "periodo", penal)

    if ini and ini > hoy:
        penal = 0.30
        incidencias.append(
            crear_incidencia(
                "fecha_imposible",
                "periodo",
                "alta",
                "El período de facturación está en el futuro",
                penal,
            )
        )
        aplicar_penalizacion(conf, "periodo", penal)
    if fecha_factura and fecha_factura > hoy.replace(year=min(hoy.year + 1, 9999)):
        penal = 0.25
        incidencias.append(
            crear_incidencia(
                "fecha_imposible",
                "fecha_factura",
                "alta",
                "Fecha de factura imposible (muy futura)",
                penal,
            )
        )
        aplicar_penalizacion(conf, "fecha_factura", penal)

    datos.confianza_por_campo = conf
    datos.confianza_global = recalcular_confianza_global(conf)
    return incidencias

