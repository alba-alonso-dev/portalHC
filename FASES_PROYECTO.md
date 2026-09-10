# Fases del proyecto — Portal de Datos Ambientales Hiberus

## Resumen ejecutivo

El **Portal de Datos Ambientales Hiberus** ha evolucionado desde un procesador OCR de facturas eléctricas a una plataforma interna de reporting ESG con trazabilidad, control de calidad del dato, recálculo histórico, alertas y seguimiento de objetivos.  
El stack operativo actual se apoya en **Python 3.13, Flask 3.1, SQLite (WAL), PaddleOCR, pdfplumber, openpyxl y una SPA con partials Jinja y JavaScript vanilla**.

> Nota de trazabilidad: los archivos listados por fase son los **principales artefactos actualmente presentes en el repositorio** que materializan cada entrega. En varias fases hubo refactorizaciones posteriores, por lo que algunos componentes iniciales quedaron absorbidos en módulos más maduros.

---

## Fase 1 — Automatización de facturación eléctrica

### Objetivo principal
Automatizar la carga y procesamiento de facturas eléctricas en PDF para convertir documentos en registros estructurados con consumo, período, metadatos de suministro y emisiones calculadas.

### Entregables
- Carga individual de facturas PDF.
- Carga masiva en lote con seguimiento de estado.
- OCR y extracción automática de campos.
- Extracción de:
  - consumo kWh / MWh,
  - período de facturación,
  - comercializadora,
  - CUPS,
  - sociedad,
  - dirección del suministro.
- Cálculo automático de emisiones de CO2e por factura.
- Persistencia en SQLite.
- Exportación inicial a Excel.
- SPA web básica para operación interna.

### Archivos creados/modificados
- `app.py`
- `config.py`
- `database\connection.py`
- `database\migrations.py`
- `routes\facturas.py`
- `routes\configuracion.py`
- `routes\exportacion.py`
- `services\ocr_service.py`
- `services\extraccion_service.py`
- `services\extractor_service.py`
- `services\lote_service.py`
- `services\emisiones_service.py`
- `templates\index.html`
- `requirements.txt`

### Decisiones técnicas clave
- **SQLite** como base de datos embebida para reducir complejidad operativa.
- **SPA en HTML/JS vanilla** para evitar build step, dependencias frontend y pipeline Node.
- **PaddleOCR como fallback OCR** sobre PDFs sin capa de texto; `pdfplumber` se usa como ruta rápida cuando el PDF ya contiene texto digital.
- **Persistencia por factura** con cálculo de emisiones en el momento de la carga.
- **Modelo simple inicial** centrado en electricidad, con estructura preparada para crecer.

### Bugs corregidos
- Robustez en carga de PDFs y validación de archivo.
- Gestión de facturas con revisión manual cuando la confianza OCR cae por debajo de umbral.
- Mejora en tratamiento de PDFs escaneados frente a PDFs digitales.

### Estado actual
**Completada y operativa.**  
La funcionalidad base sigue siendo el núcleo del portal y continúa utilizándose como entrada de datos para el resto de módulos ESG.

---

## Fase 2 — Gestión y trazabilidad de factores de emisión

### Objetivo principal
Separar los factores de emisión del código estático y convertirlos en datos versionados, auditables y gestionables por API.

### Entregables
- Tabla `fuentes_emision` para registrar fuentes bibliográficas y regulatorias.
- Migración del modelo de `factores_emision` a esquema versionado.
- Tabla `factores_historial` para trazabilidad completa de cambios.
- Relación `facturas.factor_version_id` para saber con qué versión exacta se calculó cada factura.
- API CRUD de factores y de fuentes.

### Archivos creados/modificados
- `database\migrations_fase2.py`
- `routes\factores_admin.py`
- `routes\fuentes.py`
- `services\factores_service.py`
- `services\emisiones_service.py`
- `app.py`

### Decisiones técnicas clave
- **Versionado inmutable** de factores: se crea una nueva versión, no se sobreescribe la anterior.
- **Fuente de verdad en BD**: `config.py` queda solo como seed inicial.
- **Trazabilidad por FK** desde factura a versión de factor.
- **Historial explícito** (`factores_historial`) para responder a auditoría: quién cambió qué, cuándo y con qué resultado.

