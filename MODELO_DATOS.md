# Modelo de datos — Portal de Datos Ambientales de Hiberus

## Alcance y nota de precisión

Este documento se ha elaborado contra el **schema real de `facturas_hc.db`** y las migraciones del proyecto.

### Observación importante sobre el conteo

El enunciado habla de **25 tablas**, pero el inventario facilitado enumera **24 objetos** y el schema actual expone exactamente:

- **23 tablas de aplicación**, más
- **1 tabla interna de SQLite** (`sqlite_sequence`).

Para mantener precisión técnica, a continuación se documentan **todos los objetos presentes en el schema actual** sin inventar una tabla adicional inexistente.

### Columnas numéricas y precisión

Las 35 columnas numéricas del schema son de tipo `REAL` (coma flotante de doble
precisión). Para que eso no afecte a las cifras de reporting, la aritmética del
dominio **no se hace en float**: `services/numeros.py` centraliza el cálculo en
`Decimal` con redondeo `ROUND_HALF_UP` y una precisión fija por magnitud
(importes 2 decimales, kWh 2, MWh 6, tCO₂e 4).

- `consumo_mwh` se guarda con 6 decimales, de forma que la conversión desde
  `consumo_kwh` sea exacta.
- `emisiones_tco2e` es el resultado de `consumo_mwh × factor_emision ÷ 1000`
  resuelto en un solo paso decimal, por lo que se puede reproducir exactamente a
  partir de los dos valores almacenados.

Limitación conocida: las agregaciones hechas con `SUM()` y `AVG()` **dentro de
SQLite** siguen siendo de coma flotante. Su desviación es despreciable para los
volúmenes previstos, y el redondeo final de presentación sí pasa por `Decimal`.

## Resumen del modelo

### Tablas maestras

- `paises`
- `sedes`
- `sociedades`
- `tipos_energia`
- `comercializadoras`
- `suministros`
- `fuentes_emision`
- `fuentes_documentos`

### Tablas transaccionales y analíticas

- `facturas`
- `lotes`
- `estimaciones`
- `periodos_faltantes`
- `alertas`
- `alertas_config`
- `lotes_recalculo`
- `recalculos_historial`
- `documentos_indice`
- `sync_log`
- `objetivos_emision`
- `metodo_estimacion_metricas`

### Tablas de gobierno y trazabilidad

- `audit_log`
- `facturas_historial`
- `factores_emision`
- `factores_historial`

---

## facturas

**Función**: Tabla transaccional principal. Almacena cada factura procesada, su cálculo de emisiones, su trazabilidad documental y su estado operativo.

