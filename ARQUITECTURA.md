# Arquitectura — Portal de Datos Ambientales de Hiberus

## 1. Visión general

El Portal de Datos Ambientales es una aplicación web monolítica ligera basada en **Flask + SQLite + PaddleOCR**, diseñada para convertir facturas energéticas PDF en un **repositorio ESG trazable, consultable y explotable**.

La arquitectura sigue una separación clara por capas:

- **presentación**: SPA servida desde `templates/` (shell `index.html` + partials Jinja) con los módulos JS de `static/js/`;
- **API HTTP**: blueprints Flask en `routes/`;
- **negocio**: servicios especializados en `services/`;
- **persistencia**: SQLite con migraciones por fases en `database/`;
- **documentos**: almacenamiento local abstraído por `documento_service.py`.

No se usa React, Vue ni un backend distribuido: el diseño apuesta por simplicidad operativa, trazabilidad y rapidez de despliegue.

## 2. Frontend

### Tecnología

- shell `templates/index.html`, que compone la página mediante 15 partials Jinja en
  `templates/partials/` (`_nav.html`, 8 pestañas en `tabs/`, 5 modales en `modals/`
  y `_toast.html`);
- JavaScript vanilla repartido en 11 módulos bajo `static/js/`, cargados por orden:
  `core.js` primero, luego un módulo por dominio funcional (`facturas`, `historial`,
  `factores`, `recalculo`, `estimaciones`, `dashboard`, `alertas`, `ghg`, `admin`) e
  `init.js` al final;
- estilos propios en `static/css/app.css`;
- **Fetch API** para todas las llamadas de datos;
- Bootstrap 5.3, Font Awesome 6.4 y Chart.js 4.4, cargados desde CDN.

### Patrón de funcionamiento

La interfaz es una **Single Page App** con pestañas funcionales:

- carga de facturas;
- historial;
- factores;
- recálculo;
- estimaciones;
- dashboard ESG;
- alertas;
- informe GHG.

El frontend:

- monta formularios y tablas en el navegador;
- invoca la API con `fetch(...)`;
- hace polling de lotes con `setInterval` sobre `/api/lote/<id>/estado`;
- renderiza gráficos con Chart.js a partir de respuestas JSON;
- no necesita compilación ni bundling.

### Implicaciones arquitectónicas

- despliegue simple;
- mínimo coste de mantenimiento frontend;
- excelente trazabilidad porque no hay una capa de cliente compilada opaca;
- menor complejidad, a cambio de una lógica de presentación repartida entre partials
  Jinja y módulos JS que comparten estado global de navegador, sin encapsulación real.

## 3. Backend Flask

### Punto de entrada

`app.py` actúa como entry point y expone `create_app()`.

Responsabilidades:

- ejecutar migraciones al arrancar;
- instanciar Flask;
- fijar `MAX_CONTENT_LENGTH = 50 MB`;
- registrar blueprints;
- definir `GET /` para servir la SPA;
- homogeneizar errores 404, 413 y 500 en JSON.

### Organización por blueprints

El backend está segmentado por dominio:

- `facturas.py`
- `exportacion.py`
- `estadisticas.py`
- `configuracion.py`
- `factores_admin.py`
- `fuentes.py`
- `recalculo.py`
- `estimaciones.py`
- `dashboard.py`
- `alertas.py`
- `ghg_report.py`
- `objetivos.py`

### Patrones relevantes

- **Application factory** en `create_app()`.
- **Service layer** en `services/`.
- **Factory pattern** en `ExtractorFactory` para extractores por tipo de suministro.
- **Strategy-like storage abstraction** en `LocalDocumentoStorage`.

## 4. Base de datos SQLite

### Configuración de conexión

`database/connection.py` centraliza el acceso a base de datos mediante `get_db_connection()`.

Configuración aplicada a cada conexión:

- `check_same_thread=False`;
- `row_factory = sqlite3.Row`;
- `PRAGMA journal_mode=WAL`;
- `PRAGMA foreign_keys=ON`.

### WAL mode

El modo **WAL (Write-Ahead Logging)** permite:

- más concurrencia entre lectura y escritura;
- menos bloqueo de lectores durante escrituras;
- mejor comportamiento en escenarios de dashboard + cargas.

### Modelo de bloqueo

SQLite sigue siendo una base embebida con bloqueo a nivel de archivo. Por eso el diseño evita paralelismo agresivo en OCR y escritura:

- el procesamiento de lote es secuencial por PDF;
- las migraciones son idempotentes;
- varios `ALTER TABLE` están protegidos con pre-check o captura de duplicados.

### Migraciones

Las migraciones están troceadas por hitos funcionales:

