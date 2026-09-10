# Deuda técnica y estado técnico del proyecto

## 1. Lo que está bien resuelto

### 1.1 Trazabilidad del cálculo
- Cada factura puede vincularse a una versión concreta de factor (`factor_version_id`).
- Los cambios de factores quedan registrados en `factores_historial`.
- Los recálculos no destruyen histórico: se guardan en columnas separadas y en `recalculos_historial`.

### 1.2 Migraciones de base de datos
- Son **idempotentes** y mayoritariamente **aditivas**.
- El sistema protege migraciones concurrentes con lock en hilo y lock basado en fichero.
- La estrategia es adecuada para un producto vivo con históricos que no pueden perderse.

### 1.3 Gestión documental
- El almacenamiento está desacoplado mediante `DocumentoStorage`.
- La organización por ejercicio / país / sede facilita trazabilidad y futura migración a SharePoint.
- El hash SHA256 aporta control de duplicados a nivel documental.

### 1.4 OCR y extracción
- Se combina extracción directa (`pdfplumber`) con OCR como fallback.
- Se mide confianza OCR y se decide revisión manual en función de umbral.
- El acceso a PaddleOCR se serializa para evitar corrupción por falta de thread-safety.

### 1.5 Calidad del dato
- Existen validaciones en carga, confirmación y reporting.
- Hay soporte formal para datos reales, estimados y faltantes.
- Ya hay métricas de error y reconciliación estimado → real.

### 1.6 Capacidad de reporting
- Dashboard ESG funcional.
- Alertas automáticas operativas.
- Informe GHG Protocol exportable.
- Objetivos ESG y proyección de cierre ya disponibles.

---

## 2. Deuda técnica conocida y priorizada

## Prioridad P0 — corregir o planificar de inmediato

### 2.1 Sin autenticación ni autorización
- Estado: pendiente estructural.
- Impacto:
  - cualquier usuario con acceso al portal puede operar sin control de identidad,
  - no existe segregación de permisos,
  - el `usuario` en muchos flujos es un valor declarativo, no autenticado.
- Riesgo: alto.
- Fase prevista: 7 (Azure AD / Microsoft).

### 2.2 Sin test automatizado formal
- Estado: no hay batería formal de tests unitarios/integración/regresión.
- Impacto:
  - mayor riesgo al refactorizar,
  - errores sutiles pueden reintroducirse,
  - validación muy dependiente de prueba manual.
- Riesgo: alto.

### 2.3 Semilla obsoleta en `config.py`
- Estado: `config.py` sigue mostrando factores en tCO2/MWh, mientras la BD ya opera con kgCO2/MWh.
- Impacto:
  - induce a error a quien lea el código,
  - puede sembrar datos incorrectos en escenarios nuevos o reconstrucciones.
- Riesgo: alto porque es una deuda conceptual, no operativa inmediata.

## Prioridad P1 — importante a corto plazo

### 2.4 SQLite como cuello de botella futuro
- Estado: aceptable para equipo pequeño, pero insuficiente para alta concurrencia.
- Impacto:
  - bloqueo de escrituras concurrentes,
  - escalabilidad limitada,
  - más fricción si el producto pasa a uso intensivo o multiárea.
- Riesgo: medio-alto.
- Mitigación prevista: migración a PostgreSQL.

### 2.5 Frontend monolítico en un único HTML/JS
- Estado: la SPA está concentrada en `templates\index.html` y supera ampliamente un tamaño mantenible.
- Impacto:
  - difícil de navegar,
  - alta probabilidad de regresiones de interfaz,
  - baja reutilización.
- Riesgo: medio-alto.

### 2.6 Servicios largos y multifunción
- Casos señalados:
  - `services\dashboard_service.py`
  - `services\lote_service.py`
  - `services\estimacion_service.py`
  - `routes\facturas.py`
- Impacto:
  - dificulta pruebas unitarias,
  - mezcla responsabilidades,
  - complica evolución a nuevos suministros.

### 2.7 Drift documental y naming histórico
- Ejemplos:
  - `app.py` sigue imprimiendo “Fase 4” en el banner, aunque el proyecto va por Fase 6.
- Impacto:
  - confusión para onboarding técnico,
  - coste cognitivo innecesario.

