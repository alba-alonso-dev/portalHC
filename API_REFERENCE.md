# API Reference — Portal de Datos Ambientales de Hiberus

## Convenciones generales

### Formato de respuesta

La mayoría de endpoints devuelven JSON con el patrón:

```json
{"exito": true, "...payload...": "..."}
```

Errores típicos:

```json
{"exito": false, "error": "mensaje"}
```

### Excepciones al patrón

- `GET /` devuelve **HTML**.
- `GET /api/factura/<id>/pdf` devuelve **application/pdf** o redirección.
- `GET /api/descargar-excel` devuelve **Excel**.
- `GET /api/ghg/informe` devuelve **Excel**.
- `GET /api/lote/<id>/estado` devuelve objeto de estado sin `exito`.
- `GET /api/historial` devuelve paginación JSON sin `exito`.

### Nota de inventario

El catálogo funcional entregado menciona `GET /api/facturas` como historial. En el código actual el endpoint expuesto es **`GET /api/historial`**.

---

## Entrada SPA

### GET /
- **Parámetros**: ninguno.
- **Respuesta esperada**: HTML de `templates/index.html`.
- **Caso de uso**: cargar la SPA del portal.

---

## Módulo Facturas

### GET /api/historial
- **Parámetros**: `pais?`, `sede?`, `anio?`, `page?`, `per_page?`.
- **Respuesta esperada**:
```json
{
  "historial": [
    {
      "id": 1,
      "pais": "ES",
      "sede": "Madrid",
      "sociedad": "HIBERUS...",
      "comercializadora": "...",
      "direccion_suministro": "...",
      "fecha_factura": "2025-01-31",
      "periodo_inicio": "2025-01-01",
      "periodo_fin": "2025-01-31",
      "dias_facturados": 31,
      "consumo_kwh": 1000.0,
      "consumo_mwh": 1.0,
      "factor_emision": 187.0,
      "emisiones_tco2e": 0.187,
      "estado": "procesada",
      "archivo_nombre": "factura.pdf",
      "fecha_carga": "...",
      "confianza_ocr": 0.93,
      "duplicado_potencial": 0,
      "tipo_dato": "real"
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 50
}
```
- **Caso de uso**: tabla principal de histórico.

### GET /api/factura/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{
  "exito": true,
  "factura": {
    "id": 1,
    "pais": "ES",
    "sede": "Madrid",
    "factor_version_id": 12,
    "factor_activo_kg_co2_mwh": 187.0,
    "factor_version": 2,
    "fuente_factor_nombre": "MITECO v32"
  }
}
```
- **Caso de uso**: abrir el detalle extendido de una factura.

### GET /api/factura/<id>/pdf
- **Parámetros**: path `id`, query `usuario?`.
- **Respuesta esperada**: stream PDF o redirección.
- **Caso de uso**: descargar la evidencia documental.

### GET /api/factura/<id>/historial-cambios
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{
  "exito": true,
  "factura_id": 1,
  "total": 2,
  "historial": [
    {
      "campo": "periodo_inicio",
      "valor_anterior": "2025-01-02",
      "valor_nuevo": "2025-01-01",
      "usuario": "usuario",
      "fecha_cambio": "...",
      "motivo": "Confirmación manual"
    }
  ]
}
```
- **Caso de uso**: auditoría de cambios manuales.

### POST /api/factura/<id>/confirmar
- **Parámetros**: path `id`; body `periodo_inicio?`, `periodo_fin?`, `dias_facturados?`, `fecha_factura?`, `sociedad?`, `direccion_suministro?`, `usuario?`, `motivo?`.
- **Respuesta esperada**:
```json
{"exito": true, "factura_id": 1, "mensaje": "Datos confirmados y guardados correctamente"}
```
- **Caso de uso**: consolidar datos OCR revisados.