### Bugs corregidos
- Eliminación del acoplamiento entre cálculo de emisiones y factores hardcodeados.
- Resolución retrocompatible de `factor_version_id` para facturas históricas.

### Estado actual
**Completada y consolidada.**  
Es la base de la auditabilidad del cálculo de emisiones y habilita los recálculos masivos posteriores.

---

## Fase 3 — Calidad del dato y estimaciones

### Objetivo principal
Cubrir huecos de facturación y elevar la calidad analítica del sistema incorporando estimaciones formales y detección de períodos faltantes.

### Entregables
- Tabla `estimaciones`.
- Tabla `periodos_faltantes`.
- Tabla `lotes_recalculo`.
- Tabla `recalculos_historial`.
- Nuevas columnas en `facturas` para distinguir dato real vs estimado y almacenar resultados de recálculo.
- Motor de estimación con 6 métodos iniciales:
  1. `media_historica`
  2. `mismo_mes_anio_anterior`
  3. `adyacente`
  4. `manual`
  5. `sede_similar`
  6. `ponderado`
- API de gestión de estimaciones.
- Sustitución estimado → real cuando llega factura real.

### Archivos creados/modificados
- `database\migrations_fase3.py`
- `routes\estimaciones.py`
- `routes\recalculo.py`
- `services\estimacion_service.py`
- `services\gaps_service.py`
- `services\recalculo_service.py`
- `services\dashboard_service.py`
- `app.py`

### Decisiones técnicas clave
- **No sobrescribir históricos**: los recálculos se registran aparte, sin destruir el valor original.
- **Modelo dual real/estimado** dentro del dominio de facturas y periodos.
- **Gestión explícita de huecos** con `periodos_faltantes`, en lugar de inferirlos implícitamente en consultas.
- **Estimaciones persistidas** y no solo calculadas al vuelo, para poder auditar y medir error posterior.

### Bugs corregidos
- Mejora del control de períodos faltantes por sede/mes.
- Mayor robustez en reconciliación cuando posteriormente llega factura real.

### Estado actual
**Completada y plenamente integrada** con dashboard, trazabilidad e informe GHG.

---

## Fase 3.5 — Consolidación y endurecimiento arquitectónico

### Objetivo principal
Preparar el sistema para escalar funcionalmente sin romper histórico, añadiendo tablas maestras, audit log, deduplicación documental y modelo de suministros.

### Entregables
- Tablas maestras:
  - `paises`
  - `tipos_energia`
  - `sedes`
  - `comercializadoras`
- Tabla `audit_log`.
- Tabla `facturas_historial`.
- Tabla `suministros`.
- Columnas nuevas en `facturas`:
  - `sha256_documento`
  - `suministro_id`
  - `duplicado_potencial`
  - `external_source`
  - `external_doc_id`
  - `external_doc_url`
  - `fecha_anulacion`
  - `updated_at`
  - `consumo_valor`
  - `consumo_unidad`
- Triggers de `updated_at` / `modificado_en`.
- Índices de rendimiento para consultas críticas.
- Preparación para integración documental externa (`fuentes_documentos`, `sync_log`).

### Archivos creados/modificados
- `database\migrations_refactor.py`
- `database\migrations_mejoras.py`
- `services\audit_service.py`
- `services\documento_service.py`
- `services\extractor_service.py`
- `services\lote_service.py`
- `routes\facturas.py`

### Decisiones técnicas clave
- **Migraciones aditivas e idempotentes** como norma de compatibilidad histórica.
- **SHA256 del PDF** como mecanismo de deduplicación documental a nivel de contenido.
- **Soft delete** en facturas (`fecha_anulacion`) en lugar de borrado físico.
- **Modelo `suministros`** como entidad raíz para soportar multi-CUPS y nuevos suministros en fases futuras.
- **Abstracción `DocumentoStorage`** para desacoplar almacenamiento local y futura integración SharePoint.

