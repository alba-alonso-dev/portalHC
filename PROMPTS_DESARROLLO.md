# PROMPTS_DESARROLLO — Portal de Datos Ambientales Hiberus

## Cómo usar este documento

- Cada bloque está pensado para pegarse tal cual en Claude, GPT o Gemini vía LiteLLM.
- Los prompts son autocontenidos: incluyen el contexto técnico y funcional mínimo para trabajar sin historial previo.
- En los prompts genéricos, la instrucción es tomar como requisito la petición funcional descrita en el mensaje del usuario, issue o ticket inmediatamente anterior; no hace falta reescribir el prompt.
- Si el modelo puede editar código, debe hacerlo de forma quirúrgica, validar el cambio y explicar riesgos.

---

## 1) Añadir nueva funcionalidad — template genérico
**Etiqueta de uso:** `feature-generic`

```text
Actúa como un desarrollador senior full-stack trabajando sobre el repositorio local del proyecto “Portal de Datos Ambientales — Hiberus”. Toma como requisito funcional exacto la petición descrita en el mensaje del usuario, issue o ticket inmediatamente anterior.

Contexto del proyecto:
- Sistema interno para gestión de facturas energéticas y reporting ESG.
- Stack: Python 3.13, Flask 3.1, SQLite en WAL mode, SPA servida desde templates/index.html + partials Jinja, con 11 módulos JavaScript vanilla en static/js/ + Fetch API.
- OCR: pdfplumber como vía rápida y PaddleOCR como fallback.
- Sin autenticación, sin Docker y sin suite formal de tests.
- Fórmula de emisiones: tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000.
- Países actuales: ES, AR, CO, EC, MX.
- La tabla central es facturas; hay estimaciones, alertas, factores_emision, objetivos_emision, audit_log y documentos_indice.
- Las rutas Flask están en routes/ y la lógica de negocio en services/.
- app.py registra 12 blueprints bajo /api/*.
- El pipeline principal de carga está en services/lote_service.py.
- Los factores en config.py son solo seed inicial; la fuente de verdad en runtime es la tabla factores_emision y services/emisiones_service.obtener_factor().
- Convenciones: países en mayúsculas, meses YYYY-MM, fechas YYYY-MM-DD, emisiones siempre en tCO₂e, consumo en kWh de entrada y MWh para cálculo interno.
- Errores históricos que no deben reintroducirse:
  1. No duplicar la dataclass DatosFactura.
  2. No usar datos.tipo_dato; no existe en DatosFactura.
  3. No restaurar una UNIQUE sobre sha256_documento que bloquee duplicados.
  4. No usar factores en tCO₂/MWh; la unidad correcta es kgCO₂/MWh.

Objetivo:
1. Inspecciona el código afectado por el requisito.
2. Propón un plan corto.
3. Implementa el cambio completo de forma quirúrgica.
4. Si el cambio toca backend, revisa si requiere ajuste en routes/, services/, migrations/ y templates/index.html.
5. Si el cambio altera persistencia, añade una migración nueva; no reescribas migraciones históricas ya aplicadas.
6. Valida con la comprobación más pequeña y relevante disponible.
7. Resume qué cambiaste, riesgos y siguientes pasos.

Criterios de calidad:
- Mantén compatibilidad con el comportamiento actual.
- No cambies código no relacionado.
- Prefiere servicios para lógica de negocio y blueprints finos.
- Si hay dudas de negocio no resolubles, implementa la opción más conservadora y documenta el supuesto.
```

---

## 2) Añadir nuevo tipo de suministro (gas natural, agua, residuos)
**Etiqueta de uso:** `feature-new-supply-type`