### DELETE /api/factura/<id>
- **Parámetros**: path `id`; body opcional `usuario?`, `motivo?`.
- **Respuesta esperada**:
```json
{"exito": true, "mensaje": "Factura 1 anulada"}
```
- **Caso de uso**: anulación lógica con trazabilidad.

---

## Módulo Procesamiento

### POST /api/procesar
- **Parámetros**: form-data `archivo`, `pais`, `sede`, `usuario?`.
- **Respuesta esperada**:
```json
{
  "exito": true,
  "factura_id": 1,
  "requiere_revision": false,
  "campos_a_revisar": [],
  "advertencias": [],
  "resumen": {"pais": "ES", "sede": "Madrid", "consumo_kwh": 1000.0, "emisiones_tco2e": 0.187}
}
```
- **Caso de uso**: carga individual síncrona.

### POST /api/procesar-lote
- **Parámetros**: form-data `archivos[]`, `pais`, `sede`, `usuario?`.
- **Respuesta esperada**:
```json
{"exito": true, "lote_id": "uuid", "total_archivos": 5, "mensaje": "Procesamiento iniciado para 5 factura(s)"}
```
- **Caso de uso**: carga masiva asíncrona.

### GET /api/lote/<id>/estado
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{
  "lote_id": "uuid",
  "estado": "procesando",
  "progreso": {"total": 5, "procesados": 3, "ok": 2, "error": 1, "pendientes": 2},
  "resultados": [{"archivo": "factura_01.pdf", "estado": "ok", "factura_id": 1}]
}
```
- **Caso de uso**: polling del avance del lote.

---

## Módulo Estadísticas

### GET /api/estadisticas
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "total_facturas": 120, "total_emisiones": 456.789, "total_consumo": 2345.67, "num_paises": 5, "por_pais": [{"pais": "ES", "facturas": 80, "emisiones": 300.12, "consumo": 1600.0}]}
```
- **Caso de uso**: KPIs agregados rápidos del histórico activo.

### GET /api/estadisticas/emisiones/sedes
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "sedes": [{"pais": "ES", "sede": "Madrid", "total_emisiones": 100.0, "total_kwh": 500000.0, "total_mwh": 500.0, "n_facturas": 12, "media_emisiones_mensual": 8.3333, "ranking": 1}], "total": 1}
```
- **Caso de uso**: ranking de sedes por emisiones.

### GET /api/estadisticas/emisiones/sociedades
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "sociedades": [{"sociedad": "HIBERUS DIGITAL S.L.", "total_emisiones": 200.0, "total_kwh": 800000.0, "total_mwh": 800.0, "n_facturas": 24, "n_sedes": 6, "n_paises": 2, "ranking": 1}], "total": 1}
```
- **Caso de uso**: ranking por sociedad.

### GET /api/estadisticas/emisiones/sedes-sociedades
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "sedes": [{"pais": "ES", "sede": "Asturias", "total_emisiones": 3.66, "total_mwh": 19.6, "n_facturas": 18, "sociedades": [{"sociedad": "Hiberus Tecnologías de la Información SL", "cif": null, "emisiones": 2.33, "mwh": 12.5, "n_facturas": 12, "pct": 63.7}]}], "total": 1}
```
- **Caso de uso**: drill-down sede → sociedades. Para cada sede, el desglose de emisiones por sociedad titular. Usa el modelo `suministros.sociedad_id` → `sociedades` con fallback a `facturas.sociedad` cuando no hay vinculación. Permite ver el reparto cuando una sede tiene varios CUPS de sociedades distintas (p. ej. Asturias).

### GET /api/estadisticas/comparativa/sedes
- **Parámetros**: `anio` obligatorio, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "pais": "ES", "sedes": [...], "estadisticas": {"n_sedes": 10, "total_emisiones": 320.4, "media_por_sede": 32.04, "desviacion_std": 8.2, "sede_mayor": "Madrid", "emisiones_mayor": 60.0, "sede_menor": "Logroño", "emisiones_menor": 8.0}}
```
- **Caso de uso**: benchmarking entre sedes.

