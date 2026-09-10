# HANDOVER — Portal de Datos Ambientales Hiberus

## 1. Resumen del proyecto

### Qué es
Portal interno de Hiberus para gestionar facturas energéticas, extraer datos de PDFs mediante OCR, calcular emisiones de CO₂ asociadas al consumo y generar reporting ESG corporativo.

### Para qué sirve
El sistema cubre tres necesidades de negocio que antes dependían mucho de trabajo manual:
1. **Carga y trazabilidad de facturas**: almacenar PDFs, extraer consumo, período, comercializadora y metadatos de suministro.
2. **Cálculo de emisiones**: convertir consumo energético en emisiones usando factores versionados por país y año.
3. **Cobertura ESG y reporting**: detectar huecos, generar estimaciones, lanzar alertas, seguir objetivos y emitir informes GHG.

### Quién lo usa
Equipo interno de sostenibilidad de Hiberus (Rossana y equipo), con foco en consolidación corporativa, reporting y control de calidad de datos.

### Alcance funcional real hoy
- Facturas de **electricidad** como suministro plenamente operativo.
- OCR híbrido: **pdfplumber** si el PDF tiene capa de texto, **PaddleOCR** como fallback si es escaneado.
- Cálculo automático de emisiones por país/año.
- Gestión de factores de emisión con versionado y trazabilidad.
- Detección de períodos sin factura y creación de estimaciones.
- Reconciliación automática cuando llega la factura real.
- Alertas automáticas de calidad, cobertura y anomalías.
- Dashboard ESG y seguimiento de objetivos.
- Informe GHG exportable.

---

## 2. Estado actual exacto

### Estado global
**Fase 6, iteración 1 completada**. El proyecto ya no es un prototipo mínimo: tiene una base funcional amplia y suficiente para uso interno, pero todavía conserva deuda técnica y extensiones estratégicas sin cerrar.

### Qué funciona hoy

#### Backend y arranque
- `app.py` crea la app Flask, registra blueprints y ejecuta migraciones al importarse.
- La aplicación arranca con `venv\Scripts\python.exe app.py` o con `gunicorn`.
- Hay manejo básico de errores HTTP 413, 404 y 500.

