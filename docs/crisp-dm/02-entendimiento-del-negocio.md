# CRISP-DM 1. Entendimiento del negocio

AlterEgo resuelve un solo problema de LATAM Bank: recibir disputas de cargos no reconocidos en español y portugués, abrir el caso correcto solo después de verificarlo y pasar a un humano lo que la política no deja automatizar. Esta fase fija por qué ese problema, qué pregunta responde el proyecto, cómo se mide el éxito y qué queda fuera.

En corto: offline, la arquitectura en modo solo reglas supera al pipeline inicial en 250 conversaciones guionizadas; las piezas aprendidas (modelo de riesgo, Jev, embeddings) no tienen una corrida de punta a punta comprometida (`README.md`, "Results").

## Resumen en una tabla

| Tema | Respuesta corta | Fuente |
| --- | --- | --- |
| Problema | Las quejas tienen la peor resolución en primer contacto (43,6 % contra 91,5 % de las transaccionales); las disputas de cargos son el 36,5 % de las quejas | [`AGENTS.md`](../../AGENTS.md) sec. 7 |
| Workflow | Intake de disputas de transacciones, decidido el 26-sep | [`docs/PLAN.md`](../PLAN.md), registro de decisiones |
| Acciones reales | Dos: abrir el caso y bloquear la tarjeta de forma preventiva con el sí del cliente. Nunca mover dinero | `AGENTS.md` sec. 1 y 6 |
| Criterio de éxito | Las métricas oficiales, baseline contra propuesto, sobre la misma suite held-out | `AGENTS.md` sec. 5 |
| Resultado principal | Resolución segura automatizada: 63,6 % (68 de 107) en la corrida ciega y 98,1 % (105 de 107) tras el análisis de errores, contra 3,7 % (4 de 107) del pipeline inicial. Offline, sobre casos guionizados | [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md) |
| Límite mayor | Los datos no traen portugués ni Brasil; producción corre solo reglas más el explicador BM25 | `AGENTS.md` sec. 7; [`README.md`](../../README.md), "Limitations" |

## 1. El problema de negocio: por qué disputas

Las quejas son el motivo de contacto que peor resuelve el banco en la primera llamada, y un tercio de ellas son disputas de cargos.

Motivos de contacto sobre 686.296 interacciones (datos `synthetic-organizer`, carga completa; `AGENTS.md` sec. 7, "Profiling findings"):

| Motivo | Volumen | Resolución en primer contacto (FCR) | Requiere seguimiento | Minutos promedio |
| --- | --- | --- | --- | --- |
| Transaccional | 35,0 % | 91,5 % | 22 % | 3,7 |
| Producto | 22,0 % | 89,6 % | 24 % | 4,4 |
| Queja | 17,1 % | 43,6 % | 63 % | 7,2 |
| Técnico | 15,0 % | 69,9 % | 41 % | 6,0 |
| Comercial | 8,0 % | 65,2 % | 45 % | 9,0 |
| Retención | 3,0 % | 60,2 % | 49 % | 8,0 |

Qué dicen los datos:

- **Queja tiene el peor FCR** (43,6 %), el mayor seguimiento (63 %) y casi el doble de minutos que Transaccional (`AGENTS.md` sec. 6 y 7).
- **Un tercio de las quejas son disputas.** Sobre 67.095 quejas, "Cargo no reconocido" es el 18,3 % y "Cobro indebido" el 18,2 %: 36,5 % juntas (`AGENTS.md` sec. 7).
- **La muestra repite el patrón.** En [`notebooks/01_problema_y_datos.ipynb`](../../notebooks/01_problema_y_datos.ipynb), 19.498 interacciones de marzo de 2025 dan para Queja un FCR de 45,0 %, 62,6 % de seguimiento y 7,3 minutos (celda 8). En sus 1.719 quejas de 2026, las dos subcategorías suman 36,7 % (celda 13).
- **Los volúmenes observados quedan bajo los documentados**: 686.296 contra 800.000 interacciones y 67.095 contra 80.000 quejas, una trampa declarada de calidad (`AGENTS.md` sec. 7). El análisis está en [Entendimiento de los datos](03-entendimiento-de-los-datos.md).

### Qué resultado de negocio se puede prometer

El notebook 01 contrasta las metas iniciales con los datos (celda 31, "Outcomes propuestos contra los datos"):