**Notas funcionales**:
- Distingue dato real/estimado mediante `tipo_dato`.
- Conserva referencias a factor original y a recálculo posterior.
- Incluye metadatos de documento (`sha256_documento`, `fuente_documento_id`, `external_*`).
- El bug de Fase 6 convirtió `idx_facturas_sha256` en índice no único para permitir duplicados potenciales.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais` | `TEXT` | 1 | `None` | 0 | - |
| `sede` | `TEXT` | 1 | `None` | 0 | - |
| `archivo_nombre` | `TEXT` | 1 | `None` | 0 | - |
| `archivo_ruta` | `TEXT` | 1 | `None` | 0 | - |
| `consumo_kwh` | `REAL` | 0 | `None` | 0 | - |
| `consumo_mwh` | `REAL` | 0 | `None` | 0 | - |
| `comercializadora` | `TEXT` | 0 | `None` | 0 | - |
| `factor_emision` | `REAL` | 0 | `None` | 0 | - |
| `emisiones_tco2e` | `REAL` | 0 | `None` | 0 | - |
| `estado` | `TEXT` | 0 | `'procesada'` | 0 | Campo de workflow |
| `fecha_carga` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `datos_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |
| `notas` | `TEXT` | 0 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 0 | `'electricidad'` | 0 | - |
| `fecha_factura` | `TEXT` | 0 | `None` | 0 | Marca temporal |
| `periodo_inicio` | `TEXT` | 0 | `None` | 0 | - |
| `periodo_fin` | `TEXT` | 0 | `None` | 0 | - |
| `dias_facturados` | `INTEGER` | 0 | `None` | 0 | - |
| `sociedad` | `TEXT` | 0 | `None` | 0 | - |
| `direccion_suministro` | `TEXT` | 0 | `None` | 0 | - |
| `cups` | `TEXT` | 0 | `None` | 0 | - |
| `confianza_ocr` | `REAL` | 0 | `None` | 0 | - |
| `campos_confianza` | `TEXT` | 0 | `None` | 0 | - |
| `lote_id` | `TEXT` | 0 | `None` | 0 | - |
| `factor_version_id` | `INTEGER` | 0 | `None` | 0 | FK -> factores_emision.id |
| `tipo_dato` | `TEXT` | 0 | `'real'` | 0 | - |
| `emisiones_recalculadas` | `REAL` | 0 | `None` | 0 | - |
| `factor_recalculado` | `REAL` | 0 | `None` | 0 | - |
| `factor_version_id_recalc` | `INTEGER` | 0 | `None` | 0 | - |
| `fecha_ultimo_recalculo` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `external_source` | `TEXT` | 0 | `'local'` | 0 | - |
| `external_doc_id` | `TEXT` | 0 | `None` | 0 | - |
| `external_doc_url` | `TEXT` | 0 | `None` | 0 | - |
| `fecha_anulacion` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `sha256_documento` | `TEXT` | 0 | `None` | 0 | - |
| `suministro_id` | `INTEGER` | 0 | `None` | 0 | FK -> suministros.id |
| `duplicado_potencial` | `INTEGER` | 0 | `0` | 0 | - |
| `updated_at` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `consumo_valor` | `REAL` | 0 | `None` | 0 | - |
| `consumo_unidad` | `TEXT` | 0 | `'kWh'` | 0 | - |
| `fuente_documento_id` | `INTEGER` | 0 | `None` | 0 | FK -> fuentes_documentos.id |
| `export_state` | `TEXT` | 0 | `None` | 0 | - |
| `ejercicio` | `TEXT` | 0 | `None` | 0 | - |
| `carpeta_relativa` | `TEXT` | 0 | `None` | 0 | - |
| `inconsistencias_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `fuente_documento_id` | `fuentes_documentos` | `id` | `NO ACTION` | `NO ACTION` |
| `suministro_id` | `suministros` | `id` | `NO ACTION` | `NO ACTION` |
| `factor_version_id` | `factores_emision` | `id` | `NO ACTION` | `NO ACTION` |

### Relaciones lógicas (sin FK declarada)
- `lote_id` referencia funcionalmente a `lotes.id` (sin FK física).

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_facturas_sha256` | INDEX / PARTIAL / CREADO EXPLÍCITAMENTE | `sha256_documento` | `CREATE INDEX idx_facturas_sha256 ON facturas(sha256_documento) WHERE sha256_documento IS NOT NULL` |
| `idx_facturas_cups` | INDEX / CREADO EXPLÍCITAMENTE | `cups` | `CREATE INDEX idx_facturas_cups ON facturas(cups)` |
| `idx_facturas_ejercicio` | INDEX / CREADO EXPLÍCITAMENTE | `ejercicio` | `CREATE INDEX idx_facturas_ejercicio ON facturas(ejercicio)` |
| `idx_facturas_fuente_doc` | INDEX / CREADO EXPLÍCITAMENTE | `fuente_documento_id` | `CREATE INDEX idx_facturas_fuente_doc ON facturas(fuente_documento_id)` |
| `idx_facturas_export_state` | INDEX / PARTIAL / CREADO EXPLÍCITAMENTE | `export_state` | `CREATE INDEX idx_facturas_export_state ON facturas(export_state) WHERE export_state IS NOT NULL` |
| `idx_facturas_updated_at` | INDEX / CREADO EXPLÍCITAMENTE | `updated_at` | `CREATE INDEX idx_facturas_updated_at ON facturas(updated_at)` |
| `idx_facturas_suministro` | INDEX / CREADO EXPLÍCITAMENTE | `suministro_id`, `periodo_inicio` | `CREATE INDEX idx_facturas_suministro ON facturas(suministro_id, periodo_inicio)` |
| `idx_facturas_external_doc` | UNIQUE / PARTIAL / CREADO EXPLÍCITAMENTE | `external_doc_id` | `CREATE UNIQUE INDEX idx_facturas_external_doc ON facturas(external_doc_id) WHERE external_doc_id IS NOT NULL` |
| `idx_facturas_tipo_dato` | INDEX / CREADO EXPLÍCITAMENTE | `tipo_dato` | `CREATE INDEX idx_facturas_tipo_dato ON facturas(tipo_dato)` |
| `idx_facturas_estado` | INDEX / CREADO EXPLÍCITAMENTE | `estado` | `CREATE INDEX idx_facturas_estado ON facturas(estado)` |
| `idx_facturas_sede_periodo` | INDEX / CREADO EXPLÍCITAMENTE | `sede`, `periodo_inicio` | `CREATE INDEX idx_facturas_sede_periodo ON facturas(sede, periodo_inicio)` |
| `idx_facturas_periodo` | INDEX / CREADO EXPLÍCITAMENTE | `periodo_inicio` | `CREATE INDEX idx_facturas_periodo ON facturas(periodo_inicio)` |
| `idx_facturas_pais_tipo` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `tipo_energia` | `CREATE INDEX idx_facturas_pais_tipo ON facturas(pais, tipo_energia)` |

## lotes

**Función**: Estado persistido de cargas masivas de PDFs.