#### Base de datos y migraciones
- SQLite local en `facturas_hc.db`.
- `database/connection.py` abre conexiones con:
  - `row_factory = sqlite3.Row`
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA foreign_keys=ON`
- `database/migrations.py` orquesta migraciones con protección de concurrencia:
  - lock de hilo (`threading.Lock`)
  - lock de fichero (`.migration.lock`)
  - SQL idempotente
- Existen migraciones por fases (`migrations_fase2.py` … `migrations_fase6.py`) y migraciones de refactor/mejoras.

#### OCR y extracción
- `services/ocr_service.py` usa **pdfplumber** como ruta rápida y **PaddleOCR** como fallback.
- PaddleOCR está serializado con lock porque **no es thread-safe**.
- `services/extraccion_service.py` contiene la dataclass `DatosFactura` y la lógica de extracción para electricidad.
- `services/extractor_service.py` define `ExtractorFactory`; hoy electricidad está implementada y gas/agua/residuos/viajes están como placeholders controlados.

#### Ingesta de facturas
Pipeline principal en `services/lote_service.py`:
1. `documento_service.guardar(pdf)`
2. `ExtractorFactory.get('electricidad').extraer(ruta, pais)`
3. validación de calidad
4. cálculo de emisiones
5. comprobación de duplicados
6. INSERT en `facturas`
7. registro de auditoría
8. reconciliación automática con estimaciones

Puntos importantes del flujo:
- El procesamiento en lote es **secuencial** para evitar problemas con PaddleOCR y memoria.
- El lote se ejecuta en **hilo daemon** y el frontend hace polling a `/api/lote/<id>/estado`.
- Los PDFs se guardan organizados en `uploads\{YYYY}\{PAIS}\{SEDE}\...`.
- Se calcula y persiste `sha256` documental para trazabilidad y duplicados.

#### DocumentoStorage
- `services/documento_service.py` ya abstrae almacenamiento documental con patrón Strategy.
- Funciona `LocalDocumentoStorage`.
- Existe `SharePointDocumentoStorage`, pero **solo como esqueleto / no implementado**.
- El backend activo se selecciona con `DOCUMENTO_STORAGE=local|sharepoint`.

#### Emisiones y factores
- Fórmula vigente: `tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000`.
- Factores activos conocidos 2025:
  - ES: 187.0 kgCO₂/MWh
  - AR: 118.0 kgCO₂/MWh
  - CO: 263.0 kgCO₂/MWh
  - EC: 298.0 kgCO₂/MWh
  - MX: 348.0 kgCO₂/MWh
  - FR: 57.8 kgCO₂/MWh
- `config.py` contiene un dict `FACTORES_EMISION`, pero **solo como seed inicial**.
- La fuente de verdad de runtime es la tabla `factores_emision` y `services/emisiones_service.obtener_factor()`.
- Hay versionado de factores y administración vía blueprint `routes/factores_admin.py`.

#### Estimaciones
- `services/estimacion_service.py` soporta:
  - `media_historica`
  - `mismo_mes_anio_anterior`
  - `adyacente`
  - `manual`
  - `sede_similar`
  - `ponderado`
  - `por_dias`
  - `estacional`
- La reconciliación automática sustituye estimaciones cuando se inserta una factura real del mismo período.
- Existen métricas de error por método en `metodo_estimacion_metricas`.

#### Alertas
- `services/alertas_service.py` ya ejecuta 12 detectores:
  1. consumo_cero
  2. confianza_baja
  3. periodo_solapado
  4. gap_cobertura
  5. factor_desactualizado
  6. estimacion_larga
  7. duplicado_potencial
  8. outlier_consumo
  9. z-score consumo
  10. cambio_interanual_brusco
  11. periodo_anomalo
  12. ocr_incoherente
- Hay endpoints para generar, listar, resolver, ignorar y resumir alertas.

#### Dashboard, objetivos y reporting
- `services/dashboard_service.py` ofrece KPIs y dashboard ESG.
- `services/objetivos_service.py` gestiona objetivos de reducción.
- `services/ghg_report_service.py` genera informe Excel GHG.
- `routes/dashboard.py`, `routes/objetivos.py` y `routes/ghg_report.py` exponen estas capacidades.

#### Frontend
- Toda la UI principal está en **`templates/index.html`**.
- Es una SPA simple en HTML + JavaScript vanilla + Fetch API.
- Tiene pestañas para carga, historial, factores, recálculo, estimaciones, dashboard, alertas e informe GHG.
- No hay framework frontend ni bundler.

### Qué está a medio hacer o preparado pero no completado
- **SharePoint** como backend documental alternativo: solo placeholder.
- **Power BI**: previsto, pero no integrado de verdad.
- **Azure AD / autenticación**: no existe.
- **Nuevos tipos de suministro**: la factoría está preparada, pero solo electricidad funciona de forma real.
- **PostgreSQL**: no existe soporte; todo asume SQLite.
- **Tests formales**: no hay una suite consolidada en el repo.

### Qué falta claramente
- Autenticación/autorización corporativa.
- Integración documental corporativa real (SharePoint/Graph).
- Observabilidad y pruebas automáticas estables.
- Endurecimiento de despliegue/producción.

---

## 3. Cómo arrancar el proyecto

### Opción recomendada en Windows
Desde la raíz del repo:

```powershell
cd C:\Users\AlbaAlonsoMarmany\portal_hc_hiberus
.\venv\Scripts\python.exe app.py
```

### Si el venv no está preparado
```powershell
cd C:\Users\AlbaAlonsoMarmany\portal_hc_hiberus
.\setup_windows.bat
.\venv\Scripts\python.exe app.py
```

### Qué hace el arranque
1. Importa `app.py`.
2. `app.py` llama a `database.migrations.ejecutar_migraciones()`.
3. Las migraciones crean/ajustan schema de forma idempotente.
4. Flask registra 12 blueprints.
5. La app escucha en `http://localhost:5000` salvo que `PORT` indique otro puerto.

### Variables de entorno relevantes
- `FLASK_DEBUG=true|false`
- `PORT=5000`
- `DOCUMENTO_STORAGE=local|sharepoint` — en la práctica solo `local` es funcional. `sharepoint` selecciona `SharePointDocumentoStorage`, que es un esqueleto: `guardar()` y `eliminar()` lanzan `NotImplementedError`.