| Meta inicial | Qué dicen los datos |
| --- | --- |
| 30 a 40 % de las disputas resueltas sin humano | Solo el 5,4 % de los cargos disputables son candidatos a crédito provisional, y ese crédito lo decide un humano. Lo automatizable es abrir el caso, con el techo de la sección 7 |
| Bajar de 7,3 min a menos de 30 s | Los 30 s son una meta; el notebook pide medir la latencia p50 y p95 |
| El handoff ahorra 60 % del tiempo del operador | "Ningun dato lo respalda; no citarlo sin medirlo" |

### Lecturas con cuidado

- **"El contacto más costoso" no sale de los datos.** `docs/PLAN.md` sec. 1 lo afirma. Pero Comercial dura más por contacto (9,0 min), y en minutos agregados Transaccional (35,0 % x 3,7 = 129,5) supera a Queja (17,1 % x 7,2 = 123,1). Queja solo queda arriba si se suman los seguimientos, y no existe costo por resolución ni ROI (hallazgo H18 de [`docs/reviews/2026-09-26-revision-adversarial-plan.md`](../reviews/2026-09-26-revision-adversarial-plan.md), abierto en la [auditoría del 29-sep](../reviews/2026-09-29-adversarial-audit-code-and-docs.md)).
- **El FCR y los minutos son de "Queja" completa, no de disputas.** `origin_interaction_id` está vacío en las 67.095 quejas, así que no se unen a las llamadas (`AGENTS.md` sec. 7). El FCR propio de las disputas no se puede calcular (inferido).
- **No todo es señal.** El escalamiento es un 10 % plano en todos los motivos, y `description` y `resolution` de las quejas son plantillas (`AGENTS.md` sec. 7).

## 2. El reto oficial y cómo sus reglas moldean el diseño

Los organizadores piden un sistema bancario "AI-first", no un chatbot, para un solo workflow de punta a punta, en español y portugués (`AGENTS.md` sec. 1). El jurado parte de una condición, "First and foremost, the solution must work", y luego evalúa documentación, ingeniería de IA, analítica, ingeniería de datos y ML (sec. 5). El cierre de los organizadores: "AI should not be autonomous just because it can be" (sec. 12).

Romper cualquiera de las 12 reglas de `AGENTS.md` sec. 4 descalifica el trabajo. Cada una explica una decisión:

| # | Regla (resumida) | Cómo moldea el diseño |
| --- | --- | --- |
| 1 | Un workflow, en profundidad | Solo disputas; el bloqueo preventivo es parte de la disputa (`AGENTS.md` sec. 6) |
| 2 | Tres tipos de caso | Intake autónomo, aclaración o abstención, o handoff humano ([`src/rules/dispute_policy.py`](../../src/rules/dispute_policy.py)) |
| 3 | Español y portugués, con límites honestos | Extractor de palabras clave ES/PT y textos `explanation_es` y `explanation_pt`; todo caso PT es `team-generated` |
| 4 | Datos aprobados y procedencia etiquetada | Cada dataset, fixture y caso lleva `synthetic-organizer`, `team-generated`, `derived` o externo (`AGENTS.md` sec. 11) |
| 5 | Identidad desde una sesión confiable | Supabase Auth con tokens ES256; `customer_id` sale solo de `app_metadata` (`CLAUDE.md`) |
| 6 | Permisos y política en código | "El modelo propone, el código decide": política determinista y tool gateway (`AGENTS.md` sec. 8) |
| 7 | Solo acciones verificadas | Lectura de vuelta antes de confirmar; si falla, handoff `ACTION_VERIFICATION_FAILED` (`CLAUDE.md`) |
| 8 | Sin dinero ni crédito real | `POL-AUT-150` es una marca que un humano aprueba en la consola |
| 9 | La cadena de pensamiento no es auditoría | Explicaciones con ids de cláusula; cada acción queda en `ops.audit_log` |
| 10 | Sin credenciales ni registros privados | Los modelos externos ven solo el mensaje enmascarado; las llaves de AWS viven en un `.env` fuera de git |
| 11 | Honestidad sobre lo que falta | Secciones de límites en `README.md` y en esta guía |
| 12 | Datos estáticos: probar la actualización con un fixture | Las escrituras se prueban sobre fixtures del equipo (`tests/conftest.py`). El fixture de llegadas tardías que propone `AGENTS.md` sec. 7 existe desde el 5-oct (`data/fixtures/late_arrival_transactions.json`) |

## 3. Por qué ganó el intake de disputas

El enunciado sugiere cuatro workflows como ejemplos, no como tracks, y hacer más de uno no suma puntos (enunciado oficial; `AGENTS.md` sec. 4, regla 1, y sec. 6). El equipo eligió disputas el 26-sep (`docs/PLAN.md`, fila "Workflow").

