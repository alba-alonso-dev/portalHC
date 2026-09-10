# Revisión arquitectónica — Portal de Datos Ambientales Hiberus

> **Fecha**: 2026-09-06
> **Alcance**: revisión crítica basada en evidencias del código antes de iniciar
> una nueva fase de desarrollo.
> **Comité simulado**: Arquitecto Senior · Staff Engineer · Tech Lead Python/Flask ·
> Arquitecto de Datos ESG.

---

## 1. Diagnóstico ejecutivo

El portal es un monolito Flask + SQLite + SPA vanilla **deliberadamente simple** que
ha crecido orgánicamente hasta 13 blueprints, 22 servicios y ~24 tablas. El núcleo
de cálculo ESG (factores versionados, recálculo inmutable, trazabilidad de auditoría)
está **bien diseñado y es el punto más fuerte del sistema**. Sin embargo, la capa
de presentación (routes + frontend) acumula acoplamiento y duplicación que
dificultará la siguiente fase.

**Resumen cuantitativo** (evidencias del código):

| Dimensión | Valor actual | Evidencia |
|---|---|---|
| Blueprints | 13 | `app.py` registra 13 `register_blueprint` |
| Endpoints HTTP | ~117 | Conteo de decoradores `@bp.route` en `routes/` |
| Servicios | 22 | Archivos en `services/` |
| Líneas en servicios | ~11.500 | Suma de líneas de los 22 archivos |
| Líneas en routes | ~2.500 | Suma de los 13 archivos |
| Líneas JS frontend | ~2.100 | 12 archivos en `static/js/` |
| Tablas BD | ~24 | Migraciones crean 24 tablas |
| Índices BD | ~40 | Creados en migraciones |
| Migraciones | 13 módulos | `database/migrations_*.py` |
| Líneas de migración | ~2.800 | Suma de los 13 archivos |
| Tests | 8 archivos | `tests/` (sin pytest en `requirements.txt`) |
| Dependencias | 12 paquetes | Todas con `>=`, ninguna con `==` |

**Veredicto**: el sistema es **operativamente funcional y trazable** para su
propósito actual, pero está en el límite de lo mantenible sin refactor. La deuda
técnica documentada en `DEUDA_TECNICA.md` es real y precisa; esta revisión la
complementa con evidencias concretas del código y reordena prioridades.

---

## 2. Arquitectura actual real (no idealizada)

### 2.1 Capas y flujo

```
┌─────────────────────────────────────────────────┐
│  Frontend SPA (templates/index.html)            │
│  12 JS vanilla · sin build · globals mutables   │
│  Bootstrap 5.3 + Chart.js 4.4 (CDN)             │
└───────────────────────┬─────────────────────────┘
                        │ fetch (sin API client común)
┌───────────────────────▼─────────────────────────┐
│  Routes (13 blueprints, ~117 endpoints)         │
│  Sin url_prefix · try/except → JSON             │
│  Sin auth · sin CORS · validación manual        │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│  Services (22 módulos, ~11.500 líneas)         │
│  Stateless · get_db_connection() por operación  │
│  audit_service como corte transversal           │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│  SQLite (WAL, ~24 tablas, ~40 índices)         │
│  Sin pool · check_same_thread=False             │
│  Migraciones idempotentes en cada arranque     │
└─────────────────────────────────────────────────┘
```

### 2.2 Lo que está bien encapsulado

Evidencias concretas de buen diseño:

1. **`numeros.py`** (~165 líneas) — Aritmética `Decimal` con `ROUND_HALF_UP`
   centralizada. Importado por `emisiones_service`, `estimacion_service`,
   `recalculo_service`. Garantiza reproducibilidad del cálculo para CSRD.
   *Evidencia*: `services/numeros.py` — "stored values must reproduce from stored
   operands".

2. **`factores_service.crear_nueva_version()`** — Operación multi-stamento
   (desactivar versión anterior + insertar nueva + historial) dentro de un **único**
   `with get_db_connection()` → atómica. Modelo a seguir para otros servicios.
   *Evidencia*: `services/factores_service.py` líneas ~200-270.