**Notas funcionales**:
- Permite polling desde frontend y mantiene resultados parciales/finales del batch.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `TEXT` | 0 | `None` | 1 | Clave primaria |
| `fecha_inicio` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `fecha_fin` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `total_archivos` | `INTEGER` | 1 | `None` | 0 | - |
| `procesados_ok` | `INTEGER` | 0 | `0` | 0 | - |
| `procesados_error` | `INTEGER` | 0 | `0` | 0 | - |
| `estado` | `TEXT` | 0 | `'procesando'` | 0 | Campo de workflow |
| `resultados_json` | `TEXT` | 0 | `'[]'` | 0 | Contenido JSON serializado |
| `usuario` | `TEXT` | 0 | `None` | 0 | - |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_lotes_1` | UNIQUE / PK/AUTO | `id` | `autoindex interno de SQLite` |

## factores_emision

**Función**: Catálogo versionado de factores de emisión por país, tipo de energía y año.

**Notas funcionales**:
- Una combinación puede tener varias versiones, pero solo una `es_version_activa=1`.
- La columna numérica está en kg CO₂eq/MWh.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais` | `TEXT` | 1 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 1 | `'electricidad'` | 0 | - |
| `anio` | `TEXT` | 1 | `None` | 0 | - |
| `version` | `INTEGER` | 1 | `1` | 0 | - |
| `factor_kg_co2_mwh` | `REAL` | 1 | `None` | 0 | - |
| `unidad` | `TEXT` | 1 | `'kg CO2eq/MWh'` | 0 | - |
| `descripcion` | `TEXT` | 0 | `None` | 0 | - |
| `fuente_id` | `INTEGER` | 0 | `None` | 0 | FK -> fuentes_emision.id |
| `fuente` | `TEXT` | 0 | `None` | 0 | - |
| `url` | `TEXT` | 0 | `None` | 0 | - |
| `notas` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `es_version_activa` | `INTEGER` | 0 | `1` | 0 | - |
| `fecha_vigencia_desde` | `TEXT` | 0 | `None` | 0 | Marca temporal |
| `fecha_vigencia_hasta` | `TEXT` | 0 | `None` | 0 | Marca temporal |
| `creado_por` | `TEXT` | 0 | `'sistema'` | 0 | - |
| `fecha_carga` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `modificado_en` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `scope_ghg` | `INTEGER` | 0 | `2` | 0 | - |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `fuente_id` | `fuentes_emision` | `id` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_factores_lookup` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `tipo_energia`, `anio`, `es_version_activa` | `CREATE INDEX idx_factores_lookup ON factores_emision(pais, tipo_energia, anio, es_version_activa)` |
| `sqlite_autoindex_factores_emision_1` | UNIQUE / UNIQUE CONSTRAINT | `pais`, `tipo_energia`, `anio`, `version` | `autoindex interno de SQLite` |

## fuentes_emision

**Función**: Maestro bibliográfico de fuentes oficiales que respaldan los factores de emisión.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `codigo` | `TEXT` | 1 | `None` | 0 | - |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `organizacion` | `TEXT` | 0 | `None` | 0 | - |
| `anio_publicacion` | `TEXT` | 0 | `None` | 0 | - |
| `url` | `TEXT` | 0 | `None` | 0 | - |
| `notas` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `fecha_carga` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `modificado_en` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_fuentes_emision_1` | UNIQUE / UNIQUE CONSTRAINT | `codigo` | `autoindex interno de SQLite` |

## factores_historial

**Función**: Auditoría de cambios de factores: creación, nuevas versiones, activaciones y edición de metadatos.

**Notas funcionales**:
- Preserva antes/después y versión resultante.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `factor_id` | `INTEGER` | 1 | `None` | 0 | - |
| `accion` | `TEXT` | 1 | `None` | 0 | - |
| `campo` | `TEXT` | 0 | `None` | 0 | - |
| `valor_anterior` | `TEXT` | 0 | `None` | 0 | - |
| `valor_nuevo` | `TEXT` | 0 | `None` | 0 | - |
| `version_resultante` | `INTEGER` | 0 | `None` | 0 | - |
| `usuario` | `TEXT` | 0 | `'sistema'` | 0 | - |
| `fecha_cambio` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `factor_id` es una referencia lógica al factor auditado; el esquema actual no declara FK física.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_fhist_factor` | INDEX / CREADO EXPLÍCITAMENTE | `factor_id` | `CREATE INDEX idx_fhist_factor ON factores_historial(factor_id)` |

## estimaciones

**Función**: Registro de consumos y emisiones estimados para periodos sin factura real.

**Notas funcionales**:
- Soporta ciclo `vigente -> sustituida/rechazada`.
- Acumula métricas de reconciliación cuando llega la factura real.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais` | `TEXT` | 1 | `None` | 0 | - |
| `sede` | `TEXT` | 1 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 1 | `'electricidad'` | 0 | - |
| `periodo_inicio` | `TEXT` | 1 | `None` | 0 | - |
| `periodo_fin` | `TEXT` | 1 | `None` | 0 | - |
| `mes` | `TEXT` | 1 | `None` | 0 | - |
| `consumo_kwh_estimado` | `REAL` | 1 | `None` | 0 | - |
| `consumo_mwh_estimado` | `REAL` | 1 | `None` | 0 | - |
| `emisiones_estimadas` | `REAL` | 0 | `None` | 0 | - |
| `factor_emision` | `REAL` | 0 | `None` | 0 | - |
| `factor_version_id` | `INTEGER` | 0 | `None` | 0 | - |
| `metodo_estimacion` | `TEXT` | 1 | `None` | 0 | - |
| `confianza` | `REAL` | 0 | `0.5` | 0 | - |
| `referencia_facturas_json` | `TEXT` | 0 | `'[]'` | 0 | Contenido JSON serializado |
| `valor_manual` | `REAL` | 0 | `None` | 0 | - |
| `estado` | `TEXT` | 0 | `'vigente'` | 0 | Campo de workflow |
| `factura_real_id` | `INTEGER` | 0 | `None` | 0 | - |
| `desviacion_porcentual_real` | `REAL` | 0 | `None` | 0 | - |
| `creado_por` | `TEXT` | 0 | `'sistema'` | 0 | - |
| `fecha_carga` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `notas` | `TEXT` | 0 | `None` | 0 | - |
| `metodo_detalle_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |
| `confianza_texto` | `TEXT` | 0 | `None` | 0 | - |
| `error_absoluto` | `REAL` | 0 | `None` | 0 | - |
| `n_referencias` | `INTEGER` | 0 | `0` | 0 | - |
| `error_absoluto_kwh` | `REAL` | 0 | `None` | 0 | - |
| `error_relativo_pct` | `REAL` | 0 | `None` | 0 | - |
| `sustituida_en` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `factura_real_id` es referencia funcional a `facturas.id`, sin FK declarada.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_estimaciones_sustit` | INDEX / CREADO EXPLÍCITAMENTE | `estado`, `pais`, `sede` | `CREATE INDEX idx_estimaciones_sustit   ON estimaciones(estado, pais, sede)` |
| `idx_estimaciones_lookup` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `sede`, `tipo_energia`, `mes` | `CREATE INDEX idx_estimaciones_lookup ON estimaciones(pais, sede, tipo_energia, mes)` |