### Bugs corregidos
- Mejor trazabilidad de cambios manuales en facturas.
- Corrección de riesgos de concurrencia en migraciones mediante locks de proceso e hilo.
- Mitigación de problemas de thread-safety de PaddleOCR serializando su uso.

### Estado actual
**Completada.**  
Es la capa que estabiliza el producto antes del salto a reporting ESG y nuevas integraciones.

---

## Fase 4 — Reporting ESG

### Objetivo principal
Transformar el portal desde un procesador documental a una herramienta de reporting ESG y seguimiento operativo.

### Entregables
- Dashboard ESG con KPIs de:
  - emisiones,
  - cobertura,
  - calidad,
  - facturación,
  - evolución mensual.
- Sistema de alertas automáticas.
- Informe GHG Protocol en Excel.
- Rankings y estadísticas por sede y sociedad.
- Comparativas interanuales.

### Archivos creados/modificados
- `database\migrations_fase4.py`
- `routes\dashboard.py`
- `routes\alertas.py`
- `routes\ghg_report.py`
- `routes\estadisticas.py`
- `services\dashboard_service.py`
- `services\alertas_service.py`
- `services\ghg_report_service.py`
- `services\emisiones_service.py`
- `templates\index.html`
- `app.py`

### Decisiones técnicas clave
- **KPIs servidos por API Flask** y consumidos por la SPA.
- **Alertas configurables** con tabla `alertas_config`.
- **GHG Protocol exportado en Excel** como formato operativo inmediato para reporting corporativo.
- **Separación por capas**: rutas ligeras, lógica en servicios y persistencia en BD.

### Bugs corregidos
- Normalización de consultas agregadas para dashboard.
- Ajustes de rendimiento mediante índices adicionales en alertas y entidades analíticas.

### Estado actual
**Completada y en uso.**  
Supone el primer nivel real de explotación ESG sobre la información capturada.

---

## Fase 5 — Afinado y validación

### Objetivo principal
Mejorar precisión OCR, enriquecer el modelo documental y cerrar huecos funcionales detectados tras el uso real del sistema.

### Entregables
- 2 métodos de estimación nuevos:
  - `por_dias`
  - `estacional`
- Campo `ejercicio` en facturas.
- Campo `cups` asegurado en persistencia e índices.
- Detección de inconsistencias entre campos extraídos.
- Organización documental por ejercicio / país / sede.
- Tabla `documentos_indice`.
- Filtros `pais` / `sede` en KPIs del dashboard.
- Hoja adicional del informe GHG por sociedad.
- Ranking de sociedades.

### Archivos creados/modificados
- `database\migrations_fase5.py`
- `services\documento_service.py`
- `services\estimacion_service.py`
- `services\ghg_report_service.py`
- `services\alertas_service.py`
- `services\lote_service.py`
- `services\emisiones_service.py`
- `routes\configuracion.py`
- `routes\dashboard.py`
- `routes\ghg_report.py`
- `templates\index.html`

### Decisiones técnicas clave
- **Índice documental persistido** para explotar cobertura y preparar SharePoint.
- **Organización física de PDFs por ejercicio** para orden operativo y futura migración.
- **Validación de coherencia OCR** como señal explícita, no solo como confianza baja.
- **Análisis por sociedad** como dimensión de reporting ESG adicional.

### Bugs corregidos
- **Corrección del bug de `DatosFactura` duplicada / clase sobreescrita**, eliminando definiciones inconsistentes y unificando el modelo de salida del extractor.
- Refuerzo de reglas específicas de comercializadoras españolas.
- Mejora de consistencia entre `consumo_kwh`, `consumo_mwh`, fechas y CUPS.

### Estado actual
**Completada.**  
Es la fase de estabilización funcional previa a la capa ejecutiva ESG.

---

## Fase 6 (iteración 1) — Gestión ESG y toma de decisiones

### Objetivo principal
Subir de nivel desde reporting descriptivo a control de objetivos, proyección y detección avanzada de anomalías.

