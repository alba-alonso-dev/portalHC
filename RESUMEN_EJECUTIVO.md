# Resumen ejecutivo — Portal de Datos Ambientales de Hiberus

## 1. Objetivo del proyecto y problema que resuelve

El Portal de Datos Ambientales de Hiberus centraliza la **captura, validación, trazabilidad, cálculo y explotación analítica** de facturas energéticas para convertirlas en datos ambientales auditables.

El problema de negocio que resuelve es doble:

1. **Operativo**: la información energética llega en PDF, con formatos heterogéneos, sedes repartidas en varios países y revisiones manuales costosas.
2. **ESG / cumplimiento**: el equipo de sostenibilidad necesita transformar esos documentos en métricas fiables de **consumo, emisiones, cobertura y calidad del dato**, con histórico, evidencias y capacidad de reporting compatible con GHG Protocol / CSRD.

La plataforma resuelve ese flujo extremo a extremo:

- ingiere facturas PDF individuales o en lote;
- extrae datos con OCR + parsing específico;
- calcula emisiones con factores versionados por país y año;
- detecta huecos y genera estimaciones controladas;
- registra auditoría y trazabilidad documental;
- expone dashboards, alertas, recálculo histórico y reporting ESG.

La fórmula de negocio implementada es:

```text
tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000
```

## 2. Usuarios objetivo

### Rossana / equipo de sostenibilidad Hiberus

Usuario principal del portal. Necesita:

- consolidar consumos eléctricos por sede, país y sociedad;
- seguir objetivos ESG anuales;
- detectar sedes sin cobertura o con anomalías;
- justificar cada cifra con evidencia documental y factor aplicado;
- exportar información a reporting corporativo, auditoría y dirección.

### Usuarios secundarios

- **Operaciones / backoffice**: subida y revisión de facturas.
- **Administración ESG**: mantenimiento de factores y fuentes.
- **Dirección**: consumo de KPIs ejecutivos, proyección de cierre y semáforo de objetivos.
- **Equipos futuros de BI / integración**: explotación de datos para SharePoint, Power BI o lakehouse.

## 3. Estado actual

El proyecto se encuentra en **Fase 6 — iteración 1 completada**.

### Fases ya completadas

- **Fase 1**: OCR, extracción y carga de facturas.
- **Fase 2**: factores de emisión versionados + fuentes bibliográficas.
- **Fase 3**: estimaciones, huecos de cobertura y calidad del dato.
- **Fase 3.5**: consolidación del modelo y endurecimiento operativo.
- **Fase 4**: dashboard, alertas automáticas e informe GHG.
- **Fase 5**: afinado funcional, índice documental, CUPS e inconsistencias.
- **Fase 6 iteración 1**: objetivos ESG, dashboard ejecutivo, proyección, anomalías avanzadas y reconciliación automática.

### Cobertura geográfica configurada

- **5 países**: ES, AR, CO, EC, MX.
- **19 sedes configuradas** en `config.py`.
- Factores oficiales precargados para 2025:
  - ES: **187.0** kgCO₂/MWh (MITECO v32)
  - AR: **118.0** kgCO₂/MWh (SNIGEIAR)
  - CO: **263.0** kgCO₂/MWh (UPME)
  - EC: **298.0** kgCO₂/MWh (ARCONEL)
  - MX: **348.0** kgCO₂/MWh (CRE)
  - FR: **57.8** kgCO₂/MWh

### Correcciones críticas ya incorporadas en Fase 6

- **Corrección de unidad de factores**: algunos factores estaban almacenados en tCO₂/MWh (`0.187`) cuando la columna y la fórmula requieren kgCO₂/MWh (`187`). La base fue normalizada multiplicando ×1000 donde correspondía.
- **Corrección de índice SHA-256**: `idx_facturas_sha256` dejó de ser `UNIQUE` para permitir insertar duplicados potenciales y marcarlos con `duplicado_potencial=1` sin bloquear el flujo.

## 4. Capacidades implementadas

### 4.1 Ingesta documental

- Subida de **factura individual**.
- Subida de **lotes de PDFs** con procesamiento asíncrono y polling.
- Límite de carga de **50 MB** por archivo.
- Almacenamiento documental por ejercicio con `LocalDocumentoStorage`.
- Cálculo de **SHA-256** del documento para control de duplicados.
- Índice documental por ejercicio / país / sede.

### 4.2 OCR y extracción

- OCR con **PaddleOCR**.
- Normalización a texto plano.
- Extracción con `extraccion_service.py` mediante múltiples patrones regex.
- `DatosFactura` como contrato estructurado de extracción.
- `ExtractorFactory` para soportar nuevos tipos de suministro en el futuro.
- Captura de confianza OCR global y por campo.

### 4.3 Gestión de facturas

- Persistencia de facturas con estado operativo.
- Confirmación manual de campos de baja confianza.
- Historial campo a campo de cambios manuales.
- Soft delete mediante `fecha_anulacion`.
- Descarga/servicio del PDF original desde la capa de almacenamiento.
- Señalización de facturas con `pendiente_revision`, `confirmada`, `anulada`, etc.

### 4.4 Cálculo de emisiones

- Cálculo automático de emisiones por factura.
- Lookup de factor por **país + tipo de energía + año + versión activa**.
- Trazabilidad de la **versión exacta del factor** usada en cada factura.
- Soporte GHG con `scope_ghg` en factores.

### 4.5 Gestión de factores de emisión

- CRUD de factores.
- Versionado inmutable.
- Una sola versión activa por combinación país/tipo/año.
- Historial de cambios sobre factores.
- Gestión de fuentes bibliográficas (`fuentes_emision`).
- Estado de actualización de factores (actualizado / revisar / desactualizado).

