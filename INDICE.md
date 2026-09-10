# Índice de documentación

Mapa de los 15 documentos del Portal de Datos Ambientales Hiberus.

---

## Por dónde empezar

| Perfil | Ruta de lectura |
|---|---|
| **Alguien nuevo en el proyecto** | `README.md` → `HANDOVER.md` → `ARQUITECTURA.md` |
| **Instalar y arrancar** | `INSTALACION_RAPIDA.md` → `INSTALACION.md` |
| **Desarrollar sobre el código** | `ARQUITECTURA.md` → `MODELO_DATOS.md` → `API_REFERENCE.md` → `REFERENCIA_RAPIDA.md` |
| **Integrar contra la API** | `API_REFERENCE.md` |
| **Dirección / sostenibilidad** | `RESUMEN_EJECUTIVO.md` → `FUNCIONALIDADES.md` → `ROADMAP.md` |
| **Planificar el trabajo pendiente** | `DEUDA_TECNICA.md` → `ROADMAP.md` |

---

## Documentos

### Producto y contexto

| Documento | Contenido |
|---|---|
| `README.md` | Visión general, estructura del proyecto, configuración y limitaciones conocidas |
| `RESUMEN_EJECUTIVO.md` | Objetivo de negocio, problema que resuelve y valor aportado |
| `FUNCIONALIDADES.md` | Catálogo de funcionalidades operativas, módulo a módulo |
| `HANDOVER.md` | Traspaso: qué es, quién lo usa, alcance real y puntos de atención |

### Técnicos

| Documento | Contenido |
|---|---|
| `ARQUITECTURA.md` | Capas, frontend, blueprints, servicios, persistencia y almacenamiento documental |
| `MODELO_DATOS.md` | Esquema completo de SQLite: tablas, columnas, índices y triggers |
| `API_REFERENCE.md` | Los 80 endpoints HTTP, con parámetros y formatos de respuesta |
| `REFERENCIA_RAPIDA.md` | Chuleta: comandos, mapa del código, familias de endpoints, umbrales |

### Operación

| Documento | Contenido |
|---|---|
| `INSTALACION.md` | Guía completa: requisitos, Windows y Linux/macOS, configuración, resolución de problemas, pruebas |
| `INSTALACION_RAPIDA.md` | Puesta en marcha abreviada en Windows |

### Planificación

| Documento | Contenido |
|---|---|
| `FASES_PROYECTO.md` | Historia del proyecto por fases y entregables de cada una |
| `ROADMAP.md` | Trabajo priorizado con valor, complejidad, dependencias y esfuerzo |
| `DEUDA_TECNICA.md` | Qué está bien resuelto, qué es deuda y riesgos asumidos |
| `PROMPTS_DESARROLLO.md` | Plantillas de prompt para asistir el desarrollo con LLM |

### Otros ficheros

- `INDICE.md` — este documento.
- `Planning.html` — planificación en formato HTML, fuera del conjunto Markdown.

---

## Búsqueda rápida

| Busco… | Documento |
|---|---|
| Instalar el portal | `INSTALACION_RAPIDA.md` |
| Un error al instalar o arrancar | `INSTALACION.md` §7 |
| Cambiar el puerto o activar debug | `INSTALACION.md` §4 |
| Actualizar un factor de emisión | `INSTALACION.md` §6 |
| Añadir una plantilla de comercializadora | `INSTALACION.md` §6 |
| Qué endpoints existen | `API_REFERENCE.md` |
| Qué columnas tiene una tabla | `MODELO_DATOS.md` |
| Cómo se calculan las emisiones | `REFERENCIA_RAPIDA.md` |
| Cómo encaja un servicio con otro | `ARQUITECTURA.md` |
| Qué falta por hacer | `ROADMAP.md` |
| Qué riesgos técnicos hay | `DEUDA_TECNICA.md` |
| Ejecutar las pruebas | `INSTALACION.md` §8 |

---

## Estado del proyecto

- **Stack**: Python 3.13 · Flask 3.1 · SQLite · PaddleOCR + pdfplumber · SPA Jinja + JS vanilla.
- **Alcance operativo**: electricidad, en 5 países (ES, AR, CO, EC, MX), 19 sedes.
- **Superficie**: 12 blueprints · 80 endpoints · 20 servicios · 23 tablas · 16 plantillas
  de comercializadora · 11 módulos JS.
- **Limitaciones**: sin autenticación, sin Docker, cobertura de pruebas mínima.
