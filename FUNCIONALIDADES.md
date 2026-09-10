# Funcionalidades actuales del Portal de Datos Ambientales Hiberus

## Alcance actual

El portal gestiona el ciclo completo de **captura, validación, cálculo, trazabilidad y reporting ESG** de facturas eléctricas corporativas.  
La aplicación expone APIs Flask consumidas por una SPA y persiste la información en SQLite con modelo auditable.

---

## 1. Carga y procesamiento de facturas

### 1.1 Carga individual
- Endpoint: `POST /api/procesar`
- Recibe un PDF, país y sede.
- Guarda el documento a través de `DocumentoStorage`.
- Procesa de forma síncrona y devuelve:
  - `factura_id`
  - resumen de datos extraídos
  - si requiere revisión manual
  - advertencias de calidad

### 1.2 Carga en lote
- Endpoint: `POST /api/procesar-lote`
- Permite enviar múltiples PDFs en una sola operación.
- Crea un `lote_id` y lanza procesamiento en background.
- Endpoint de seguimiento: `GET /api/lote/<lote_id>/estado`
- Persiste:
  - número total de archivos,
  - procesados correctamente,
  - procesados con error,
  - resultados parciales y finales.

### 1.3 OCR y extracción
- Usa:
  - `pdfplumber` cuando el PDF tiene capa de texto,
  - `PaddleOCR` como fallback para PDFs escaneados.
- Calcula una **confianza OCR global** y confianza por campo.
- Extrae:
  - consumo kWh,
  - consumo MWh,
  - comercializadora,
  - fecha de factura,
  - período inicio / fin,
  - días facturados,
  - sociedad,
  - dirección de suministro,
  - CUPS,
  - preview textual del documento.

### 1.4 Revisión y confirmación manual
- Endpoint: `POST /api/factura/<id>/confirmar`
- Permite corregir campos antes de confirmar la factura.
- Valida:
  - formato de fechas,
  - coherencia de período,
  - rango de `dias_facturados`,
  - longitud de campos de texto.
- Registra cambios campo a campo en `facturas_historial`.

### 1.5 Consulta y ciclo de vida de la factura
- `GET /api/factura/<id>`: detalle completo.
- `GET /api/factura/<id>/pdf`: acceso al PDF local o remoto.
- `GET /api/factura/<id>/historial-cambios`: trazabilidad de modificaciones manuales.
- `GET /api/historial`: listado paginado con filtros.
- `DELETE /api/factura/<id>`: anulación lógica (soft delete).

---

## 2. Dashboard ESG

### 2.1 KPIs de cabecera
- Endpoint: `GET /api/dashboard/resumen`
- Devuelve visión resumida del ejercicio:
  - emisiones,
  - cobertura,
  - alertas,
  - variación anual.

### 2.2 KPIs de emisiones
- Endpoint: `GET /api/dashboard/emisiones`
- Soporta filtros por `anio`, `pais`, `sede`.
- Incluye:
  - emisiones totales tCO2e,
  - consumo total MWh,
  - desglose por país,
  - desglose por sede,
  - evolución mensual,
  - comparativa interanual,
  - reparto por scope GHG.

### 2.3 KPIs de cobertura
- Endpoint: `GET /api/dashboard/cobertura`
- Mide:
  - porcentaje de datos reales,
  - porcentaje estimado,
  - porcentaje faltante,
  - cobertura por sede.

### 2.4 KPIs de calidad
- Endpoint: `GET /api/dashboard/calidad`
- Mide:
  - facturas con OCR bajo,
  - duplicados potenciales,
  - anomalías de consumo,
  - score de calidad,
  - sedes con peor calidad relativa.

### 2.5 KPIs de facturación
- Endpoint: `GET /api/dashboard/facturacion`
- Incluye:
  - número de facturas,
  - estados,
  - pendientes de revisión,
  - confirmadas,
  - anuladas,
  - duplicadas potenciales.

### 2.6 Evolución temporal
- Endpoint: `GET /api/dashboard/evolucion`
- Proporciona series mensuales para gráficos:
  - ejercicio actual,
  - ejercicio anterior,
  - datos reales,
  - datos estimados.

### 2.7 Dashboard ejecutivo ESG
- Endpoint: `GET /api/dashboard/esg`
- Combina en una sola llamada:
  - emisiones acumuladas,
  - cumplimiento de objetivos,
  - número de sedes en riesgo,
  - semáforo global,
  - proyección de cierre.