- `migrations.py`: bootstrap base;
- `migrations_fase2.py`: versionado de factores y fuentes;
- `migrations_fase3.py`: estimaciones y recálculo;
- `migrations_refactor.py`: tablas maestras;
- `migrations_mejoras.py`: auditoría, SHA-256, CDC y normalización documental;
- `migrations_fase4.py`: alertas;
- `migrations_fase5.py`: ejercicio, índice documental, CUPS, inconsistencias;
- `migrations_fase6.py`: objetivos ESG, métricas de métodos y correcciones críticas;
- `migrations_campos_factura.py`: campos comerciales de factura (importe, tarifa, contrato, potencia, distribuidora);
- `migrations_sedes.py`: normalización de sedes — fusiona las que solo difieren en tildes, mayúsculas o espacios, que el `UNIQUE(pais_codigo, nombre)` literal no detecta.
- `migrations_integridad.py`: integridad referencial — borra las filas huérfanas que dejaron los borrados masivos de datos y añade `ON DELETE CASCADE` a `facturas_historial.factura_id`.

## 5. Capa OCR

### Flujo lógico

```text
PDF -> ocr_service.py -> texto plano -> extraccion_service.py -> DatosFactura
```

### Componentes

- `ocr_service.py`: encapsula PaddleOCR.
- `extraccion_service.py`: transforma texto OCR en datos estructurados con regex multi-patrón.
- `extractor_service.py`: `ExtractorFactory`, punto de extensión para nuevos tipos de suministro.

### Contrato de extracción

La salida funcional es `DatosFactura`, que concentra campos como:

- consumo;
- fechas de factura y período;
- comercializadora;
- sociedad;
- dirección;
- confianza global y por campo.

### Objetivo arquitectónico

Separar OCR de parsing permite:

- cambiar el motor OCR sin reescribir la lógica de negocio;
- añadir extractores por suministro, país o proveedor;
- medir calidad de extracción de forma explícita.

## 6. Pipeline de procesamiento de facturas

El orquestador es `services/lote_service.py`.

### Flujo end-to-end

```text
subida -> guardado documento -> OCR -> extracción -> validación
      -> detección duplicados -> cálculo emisiones -> INSERT factura
      -> audit log -> conciliación con estimaciones -> respuesta API
```

### Pasos principales

1. **Persistencia de documento** con `documento_service.py`.
2. **Cálculo de SHA-256**.
3. **Extracción** vía `ExtractorFactory`.
4. **Validaciones de calidad**.
5. **Determinación del año** del factor a aplicar.
6. **Cálculo de emisiones** con `emisiones_service.py`.
7. **Persistencia** en `facturas`.
8. **Registro de auditoría**.
9. **Reconciliación automática** con estimaciones vigentes del mismo mes.

### Lotes

- `/api/procesar-lote` crea un `lote_id`.
- Un hilo daemon procesa secuencialmente los PDFs.
- El estado se persiste en `lotes`.
- El frontend consulta `/api/lote/<id>/estado`.

## 7. Motor de emisiones

### Servicio

`services/emisiones_service.py`

### Responsabilidades

- localizar el factor activo aplicable;
- devolver factor, fuente y `factor_version_id`;
- calcular `emisiones_tco2e`.

### Fórmula implementada

```text
emisiones_tCO₂e = consumo_MWh × factor_kg_co2_mwh ÷ 1000
```

### Aritmética decimal

El cálculo no usa coma flotante ni la función `round()` de Python, que aplica
redondeo bancario (`round(2.675, 2)` devuelve `2.67`). `services/numeros.py`
centraliza la conversión a `Decimal` y el redondeo `ROUND_HALF_UP`, con una
precisión fija por magnitud: importes 2 decimales, kWh 2, MWh 6, tCO₂e 4.

Dos consecuencias de diseño:

- La conversión de kWh a MWh es **exacta**: al guardarse con 6 decimales, dividir
  por 1000 no pierde información. Antes se redondeaba a 3 decimales, de modo que
  999,999 kWh se almacenaban como 1,0 MWh.
- La fórmula se resuelve en **un solo paso**, sin redondeos intermedios, y solo se
  redondea el resultado. Así las emisiones guardadas son exactamente el producto
  del consumo y el factor guardados, y un tercero puede reproducir la cifra.

Las columnas siguen almacenándose como `REAL` en SQLite; lo que cambia es la
aritmética, no el tipo de la columna.

### Factores 2025 cargados

- ES 2025 = 187.0
- AR 2025 = 118.0
- CO 2025 = 263.0
- EC 2025 = 298.0
- MX 2025 = 348.0
- FR 2025 = 57.8

### Diseño de trazabilidad

Cada factura conserva `factor_version_id`, lo que permite responder con precisión a preguntas de auditoría como:

- qué factor se usó;
- de qué fuente provenía;
- si el cálculo fue anterior o posterior a un recálculo.

## 8. Motor de estimaciones

### Servicio principal