### Entregables
- Módulo de objetivos ESG:
  - CRUD por sede / sociedad / país / año,
  - seguimiento real vs objetivo,
  - semáforo,
  - proyección de cierre.
- Dashboard ejecutivo ESG.
- Proyección de cierre anual:
  - pro-rata,
  - ajuste estacional si hay histórico suficiente.
- 4 detectores avanzados de anomalías:
  - z-score,
  - cambio interanual brusco,
  - período anómalo,
  - incoherencia OCR.
- Reconciliación automática estimado → real con métricas por método.
- Tabla `metodo_estimacion_metricas`.
- Corrección crítica de factores en kgCO2/MWh.
- Corrección del índice SHA256 para permitir duplicados controlados.

### Archivos creados/modificados
- `database\migrations_fase6.py`
- `routes\objetivos.py`
- `routes\dashboard.py`
- `services\objetivos_service.py`
- `services\dashboard_service.py`
- `services\alertas_service.py`
- `services\estimacion_service.py`
- `services\lote_service.py`
- `app.py`

### Decisiones técnicas clave
- **Objetivos flexibles por granularidad**: global, país, sociedad o sede.
- **Semáforo simple y explicable**:
  - verde: real <= objetivo,
  - amarillo: hasta +20% sobre objetivo,
  - rojo: >20% sobre objetivo.
- **Proyección de cierre híbrida**:
  - pro-rata como método base,
  - estacional si hay suficiente histórico.
- **Reconciliación automática** como mecanismo de aprendizaje operativo del motor de estimación.
- **Corrección de unidad de factores**: la fórmula espera kgCO2/MWh y la BD debía reflejar esa unidad.

### Bugs corregidos
- **Error crítico de unidad en factores de emisión**:
  - antes: valores cargados como tCO2/MWh (`0.187`)
  - correcto: kgCO2/MWh (`187`)
  - impacto: recálculo de 166 facturas.
- **`UNIQUE INDEX` sobre `sha256_documento`**:
  - problema: bloqueaba la inserción de duplicados antes de poder marcarlos,
  - solución: reemplazo por índice normal y detección en capa de aplicación.

### Estado actual
**Completada en su iteración 1.**  
La fase 6 continúa abierta para nuevas iteraciones: nuevos suministros, notificaciones, objetivos por scope, benchmark y mejoras de cuadro de mando.

---

## Estado global actual

### Completado
- Fase 1
- Fase 2
- Fase 3
- Fase 3.5
- Fase 4
- Fase 5
- Fase 6 — iteración 1

### Abierto / pendiente
- Fase 6 — iteraciones 2 a 4
- Fase 7 — integración Microsoft
- Fase 8 — inteligencia ESG

### Capacidades ya maduras
- OCR + extracción documental.
- Trazabilidad de factores.
- Recálculo histórico.
- Estimaciones y cobertura.
- Dashboard ESG.
- Alertas automáticas.
- Informe GHG.
- Objetivos ESG y proyección.

### Capacidades aún pendientes
- Autenticación y autorización.
- Integración SharePoint / Azure AD / Power BI.
- Nuevos suministros distintos de electricidad.
- Notificaciones externas.
- Analítica predictiva avanzada.

---

## Mapa rápido de módulos por fase

| Fase | Núcleo funcional | Tablas / componentes clave |
|---|---|---|
| 1 | OCR y facturación | `facturas`, `lotes`, OCR, extracción, exportación |
| 2 | Factores de emisión | `factores_emision`, `fuentes_emision`, `factores_historial` |
| 3 | Estimaciones y recálculo | `estimaciones`, `periodos_faltantes`, `lotes_recalculo`, `recalculos_historial` |
| 3.5 | Consolidación | `audit_log`, `facturas_historial`, `suministros`, tablas maestras |
| 4 | Reporting ESG | `alertas`, `alertas_config`, dashboard, GHG report |
| 5 | Afinado y validación | `documentos_indice`, nuevos métodos de estimación, filtros y ranking sociedades |
| 6.1 | Gestión ESG | `objetivos_emision`, `metodo_estimacion_metricas`, proyección, semáforo, anomalías avanzadas |