| Candidato | Decisión y razón | Fuente |
| --- | --- | --- |
| Consultas de cuenta o pago | Descartado: sin acción real y con ML débil; termina en un FAQ | [`docs/TEAM_BRIEF_COMPLEMENTED.md`](../TEAM_BRIEF_COMPLEMENTED.md), Decision 1 |
| Soporte de tarjeta | Descartado. La razón no está en el repo: la tabla vive en la página "Task" de Notion. El bloqueo preventivo quedó dentro de la disputa | `AGENTS.md` sec. 2 y 6 |
| Elegibilidad de crédito | Descartado: complejidad regulatoria y de equidad alta para 10 días. Era el respaldo; se retiró el 26-sep | Brief, Decision 1; `docs/PLAN.md`, fila "Workflow" |
| **Intake de disputas (elegido)** | Ataca el peor FCR, une cinco tablas (`transactions`, `complaints`, `call_center_interactions`, `customers`, `products`) y tiene acciones reales acotadas y verificables | Brief, Decision 1; `AGENTS.md` sec. 6 |

Después de elegir cambió un supuesto: `transactions.is_fraud` parecía la etiqueta del modelo de riesgo, pero no tiene señal aprendible. El modelo servido se transfiere de IEEE-CIS (TQ-026; ver [Modelado](05-modelado.md)).

## 4. La pregunta problema y sus hipótesis

La pregunta, textual de `docs/PLAN.md` sec. 1:

> **¿Puede un sistema de intake de disputas en español y portugués resolver de forma segura y verificada los cargos no reconocidos elegibles de LATAM Bank, logrando más resolución segura automatizada que el baseline actual, sin aumentar los resultados inseguros y con latencia y costo medidos?**

"Resolver" significa abrir el caso correcto y verificarlo, o abstenerse o escalar cuando la política lo pide. No significa reembolsar (`AGENTS.md` sec. 1).

Estado de las cinco hipótesis (texto de `docs/PLAN.md` sec. 1; evidencia de `reports/`; detalle en [Modelado](05-modelado.md) y [Evaluación](06-evaluacion.md)):

