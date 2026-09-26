# Revisión tecnológica y arquitectónica, AlterEgo

> **Estado al cierre del 26 sep.** El cuerpo de esta revisión no se modificó; solo las referencias pasaron a notas al pie de Markdown. Destino de cada recomendación en el registro de decisiones de `docs/PLAN.md`:
>
> - **Nuevas filas en Propuesta:** "SemIf fuera del Plan B", "Datos del organizador en Supabase", "LLM de apoyo sin montos ni comercios", "Modelo de embeddings y respaldo del RAG", "Presupuesto de 500 MB sin Large Functions", "Retención de proveedores externos" y "Cierre de keys y presupuesto". Tres de ellas tocan filas Decididas ("Understand y conversación", "Embeddings del RAG", "Despliegue") y se consultan al equipo antes de aplicarse.
> - **Ya estaba en el plan:** OpenTelemetry recortable (la hoja de ruta de `PLAN.md` lo pone segundo en ceder, después del panel de resultados); máquina de estados propia sin LangGraph; ONNX con paridad frente a LightGBM; Python 3.12; `bank` y `ops` con `app_gateway` y RLS; emisor local bloqueado en producción; tests de `alg=none`, HS256 y token vencido (`docs/SUPABASE_VERCEL.md` sección 7); corte de Jev el 29 sep a las 12:00 (H05); canario sin abrir casos; LightGBM sin `fraud_score` y con split temporal; plantillas sin key de Anthropic; una persona del harness por cliente, no por caso (`docs/SUPABASE_VERCEL.md` sección 3.1).
> - **Acciones sin decisión, a aplicar cuando se toque cada pieza:** fijar Vite en 7.3.2 o 8.0.5 o superior y nunca exponer `vite dev`; MLflow 3.16 o superior, solo local; DuckDB 1.5.x, sin 2.0; regresión logística como baseline de control del modelo de fraude; PR-AUC y Brier o ECE en el reporte; en G3, una falla de Postgres o de un proveedor termina en pendiente o handoff, nunca en confirmación falsa.

Fecha: 2026-09-26 (día 2). Rama de trabajo: `feat/dispute-stack`.

Fuente: deep research encargado por Daniel a una herramienta externa. Entrada: `AGENTS.md`, `docs/PLAN.md`, `docs/SUPABASE_VERCEL.md`, `docs/JEV_TYPESAFE_AI.md`, el enunciado oficial y las slides del kickoff, con la instrucción de citar fuente y fecha y de no inferir donde no hay evidencia pública.

Método del equipo: las citas no se verificaron una por una. Antes de actuar sobre una cifra, confirmarla en la fuente primaria. Reservas conocidas:

- Los CVE de Vite (CVE-2026-39364) y MLflow (CVE-2026-64849) vienen de notas secundarias: verificar en GitHub Security Advisories o NVD antes de fijar versiones por ellos.
- Fuentes débiles: la versión de LangGraph sale de un sitio comparador (usar PyPI); los límites de Supabase Free, de blogs de terceros (`docs/SUPABASE_VERCEL.md` sección 11 tiene las fuentes oficiales verificadas); ONNX Runtime se cita desde un GitHub Pages personal; la adopción de Jev en finanzas es un post de LinkedIn, como el mismo informe admite.
- Algunas versiones van atrasadas: da FastAPI 0.141.0 como última y `pyproject.toml` ya exige 0.141.1 o superior.
- El resumen corto que acompañó al informe tiene las citas desalineadas (la retención de 14 días de LangSmith aparece citada a PyPI). Vale este informe, no ese resumen.

---

**Corte:** 26 de septiembre de 2026. **Entrega:** 5 de octubre de 2026. **Alcance:** arquitectura objetivo de `AGENTS.md §8`, decisiones de `PLAN.md`, con prioridad para estados Propuesta y Abierta.

## Dictamen ejecutivo

La estructura está bien alineada con el problema y con las restricciones del hackathon: un workflow profundo, identidad confiable, política y permisos deterministas, acciones con idempotencia y verificación posterior, HITL estructurado, y separación entre datos analíticos locales y estado operacional. La decisión arquitectónica más importante es correcta: **el modelo interpreta y redacta, pero no autoriza, decide ni afirma que una acción ocurrió**.