### Base de datos
- Archivo: `facturas_hc.db`
- Se usa directamente; no hace falta servidor externo.
- Si el proyecto arranca bien, la BD se inicializa/migra automáticamente.

### Gunicorn
El proyecto declara compatibilidad con gunicorn. Recomendación ya documentada en migraciones:

```bash
gunicorn --preload --workers=4 app:app
```

`--preload` es importante porque reduce riesgos de concurrencia en migraciones y hace que los workers hereden la BD ya inicializada.

### Verificación mínima de arranque
- Abrir `http://localhost:5000`
- Comprobar que carga la SPA.
- Confirmar que rutas como `/api/paises` responden.

### Nota sobre la documentación de instalación
`README.md`, `INSTALACION.md`, `INSTALACION_RAPIDA.md`, `REFERENCIA_RAPIDA.md` e `INDICE.md` se reescribieron contra el código actual y ya reflejan el stack real (Python 3.13, PaddleOCR, sin Tesseract). Aun así, ante cualquier discrepancia **manda el código**.

---

## 4. Cómo entender el código

### Ruta de lectura recomendada si vienes de cero

#### Paso 1 — Punto de entrada
Lee `app.py`.
- Qué blueprints existen.
- Qué ocurre al arrancar.
- Qué endpoints y módulos forman parte del producto real.

#### Paso 2 — Configuración crítica
Lee `config.py`.
- Umbral OCR (`UMBRAL_REVISION=0.75`).
- `UPLOAD_FOLDER`.
- `SEDES_PAISES`.
- `COMERCIALIZADORAS`.
- Advertencia clave: `FACTORES_EMISION` es seed inicial, no runtime source of truth.

#### Paso 3 — Persistencia
Lee en este orden:
1. `database/connection.py`
2. `database/migrations.py`
3. migraciones de fase relevantes (`migrations_fase5.py`, `migrations_fase6.py`, etc.)

Objetivo: entender cómo se crean tablas, índices y columnas antes de tocar cualquier servicio.

#### Paso 4 — Pipeline principal de negocio
Lee `services/lote_service.py`.
Ese archivo explica casi toda la vida real de una factura:
- almacenamiento documental
- OCR/extracción
- validación
- cálculo de emisiones
- duplicados
- INSERT
- auditoría
- reconciliación de estimaciones

Si entiendes `lote_service.py`, entiendes el corazón del sistema.

#### Paso 5 — OCR y extracción
Lee:
1. `services/ocr_service.py`
2. `services/extraccion_service.py`
3. `services/extractor_service.py`

Esto aclara:
- qué parte es OCR puro,
- qué parte es parsing de factura,
- cómo se extenderá a nuevos suministros.

#### Paso 6 — Dominios funcionales
Según la tarea, revisa:
- emisiones/factores → `services/emisiones_service.py`, `services/factores_service.py`
- estimaciones → `services/estimacion_service.py`, `services/gaps_service.py`
- alertas → `services/alertas_service.py`
- dashboard → `services/dashboard_service.py`
- objetivos → `services/objetivos_service.py`
- informes → `services/ghg_report_service.py`
- documentos → `services/documento_service.py`
- auditoría → `services/audit_service.py`
- recálculo → `services/recalculo_service.py`

#### Paso 7 — Capa HTTP
Después mira el blueprint correspondiente en `routes/`.
Regla práctica del proyecto: **la lógica de negocio debe vivir en `services/`; `routes/` debería ser una capa delgada**.

#### Paso 8 — Frontend
Si el cambio toca UX o contratos de respuesta, abre `templates/index.html`.
Como no hay frontend framework, cualquier cambio de endpoint suele exigir revisar manualmente el Fetch asociado.

### Mapa mental rápido del sistema
- `app.py`: arranque y registro.
- `database/`: schema y acceso.
- `services/`: negocio real.
- `routes/`: API REST-like.
- `templates/index.html`: cliente web único.
- `uploads/`: evidencia documental local.
- `facturas_hc.db`: estado persistente y trazabilidad.

---

## 5. Convenciones críticas

### Países
- Siempre en mayúsculas ISO2 o pseudo-ISO del proyecto.
- Ejemplos: `ES`, `AR`, `CO`, `EC`, `MX`.
- No mezclar `es`, `Espana`, `España` dentro de tablas o lógica.