## periodos_faltantes

**Función**: Catálogo de huecos de cobertura por sede, año, mes y tipo de energía.

**Notas funcionales**:
- Sirve como base de calidad y cobertura.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais` | `TEXT` | 1 | `None` | 0 | - |
| `sede` | `TEXT` | 1 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 1 | `'electricidad'` | 0 | - |
| `anio` | `TEXT` | 1 | `None` | 0 | - |
| `mes` | `TEXT` | 1 | `None` | 0 | - |
| `estado` | `TEXT` | 0 | `'faltante'` | 0 | Campo de workflow |
| `factura_id` | `INTEGER` | 0 | `None` | 0 | - |
| `estimacion_id` | `INTEGER` | 0 | `None` | 0 | - |
| `deteccion_fecha` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | - |
| `resolucion_fecha` | `TIMESTAMP` | 0 | `None` | 0 | - |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `factura_id` y `estimacion_id` son referencias lógicas a `facturas` y `estimaciones`; no existen FK físicas en el esquema actual.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_periodos_lookup` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `sede`, `tipo_energia`, `mes` | `CREATE INDEX idx_periodos_lookup ON periodos_faltantes(pais, sede, tipo_energia, mes)` |
| `sqlite_autoindex_periodos_faltantes_1` | UNIQUE / UNIQUE CONSTRAINT | `pais`, `sede`, `tipo_energia`, `mes` | `autoindex interno de SQLite` |

## alertas

**Función**: Bandeja de alertas automáticas o manuales sobre cobertura, calidad, emisiones y documentación.

**Notas funcionales**:
- Gestiona estados `pendiente`, `resuelta`, `ignorada`.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `tipo` | `TEXT` | 1 | `None` | 0 | - |
| `subtipo` | `TEXT` | 0 | `None` | 0 | - |
| `severidad` | `TEXT` | 1 | `'media'` | 0 | - |
| `titulo` | `TEXT` | 1 | `None` | 0 | - |
| `descripcion` | `TEXT` | 0 | `None` | 0 | - |
| `entidad` | `TEXT` | 0 | `None` | 0 | - |
| `entidad_id` | `INTEGER` | 0 | `None` | 0 | - |
| `pais` | `TEXT` | 0 | `None` | 0 | - |
| `sede` | `TEXT` | 0 | `None` | 0 | - |
| `mes` | `TEXT` | 0 | `None` | 0 | - |
| `estado` | `TEXT` | 1 | `'pendiente'` | 0 | Campo de workflow |
| `fecha_creacion` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `fecha_resolucion` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `resuelta_por` | `TEXT` | 0 | `None` | 0 | - |
| `notas_resolucion` | `TEXT` | 0 | `None` | 0 | - |
| `datos_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |
| `auto_generada` | `INTEGER` | 0 | `1` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `entidad` + `entidad_id` apuntan lógicamente a la entidad afectada (factura, sede, etc.).

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_alertas_entidad` | INDEX / CREADO EXPLÍCITAMENTE | `entidad`, `entidad_id` | `CREATE INDEX idx_alertas_entidad ON alertas(entidad, entidad_id)` |
| `idx_alertas_pais_sede` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `sede`, `mes` | `CREATE INDEX idx_alertas_pais_sede ON alertas(pais, sede, mes)` |
| `idx_alertas_tipo` | INDEX / CREADO EXPLÍCITAMENTE | `tipo`, `subtipo`, `estado` | `CREATE INDEX idx_alertas_tipo ON alertas(tipo, subtipo, estado)` |
| `idx_alertas_estado` | INDEX / CREADO EXPLÍCITAMENTE | `estado`, `severidad`, `fecha_creacion` | `CREATE INDEX idx_alertas_estado ON alertas(estado, severidad, fecha_creacion)` |