```text
Quiero extender el “Portal de Datos Ambientales — Hiberus” para soportar un nuevo tipo de suministro usando la arquitectura existente basada en ExtractorFactory. Implementa el soporte completo para el nuevo suministro descrito en el contexto del mensaje anterior del usuario; si no se especifica uno, implementa la base preparada para “gas”.

Contexto técnico obligatorio:
- Backend: Flask + SQLite.
- OCR y extracción actuales pensados para electricidad.
- services/extractor_service.py define ExtractorFactura, ExtractorElectricidad y ExtractorFactory.
- Actualmente están registrados placeholders para: gas, agua, residuos y viajes.
- services/lote_service.py ya llama a ExtractorFactory.get(tipo_energia).extraer(...), así que la extensión debe apoyarse en esta factoría y evitar hardcodes adicionales.
- DatosFactura vive en services/extraccion_service.py y debe seguir teniendo una única definición.
- El sistema calcula emisiones con factors por país/año; si el nuevo suministro requiere factores distintos, diseña el cambio sin romper electricidad.
- Hay tablas y flujos ligados a facturas, alertas, exportación y auditoría.

Tareas esperadas:
1. Analiza qué cambios mínimos son necesarios en extractor_service.py, extraccion_service.py, lote_service.py, factores_emision/migraciones, routes y frontend.
2. Implementa el nuevo extractor concreto (por ejemplo ExtractorGas) y regístralo en ExtractorFactory.
3. Añade validaciones, campos opcionales y convenciones específicas del suministro sin romper electricidad.
4. Si hacen falta nuevos factores, crea migración aditiva y seed correspondiente.
5. Revisa si alertas, estimaciones y exportaciones deben distinguir tipo_energia.
6. Valida el flujo de principio a fin con la verificación más pequeña posible.
7. Entrega resumen indicando limitaciones y trabajo pendiente si la extracción OCR del nuevo suministro queda solo parcialmente soportada.

Restricciones:
- No modifiques lote_service para acoplarlo a un tipo concreto.
- No dupliques DatosFactura.
- No edites migraciones históricas; crea una nueva.
- Mantén compatibilidad con electricidad como caso por defecto.
```

---

## 3) Crear nueva migración de base de datos
**Etiqueta de uso:** `db-new-migration`

```text
Necesito una nueva migración para el proyecto “Portal de Datos Ambientales — Hiberus”. Toma como requisito de schema el cambio solicitado en el mensaje anterior del usuario y crea la migración siguiendo las convenciones reales del repositorio.

Contexto del proyecto:
- Base de datos SQLite local en archivo facturas_hc.db.
- Conexiones mediante database/connection.py con row_factory=sqlite3.Row, foreign_keys=ON y journal_mode=WAL.
- Orquestador en database/migrations.py; llama secuencialmente a migrations_fase2.py, fase3, refactor, mejoras, fase4, fase5 y fase6.
- Las migraciones deben ser idempotentes y thread-safe.
- El proyecto usa CREATE TABLE IF NOT EXISTS, prechecks con PRAGMA table_info y ALTER TABLE protegido.
- No se deben reescribir migraciones antiguas ya aplicadas sobre datos reales.

Instrucciones de implementación:
1. Inspecciona el esquema actual y localiza el lugar correcto para la nueva migración.
2. Crea un archivo de migración nuevo o añade una función nueva bien aislada dentro de la fase que corresponda solo si esa es la convención predominante y no rompe trazabilidad; prioriza un archivo nuevo si el cambio es sustancial.
3. Registra la ejecución en database/migrations.py en el orden correcto.
4. Haz la migración aditiva y segura ante dobles ejecuciones.
5. Añade índices solo si están justificados por consultas reales.
6. Si el cambio requiere seed inicial, sepáralo claramente del DDL.
7. Ejecuta la verificación mínima necesaria para confirmar que arranca sin romper migraciones previas.

Reglas:
- Nunca borres columnas ni tablas con datos históricos.
- No metas lógica de negocio compleja dentro de la migración.
- Si cambian unidades o semántica, documenta explícitamente la convención resultante.
- Si tocas factores de emisión, la unidad correcta es kgCO₂/MWh.
```

---

## 4) Revisar y mejorar endpoint existente
**Etiqueta de uso:** `api-improve-endpoint`

