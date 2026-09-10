# Roadmap priorizado — Portal de Datos Ambientales Hiberus

## Criterios de priorización

- **Valor de negocio**: impacto directo en operación ESG, cumplimiento, eficiencia o adopción.
- **Complejidad técnica**: Baja / Media / Alta.
- **Dependencias**: funcionales, de arquitectura o de terceros.
- **Esfuerzo**: estimación orientativa en días laborables efectivos, sin incluir esperas organizativas externas.

---

## Fase 6 — Iteraciones 2, 3 y 4

## Iteración 2 — Extensión del modelo a nuevos suministros

### Objetivo
Pasar de un portal centrado en electricidad a una base ESG multisuministro empezando por los casos de mayor valor inmediato.

| Prioridad | Item | Descripción | Valor | Complejidad | Dependencias | Esfuerzo |
|---|---|---|---|---|---|---|
| 1 | Soporte de gas natural | Implementar carga, extracción, factores, cálculo de emisiones, reporting y persistencia para facturas de gas. Incluye extractor específico, validaciones, integración con `tipos_energia`, `suministros`, dashboard y exportaciones. | Alto | Alta | Modelo `suministros`, catálogo `tipos_energia`, factores de gas, extractores específicos | 12-16 días |
| 2 | Soporte de agua | Incorporar agua como nuevo suministro con extracción documental o carga semi-manual, persistencia, indicadores de consumo y preparación de factores si aplica. | Alto | Media | Generalización del modelo de consumo/unidad, extractor o formulario específico | 8-12 días |
| 3 | Generalización analítica multi-suministro | Adaptar consultas, KPIs, comparativas y reportes para que no asuman electricidad como único caso productivo. | Alto | Media-Alta | Gas y/o agua implementados; revisión de `dashboard_service`, `ghg_report_service`, `emisiones_service` | 6-8 días |
| 4 | Ajuste de UX y filtros por tipo de energía | Incorporar selección clara por suministro en la SPA y en todos los endpoints relevantes. | Medio | Media | Generalización multi-suministro | 3-5 días |

### Resultado esperado
- El portal deja de ser “portal de facturas eléctricas con capa ESG” y pasa a ser un **portal ambiental ampliable**.

---

## Iteración 3 — Automatización operativa y gobierno ESG

### Objetivo
Reducir operación manual y mejorar el control directivo del cumplimiento.

| Prioridad | Item | Descripción | Valor | Complejidad | Dependencias | Esfuerzo |
|---|---|---|---|---|---|---|
| 1 | Notificaciones por email | Envío automático de alertas críticas/resúmenes a responsables. Incluye plantillas, preferencias básicas y agrupación por severidad. | Medio | Media | Motor de alertas estable, configuración de SMTP o servicio corporativo | 4-6 días |
| 2 | Notificaciones Teams | Publicación de alertas y resúmenes en canales Teams vía webhook o Graph. | Medio | Media | Diseño de alertas por email o estructura equivalente; acceso Microsoft | 4-6 días |
| 3 | Objetivos ESG por scope | Extender `objetivos_emision` o modelo asociado para fijar metas separadas por scope 1/2/3. | Medio | Media | Uso consistente de `scope_ghg`, adaptación dashboard e informe GHG | 5-7 días |
| 4 | Benchmark automático entre sedes | Comparativas automáticas de intensidad, consumo y emisiones para detectar mejores/peores sedes y desvíos estructurales. | Medio | Media | Calidad de dato suficiente, KPIs por sede maduros | 4-6 días |
| 5 | Afinado de alertas para multisuministro | Adaptar detectores y umbrales al comportamiento de gas y agua. | Medio | Media | Iteración 2 completada | 3-4 días |

### Resultado esperado
- Menor dependencia del uso reactivo del portal.
- Mejor capacidad de seguimiento proactivo por parte de sostenibilidad y facilities.

---

## Iteración 4 — Cuadro de mando ampliado y experiencia ejecutiva

### Objetivo
Cerrar Fase 6 con una capa de explotación más directiva y con menor latencia operativa.

| Prioridad | Item | Descripción | Valor | Complejidad | Dependencias | Esfuerzo |
|---|---|---|---|---|---|---|
| 1 | Dashboard casi en tiempo real | Refrescos más frecuentes, carga incremental y mejoras de rendimiento para que el cuadro refleje entradas recientes sin fricción. | Baja | Media | Optimización de consultas, posible cache ligera | 4-6 días |
| 2 | Cuadro de mando directivo | Vista resumida para dirección: cumplimiento, desviación, focos de riesgo, ranking ejecutivo y alertas estratégicas. | Medio | Media | Dashboard ESG y objetivos consolidados | 5-7 días |
| 3 | Benchmark ejecutivo enriquecido | Añadir percentiles, intensidad por sede y señales de outliers al benchmark. | Medio | Media | Benchmark base de iteración 3 | 3-5 días |
| 4 | Pulido funcional y cierre de deuda visible | Corrección de naming, mensajes, consistencia de filtros y mejoras UX de Fase 6. | Medio | Baja | Iteraciones previas estables | 2-4 días |

### Resultado esperado
- Fase 6 cerrada con capacidad de gestión ESG más madura y explotable a nivel dirección.

---

## Fase 7 — Integración Microsoft

## Objetivo
Integrar el portal con el ecosistema corporativo Microsoft para identidad, documentos, colaboración y visualización avanzada.