No conviene rediseñar el sistema a nueve días de la entrega. Conviene cerrar cuatro riesgos: acceso y evidencia de Jev, legalidad del uso de datos del organizador en Supabase, prueba real del bundle y cold start en Vercel, y retención de todo proveedor externo. Jev debe seguir como experimento con fallback, no como dependencia de G1; el plan B SemIf vía LangSmith debe descartarse salvo aprobación explícita de mentores y evidencia contractual.

| Prioridad | Decisión | Veredicto | Acción antes del gate |
|---|---|---|---|
| P0 | Datos en Supabase | **Validar** | Obtener respuesta escrita de mentores. Mientras tanto usar únicamente fixtures `team-generated` en demo pública. |
| P0 | Jev / TypeSafe | **Validar** | Conseguir key, fijar `typesafe-sdk==0.7.1` y `jev-1.13.0`, ejecutar prueba ES/PT y conservar fallback determinista. |
| P0 | Runtime ONNX | **Mantener y validar** | Comparar paridad LightGBM vs ONNX y desplegar el esqueleto midiendo bundle, memoria y cold start. |
| P0 | SemIf por LangSmith | **Cambiar** | Sacarlo del camino de entrega. No hay evidencia pública suficiente de modelo, versión, privacidad ni desempeño ES/PT. |
| P1 | LangGraph | **Mantener fuera** | Usar máquina de estados propia y patrones tipados. Reconsiderar solo después del hackathon. |
| P1 | Claude Haiku 4.5 | **Mantener con restricción** | Solo mensaje enmascarado y plantillas. Plantillas locales si no hay key o presupuesto. |
| P1 | Embeddings locales | **Validar modelo exacto** | Probar `multilingual-e5-small` ONNX int8 contra BM25; no adoptar BGE-M3 por tamaño. |
| P1 | Supabase Auth/Postgres | **Mantener y validar** | Aplicar migraciones, RLS y permisos en dev; probar 401, 403, aislamiento y read-back. |

## Ajuste al problema

La separación `Understand → Decide → Act → Verify → Escalate` corresponde exactamente al riesgo de una disputa bancaria: incertidumbre lingüística al inicio, reglas y autorización en el centro, efectos controlados al final. El diseño además evita confundir un resultado estructurado de un modelo con una autorización: Pydantic o Jev pueden garantizar forma, pero el código sigue siendo responsable de identidad, propiedad del recurso, política, allowlist de herramientas y umbrales.

La doble persistencia también es acertada. DuckDB sirve para ingestión, análisis y entrenamiento reproducible; Postgres sirve para sesiones conversacionales, concurrencia, casos, locks, handoffs y auditoría. No debe introducirse un segundo sistema de estado mediante checkpoints de un framework, porque crearía dos fuentes de verdad y más trabajo de reconciliación.

La principal reserva no es técnica sino de cumplimiento: aunque los registros sean sintéticos, `AGENTS.md §4` prohíbe que registros privados o no autorizados salgan a terceros. Supabase es un tercero aunque no sea un modelo. Hasta que los mentores respondan, la única interpretación conservadora es desplegar fixtures del equipo con el mismo esquema.

## Tecnologías propuestas

### Jev / TypeSafe AI

| Aspecto | Evidencia al 26-sep-2026 |
|---|---|
| Versión | La documentación enumera `jev-1.13.0`; `jev-latest` y `jev-preview` apuntan hoy a esa versión, pero son alias móviles[^1]. PyPI muestra `typesafe-sdk 0.7.1`[^2]. |
| Madurez | Lanzamiento público en septiembre de 2026, SDK inicial y cinco versiones en pocos días: **experimental/early-stage**, no maduro para una ruta crítica. |
| Capacidad | Devuelve `Choice`, `Score` y `Noul`, no prosa; precio publicado de $0.042 por millón de tokens de entrada y salida sin cargo[^1]. |
| Limitaciones | El propio proveedor advierte lectura literal, dificultad con indirectas y precisión numérica en Jev 1.13[^3]. |
| Adopción bancaria | No se encontró caso bancario o fintech público, auditado y reproducible. Un post de LinkedIn lo considera prometedor para servicios financieros, pero eso es opinión, no adopción demostrada[^4]. |