```text
Revisa y mejora el endpoint solicitado en el mensaje anterior dentro del proyecto “Portal de Datos Ambientales — Hiberus”. Si el usuario no identifica el endpoint exacto, localiza el más probable a partir del contexto funcional descrito.

Contexto del sistema:
- Flask con blueprints en routes/.
- Los endpoints son /api/* y delegan la lógica a services/.
- El frontend es una SPA en templates/index.html que consume JSON vía Fetch API.
- No hay autenticación ni serialización avanzada.
- La base de datos es SQLite, por lo que hay que cuidar tiempos de consulta y concurrencia.

Objetivo:
1. Analiza el endpoint actual: contrato de entrada, salida JSON, validaciones, errores y dependencia de servicios.
2. Detecta problemas de diseño, duplicación, validación, manejo de errores, consultas ineficientes o incoherencias de naming.
3. Mejora el endpoint sin romper el contrato externo salvo que el requerimiento lo exija.
4. Si cambias el JSON de respuesta, actualiza también el consumo del frontend o documenta compatibilidad.
5. Valida el resultado con una comprobación dirigida.

Criterios específicos:
- Los blueprints deben seguir siendo finos; mueve lógica a services si hace falta.
- Usa mensajes de error útiles y consistentes.
- Revisa impacto sobre audit_log, alertas, estimaciones o recalculo si el endpoint toca esas áreas.
- Resume antes/después, riesgos de compatibilidad y posibles mejoras futuras.
```

---

## 5) Añadir nuevo detector de alertas
**Etiqueta de uso:** `feature-new-alert-detector`

```text
Añade un nuevo detector automático de alertas al “Portal de Datos Ambientales — Hiberus” usando el patrón real existente en services/alertas_service.py y las rutas expuestas en routes/alertas.py. Toma como definición del detector la necesidad descrita en el mensaje anterior del usuario.

Contexto actual:
- Ya existen detectores para consumo_cero, confianza_baja, periodo_solapado, gap_cobertura, factor_desactualizado, estimacion_larga, duplicado_potencial, outlier_consumo, z-score consumo, cambio_interanual_brusco, periodo_anomalo y ocr_incoherente.
- Las alertas se generan automáticamente y se persisten en la tabla alertas.
- Hay endpoints para generar, listar, resumir, resolver e ignorar alertas.
- El sistema tiene trazabilidad y contexto ESG; evita falsos positivos masivos.

Implementa así:
1. Estudia la estructura de services/alertas_service.py y cómo se encadena la generación.
2. Diseña el nuevo detector con criterios explícitos, severidad, subtipo y payload útil para el usuario.
3. Evita duplicar alertas pendientes del mismo subtipo para la misma entidad/período.
4. Añade cualquier índice o soporte de datos solo si es imprescindible.
5. Verifica que el resumen y los listados siguen funcionando.
6. Explica la regla, umbrales elegidos, posibles falsos positivos y cómo ajustarlos.

Restricciones:
- No rompas detectores existentes.
- Si introduces umbrales numéricos, documéntalos en comentarios solo si son poco obvios.
- Mantén consistencia con la taxonomía actual de tipos/subtipos y severidades.
```

---

## 6) Añadir nuevo método de estimación
**Etiqueta de uso:** `feature-new-estimation-method`

```text
Añade un nuevo método de estimación de consumo al proyecto “Portal de Datos Ambientales — Hiberus”. Toma como definición del método la necesidad descrita en el mensaje anterior del usuario; si no se especifica ninguna, implementa la infraestructura para un método llamado “regresion_simple” sin activarlo por defecto.

Contexto técnico:
- services/estimacion_service.py concentra la lógica.
- Métodos actuales: media_historica, mismo_mes_anio_anterior, adyacente, manual, sede_similar, ponderado, por_dias y estacional.
- Existen funciones de creación de estimaciones, resolución de huecos, reconciliación automática y métricas por método en metodo_estimacion_metricas.
- Las estimaciones pueden ser sustituidas automáticamente por facturas reales al cargarse.

Objetivo:
1. Inspecciona cómo se registran y seleccionan los métodos actuales.
2. Implementa el nuevo método con detalle reproducible, referencias y nivel de confianza coherente.
3. Integra el método en la comparativa de métodos y, si procede, en resolver-hueco.
4. Revisa impacto sobre reconciliación automática y métricas acumuladas.
5. Si hacen falta columnas nuevas, crea migración aditiva.
6. Valida el flujo mínimo y explica cuándo conviene o no usar el método.

Criterios:
- No degrades la calidad de los métodos actuales.
- Si el nuevo método necesita histórico mínimo, controla el caso de datos insuficientes.
- Mantén las unidades: kWh para entrada/almacenamiento visible y MWh solo para cálculos internos donde aplique.
```