3. **`extractor_service.py`** (~180 líneas) — Factory/Registry por `tipo_energia`.
   Añadir un nuevo suministro = 1 clase + 1 `register()`. No toca `lote_service`.
   *Evidencia*: `services/extractor_service.py`.

4. **`documento_service.py`** — Strategy pattern con `LocalDocumentoStorage` /
   `SharePointDocumentoStorage` (placeholder). Los callers no conocen la
   implementación. *Evidencia*: `services/documento_service.py`.

5. **`audit_service.py`** (~140 líneas) — `registrar_evento()` es silencioso por
   diseño (nunca propaga excepciones). Acepta `conn` opcional para atomicidad
   transaccional. *Evidencia*: `services/audit_service.py`.

6. **`recalculo_service.py`** (~310 líneas) — Recálculo inmutable: nunca sobrescribe
   `emisiones_tco2e`, guarda en columnas separadas + `recalculos_historial`.
   Patrón de batch con conteo de errores por factura.
   *Evidencia*: `services/recalculo_service.py`.

7. **`ghg_report_service.py`** — Separación limpia entre `_recopilar_datos_informe()`
   (dict estructurado) y `_construir_excel()` (renderer openpyxl). Un futuro PDF
   renderer reutilizaría el dict sin tocar la lógica de datos.
   *Evidencia*: `services/ghg_report_service.py`.

8. **`image_preprocessing_service.py`** (~75 líneas) — Dependencia opcional de
   OpenCV con `try/except ImportError` y degradación graceful. Nunca rompe el
   pipeline. *Evidencia*: `services/image_preprocessing_service.py`.

### 2.3 Lo que sigue acoplado

1. **`routes/facturas.py`** — El peor violador de capas. 6 de 11 endpoints hacen
   SQL directo inline. `confirmar_factura` (líneas ~300-540) contiene lógica de
   negocio: recálculo de emisiones, derivación de moneda, diff campo a campo para
   auditoría, validación de límites físicos. Debería estar en un servicio.
   *Evidencia*: `routes/facturas.py`.

2. **`lote_service._procesar_una()`** (~200 líneas) — El hotspot de complejidad.
   Ejecuta extracción → validación → cálculo de emisiones → detección de
   duplicados → resolución de suministro → INSERT → reconciliación → auditoría en
   una sola función. Tiene fan-out a 7 servicios.
   *Evidencia*: `services/lote_service.py`.

3. **`extraccion_service.py`** (~1.320 líneas) — Segundo archivo más grande. Acoplado
   a `ocr_service`, `ocr_quality_service`, `plantillas_service` y `config`. El árbol
   de 8 patrones para extraer periodo es complejo pero bien documentado.
   *Evidencia*: `services/extraccion_service.py`.

4. **Frontend: globals mutables sin namespacing** — `core.js` expone 9 variables
   globales (`archivosSeleccionados`, `loteIdActual`, `pollingInterval`, etc.) que
   `facturas.js`, `historial.js` y `dashboard.js` mutan directamente. El orden de
   carga de los 12 `<script>` es load-bearing.
   *Evidencia*: `static/js/core.js`, `templates/index.html`.

5. **`dashboard_service` ↔ `objetivos_service`** — Dependencia circular resuelta con
   import lazy dentro de funciones. Señal de que el límite entre "dashboard" y
   "objetivos ESG" no está claro.
   *Evidencia*: `services/dashboard_service.py` — `from services.objetivos_service
   import ...` dentro de `dashboard_esg()`.

---

## 3. Fortalezas, cuellos de botella, deuda técnica y límites de escalabilidad

### 3.1 Fortalezas