**Alternativas actuales:** clasificador de palabras clave y regex, Claude Haiku con salida estructurada, un clasificador local pequeño multilingüe, o un modelo tradicional entrenado sobre el set etiquetado. Para nueve días, el fallback de palabras clave es la alternativa de menor riesgo operacional; Claude puede ser un brazo experimental, no la autoridad.

**Encaje:** parcial. Solo recibe `masked_message`, por lo que puede cumplir la prohibición de enviar filas del dataset; sus salidas tipadas encajan con un `IntentExtractor`. Sin embargo, una API externa implica retención, disponibilidad y residencia de datos que deben verificarse contractualmente. `Choice` debe alimentar señales, nunca herramientas directamente.

**Riesgos:** proveedor nuevo, evidencia casi totalmente del proveedor, español y portugués sin benchmark público independiente, y calibración anunciada pero no probada en el dominio. Las garantías de formato no prueban exactitud ni calibración. **Veredicto: VALIDAR**, manteniendo fallback como default hasta superar el set de desarrollo por idioma. Fijar versión exacta, registrar `model` y `request_id`, timeouts breves y circuit breaker.

### SemIf por LangSmith

No se encontró documentación pública verificable para `semif-qwen3.5-4b`, una versión, fecha de release, licencia, retención, residencia, precio, benchmark ES/PT o caso bancario. No debe inferirse que existe, que es privado o que el gateway no retiene datos.

LangSmith Cloud conserva trazas en un nivel base de 14 días o extendido hasta 180 días; la personalización avanzada corresponde a Enterprise. Eso choca con la restricción de no exponer datos y añade un proveedor justo antes de entrega.[^5]

**Alternativas:** fallback determinista, Claude como brazo controlado, o inferencia local fuera de Vercel. **Veredicto: CAMBIAR**, eliminarlo del Plan B operativo. Solo reabrirlo con documentación oficial de modelo y licencia, aprobación escrita de datos, tracing desactivado y prueba de ES/PT.

### ONNX Runtime

ONNX es un formato interoperable para representar modelos, y ONNX Runtime ejecuta modelos exportados desde múltiples frameworks. Es un runtime ampliamente usado; una referencia de Microsoft reporta uso en Office 365, Visual Studio y Bing a gran escala.[^6][^7][^8]

**Alternativas:** servir LightGBM nativo, Treelite, XGBoost nativo o un microservicio de inferencia aparte. Para este despliegue, LightGBM nativo agrega SciPy y una dependencia OpenMP del sistema; un servicio separado excede el tiempo y complejidad razonables del hackathon.

**Encaje:** alto. El mismo runtime puede servir el modelo tabular y embeddings, no envía datos fuera y es compatible con Python 3.12. **Riesgo:** conversión incorrecta de operadores o diferencias numéricas. **Veredicto: MANTENER Y VALIDAR** con prueba de paridad sobre todo el split de validación: misma clase en 100% y desviación máxima de probabilidad definida antes de medir.

### LangGraph y LangSmith

LangGraph es maduro en su categoría: la versión Python reportada en septiembre es 1.2.11 y tiene adopción alta en descargas. Sus checkpoints soportan memoria conversacional, HITL, recuperación, time travel y persistencia Postgres.[^9][^10][^11]

El problema no es capacidad sino duplicación. El sistema ya necesita Postgres como registro y una máquina pequeña con dos esperas explícitas. Añadir checkpoints de grafo no mejora la regla de verificar acciones y sí crea más estado, tablas, serialización y riesgo de guardar texto crudo.

**Alternativas:** máquina de estados explícita en Python, Temporal, AWS Step Functions. Estas últimas son desproporcionadas para un hackathon. **Veredicto LangGraph: MANTENER FUERA**; adoptar únicamente sus patrones. **Veredicto LangSmith: MANTENER FUERA**; OpenTelemetry sin contenido y `ops.audit_log` cubren lo necesario. La documentación confirma que el tracing puede desactivarse y que un servidor local no envía datos salvo telemetría o llamadas explícitas.[^12]

### Embeddings y RAG

`multilingual-e5-small` tiene 12 capas, 384 dimensiones, cerca de 0.1B parámetros y soporte declarado para alrededor de 100 idiomas, con advertencia de degradación en idiomas de pocos recursos. Existe una conversión ONNX preparada para ejecución ligera. BGE-M3 es más potente y soporta más de 100 idiomas y 8,192 tokens, pero su modelo documentado ocupa 2.27 GB, incompatible con el límite conservador de la función.[^13][^14][^15]