### Sedes
- Formato legible de negocio: `Barcelona`, `Madrid`, `Buenos Aires`.
- En disco se sanea el nombre para carpetas, pero en BD debe mantenerse la forma de negocio.

### Fechas y períodos
- Fechas: `YYYY-MM-DD`
- Meses: `YYYY-MM`
- No usar formatos locales tipo `DD/MM/YYYY` dentro de BD o contratos internos.

### Unidades
- Consumo visible/formularios: normalmente **kWh**.
- Cálculos internos de emisiones: **MWh**.
- Emisiones: siempre **tCO₂e**.
- Factor: siempre **kgCO₂/MWh**.

### Fórmula oficial
```text
tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000
```

No simplificar ni reinterpretar esta fórmula al tocar reporting, validaciones o tests.

### DatosFactura
`DatosFactura` es el contrato base de extracción. Campos clave:
- `pais`
- `consumo_kwh`
- `consumo_mwh`
- `fecha_factura`
- `periodo_inicio`
- `periodo_fin`
- `dias_facturados`
- `mes`
- `comercializadora`
- `sociedad`
- `direccion_suministro`
- `cups`
- `confianza_global`
- `confianza_por_campo`
- `requiere_revision`
- `errores`, `advertencias`, `inconsistencias`
- `texto_preview`
- `exito`

### Patrón de arquitectura que conviene respetar
- **Routes**: validación ligera + serialización HTTP.
- **Services**: reglas de negocio.
- **Database/migrations**: evolución de schema.
- **Factories/Strategies**: extensibilidad (ExtractorFactory, DocumentoStorage).

### Convención de cambios de BD
- Añadir, no romper.
- Crear migración nueva si el cambio es persistente.
- No editar migraciones históricas ya aplicadas salvo emergencia extrema y controlada.

---

## 6. Trampas conocidas

Esta sección es crítica: ya hubo errores costosos que no deben volver.

### 1) Dataclass `DatosFactura` duplicada
Hubo una copia antigua dentro de `extraccion_service.py` que sobrescribía la definición correcta en tiempo de importación.

**Riesgo:** comportamiento fantasma, atributos incoherentes y bugs difíciles de rastrear.

**Regla:** `DatosFactura` debe existir **una sola vez**. Antes de tocar extracción, busca duplicados y evita reintroducir copias.

### 2) `datos.tipo_dato` no existe
Se intentó usar `datos.tipo_dato` desde `lote_service`, pero ese atributo no forma parte de `DatosFactura`.

**Riesgo:** `AttributeError` al procesar facturas.

**Regla:** si necesitas distinguir real/estimado, usa el flujo y columnas de persistencia; no inventes atributos en `DatosFactura` sin diseñarlo de verdad.

### 3) UNIQUE sobre SHA-256 documental
Se llegó a imponer una restricción UNIQUE sobre el hash del documento, impidiendo insertar duplicados potenciales.

**Riesgo:** pérdida de trazabilidad operativa. Dos documentos iguales o casi iguales pueden necesitar registrarse como duplicados a revisar, no bloquearse en duro.

**Regla:** el hash sirve para **detección** y **alerta**, no para impedir la inserción de forma ciega.

### 4) Unidades erróneas de factores
Se utilizaron factores como si estuvieran en tCO₂/MWh cuando debían estar en kgCO₂/MWh. Eso obligó a recalcular 166 facturas.

**Riesgo:** error masivo de reporting ESG.

**Regla:** revisa siempre unidad + fórmula antes de tocar cálculo, semillas, migraciones o informes.

### 5) `config.py` no es fuente de verdad de factores en runtime
El dict `FACTORES_EMISION` solo sirve como seed inicial de la BD.

**Riesgo:** usar valores desalineados respecto al versionado real en `factores_emision`.

**Regla:** cualquier cálculo o consulta operativa debe pasar por `services/emisiones_service.obtener_factor()` o la tabla correspondiente.

### 6) PaddleOCR no es thread-safe
`ocr_service.py` ya lo protege con lock.

**Riesgo:** si intentas paralelizar OCR o cambiar el lock sin cuidado, puedes corromper inferencias o provocar fallos no deterministas.

**Regla:** no conviertas OCR en paralelo ingenuamente. La secuencialidad de lotes es una decisión deliberada.