## alertas_config

**Función**: Configuración de reglas de alertas por tipo/subtipo: activación, severidad y umbral.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `tipo` | `TEXT` | 1 | `None` | 0 | - |
| `subtipo` | `TEXT` | 1 | `None` | 0 | - |
| `activa` | `INTEGER` | 0 | `1` | 0 | - |
| `severidad` | `TEXT` | 1 | `'media'` | 0 | - |
| `umbral_valor` | `REAL` | 0 | `None` | 0 | - |
| `descripcion` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_alertas_config_1` | UNIQUE / UNIQUE CONSTRAINT | `tipo`, `subtipo` | `autoindex interno de SQLite` |

## audit_log

**Función**: Registro inmutable de eventos relevantes del sistema.

**Notas funcionales**:
- Usado para auditoría funcional y seguridad operativa.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `timestamp` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `usuario` | `TEXT` | 1 | `'sistema'` | 0 | - |
| `accion` | `TEXT` | 1 | `None` | 0 | - |
| `entidad` | `TEXT` | 0 | `None` | 0 | - |
| `entidad_id` | `INTEGER` | 0 | `None` | 0 | - |
| `detalle_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |
| `ip_origen` | `TEXT` | 0 | `None` | 0 | - |
| `sesion_id` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `entidad` + `entidad_id` son referencias lógicas, no FK.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_audit_usuario` | INDEX / CREADO EXPLÍCITAMENTE | `usuario`, `timestamp` | `CREATE INDEX idx_audit_usuario ON audit_log(usuario, timestamp)` |
| `idx_audit_entidad` | INDEX / CREADO EXPLÍCITAMENTE | `entidad`, `entidad_id` | `CREATE INDEX idx_audit_entidad ON audit_log(entidad, entidad_id)` |
| `idx_audit_accion_ts` | INDEX / CREADO EXPLÍCITAMENTE | `accion`, `timestamp` | `CREATE INDEX idx_audit_accion_ts ON audit_log(accion, timestamp)` |

## facturas_historial

**Función**: Historial campo a campo de cambios manuales en facturas.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `factura_id` | `INTEGER` | 1 | `None` | 0 | FK -> facturas.id |
| `campo` | `TEXT` | 1 | `None` | 0 | - |
| `valor_anterior` | `TEXT` | 0 | `None` | 0 | - |
| `valor_nuevo` | `TEXT` | 0 | `None` | 0 | - |
| `usuario` | `TEXT` | 1 | `'usuario'` | 0 | - |
| `fecha_cambio` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `motivo` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `factura_id` | `facturas` | `id` | `NO ACTION` | `CASCADE` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_fhist_factura` | INDEX / CREADO EXPLÍCITAMENTE | `factura_id`, `fecha_cambio` | `CREATE INDEX idx_fhist_factura ON facturas_historial(factura_id, fecha_cambio)` |

## lotes_recalculo

**Función**: Cabecera de ejecuciones de recálculo masivo de emisiones.