### GET /api/estadisticas/comparativa/sociedades
- **Parámetros**: `anio` obligatorio, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "pais": null, "sociedades": [...], "estadisticas": {"n_sociedades": 4, "total_emisiones": 500.0, "sociedad_mayor": "HIBERUS...", "emisiones_mayor": 220.0}}
```
- **Caso de uso**: comparativa entre sociedades.

---

## Módulo Dashboard

### GET /api/dashboard/resumen
- **Parámetros**: `anio?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "anio_anterior": "2024", "n_facturas": 120, "emisiones_tco2e": 456.789, "consumo_mwh": 2345.67, "emisiones_anio_anterior": 430.111, "variacion_emisiones_pct": 6.2, "n_sedes": 19, "n_paises": 5, "cobertura": {"pct_real": 80.0, "pct_estimado": 15.0, "pct_faltante": 5.0, "meses_reales": 180, "meses_estimados": 34, "meses_faltantes": 11}, "sedes_pendientes": 3, "alertas": {"critica": 2, "media": 5, "informativa": 4, "total": 11}}
```
- **Caso de uso**: cabecera del dashboard.

### GET /api/dashboard/emisiones
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "total_tco2e": 456.789, "total_tco2e_anio_anterior": 430.111, "variacion_pct": 6.2, "por_pais": [...], "por_sede": [...], "por_mes": [...], "por_mes_anio_anterior": [...], "por_scope": [{"scope": 2, "label": "Scope 2 — Electricidad", "emisiones": 456.789}]}
```
- **Caso de uso**: análisis de emisiones por dimensión.

### GET /api/dashboard/cobertura
- **Parámetros**: `anio?`, `tipo_energia?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "pct_real": 80.0, "pct_estimado": 15.0, "pct_faltante": 5.0, "total_meses_esperados": 228, "total_meses_reales": 180, "total_meses_estimados": 34, "total_meses_faltantes": 14, "detalle_sedes": [...]}
```
- **Caso de uso**: cobertura de datos.

### GET /api/dashboard/calidad
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "total_facturas": 120, "facturas_ocr_bajo": 4, "duplicados_detectados": 2, "consumos_anomalos": 3, "pct_ocr_bajo": 3.3, "score_calidad_global": 92.0, "confianza_ocr_media": 0.91, "sedes_mejor_calidad": [...], "sedes_peor_calidad": [...]}
```
- **Caso de uso**: priorización de limpieza de datos.

### GET /api/dashboard/facturacion
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "total": 120, "revisadas": 90, "pendientes_revision": 20, "duplicados_detectados": 2, "pct_revisadas": 75.0, "por_estado": [{"estado": "confirmada", "n": 90}]}
```
- **Caso de uso**: gestión operativa del workflow de revisión.

### GET /api/dashboard/evolucion
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "pais": "ES", "sede": "Madrid", "serie": [{"mes": "2025-01", "real": 10.0, "estimado": 0.0, "total": 10.0, "anio_anterior": 9.0}], "total_actual": 100.0, "total_anterior": 94.0}
```
- **Caso de uso**: gráfico de tendencia mensual.

### GET /api/dashboard/esg
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "filtros": {"pais": "ES", "sede": "Madrid"}, "emisiones_acumuladas_tco2e": 100.0, "consumo_acumulado_mwh": 500.0, "comparativa_anual": [], "n_objetivos_total": 3, "n_verde": 1, "n_amarillo": 1, "n_rojo": 1, "pct_cumplimiento_global": 4.5, "sedes_en_riesgo": ["Madrid"], "n_sedes_en_riesgo": 1, "semaforo_global": "amarillo", "proyeccion": {...}}
```
- **Caso de uso**: cuadro ejecutivo ESG.