### 7) Documentación y código pueden divergir
Las guías se reescribieron contra el código actual, pero el repositorio evoluciona y los documentos de fases (`FASES_PROYECTO.md`) describen estados históricos, no el presente.

**Riesgo:** implementar contra documentación desactualizada en vez de contra el código actual.

**Regla:** para decisiones técnicas, **manda el código**; los documentos de fases sirven como contexto histórico.

### 8) La UI está repartida entre partials Jinja y módulos JS sin encapsulación
La SPA se compone de `templates/index.html` + 15 partials y 11 módulos en `static/js/`, todos compartiendo estado global de navegador. No hay framework, bundling ni aislamiento: un pequeño cambio de backend puede romper la UI si no revisas el `fetch` y el DOM afectados.

**Regla:** cualquier cambio de contrato JSON requiere revisar manualmente el módulo JS correspondiente y su partial.

### 9) Migraciones al importar la app
`app.py` ejecuta migraciones al cargar el módulo.

**Riesgo:** si añades migraciones no idempotentes o lentas, romperás arranque y despliegue.

**Regla:** toda migración debe poder correr dos veces sin causar desastre.

---

## 7. Cómo añadir X

### A. Nuevo tipo de suministro
Objetivo típico: gas, agua o residuos.

#### Dónde tocar
- `services/extractor_service.py`
- `services/extraccion_service.py` o un módulo de extracción nuevo si la lógica se complica
- `services/lote_service.py` solo si hace falta pasar/usar `tipo_energia` ya soportado
- migraciones si hay nuevos factores, nuevas columnas o catálogos
- routes/frontend si el usuario debe poder seleccionar el nuevo tipo

#### Estrategia recomendada
1. Crear extractor concreto (`ExtractorGas`, `ExtractorAgua`, etc.).
2. Registrarlo en `ExtractorFactory.register(...)`.
3. Mantener `lote_service` desacoplado del tipo concreto.
4. Reutilizar `DatosFactura` dejando en `None` los campos no aplicables.
5. Revisar si factores de emisión cambian por `tipo_energia`.
6. Revisar alertas, exportaciones y estimaciones para que filtren por `tipo_energia` correctamente.

#### Qué no hacer
- No hardcodear `if tipo == gas` por todo el proyecto.
- No duplicar `DatosFactura`.
- No romper electricidad como caso por defecto.

### B. Nuevo país o nueva sede

#### Para una nueva sede en país existente
1. Añadir sede en `config.py` → `SEDES_PAISES`.
2. Revisar si afecta a reglas de estimación tipo `sede_similar`.
3. Verificar que frontend carga la sede vía `/api/sedes/<pais>`.

#### Para un país nuevo
1. Añadir país en `config.py` (`SEDES_PAISES`, `COMERCIALIZADORAS` si aplica).
2. Añadir seed de factores si todavía no existen en BD.
3. Preferiblemente crear vía migración/servicio los factores en `factores_emision`.
4. Revisar extracción OCR si el formato de factura del país es muy distinto.
5. Revisar si el frontend lista el país manualmente en `templates/index.html` o vía endpoint.

#### Checklist mínimo
- país disponible en API
- sedes disponibles
- factor disponible para el año
- extracción soportada
- dashboard/reporting no rompe filtros

### C. Nueva migración
1. Entender primero el schema actual leyendo `database/migrations.py` y la fase afectada.
2. Crear migración aditiva e idempotente.
3. Añadir ejecución al orquestador en el orden correcto.
4. Si añades columnas, usar precheck o helper seguro.
5. Si añades índices, justificarlos con consultas reales.
6. Arrancar la app y confirmar que la migración no rompe el boot.

### D. Nuevo endpoint
1. Define el contrato JSON primero.
2. Implementa o reutiliza lógica en `services/`.
3. Añade el blueprint en `routes/` correspondiente o crea uno nuevo si es un dominio nuevo real.
4. Si cambias respuestas consumidas por la SPA, actualiza `templates/index.html`.
5. Revisa errores, códigos HTTP y consistencia de nombres.
6. Valida con una llamada dirigida.

### E. Nuevo detector de alertas
1. Revisa `services/alertas_service.py` y cómo se encadena la generación.
2. Implementa una función nueva con criterios claros.
3. Evita duplicar alertas ya pendientes del mismo subtipo/entidad/período.
4. Decide severidad y payload útil.
5. Confirma que listados y resumen siguen funcionando.
6. Si depende de volumen, considera índice SQL solo si es necesario.

