# GAIA: Portal GAIA - Plataforma de Datos Ambientales para el cálculo de la Huella de Carbono

Aplicación web interna para convertir facturas energéticas en PDF en datos ambientales
trazables: extracción automática de datos, cálculo de emisiones de CO₂, control de
calidad, estimación de periodos sin factura y reporting ESG.

Stack: **Python 3.13 · Flask 3.1 · SQLite · PaddleOCR + pdfplumber · SPA en Jinja + JavaScript vanilla**.

---

## Qué hace

| Área | Descripción |
|---|---|
| Carga de facturas | Individual (`POST /api/procesar`) o en lote asíncrono (`POST /api/procesar-lote`) |
| Extracción | `pdfplumber` si el PDF tiene capa de texto; `PaddleOCR` como fallback en PDFs escaneados |
| Plantillas | 16 plantillas YAML por comercializadora en `config/plantillas_facturas/` para afinar la extracción |
| Cálculo de emisiones | `tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000` |
| Factores de emisión | Versionados por país y año, con historial de cambios y fuentes citadas |
| Calidad del dato | Confianza OCR por campo; revisión manual obligatoria bajo el umbral configurado |
| Huecos y estimaciones | Detección de meses sin factura, estimación y reconciliación con la factura real |
| Recálculo | Recálculo histórico de emisiones al publicarse un factor nuevo, sin destruir el original |
| Alertas | Generación automática de alertas de cobertura, calidad y anomalías |
| Objetivos | Targets de reducción absolutos o relativos, con seguimiento |
| Reporting | Informe GHG y exportación a Excel |

**Cobertura geográfica actual**: España, Argentina, Colombia, Ecuador y México
(5 países, 19 sedes, 16 sociedades y 19 comercializadoras registradas en la base
de datos).

**Modelo jerárquico**: país → sede → suministro (CUPS) → sociedad titular. Una
sede puede tener varios CUPS, cada uno facturado a una sociedad distinta del
grupo (p. ej. Asturias tiene CUPS de *Hiberus Tecnologías de la Información SL*
y de *HIBERUS IT DEVELOPMENT SERVICES SL*). El dashboard y el informe GHG
permiten ver el desglose por sociedad dentro de cada sede.

**Alcance real**: solo el suministro de **electricidad** está plenamente operativo.
El modelo de datos contempla otros tipos de energía (`tipos_energia`, `suministros`),
pero no hay extractores ni factores en producción para gas, agua u otros.

---

## Inicio rápido (Windows)

```powershell
# 1. Instalar dependencias en un entorno virtual
.\setup_windows.bat

# 2. Arrancar
.\venv\Scripts\python.exe app.py
```

Abre `http://localhost:5000`.

Requiere **Python 3.13** (PaddleOCR soporta 3.9–3.13). **No se necesita Tesseract.**

Guía completa, incluida Linux/macOS y resolución de problemas: [`INSTALACION.md`](INSTALACION.md).

---

## Estructura del proyecto

```
app.py                      Factory Flask, registro de 13 blueprints y errorhandlers
config.py                   Umbrales, rangos de validación, catálogos y seed de factores
requirements.txt            Dependencias Python
facturas_hc.db              Base de datos SQLite (24 tablas de aplicación)

routes/                     13 blueprints, 80+ endpoints HTTP
services/                   22 servicios de negocio (OCR, extracción, emisiones,
                            estimación, alertas, dashboard, GHG, recálculo, auditoría,
                            maestros…)
database/                   connection.py + 11 módulos de migraciones idempotentes
config/plantillas_facturas/ 16 plantillas YAML por comercializadora

templates/index.html        Shell de la SPA
templates/partials/         15 fragmentos Jinja (nav, 8 pestañas, 5 modales, toast)
static/js/                  11 módulos JavaScript (core.js primero, init.js al final)
static/css/app.css          Estilos propios

uploads/                    PDFs almacenados por ejercicio / país / sede
tests/                      2 ficheros de pruebas (pytest no está instalado en el venv)
```

La interfaz se organiza en 8 pestañas: **Cargar Facturas, Historial, Factores de Emisión,
Recálculo, Estimaciones, Dashboard ESG, Alertas e Informe GHG**.

---

## Configuración

Se controla por variables de entorno y por `config.py`.

| Variable de entorno | Por defecto | Efecto |
|---|---|---|
| `FLASK_DEBUG` | `false` | Modo debug (solo desarrollo local) |
| `PORT` | `5000` | Puerto de escucha |
| `DOCUMENTO_STORAGE` | `local` | Backend de almacenamiento de PDFs. Solo `local` es funcional; `sharepoint` es un esqueleto sin implementar |

Valores relevantes de `config.py`:

- `UMBRAL_REVISION = 0.75` — confianza OCR por debajo de la cual la factura se marca para revisión.
- `CAMPOS_CRITICOS_REVISION` — campos que fuerzan revisión manual si su confianza es baja.
- `ANIO_MIN_FACTURA`, `PERIODO_DIAS_MIN/MAX`, `CONSUMO_KWH_DIA_MIN/MAX` — rangos de validación compartidos.
- `UPLOAD_FOLDER` — raíz de almacenamiento local de PDFs.
- `FACTORES_EMISION` — **solo semilla inicial**. Una vez migrada la base de datos, la
  fuente de verdad es la tabla `factores_emision`; los factores se gestionan desde la
  pestaña *Factores de Emisión* o vía `/api/factores`.

El tamaño máximo de subida es de **50 MB** (`MAX_CONTENT_LENGTH` en `app.py`).

---

## Limitaciones conocidas

- **Sin autenticación ni control de acceso.** Cualquiera con acceso de red al puerto
  puede usar todos los endpoints, salvo dos grupos que requieren variable de entorno:
  `POST /api/dev/reset-datos` exige `ALLOW_DEV_RESET=true`, y la edición de datos
  maestros desde la pestaña **Admin** (`/api/admin/…`) exige `ALLOW_ADMIN_MAESTROS=true`.
  Sin esas variables los endpoints de escritura responden `403`.
- Sin Docker ni despliegue empaquetado.
- Cobertura de pruebas mínima: 2 ficheros en `tests/`, y `pytest` no está instalado
  en el entorno virtual actual.

Detalle completo en [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md).

---

## Documentación

Consulta [`INDICE.md`](INDICE.md) para el mapa completo de documentos.