### GET /api/dashboard/proyeccion
- **Parámetros**: `anio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "disponible": true, "anio": "2025", "emisiones_acumuladas_tco2e": 80.0, "meses_con_datos": 7, "meses_restantes": 5, "emisiones_proyectadas_tco2e": 137.1, "proyeccion_pro_rata": 137.1, "proyeccion_estacional": 133.4, "metodo": "estacional", "confianza": 0.8, "diferencia_vs_objetivo_tco2e": 5.0}
```
- **Caso de uso**: prever cierre anual.

---

## Módulo Alertas

### POST /api/alertas/generar
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "generadas": 12}
```
- **Caso de uso**: refresco manual de alertas.

### GET /api/alertas
- **Parámetros**: `estado?`, `severidad?`, `tipo?`, `pais?`, `sede?`, `limit?`.
- **Respuesta esperada**:
```json
{"exito": true, "alertas": [{"id": 1, "tipo": "calidad", "subtipo": "ocr_bajo", "severidad": "media", "titulo": "OCR bajo...", "descripcion": "...", "entidad": "factura", "entidad_id": 10, "pais": "ES", "sede": "Madrid", "estado": "pendiente", "fecha_creacion": "...", "datos_json": "{...}", "auto_generada": 1}], "total": 1}
```
- **Caso de uso**: bandeja general.

### GET /api/alertas/pendientes
- **Parámetros**: `severidad?`, `tipo?`, `pais?`.
- **Respuesta esperada**:
```json
{"exito": true, "alertas": [...], "total": 5}
```
- **Caso de uso**: priorización operativa.

### GET /api/alertas/resueltas
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "alertas": [...], "total": 20}
```
- **Caso de uso**: histórico de resueltas/ignoradas.

### GET /api/alertas/resumen
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "pendientes": {"critica": 2, "media": 5, "informativa": 4}, "total_pendientes": 11, "resueltas": 30, "ignoradas": 3}
```
- **Caso de uso**: badges y KPI de alertas.

### POST /api/alertas/<id>/resolver
- **Parámetros**: path `id`; body `notas?`, `resuelta_por?`.
- **Respuesta esperada**:
```json
{"exito": true, "alerta": {"id": 1, "estado": "resuelta", "resuelta_por": "usuario"}}
```
- **Caso de uso**: cerrar incidencia.

### POST /api/alertas/<id>/ignorar
- **Parámetros**: path `id`; body `resuelta_por?`.
- **Respuesta esperada**:
```json
{"exito": true, "alerta": {"id": 1, "estado": "ignorada"}}
```
- **Caso de uso**: descartar alerta no accionable.

---

## Módulo Estimaciones

### GET /api/estimaciones/gaps
- **Parámetros**: `pais?`, `sede?`, `anio?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "faltantes": [...], "total": 4}
```
- **Caso de uso**: detectar meses sin cobertura.

### GET /api/estimaciones/periodos
- **Parámetros**: `pais?`, `sede?`, `anio?`, `tipo_energia?`, `solo_faltantes?`.
- **Respuesta esperada**:
```json
{"exito": true, "periodos": [...], "total": 12}
```
- **Caso de uso**: catálogo persistido de huecos.

### GET /api/estimaciones
- **Parámetros**: `pais?`, `sede?`, `anio?`, `estado?`.
- **Respuesta esperada**:
```json
{"exito": true, "estimaciones": [...], "total": 8}
```
- **Caso de uso**: listado de estimaciones.

### POST /api/estimaciones
- **Parámetros**: body `pais`, `sede`, `mes`, `metodo`, `tipo_energia?`, `valor_manual?`, `notas?`, `creado_por?`.
- **Respuesta esperada**:
```json
{"exito": true, "estimacion": {"id": 1, "metodo_estimacion": "media_historica", "mes": "2025-02"}}
```
- **Caso de uso**: cubrir un hueco con un método elegido.

### DELETE /api/estimaciones/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "estimacion": {"id": 1, "estado": "rechazada"}}
```
- **Caso de uso**: descartar una estimación.