---

## 8. Archivos que NO hay que tocar (salvo necesidad muy explícita)

### `facturas_hc.db`
**No editar manualmente** salvo tareas controladas de mantenimiento o validación directa de datos.

Motivo:
- contiene estado real del sistema
- puede incluir histórico valioso
- cambios manuales sin migración/servicio rompen trazabilidad

### Migraciones históricas ya aplicadas (`database/migrations_fase*.py`, `migrations_mejoras.py`, `migrations_refactor.py`)
**No reescribirlas** como práctica habitual.

Motivo:
- alteras la historia del schema
- puedes romper instalaciones existentes
- haces imposible razonar sobre datos ya migrados

Lo correcto casi siempre es: **crear una nueva migración**.

### `venv\`
No tocar ni versionar cambios manuales aquí.

Motivo:
- no forma parte del código del producto
- solo introduce ruido y falsas diferencias

### Archivos `.zip` de fases antiguas
- `fase 1.zip`
- `fase 2.zip`
- `fase 3.zip`
- `fase 4.zip`

No tocar salvo que estés haciendo arqueología del proyecto.

Motivo:
- son histórico de entregas, no superficie de desarrollo activa

### Documentación de instalación/README, salvo trabajo documental explícito
`README.md`, `INSTALACION.md`, `INSTALACION_RAPIDA.md` y `REFERENCIA_RAPIDA.md` están alineados con el código, pero no son la fuente de verdad para implementar cambios.

Motivo:
- describen el sistema, no lo definen
- ante discrepancia, la fuente de verdad es el código

### `services/ocr_service.py` — tocar con mucho cuidado
No cambiar su modelo de concurrencia sin motivo fuerte.

Motivo:
- el lock alrededor de PaddleOCR resuelve un problema real de thread-safety
- cambios ingenuos aquí pueden romper lotes de forma intermitente

---

## 9. Archivos que siempre hay que revisar cuando se hace un cambio

### Siempre
- `app.py` → para entender arranque y blueprints activos.
- `config.py` → para convenciones, seeds y listas maestras.
- `database/migrations.py` → si cambias persistencia.
- `templates/index.html` → si cambia cualquier contrato consumido por la UI.

### Si cambias carga de facturas
- `services/lote_service.py`
- `services/documento_service.py`
- `services/extractor_service.py`
- `services/extraccion_service.py`
- `services/ocr_service.py`
- `routes/facturas.py`

### Si cambias emisiones o factores
- `services/emisiones_service.py`
- `services/factores_service.py`
- `routes/factores_admin.py`
- tablas/migraciones relacionadas con `factores_emision`
- cualquier informe o dashboard que muestre emisiones

### Si cambias estimaciones
- `services/estimacion_service.py`
- `services/gaps_service.py`
- `routes/estimaciones.py`
- `services/lote_service.py` (por la reconciliación automática)
- `services/alertas_service.py` (porque hay detectores ligados a cobertura/estimación)

### Si cambias alertas
- `services/alertas_service.py`
- `routes/alertas.py`
- `templates/index.html` (badges/resúmenes)
- dashboard si consume resumen de alertas

### Si cambias dashboard, reporting u objetivos
- `services/dashboard_service.py`
- `services/objetivos_service.py`
- `services/ghg_report_service.py`
- `routes/dashboard.py`
- `routes/objetivos.py`
- `routes/ghg_report.py`
- `templates/index.html`

### Si cambias almacenamiento documental
- `services/documento_service.py`
- `routes/facturas.py` (servir PDF / borrar / detalles)
- `services/lote_service.py`
- schema de `facturas` y `documentos_indice`

---

## 10. Contexto de negocio

### Empresa y usuarios
Hiberus necesita consolidar consumos eléctricos y emisiones asociadas para su seguimiento corporativo. Los usuarios principales son el equipo de sostenibilidad, no un equipo técnico finalista ni usuarios públicos.

### Objetivo real del producto
No es solo “subir PDFs”. El objetivo es tener una **cadena de custodia ESG**:
- documento fuente
- extracción verificable
- cálculo reproducible
- trazabilidad de cambios
- cobertura temporal completa
- reporting listo para dirección o auditoría interna