`services/estimacion_service.py`

### Objetivo

Cubrir meses sin factura real manteniendo separación explícita entre:

- dato real;
- dato estimado;
- período faltante.

### Métodos disponibles

1. `media_historica`
2. `mismo_mes_anio_anterior`
3. `adyacente`
4. `manual`
5. `sede_similar`
6. `ponderado`
7. `por_dias`
8. `estacional`

### Capacidades avanzadas

- comparativa de métodos antes de guardar;
- cálculo de confianza y `confianza_texto`;
- actualización de `periodos_faltantes`;
- sustitución por factura real;
- cálculo de error absoluto y relativo;
- actualización acumulada de `metodo_estimacion_metricas`.

## 9. Reporting ESG

### Servicio

`services/ghg_report_service.py`

### Doble salida

- **JSON preview** para la SPA;
- **Excel** para reporting externo.

### Las 7 hojas del Excel

1. `1. Resumen Ejecutivo`
2. `2. Emisiones por Scope`
3. `3. Metodología`
4. `4. Calidad del Dato`
5. `5. Trazabilidad`
6. `6. Detalle Facturas`
7. `7. Emisiones por Sociedad`

## 10. Dashboard y KPIs

### Servicio

`services/dashboard_service.py`

### Endpoints funcionales

- resumen global;
- emisiones;
- cobertura;
- calidad;
- facturación;
- evolución mensual;
- dashboard ESG;
- proyección de cierre.

### Filtros

Los módulos admiten filtros de negocio por:

- año;
- país;
- sede;
- en algunos casos `tipo_energia`.

## 11. Sistema de alertas

### Servicio

`services/alertas_service.py`

### Detectores implementados

1. cobertura: falta factura del mes anterior;
2. calidad: OCR bajo;
3. calidad: consumo anómalo;
4. calidad: duplicado potencial;
5. emisiones: factor no actualizado;
6. emisiones: versión antigua de factor;
7. documentación: documento no encontrado;
8. emisiones: recálculo pendiente;
9. calidad: consumo anómalo por z-score;
10. calidad: cambio interanual brusco;
11. calidad: período anómalo;
12. calidad: OCR incoherente.

## 12. Gestión documental

### Servicio

`services/documento_service.py`

### Capacidades actuales

- guardar PDFs;
- organizar carpetas por `ejercicio`;
- calcular `sha256`;
- indexar en `documentos_indice`;
- resolver acceso local o redirección futura.

## 13. Módulo de objetivos ESG

### Servicio

`services/objetivos_service.py`

### Ámbitos soportados

- corporativo global;
- país;
- sociedad;
- sede.

### Funciones

- CRUD de objetivos;
- seguimiento individual;
- seguimiento global;
- resumen ESG;
- semáforo `verde / amarillo / rojo / sin_datos / sin_objetivo`;
- integración con dashboard ejecutivo y proyección.

## 14. Integraciones futuras preparadas

### SharePoint

La arquitectura ya tiene puntos de extensión claros:

- `fuentes_documentos` para registrar bibliotecas/sitios;
- `sync_log` para auditoría de sincronización;
- `external_doc_id` y `external_doc_url` en facturas;
- `resolver_acceso()` preparado para retorno por redirección.

### Power BI / Data Platform

La base también está preparada para extracción incremental gracias a:

- `updated_at`;
- `export_state`;
- índices CDC;
- normalización de maestros (`paises`, `sedes`, `suministros`, `tipos_energia`).

## 15. Diagrama textual ASCII de la arquitectura

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Navegador                                                          │
│ SPA: templates/index.html + partials Jinja                         │
│ - Bootstrap                                                        │
│ - JS vanilla (11 módulos en static/js/)                            │
│ - Fetch API                                                        │
│ - Chart.js                                                         │
└───────────────┬─────────────────────────────────────────────────────┘
                │ HTTP / JSON / archivos
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Flask (app.py)                                                     │
│ create_app() + blueprints                                          │
│ / facturas / estimaciones / dashboard / alertas / ghg / objetivos  │
└───────────────┬─────────────────────────────────────────────────────┘
                │ llama servicios
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Capa de servicios                                                  │
│ OCR -> extracción -> validación -> emisiones -> auditoría          │
│ lote_service / dashboard_service / alertas_service / objetivos     │
└───────────────┬─────────────────────────────────────────────────────┘
                │
      ┌─────────┴─────────┐
      ▼                   ▼
┌───────────────┐   ┌─────────────────────────────────────────────────┐
│ SQLite        │   │ Almacenamiento documental                      │
│ facturas_hc.db│   │ LocalDocumentoStorage                          │
│ WAL mode      │   │ - archivos por ejercicio                       │
│ tablas ESG    │   │ - sha256                                       │
└───────────────┘   └─────────────────────────────────────────────────┘
```