**Alternativas:** BM25, TF-IDF, `multilingual-e5-small`, BGE-M3, embeddings externos. Con solo unos 15 fragmentos, BM25 puede ganar por simplicidad y trazabilidad. Un modelo externo viola el criterio local; BGE-M3 excede el presupuesto de bundle.

**Encaje:** alto para E5 pequeño cuantizado, pero el documento debe fijar repositorio, revisión/hash, tokenizer, cuantización y prefijos de consulta/documento. El corpus y sus embeddings se calculan en build; solo la consulta enmascarada se procesa en ejecución. **Veredicto: VALIDAR** `multilingual-e5-small` ONNX int8 contra BM25 con Recall@3 y exact match de `clause_id`, separados por ES/PT. Si no gana de forma consistente, usar BM25 en la demo.

### Supabase Auth y Postgres

Supabase ofrece Postgres, transacciones ACID y auditabilidad, y publica casos en trading, lending y pagos. Es evidencia de adopción fintech, aunque no prueba idoneidad regulatoria automática para un banco real.[^16][^17]

**Alternativas:** Auth0/Clerk más Neon, Firebase, Postgres administrado, o JWT propio. El JWT propio no resuelve emisión ni ciclo de credenciales; separar Auth y base añade integración. Supabase es pragmático para el plazo.

**Encaje:** alto si el front solo usa Auth y todo dato pasa por FastAPI. La separación `bank` read-only y `ops` writable, rol `app_gateway`, RLS y `SET LOCAL` por transacción es coherente con mínimo privilegio. El plan Free reporta 500 MB y pausa por inactividad, por lo que no es un diseño de producción bancaria.[^18]

**Riesgos:** fuga por Data API, políticas RLS mal configuradas, pooler transaccional, expiración/revocación de tokens y pausa durante evaluación. **Veredicto: MANTENER Y VALIDAR**. La demo debe usar fixtures hasta autorización; correr pruebas de autorización como otro cliente, rol agente, token expirado y `alg=none`; verificar permisos directamente como `app_gateway`; desactivar exposición de esquemas y leer de vuelta cada escritura.

### Subconjunto en Supabase

Publicar solo clientes utilizados por la suite, demo y canario es técnicamente mejor que publicar la muestra completa: reduce superficie de exposición sin perjudicar la aplicación. No obstante, minimización no equivale a autorización.

**Alternativas:** fixtures del equipo, datos cifrados en Supabase, base efímera local o servicio privado. El cifrado no resuelve por sí solo la prohibición de alojamiento. **Veredicto: VALIDAR**. Usar fixtures como estado inicial; cambiar a registros sintéticos del organizador solo con aprobación explícita, conservando provenance y excluyendo `is_fraud`, `fraud_score`, documentos, contactos y números de producto.

### Modelo de identidad

Personas sembradas con email/password, signup público deshabilitado y autorización desde `app_metadata` es un patrón razonable para demo. `user_metadata` nunca debe autorizar; `customer_id` tampoco debe aceptarse desde body, prompt o modelo.

**Alternativas:** mock OIDC, JWT local o Auth0. El emisor local es correcto solo para CI y pruebas adversariales. **Veredicto: MANTENER** con dos cambios: no crear un usuario por cada uno de 310 casos si eso agrega fragilidad, sino reutilizar personas por cliente cuando la suite lo permita; y hacer fallar el arranque de producción si el emisor local está habilitado.

### Proyectos Supabase

Dos proyectos Free, dev y demo, aíslan previews de la URL juzgada y aprovechan el máximo gratuito descrito para el plan. Es una buena división, pero no una frontera de seguridad suficiente si ambos contienen datos no autorizados.[^19]

**Veredicto: MANTENER**. Demo inmutable salvo migración versionada; previews apuntan a dev; nunca usar la secret key de administración en Vercel. El canario debe comprobar Auth, lectura, escritura de auditoría y read-back, sin abrir casos.

### Runtime Python y Vercel

Python 3.12.14 salió el 12 de agosto de 2026 y la rama 3.12 está en fase de correcciones de seguridad hasta octubre de 2028. No es la versión feature más reciente, pero es una elección conservadora si es la predeterminada del runtime y todas las wheels resuelven.[^20]