### Implicaciones prácticas
- **La trazabilidad importa tanto como el dato.** Por eso existen `audit_log`, `documentos_indice`, `sha256_documento`, versionado de factores y alertas.
- **Los huecos de cobertura importan.** No basta con guardar facturas; hay que saber qué meses faltan y cómo se estiman.
- **La calidad del OCR importa, pero no es suficiente.** Por eso se controla confianza, incoherencias y anomalías estadísticas.
- **El reporting ESG necesita consistencia temporal y de unidades.** Un error de unidad en factores o fechas contamina cuadros de mando e informes.

### Cumplimiento y reporting
El sistema está orientado explícitamente a informes alineados con **GHG Protocol** y reporting ESG corporativo. Aunque el repo no implementa un motor normativo complejo, cualquier cambio debe conservar:
- coherencia de emisiones
- trazabilidad de factores
- posibilidad de explicar cada cifra hacia atrás

### Sensibilidad del dato
Las facturas contienen datos empresariales sensibles (consumos, ubicaciones, proveedores, potencialmente CIF/sociedad/dirección). Esto refuerza la necesidad de:
- autenticación futura
- control de acceso a documentos
- no romper auditabilidad

---

## 11. Próximos pasos inmediatos recomendados

### Prioridad 1 — Cerrar seguridad básica
**Añadir autenticación Azure AD** o un mecanismo corporativo equivalente.

Por qué:
- el portal ya maneja documentos y métricas sensibles
- ahora mismo cualquiera con acceso al entorno podría usarlo

### Prioridad 2 — Decidir estrategia documental corporativa
**Implementar SharePointDocumentoStorage** si el objetivo es dejar de depender del filesystem local.

Por qué:
- la arquitectura ya lo prevé
- hoy existe desacoplamiento suficiente para hacerlo sin reescribir el resto

### Prioridad 3 — Añadir tests de regresión en áreas críticas
Empezar por:
1. `services/emisiones_service.py`
2. `services/estimacion_service.py`
3. `services/alertas_service.py`
4. migraciones idempotentes

Por qué:
- ya hubo errores históricos de unidad y contrato de datos
- el sistema ha crecido lo suficiente como para necesitar red de seguridad

### Prioridad 4 — Limpiar y actualizar documentación viva
Especialmente:
- `README.md`
- `INSTALACION.md`
- `INSTALACION_RAPIDA.md`

Por qué:
- siguen reflejando etapas previas
- pueden confundir a futuros desarrolladores o IAs

### Prioridad 5 — Preparar integraciones corporativas
Elegir orden entre:
- Power BI
- SharePoint
- nuevos suministros
- PostgreSQL

Recomendación práctica de secuencia:
1. Auth
2. SharePoint
3. Tests
4. Power BI
5. Nuevos suministros
6. PostgreSQL solo si realmente hay presión de escalado/concurrencia

### Prioridad 6 — Revisar modularidad del frontend
`templates/index.html` seguirá siendo un cuello de botella de mantenibilidad si crecen mucho las pantallas. No hace falta reescribirlo ya, pero sí conviene planificar una separación progresiva de JS y vistas.

---

## Apéndice rápido de referencia

### Blueprints activos en `app.py`
- `facturas`
- `exportacion`
- `estadisticas`
- `configuracion`
- `factores_admin`
- `fuentes`
- `recalculo`
- `estimaciones`
- `dashboard`
- `alertas`
- `ghg_report`
- `objetivos`

### Servicios clave
- `ocr_service.py`
- `extraccion_service.py`
- `extractor_service.py`
- `lote_service.py`
- `emisiones_service.py`
- `estimacion_service.py`
- `factores_service.py`
- `gaps_service.py`
- `alertas_service.py`
- `dashboard_service.py`
- `objetivos_service.py`
- `ghg_report_service.py`
- `documento_service.py`
- `audit_service.py`
- `recalculo_service.py`

### Tablas principales a tener en mente
- `facturas`
- `estimaciones`
- `factores_emision`
- `objetivos_emision`
- `alertas`
- `audit_log`
- `documentos_indice`
- `metodo_estimacion_metricas`

### Regla final para continuar el proyecto sin romperlo
Si dudas entre confiar en un documento antiguo o en el código actual, **confía en el código actual**; después, actualiza la documentación para que el siguiente no tenga que adivinar.
