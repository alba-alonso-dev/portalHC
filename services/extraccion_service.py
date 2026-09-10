"""
Servicio de extracción de datos de facturas eléctricas.

Extrae de forma automática mediante regex multi-patrón:
  - Consumo en kWh
  - Período de facturación (inicio, fin, días)
  - Fecha de emisión de la factura
  - Comercializadora
  - Sociedad (razón social del cliente)
  - Dirección del punto de suministro
  - CUPS (España)

Fase 5 — Mejoras de calidad:
  - Nuevas comercializadoras ES (Holaluz, Plenitude, TotalEnergies, Acciona…)
  - Reglas de extracción específicas por comercializadora
  - Patrones de período en formato de texto (mes en palabras)
  - Patrones de consumo adicionales (formato tabla, totales múltiples)
  - Detección de inconsistencias entre campos extraídos
  - Umbral OCR reducido de 50 a 30 caracteres

Cada campo lleva asociado una puntuación de confianza [0-1] que determina
si el registro necesita revisión manual antes de ser confirmado.
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import config
from services.ocr_service import extract_pdf_text, extract_pdf_zone_text
from services.ocr_quality_service import recalcular_confianza_global, cups_valido, crear_incidencia

from services import plantillas_service
from services.plantillas_service import mapa_deteccion
from services.numeros import kwh_a_mwh, importe as importe_decimal
from database.migrations_campos_factura import moneda_de_pais

# Los patrones de detección de comercializadora se cargan desde
# config/plantillas_facturas/*.yaml (ver services/plantillas_service.py), que es
# multipaís: cada plantilla declara su país. La resolución es perezosa y por país
# (no puede hacerse a nivel de módulo, porque mapa_deteccion() requiere el país).

# Fallback para países que todavía no tienen plantillas YAML. Se consulta solo si
# el catálogo YAML no devuelve ningún patrón para ese país.
_COMERCIALIZADORAS_FALLBACK = {
    'AR': {'EDESUR': 'Edesur',   'EDENOR': 'Edenor', 'EDES': 'EDES'},
    'CO': {'CODENSA': 'Codensa', 'EMCALI': 'EMCALI', 'CELSIA': 'CELSIA'},
    'EC': {'EEQSA': 'EEQSA',     'CNEL': 'CNEL',     'AMBATO': 'Ambato'},
    'MX': {'CFE': 'CFE',         'LEC': 'LEC'},
}


def _patrones_comercializadora(pais: str) -> dict:
    """{patron: nombre_canonico} para el país indicado (YAML con prioridad)."""
    pais = (pais or 'ES').upper()
    return mapa_deteccion(pais) or _COMERCIALIZADORAS_FALLBACK.get(pais, {})

# Campos que se intentan si NO hay plantilla o la plantilla no declara
# campos_disponibles — comportamiento legacy, idéntico al de antes de esta
# arquitectura.
CAMPOS_EXTRAIBLES_DEFECTO = [
    'consumo', 'periodo', 'fecha_factura', 'cups',
    'comercializadora', 'direccion', 'sociedad',
]
logger = logging.getLogger(__name__)


# ── Modelo de datos ───────────────────────────────────────────────────────────

@dataclass
class DatosFactura:
    """Resultado completo de la extracción de una factura eléctrica."""
    pais: str = ""
    sede: Optional[str] = None

    # Consumo
    consumo_kwh: Optional[float] = None
    consumo_mwh: Optional[float] = None

    # Período (nuevo en Fase 1)
    fecha_factura: Optional[str] = None      # ISO 8601 YYYY-MM-DD
    periodo_inicio: Optional[str] = None     # ISO 8601 YYYY-MM-DD
    periodo_fin: Optional[str] = None        # ISO 8601 YYYY-MM-DD
    dias_facturados: Optional[int] = None
    mes: Optional[str] = None               # YYYY-MM — retrocompatibilidad

    # Empresa (nuevo en Fase 1)
    comercializadora: Optional[str] = None
    sociedad: Optional[str] = None
    direccion_suministro: Optional[str] = None
    cups: Optional[str] = None

    # Datos comerciales y técnicos del contrato.
    # No intervienen en el cálculo de emisiones: son datos de gestión y de
    # validación cruzada. El importe va siempre con su divisa, derivada del
    # país, para que sea agregable sin ambigüedad en un portal multipaís.
    importe_total: Optional[float] = None
    moneda: Optional[str] = None
    tarifa: Optional[str] = None             # peaje de acceso: 2.0TD, 3.0TD, 6.1TD
    contrato: Optional[str] = None           # referencia de contrato de suministro
    potencia_kw: Optional[float] = None      # potencia contratada
    distribuidora: Optional[str] = None      # distinta de la comercializadora

    # Metadatos OCR
    confianza_global: float = 0.0
    confianza_por_campo: dict = field(default_factory=dict)
    requiere_revision: bool = False
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)    # Fase 5: inconsistencias
    inconsistencias: list = field(default_factory=list) # Fase 5
    incidencias_estructuradas: list = field(default_factory=list)  # QW7 — para UI futura
    campos_aplicables: list = field(default_factory=list)  # arquitectura declarativa
    plantilla_codigo: Optional[str] = None                 # trazabilidad de qué plantilla se usó
    texto_preview: str = ""
    exito: bool = False

# Nombres de meses en español para patrones de fecha
_MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
}

_MESES_ES_PATRON = '|'.join(_MESES_ES.keys())


# ── Utilidades de parseo ──────────────────────────────────────────────────────

def _parse_date(dia: str, mes: str, anio: str) -> Optional[date]:
    """Convierte partes de fecha (string) a un objeto date. Acepta años de 2 dígitos."""
    try:
        d, m, a = int(dia), int(mes), int(anio)
        if a < 100:
            a += 2000
        anio_min = getattr(config, 'ANIO_MIN_FACTURA', 2015)          # QW5
        anio_max = date.today().year + getattr(config, 'ANIO_MAX_OFFSET', 1)  # QW5
        if anio_min <= a <= anio_max and 1 <= m <= 12 and 1 <= d <= 31:
            return date(a, m, d)
    except (ValueError, TypeError):
        pass
    return None


def _parse_date_texto(dia: str, mes_texto: str, anio: str) -> Optional[date]:
    """Convierte fecha con mes en texto (ej. '15 enero 2025') a objeto date."""
    m = _MESES_ES.get(mes_texto.lower().strip())
    if m is None:
        return None
    return _parse_date(dia, str(m), anio)


def _normalizar_consumo(s: str) -> Optional[float]:
    """
    Convierte cadenas numéricas con separadores variados a float.
    Maneja: 81.600,00  /  81,600.00  /  81600  /  81600,00
    """
    s = s.strip()
    # 81.600,00 → punto=miles, coma=decimal
    if re.match(r'^\d{1,3}(\.\d{3})+(,\d+)?$', s):
        s = s.replace('.', '').replace(',', '.')
    # 81,600.00 → coma=miles, punto=decimal
    elif re.match(r'^\d{1,3}(,\d{3})+(\.\d+)?$', s):
        s = s.replace(',', '')
    # 81600,00 → solo coma decimal
    elif ',' in s and '.' not in s:
        s = s.replace(',', '.')
    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None


def _aplicar_agregacion(match: 're.Match', agregacion: str) -> Optional[float]:
    """
    Soporte multi-grupo. Caso típico: tarifas con discriminación horaria
    donde el consumo total es la SUMA de varios períodos (P1+P2+P6), no un
    único número — el caso real de universidad_cantabria.yaml:
        patron: 'P1:\\s*([\\d.,]+)\\s*kWh.*?P2:\\s*([\\d.,]+)\\s*kWh.*?P6:\\s*([\\d.,]+)\\s*kWh'

    'primer_grupo' (por defecto): usa match.group(1) — comportamiento v1,
      retrocompatible con todas las plantillas que no declaran 'agregacion'.
    'suma_grupos': suma TODOS los grupos capturados (ignorando los que no
      se pudieron normalizar a número).
    """
    if agregacion == 'suma_grupos':
        valores = [_normalizar_consumo(g) for g in match.groups() if g]
        valores = [v for v in valores if v is not None]
        return round(sum(valores), 2) if valores else None

    # 'primer_grupo' (o cualquier otro valor — ya validado por
    # plantillas_service antes de llegar aquí, así que en la práctica solo
    # llegan estos dos valores)
    return _normalizar_consumo(match.group(1)) if match.groups() else None

def _fin_de_mes(fecha: date) -> date:
    """Devuelve el último día del mes de 'fecha'."""
    if fecha.month == 12:
        return date(fecha.year + 1, 1, 1) - timedelta(days=1)
    return date(fecha.year, fecha.month + 1, 1) - timedelta(days=1)


# ── Extracciones individuales ─────────────────────────────────────────────────

def extraer_consumo(texto: str,
                    comercializadora: Optional[str] = None,
                    pais: str = 'ES') -> tuple[Optional[float], float]:
    """
    Estrategia A: franjas horarias (genérico).
    Estrategia B: E.Tot en tabla histórica (genérico).
    Estrategia C: regla DECLARADA EN LA PLANTILLA (esquema v2) — el
                  comportamiento específico de comercializadora viene
                  ÚNICAMENTE de plantillas_service; no hay ningún nombre de
                  proveedor hardcodeado en esta función.
    Estrategia D: patrones genéricos (fallback universal).
    Devuelve (consumo_kwh, confianza).
    """
    # A: franjas horarias
    patron_franja = r'Energ(?:[iÃ­]a)?\.?\s*Hrs?\.?\s*(?:Restantes|Valle|Punta|Noc)[^\n]*?([\d.,]+)\s*KWH'
    matches = re.findall(patron_franja, texto, re.IGNORECASE)
    if matches:
        total = 0.0
        for m in matches:
            v = _normalizar_consumo(m)
            if v:
                total += v
        if total > 50:
            return total, 0.92

    # B: E.Tot
    patron_etot = r'E\.?\s*Tot[^\n]*?(\d{4,6})\s*$'
    m = re.search(patron_etot, texto, re.MULTILINE | re.IGNORECASE)
    if m:
        nums = re.findall(r'\b(\d{4,6})\b', m.group(0))
        if nums:
            v = _normalizar_consumo(nums[-1])
            if v and v > 50:
                return v, 0.85

    # C: regla declarada en la plantilla (esquema v2)
    if comercializadora:
        regla = plantillas_service.regla_extraccion_campo(pais, comercializadora, 'consumo')
        if regla and regla.get('patron'):
            m = re.search(regla['patron'], texto, re.IGNORECASE)
            if m:
                valor = _aplicar_agregacion(m, regla.get('agregacion', 'primer_grupo'))
                if valor and valor > 50:
                    return valor, regla.get('confianza', 0.90)

    # D: patrones genéricos (sin cambios respecto al original)
    patrones_d = [
        (r'(?:Consumo\s+(?:Activo|Total|Neto)|CONSUMO\s+TOTAL)\s*[:\s]*([\d.,]+)\s*k?Wh',  0.90),
        (r'(?:Energ[iÃ­]a\s+Activa|ENERG[ÃI]A\s+ACTIVA)\s*[:\s]*([\d.,]+)\s*k?Wh',          0.88),
        (r'(?:Consumo|CONSUMO)\s*[:\s]*([\d.,]+)\s*k?Wh',                                   0.85),
        (r'Total\s+facturado[:\s]+([\d.,]+)\s*kWh',                                          0.88),
        (r'kWh\s+facturados?[:\s]+([\d.,]+)',                                                 0.85),
        (r'Lecturas?\s*(?:anterior|final)[^\n]*?([\d.,]{3,8})\s*kWh',                        0.80),
        (r'(?:Energ[iÃ­]a|ENERG[ÃI]A)\s*[:\s]*([\d.,]+)\s*k?Wh',                             0.82),
        (r'([\d.,]{4,10})\s*k[Ww][Hh]',                                                      0.65),
        (r'(\d{3,6})\s*[KkWw][Ww]?[Hh]',                                                     0.55),
    ]
    for patron, conf in patrones_d:
        for m in re.finditer(patron, texto, re.IGNORECASE):
            v = _normalizar_consumo(m.group(1))
            if v and v > 50:
                return v, conf

    return None, 0.0


def extraer_periodo_facturacion(
    texto: str, pais: str
) -> tuple[Optional[str], Optional[str], Optional[int], float]:
    """
    Extrae el período de facturación (inicio ISO, fin ISO, días, confianza).

    Árbol de decisión (extendido en Fase 5):
      1. Patrón explícito "Período del DD/MM/YYYY al DD/MM/YYYY"       → conf 0.95
      2. "Del DD/MM/YYYY al DD/MM/YYYY"                                   → conf 0.88
      3. Formato compacto YYYYMMDD-YYYYMMDD                               → conf 0.85
      4. Dos fechas separadas por " - " o " a " en la misma línea       → conf 0.80
      5. Fecha con mes en texto "DD de mes de YYYY"                      → conf 0.78 (Fase 5)
      6. Formato "mes YYYY - mes YYYY"                                   → conf 0.72 (Fase 5)
      7. "Período de Liquidación DD/MM/YYYY" → mes completo inferido    → conf 0.65
      8. Deducción desde fecha de factura + número de días                → conf 0.55 (Fase 5)
    """

    def _rango_valido(ini: date, fin: date) -> bool:
        return ini <= fin and 15 <= (fin - ini).days + 1 <= 95

    # Patrón 1
    p1 = (r'[Pp]er[ií]odo\s+del?\s+'
          r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\s+'
          r'al?\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})')
    m = re.search(p1, texto, re.IGNORECASE)
    if m:
        g = m.groups()
        ini = _parse_date(g[0], g[1], g[2])
        fin = _parse_date(g[3], g[4], g[5])
        if ini and fin and _rango_valido(ini, fin):
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.95

    # Patrón 2
    p2 = (r'[Dd]el?\s+'
          r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\s+'
          r'al?\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})')
    m = re.search(p2, texto, re.IGNORECASE)
    if m:
        g = m.groups()
        ini = _parse_date(g[0], g[1], g[2])
        fin = _parse_date(g[3], g[4], g[5])
        if ini and fin and _rango_valido(ini, fin):
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.88

    # Patrón 3: YYYYMMDD-YYYYMMDD
    for m in re.finditer(r'\b(\d{8})\s*[\-–]\s*(\d{8})\b', texto):
        try:
            ini = datetime.strptime(m.group(1), '%Y%m%d').date()
            fin = datetime.strptime(m.group(2), '%Y%m%d').date()
            if _rango_valido(ini, fin):
                dias = (fin - ini).days + 1
                return ini.isoformat(), fin.isoformat(), dias, 0.85
        except ValueError:
            pass

    # Patrón 4: dos fechas DD/MM/YYYY separadas por " - " o " a "
    p4 = (r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})'
          r'\s*(?:[\-–]\s*|al?\s+)'
          r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})')
    for m in re.finditer(p4, texto, re.IGNORECASE):
        g = m.groups()
        ini = _parse_date(g[0], g[1], g[2])
        fin = _parse_date(g[3], g[4], g[5])
        if ini and fin and _rango_valido(ini, fin):
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.80

    # Patrón 5 (Fase 5): "DD de mes de YYYY al DD de mes de YYYY"
    p5a = (rf'(\d{{1,2}})\s+de\s+({_MESES_ES_PATRON})\s+de\s+(\d{{4}})'
           rf'\s+al?\s+'
           rf'(\d{{1,2}})\s+de\s+({_MESES_ES_PATRON})\s+de\s+(\d{{4}})')
    m = re.search(p5a, texto, re.IGNORECASE)
    if m:
        ini = _parse_date_texto(m.group(1), m.group(2), m.group(3))
        fin = _parse_date_texto(m.group(4), m.group(5), m.group(6))
        if ini and fin and _rango_valido(ini, fin):
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.78

    # Patrón 6 (Fase 5): "mes YYYY" como período implícito (mes completo)
    p6 = rf'[Pp]er[ií]odo[:\s]+({_MESES_ES_PATRON})\s+(\d{{4}})'
    m = re.search(p6, texto, re.IGNORECASE)
    if m:
        mes_num = _MESES_ES.get(m.group(1).lower())
        if mes_num:
            ini = date(int(m.group(2)), mes_num, 1)
            fin = _fin_de_mes(ini)
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.72

    # Patrón 7: "Período de Liquidación DD/MM/YYYY" → mes completo
    p7 = r'[Pp]er[ií]odo\s+de\s+[Ll]iquidaci[oó]n\s*[:\-]?\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})'
    m = re.search(p7, texto, re.IGNORECASE)
    if m:
        fecha = _parse_date(*m.groups())
        if fecha:
            ini = date(fecha.year, fecha.month, 1)
            fin = _fin_de_mes(ini)
            dias = (fin - ini).days + 1
            return ini.isoformat(), fin.isoformat(), dias, 0.65

    # Patrón 8 (Fase 5): número de días facturados + fecha factura → período aproximado
    p8_dias = r'(\d{2,3})\s*d[ií]as?\s+(?:facturados?|de\s+consumo)'
    p8_fecha = r'[Ff]echa\s+(?:de\s+(?:la\s+)?[Ff]actura|[Ee]misi[oó]n)\s*[:\-]\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})'
    m_dias  = re.search(p8_dias, texto, re.IGNORECASE)
    m_fecha = re.search(p8_fecha, texto, re.IGNORECASE)
    if m_dias and m_fecha:
        try:
            n_dias = int(m_dias.group(1))
            fecha_fac = _parse_date(*m_fecha.groups()[:3])
            if fecha_fac and 15 <= n_dias <= 95:
                fin = fecha_fac
                ini = fin - timedelta(days=n_dias - 1)
                return ini.isoformat(), fin.isoformat(), n_dias, 0.55
        except Exception:
            pass

    return None, None, None, 0.0


def _normalizar_fecha(bruto: Optional[str]) -> Optional[str]:
    """Convierte una fecha en cualquiera de los formatos que imprimen las
    comercializadoras a ISO (YYYY-MM-DD). Acepta dd/mm/aaaa, dd-mm-aaaa,
    dd.mm.aa y '10 de febrero de 2026'."""
    if not bruto:
        return None
    s = re.sub(r'\s+', ' ', str(bruto)).strip()

    m = re.search(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})', s)
    if m:
        d = _parse_date(*m.groups())
        if d:
            return d.isoformat()

    m = re.search(rf'(\d{{1,2}})\s+de\s+({_MESES_ES_PATRON})\s+de\s+(\d{{4}})',
                  s, re.IGNORECASE)
    if m:
        d = _parse_date_texto(m.group(1), m.group(2), m.group(3))
        if d:
            return d.isoformat()
    return None


def extraer_fecha_factura(texto: str, comercializadora: Optional[str] = None,
                          pais: str = 'ES') -> tuple[Optional[str], float]:
    """
    Extrae la fecha de emisión de la factura.

    Igual que importe/potencia/tarifa: primero la regla declarada en la
    plantilla y solo después los patrones genéricos. Antes esta función
    ignoraba por completo la plantilla, así que las reglas 'fecha_factura' de
    los YAML eran letra muerta y cualquier emisor que no rotulase la fecha
    con el formato genérico ('Fecha de emisión: dd/mm/aaaa') se quedaba sin
    fecha — el caso de Ecuador ('Fecha de emisión 21-01-2026', sin dos puntos)
    y de la UGR ('FechadeEmisión:22/01/2026', sin espacios).
    """
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora,
                                           'fecha_factura', pais)
        iso = _normalizar_fecha(bruto)
        if iso:
            return iso, conf

    patrones = [
        (r'[Ff]echa\s+(?:de\s+(?:la\s+)?[Ff]actura|[Ee]misi[oó]n)\s*[:\-]\s*'
         r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})',                             0.95),
        (r'[Ee]mitida?\s+(?:el|en)\s*[:\-]?\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', 0.90),
        (r'[Ff]echa\s*[:\-]\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})',          0.85),
        # Ciudades cabecera de factura (Argentina, Colombia…)
        (r'(?:Capital\s+Federal|Buenos\s+Aires|Bogot[aá]|Guayaquil|'
         r'Quito|M[eé]xico\s+D\.?F\.?|Madrid|Zaragoza)[,\s]+'
         r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})',                             0.80),
        (r'[Vv]ence\s+el\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})',            0.50),
    ]
    for patron, conf in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            d = _parse_date(*m.groups()[:3])
            if d:
                return d.isoformat(), conf

    # Fase 5: fecha con mes en texto "15 de enero de 2025"
    p_texto = (rf'(\d{{1,2}})\s+de\s+({_MESES_ES_PATRON})\s+de\s+(\d{{4}})')
    m = re.search(p_texto, texto, re.IGNORECASE)
    if m:
        d = _parse_date_texto(m.group(1), m.group(2), m.group(3))
        if d and 2015 <= d.year <= 2040:
            return d.isoformat(), 0.80

    return None, 0.0


def _regex_alias(patron: str) -> str:
    """
    Convierte un alias de detección en una regex tolerante al espaciado.

    El alias se declara en el YAML con espacios simples ("UNIVERSIDAD DE
    CANTABRIA"), pero el texto real rara vez los conserva: el OCR emite un
    token por línea ("Universidad\\nde Cantabria") y pdfplumber puede insertar
    espacios dobles al reconstruir columnas. Un re.escape() literal exige el
    espacio exacto y falla en ambos casos — ese era el motivo de que las
    facturas escaneadas de la Universidad de Cantabria quedaran sin plantilla
    pese a tenerla.

    Cada espacio del alias pasa a \\s+, así que sigue exigiendo separación
    (no une palabras que estén pegadas) pero acepta saltos de línea y
    espaciado múltiple. El resto del alias se escapa como antes.
    """
    return r'\s+'.join(re.escape(p) for p in patron.split())


def extraer_comercializadora(texto: str, pais: str) -> tuple[Optional[str], float]:
    """
    Detecta la comercializadora usando los patrones declarados en las plantillas
    YAML del país (multipaís: ES, AR, ...), con fallback a la lista embebida para
    los países que aún no tienen plantillas.
    """
    pais = (pais or 'ES').upper()
    patrones = _patrones_comercializadora(pais)

    # Patrones largos primero: evita que "EDES" gane a "EDESUR".
    for patron in sorted(patrones, key=len, reverse=True):
        if re.search(_regex_alias(patron), texto, re.IGNORECASE):
            return patrones[patron], 0.92
    return None, 0.0


def extraer_sociedad(texto: str, comercializadora: Optional[str] = None,
                     pais: str = 'ES') -> tuple[Optional[str], float]:
    """
    Extrae la razón social del titular de la factura.
    Prioridad: CIF conocido del grupo Hiberus > regla de la plantilla >
    etiqueta explícita genérica.

    El CIF va primero porque identifica la sociedad sin ambigüedad; la regla
    de la plantilla va antes que los patrones genéricos porque estos exigen
    un separador ':' o '-' que muchas facturas de LATAM no imprimen.
    """
    # 1. CIF conocido
    for cif, nombre in getattr(config, 'SOCIEDADES_CONOCIDAS', {}).items():
        if cif.upper() in texto.upper():
            return nombre, 0.97

    # 2. Regla declarada en la plantilla
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'sociedad', pais)
        val = _limpiar_texto(bruto)
        if val and 3 < len(val) < 80:
            return val, conf

    # 3. Etiqueta explícita
    patrones = [
        (r'(?:[Tt]itular|[Rr]az[oó]n\s+[Ss]ocial)\s*[:\-]\s*'
         r'([A-ZÁÉÍÓÚÜÑ][^\n\r]{5,70})',                             0.87),
        (r'[Cc]liente\s*[:\-]\s*([A-ZÁÉÍÓÚÜÑ][^\n\r]{5,70})',      0.82),
        (r'[Ss]ociedad\s*[:\-]\s*([A-ZÁÉÍÓÚÜÑ][^\n\r]{5,70})',     0.80),
        (r'[Nn]ombre\s+(?:del?\s+)?[Cc]liente\s*[:\-]\s*'
         r'([A-ZÁÉÍÓÚÜÑ][^\n\r]{5,70})',                             0.82),
    ]
    for patron, conf in patrones:
        m = re.search(patron, texto)
        if m:
            val = re.sub(r'\s+', ' ', m.group(1)).rstrip('.,;: ')
            if 3 < len(val) < 80:
                return val, conf

    return None, 0.0


def extraer_direccion_suministro(texto: str, comercializadora: Optional[str] = None,
                                 pais: str = 'ES') -> tuple[Optional[str], float]:
    """Extrae la dirección del punto de suministro.

    La regla de la plantilla tiene prioridad sobre los patrones genéricos: el
    último de estos es un comodín de dirección postal ('C/ ...', 'Av. ...')
    que casa con la PRIMERA dirección del documento, y esa suele ser la del
    emisor o la de correspondencia, no la del punto de suministro.
    """
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'direccion', pais)
        val = _limpiar_texto(bruto)
        if val and len(val) >= 8:
            return val[:100], conf

    patrones = [
        (r'[Dd]irecci[oó]n\s+(?:de\s+)?[Ss]uministro\s*[:\-]\s*([^\n\r]{10,100})', 0.90),
        (r'[Pp]unto\s+de\s+[Ss]uministro\s*[:\-]\s*([^\n\r]{10,100})',               0.87),
        (r'[Dd]irecci[oó]n\s+de\s+[Ss]ervicio\s*[:\-]\s*([^\n\r]{10,100})',          0.85),
        (r'[Uu]bicaci[oó]n\s+del?\s+[Ss]uministro\s*[:\-]\s*([^\n\r]{10,100})',      0.82),
        # Tras CUPS en España
        (r'CUPS\s*[:\-]?\s*[A-Z0-9]{18,22}\s+([^\n\r]{10,100})',                    0.72),
        # Patrón genérico de dirección postal
        (r'(?:C/|Calle|Av\.|Avda\.|Plaza|Pº\.|Pol\.)\s+'
         r'[A-Za-záéíóúüñÁÉÍÓÚÜÑ][^\n\r]{5,80}',                                   0.55),
    ]
    for patron, conf in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            val = m.group(1).strip() if m.lastindex else m.group(0).strip()
            val = re.sub(r'\s+', ' ', val)[:100]
            return val, conf
    return None, 0.0


def extraer_cups(texto: str) -> tuple[Optional[str], float]:
    """
    Extrae el CUPS (Código Unificado de Punto de Suministro, solo España).
    Fase 5: patrones adicionales para variaciones de formato.
    """
    # Patrón primario: precedido por "CUPS"
    m = re.search(
        r'\bCUPS\s*[:\-]?\s*([A-Z]{2}\d{16,18}[A-Z0-9]{0,2})\b',
        texto, re.IGNORECASE
    )
    if m:
        cups = m.group(1).upper()
        return cups, 0.95 if cups_valido(cups) else 0.70

    # Fase 5: CUPS sin etiqueta — ES seguido de 18-20 caracteres alfanuméricos
    # Formato: ES + 16 dígitos + 0-2 letras de control
    m = re.search(r'\b(ES\d{16}[A-Z0-9]{0,2})\b', texto, re.IGNORECASE)
    if m:
        cups = m.group(1).upper()
        if 18 <= len(cups) <= 22:
            return cups, 0.82 if cups_valido(cups) else 0.60

    return None, 0.0


def _extraer_periodo_regla(texto: str, comercializadora: Optional[str], pais: str = 'ES'):
    if not comercializadora:
        return None, None, None, 0.0
    regla = plantillas_service.regla_extraccion_campo(pais, comercializadora, 'periodo')
    if not regla or not regla.get('patron'):
        return None, None, None, 0.0
    m = re.search(regla['patron'], texto, re.IGNORECASE)
    if not m or len(m.groups()) < 2:
        return None, None, None, 0.0

    # Algunas facturas imprimen la lectura ACTUAL antes que la anterior (Edesur:
    # 'Estados al 20/01/2026  Estados al 22/12/2025'). El orden lo declara la
    # plantilla en vez de deducirse invirtiendo cuando ini>fin: una inversión
    # automática enmascararía un patrón que está capturando fechas equivocadas,
    # que es justo lo que no queremos que pase inadvertido.
    g1, g2 = m.group(1), m.group(2)
    if (regla.get('orden') or 'inicio_fin') == 'fin_inicio':
        g1, g2 = g2, g1

    try:
        ini = datetime.strptime(g1.replace("-", "/"), "%d/%m/%Y").date()
        fin = datetime.strptime(g2.replace("-", "/"), "%d/%m/%Y").date()
    except ValueError:
        return None, None, None, 0.0
    if ini > fin:
        return None, None, None, 0.0
    dias = (fin - ini).days + 1
    if dias < 10 or dias > 120:
        return None, None, None, 0.0
    return ini.isoformat(), fin.isoformat(), dias, regla.get('confianza', 0.90)


def _extraer_cups_regla(texto: str, comercializadora: Optional[str], pais: str = 'ES'):
    if not comercializadora:
        return None, 0.0
    regla = plantillas_service.regla_extraccion_campo(pais, comercializadora, 'cups')
    if not regla or not regla.get('patron'):
        return None, 0.0
    m = re.search(regla['patron'], texto, re.IGNORECASE)
    if not m:
        return None, 0.0
    # Defensivo: algunas plantillas reales tienen patron_cups_extra SIN grupo
    # de captura (p.ej. 'ES\d{16}[A-Z0-9]{2,4}' a secas) — usar group(0) en
    # ese caso en vez de asumir que group(1) existe.
    cups = (m.group(1) if m.groups() else m.group(0)).upper().strip()
    conf_base = regla.get('confianza', 0.85)
    return cups, conf_base if cups_valido(cups) else conf_base * 0.7


# ── Detección de inconsistencias (Fase 5) ─────────────────────────────────────

def detectar_inconsistencias(datos: 'DatosFactura') -> list[str]:
    """
    Detecta inconsistencias lógicas entre los campos extraídos.
    Devuelve lista de mensajes de advertencia.
    """
    incidencias_obj: list[dict] = []

    # 1. Período vs días facturados
    if datos.periodo_inicio and datos.periodo_fin and datos.dias_facturados:
        try:
            ini = date.fromisoformat(datos.periodo_inicio)
            fin = date.fromisoformat(datos.periodo_fin)
            dias_calculados = (fin - ini).days + 1
            if abs(dias_calculados - datos.dias_facturados) > 2:
                incidencias_obj.append(
                    crear_incidencia(
                        tipo="periodo_dias_incoherente",
                        campo="periodo",
                        severidad="media",
                        mensaje=(
                            f"Inconsistencia: días_facturados={datos.dias_facturados} "
                            f"pero {datos.periodo_inicio}→{datos.periodo_fin} son {dias_calculados} días"
                        ),
                        evidencia={
                            "dias_declarados": datos.dias_facturados,
                            "dias_calculados": dias_calculados,
                        },
                    )
                )
        except ValueError:
            pass

    # 2. Fecha factura fuera del período (debería ser posterior al fin del período)
    if datos.fecha_factura and datos.periodo_fin:
        try:
            f_fac = date.fromisoformat(datos.fecha_factura)
            f_fin = date.fromisoformat(datos.periodo_fin)
            if f_fac < f_fin:
                incidencias_obj.append(
                    crear_incidencia(
                        tipo="fecha_incoherente",
                        campo="fecha_factura",
                        severidad="media",
                        mensaje=(
                            f"Fecha de factura ({datos.fecha_factura}) anterior al fin "
                            f"del período ({datos.periodo_fin})"
                        ),
                        evidencia={
                            "fecha_factura": datos.fecha_factura,
                            "periodo_fin": datos.periodo_fin,
                        },
                    ) 
                )
            if (f_fac - f_fin).days > 90:
                diferencia_dias = (f_fac - f_fin).days
                incidencias_obj.append(
                    crear_incidencia(
                        tipo="fecha_muy_posterior",
                        campo="fecha_factura",
                        severidad="baja",
                        mensaje=(
                            f"Fecha de factura muy posterior al fin del período "
                            f"({diferencia_dias} días de diferencia)"
                        ),
                        evidencia={"diferencia_dias": diferencia_dias},
                    )
                )
        except ValueError:
            pass

    # 3. Consumo atípico respecto a días facturados
    if datos.consumo_kwh and datos.dias_facturados:
        kwh_por_dia = datos.consumo_kwh / datos.dias_facturados
        if kwh_por_dia > 5000:
            incidencias_obj.append(
                crear_incidencia(
                    tipo="consumo_muy_elevado",
                    campo="consumo",
                    severidad="alta",
                    mensaje=(
                        f"Consumo muy elevado: {kwh_por_dia:.0f} kWh/día "
                        f"({datos.consumo_kwh:.0f} kWh en {datos.dias_facturados} días)"
                    ),
                    evidencia={
                        "kwh_por_dia": kwh_por_dia,
                        "consumo_total": datos.consumo_kwh,
                    },
                )
            )
        elif kwh_por_dia < 0.1:
            incidencias_obj.append(
                crear_incidencia(
                    tipo="consumo_muy_bajo",
                    campo="consumo",
                    severidad="baja",
                    mensaje=(
                        f"Consumo muy bajo: {kwh_por_dia:.3f} kWh/día "
                        f"({datos.consumo_kwh:.2f} kWh en {datos.dias_facturados} días)"
                    ),
                    evidencia={
                        "kwh_por_dia": kwh_por_dia,
                        "consumo_total": datos.consumo_kwh,
                    },
                )
            )

    # 4. Período en el futuro
    if datos.periodo_fin:
        try:
            fin = date.fromisoformat(datos.periodo_fin)
            hoy = date.today()
            if fin > hoy:
                incidencias_obj.append(
                    crear_incidencia(
                        tipo="periodo_futuro",
                        campo="periodo",
                        severidad="alta",
                        mensaje=f"Período de facturación en el futuro: fin={datos.periodo_fin}",
                        evidencia={
                            "periodo_fin": datos.periodo_fin,
                            "fecha_hoy": str(hoy),
                        },
                    )
                )
        except ValueError:
            pass

    # 5. Año del período inconsistente con año de la factura
    if datos.periodo_inicio and datos.fecha_factura:
        anio_periodo = datos.periodo_inicio[:4]
        anio_factura = datos.fecha_factura[:4]
        # Permitir diciembre del año anterior (factura emitida en enero)
        if anio_periodo != anio_factura and abs(int(anio_periodo) - int(anio_factura)) > 1:
            incidencias_obj.append(
                crear_incidencia(
                    tipo="anio_incoherente",
                    campo="periodo",
                    severidad="media",
                    mensaje=(
                        f"Posible error de año: período en {anio_periodo} "
                        f"pero factura emitida en {anio_factura}"
                    ),
                    evidencia={
                        "anio_periodo": anio_periodo,
                        "anio_factura": anio_factura,
                    },
                )
            )

    # Se guarda la lista de diccionarios estructurados para uso en la UI
    datos.incidencias_estructuradas = incidencias_obj

    return incidencias_obj

def _extraer_campo_regla(
        texto: str,
        comercializadora: str,
        campo: str,
        pais: str = 'ES'
):
    regla = plantillas_service.regla_extraccion_campo(
        pais,
        comercializadora,
        campo
    )

    if not regla:
        return None, 0.0

    patron = regla.get("patron")

    if not patron:
        return None, 0.0

    m = re.search(patron, texto, re.IGNORECASE)

    if not m:
        return None, 0.0

    # Defensivo: no todas las plantillas definen grupo de captura (p.ej. un
    # patrón de tarifa a secas). Sin esto, group(1) lanzaría IndexError y
    # tumbaría la extracción completa de la factura.
    valor = (m.group(1) if m.groups() else m.group(0)).strip()

    return valor, regla.get("confianza", 0.90)


# ── Campos comerciales y técnicos ─────────────────────────────────────────────
# Todos siguen el mismo contrato: primero la regla declarada en la plantilla
# (más precisa, específica de esa comercializadora) y, si no hay o no casa,
# patrones genéricos. Ninguno alimenta el cálculo de emisiones.

def _limpiar_texto(valor: Optional[str]) -> Optional[str]:
    """Colapsa espacios y descarta cadenas vacías o de puro relleno."""
    if not valor:
        return None
    limpio = re.sub(r'\s+', ' ', valor).strip(' .,:;-')
    return limpio or None


def _primer_match(texto: str, patrones: list[tuple[str, float]]):
    for patron, conf in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            valor = m.group(1) if m.groups() else m.group(0)
            return valor, conf
    return None, 0.0


def extraer_importe(texto: str, comercializadora: Optional[str] = None,
                    pais: str = 'ES') -> tuple[Optional[float], float]:
    """Importe total facturado. Devuelve el valor numérico; la divisa la fija
    el país de la factura (no se infiere del símbolo, que suele venir mal
    reconocido por el OCR)."""
    bruto, conf = (None, 0.0)
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'importe', pais)

    if not bruto:
        bruto, conf = _primer_match(texto, [
            (r'(?:IMPORTE\s+TOTAL|TOTAL\s+FACTURA|TOTAL\s+A\s+PAGAR)'
             r'[^\d\n]{0,20}([\d][\d.,]*)', 0.88),
            (r'Total\s+importe\s+factura[^\d\n]{0,20}([\d][\d.,]*)', 0.88),
            (r'(?:TOTAL|Total)[^\d\n]{0,15}([\d][\d.,]*)\s*(?:€|EUR|Eur)', 0.80),
        ])

    if not bruto:
        return None, 0.0

    valor = _normalizar_consumo(str(bruto))
    # Cota de cordura: un importe de factura eléctrica fuera de este rango es
    # casi seguro un error de OCR (una lectura de contador colada como importe).
    if valor is None or not (0 < valor < 10_000_000):
        return None, 0.0
    return importe_decimal(valor), conf


def extraer_potencia(texto: str, comercializadora: Optional[str] = None,
                     pais: str = 'ES') -> tuple[Optional[float], float]:
    """Potencia contratada en kW."""
    bruto, conf = (None, 0.0)
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'potencia', pais)

    if not bruto:
        bruto, conf = _primer_match(texto, [
            (r'Potencia\s+contratada[^\d\n]{0,30}([\d][\d.,]*)\s*kW', 0.88),
            (r'Pot\.?\s*contratada[^\d\n]{0,30}([\d][\d.,]*)\s*kW', 0.85),
            (r'\bP(?:C)?1\s*[:=]\s*([\d][\d.,]*)\s*kW', 0.82),
        ])

    if not bruto:
        return None, 0.0

    valor = _normalizar_consumo(str(bruto))
    if valor is None or not (0 < valor <= 100_000):
        return None, 0.0
    return round(valor, 3), conf


# Peajes de acceso vigentes (2.0TD/3.0TD/6.xTD) y los antiguos previos a 2021,
# que siguen apareciendo en facturas históricas cargadas retroactivamente.
_PATRON_TARIFA = r'\b(2\.0TD|3\.0TD|6\.[1-4]TD|2\.0A|2\.0DHA|2\.1A|3\.0A|6\.[1-5]A)\b'


def extraer_tarifa(texto: str, comercializadora: Optional[str] = None,
                   pais: str = 'ES') -> tuple[Optional[str], float]:
    """Peaje de acceso / tarifa contratada."""
    bruto, conf = (None, 0.0)
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'tarifa', pais)

    if not bruto:
        bruto, conf = _primer_match(texto, [
            (r'(?:Tarifa|Peaje)[^\n]{0,40}?' + _PATRON_TARIFA, 0.90),
            (_PATRON_TARIFA, 0.82),
        ])

    valor = _limpiar_texto(bruto)
    if not valor:
        return None, 0.0
    # Normalización: el OCR alterna mayúsculas/minúsculas y cuela espacios
    # ("2.0 td"), lo que fragmentaría cualquier agrupación por tarifa.
    normalizada = re.sub(r'\s+', '', valor).upper()
    return normalizada, conf


def extraer_contrato(texto: str, comercializadora: Optional[str] = None,
                     pais: str = 'ES') -> tuple[Optional[str], float]:
    """Referencia del contrato de suministro."""
    bruto, conf = (None, 0.0)
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'contrato', pais)

    if not bruto:
        bruto, conf = _primer_match(texto, [
            (r'(?:Referencia\s+de\s+contrato(?:\s+de\s+suministro)?|'
             r'N[ºo°]\s*de\s*[Cc]ontrato|N[úu]mero\s+de\s+contrato|'
             r'Ref\.?\s*Contrato(?:\s+Suministro)?)\s*[:=]?\s*([A-Z0-9][A-Z0-9\-_/\.]{3,30})', 0.85),
        ])

    valor = _limpiar_texto(bruto)
    if not valor or len(valor) < 4:
        return None, 0.0
    return valor.upper(), conf


def extraer_distribuidora(texto: str, comercializadora: Optional[str] = None,
                          pais: str = 'ES') -> tuple[Optional[str], float]:
    """Empresa distribuidora — NO es la comercializadora: la distribuidora
    opera la red y no se elige, la comercializadora vende la energía."""
    bruto, conf = (None, 0.0)
    if comercializadora:
        bruto, conf = _extraer_campo_regla(texto, comercializadora, 'distribuidora', pais)

    if not bruto:
        bruto, conf = _primer_match(texto, [
            (r'(?:Empresa\s+)?Distribuidora\s*[:=]\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\-\.\, ]{3,45})', 0.85),
        ])

    valor = _limpiar_texto(bruto)
    if not valor or len(valor) < 3:
        return None, 0.0
    return valor, conf


# ── Función principal ─────────────────────────────────────────────────────────

# Reemplazar la función completa por:
def extraer_datos_factura(pdf_path: str, pais: str) -> DatosFactura:
    """
    Orquestador principal. El comportamiento (qué campos se intentan extraer,
    y con qué peso penalizan la confianza global) depende ÚNICAMENTE de
    campos_aplicables, resuelto desde plantillas_service.campos_disponibles().
    No hay ninguna rama por 'categoria' aquí ni en ningún otro punto del
    pipeline — categoria es solo metadato de reporting.
    """
    logger.info(f"📄 Extrayendo: {pdf_path} | País: {pais}")
    pais = (pais or 'ES').upper()
    texto, confianza_ocr_base = extract_pdf_text(pdf_path)

    datos = DatosFactura(pais=pais, texto_preview=texto[:600])
    conf = {c: 0.0 for c in
            ("consumo", "periodo", "fecha_factura", "cups",
             "comercializadora", "direccion", "sociedad", "sede",
             "importe", "potencia", "tarifa", "contrato", "distribuidora")}

    # 1. Comercializadora — se detecta siempre; es lo que decide la plantilla.
    comercial, c_comercial = extraer_comercializadora(texto, pais)
    datos.comercializadora = comercial
    conf['comercializadora'] = c_comercial
    if comercial:
        logger.info(f"  ✓ Comercializadora: {comercial}")
    else:
        zonas_candidatas = ["Endesa", "Iberdrola", "Naturgy", "Repsol", "TotalEnergies"]
        for candidata in zonas_candidatas:
            zonas_zc = extract_pdf_zone_text(pdf_path, candidata, pais)
            txt = zonas_zc.get("comercializadora", "")
            if txt:
                c2, conf2 = extraer_comercializadora(txt, pais)
                if c2 and conf2 > conf["comercializadora"]:
                    datos.comercializadora = c2
                    conf["comercializadora"] = max(conf2, 0.86)
                    comercial = c2
                    break

    # 2. Resolver campos aplicables — ARQUITECTURA DECLARATIVA.
    #    Se filtra por CAMPOS_EXTRAIBLES: los metadatos declarados en la plantilla
    #    (tarifa, potencia, contrato, distribuidora...) describen la factura pero
    #    el pipeline no los implementa, así que no deben aparecer aquí ni influir
    #    en confianza/criterio de revisión.
    campos_decl = plantillas_service.campos_disponibles(pais, comercial) if comercial else None
    if campos_decl is not None:
        campos_aplicables = set(campos_decl) & plantillas_service.CAMPOS_EXTRAIBLES
        # Guardrail: si la plantilla no declara ningún campo extraíble, usar los
        # de defecto. Si no, no se extraería nada y la factura se marcaría como
        # correcta con consumo vacío (y por tanto 0 emisiones) sin avisar.
        if not campos_aplicables:
            logger.warning(
                f"  ⚠️ Plantilla '{comercial}' ({pais}) no declara campos extraíbles "
                f"({campos_decl}) — usando campos por defecto")
            campos_aplicables = set(CAMPOS_EXTRAIBLES_DEFECTO)
    else:
        campos_aplicables = set(CAMPOS_EXTRAIBLES_DEFECTO)
    datos.campos_aplicables = sorted(campos_aplicables)
    plantilla_activa = plantillas_service.get_plantillas().get((pais, comercial)) if comercial else None
    datos.plantilla_codigo = (plantilla_activa or {}).get('codigo')

    zonas_pdf = extract_pdf_zone_text(pdf_path, comercial, pais) if comercial else {}

    # 3. Consumo
    if 'consumo' in campos_aplicables:
        consumo, c_consumo = extraer_consumo(texto, comercializadora=comercial, pais=pais)
        if zonas_pdf.get("consumo"):
            consumo_z, c_consumo_z = extraer_consumo(zonas_pdf["consumo"], comercializadora=comercial, pais=pais)
            if consumo_z and (not consumo or c_consumo_z > c_consumo):
                consumo, c_consumo = consumo_z, max(c_consumo_z, 0.89)
        datos.consumo_kwh = consumo
        datos.consumo_mwh = kwh_a_mwh(consumo) if consumo else None
        conf['consumo'] = c_consumo
        if consumo:
            logger.info(f"  ✓ Consumo: {consumo} kWh (conf {c_consumo:.2f})")
        else:
            datos.errores.append("No se detectó consumo en kWh")
    else:
        conf['consumo'] = None
        logger.debug(f"  – Consumo no aplicable (plantilla: {comercial})")

    # 4. Período
    if 'periodo' in campos_aplicables:
        ini, fin, dias, c_periodo = extraer_periodo_facturacion(texto, pais)
        if zonas_pdf.get("periodo"):
            ini_z, fin_z, dias_z, c_periodo_z = extraer_periodo_facturacion(zonas_pdf["periodo"], pais)
            if ini_z and (not ini or c_periodo_z > c_periodo):
                ini, fin, dias, c_periodo = ini_z, fin_z, dias_z, max(c_periodo_z, 0.87)
        if not ini:
            ini_r, fin_r, dias_r, c_periodo_r = _extraer_periodo_regla(texto, comercial, pais)
            if ini_r:
                ini, fin, dias, c_periodo = ini_r, fin_r, dias_r, c_periodo_r
        if not ini and zonas_pdf.get("periodo"):
            ini_r, fin_r, dias_r, c_periodo_r = _extraer_periodo_regla(zonas_pdf["periodo"], comercial, pais)
            if ini_r:
                ini, fin, dias, c_periodo = ini_r, fin_r, dias_r, c_periodo_r
        datos.periodo_inicio, datos.periodo_fin, datos.dias_facturados = ini, fin, dias
        conf['periodo'] = c_periodo
        if ini:
            datos.mes = ini[:7]
            logger.info(f"  ✓ Período: {ini} → {fin} ({dias}d) (conf {c_periodo:.2f})")
        else:
            datos.errores.append("No se detectó período de facturación")
    else:
        conf['periodo'] = None

    # 5. Fecha de factura
    if 'fecha_factura' in campos_aplicables:
        fecha_fac, c_fecha = extraer_fecha_factura(texto, comercial, pais)
        if zonas_pdf.get("periodo") and not fecha_fac:
            fecha_z, c_fecha_z = extraer_fecha_factura(zonas_pdf["periodo"], comercial, pais)
            if fecha_z:
                fecha_fac, c_fecha = fecha_z, max(c_fecha_z, 0.84)
        datos.fecha_factura = fecha_fac
        conf['fecha_factura'] = c_fecha
        if fecha_fac and not datos.mes:
            datos.mes = fecha_fac[:7]
    else:
        conf['fecha_factura'] = None

    # 6. Sociedad
    if 'sociedad' in campos_aplicables:
        sociedad, c_sociedad = extraer_sociedad(texto, comercial, pais)
        datos.sociedad = sociedad
        conf['sociedad'] = c_sociedad
    else:
        conf['sociedad'] = None

    # 7. Dirección de suministro
    if 'direccion' in campos_aplicables:
        direccion, c_dir = extraer_direccion_suministro(texto, comercial, pais)
        if zonas_pdf.get("cups") and not direccion:
            direccion_z, c_dir_z = extraer_direccion_suministro(zonas_pdf["cups"], comercial, pais)
            if direccion_z:
                direccion, c_dir = direccion_z, max(c_dir_z, 0.70)
        datos.direccion_suministro = direccion
        conf['direccion'] = c_dir
    else:
        conf['direccion'] = None

    # 8. CUPS — nunca aplicará a documentos de repercusión típicos
    if 'cups' in campos_aplicables:
        cups, c_cups = extraer_cups(texto)
        if zonas_pdf.get("cups"):
            cups_z, c_cups_z = extraer_cups(zonas_pdf["cups"])
            if cups_z and (not cups or c_cups_z > c_cups):
                cups, c_cups = cups_z, max(c_cups_z, 0.85)
        if not cups:
            cups_r, c_cups_r = _extraer_cups_regla(texto, comercial, pais)
            if cups_r:
                cups, c_cups = cups_r, c_cups_r
        datos.cups = cups
        conf["cups"] = c_cups
    else:
        conf['cups'] = None

    # 8b. Campos comerciales y técnicos del contrato.
    #     No entran en FIELD_WEIGHTS a propósito: la confianza global mide
    #     cuánto nos fiamos del dato relevante para la huella de carbono, y
    #     estos campos no participan en ningún cálculo de emisiones. Ponderarlos
    #     haría que una factura con el consumo perfectamente leído bajase de
    #     confianza solo por no encontrar la referencia de contrato.
    if 'importe' in campos_aplicables:
        importe, c_importe = extraer_importe(texto, comercial, pais)
        datos.importe_total = importe
        # La divisa se fija siempre que haya importe: un número sin moneda no
        # es agregable en un portal con España, Argentina, México...
        datos.moneda = moneda_de_pais(pais) if importe is not None else None
        conf['importe'] = c_importe
        if importe is not None:
            logger.info(f"  ✓ Importe: {importe} {datos.moneda} (conf {c_importe:.2f})")
    else:
        conf['importe'] = None

    if 'potencia' in campos_aplicables:
        potencia, c_pot = extraer_potencia(texto, comercial, pais)
        datos.potencia_kw = potencia
        conf['potencia'] = c_pot
        if potencia is not None:
            logger.info(f"  ✓ Potencia contratada: {potencia} kW (conf {c_pot:.2f})")
    else:
        conf['potencia'] = None

    if 'tarifa' in campos_aplicables:
        tarifa, c_tar = extraer_tarifa(texto, comercial, pais)
        datos.tarifa = tarifa
        conf['tarifa'] = c_tar
        if tarifa:
            logger.info(f"  ✓ Tarifa: {tarifa} (conf {c_tar:.2f})")
    else:
        conf['tarifa'] = None

    if 'contrato' in campos_aplicables:
        contrato, c_con = extraer_contrato(texto, comercial, pais)
        datos.contrato = contrato
        conf['contrato'] = c_con
        if contrato:
            logger.info(f"  ✓ Contrato: {contrato} (conf {c_con:.2f})")
    else:
        conf['contrato'] = None

    if 'distribuidora' in campos_aplicables:
        distri, c_dis = extraer_distribuidora(texto, comercial, pais)
        datos.distribuidora = distri
        conf['distribuidora'] = c_dis
        if distri:
            logger.info(f"  ✓ Distribuidora: {distri} (conf {c_dis:.2f})")
    else:
        conf['distribuidora'] = None

    # 9. Confianza global — renormalizada sobre campos_aplicables
    datos.confianza_global = recalcular_confianza_global(conf, campos_aplicables=campos_aplicables)
    if 'consumo' in campos_aplicables and not datos.consumo_kwh:
        datos.confianza_global *= 0.2
    datos.confianza_por_campo = conf

    # 10. ¿Requiere revisión? — solo sobre campos críticos que ADEMÁS aplican
    umbral = getattr(config, 'UMBRAL_REVISION', 0.75)
    campos_criticos_config = getattr(config, 'CAMPOS_CRITICOS_REVISION', ['consumo', 'periodo', 'cups'])
    campos_criticos_efectivos = [c for c in campos_criticos_config if c in campos_aplicables]
    datos.requiere_revision = any((conf.get(c) or 0.0) < umbral for c in campos_criticos_efectivos)

    # 11. Detección de inconsistencias (QW7 — sin cambios de lógica interna;
    #     los checks ya usan "if datos.X and datos.Y" y se saltan solos
    #     cuando un campo no aplicable queda en None)
    incidencias_obj = detectar_inconsistencias(datos)
    mensajes = [inc['mensaje'] for inc in incidencias_obj]
    datos.incidencias_estructuradas = incidencias_obj
    datos.inconsistencias = mensajes
    datos.advertencias = mensajes
    if incidencias_obj:
        logger.warning(f"  ⚠️ Inconsistencias detectadas: {mensajes}")
        tipos_criticos = {"periodo_dias_incoherente", "anio_incoherente"}
        if any(inc['tipo'] in tipos_criticos for inc in incidencias_obj):
            datos.requiere_revision = True

    datos.exito = ('consumo' not in campos_aplicables) or (datos.consumo_kwh is not None)

    if datos.exito:
        logger.info(f"✅ Extracción OK — confianza global: {datos.confianza_global:.2f} "
                    f"(plantilla: {datos.plantilla_codigo or 'genérica'})")
    else:
        logger.warning(f"⚠️ Extracción incompleta: {datos.errores}")

    return datos
    