### 2.7.b Filas huérfanas por borrado de facturas — RESUELTO
- **Estado**: corregido. `PRAGMA foreign_key_check` reportaba **189 violaciones**
  (184 filas de `documentos_indice` y 5 de `facturas_historial` apuntando a facturas
  ya inexistentes). Hoy devuelve 0.
- Causa: `POST /api/dev/reset-datos` vaciaba las tablas transaccionales con
  `PRAGMA foreign_keys = OFF` y una lista fija que **no incluía `documentos_indice`**.
  Al borrar `facturas` con las claves foráneas desactivadas, SQLite ni ejecutaba el
  `ON DELETE CASCADE` del índice documental ni avisaba de las referencias rotas.
- Corrección aplicada:
  - `routes/configuracion.py` ya no desactiva las claves foráneas y añade
    `documentos_indice` a la lista, de modo que una tabla olvidada provoca un error
    visible en lugar de corrupción silenciosa.
  - `database/migrations_integridad.py` borra las filas huérfanas existentes y añade
    `ON DELETE CASCADE` a `facturas_historial.factura_id`.
- Riesgo residual: las claves foráneas se activan por conexión, así que cualquier
  borrado hecho desde fuera de `get_db_connection()` (consola `sqlite3`, herramientas
  externas) sigue pudiendo dejar huérfanos. La migración de integridad se ejecuta en
  cada arranque y los limpiaría.

## Prioridad P2 — mejora progresiva

### 2.8 Modelo todavía muy centrado en electricidad
- Aunque existen `tipos_energia`, `suministros` y extractores placeholder, el flujo productivo completo está orientado a electricidad.
- Impacto: dificulta expansión a gas, agua, residuos y viajes.

### 2.9 Dominio mezclado con capa HTTP en algunos puntos
- Algunas validaciones y transformaciones siguen estando repartidas entre `routes` y `services`.
- Impacto: menor cohesión, más lógica repetida, tests más complejos.

### 2.10 Calidad de datos heredados
- Se conoce la existencia de duplicados y registros históricos mejorables.
- Caso citado: duplicados ES 2026 en `facturas.sha256_documento` / referencias activas de factores.
- Impacto: ruido analítico, necesidad de saneamiento selectivo.

---

## 3. Decisiones técnicas tomadas y justificación

### 3.1 SQLite sobre PostgreSQL
- **Decisión**: usar SQLite como motor inicial.
- **Justificación**:
  - cero infraestructura,
  - despliegue muy simple,
  - suficiente para uso interno pequeño,
  - muy útil en fases de descubrimiento.
- **Coste asumido**:
  - menor concurrencia,
  - futura migración.

### 3.2 SPA en HTML vanilla
- **Decisión**: evitar framework frontend.
- **Justificación**:
  - despliegue trivial,
  - sin Node.js ni build,
  - curva de entrada baja.
- **Coste asumido**:
  - crecimiento monolítico,
  - mantenibilidad más baja al aumentar funcionalidades.

### 3.3 PaddleOCR sobre enfoques más simples
- **Decisión**: OCR robusto con PaddleOCR, manteniendo `pdfplumber` como ruta rápida.
- **Justificación**:
  - mejor comportamiento con layouts complejos,
  - tablas y facturas escaneadas mejor resueltas.
- **Coste asumido**:
  - más peso de dependencias,
  - cuidado con thread-safety.

### 3.4 Migraciones aditivas e idempotentes
- **Decisión**: no hacer cambios destructivos como estrategia estándar.
- **Justificación**:
  - preservar histórico,
  - minimizar riesgo sobre BD en uso,
  - compatibilidad con auditoría.

### 3.5 ExtractorFactory
- **Decisión**: usar factoría / registry por `tipo_energia`.
- **Justificación**:
  - permite añadir nuevos suministros sin reescribir `lote_service`,
  - reduce acoplamiento.

### 3.6 SHA256 como índice normal, no único
- **Decisión**: permitir insertar duplicados y marcarlos en aplicación.
- **Justificación**:
  - el negocio necesita detectar y gestionar duplicados, no bloquearlos ciegamente,
  - habilita trazabilidad del error operativo.