### POST /api/estimaciones/<id>/sustituir
- **Parámetros**: path `id`; body `factura_real_id`.
- **Respuesta esperada**:
```json
{"exito": true, "estimacion": {"id": 1, "estado": "sustituida", "factura_real_id": 99}}
```
- **Caso de uso**: reemplazar estimado por dato real.

### POST /api/estimaciones/resolver-hueco
- **Parámetros**: body `pais`, `sede`, `mes`, `tipo_energia?`, `umbral_dias?`, `creado_por?`.
- **Respuesta esperada**:
```json
{"exito": true, "estimacion": {...}}
```
- **Caso de uso**: resolver huecos pequeños automáticamente.

### GET /api/estimaciones/comparativa
- **Parámetros**: `pais?`, `sede?`, `anio?`.
- **Respuesta esperada**:
```json
{"exito": true, "comparativa": [{"pais": "ES", "sede": "Madrid", "mes": "2025-02", "metodo_estimacion": "adyacente", "emisiones_estimadas": 1.2, "emisiones_reales": 1.1, "desviacion_porcentual_real": 9.1, "archivo_nombre": "factura.pdf"}], "total": 1}
```
- **Caso de uso**: análisis real vs estimado.

### GET /api/estimaciones/comparativa-metodos
- **Parámetros**: `pais`, `sede`, `mes`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "pais": "ES", "sede": "Madrid", "mes": "2025-02", "metodos": [{"metodo": "estacional", "kwh_estimado": 12345.6, "confianza": 0.82, "confianza_texto": "alta", "n_referencias": 12, "detalle": {...}, "disponible": true}], "n_disponibles": 5, "recomendado": "estacional"}
```
- **Caso de uso**: comparar métodos antes de persistir.

### GET /api/estimaciones/metricas-error
- **Parámetros**: `pais?`, `sede?`, `anio?`.
- **Respuesta esperada**:
```json
{"exito": true, "n_validadas": 25, "error_medio_pct": 8.2, "error_mediano_pct": 6.1, "por_metodo": [...], "por_sede": [...]}
```
- **Caso de uso**: evaluar la precisión histórica del motor.

### GET /api/estimaciones/metricas-precision
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "metricas": [{"metodo": "estacional", "n_sustituciones": 14, "mae_kwh": 120.4, "mape_pct": 4.8, "max_error_abs_kwh": 410.0, "max_error_rel_pct": 11.2, "ultima_actualizacion": "...", "calidad": "excelente"}], "total": 8}
```
- **Caso de uso**: ranking acumulado de precisión por método.

---

## Módulo Calidad

### GET /api/calidad
- **Parámetros**: `anio?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "total_meses": 228, "reales": 180, "estimados": 34, "faltantes": 14, "pct_cobertura": 93.9}
```
- **Caso de uso**: indicador global de calidad/cobertura.

### GET /api/calidad/sedes
- **Parámetros**: `anio?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "sedes": [...], "total": 19}
```
- **Caso de uso**: comparar sedes por calidad.

### GET /api/calidad/sede
- **Parámetros**: `pais`, `sede`, `anio`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "pais": "ES", "sede": "Madrid", "anio": "2025", "pct_cobertura": 100.0, "meses_faltantes": 0}
```
- **Caso de uso**: diagnóstico detallado de una sede.

---

## Módulo GHG Report

### GET /api/ghg/informe
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**: Excel descargable.
- **Caso de uso**: exportar el informe GHG.

### GET /api/ghg/preview
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "informe": {"meta": {"anio": "2025", "pais": "ES", "tipo_energia": "electricidad", "fecha_generacion": "...", "version": "1.1"}, "resumen": {...}, "scopes": {...}, "metodologia": {...}, "calidad": {...}, "trazabilidad": {...}, "detalle_facturas": [...], "por_sociedad": [...]}}
```
- **Caso de uso**: preview del informe sin descarga.

### GET /api/ghg/ranking/sociedades
- **Parámetros**: `anio?`, `pais?`, `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": "2025", "pais": "ES", "tipo_energia": "electricidad", "ranking": [...], "n_sociedades": 4}
```
- **Caso de uso**: ranking societario dentro del módulo GHG.