| Fortaleza | Evidencia |
|---|---|
| **Trazabilidad ESG completa** | Cada emisión referencia `factor_version_id` → `factores_emision` → `fuentes_emision`. Recálculo inmutable en columnas separadas. `audit_log` y `facturas_historial` registran cambios. |
| **Migraciones robustas** | 3 capas de protección: `threading.Lock` + `_FileLock` (atómico) + idempotencia SQL. `use_reloader=False` evita doble ejecución. |
| **Modelo de factores versionado** | Inmutable, una versión activa por (pais, tipo, anio). `crear_nueva_version` es atómica. |
| **OCR thread-safe** | `_ocr_lock` serializa PaddleOCR. Ruta rápida (pdfplumber) sin lock. |
| **Validación de datos histórica** | `ocr_quality_service.validar_con_historico` hace 13+ checks cruzados (z-score, Levenshtein CUPS, solapamiento de periodos, fechas imposibles). |
| **Estimaciones con reconciliación** | 8 métodos, lifecycle vigente→sustituida/rechazada, métricas de error acumuladas. |

### 3.2 Cuellos de botella

| Cuello de botella | Evidencia | Impacto |
|---|---|---|
| **SQLite single-writer** | `database/connection.py` — sin `busy_timeout`, `check_same_thread=False`. Un segundo escritor recibe `OperationalError: database is locked` inmediato. | Bloqueo bajo concurrencia. Aceptable hoy (1-2 usuarios), crítico si crece. |
| **PaddleOCR serializado** | `ocr_service._ocr_lock` — toda inferencia OCR pasa por un lock global. | Procesamiento de lotes secuencial. No paralelizable sin múltiples procesos. |
| **`resultados_json` O(n²)** | `lote_service._actualizar_lote` reescribe todo el JSON del lote tras cada factura. Mitigado con `MAX_RESULTADOS_JSON=500`. | Degradación en lotes grandes. |
| **Migraciones en cada arranque** | Sin tabla `schema_migrations`. `migrations_fase6._recalcular_emisiones_facturas()` reescribe `emisiones_tco2e` de TODAS las facturas en cada boot. | Arranque lento + WAL churn innecesario. |
| **Sin connection pooling** | Cada `with get_db_connection()` abre y cierra una conexión + 2 pragmas. | Overhead bajo volumen (miles de open/close por batch). |
| **Frontend sin build** | 12 `<script>` tags, ~2.100 líneas sin minificar, 4 requests CDN adicionales. | Aceptable para intranet; no escala a más módulos. |

### 3.3 Deuda técnica (con evidencias, complementando `DEUDA_TECNICA.md`)

#### 🔴 P0 — Imprescindible ahora

**D1. Sin `busy_timeout` en SQLite**
- *Evidencia*: `database/connection.py` no establece `PRAGMA busy_timeout`.
- *Riesgo*: bajo concurrencia real (dos usuarios confirmando facturas a la vez), el
  segundo escritor recibe `database is locked` sin espera.
- *Fix*: una línea: `conn.execute("PRAGMA busy_timeout=5000")`.

**D2. Sin `.gitignore` y sin control de versiones**
- *Evidencia*: no hay `.git` ni `.gitignore` en la raíz. `facturas_hc.db` (con datos
  de facturas reales) y dos `.bak` están en el raíz sin protección.
- *Riesgo*: si se hace `git init` + `git add .`, la BD y los backups se commitean.
- *Fix*: crear `.gitignore` antes de cualquier `git init`.

**D3. `requirements.txt` sin pinning ni lock file**
- *Evidencia*: las 12 dependencias usan `>=` sin límite superior. No hay
  `requirements.lock` ni `pip-compile`.
- *Riesgo*: una instalación limpia puede traer Flask 4 o pandas 3 con breaking
  changes. Para un sistema de reporting ESG, la reproducibilidad es crítica.
- *Fix*: `pip-compile` o `pip freeze > requirements.lock`.

**D4. `facturas.py` contiene lógica de negocio fuera del service layer**
- *Evidencia*: `routes/facturas.py` — `confirmar_factura` (líneas ~300-540) hace
  recálculo de emisiones, derivación de moneda, diff de auditoría y validación de
  límites físicos inline. 6 de 11 endpoints ejecutan SQL directo.