Vercel anunció Large Functions de hasta 5 GB en beta para Python y Node sobre Fluid compute; como el requerimiento del proyecto fija 500 MB, no debe usarse esa beta para justificar el diseño. Mantener el presupuesto de 500 MB aporta portabilidad y reduce cold start.[^21]

**Alternativas:** Python 3.13/3.14, contenedor en Render/Fly/Cloud Run. Cambiar ahora agrega riesgo sin beneficio de evaluación. **Veredicto: MANTENER Python 3.12 y Vercel**, pero el deploy esqueleto es un gate, no una tarea secundaria. Registrar tamaño descomprimido, memoria RSS, cold start p50/p95 y tiempo de instalación.

### LightGBM

LightGBM sigue siendo una opción fuerte para fraude tabular desbalanceado. Un estudio comparativo de 2025 sobre más de 590,000 transacciones reportó que Random Forest y LightGBM lograron weighted F1 de 0.97, con AUC 0.91 y 0.90 respectivamente; también muestra por qué deben reportarse métricas de clase minoritaria, no solo promedios. Esto es evidencia de benchmark, no del dataset del hackathon.[^22]

**Alternativas:** XGBoost, CatBoost, Random Forest, regresión logística. La regresión logística debe incluirse como sanity baseline si el tiempo lo permite; CatBoost merece consideración si predominan categóricas, pero cambiar después de implementar no aporta si LightGBM gana en held-out temporal.

**Encaje:** alto para entrenamiento local y exportación ONNX. Excluir `fraud_score`, usar split temporal y elegir umbral por costo son decisiones correctas. **Veredicto: MANTENER**, condicionado a PR-AUC, recall y precision del fraude, matriz de costos, calibración y comparación con reglas. No afirmar “fraude detectado”; usar el score únicamente para escalar.

### Claude Haiku 4.5

Claude Haiku 4.5 fue lanzado el 15 de octubre de 2025 y se publica a $1 por millón de tokens de entrada y $5 por millón de salida. Tiene suficiente madurez comercial para redactar, pero no hay evidencia pública específica de desempeño en disputas bancarias ES/PT.[^23][^24]

**Alternativas:** plantillas locales, Gemini Flash, GPT mini o modelo local. Las plantillas son el fallback correcto porque el trabajo es rellenar hechos verificados y mantener lenguaje seguro.

**Encaje:** solo si recibe el mensaje enmascarado y marcadores, no filas. La retención estándar de la API puede llegar a 30 días, mientras ZDR requiere acuerdo específico; por ello “ningún registro sale” no significa “ningún texto sensible sale”. **Veredicto: MANTENER CON RESTRICCIÓN**: sanitizar, no enviar hechos de `bank`, salida limitada a texto, validación de marcadores y fallback local. No utilizarlo como extractor de apoyo si eso obliga a enviar comercio o montos no enmascarados.[^25][^26]

### FastAPI y Pydantic

FastAPI sigue activo y ampliamente adoptado; las notas oficiales muestran 0.141.0 publicada el 29 de julio de 2026. Pydantic aporta contratos internos y OpenAPI, pero no es una barrera de autorización.[^27]

**Alternativas:** Flask, Django, Litestar. No existe razón para migrar. **Veredicto: MANTENER**, fijando versiones y generando tipos TypeScript desde un OpenAPI congelado. Separar esquemas de entrada pública, señales internas y comandos de herramientas evita mass assignment.

### React, TypeScript, Vite y Playwright

React 19.3 fue publicado el 9 de septiembre de 2026 y es la versión activa. Playwright 1.63.0 fue publicado el 15 de septiembre de 2026 y automatiza Chromium, Firefox y WebKit.[^28][^29][^30][^31]

**Alternativas:** Next.js, SvelteKit, Streamlit. React con Vite evita añadir SSR y runtime Node; Streamlit dificultaría una consola y chat con controles finos. **Veredicto: MANTENER**. Fijar Vite en una versión corregida, ya que se reportó una vulnerabilidad alta corregida en 7.3.2 y 8.0.5 cuando el dev server se exponía a red. Nunca desplegar `vite dev`; servir solo artefactos de build.[^32]

### DuckDB y validación

DuckDB 1.5.5 es la última estable observada antes del corte, mientras 2.0 seguía planificada y no estable. DuckDB 1.5 es apropiado para CSV particionado, joins, profiling y generación local de marts sin administrar clúster.[^33][^34]