### 3.7 Factores en kgCO2/MWh
- **Decisión**: unificar unidad real operativa en kgCO2/MWh.
- **Justificación**:
  - la fórmula ya trabajaba con kg/MWh,
  - evita errores de escala por 1000,
  - es coherente con el nombre de columna `factor_kg_co2_mwh`.

---

## 4. Riesgos conocidos

## 4.1 Seguridad

### Riesgo
- Sin autenticación.
- Sin RBAC.
- Sin segregación real de permisos.

### Consecuencia
- Acceso excesivo a datos y operaciones.
- Imposibilidad de garantizar trazabilidad de usuario real.

### Mitigación prevista
- Azure AD + RBAC en Fase 7.

## 4.2 Escalabilidad

### Riesgo
- SQLite y procesamiento síncrono en partes del sistema.
- Crecimiento del volumen documental y analítico.

### Consecuencia
- Degradación con muchos usuarios o muchas cargas simultáneas.

### Mitigación prevista
- PostgreSQL.
- Posible separación de colas / jobs si escala el lote.

## 4.3 Mantenibilidad

### Riesgo
- Servicios y frontend extensos.
- Lógica repartida entre rutas, servicios y migraciones.

### Consecuencia
- Mayor coste de cambio.
- Refactor más arriesgado.

### Mitigación prevista
- Modularización por dominio y por feature.
- Cobertura de tests.

## 4.4 Calidad del dato

### Riesgo
- OCR imperfecto por naturaleza.
- Reglas heurísticas específicas por comercializadora.
- Datos históricos con inconsistencias o duplicados.

### Consecuencia
- Necesidad de revisión manual en casos límite.
- Alertas falsas positivas / negativas.

### Mitigación prevista
- Más validaciones.
- Métricas por método.
- Ampliación de detectores.

---

## 5. Bugs históricos corregidos

## 5.1 Factores de emisión en unidad incorrecta

### Causa raíz
Los factores estaban almacenados como **tCO2/MWh** (`0.187`) pero el sistema los trataba como **kgCO2/MWh**.

### Efecto
Emisiones infravaloradas por un factor 1000.

### Solución aplicada
- Conversión de factores `< 1.0` multiplicando por 1000.
- Recalculo de facturas afectadas.
- Normalización conceptual en servicios y migraciones.

## 5.2 Índice UNIQUE sobre SHA256 del documento

### Causa raíz
Se había modelado `sha256_documento` con restricción única.

### Efecto
La BD rechazaba el insert antes de que la aplicación pudiera marcar el documento como duplicado potencial.

### Solución aplicada
- Eliminación del `UNIQUE INDEX`.
- Sustitución por índice normal.
- La lógica de detección queda en aplicación y no en bloqueo duro de BD.

## 5.3 `DatosFactura` duplicada / clase sobreescrita

### Causa raíz
Existía duplicación / sobreescritura del modelo de datos de extracción.

### Efecto
- Riesgo de comportamiento inconsistente,
- posible pérdida o divergencia de atributos.

### Solución aplicada
- Unificación del contrato de salida.
- `extractor_service` usa una única definición importada desde `extraccion_service`.

## 5.4 Concurrencia en OCR

### Causa raíz
PaddleOCR no es thread-safe.

---

## 6. Fase 0 — Estabilización (2026-09-06)

Correcciones aplicadas antes de iniciar una nueva fase de desarrollo, basadas
en la revisión arquitectónica (`REVISION_ARQUITECTURA.md`). Todas son de bajo
riesgo y alto retorno.

### 6.1 `.gitignore` creado
- **Antes**: no existía `.gitignore` en la raíz. La BD (`facturas_hc.db`), los
  backups (`.bak`), `uploads/` y `venv/` estaban sin proteger.
- **Riesgo que evita**: si se hace `git init` + `git add .`, la BD con datos de
  facturas reales se commitea al repositorio.
- **Estado**: corregido. `.gitignore` cubre BD, backups, uploads, venv,
  `__pycache__`, `.pytest_cache`, IDE, logs y `.env`.

### 6.2 `busy_timeout` en SQLite
- **Antes**: `database/connection.py` no establecía `PRAGMA busy_timeout`. Un
  segundo escritor concurrente recibía `OperationalError: database is locked`
  sin espera.