- *Riesgo*: imposible testear la lógica de confirmación sin levantar HTTP.
- *Fix*: extraer a `services/facturas_service.py` (o `confirmacion_service.py`).

#### 🟠 P1 — Importante a corto plazo

**D5. Sin tabla `schema_migrations`**
- *Evidencia*: `database/migrations.py` orquesta 13 módulos secuencialmente sin
  versionar. Cada arranque re-ejecuta todos los módulos (idempotentes, pero con
  coste). `_recalcular_emisiones_facturas` reescribe toda la columna en cada boot.
- *Riesgo*: arranque lento, WAL churn, riesgo si una idempotencia falla.
- *Fix*: tabla `schema_migrations(modulo, fecha, version)` con guard antes de
  ejecutar.

**D6. Operaciones no atómicas multi-bloque**
- *Evidencia*: `estimacion_service.sustituir_por_real`, `gaps_service.
  _detectar_huecos_sede`, `recalculo_service._recalcular_una` abren múltiples
  `with get_db_connection()` separados. Un fallo a mitad deja estado parcial.
- *Modelo correcto*: `factores_service.crear_nueva_version` usa un único bloque.
- *Fix*: consolidar operaciones relacionadas en un solo contexto de conexión.

**D7. Mensajes de excepción filtrados al cliente**
- *Evidencia*: ~20 endpoints devuelven `jsonify({'error': str(exc)})`, exponiendo
  detalles internos de SQLite (nombres de tablas, columnas, constraints).
- *Riesgo*: fuga de información del esquema. No crítico en intranet, pero sí si
  se expone.
- *Fix*: mapear a mensajes genéricos en producción; loguear el detalle.

**D8. Sin validación de input estructurada**
- *Evidencia*: no hay Marshmallow/Pydantic. `int(request.args.get('limit', 200))`
  puede lanzar 500 si `limit=abc`. Solo `confirmar_factura` tiene validación
  completa manual.
- *Fix*: añadir Pydantic o al menos validadores reutilizables en routes.

**D9. Duplicación masiva en `alertas_service` y `maestros_service`**
- *Evidencia*: `alertas_service.py` (~1.300 líneas) tiene 12 funciones
  `_alertas_*` con la misma estructura: abrir conexión, fetch, loop,
  `_existe_alerta_pendiente` + `_insertar_alerta`. `maestros_service.py` (~1.050
  líneas) repite listar/crear/actualizar/estado/borrar por 6 entidades.
- *Riesgo*: cambios repetidos en N sitios; dificultad de testeo.
- *Fix*: base class o decorador para detectores de alerta; CRUD genérico para
  maestros. Reduciría ~40-50% el código.

**D10. `dashboard_service` repite el filtro de fecha ~20 veces**
- *Evidencia*: `strftime('%Y', COALESCE(periodo_inicio, fecha_carga))` + `extra_cond`
  se repite en cada KPI. `ghg_report_service._filtros_base()` ya tiene el patrón
  correcto.
- *Fix*: extraer helper `_filtro_anio_facturas(anio, pais, sede, alias)`.

#### 🟡 P2 — Mejora progresiva

**D11. `facturas` con columnas duales texto+FK**
- *Evidencia*: `facturas.sede` (texto) + `facturas.suministro_id → suministros →
  sedes`. Igual con `sociedad` (texto) + `suministros.sociedad_id → sociedades`.
  Las consultas de dashboard/ghg hacen `COALESCE(soc.nombre, NULLIF(TRIM(f.sociedad),
  ''), 'Sin identificar')` para cubrir ambos caminos.
- *Riesgo*: drift entre texto y FK; complejidad en cada query.
- *Fix*: migración que backfillee 100% los FKs y depreque los text columns.

**D12. FKs no declaradas en varias tablas**
- *Evidencia*: `recalculos_historial.factura_id`, `estimaciones.factura_real_id`,
  `periodos_faltantes.factura_id`, `alertas.entidad_id` no tienen `REFERENCES`.