**Notas funcionales**:
- Agrupa ejecución, alcance, filtros y resumen agregado.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `TEXT` | 0 | `None` | 1 | Clave primaria |
| `alcance` | `TEXT` | 1 | `None` | 0 | - |
| `filtro_pais` | `TEXT` | 0 | `None` | 0 | - |
| `filtro_sede` | `TEXT` | 0 | `None` | 0 | - |
| `filtro_anio` | `TEXT` | 0 | `None` | 0 | - |
| `filtro_factura_id` | `INTEGER` | 0 | `None` | 0 | - |
| `total_facturas` | `INTEGER` | 0 | `0` | 0 | - |
| `procesadas_ok` | `INTEGER` | 0 | `0` | 0 | - |
| `procesadas_error` | `INTEGER` | 0 | `0` | 0 | - |
| `estado` | `TEXT` | 0 | `'pendiente'` | 0 | Campo de workflow |
| `usuario` | `TEXT` | 0 | `'usuario'` | 0 | - |
| `motivo` | `TEXT` | 0 | `None` | 0 | - |
| `fecha_inicio` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `fecha_fin` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `resumen_json` | `TEXT` | 0 | `'{}'` | 0 | Contenido JSON serializado |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_lotes_recalculo_1` | UNIQUE / PK/AUTO | `id` | `autoindex interno de SQLite` |

## recalculos_historial

**Función**: Trazabilidad por factura de cada recálculo ejecutado.

**Notas funcionales**:
- Preserva emisiones/factores originales y recalculados.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `factura_id` | `INTEGER` | 1 | `None` | 0 | - |
| `lote_recalculo_id` | `TEXT` | 0 | `None` | 0 | - |
| `emisiones_originales` | `REAL` | 0 | `None` | 0 | - |
| `factor_original` | `REAL` | 0 | `None` | 0 | - |
| `factor_version_id_original` | `INTEGER` | 0 | `None` | 0 | - |
| `fuente_original` | `TEXT` | 0 | `None` | 0 | - |
| `emisiones_recalculadas` | `REAL` | 0 | `None` | 0 | - |
| `factor_nuevo` | `REAL` | 0 | `None` | 0 | - |
| `factor_version_id_nuevo` | `INTEGER` | 0 | `None` | 0 | - |
| `fuente_nueva` | `TEXT` | 0 | `None` | 0 | - |
| `diferencia_absoluta` | `REAL` | 0 | `None` | 0 | - |
| `diferencia_porcentual` | `REAL` | 0 | `None` | 0 | - |
| `usuario` | `TEXT` | 0 | `'usuario'` | 0 | - |
| `motivo` | `TEXT` | 0 | `None` | 0 | - |
| `fecha_recalculo` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Relaciones lógicas (sin FK declarada)
- `lote_recalculo_id` referencia funcionalmente a `lotes_recalculo.id`.
- `factor_version_id_original` y `factor_version_id_nuevo` apuntan lógicamente a `factores_emision.id` pero no tienen FK física en esta tabla.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_recalculos_factura` | INDEX / CREADO EXPLÍCITAMENTE | `factura_id` | `CREATE INDEX idx_recalculos_factura ON recalculos_historial(factura_id)` |

## paises

**Función**: Maestro de países soportados.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `codigo` | `TEXT` | 0 | `None` | 1 | Clave primaria |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `zona_horaria` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_paises_1` | UNIQUE / PK/AUTO | `codigo` | `autoindex interno de SQLite` |

## sedes

**Función**: Maestro de sedes operativas.

**Notas funcionales**:
- Normaliza las sedes disponibles por país.
- El `UNIQUE(pais_codigo, nombre)` compara nombres **literalmente**, por lo que por sí solo no impide que convivan variantes de la misma sede que solo difieran en tildes, mayúsculas o espacios (p. ej. `Almeria` y `Almería`). `database/migrations_sedes.py` cubre ese hueco: en cada arranque agrupa las sedes por una clave insensible a esas diferencias, conserva la grafía declarada en `config.SEDES_PAISES` y repunta las referencias de `suministros.sede_id` y de las columnas de texto `sede` del resto de tablas.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais_codigo` | `TEXT` | 1 | `None` | 0 | FK -> paises.codigo |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `direccion` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `updated_at` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `pais_codigo` | `paises` | `codigo` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_sedes_1` | UNIQUE / UNIQUE CONSTRAINT | `pais_codigo`, `nombre` | `autoindex interno de SQLite` |

## sociedades

**Función**: Maestro de sociedades del grupo (titulares legales de los puntos de suministro).

**Notas funcionales**:
- Una misma sede puede tener varios CUPS facturados a sociedades distintas
  (p. ej. Asturias tiene CUPS de *Hiberus Tecnologías de la Información SL* y de
  *HIBERUS IT DEVELOPMENT SERVICES SL*). Por eso la sociedad se vincula al
  suministro, no a la sede.
- El campo `facturas.sociedad` es un respaldo en texto libre; la clave de
  agrupación real es `suministros.sociedad_id` → `sociedades.id`.
- `cif` es nullable porque muchas sociedades históricas provienen de
  `facturas.sociedad` (texto libre sin CIF conocido). El índice UNIQUE parcial
  `uq_sociedades_nombre_cif_null` garantiza que no haya duplicados por nombre
  cuando `cif IS NULL` (SQLite trata los NULL como distintos en constraints
  UNIQUE normales).

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `nombre` | `TEXT` | 1 | `None` | 0 | Nombre legal de la sociedad |
| `cif` | `TEXT` | 0 | `None` | 0 | CIF/NIF (nullable si solo se conoce el nombre) |
| `pais_codigo` | `TEXT` | 0 | `None` | 0 | FK -> paises.codigo (inferido de las sedes de sus suministros) |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `fecha_alta` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `pais_codigo` | `paises` | `codigo` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_sociedades_1` | UNIQUE / UNIQUE CONSTRAINT | `nombre`, `cif` | `autoindex interno de SQLite` |
| `uq_sociedades_nombre_cif_null` | UNIQUE / ÍNDICE PARCIAL | `nombre` | `CREATE UNIQUE INDEX uq_sociedades_nombre_cif_null ON sociedades(nombre) WHERE cif IS NULL` |
| `idx_sociedades_pais` | INDEX / CREADO EXPLÍCITAMENTE | `pais_codigo` | `CREATE INDEX idx_sociedades_pais ON sociedades(pais_codigo)` |
| `idx_sociedades_nombre` | INDEX / CREADO EXPLÍCITAMENTE | `nombre` | `CREATE INDEX idx_sociedades_nombre ON sociedades(nombre)` |

