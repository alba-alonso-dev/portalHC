# Referencia rápida

Chuleta operativa del Portal de Datos Ambientales Hiberus.
Detalle de endpoints en [`API_REFERENCE.md`](API_REFERENCE.md) y del esquema en
[`MODELO_DATOS.md`](MODELO_DATOS.md).

---

## Comandos

```powershell
# Instalar (Windows)
.\setup_windows.bat

# Arrancar
.\venv\Scripts\python.exe app.py

# Arrancar en otro puerto / con debug
$env:PORT = "8080"; $env:FLASK_DEBUG = "true"; .\venv\Scripts\python.exe app.py

# Inspeccionar la base de datos
.\venv\Scripts\python.exe -c "import sqlite3;print(sqlite3.connect('facturas_hc.db').execute('select count(*) from facturas').fetchone())"

# Pruebas (pytest no viene instalado)
.\venv\Scripts\python.exe -m pip install pytest
.\venv\Scripts\python.exe -m pytest tests\
```

URL: <http://localhost:5000> · Base de datos: `facturas_hc.db` · PDFs: `uploads/`

---

## Mapa del código

| Ruta | Contenido |
|---|---|
| `app.py` | Factory Flask, 13 blueprints, errorhandlers 413/404/500, límite de 50 MB |
| `config.py` | Umbrales, rangos de validación, catálogos y semilla de factores |
| `routes/` | 13 blueprints, 80+ endpoints |
| `services/` | 22 servicios de negocio |
| `database/` | `connection.py` + 11 módulos de migraciones idempotentes |
| `config/plantillas_facturas/` | 16 plantillas YAML por comercializadora |
| `templates/index.html` | Shell de la SPA (incluye partials Jinja) |
| `static/js/` | 12 módulos JS — `core.js` primero, `init.js` al final |
| `uploads/` | PDFs por ejercicio / país / sede |

### Servicios principales

`ocr_service` (pdfplumber + PaddleOCR) · `extraccion_service` · `extractor_service` ·
`plantillas_service` · `ocr_quality_service` · `validacion_service` ·
`emisiones_service` · `factores_service` · `recalculo_service` · `lote_service` ·
`gaps_service` · `estimacion_service` · `alertas_service` · `dashboard_service` ·
`ghg_report_service` · `objetivos_service` · `documento_service` · `audit_service` ·
`image_preprocessing_service` · `maestros_service`

---

## Pestañas de la interfaz

Cargar Facturas · Historial · Factores de Emisión · Recálculo · Estimaciones ·
Dashboard ESG · Alertas · Informe GHG · Admin

---

## Endpoints por familia

| Prefijo | Blueprint | Qué cubre |
|---|---|---|
| `/api/procesar`, `/api/procesar-lote`, `/api/lote/…`, `/api/factura/…`, `/api/historial` | `facturas` | Carga, lotes, detalle, PDF, confirmación, borrado, historial de cambios |
| `/api/factores/…` | `factores_admin` | Alta, versionado, metadatos, estado, historial de factores |
| `/api/fuentes/…` | `fuentes` | Fuentes de factores de emisión |
| `/api/recalculo/…` | `recalculo` | Impacto, ejecución, lotes e historial de recálculo |
| `/api/estimaciones/…`, `/api/calidad/…` | `estimaciones` | Huecos, estimaciones, sustitución, métricas de error |
| `/api/dashboard/…` | `dashboard` | Resumen, emisiones, cobertura, calidad, evolución, ESG, proyección |
| `/api/estadisticas/…` | `estadisticas` | Emisiones y comparativas por sede, sociedad y drill-down sede→sociedad. `/api/estadisticas/emisiones/sedes-sociedades` devuelve el desglose por sede con sus sociedades |
| `/api/alertas/…` | `alertas` | Generación, listados, resumen, resolver, ignorar |
| `/api/ghg/…` | `ghg_report` | Informe GHG (Excel), preview JSON, ranking por sociedad. El Excel incluye hoja "8. Desglose Sede-Sociedad" con el reparto por sede |
| `/api/objetivos/…` | `objetivos` | CRUD de objetivos, seguimiento, resumen ESG |
| `/api/paises`, `/api/sedes/<pais>`, `/api/comercializadoras/<pais>`, `/api/documentos/…`, `/api/dev/reset-datos` | `configuracion` | Catálogos, índice y cobertura documental, reset de desarrollo |
| `/api/admin/…` | `admin_maestros` | CRUD de datos maestros (países, sedes, sociedades, comercializadoras, tipos energía, suministros). Escritura requiere `ALLOW_ADMIN_MAESTROS=true` |
| `/api/descargar-excel` | `exportacion` | Exportación a Excel |

