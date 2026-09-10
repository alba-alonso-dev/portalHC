"""
Capa de abstracción para extracción de datos de facturas — patrón Registry.

Diseño
──────
ExtractorFactura   : ABC con contrato mínimo (extraer + tipo_energia).
ExtractorElectricidad : implementación actual — delega en extraccion_service.py.
ExtractorFactory   : registro de extractores por tipo_energia.

Uso
───
    from services.extractor_service import ExtractorFactory

    extractor = ExtractorFactory.get('electricidad')
    datos = extractor.extraer(pdf_path, pais)      # → DatosFactura

Añadir un nuevo suministro en Fase 5
─────────────────────────────────────
    1. Crear ExtractorGas (o ExtractorAgua, …) en este mismo módulo
       (o en un módulo propio si la lógica es compleja).
    2. Registrarlo:
           ExtractorFactory.register('gas', ExtractorGas)
    3. No modificar lote_service ni routes/facturas — usan la factoría.

Compatibilidad
──────────────
extraccion_service.extraer_datos_factura() permanece sin cambios.
ExtractorElectricidad es un thin-wrapper que la llama directamente.
DatosFactura se importa desde extraccion_service (única definición).
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ── Interfaz base ─────────────────────────────────────────────────────────────

class ExtractorFactura(ABC):
    """
    Contrato para extractores de facturas.

    Cada tipo de suministro implementa su propia subclase:
      - Lee el PDF en el formato que le corresponde.
      - Devuelve siempre DatosFactura con los campos que apliquen.
      - Campos no aplicables quedan como None (ej: cups para gas).
    """

    @property
    @abstractmethod
    def tipo_energia(self) -> str:
        """Código del tipo de energía: 'electricidad', 'gas', 'agua', …"""

    @abstractmethod
    def extraer(self, pdf_path: str, pais: str):
        """
        Extrae datos de una factura en PDF.

        Parameters
        ----------
        pdf_path : ruta local al PDF (requerida para OCR/pdfplumber).
        pais     : código ISO2 del país ('ES', 'AR', 'CO'…).

        Returns
        -------
        DatosFactura  (importada desde services.extraccion_service)
        """


# ── Implementación electricidad ───────────────────────────────────────────────

class ExtractorElectricidad(ExtractorFactura):
    """
    Extractor de facturas eléctricas.

    Thin-wrapper sobre extraccion_service.extraer_datos_factura().
    Toda la lógica de extracción permanece en extraccion_service.py
    para no romper comportamiento ni tests existentes.
    """

    @property
    def tipo_energia(self) -> str:
        return 'electricidad'

    def extraer(self, pdf_path: str, pais: str):
        # Import local para evitar circular imports durante carga del módulo
        from services.extraccion_service import extraer_datos_factura
        return extraer_datos_factura(pdf_path, pais)


# ── Esqueletos para Fase 5 (activo=False en tipos_energia hasta que se implemente) ──

class _ExtractorNoImplementado(ExtractorFactura):
    """
    Placeholder para tipos de suministro aún no implementados.
    Lanza NotImplementedError con instrucciones claras en lugar de fallar silenciosamente.
    """

    def __init__(self, tipo: str):
        self._tipo = tipo

    @property
    def tipo_energia(self) -> str:
        return self._tipo

    def extraer(self, pdf_path: str, pais: str):
        raise NotImplementedError(
            f"El extractor para '{self._tipo}' aún no está implementado. "
            f"Para añadirlo: crear clase Extractor{self._tipo.capitalize()} "
            f"en services/extractor_service.py y registrarla con "
            f"ExtractorFactory.register('{self._tipo}', Extractor{self._tipo.capitalize()})."
        )


# ── Factoría ──────────────────────────────────────────────────────────────────

class ExtractorFactory:
    """
    Registro de extractores por tipo_energia.

    Uso típico
    ──────────
        extractor = ExtractorFactory.get('electricidad')
        datos     = extractor.extraer(pdf_path, pais)

    Registro de un nuevo extractor
    ────────────────────────────────
        ExtractorFactory.register('gas', ExtractorGas)
    """

    _registry: dict[str, type[ExtractorFactura]] = {}

    @classmethod
    def register(cls, tipo: str, extractor_class: type[ExtractorFactura]) -> None:
        """Registra un extractor para un tipo de energía."""
        cls._registry[tipo.lower()] = extractor_class
        logger.debug(f"[ExtractorFactory] Registrado: '{tipo}' -> {extractor_class.__name__}")

    @classmethod
    def get(cls, tipo: str) -> ExtractorFactura:
        """
        Devuelve una instancia del extractor para el tipo indicado.

        Raises
        ------
        ValueError si el tipo no está registrado.
        """
        tipo_lower = tipo.lower() if tipo else 'electricidad'
        klass = cls._registry.get(tipo_lower)
        if klass is None:
            tipos_disponibles = list(cls._registry.keys())
            raise ValueError(
                f"No hay extractor registrado para tipo_energia='{tipo}'. "
                f"Disponibles: {tipos_disponibles}"
            )
        return klass()

    @classmethod
    def tipos_disponibles(cls) -> list[str]:
        """Lista los tipos de energía con extractor registrado."""
        return list(cls._registry.keys())


# ── Registro inicial ──────────────────────────────────────────────────────────
# Solo electricidad está implementado en Fases 1-3.
# Los demás se registran como placeholders para detectar llamadas prematuras.

ExtractorFactory.register('electricidad', ExtractorElectricidad)


def _make_placeholder(tipo_str: str) -> type:
    """Crea una clase placeholder para un tipo de suministro no implementado."""

    class _Placeholder(_ExtractorNoImplementado):
        def __init__(self):
            super().__init__(tipo_str)

        @property
        def tipo_energia(self) -> str:
            return tipo_str

    _Placeholder.__name__ = f'_Extractor{tipo_str.capitalize()}Placeholder'
    return _Placeholder


for _tipo_pendiente in ('gas', 'agua', 'residuos', 'viajes'):
    ExtractorFactory.register(_tipo_pendiente, _make_placeholder(_tipo_pendiente))