---

## 7) Integrar SharePoint como DocumentoStorage alternativo
**Etiqueta de uso:** `integration-sharepoint-storage`

```text
Implementa la integración de SharePoint como backend alternativo de almacenamiento documental en el proyecto “Portal de Datos Ambientales — Hiberus”, completando el esqueleto existente en services/documento_service.py.

Contexto técnico conocido:
- Existe una abstracción DocumentoStorage con LocalDocumentoStorage y un placeholder SharePointDocumentoStorage.
- La selección se hace por variable de entorno DOCUMENTO_STORAGE=local|sharepoint.
- El resto del sistema ya usa get_documento_storage(), por lo que la integración debe respetar esa interfaz.
- El método guardar() debe devolver: archivo_nombre, archivo_ruta, carpeta_relativa, external_source, external_doc_id, external_doc_url, sha256 y fuente_documento_id.
- resolver_acceso() debe permitir servir el PDF o redirigir a la URL remota.
- lote_service usa doc_info para persistir la factura y alimentar duplicados/auditoría.
- uploads/ es el backend local actual y documents_indice conserva la trazabilidad.

Lo que necesito que hagas:
1. Diseña e implementa SharePointDocumentoStorage con Microsoft Graph API o, si no hay credenciales disponibles, deja una implementación lista para configurar sin romper local.
2. Añade configuración por variables de entorno para tenant, client id, secret/cert, site, drive y carpeta raíz.
3. Mantén compatibilidad total con LocalDocumentoStorage.
4. Decide cómo obtener SHA-256 sin depender de descargar el archivo otra vez.
5. Define estrategia de nombres/carpetas equivalente a uploads/{YYYY}/{PAIS}/{SEDE}/{archivo}.
6. Revisa impacto en descarga de PDFs, eliminación y auditoría.
7. Añade documentación mínima inline o en comentarios donde sea estrictamente necesario.
8. Valida al menos el arranque y la selección de backend; si no puedes validar subida real por falta de credenciales, deja claro qué queda pendiente.

Importante:
- No acoples rutas o servicios a SharePoint directamente; todo debe pasar por DocumentoStorage.
- No rompas el flujo local existente.
```

---

## 8) Integrar Power BI para visualización
**Etiqueta de uso:** `integration-powerbi`

```text
Quiero integrar Power BI en el “Portal de Datos Ambientales — Hiberus” para visualización ejecutiva, partiendo del estado actual del proyecto.

Contexto del sistema:
- El portal ya expone datos operativos y agregados vía endpoints Flask: dashboard, estadísticas, alertas, estimaciones, factores, objetivos y GHG report.
- El frontend actual es una SPA sencilla en templates/index.html.
- No hay autenticación todavía.
- Los usuarios son internos del equipo de sostenibilidad de Hiberus.
- El objetivo de negocio es reporting ESG corporativo y seguimiento de emisiones.

Trabajo solicitado:
1. Analiza si la integración debe ser embebido directo en la SPA, consumo desde Power BI Service o exportación de datasets intermedios.
2. Implementa la solución más realista y de menor riesgo con el estado actual del proyecto.
3. Si hace falta crear endpoints específicos para consumo analítico, hazlos de forma desacoplada del frontend actual.
4. Define estructura de dataset útil para KPIs ESG, evolución mensual, cobertura real/estimada, alertas y objetivos.
5. Considera limitaciones actuales: sin auth, SQLite local y uso interno.
6. Si no es viable un embebido completo sin Azure AD, implementa la preparación técnica mínima para que Power BI consuma los datos correctamente.
7. Resume arquitectura recomendada, dependencias necesarias y riesgos.

Criterios:
- No introduzcas una integración frágil basada en scraping del HTML.
- Prefiere JSON tabular/analítico estable y versionable.
- Mantén el portal funcional aunque Power BI no esté configurado.
```