- **Corrección**: añadido `conn.execute("PRAGMA busy_timeout=5000")` en
  `get_db_connection()`. Ahora SQLite espera hasta 5 segundos antes de fallar.
- **Estado**: corregido. Test `test_busy_timeout_activo` lo verifica.

### 6.3 Pinning de dependencias
- **Antes**: `requirements.txt` tenía todas las dependencias con `>=` sin límite
  superior. Una instalación limpia podía traer majors con breaking changes.
- **Corrección**: todas las dependencias fijadas con `==` a las versiones
  verificadas del entorno. Creado `requirements.lock` (snapshot exacto con
  transitivas) y `requirements-dev.txt` (pytest + pytest-cov, antes no
  declarados pese a existir `tests/`).
- **Estado**: corregido.

### 6.4 Tabla `schema_migrations`
- **Antes**: no existía tabla de versiones. Las 13 migraciones se re-ejecutaban
  completas en cada arranque (idempotentes, pero con coste). En particular,
  `migrations_fase6._recalcular_emisiones_facturas()` reescribía
  `emisiones_tco2e` de las 136 facturas en cada boot.
- **Corrección**: creada tabla `schema_migrations(modulo, descripcion,
  fecha_ejecucion)`. Cada módulo se ejecuta una sola vez y queda registrado.
  Los módulos externos mantienen su interfaz sin cambios (`_importar_y_ejecutar`
  los invoca sin `conn`).
- **Resultado medible**: arranque de ~1.5s → ~0.17s (90% más rápido, sin
  recalculo de facturas).
- **Estado**: corregido. Test `test_schema_migrations_existe_y_tiene_13_modulos`
  lo verifica.

### 6.5 pytest + smoke tests
- **Antes**: `pytest` estaba instalado pero no declarado en `requirements.txt`.
  No había tests de integración de endpoints.
- **Corrección**: creado `requirements-dev.txt` (pytest==9.1.1, pytest-cov==6.0.0),
  `pytest.ini` con configuración del proyecto, y `tests/test_smoke_endpoints.py`
  con 10 tests:
  - 3 invariantes estructurales (schema_migrations, busy_timeout, foreign_keys)
  - 7 endpoints críticos (dashboard, estadisticas, paises, factores, alertas,
    dashboard ESG, ranking sociedades)
- **Estado**: corregido. 181 tests pasan (171 existentes + 10 nuevos), 0 fallos.

---

## 7. Fase 1 — Refactors de bajo riesgo (2026-09-06)

Refactors de bajo riesgo aplicados tras la Fase 0, basados en la revisión
arquitectónica (`REVISION_ARQUITECTURA.md`). Reducen duplicación y mejoran
la consistencia sin cambiar el comportamiento funcional.

### 7.1 Helper `filtro_facturas` compartido
- **Antes**: `dashboard_service.py` repetía el patrón
  `strftime('%Y', COALESCE(periodo_inicio, fecha_carga)) = ?` + `extra_cond`
  ~30 veces. `ghg_report_service.py` ya tenía `_filtros_base()` pero no se
  compartía.
- **Corrección**: creado `services/_queries.py` con `filtro_facturas()` que
  genera la cláusula WHERE completa (fecha_anulacion + año + pais + sede +
  tipo_energia). `dashboard_service.py` refactorizado para usarlo en
  `kpis_emisiones`, `kpis_calidad`, `kpis_facturacion`, `calidad_ocr_por_campo`
  y `dashboard_proyeccion`.
- **Estado**: corregido. 181 tests pasan.

### 7.2 Mensajes de error genéricos en producción
- **Antes**: ~217 ocurrencias de `str(exc)` en 13 blueprints filtraban
  detalles internos de SQLite (nombres de tablas, columnas, constraints) al
  cliente.
- **Corrección**: creado `routes/_helpers.py` con `server_error(exc, contexto)`
  (500) y `bad_request(exc, contexto)` (400). En producción devuelven
  "Error interno del servidor" / "Solicitud inválida"; en modo debug
  (`FLASK_DEBUG=true`) mantienen el detalle. Los 13 blueprints refactorizados
  para usar los helpers.
- **Estado**: corregido. 181 tests pasan. Solo queda 1 ocurrencia legítima
  (404 ValueError en `objetivos.py`).