**Alternativas:** Polars, Spark/Databricks, Postgres analítico. Para 5.3 GB y diez días, Spark agrega operación sin ventaja demostrada. **Veredicto: MANTENER DuckDB 1.5.x**, fijando versión y evitando 2.0 alpha. Pandera es opcional; para el gate, constraints SQL y pruebas de paridad pueden ser suficientes y reducen dependencias.

### MLflow y OpenTelemetry

MLflow 3.16.0 salió el 3 de septiembre de 2026 y prioriza observabilidad y trazas GenAI. También hubo explotación de una vulnerabilidad crítica que afectaba versiones anteriores a 3.15.0.[^35][^36]

**Alternativas:** archivos JSON/Parquet con hashes, Weights & Biases, Neptune. **Veredicto MLflow: MANTENER SOLO LOCAL**, versión 3.16 o superior, sin servidor expuesto y sin meterlo en el bundle. Para cuatro personas, un registro de corridas en archivos versionados puede ser suficiente si MLflow pone en riesgo G2.

OpenTelemetry es útil para spans técnicos, pero debe excluir texto, PII, tokens y payloads de base. **Veredicto: VALIDAR/RECORTABLE**: conservar `trace_id`, duración, estado y nombres de etapas; si amenaza el deadline, el audit log es obligatorio y OTel puede ceder.

## Decisiones abiertas

### Keys y presupuesto

Definir dueño, cuenta, límites y fecha de corte. La aplicación debe funcionar sin Jev ni Anthropic; por tanto, keys externas son optimizaciones, no prerrequisitos. Usar cuotas de aplicación en `ops.llm_usage`, timeout, máximo de reintentos y kill switch por proveedor.

**Cierre recomendado:** presupuesto total del hackathon, presupuesto diario, propietario único de cada key, rotación al finalizar y prohibición de keys en previews de forks. Si no hay key de Jev al 29-sep 12:00, congelar el experimento; si no hay key de Anthropic al día 5, plantillas.

### Uso de datos

Esta decisión bloquea el despliegue, no el desarrollo. El repositorio ya contempla una base de fixtures con el mismo esquema, que es la opción segura.

**Cierre recomendado:** demo pública con fixtures del equipo por defecto. Solo publicar el subconjunto del organizador tras respuesta escrita de mentores; registrar origen por fila y mantener un comando reproducible que intercambie datasets sin cambiar código.

## Arquitectura ajustada

```text
React ES/PT + HITL EN
        |
Supabase Auth -> FastAPI session verifier
        |
Input guards: size, language, PII masking, injection delimiters
        |
IntentExtractor
  |- deterministic keyword/regex (always available)
  |- Jev pinned (experimental)
        |
Deterministic state machine + policy engine
        |
Postgres transaction with customer-scoped RLS
  |- read bank candidates
  |- compute policy facts
  |- insert ops effect + audit
        |
new transaction: read-back verification
        |
response renderer
  |- safe local template
  |- optional Claude over masked text + verified placeholders
        |
customer response or structured HITL packet
```

El cambio clave frente al plan actual es eliminar SemIf/LangSmith del camino, declarar BM25 como fallback de producción del RAG y hacer que los proveedores externos sean adaptadores opcionales. De ese modo G1, G2 y la demo no dependen de una waitlist, una key o una política de retención.

## Gates verificables

### Antes de G1

- Ejecutar una conversación ES completa con Auth real o emisor local explícitamente test-only.
- Probar propiedad de transacción: propio, ajeno e inexistente producen comportamiento no filtrante.
- Abrir caso con idempotency key, guardar auditoría en la misma transacción y verificar en una transacción posterior.
- Desplegar esqueleto en Vercel con ONNX Runtime y modelo de embeddings real, no vacío.
- Medir bundle descomprimido, memoria y cold start.

### Antes de G2

- Congelar hashes de suite, versiones y artefactos de modelo.
- Comparar reglas, Jev si disponible y Claude-clasificador con exactamente los mismos casos y splits ES/PT.
- Reportar accuracy, macro-F1, Brier/ECE, abstención, latencia y costo; no seleccionar umbrales en held-out.
- Probar paridad LightGBM/ONNX y evaluación temporal sin `fraud_score`.
- Comparar E5 int8 contra BM25. Adoptar embeddings solo si gana.