---

## 9) Añadir autenticación Azure AD
**Etiqueta de uso:** `security-azure-ad-auth`

```text
Añade autenticación corporativa con Azure AD al proyecto “Portal de Datos Ambientales — Hiberus”, manteniendo el menor impacto posible sobre la arquitectura existente.

Contexto:
- Aplicación Flask monolítica con SPA en templates/index.html.
- Actualmente no existe autenticación.
- El portal es interno y gestiona documentación sensible (facturas, consumos, reporting ESG).
- Hay endpoints /api/* y operaciones de carga, borrado, recálculo, estimaciones, factores, alertas y objetivos.
- Existe audit_log, por lo que conviene enriquecerlo con usuario real.

Objetivo:
1. Diseña la integración adecuada con Microsoft identity platform para una app interna web.
2. Protege UI y API, minimizando ruptura del frontend actual.
3. Introduce configuración por variables de entorno y un modo desarrollo razonable.
4. Revisa CORS, sesiones, logout, expiración y manejo de errores de autenticación.
5. Actualiza audit_log para registrar usuario autenticado cuando exista.
6. Mantén los blueprints limpios y centraliza autenticación/autorización lo máximo posible.
7. Valida el arranque local y deja documentadas las variables necesarias.

Restricciones:
- No metas credenciales en el código.
- No rompas completamente el modo local si faltan secretos; permite un modo seguro de desarrollo o una degradación explícita controlada.
- Identifica endpoints críticos que deban requerir rol admin si introduces autorización básica.
```

---

## 10) Revisar rendimiento de un servicio o query
**Etiqueta de uso:** `perf-review-service-query`

```text
Haz una revisión de rendimiento sobre el servicio, endpoint o consulta señalado en el mensaje anterior dentro del proyecto “Portal de Datos Ambientales — Hiberus”. Si el usuario no especifica el punto exacto, empieza por el flujo de mayor probabilidad de coste: carga de lotes, dashboard agregado o detección de alertas.

Contexto técnico:
- Backend Flask + SQLite WAL.
- OCR con PaddleOCR como fallback; no es thread-safe y se serializa con lock.
- Procesamiento en lote secuencial en un hilo daemon; polling desde frontend.
- Módulos con queries agregadas: dashboard_service, alertas_service, estimacion_service, ghg_report_service.
- La tabla facturas es central y grande comparada con el resto.

Necesito que:
1. Localices cuellos de botella reales leyendo código y consultas.
2. Diferencies claramente entre I/O de OCR, CPU Python y SQL SQLite.
3. Propongas y, si es seguro, implementes optimizaciones concretas: índices, reducción de consultas repetidas, mejora de agregaciones, paginación, caché local simple o refactor ligero.
4. Evites optimizaciones prematuras que compliquen el mantenimiento.
5. Valides con la comprobación mínima disponible y midas antes/después si es factible.
6. Entregues un informe corto con hallazgos, cambios y próximos pasos.

Criterios:
- No cambies la semántica de resultados.
- Ten en cuenta que SQLite es local y compartido por la app; evita locks innecesarios.
- Si propones migrar a PostgreSQL, trátalo como recomendación futura, no como requisito inmediato salvo petición explícita.
```

---

## 11) Crear nuevo informe (PDF/Excel)
**Etiqueta de uso:** `report-new-output`