---

## Módulo Factores de Emisión

### GET /api/factores
- **Parámetros**: `pais?`, `anio?`, `tipo_energia?`, `solo_activos?`, `solo_versiones_activas?`.
- **Respuesta esperada**:
```json
{"exito": true, "factores": [...], "total": 6}
```
- **Caso de uso**: catálogo de factores.

### POST /api/factores
- **Parámetros**: body `pais`, `anio`, `factor_kg_co2_mwh`, `fuente_id`, `tipo_energia?`, `unidad?`, `descripcion?`, `notas?`, `creado_por?`, `fecha_vigencia_desde?`, `fecha_vigencia_hasta?`.
- **Respuesta esperada**:
```json
{"exito": true, "factor": {"id": 10, "pais": "ES", "anio": "2026", "version": 1}}
```
- **Caso de uso**: alta de factor.

### GET /api/factores/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "factor": {"id": 1, "pais": "ES", "version": 2, "fuente_nombre": "MITECO v32"}}
```
- **Caso de uso**: detalle de factor.

### PUT /api/factores/<id>/nueva-version
- **Parámetros**: path `id`; body `factor_kg_co2_mwh`, `fuente_id`, `unidad?`, `descripcion?`, `notas?`, `creado_por?`, `fecha_vigencia_desde?`, `fecha_vigencia_hasta?`.
- **Respuesta esperada**:
```json
{"exito": true, "factor": {"id": 11, "version": 3, "es_version_activa": 1}}
```
- **Caso de uso**: versionar un factor.

### PATCH /api/factores/<id>/metadatos
- **Parámetros**: path `id`; body `descripcion?`, `notas?`, `fuente_id?`, `unidad?`, `fecha_vigencia_desde?`, `fecha_vigencia_hasta?`, `usuario?`.
- **Respuesta esperada**:
```json
{"exito": true, "factor": {...}}
```
- **Caso de uso**: editar metadatos.

### PATCH /api/factores/<id>/estado
- **Parámetros**: path `id`; body `activo`, `usuario?`.
- **Respuesta esperada**:
```json
{"exito": true, "factor": {"id": 11, "activo": 0, "es_version_activa": 0}}
```
- **Caso de uso**: activar/desactivar versión.

### GET /api/factores/<id>/historial
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "historial": [...], "total": 3}
```
- **Caso de uso**: auditoría del factor.

### GET /api/factores/<pais>/<anio>/versiones
- **Parámetros**: path `pais`, `anio`; query `tipo_energia?`.
- **Respuesta esperada**:
```json
{"exito": true, "versiones": [...], "total": 2}
```
- **Caso de uso**: revisar todas las versiones del par país/año.

### GET /api/factores/estado-actualizacion
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"exito": true, "factores": [{"id": 1, "pais": "ES", "anio": "2025", "version": 2, "factor_kg_co2_mwh": 187.0, "fuente_nombre": "MITECO v32", "fuente_url": "https://...", "ultima_actualizacion": "...", "dias_sin_actualizar": 40, "estado_actualizacion": "actualizado"}], "resumen": {"total": 6, "actualizados": 5, "a_revisar": 1, "desactualizados": 0}}
```
- **Caso de uso**: gobierno y mantenimiento de factores.

---

## Módulo Fuentes

### GET /api/fuentes
- **Parámetros**: `solo_activas?`.
- **Respuesta esperada**:
```json
{"exito": true, "fuentes": [...], "total": 8}
```
- **Caso de uso**: listado de fuentes bibliográficas.

### POST /api/fuentes
- **Parámetros**: body `codigo`, `nombre`, `organizacion?`, `anio_publicacion?`, `url?`, `notas?`.
- **Respuesta esperada**:
```json
{"exito": true, "fuente": {"id": 9, "codigo": "MITECO_2025", "nombre": "MITECO v33"}}
```
- **Caso de uso**: alta de nueva fuente.

### GET /api/fuentes/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "fuente": {...}}
```
- **Caso de uso**: detalle de fuente.