### 4.6 Estimaciones y calidad de dato

- Detección de `periodos_faltantes`.
- Creación de estimaciones manuales y automáticas.
- Ocho métodos implementados:
  - `media_historica`
  - `mismo_mes_anio_anterior`
  - `adyacente`
  - `manual`
  - `sede_similar`
  - `ponderado`
  - `por_dias`
  - `estacional`
- Comparativa entre métodos antes de persistir.
- Rechazo o sustitución de estimaciones.
- Reconciliación automática cuando llega la factura real.
- Métricas de error y ranking de precisión por método.

### 4.7 Dashboard y analítica ESG

- Resumen ejecutivo.
- KPIs de emisiones, cobertura, calidad y facturación.
- Evolución mensual.
- Filtros por **año, país y sede**.
- Dashboard ESG ejecutivo de Fase 6.
- Proyección de cierre del ejercicio.
- Semáforo global ESG.

### 4.8 Alertas automáticas

Doce detectores automáticos:

1. falta de factura del mes anterior;
2. OCR bajo;
3. consumo anómalo vs media;
4. duplicado potencial;
5. factor no actualizado;
6. factor con versión antigua;
7. documento no encontrado;
8. recálculo pendiente;
9. anomalía por z-score;
10. cambio interanual brusco;
11. período anómalo;
12. OCR incoherente.

Además:

- resolución e ignorado de alertas;
- severidades `critica`, `media`, `informativa`;
- configuración de umbrales en `alertas_config`.

### 4.9 Reporting y exportación

- Exportación Excel de historial filtrado.
- Informe GHG Protocol en Excel.
- Preview JSON del informe GHG.
- Ranking de emisiones por sociedad.
- Preparación para explotación posterior en Power BI / lakehouse.

### 4.10 Gobierno del dato y auditoría

- `audit_log` inmutable.
- `facturas_historial` para cambios de negocio.
- `recalculos_historial` para trazabilidad de recálculos.
- `sync_log` para futuras integraciones documentales.
- `updated_at` y `export_state` para escenarios CDC / integración incremental.

### 4.11 Objetivos ESG

- Alta, edición y baja lógica de objetivos anuales.
- Objetivos a nivel global, país, sociedad o sede.
- Objetivos absolutos o relativos contra año base.
- Seguimiento automático y semáforo.
- Resumen ESG agregado y sedes en riesgo.

## 5. Arquitectura resumida

### Frontend

- **SPA sin frameworks**: todo el frontend vive en `templates/index.html`.
- JavaScript vanilla + **Fetch API**.
- Bootstrap 5 para layout y Chart.js para visualización.
- Polling para seguimiento de lotes.

### Backend

- **Flask** como servidor HTTP.
- `app.py` registra blueprints especializados por dominio.
- `services/` concentra la lógica de negocio.
- `routes/` expone la API REST/JSON.

### Persistencia

- **SQLite** con `journal_mode=WAL` y `foreign_keys=ON`.
- Migraciones idempotentes por fases.
- Modelo orientado a trazabilidad y auditoría, no solo a captura transaccional.

### Flujo principal

```text
PDF -> PaddleOCR -> extracción estructurada -> validación -> factor de emisión -> factura
    -> auditoría -> cobertura/estimación -> dashboard/alertas/reporting
```

## 6. Roadmap futuro

### Fase 6 — iteraciones pendientes

**Iteración 2**

- endurecimiento del módulo de objetivos (más KPIs agregados y comparativas);
- automatización programada de alertas y reconciliación;
- refinado del motor de proyección con mayor sensibilidad estacional;
- consolidación de datasets ejecutivos para dirección.

**Iteración 3**

- ampliación multi-suministro real (gas, agua, residuos, viajes) activando maestros ya preparados;
- extensión de Scope 1 y Scope 3 con factores específicos;
- reglas avanzadas de benchmark entre sedes y sociedades.

### Fase 7 — industrialización e integraciones

- integración real con **SharePoint** como fuente documental;
- sincronización incremental vía `fuentes_documentos` + `sync_log`;
- dataset de consumo para **Power BI** / Data Lake;
- autenticación, roles y permisos;
- observabilidad operativa y jobs programados.

### Fase 8 — analítica avanzada y compliance

- forecasting avanzado con modelos explicables;
- escenarios de reducción y simulación presupuestaria de carbono;
- reporting CSRD más amplio (narrativa + anexos + evidencias);
- cuadros de mando corporativos multi-entidad;
- workflows de aprobación y cierre mensual ESG.

## 7. Métricas de calidad y cobertura

El portal ya incorpora medición nativa de calidad y cobertura, no solo captura de datos.

### Cobertura

- % de meses **reales**.
- % de meses **estimados**.
- % de meses **faltantes**.
- detalle por sede;
- meses cubiertos por ejercicio;
- meses pendientes por país / sede.

### Calidad

- nº de facturas con OCR bajo;
- confianza OCR media;
- nº de duplicados potenciales;
- nº de consumos anómalos;
- score global de calidad (0-100);
- ranking de sedes con mejor y peor calidad.

### Precisión de estimaciones

- nº de estimaciones validadas con factura real;
- error medio y mediano;
- comparativa real vs estimado;
- MAE y MAPE por método de estimación;
- clasificación cualitativa del método: `excelente`, `bueno`, `aceptable`, `mejorable`.

### Trazabilidad y control

- historial de cambios manuales por factura;
- historial de versiones de factores;
- historial de recálculos;
- evidencia documental indexada por ejercicio.

En conjunto, el proyecto ya no es solo un capturador de facturas: es una **plataforma ESG operativa y auditable** preparada para crecer hacia integración corporativa y reporting regulatorio.