- *Riesgo*: huérfanos no detectados por `foreign_key_check`.
- *Fix*: `ALTER TABLE ... ADD COLUMN ... REFERENCES ...` (SQLite soporta en
  columnas nuevas; para existentes requiere recreación de tabla).

**D13. Frontend: globals sin namespacing ni módulos**
- *Evidencia*: `core.js` expone 9 globales. 11 de 12 JS hacen `fetch` directo sin
  API client común. `alertas.js` tiene `catch(e){}` vacío.
- *Riesgo*: regresiones al reordenar scripts; errores silenciados.
- *Fix*: envolver cada módulo en IIFE o migrar a ES modules (`type="module"`).

**D14. `ocr_quality_service.validar_con_historico` (~300 líneas)**
- *Evidencia*: función procedural con 13 checks secuenciales.
- *Fix*: registry de funciones de check, como `ExtractorFactory`.

**D15. Sin tests formalizados**
- *Evidencia*: `tests/` tiene 8 archivos pero `pytest` no está en
  `requirements.txt`. No hay CI ni cobertura medida.
- *Fix*: `pip install pytest pytest-cov`; smoke test de los endpoints críticos.

### 3.4 Límites de escalabilidad

| Recurso | Límite actual | Punto de rotura |
|---|---|---|
| **Concurrencia de escritura** | 1 escritor activo (SQLite WAL) | 2+ usuarios confirmando facturas simultáneamente |
| **Volumen de facturas** | ~136 facturas hoy | Miles → migraciones de arranque lentas; `_recalcular_emisiones_facturas` O(n) en cada boot |
| **Tamaño de lote** | `MAX_RESULTADOS_JSON=500` | Lotes > 500 facturas → truncación de resultados |
| **Procesamiento OCR** | 1 PDF a la vez (lock global) | Lotes con muchos PDFs escaneados → cola secuencial |
| **Frontend** | 12 scripts, ~2.100 líneas | Añadir 2-3 módulos más → inmanejable sin build |
| **Memoria PaddleOCR** | ~500 MB residentes | 1 instancia por proceso; no escala horizontalmente sin refactor |

---

## 4. Riesgos técnicos

| # | Riesgo | Probabilidad | Impacto | Evidencia |
|---|---|---|---|---|
| R1 | `database is locked` bajo concurrencia | Alta si crece usuarios | Alto | Sin `busy_timeout` en `connection.py` |
| R2 | BD commiteada a git con datos sensibles | Alta si se hace `git init` sin `.gitignore` | Alto | Sin `.gitignore`, `.bak` en raíz |
| R3 | Instalación no reproducible | Media | Alto | `requirements.txt` sin pinning |
| R4 | Estado parcial en operaciones multi-bloque | Media | Medio | `sustituir_por_real`, `_detectar_huecos_sede` |
| R5 | Lógica de negocio en routes no testeable | Alta (ya ocurre) | Medio | `facturas.py:confirmar_factura` |
| R6 | Drift entre texto y FK en `facturas` | Media | Medio | `facturas.sede` vs `suministro_id → sedes` |
| R7 | Migración fallida deja lock huérfano | Baja | Medio | `_FileLock` con timeout 30s + idempotencia |
| R8 | Excepción de SQLite expuesta al cliente | Alta (ya ocurre) | Bajo | `str(exc)` en ~20 endpoints |
| R9 | Frontend se rompe al reordenar scripts | Media | Bajo | Globals sin IIFE/modules |
| R10 | Ausencia de auth permite borrado de datos | Alta si se expone | Crítico | Solo env-var gating, `usuario` spoofable |

---

## 5. Decisiones de arquitectura que conviene mantener