### 2.8 Semáforo ESG
- Verde: emisiones reales dentro del objetivo.
- Amarillo: desviación moderada (hasta ~20% sobre objetivo).
- Rojo: desviación clara o incumplimiento relevante.
- Gris: datos insuficientes o sin objetivos.

### 2.9 Proyección de cierre
- Endpoint: `GET /api/dashboard/proyeccion`
- Métodos:
  - pro-rata por meses con datos,
  - ajuste estacional si existe histórico suficiente.
- Devuelve:
  - emisiones acumuladas,
  - emisiones proyectadas,
  - meses con datos,
  - meses restantes,
  - confianza,
  - diferencia frente a objetivo.

---

## 3. Alertas automáticas

### 3.1 Motor de alertas
- Endpoint generación: `POST /api/alertas/generar`
- Endpoints de consulta:
  - `GET /api/alertas`
  - `GET /api/alertas/pendientes`
  - `GET /api/alertas/resueltas`
  - `GET /api/alertas/resumen`
- Endpoints de acción:
  - `POST /api/alertas/<id>/resolver`
  - `POST /api/alertas/<id>/ignorar`

### 3.2 Configuración
- Tabla `alertas_config`
- Permite activar/desactivar reglas y ajustar umbrales.

### 3.3 Detectores implementados (12)
1. **Falta de factura del mes anterior**  
   Detecta sedes sin factura real ni estimación vigente para el mes anterior.
2. **OCR bajo**  
   Genera alerta si la confianza OCR cae por debajo del umbral configurado.
3. **Consumo anómalo por umbral histórico**  
   Marca consumos muy por encima de la media histórica de la sede.
4. **Duplicado potencial**  
   Basado en período coincidente o SHA256 idéntico.
5. **Factor no actualizado**  
   Identifica factores que requieren revisión temporal o normativa.
6. **Documento no encontrado**  
   Detecta registros de factura cuyo PDF no está accesible.
7. **Recálculo pendiente**  
   Señala facturas o conjuntos que deberían recalcularse tras cambios en factores.
8. **Versión antigua de factor**  
   Detecta uso de versiones históricas no vigentes como referencia analítica.
9. **Anomalía por z-score**  
   Alerta por desviaciones estadísticas significativas respecto a la distribución de la sede.
10. **Cambio interanual brusco**  
    Detecta variaciones fuertes frente al mismo mes del año anterior.
11. **Período anómalo**  
    Detecta facturas con períodos demasiado cortos o demasiado largos.
12. **Incoherencia OCR interna**  
    Detecta inconsistencias entre campos extraídos:
    - kWh vs MWh,
    - fecha de factura vs período,
    - CUPS de longitud anómala.

---

## 4. Informe GHG Protocol

### 4.1 Generación
- Endpoint: `GET /api/ghg/informe`
- Vista previa: `GET /api/ghg/preview`
- Ranking sociedades: `GET /api/ghg/ranking/sociedades`

### 4.2 Formato de salida
- Excel generado con `openpyxl`.
- Incluye 7 hojas:
  1. `1. Resumen Ejecutivo`
  2. `2. Emisiones por Scope`
  3. `3. Metodología`
  4. `4. Calidad del Dato`
  5. `5. Trazabilidad`
  6. `6. Detalle Facturas`
  7. `7. Emisiones por Sociedad`

### 4.3 Contenido del informe
- Totales de emisiones y consumo.
- Reparto por scope 1/2/3.
- Factores usados, fuente y vigencia.
- Calidad del dato:
  - % real,
  - % estimado,
  - % faltante,
  - nivel de calidad.
- Trazabilidad:
  - número de recálculos,
  - modificaciones manuales,
  - evidencia documental,
  - estimaciones sustituidas.
- Detalle factura a factura para auditoría.
- Ranking por sociedad/empresa.

---

## 5. Estimaciones

### 5.1 Gestión de periodos faltantes
- Endpoints:
  - `GET /api/estimaciones/gaps`
  - `GET /api/estimaciones/periodos`
- Tabla base: `periodos_faltantes`

### 5.2 CRUD operativo
- `GET /api/estimaciones`
- `POST /api/estimaciones`
- `DELETE /api/estimaciones/<id>` (rechazo funcional)
- `POST /api/estimaciones/<id>/sustituir`