### Antes de G3

- Pruebas 401/403, RLS entre clientes, consola agente, `alg=none`, HS256, token vencido y claims modificados.
- Inyección en merchant name y mensaje del cliente; verificar que no altera permisos, política ni allowlist.
- Fallas de Postgres y proveedor externo deben terminar en pendiente o handoff, nunca en confirmación falsa.
- Canario completo con read-back y aviso comprobado.
- Escaneo de secretos y revisión de columnas publicadas.

## Criterio final

La arquitectura merece **mantenerse**, con validaciones focalizadas, porque optimiza correctamente para seguridad demostrable y una entrega de diez días. Los componentes maduros forman el camino obligatorio: FastAPI, Pydantic, Postgres/Supabase, React, DuckDB, LightGBM y ONNX Runtime. Los componentes de evidencia débil o dependencia externa quedan detrás de interfaces y fallbacks: Jev, Claude, embeddings y observabilidad.

La evidencia pública de Jev/TypeSafe AI a septiembre de 2026 es insuficiente para afirmar adopción bancaria, calibración ES/PT o madurez operacional. Debe presentarse como innovación evaluada, no como tecnología probada. Para SemIf no se encontró evidencia pública suficiente en absoluto; incluirlo como plan de contingencia reduciría, en vez de aumentar, la credibilidad técnica.

## Referencias