### PUT /api/fuentes/<id>
- **Parámetros**: path `id`; body `nombre?`, `organizacion?`, `anio_publicacion?`, `url?`, `notas?`.
- **Respuesta esperada**:
```json
{"exito": true, "fuente": {...}}
```
- **Caso de uso**: actualización de fuente.

---

## Módulo Recálculo

### GET /api/recalculo/impacto
- **Parámetros**: `alcance`, `pais?`, `sede?`, `anio?`, `factura_id?`.
- **Respuesta esperada**:
```json
{"exito": true, "facturas_afectadas": 120, "paises_afectados": 5, "sedes_afectadas": 19, "total_emisiones_original": 450.0, "total_emisiones_nueva": 456.0, "diferencia": 6.0, "porcentaje_variacion": 1.33, "desglose": [...], "advertencias": []}
```
- **Caso de uso**: simulación previa del recálculo.

### POST /api/recalculo/ejecutar
- **Parámetros**: body `alcance`, `pais?`, `sede?`, `anio?`, `factura_id?`, `usuario?`, `motivo?`.
- **Respuesta esperada**:
```json
{"exito": true, "lote_recalculo_id": "uuid", "lote": {"id": "uuid", "alcance": "pais", "estado": "completado", "procesadas_ok": 100, "procesadas_error": 0, "resumen": {"total_emisiones_original": 100.0, "total_emisiones_nueva": 101.5, "diferencia": 1.5, "porcentaje_variacion": 1.5}}}
```
- **Caso de uso**: ejecutar recalculado histórico.

### GET /api/recalculo/lotes
- **Parámetros**: `limit?`.
- **Respuesta esperada**:
```json
{"exito": true, "lotes": [...], "total": 10}
```
- **Caso de uso**: histórico de lotes de recálculo.

### GET /api/recalculo/lote/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "lote": {...}}
```
- **Caso de uso**: detalle de una ejecución concreta.

### GET /api/recalculo/historial/<factura_id>
- **Parámetros**: path `factura_id`.
- **Respuesta esperada**:
```json
{"exito": true, "historial": [...], "total": 2}
```
- **Caso de uso**: auditoría de recálculos por factura.

---

## Módulo Objetivos ESG

### POST /api/objetivos
- **Parámetros**: body `anio`, `pais?`, `sociedad?`, `sede?`, `tipo_energia?`, `emisiones_objetivo_tco2e?`, `pct_reduccion_objetivo?`, `anio_base?`, `emisiones_anio_base_tco2e?`, `observaciones?`.
- **Respuesta esperada**:
```json
{"exito": true, "objetivo": {"id": 1, "anio": 2025, "sede": "Madrid"}}
```
- **Caso de uso**: crear un objetivo ESG.

### GET /api/objetivos
- **Parámetros**: `anio?`, `pais?`, `sociedad?`, `sede?`, `solo_activos?`.
- **Respuesta esperada**:
```json
{"exito": true, "objetivos": [...], "total": 6}
```
- **Caso de uso**: listar objetivos.

### GET /api/objetivos/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "objetivo": {...}}
```
- **Caso de uso**: detalle del objetivo.

### PUT /api/objetivos/<id>
- **Parámetros**: path `id`; body `emisiones_objetivo_tco2e?`, `pct_reduccion_objetivo?`, `anio_base?`, `emisiones_anio_base_tco2e?`, `observaciones?`, `activo?`.
- **Respuesta esperada**:
```json
{"exito": true, "objetivo": {...}}
```
- **Caso de uso**: modificar objetivo.