### 5.3 Métodos de estimación disponibles (8)
1. `media_historica`
2. `mismo_mes_anio_anterior`
3. `adyacente`
4. `manual`
5. `sede_similar`
6. `ponderado`
7. `por_dias`
8. `estacional`

### 5.4 Capacidades del motor
- Calcula kWh, MWh, emisiones estimadas y factor aplicado.
- Asigna confianza numérica y textual.
- Guarda referencias usadas para la estimación.
- Mantiene estado:
  - `vigente`
  - `sustituida`
  - `rechazada`

### 5.5 Comparativa de métodos
- Endpoint: `GET /api/estimaciones/comparativa-metodos`
- Devuelve resultados comparados sin persistir, útil para escoger método.

### 5.6 Resolución automática de huecos pequeños
- Endpoint: `POST /api/estimaciones/resolver-hueco`
- Usa `por_dias` cuando el hueco es suficientemente pequeño.

### 5.7 Reconciliación estimado → real
- Automática al registrar una nueva factura real.
- Sustituye estimaciones vigentes del mismo mes/sede.
- Calcula:
  - error absoluto,
  - error relativo,
  - desviación porcentual,
  - timestamp de sustitución.

### 5.8 Métricas de precisión
- Endpoints:
  - `GET /api/estimaciones/metricas-error`
  - `GET /api/estimaciones/metricas-precision`
- Tabla `metodo_estimacion_metricas`
- Métricas por método:
  - `n_sustituciones`
  - `mae_kwh`
  - `mape_pct`
  - error máximo absoluto y relativo
  - clasificación de calidad del método

---

## 6. Calidad del dato

### 6.1 Controles en la carga
- Validación de período.
- Validación de consumo positivo.
- Detección de anomalía frente al histórico.
- Detección de duplicado por:
  - período,
  - contenido PDF (SHA256).

### 6.2 Controles en la confirmación
- Fechas ISO válidas.
- `periodo_inicio <= periodo_fin`.
- `dias_facturados` razonable.
- cadenas con longitud controlada.

### 6.3 Cobertura
- Métricas de cobertura real / estimada / faltante.
- Cobertura por ejercicio, país y sede.
- Seguimiento de huecos con `periodos_faltantes`.

### 6.4 Inconsistencias detectadas
- Campo `inconsistencias_json` por factura.
- Reglas sobre:
  - coherencia consumo kWh/MWh,
  - cronología de fechas,
  - estructura del CUPS.

### 6.5 Duplicados
- Campo `duplicado_potencial`.
- No se bloquea la inserción: se marca y se deja trazabilidad.

### 6.6 Trazabilidad de cambios
- `facturas_historial` para cambios manuales.
- `audit_log` para acciones de usuario y sistema.

---

## 7. Gestión documental

### 7.1 Almacenamiento abstracto
- Patrón `DocumentoStorage`.
- Implementaciones:
  - `LocalDocumentoStorage` (activa)
  - `SharePointDocumentoStorage` (placeholder)

### 7.2 Organización física de documentos
- Estructura:
  - `uploads/{YYYY}/{PAIS}/{SEDE}/{archivo}`
- Registra `carpeta_relativa` para futura migración o localización.

### 7.3 Índice documental
- Tabla `documentos_indice`
- Endpoint: `GET /api/documentos/indice`
- Permite consultar documentos por:
  - ejercicio,
  - país,
  - sede.

### 7.4 Cobertura documental
- Endpoint: `GET /api/documentos/cobertura`
- Devuelve:
  - meses cubiertos,
  - meses faltantes,
  - porcentaje de cobertura.

### 7.5 Integridad documental
- SHA256 calculado en el momento del guardado.
- Comprobación de existencia real del PDF.

---

## 8. Emisiones y estadísticas

### 8.1 Cálculo de emisiones
- Fórmula:
  - `tCO2e = consumo_MWh × factor_kgCO2_MWh / 1000`
- El factor se obtiene siempre desde BD.
- Cada factura queda ligada a `factor_version_id`.

### 8.2 Fallback de factor
- Si no existe factor exacto para el año:
  - se usa la versión activa más reciente disponible del país.

### 8.3 Estadísticas por sede
- Endpoint: `GET /api/estadisticas/emisiones/sedes`
- Incluye ranking, consumo, total emisiones, media mensual.