| # | Hipótesis | Evidencia | Estado |
| --- | --- | --- | --- |
| H1 | "El sistema propuesto supera a los dos baselines (la versión solo reglas y el pipeline inicial) en resolución segura automatizada." | Contra el pipeline inicial sí (sección 5 y resumen). Contra la versión solo reglas no hay comparación: es el "propuesto" de las corridas (`README.md`, "Results"). Con el modelo de riesgo: 101 de 107 contra 105 de 107 de la versión solo reglas ([`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md), 5-oct): el modelo no la supera en esta métrica | Parcial |
| H2 | "Los resultados inseguros no aumentan; se reportan como conteos con denominador." | Ciega: 15,6 % (39 de 250) contra 48,8 % (122 de 250) del pipeline inicial. Tras el análisis: 8,0 % (20 de 250), las 20 compras en línea extranjeras de alto riesgo, que sin modelo abren caso donde la etiqueta pide humano (`README.md`, "Results"). Con el modelo: 3,6 % (9 de 250) (`reports/eval_heldout_model.md`; intervalos en [`reports/eval_intervals.md`](../../reports/eval_intervals.md)) | Soportada en esta suite, con límites |
| H3 | "El modelo de riesgo sin `fraud_score` supera a la línea base de reglas en la ventana temporal held-out." | Historia completa, test desde 2025-05-30 (1.555.062 filas, 1.445 fraudes): ROC AUC 0,497 contra 0,495 de las reglas ([`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md)). El modelo transferido logra 0,817 en IEEE-CIS, pero su acuerdo con `is_fraud` es 0,507 ([`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md)) | No soportada con los datos del banco |
| H4 | "Jev clasifica la intención mejor que el extractor por palabras clave, con calibración medida por separado en ES y PT." | Medida el 5-oct con llamadas reales sobre el held-out ([`reports/jev_evaluation_report.md`](../../reports/jev_evaluation_report.md)): la misma resolución segura (105 de 107) y más inseguros (26 de 250 contra 20). En el primer mensaje los dos motores aciertan igual (225 de 225). Con una pregunta por afirmación (TQ-044), Jev iguala la seguridad del extractor (20 de 250) y acierta 223 de 250 contra 221. En un banco de 100 mensajes de redacción variada, con la regla fijada antes, Jev lee bien 92 contra 49 del extractor (McNemar p menor a 0,0001; adelante en ES y en PT) ([`reports/intent_hypothesis4_report.md`](../../reports/intent_hypothesis4_report.md)). Producción no tiene key de Jev | Soportada en el banco de mensajes (LLM-drafted, una sola etiquetadora); de punta a punta, igual de seguro que el extractor |
| H5 | "La recuperación del RAG con embeddings multilingües supera a BM25 en recall@3 sobre preguntas de política en ES y PT." | El benchmark comprometido mide solo BM25: recall@3 de 69,6 % (16 de 23) en test ([`reports/rag_benchmark.md`](../../reports/rag_benchmark.md)). E5, medido el 5-oct con la regla fijada antes: 87,0 % (20 de 23), con ventaja de 3 preguntas en ES y de 1 en PT, bajo las 2 por idioma que pedía la regla ([`reports/rag_evaluation_report.md`](../../reports/rag_evaluation_report.md)) | En dirección sí; no por el margen fijado |

Cómo leer la tabla:

1. **La corrida ciega es el resultado held-out.** La de `9efb497` reutiliza los casos que guiaron los arreglos: es una medida posterior al análisis de errores (TQ-033).
2. **No todas las hipótesis usan la misma suite**, aunque `docs/PLAN.md` lo diga: H3 se mide en el banco y en IEEE-CIS, H5 en 60 preguntas de política (auditoría del 29-sep, hallazgo C02).
3. **Los intervalos llegaron el 5-oct.** `reports/eval_intervals.md` da un intervalo de Wilson por tasa y una prueba pareada para H1 y H2 (hallazgo H09 de la auditoría del 29-sep); H3, H4 y H5 siguen sin prueba. Detalle en [Plan de pendientes](09-plan-de-pendientes.md), sección 2.3.
4. **H3 no tiene decisión formal.** La fila "Hipótesis 3 sobre estos datos" de `docs/PLAN.md` sigue en Propuesta y TQ-023 no tiene respuesta.

## 5. Criterios de éxito: las métricas oficiales en palabras simples

El éxito se mide con las métricas del enunciado (`AGENTS.md` sec. 5), con fórmulas en `docs/TEAM_BRIEF_COMPLEMENTED.md` sec. 5 y código en `src/eval/metrics.py`. El resultado es la corrida tras el análisis de errores (`reports/eval_heldout.md`, commit `9efb497`, 3 repeticiones, solo reglas).

| Métrica | En palabras simples | Resultado (propuesto) |
| --- | --- | --- |
| Resolución segura automatizada | El caso que podía resolverse solo termina bien, sin humano. Dos denominadores (TQ-034): 107 elegibles y 230 en alcance. Como 123 de los 230 piden humano, abstención o aclaración, el techo en alcance es 46,5 % (107 de 230) (`README.md`) | 98,1 % (105 de 107); 45,7 % (105 de 230) |
| Intento de automatización | Casos en que el sistema intentó resolver solo | 52,4 % (131 de 250) |
| Contención | Termina sin transferencia. Sola no prueba que se resolvió | 68,8 % (172 de 250) |
| Calidad de escalamiento | Lo que necesita humano le llega, con un handoff útil | Precisión 100,0 % (78 de 78); recall 79,6 % (78 de 98); 20 omitidas, 0 innecesarias |
| Resultados inseguros | Acceso o divulgación no autorizada, acción prohibida o sin verificar, confirmación falsa, promesa de dinero, caída o resultado materialmente incorrecto. Abstenerse cuando hacía falta humano cuenta (TQ-035) | 8,0 % (20 de 250) |
| Eficiencia | Latencia p50 y p95 en proceso, sin red; costo por caso | 161,6 / 662,1 ms; 0 tokens de modelo; el cómputo no se mide (`README.md`) |
| Idioma de la respuesta | Métrica propia del harness | 99,2 % (236 de 238) |

Cada métrica se corta por idioma, país y segmento, con advertencia de muestra chica. El enunciado prohíbe presentar un resultado offline como mejora en producción (`AGENTS.md` sec. 5). La corrida ciega y los cortes están en [Evaluación](06-evaluacion.md).

## 6. Alcance

El alcance es estrecho a propósito: un workflow, dos acciones reales y tres tipos de caso (`docs/PLAN.md` sec. 2).

**Dentro:**

- **Abrir el caso de disputa** (`POL-AUT-INTAKE`) con valores del diccionario: `case_type` Claim, `category` Transactions, `subcategory` "Cargo no reconocido" o "Cobro indebido" (brief, Decision 4).
- **Bloqueo preventivo** (`POL-AUT-LOCK`): solo ante tarjeta robada o fraude en varios cargos, en una tarjeta propia y activa, y después del sí del cliente. En producción se escribe y se verifica en `ops.card_locks`; ningún sistema del banco lo recibe (`README.md`, "Limitations").
- **Handoff humano** con paquete estructurado (`src/domain/handoff.py`), revisado en una consola en inglés.
- **Explicador de políticas** (BM25): responde preguntas sobre las reglas citando la cláusula y nunca cambia una decisión (`README.md`).

Los tres tipos de caso que pide el enunciado (`AGENTS.md` sec. 6):

| Tipo | Ejemplo | Comportamiento esperado |
| --- | --- | --- |
| Normal | "No reconozco un cargo de ayer en Super Ahorro" | Encuentra el cargo, revisa la ventana, abre el caso, lo lee de vuelta y confirma |
| Ambiguo o no soportado | "Tenho uma cobrança estranha" con varios cargos candidatos | Lista opciones y pregunta. Fuera de ventana: explica la política y se abstiene |
| Requiere humano | Monto alto, varios cargos no reconocidos o riesgo alto | Handoff con hechos verificados; bloqueo preventivo si hay tarjeta robada o fraude en varios cargos |

La política v2.3 decide en un orden fijo; el detalle cláusula por cláusula está en [Modelado](05-modelado.md).

**Fuera:**

- **Mover dinero o decidir crédito** (regla 8). `POL-AUT-150` solo marca un candidato a crédito provisional: hasta 150 USD, segmento Premium o Plus, cuenta de más de 180 días y 0 quejas en 90 días. Un humano lo aprueba o rechaza; el cliente oye que su caso quedó registrado y en revisión (`docs/PLAN.md`, fila "Crédito provisional").
- **Desbloquear la tarjeta.** `ACTION_AUTH_MATRIX` la declara como acción de consola, pero no se construyó (`README.md`).
- **Otros productos.** Préstamos, saldos, inversiones o soporte de tarjeta, leídos con confianza decisiva, terminan en una abstención que nombra la categoría ([`docs/technical-discuss-points.md`](../technical-discuss-points.md) sec. 2.3).

## 7. Supuestos y límites conocidos

**Supuestos:**

| Supuesto | Consecuencia | Fuente |
| --- | --- | --- |
| "Hoy" es 2026-06-17, el fin del dataset | Ventana y antigüedad de cuenta usan esa fecha, fija en código y en SQL (`ops.business_today()`) | `CLAUDE.md`, "Gotchas" |
| El dataset es 100 % sintético (`synthetic-organizer`) | No hay clientes reales | `AGENTS.md` sec. 7 |
| El día del banco es `process_date` (UTC-6) | La ventana usa `process_date`; el cast simple fecha mal cerca del 24 % de las filas | `AGENTS.md` sec. 7 |
| Los topes van en USD | COP y ARS se convierten con la tasa diaria; México transacciona en USD | `AGENTS.md` sec. 7 |
| Portugués y preguntas de política son del equipo | Todo caso PT es `team-generated`; el banco de preguntas lo redactó un LLM | `README.md`; `reports/rag_benchmark.md` |
| IEEE-CIS es externo | Transacciones reales de e-commerce, desidentificadas, de una competencia de Kaggle, para uso de competencia y no comercial | `README.md`, "Limitations" |

**Límites:**

- **Idioma y país.** Los datos no traen portugués ni Brasil (`AGENTS.md` sec. 7). Además, el idioma queda fijo cuando la conversación sale del estado `new` (`src/orchestrator/dispute_orchestrator.py`, línea 171): si el cliente cambia a portugués después, sigue recibiendo español (inferido de la lectura del código; ningún test lo demuestra).
- **Techo de 500 USD.** De los 8.967 cargos disputables de la muestra de junio, 3.547 (39,6 %) superan 500 USD, así que el techo de contención es 60,4 %, antes de los escalamientos por riesgo, legales, de varios cargos y de aclaración ([`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md) sec. 5). Con 300 USD sería 36,0 % y con 1.000 USD 67,3 %. El equipo mantuvo 500 USD (`docs/PLAN.md`, fila "Techo de escalamiento de $500"). `docs/PLAN.md`, `AGENTS.md` sec. 7, `docs/TEAM_BRIEF_COMPLEMENTED.md` y el texto del notebook 01 dicen 60,5 % (39,5 %): la spec explica que ese texto quedó desfasado en una fila y toma como fuente la salida de la celda 26. La contención de la suite (68,8 %) no se compara con este techo: la mezcla de la suite es de diseño (inferido).
- **Planes gratis.** Vercel Hobby y un solo proyecto Supabase Free que también es producción. El plan Free pausa un proyecto inactivo y el canario planeado no se construyó (`README.md`; `AGENTS.md` sec. 8 y 9).
- **Configuración de producción.** Solo reglas más el explicador BM25. El archivo del modelo de riesgo está fuera de git y Vercel construye desde GitHub, así que `POL-ESC-ML-RISK` nunca se dispara. No hay key de Jev ni de LLM: toda respuesta es una plantilla (`README.md`; commit `a18f045`).
- **Etiquetas y medición.** La suite tiene etiquetas de diseño, sin doble etiquetado ni kappa (TQ-018). Los resultados son offline, sobre casos guionizados, no ganancias de producción (`reports/eval_heldout.md`).
- **Explicador de políticas.** En test acierta la acción en el 36,7 % (11 de 30), y el 27,3 % (3 de 11) de sus respuestas cita una cláusula equivocada (`reports/rag_benchmark.md`).
- **Uso de datos de IEEE-CIS (contradicción abierta).** `README.md` ("Limitations"), TQ-032 y la fila "Uso de datos en el despliegue y en los modelos" de `docs/PLAN.md` registran la aprobación de los mentores. La fila "Modelo de riesgo transferido de IEEE-CIS" del mismo `docs/PLAN.md`, la respuesta de TQ-026 y [`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md) (encabezado y sec. 7) dicen que la licencia sigue pendiente. La regla 4 solo admite datos aprobados.
- **Capacidad del equipo.** El plan se escribió para 4 personas en tres frentes (`docs/PLAN.md`, fila "Equipo"); el equipo terminó en dos, Daniel y Kmilo (`docs/TEAM_BRIEF_COMPLEMENTED.md`, Decision 5).

## Cómo se conecta con el resto

- [Entendimiento de los datos](03-entendimiento-de-los-datos.md): motivos de contacto, quejas y trampas de calidad.
- [Preparación de los datos](04-preparacion-de-los-datos.md): `process_date`, `amount_usd` y la muestra que alimenta la política.
- [Modelado](05-modelado.md): la política como código, el modelo de riesgo transferido y el explicador BM25.
- [Evaluación](06-evaluacion.md): la suite de 250 casos, sus dos corridas y los cortes.
- [Despliegue](07-despliegue.md): qué corre en Vercel y Supabase.

## Fuentes

- [`AGENTS.md`](../../AGENTS.md) sec. 1, 4 a 9, 11 y 12; [`README.md`](../../README.md) ("Results", "Limitations"); [`CLAUDE.md`](../../CLAUDE.md).
- [`docs/PLAN.md`](../PLAN.md) sec. 1 y 2 y registro de decisiones; [`docs/TEAM_BRIEF_COMPLEMENTED.md`](../TEAM_BRIEF_COMPLEMENTED.md), Decisions 1, 4 y 5 y sec. 5.
- [`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md) sec. 5; [`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md); [`docs/technical-discuss-points.md`](../technical-discuss-points.md) sec. 2.3; [`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md) sec. 6.
- [`docs/reviews/2026-09-26-revision-adversarial-plan.md`](../reviews/2026-09-26-revision-adversarial-plan.md) y [`docs/reviews/2026-09-29-adversarial-audit-code-and-docs.md`](../reviews/2026-09-29-adversarial-audit-code-and-docs.md) (C02, H09, H18).
- [`reports/eval_heldout.md`](../../reports/eval_heldout.md), [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md), [`reports/rag_benchmark.md`](../../reports/rag_benchmark.md), [`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md), [`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md).
- [`notebooks/01_problema_y_datos.ipynb`](../../notebooks/01_problema_y_datos.ipynb), celdas 8, 13, 26, 28 y 31; [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json), TQ-017, TQ-018, TQ-023, TQ-026 y TQ-032 a TQ-035.
- [`src/rules/dispute_policy.py`](../../src/rules/dispute_policy.py); [`src/orchestrator/dispute_orchestrator.py`](../../src/orchestrator/dispute_orchestrator.py).
- Enunciado oficial (copia local, fuera de git); PR #24, #44 y #45 (`gh pr view`); commit `a18f045`.
