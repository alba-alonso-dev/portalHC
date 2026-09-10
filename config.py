"""
Configuración centralizada del Portal de Datos Ambientales Hiberus.

NOTA SOBRE FACTORES DE EMISIÓN:
  Los valores de FACTORES_EMISION se usan ÚNICAMENTE como seed inicial en
  las migraciones de base de datos. La fuente de verdad en producción es la
  tabla `factores_emision` en la BD. No acceder a este dict desde servicios
  de cálculo — usar siempre services/emisiones_service.obtener_factor().

NOTA SOBRE UPLOAD_FOLDER:
  Ruta raíz para almacenamiento local de PDFs.
  Utilizada por services/documento_service.LocalDocumentoStorage.
  Para cambiar a SharePoint en Fase 4, establecer DOCUMENTO_STORAGE=sharepoint
  en variables de entorno — el resto del código no cambia.
"""

import os

# ── Umbral de confianza OCR para requerir revisión manual (0-1) ──
UMBRAL_REVISION = 0.75

# ── Campos cuya baja confianza fuerza revisión manual (QW4) ─────────────────
# Antes solo forzaban revisión consumo/periodo/cups; sociedad y comercializadora
# tienen peso en FIELD_WEIGHTS (ocr_quality_service) pero no forzaban revisión
# por sí solas, aunque son críticas para atribuir la factura a la entidad legal
# correcta en el reporting ESG (ranking por sociedad del informe GHG).
CAMPOS_CRITICOS_REVISION = ['consumo', 'periodo', 'cups', 'sociedad', 'comercializadora']

# ── Rangos de validación compartidos (QW5) ───────────────────────────────────
# Antes cada módulo (extraccion_service, ocr_quality_service, lote_service)
# tenía sus propios límites hardcodeados y a veces distintos entre sí para el
# mismo concepto. Centralizados aquí para que exista una única fuente de verdad.
ANIO_MIN_FACTURA = 2015     # ninguna factura anterior a esta fecha es plausible
ANIO_MAX_OFFSET = 1         # margen sobre el año actual (año_actual + offset)
PERIODO_DIAS_MIN = 15       # período de facturación mínimo plausible
PERIODO_DIAS_MAX = 95       # período de facturación máximo plausible
CONSUMO_KWH_DIA_MIN = 0.05  # bound físico absoluto, independiente del histórico de sede
CONSUMO_KWH_DIA_MAX = 10000.0

# ── Carpeta de subida de documentos PDF ──────────────────────────────────────
# Usada por services/documento_service.LocalDocumentoStorage.
# Para SharePoint (Fase 4): establecer DOCUMENTO_STORAGE=sharepoint en .env.
# En contenedor se puede sobreescribir con UPLOAD_FOLDER para apuntar a un volumen
# persistente (p. ej. /data/uploads).
_DEFAULT_UPLOAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', _DEFAULT_UPLOAD)

# ── Sociedades del grupo Hiberus (CIF → nombre legal) ──────────────
# Ampliar con los CIFs reales del grupo antes de producción
SOCIEDADES_CONOCIDAS: dict[str, str] = {
    # "B12345678": "HIBERUS TECNOLOGÍA S.L.",
    # "B87654321": "HIBERUS DIGITAL S.L.",
}

# ── FACTORES_EMISION — solo seed inicial ─────────────────────────────────────
# ATENCIÓN: estos valores se cargan en BD al arrancar la aplicación por primera
# vez (migrations.py). Después, la BD es la única fuente de verdad.
# Actualizar SOLO si se añade un nuevo país sin datos en BD todavía.
FACTORES_EMISION = {
    "AR": {
        "2026": 0.118,
        "2025": 0.118,
        "2024": 0.125,
        "fuente": "SNIGEIAR",
        "url": "https://www.minem.gob.ar/snigeiar"
    },
    "CO": {
        "2026": 0.263,
        "2025": 0.263,
        "2024": 0.268,
        "fuente": "UPME",
        "url": "https://www1.upme.gov.co/"
    },
    # PROVISIONAL — verificar contra el dato anual publicado por la CNE antes de
    # reportar. Las actas de la sede de Santiago no traen kWh, así que hoy este
    # factor no llega a aplicarse a ninguna factura.
    "CL": {
        "2026": 0.400,
        "2025": 0.400,
        "2024": 0.400,
        "fuente": "CNE Energía Abierta (provisional, pendiente de verificar)",
        "url": "http://energiaabierta.cl/visualizaciones/factor-de-emision-sic-sing/"
    },
    "EC": {
        "2026": 0.298,
        "2025": 0.298,
        "2024": 0.302,
        "fuente": "ARCONEL",
        "url": "https://www.regulacionelectrica.gob.ec/"
    },
    "MX": {
        "2026": 0.348,
        "2025": 0.348,
        "2024": 0.352,
        "fuente": "CRE",
        "url": "https://datos.cre.gob.mx/"
    },
    "ES": {
        "2026": 0.187,
        "2025": 0.187,
        "2024": 0.215,
        "fuente": "MITECO v32",
        "url": "https://www.miteco.gob.es/"
    }
}

# Mapeo de comercializadoras por país
COMERCIALIZADORAS = {
    "AR": ["Edesur", "Edenor", "EDES"],
    "CL": ["Enel Distribución", "CGE", "Administración edificio"],
    "CO": ["Codensa", "EMCALI", "CELSIA"],
    "EC": ["EEQSA", "CNEL", "Ambato"],
    "MX": ["CFE", "LEC", "Privado"],
    "ES": ["Endesa", "Iberdrola", "Naturgas", "EDP", "Viesgo"]
}

SEDES_PAISES = {
    "AR": ["Buenos Aires"],
    "CL": ["Santiago"],
    "CO": ["Bogotá"],
    "EC": ["Guayaquil", "Quito"],
    "MX": ["Querétaro"],
    "ES": ["Almería", "Asturias", "Barcelona", "Bilbao", "Granada", "Lleida",
           "Logroño", "Madrid", "Pamplona", "Santander", "Valencia",
           "Valladolid", "Vitoria", "Zaragoza"]
}

# ── FACTORES_RESIDUOS — pendiente módulo de residuos (Fase 5+) ───────────────
# Valores de referencia (kg CO₂eq / kg residuo).
# No se usan en producción hasta implementar el módulo de residuos.
FACTORES_RESIDUOS = {
    "papel":         0.0012,
    "plastico":      0.0034,
    "vidrio":        0.0008,
    "metal":         0.0045,
    "residuo_comun": 0.0015,
    "organico":      0.0005,
}