### 7.3 API client JS común
- **Antes**: 62 ocurrencias de `fetch()` en 10 archivos JS con patrones
  inconsistentes (`.then(r => r.json())` sin manejo de errores, sin toast).
  `admin_maestros.js` ya tenía un `adminFetch` local.
- **Corrección**: creado `static/js/api.js` con métodos `get`, `post`,
  `postForm`, `put`, `patch`, `del`, `blob`. Manejo de errores automático
  (toast + mensaje del backend). Cargado antes que `core.js` en `index.html`.
- **Estado**: creado y verificado. Los módulos JS existentes pueden migrar
  gradualmente a usar `api.*`; no es necesario hacerlo de golpe.

### 7.4 `url_prefix` en blueprints — APLAZADO
- **Motivo**: el refactor requiere cambiar los 13 `Blueprint()` para añadir
  `url_prefix` y quitar `/api/...` de las 114 rutas. Es un cambio mecánico
  pero extenso con riesgo de romper URLs sin tests E2E que validen cada una.
- **Decisión**: aplazado hasta tener mayor cobertura de tests de endpoints.

### 7.5 Refactors pendientes (Fase 1 continuada)
Los siguientes refactors están identificados pero pendientes de ejecución:
- **Extraer `facturas_service.py`** de `routes/facturas.py` (lógica de
  `confirmar_factura` con ~240 líneas inline).
- **Base class para detectores de alerta** en `alertas_service.py` (12
  funciones `_alertas_*` con la misma estructura).
- **CRUD genérico** para maestros en `maestros_service.py` (6 entidades con
  listar/crear/actualizar/estado/borrar duplicados).

### Efecto
Posible corrupción de estado o errores impredecibles en lotes concurrentes.

### Solución aplicada
- Singleton con lock.
- Serialización de inicialización e inferencia OCR.

## 5.5 Concurrencia en migraciones

### Causa raíz
Las migraciones se ejecutan al importar la app y podían coincidir en escenarios multi-hilo o multi-proceso.

### Efecto
Riesgo de carrera sobre DDL idempotente.

### Solución aplicada
- `threading.Lock`
- file lock por `.migration.lock`
- tolerancia explícita a columnas ya existentes.

---

## 6. Qué refactorizar en próximas fases

## 6.1 Seguridad y acceso
- Introducir capa de autenticación real.
- Sustituir `usuario='usuario'` por identidad federada.
- Añadir autorización por roles y ámbitos.

## 6.2 Frontend
- Extraer la SPA en módulos:
  - dashboard,
  - facturas,
  - alertas,
  - estimaciones,
  - objetivos,
  - reporting.
- Separar JS, HTML parcial y estilos.
- Preparar componentes reutilizables.

## 6.3 Servicios de dominio
- Dividir `dashboard_service` en subservicios:
  - emisiones,
  - cobertura,
  - calidad,
  - ejecutivo ESG.
- Dividir `lote_service` en:
  - orquestación,
  - validación,
  - persistencia,
  - reconciliación.
- Normalizar DTOs / modelos de respuesta.

## 6.4 Acceso a datos
- Reducir SQL embebido repetido.
- Introducir repositorios ligeros o capa de consultas compartidas.
- Centralizar filtros comunes por ejercicio / país / sede / tipo de energía.

## 6.5 Testing
- Crear suite mínima:
  - tests de cálculo de emisiones,
  - tests de estimaciones,
  - tests de reconciliación,
  - tests de migraciones críticas,
  - tests de endpoints principales.

## 6.6 Nuevos suministros
- Implementar extractores reales para gas y agua.
- Generalizar unidades, factores, métricas y dashboards más allá de electricidad.

## 6.7 Persistencia escalable
- Diseñar migración a PostgreSQL:
  - esquema compatible,
  - backfill controlado,
  - validación dual si fuera necesario.

---

## Conclusión honesta

El proyecto está **bien resuelto a nivel funcional y de trazabilidad** para su estado de madurez actual.  
La deuda principal no está en el dominio ESG, sino en los **atributos de producto corporativo** aún pendientes: autenticación, tests, modularidad frontend y escalabilidad de base de datos.  
No es un prototipo frágil, pero tampoco debe considerarse todavía una plataforma enterprise terminada.