### 8.4 Estadísticas por sociedad
- Endpoint: `GET /api/estadisticas/emisiones/sociedades`
- Agrupa también facturas sin sociedad bajo `Sin identificar`.

### 8.5 Comparativas
- `GET /api/estadisticas/comparativa/sedes`
- `GET /api/estadisticas/comparativa/sociedades`
- Soporta análisis descriptivo y rankings.

### 8.6 Scope GHG
- Los factores incorporan `scope_ghg`.
- El informe y dashboard distinguen scope 1, 2 y 3.
- Actualmente la operativa real está centrada en **electricidad comprada (scope 2)**.

---

## 9. Objetivos ESG

### 9.1 CRUD de objetivos
- Endpoints:
  - `POST /api/objetivos`
  - `GET /api/objetivos`
  - `GET /api/objetivos/<id>`
  - `PUT /api/objetivos/<id>`
  - `DELETE /api/objetivos/<id>`

### 9.2 Granularidades soportadas
- Global corporativo.
- Por país.
- Por sociedad.
- Por sede.

### 9.3 Tipos de objetivo
- Objetivo absoluto en tCO2e.
- Objetivo relativo (% reducción respecto a año base).

### 9.4 Seguimiento
- `GET /api/objetivos/<id>/seguimiento`
- `GET /api/objetivos/seguimiento`
- Métricas devueltas:
  - emisiones reales acumuladas,
  - desviación,
  - % cumplimiento,
  - semáforo,
  - proyección de cierre.

### 9.5 Resumen ejecutivo ESG
- Endpoint: `GET /api/objetivos/resumen-esg`
- Devuelve:
  - número total de objetivos,
  - verde / amarillo / rojo / sin datos,
  - % cumplimiento global,
  - sedes en riesgo.

---

## 10. Factores de emisión

### 10.1 Modelo de factores
- Tabla `factores_emision`
- Versionado inmutable por:
  - país,
  - tipo de energía,
  - año,
  - versión.

### 10.2 Trazabilidad y gobierno
- Tabla `fuentes_emision`
- Tabla `factores_historial`
- API de consulta y administración:
  - `GET /api/factores`
  - `POST /api/factores`
  - `GET /api/factores/<id>`
  - `PUT /api/factores/<id>/nueva-version`
  - `PATCH /api/factores/<id>/metadatos`
  - `PATCH /api/factores/<id>/estado`
  - `GET /api/factores/<id>/historial`
  - `GET /api/factores/<pais>/<anio>/versiones`
  - `GET /api/factores/estado-actualizacion`

### 10.3 Recálculo masivo
- Endpoints:
  - `GET /api/recalculo/impacto`
  - `POST /api/recalculo/ejecutar`
  - `GET /api/recalculo/lotes`
  - `GET /api/recalculo/lote/<id>`
  - `GET /api/recalculo/historial/<factura_id>`
- Soporta alcances:
  - individual,
  - sede,
  - país,
  - año,
  - completo.

### 10.4 Seguridad del recálculo
- No machaca el valor original.
- Guarda:
  - emisiones recalculadas,
  - factor recalculado,
  - versión nueva,
  - diferencias absolutas y porcentuales,
  - usuario y motivo.

### 10.5 Corrección crítica ya aplicada
- Factores ajustados de tCO2/MWh a kgCO2/MWh.
- Recalculo histórico ejecutado sobre facturas afectadas.

---

## 11. Exportación y reporting

### 11.1 Exportación Excel histórica
- Endpoint: `GET /api/descargar-excel`
- Exporta histórico operativo de facturas.

### 11.2 Reporting GHG
- Generación de informe Excel estructurado y auditable.
- Incluye metodología, trazabilidad y calidad.

### 11.3 Preparación para reporting corporativo
- Trazabilidad por factor.
- Evidencia documental.
- Histórico de modificaciones.
- Distinción entre dato real y estimado.
- Soporte para reporting ESG interno y base para CSRD.

---

## Resumen funcional actual

El portal ya puede:
- capturar facturas eléctricas con OCR,
- calcular emisiones auditables,
- detectar duplicados e inconsistencias,
- cubrir huecos con 8 métodos de estimación,
- reconciliar estimado vs real,
- versionar factores con historial,
- recalcular emisiones masivamente,
- organizar y localizar documentos,
- generar alertas automáticas,
- construir dashboards ESG operativos y ejecutivos,
- gestionar objetivos de reducción,
- exportar reporting GHG en Excel listo para negocio.