[^1]: [Models - TypeSafe AI](https://docs.typesafe.ai/models) — Jev is TypeSafe’s flagship model and the first System One model. Every model on this page is served ...
[^2]: [typesafe-sdk · PyPI](https://pypi.org/project/typesafe-sdk/) — Release files for typesafe-sdk 0.7.1 ...
[^3]: [Jev 1.13 jaggedness - TypeSafe AI](https://docs.typesafe.ai/model-jaggedness/jev-1.13) — Jev isn't perfect. Here are some jagged edges we are aware of with jev-1.13. Many of these will be f...
[^4]: [Madhan Kandaswamy, post en LinkedIn](https://www.linkedin.com/posts/kmadhan_typesafe-ais-new-system-one-model-jev-activity-7507954469771403265-wGkE) — TypeSafe AI's new "System One" model, Jev, looks like a major architectural breakthrough for the Fin...
[^5]: [Data purging for compliance - Docs by LangChain](https://docs.langchain.com/langsmith/data-purging-compliance) — This guide covers the various features available after data reaches LangSmith Cloud servers to help ...
[^6]: [ONNX | Home](https://onnx.ai/) — ONNX is an open format built to represent machine learning models. ONNX defines a common set of oper...
[^7]: [ONNX Runtime | Home - GitHub Pages](https://tomwildenhain-microsoft.github.io/onnxruntime/) — ONNX Runtime is an open-source project that is designed to accelerate machine learning across a wide...
[^8]: [ONNX Runtime docs](https://onnxruntime.ai/docs/) — ONNX Runtime is a cross-platform machine-learning model accelerator, with a flexible interface to in...
[^9]: [LangGraph vs MetaGPT: Key Differences (2026) | Modern DataTools](https://www.modern-datatools.com/compare/langgraph-vs-metagpt) — LangGraph is a general orchestration framework: you define states, transitions, cycles and interrupt...
[^10]: [Persistence - Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/persistence) — Checkpointers persist a thread’s graph state as checkpoints. Use them for short-term, thread-scoped ...
[^11]: [Checkpointers - Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/checkpointers) — LangGraph checkpointers save graph state as checkpoints at each step, enabling persistence, human-in...
[^12]: [Data storage and privacy - Docs by LangChain](https://docs.langchain.com/langsmith/data-storage-and-privacy) — This document describes how data is processed in the LangGraph CLI and the Agent Server for both the...
[^13]: [intfloat/multilingual-e5-small - Hugging Face](https://huggingface.co/intfloat/multilingual-e5-small) — This model is initialized from microsoft/Multilingual-MiniLM-L12-H384 and continually trained on a m...
[^14]: [BGE-M3 — BGE documentation](https://bge-model.com/bge/bge_m3.html) — It can support more than 100 working languages. BGE-M3 was trained on multiple datasets covering up ...
[^15]: [Xenova/multilingual-e5-small - Hugging Face](https://huggingface.co/Xenova/multilingual-e5-small) — If you would like to make your models web-ready, we recommend converting to ONNX using Optimum and s...
[^16]: [Supabase for Financial Services](https://supabase.com/solutions/finserv) — Secure, compliant financial applications without the complexity. Supabase is a Postgres development ...
[^17]: [Customer Stories | Supabase](https://supabase.com/customers) — See how Supabase empowers companies of all sizes to accelerate their growth and streamline their wor...
[^18]: [Supabase Pricing 2026: Total Cost & Competitors](https://checkthat.ai/brands/supabase/pricing) — Free Tier, Yes — 50,000 MAUs, 500 MB database, and 5 GB egress, but projects pause after 7 days of i...
[^19]: [Keep Your Supabase Free Tier Project Live Past The Limit](https://aiagencyplus.com/keep-your-supabase-free-tier-project-live-past-the-limit/) — Supabase pauses free tier projects after 7 days of inactivity, and ... 500 MB database size; 5 GB eg...
[^20]: [Python Release Python 3.12.14 | Python.org](https://www.python.org/downloads/latest/python3.12/) — According to the release calendar specified in PEP 693, Python 3.12 is now in the "security fixes on...
[^21]: [Vercel Functions can now be up to 5GB in package size](https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size) — Vercel Functions now support Node.js and Python deployments up to 5GB in package size on Fluid compu...
[^22]: [Evaluating Supervised Learning Models for Fraud Detection (arXiv 2505.22521v2)](https://arxiv.org/pdf/2505.22521v2.pdf) — In this study, we conducted a comprehensive evaluation of four supervised learning models—Logistic R...
[^23]: [Anthropic launches Claude Haiku 4.5, a smaller, cheaper AI model (CNBC)](https://www.cnbc.com/2025/10/15/anthropic-claude-haiku-4-5-ai.html) — Published Wed, Oct 15 2025 ...
[^24]: [Claude Haiku 4.5 - API Pricing & Benchmarks | OpenRouter](https://openrouter.ai/anthropic/claude-haiku-4.5) — Claude Haiku 4.5 was released on October 15, 2025 ...
[^25]: [API and data retention - Claude Platform Docs](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) — Learn about how Anthropic's APIs and associated features retain data, including information about ze...
[^26]: [How long do you store my organization's data?](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data) — Standard Retention Timeframe. For Anthropic API users, we automatically delete inputs and outputs on...
[^27]: [Release Notes - FastAPI](https://fastapi.tiangolo.com/release-notes/) — FastAPI framework, high performance, easy to learn, fast to code, ready for production.
[^28]: [React 19.3](https://react.dev/blog/2026/09/09/react-19-3) — September 9, 2026 by The React Team. React 19.3 is now available on npm! ...
[^29]: [playwright - PyPI](https://pypi.org/project/playwright/) — Released: Sep 15, 2026 ...
[^30]: [React Versions](https://react.dev/versions) — React 19 · v19.3.0 (September 9, 2026) · v19.2.7 (June, 2026) ...
[^31]: [playwright - npm](https://www.npmjs.com/package/playwright) — Latest version: 1.63.0 ...
[^32]: [Vite Dev Server Flaw Fuels Mass Credential Harvesting (CSA)](https://labs.cloudsecurityalliance.org/research/csa-research-note-vite-dev-server-credential-harvesting-2026/) — A high-severity flaw in the Vite JavaScript build tool, tracked as CVE-2026-39364, allows unauthenti...
[^33]: [Release Calendar – DuckDB](https://duckdb.org/release_calendar) — The planned dates of upcoming DuckDB releases are shown below. Please note that these dates are tent...
[^34]: [Releases · duckdb/duckdb - GitHub](https://github.com/duckdb/duckdb/releases) — DuckDB is an analytical in-process SQL database management system.
[^35]: [MLflow releases](https://mlflow.org/releases/) — MLflow 3.12.0 is a release focused on improving our LLM observability workflows, making tracing more...
[^36]: [MLflow Vulnerability Exploited for Cloud Credential Theft (SecurityWeek)](https://www.securityweek.com/mlflow-vulnerability-exploited-for-cloud-credential-theft/) — Hackers are exploiting CVE-2026-64849, a critical SSRF vulnerability in MLflow, to steal credentials...