### DELETE /api/objetivos/<id>
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "mensaje": "Objetivo 1 desactivado"}
```
- **Caso de uso**: baja lógica de objetivo.

### GET /api/objetivos/<id>/seguimiento
- **Parámetros**: path `id`.
- **Respuesta esperada**:
```json
{"exito": true, "objetivo": {...}, "real_acumulado_tco2e": 80.0, "desviacion": -5.0, "pct_cumplimiento": 6.0, "semaforo": "verde", "proyeccion_cierre_tco2e": 130.0, "meses_con_datos": 7, "meses_totales": 12}
```
- **Caso de uso**: seguimiento individual.

### GET /api/objetivos/seguimiento
- **Parámetros**: `anio?`, `pais?`, `sociedad?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "seguimientos": [...], "total": 6}
```
- **Caso de uso**: seguimiento global.

### GET /api/objetivos/resumen-esg
- **Parámetros**: `anio?`.
- **Respuesta esperada**:
```json
{"exito": true, "anio": 2025, "n_objetivos": 6, "n_verde": 2, "n_amarillo": 3, "n_rojo": 1, "n_sin_datos": 0, "pct_cumplimiento_global": 4.5, "sedes_en_riesgo": ["Madrid", "Bogotá"], "detalle": [...]}
```
- **Caso de uso**: semáforo ESG agregado.

---

## Módulo Configuración y gestión documental

### GET /api/paises
- **Parámetros**: ninguno.
- **Respuesta esperada**:
```json
{"paises": [{"codigo": "ES", "nombre": "España"}]}
```
- **Caso de uso**: selector de países.

### GET /api/sedes/<pais>
- **Parámetros**: path `pais`.
- **Respuesta esperada**:
```json
{"sedes": ["Madrid", "Barcelona"]}
```
- **Caso de uso**: selector de sedes por país.

### GET /api/comercializadoras/<pais>
- **Parámetros**: path `pais`.
- **Respuesta esperada**:
```json
{"comercializadoras": ["Iberdrola", "Endesa"]}
```
- **Caso de uso**: catálogos de soporte a formularios.

### GET /api/documentos/indice
- **Parámetros**: `ejercicio?`, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "total": 10, "documentos": [{"id": 1, "factura_id": 10, "ejercicio": "2025", "pais": "ES", "sede": "Madrid", "mes": "2025-01", "archivo_nombre": "factura.pdf", "estado": "disponible", "periodo_inicio": "2025-01-01", "periodo_fin": "2025-01-31", "consumo_kwh": 1000.0}]}
```
- **Caso de uso**: inventario documental.

### GET /api/documentos/cobertura
- **Parámetros**: `ejercicio` obligatorio, `pais?`, `sede?`.
- **Respuesta esperada**:
```json
{"exito": true, "ejercicio": "2025", "meses_cubiertos": ["2025-01", "2025-02"], "meses_faltantes": ["2025-03"], "cobertura_pct": 16.7, "total_docs": 2}
```
- **Caso de uso**: cobertura documental anual.

### POST /api/dev/reset-datos
- **Parámetros**: ninguno; requiere `ALLOW_DEV_RESET=true` (si no, responde `403`).
- **Comportamiento**: vacía las tablas transaccionales (`documentos_indice`,
  `facturas_historial`, `alertas`, `recalculos_historial`, `audit_log`,
  `lotes_recalculo`, `periodos_faltantes`, `estimaciones`, `facturas`, `lotes`,
  `sync_log`) y pone a cero los contadores de `metodo_estimacion_metricas`.
  Conserva los datos maestros: factores, fuentes, países, sedes, comercializadoras
  y tipos de energía. Las claves foráneas permanecen activas durante el borrado.
- **Respuesta esperada**:
```json
{"exito": true, "tablas_vaciadas": ["documentos_indice", "facturas_historial", "..."]}
```
- **Caso de uso**: limpieza de entorno de pruebas.

---

## Módulo Exportación

### GET /api/descargar-excel
- **Parámetros**: `pais?`, `sede?`, `anio?`, `usuario?`.
- **Respuesta esperada**: Excel descargable con facturas activas filtradas.
- **Caso de uso**: extracción offline para análisis y reporting.