Respuesta habitual: `{"exito": true, ...}` / `{"exito": false, "error": "..."}`.
Devuelven binario o HTML: `GET /`, `/api/factura/<id>/pdf`, `/api/descargar-excel`,
`/api/ghg/informe`.

---

## Base de datos

SQLite, **24 tablas de aplicación**, 38 índices y 4 triggers de `updated_at` /
`modificado_en`.

| Grupo | Tablas |
|---|---|
| Maestros | `paises`, `sedes`, `sociedades`, `suministros`, `tipos_energia`, `comercializadoras`, `fuentes_emision` |
| Núcleo | `facturas`, `lotes`, `documentos_indice` |
| Factores | `factores_emision`, `factores_historial` |
| Recálculo | `lotes_recalculo`, `recalculos_historial` |
| Estimación | `estimaciones`, `periodos_faltantes`, `metodo_estimacion_metricas` |
| ESG | `objetivos_emision`, `alertas`, `alertas_config` |
| Trazabilidad | `audit_log`, `facturas_historial` |
| Integración | `fuentes_documentos`, `sync_log` |

`facturas` es la tabla central. Conserva el cálculo original
(`emisiones_tco2e`, `factor_emision`, `factor_version_id`) y el recalculado
(`emisiones_recalculadas`, `factor_recalculado`, `factor_version_id_recalc`) en
columnas separadas, de modo que un recálculo nunca destruye el histórico.

---

## Cálculo de emisiones

```
tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000
```

El factor se toma de `factores_emision` según país, tipo de energía y año, usando la
versión activa. Nunca desde `config.FACTORES_EMISION`, que es solo semilla inicial.

Países: **ES, AR, CO, EC, MX** — 19 sedes y 19 comercializadoras en base de datos.

---

## Calidad del dato

| Parámetro | Valor | Dónde |
|---|---|---|
| Umbral de revisión manual | `0.75` | `config.UMBRAL_REVISION` |
| Campos que fuerzan revisión | consumo, periodo, cups, sociedad, comercializadora | `config.CAMPOS_CRITICOS_REVISION` |
| Descarte de tokens OCR | score `< 0.55` | `services/ocr_service._OCR_DROP_SCORE` |
| Confianza de texto digital | `0.95` | `services/ocr_service` |
| Año mínimo de factura | `2015` | `config.ANIO_MIN_FACTURA` |
| Período de facturación | 15–95 días | `config.PERIODO_DIAS_MIN/MAX` |
| Consumo diario plausible | 0,05–10 000 kWh/día | `config.CONSUMO_KWH_DIA_MIN/MAX` |

---

## Avisos operativos

- **No hay autenticación.** Todos los endpoints son públicos para quien alcance el
  puerto. Excepciones que además requieren variable de entorno activa:
  `POST /api/dev/reset-datos` exige `ALLOW_DEV_RESET=true`, y las operaciones de
  escritura de datos maestros (`/api/admin/…` POST/PUT/PATCH/DELETE) exigen
  `ALLOW_ADMIN_MAESTROS=true`. Sin esas variables responden `403`.
- La aplicación escucha en `0.0.0.0`. No la expongas fuera de una red de confianza.
- PaddleOCR no es thread-safe; `ocr_service` serializa las inferencias con un lock.
  Los PDFs con capa de texto no pasan por ahí y no se ven afectados.
- Solo **electricidad** está operativa como suministro.