| Decisión | Por qué mantenerla | Evidencia |
|---|---|---|
| **Migraciones aditivas e idempotentes** | Preserva histórico, minimiza riesgo sobre BD en uso, compatible con auditoría ESG. | 13 módulos sin un solo `DROP TABLE` productivo. |
| **Factores versionados e inmutables** | CSRD requiere trazabilidad de qué factor se usó en cada cálculo. Recálculo no destruye original. | `factores_emision` con `es_version_activa`, `facturas_historial`. |
| **`numeros.py` con `Decimal`** | Evita drift de coma flotante en cálculos de emisiones. Reproducible desde operandos almacenados. | `ROUND_HALF_UP`, precisiones por magnitud. |
| **`ExtractorFactory` por `tipo_energia`** | Añadir gas/agua/residuos sin tocar `lote_service`. | Registry pattern, 1 clase + 1 `register()`. |
| **`documento_service` Strategy** | Migrar a SharePoint sin tocar callers. | `LocalDocumentoStorage` / `SharePointDocumentoStorage`. |
| **`audit_service` silencioso** | Un fallo de auditoría no debe romper el flujo de negocio. | `try/except` que loguea pero no raise. |
| **SHA256 como índice normal (no UNIQUE)** | El negocio necesita detectar duplicados, no bloquearlos. | `idx_facturas_sha256` degradado en Fase 6. |
| **OCR con lock serializado** | PaddleOCR no es thread-safe. El lock es la única protección. | `_ocr_lock` en `ocr_service.py`. |
| **`ghg_report_service` data/render split** | Permite añadir PDF sin tocar la lógica de datos. | `_recopilar_datos_informe()` ↔ `_construir_excel()`. |

---

## 6. Roadmap técnico priorizado

### Fase 0 — Estabilización (antes de cualquier nueva funcionalidad)

| # | Tarea | Esfuerzo | Riesgo | Tipo |
|---|---|---|---|---|
| 0.1 | **Añadir `.gitignore`** (`facturas_hc.db`, `*.bak`, `uploads/`, `venv/`, `__pycache__/`) | 10 min | Nulo | Imprescindible ahora |
| 0.2 | **Añadir `PRAGMA busy_timeout=5000`** en `connection.py` | 5 min | Nulo | Imprescindible ahora |
| 0.3 | **Pin versions** en `requirements.txt` con `pip freeze > requirements.lock` | 30 min | Bajo | Imprescindible ahora |
| 0.4 | **Tabla `schema_migrations`** para no re-ejecutar migraciones | 2h | Bajo | Imprescindible ahora |
| 0.5 | **Instalar pytest + smoke tests** de los 5 endpoints críticos | 4h | Bajo | Imprescindible ahora |

### Fase 1 — Refactor de bajo riesgo

| # | Tarea | Esfuerzo | Riesgo | Tipo |
|---|---|---|---|---|
| 1.1 | **Extraer `facturas_service.py`** de `routes/facturas.py` | 1 día | Medio | Importante después |
| 1.2 | **Helper `_filtro_anio_facturas()`** en `dashboard_service` | 2h | Bajo | Importante después |
| 1.3 | **Base class para detectores de alerta** en `alertas_service` | 1 día | Medio | Importante después |
| 1.4 | **CRUD genérico** para maestros en `maestros_service` | 1 día | Medio | Importante después |
| 1.5 | **Mensajes de error genéricos** en producción (no `str(exc)`) | 2h | Bajo | Importante después |
| 1.6 | **`url_prefix` en blueprints** | 1h | Bajo | Importante después |
| 1.7 | **API client JS común** (wrapper de fetch con error handling) | 2h | Bajo | Opcional |

### Fase 2 — Escalabilidad

| # | Tarea | Esfuerzo | Riesgo | Tipo |
|---|---|---|---|---|
| 2.1 | **Migración a PostgreSQL** | 1 semana | Alto | Cuando la concurrencia lo exija |
| 2.2 | **Connection pooling** (si PostgreSQL) | Incluido en 2.1 | — | — |
| 2.3 | **Cola de procesamiento OCR** (Redis + worker) | 1 semana | Medio | Cuando el volumen de lotes crezca |
| 2.4 | **Frontend build step** (Vite + ES modules) | 2 días | Medio | Cuando se añadan más módulos |

### Fase 3 — Producto