```text
Crea un nuevo informe exportable para el proyecto “Portal de Datos Ambientales — Hiberus”, tomando como especificación funcional la petición del mensaje anterior del usuario.

Contexto actual:
- Ya existe services/ghg_report_service.py para informes Excel GHG y routes/ghg_report.py para su exposición.
- También hay exportación histórica en routes/exportacion.py.
- Stack de reporting: openpyxl y pandas.
- El objetivo del producto es reporting ESG corporativo con trazabilidad y uso interno.

Objetivo de trabajo:
1. Analiza si el nuevo informe debe vivir como extensión del informe GHG existente o como módulo aparte.
2. Implementa el servicio de generación y el endpoint necesario.
3. Define claramente estructura del informe, filtros y columnas/hojas.
4. Si el usuario pide PDF y el proyecto no tiene librería de PDF robusta, evalúa la opción menos invasiva y deja claras dependencias nuevas si fueran imprescindibles.
5. Asegura que los datos usen unidades y convenciones correctas: kWh visibles, tCO₂e para emisiones, factores en kgCO₂/MWh.
6. Valida la generación mínima del archivo.
7. Resume uso, formato y limitaciones.

Importante:
- No dupliques lógica de agregación si ya existe en dashboard_service, objetivos_service o ghg_report_service; reutilízala.
- Mantén separada la lógica de consulta, transformación y formateo del archivo.
```

---

## 12) Corregir bug — template con contexto del proyecto
**Etiqueta de uso:** `bugfix-generic`

```text
Corrige el bug descrito en el mensaje anterior dentro del repositorio “Portal de Datos Ambientales — Hiberus”. Trabaja como ingeniero de mantenimiento senior y no te quedes en un parche superficial: identifica causa raíz, aplica una corrección segura y valida el comportamiento.

Contexto del proyecto:
- Flask + SQLite + SPA HTML/JS.
- OCR con pdfplumber y PaddleOCR fallback.
- Pipeline de facturas en services/lote_service.py.
- Migraciones idempotentes en database/migrations.py.
- Sin tests formales; la validación suele ser dirigida y manual.
- Datos sensibles de ESG y trazabilidad, por lo que una corrección no debe dañar histórico ni auditoría.

Puntos críticos a vigilar:
- DatosFactura debe existir una sola vez.
- No usar atributos inexistentes como datos.tipo_dato.
- No bloquear duplicados con una UNIQUE errónea en sha256_documento.
- No volver a unidades incorrectas de factor (tCO₂/MWh en lugar de kgCO₂/MWh).
- Los factores runtime salen de BD, no del dict de config.

Tareas:
1. Reproduce mentalmente o mediante inspección el fallo.
2. Localiza la causa raíz exacta.
3. Corrige el bug con el cambio mínimo suficiente.
4. Revisa efectos laterales en rutas, servicios, migraciones, frontend o reporting.
5. Valida con un test/manual check dirigido.
6. Entrega explicación breve: síntoma, causa raíz, fix, riesgos.
```

---

## 13) Añadir tests para un módulo
**Etiqueta de uso:** `tests-add-module`

```text
Añade tests al módulo indicado en el mensaje anterior del proyecto “Portal de Datos Ambientales — Hiberus”. Si no se especifica módulo, empieza por el más crítico para negocio entre emisiones_service, estimacion_service, alertas_service o lote_service, eligiendo el que pueda cubrirse con menor acoplamiento.

Contexto:
- Actualmente no hay suite formal consolidada.
- Stack backend Python 3.13 + Flask 3.1.
- La BD es SQLite local.
- Algunos servicios son puros y otros dependen de BD o archivos.
- Existe sensibilidad alta a regresiones en cálculo de emisiones, estimaciones, factores y alertas.

Objetivo:
1. Detecta el runner más razonable ya disponible o, si no existe ninguno, propone la mínima incorporación viable solo si el repositorio realmente carece de herramienta y el valor lo justifica.
2. Crea tests legibles que documenten reglas de negocio.
3. Prioriza casos críticos: unidades, fechas, reconciliación, duplicados, umbrales y detectores.
4. Aísla dependencias externas cuando sea posible.
5. Evita reescribir masivamente código productivo solo para testearlo; haz refactors pequeños si son necesarios.
6. Ejecuta el subconjunto de tests creado o el runner mínimo aplicable.
7. Resume cobertura añadida y huecos pendientes.

Casos especialmente valiosos:
- Fórmula de emisiones y lookup de factores.
- Métodos de estimación y confianza.
- Detección de alertas no duplicadas.
- Migraciones idempotentes.
```