## suministros

**Función**: Entidad raíz de puntos de suministro físicos (CUPS) por sede y tipo de energía.

**Notas funcionales**:
- Prepara el salto desde modelo sede-centric a modelo de contador/CUPS real.
- `sociedad_id` vincula el CUPS con su sociedad titular. Una sede puede tener
  varios suministros, cada uno facturado a una sociedad distinta del grupo.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `sede_id` | `INTEGER` | 1 | `None` | 0 | FK -> sedes.id |
| `tipo_energia` | `TEXT` | 1 | `'electricidad'` | 0 | - |
| `referencia` | `TEXT` | 0 | `None` | 0 | CUPS / número de contador |
| `sociedad_id` | `INTEGER` | 0 | `None` | 0 | FK -> sociedades.id (titular del suministro) |
| `notas` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `fecha_alta` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `updated_at` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `sede_id` | `sedes` | `id` | `NO ACTION` | `NO ACTION` |
| `sociedad_id` | `sociedades` | `id` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_suministros_sede` | INDEX / CREADO EXPLÍCITAMENTE | `sede_id`, `tipo_energia` | `CREATE INDEX idx_suministros_sede ON suministros(sede_id, tipo_energia)` |
| `idx_suministros_sociedad` | INDEX / CREADO EXPLÍCITAMENTE | `sociedad_id` | `CREATE INDEX idx_suministros_sociedad ON suministros(sociedad_id) WHERE sociedad_id IS NOT NULL` |
| `sqlite_autoindex_suministros_1` | UNIQUE / UNIQUE CONSTRAINT | `sede_id`, `tipo_energia`, `referencia` | `autoindex interno de SQLite` |

## tipos_energia

**Función**: Maestro de tipos de suministro y sus unidades.

**Notas funcionales**:
- Solo electricidad está activa de forma operativa en el estado actual.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `codigo` | `TEXT` | 0 | `None` | 1 | Clave primaria |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `unidad_medida` | `TEXT` | 1 | `None` | 0 | - |
| `unidad_emision` | `TEXT` | 1 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_tipos_energia_1` | UNIQUE / PK/AUTO | `codigo` | `autoindex interno de SQLite` |

## comercializadoras

**Función**: Maestro de comercializadoras por país y tipo de energía.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `pais_codigo` | `TEXT` | 0 | `None` | 0 | FK -> paises.codigo |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 0 | `'electricidad'` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `pais_codigo` | `paises` | `codigo` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_comercializadoras_1` | UNIQUE / UNIQUE CONSTRAINT | `pais_codigo`, `nombre`, `tipo_energia` | `autoindex interno de SQLite` |

## fuentes_documentos

**Función**: Registro de orígenes documentales (local, SharePoint, SFTP, API).

**Notas funcionales**:
- Hoy se usa almacenamiento local; el modelo ya prepara integraciones futuras.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `tipo` | `TEXT` | 1 | `None` | 0 | - |
| `nombre` | `TEXT` | 1 | `None` | 0 | - |
| `configuracion` | `TEXT` | 0 | `None` | 0 | - |
| `activo` | `INTEGER` | 0 | `1` | 0 | - |
| `ultima_sync` | `TIMESTAMP` | 0 | `None` | 0 | - |
| `creado_en` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_fuentes_documentos_tipo` | INDEX / CREADO EXPLÍCITAMENTE | `tipo`, `activo` | `CREATE INDEX idx_fuentes_documentos_tipo ON fuentes_documentos(tipo, activo)` |

## documentos_indice

**Función**: Índice documental por ejercicio, país, sede y mes.