| # | Tarea | Esfuerzo | Riesgo | Tipo |
|---|---|---|---|---|
| 3.1 | **Autenticación Azure AD** | 3 días | Medio | Imprescindible antes de exponer |
| 3.2 | **SharePoint storage** | 2 días | Bajo | Cuando el cliente lo pida |
| 3.3 | **Backfill completo de FKs** en `facturas` (deprecar texto) | 1 día | Medio | Importante después |
| 3.4 | **Nuevos suministros** (gas, agua) | 1 semana por tipo | Medio | Por demanda de negocio |

---

## 7. Refactors concretos de bajo riesgo

### 7.1 `busy_timeout` (D1)

```python
# database/connection.py — añadir una línea
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.execute("PRAGMA busy_timeout=5000")  # ← NUEVO: esperar 5s antes de error
```

### 7.2 Helper de filtro de año (D10)

Extraer de `ghg_report_service._filtros_base()` y reutilizar en `dashboard_service`:

```python
# services/_queries.py (nuevo módulo compartido)
def filtro_anio_facturas(anio, pais=None, sede=None, alias='f'):
    cond = [f"{alias}.fecha_anulacion IS NULL",
            f"strftime('%Y', COALESCE({alias}.periodo_inicio, {alias}.fecha_carga)) = ?"]
    params = [anio]
    if pais: cond.append(f"{alias}.pais = ?"); params.append(pais.upper())
    if sede: cond.append(f"{alias}.sede = ?"); params.append(sede)
    return " AND ".join(cond), params
```

### 7.3 API client JS común (D13 parcial)

```javascript
// static/js/api.js (nuevo)
async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function apiPost(url, body) {
  const r = await fetch(url, { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
```

### 7.4 Tabla `schema_migrations` (D5)

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  modulo TEXT PRIMARY KEY,
  fecha_ejecucion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Cada `ejecutar_migraciones_X()` comprueba si su módulo ya está registrado antes de
ejecutar el cuerpo.

---

## 8. Clasificación final de recomendaciones

### Imprescindible ahora (P0)
1. `.gitignore` antes de cualquier control de versiones — [D2]
2. `PRAGMA busy_timeout=5000` en `connection.py` — [D1]
3. Pin versions en `requirements.txt` — [D3]
4. Tabla `schema_migrations` para evitar re-ejecución — [D5]
5. Instalar pytest + smoke tests de endpoints críticos — [D15]

### Importante después (P1)
6. Extraer `facturas_service.py` de `routes/facturas.py` — [D4]
7. Helper de filtro de año compartido — [D10]
8. Base class para detectores de alerta — [D9]
9. CRUD genérico para maestros — [D9]
10. Mensajes de error genéricos en producción — [D7]
11. `url_prefix` en blueprints — [D8 adyacente]
12. Operaciones atómicas (un solo `with` por transacción) — [D6]

### Opcional (P2)
13. API client JS común + IIFE por módulo — [D13]
14. Registry de checks en `ocr_quality_service` — [D14]
15. Backfill completo de FKs y deprecación de texto en `facturas` — [D11]
16. Frontend build step (Vite) — cuando crezca — [D13]
17. Migración a PostgreSQL — cuando la concurrencia lo exija — [D4 de `DEUDA_TECNICA.md`]
18. Azure AD — antes de exponer externamente — [D1 de `DEUDA_TECNICA.md`]

---

## 9. Conclusión

El portal tiene un **núcleo ESG sólido y trazable** que cumple su propósito. La
deuda técnica documentada en `DEUDA_TECNICA.md` es precisa. Esta revisión añade
evidencias concretas del código y recomienda **estabilizar antes de expandir**:
`.gitignore`, `busy_timeout`, pinning de dependencias, `schema_migrations` y tests
básicos son de bajo coste y alto retorno. El refactor de `facturas.py` y la
consolidación de `alertas_service`/`maestros_service` son los siguientes pasos
naturales para reducir complejidad antes de añadir nuevos suministros o exponer
el sistema externamente.