---

## 14) Revisar arquitectura antes de una nueva fase
**Etiqueta de uso:** `architecture-phase-review`

```text
Haz una revisión arquitectónica del proyecto “Portal de Datos Ambientales — Hiberus” antes de arrancar una nueva fase de desarrollo. Toma como foco la fase o iniciativa descrita en el mensaje anterior del usuario; si no se especifica, evalúa la preparación para una Fase 7 orientada a escalado funcional e integraciones corporativas.

Contexto del producto:
- Portal interno de facturas energéticas y reporting ESG.
- Stack actual deliberadamente simple: Flask monolítico, SQLite, SPA vanilla, sin auth, sin Docker, sin tests formales.
- Ya existen módulos de OCR, factores versionados, estimaciones avanzadas, alertas automáticas, objetivos ESG, dashboard e informe GHG.
- Hay placeholders o líneas de evolución para SharePoint, nuevos suministros, Power BI y Azure AD.

Quiero que:
1. Describas la arquitectura actual real, no una idealizada.
2. Identifiques fortalezas, cuellos de botella, deuda técnica y límites de escalabilidad.
3. Señales qué partes están bien encapsuladas (por ejemplo DocumentoStorage, ExtractorFactory) y cuáles siguen acopladas.
4. Propongas un roadmap técnico priorizado para la siguiente fase.
5. Clasifiques recomendaciones en: imprescindible ahora, importante después, opcional.
6. Si es conveniente, sugiere refactors concretos con bajo riesgo.
7. Mantengas el análisis aterrizado al código existente y al contexto de negocio ESG.

Entrega esperada:
- Diagnóstico ejecutivo.
- Riesgos técnicos.
- Recomendaciones priorizadas.
- Decisiones de arquitectura que conviene mantener.
```

---

## 15) Migrar SQLite a PostgreSQL
**Etiqueta de uso:** `migration-sqlite-to-postgresql`

```text
Planifica e implementa la migración de persistencia desde SQLite a PostgreSQL para el proyecto “Portal de Datos Ambientales — Hiberus”, manteniendo compatibilidad funcional con el estado actual del sistema.

Contexto técnico actual:
- SQLite local con WAL y acceso vía sqlite3 directo en database/connection.py.
- Migraciones hechas manualmente con SQL y orquestadas desde database/migrations.py.
- Muchas consultas viven en services/ y asumen sintaxis SQLite o su tolerancia tipológica.
- El sistema usa facturas, estimaciones, factores_emision, alertas, objetivos_emision, audit_log y documentos_indice.
- La app es Flask y no utiliza ORM.

Trabajo solicitado:
1. Inspecciona el código y detecta dependencias concretas de SQLite: pragmas, placeholders, sintaxis, tipos, funciones de fecha, row_factory, autoincrement, etc.
2. Propón una estrategia de migración incremental con riesgo controlado.
3. Implementa la capa mínima necesaria para soportar PostgreSQL sin romper SQLite si la coexistencia temporal es razonable.
4. Adapta connection.py y los puntos críticos del acceso a datos.
5. Decide si conviene introducir un driver como psycopg y cómo parametrizar la conexión por variables de entorno.
6. Revisa migraciones e idempotencia en el nuevo motor.
7. Valida los flujos críticos: arranque, migraciones, lectura/escritura de facturas y consultas principales.
8. Documenta incompatibilidades o SQL pendiente de adaptar.

Restricciones:
- No hagas una reescritura total salvo que sea imprescindible.
- No pierdas trazabilidad ni semántica de datos históricos.
- Conserva las convenciones de negocio del proyecto: fechas ISO, meses YYYY-MM, emisiones en tCO₂e, factores en kgCO₂/MWh.
```