**Notas funcionales**:
- Facilita cobertura documental y futura migración de ficheros.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `factura_id` | `INTEGER` | 0 | `None` | 0 | FK -> facturas.id |
| `ejercicio` | `TEXT` | 1 | `None` | 0 | - |
| `pais` | `TEXT` | 1 | `None` | 0 | - |
| `sede` | `TEXT` | 1 | `None` | 0 | - |
| `sociedad` | `TEXT` | 0 | `None` | 0 | - |
| `mes` | `TEXT` | 0 | `None` | 0 | - |
| `archivo_nombre` | `TEXT` | 1 | `None` | 0 | - |
| `carpeta_relativa` | `TEXT` | 0 | `None` | 0 | - |
| `archivo_ruta` | `TEXT` | 0 | `None` | 0 | - |
| `sha256` | `TEXT` | 0 | `None` | 0 | - |
| `estado` | `TEXT` | 1 | `'disponible'` | 0 | Campo de workflow |
| `fecha_indexado` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `notas` | `TEXT` | 0 | `None` | 0 | - |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `factura_id` | `facturas` | `id` | `NO ACTION` | `CASCADE` |

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_documentos_indice_estado` | INDEX / CREADO EXPLÍCITAMENTE | `estado` | `CREATE INDEX idx_documentos_indice_estado ON documentos_indice(estado)` |
| `idx_documentos_indice_ejercicio` | INDEX / CREADO EXPLÍCITAMENTE | `ejercicio`, `pais`, `sede` | `CREATE INDEX idx_documentos_indice_ejercicio ON documentos_indice(ejercicio, pais, sede)` |

## sync_log

**Función**: Log de sincronizaciones con fuentes documentales externas.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `fuente_id` | `INTEGER` | 0 | `None` | 0 | FK -> fuentes_documentos.id |
| `fecha_inicio` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `fecha_fin` | `TIMESTAMP` | 0 | `None` | 0 | Marca temporal |
| `documentos_nuevos` | `INTEGER` | 0 | `0` | 0 | - |
| `documentos_duplicados` | `INTEGER` | 0 | `0` | 0 | - |
| `documentos_error` | `INTEGER` | 0 | `0` | 0 | - |
| `estado` | `TEXT` | 0 | `'procesando'` | 0 | Campo de workflow |
| `log_json` | `TEXT` | 0 | `None` | 0 | Contenido JSON serializado |

### Relaciones FK físicas
| Columna local | Tabla destino | Columna destino | ON UPDATE | ON DELETE |
|---|---|---|---|---|
| `fuente_id` | `fuentes_documentos` | `id` | `NO ACTION` | `NO ACTION` |

### Índices y restricciones
Sin índices explícitos ni autoíndices registrados.

## objetivos_emision

**Función**: Objetivos ESG anuales de emisiones a distintos niveles de granularidad.

**Notas funcionales**:
- Permite objetivos absolutos o relativos frente a año base.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `anio` | `INTEGER` | 1 | `None` | 0 | - |
| `pais` | `TEXT` | 0 | `None` | 0 | - |
| `sociedad` | `TEXT` | 0 | `None` | 0 | - |
| `sede` | `TEXT` | 0 | `None` | 0 | - |
| `tipo_energia` | `TEXT` | 0 | `'electricidad'` | 0 | - |
| `emisiones_objetivo_tco2e` | `REAL` | 0 | `None` | 0 | - |
| `pct_reduccion_objetivo` | `REAL` | 0 | `None` | 0 | - |
| `anio_base` | `INTEGER` | 0 | `None` | 0 | - |
| `emisiones_anio_base_tco2e` | `REAL` | 0 | `None` | 0 | - |
| `observaciones` | `TEXT` | 0 | `None` | 0 | - |
| `creado_en` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `modificado_en` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |
| `activo` | `INTEGER` | 1 | `1` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `idx_objetivos_sociedad` | INDEX / CREADO EXPLÍCITAMENTE | `sociedad` | `CREATE INDEX idx_objetivos_sociedad    ON objetivos_emision(sociedad)` |
| `idx_objetivos_pais_sede` | INDEX / CREADO EXPLÍCITAMENTE | `pais`, `sede` | `CREATE INDEX idx_objetivos_pais_sede   ON objetivos_emision(pais, sede)` |
| `idx_objetivos_anio` | INDEX / CREADO EXPLÍCITAMENTE | `anio` | `CREATE INDEX idx_objetivos_anio        ON objetivos_emision(anio)` |
| `sqlite_autoindex_objetivos_emision_1` | UNIQUE / UNIQUE CONSTRAINT | `anio`, `pais`, `sociedad`, `sede`, `tipo_energia` | `autoindex interno de SQLite` |

## metodo_estimacion_metricas

**Función**: Métricas acumuladas de precisión por método de estimación.

**Notas funcionales**:
- Se actualiza automáticamente al reconciliar estimado vs real.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `id` | `INTEGER` | 0 | `None` | 1 | Clave primaria |
| `metodo` | `TEXT` | 1 | `None` | 0 | - |
| `n_sustituciones` | `INTEGER` | 1 | `0` | 0 | - |
| `suma_error_abs` | `REAL` | 1 | `0` | 0 | - |
| `suma_error_rel` | `REAL` | 1 | `0` | 0 | - |
| `max_error_abs` | `REAL` | 0 | `None` | 0 | - |
| `max_error_rel` | `REAL` | 0 | `None` | 0 | - |
| `ultima_actualizacion` | `TIMESTAMP` | 0 | `CURRENT_TIMESTAMP` | 0 | Marca temporal |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
| Índice | Tipo | Columnas | Definición |
|---|---|---|---|
| `sqlite_autoindex_metodo_estimacion_metricas_1` | UNIQUE / UNIQUE CONSTRAINT | `metodo` | `autoindex interno de SQLite` |

## sqlite_sequence

**Función**: Tabla interna de SQLite para el seguimiento de secuencias AUTOINCREMENT.

**Notas funcionales**:
- No pertenece al dominio de negocio, pero forma parte del schema físico.

### Columnas
| Columna | Tipo | NOT NULL | Default | PK | Observación |
|---|---|---:|---|---:|---|
| `name` | `` | 0 | `None` | 0 | - |
| `seq` | `` | 0 | `None` | 0 | - |

### Relaciones FK físicas
Sin claves foráneas declaradas físicamente.

### Índices y restricciones
Sin índices explícitos ni autoíndices registrados.