| Prioridad | Item | Descripción | Valor | Complejidad | Dependencias | Esfuerzo |
|---|---|---|---|---|---|---|
| 1 | Azure AD / Microsoft Entra ID | Autenticación corporativa, sesión federada, identidad real de usuario y base para RBAC. | Alto | Alta | Tenant corporativo, app registration, definición de roles | 8-12 días |
| 2 | RBAC por perfil y ámbito | Autorización por roles (admin ESG, carga documental, consulta, auditoría) y, si aplica, por país/sociedad/sede. | Alto | Alta | Azure AD operativo, modelo de permisos definido | 6-10 días |
| 3 | SharePoint para almacenamiento documental | Sustituir o complementar `LocalDocumentoStorage` con `SharePointDocumentoStorage` usando Microsoft Graph. | Alto | Alta | Azure AD, permisos Graph, estructura documental corporativa | 10-14 días |
| 4 | Sincronización documental SharePoint | Ingesta y reconciliación de documentos desde bibliotecas SharePoint, con `sync_log` y trazabilidad. | Alto | Alta | SharePoint storage operativo | 6-9 días |
| 5 | Teams para notificaciones corporativas | Integración formal con Teams para alertas y resúmenes ejecutivos. | Medio | Media | Azure/Graph o webhooks habilitados | 4-6 días |
| 6 | Power BI Embedded | Exponer cuadros avanzados o ejecutivos integrados en el portal sin sacar al usuario de la aplicación. | Medio | Alta | Azure AD, dataset gobernado, diseño BI corporativo | 8-12 días |

### Resultado esperado
- El portal pasa de solución interna autónoma a **componente integrado del ecosistema corporativo Microsoft**.

---

## Fase 8 — Inteligencia ESG

## Objetivo
Evolucionar desde reporting y control hacia predicción, recomendación y simulación de escenarios de reducción.

| Prioridad | Item | Descripción | Valor | Complejidad | Dependencias | Esfuerzo |
|---|---|---|---|---|---|---|
| 1 | Recomendaciones automáticas de reducción | Sugerir acciones priorizadas a partir de patrones de consumo, benchmarking y anomalías. | Alto | Alta | Datos suficientemente limpios, benchmark maduro, reglas o modelo de recomendación | 8-12 días |
| 2 | Predicción de emisiones (ML) | Modelos predictivos por sede/sociedad para anticipar cierre, consumo y desviaciones. | Medio | Alta | Histórico suficiente, variables explicativas y base de entrenamiento | 10-15 días |
| 3 | Detección avanzada de anomalías (Isolation Forest u otros) | Complementar reglas heurísticas y z-score con modelos no supervisados. | Medio | Alta | Histórico suficiente y pipeline de features | 7-10 días |
| 4 | Simulación de escenarios | Permitir simular reducciones por sede, factor, eficiencia o sustitución de suministro. | Medio | Media-Alta | Recomendaciones y modelo de negocio bien definidos | 6-9 días |
| 5 | Benchmark inteligente | Priorizar sedes con peor intensidad, detectar clústeres comparables y ofrecer interpretación automática. | Medio | Media | Benchmark automático consolidado | 4-6 días |
| 6 | PostgreSQL + Databricks (condicional) | Migración a arquitectura más escalable y analítica solo si el volumen/usuarios lo justifican. | Baja | Alta | Necesidad real de escala, presupuesto, gobierno de datos | 12-20 días |

### Resultado esperado
- El portal deja de limitarse a describir y controlar; pasa a **anticipar, recomendar y simular**.

---

## Dependencias estratégicas entre fases

### Dependencias críticas
1. **Azure AD** antes de RBAC robusto.
2. **Azure AD / Graph** antes de SharePoint productivo.
3. **Multisuministro** antes de objetivos y benchmarking verdaderamente ambientales.
4. **Calidad de datos + histórico suficiente** antes de ML serio en Fase 8.
5. **Modularización mínima y tests** muy recomendables antes de integrar varias piezas Microsoft y ML.

### Dependencias recomendadas de arquitectura
- Corregir la semilla obsoleta de factores en `config.py`.
- Introducir tests mínimos antes de Fase 7.
- Reducir acoplamiento del frontend antes de añadir capas complejas de UX ejecutiva.

---

## Orden de ejecución recomendado

### Orden propuesto
1. **Fase 6 Iteración 2**
   - Gas
   - Agua
   - Generalización multi-suministro
2. **Fase 6 Iteración 3**
   - Email / Teams
   - Objetivos por scope
   - Benchmark automático
3. **Fase 6 Iteración 4**
   - Cuadro de mando ejecutivo
   - Tiempo casi real
4. **Fase 7**
   - Azure AD
   - RBAC
   - SharePoint
   - Power BI / Teams
5. **Fase 8**
   - Recomendaciones
   - Predicción
   - Anomalías avanzadas
   - Simulación

---

## Resumen de prioridad global

| Bloque | Prioridad | Motivo |
|---|---|---|
| Nuevos suministros (gas, agua) | Muy alta | Amplía el alcance real del portal ambiental |
| Azure AD + RBAC | Muy alta | Cierra el mayor riesgo de seguridad y gobierno |
| SharePoint | Alta | Profesionaliza la gestión documental y elimina dependencia local |
| Objetivos por scope + benchmark | Media | Mejora la gestión ESG avanzada |
| Power BI Embedded | Media | Aporta valor ejecutivo, pero no es prerequisito funcional |
| ML / simulación | Media | Mucho potencial, pero depende de madurez previa |
| PostgreSQL + Databricks | Condicionada | Solo si escala el uso o complejidad analítica |

---

## Conclusión

El roadmap recomendado prioriza primero **ampliación funcional real del dato ambiental** y **gobierno corporativo** (multisuministro + seguridad + documentos), y deja la **inteligencia avanzada** para cuando el producto tenga mejor base de datos, procesos y adopción.

