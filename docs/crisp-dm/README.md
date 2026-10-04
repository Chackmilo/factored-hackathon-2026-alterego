# Guía del proyecto con CRISP-DM

Esta carpeta explica AlterEgo de punta a punta con las fases de CRISP-DM: qué problema resuelve, con qué datos, cómo decide, cuánto mejora y qué corre en producción. Sirve al equipo, a un jurado y a quien herede el repo. Cada cifra sale de un archivo comprometido del repo o de metadatos de git y GitHub, citado con su ruta. Lo que no tiene fuente directa se marca "inferido".

## 1. Para qué sirve y cómo leerla

Orden sugerido: el resumen (00), la guía de uso (01), las seis fases en orden (02 a 07) y las iteraciones (08). Con cinco minutos, lea 00. Para correr el sistema, 01. Para juzgar el método, 02 a 07.

| Archivo | Fase CRISP-DM | Pregunta que responde | Lectura |
| --- | --- | --- | --- |
| [00-resumen-ejecutivo.md](00-resumen-ejecutivo.md) | Todas | ¿Qué es AlterEgo, qué logró y qué falta? | 4 min |
| [01-guia-de-uso.md](01-guia-de-uso.md) | Apoyo al despliegue | ¿Cómo pruebo la demo, lo corro en local y reproduzco las cifras? | 17 min |
| [02-entendimiento-del-negocio.md](02-entendimiento-del-negocio.md) | 1. Entendimiento del negocio | ¿Por qué disputas, qué pregunta responde el proyecto y cómo se mide el éxito? | 15 min |
| [03-entendimiento-de-los-datos.md](03-entendimiento-de-los-datos.md) | 2. Entendimiento de los datos | ¿Qué trae el dataset, qué trampas tiene y qué cambió cada hallazgo? | 17 min |
| [04-preparacion-de-los-datos.md](04-preparacion-de-los-datos.md) | 3. Preparación de los datos | ¿Cómo se limpian los datos, qué viaja a producción y cómo se armaron las suites? | 16 min |
| [05-modelado.md](05-modelado.md) | 4. Modelado | ¿Quién decide, qué modelos hay y por qué esos? | 16 min |
| [06-evaluacion.md](06-evaluacion.md) | 5. Evaluación | ¿Cuánto mejora sobre el baseline y qué no prueban las cifras? | 17 min |
| [07-despliegue.md](07-despliegue.md) | 6. Despliegue | ¿Qué corre en producción, con qué controles y con qué riesgos? | 16 min |
| [08-iteraciones-y-decisiones.md](08-iteraciones-y-decisiones.md) | Vuelta del ciclo | ¿Qué cambió, cuándo y por qué? | 13 min |
| README.md (este archivo) | Entrada | ¿Cómo se lee la guía y dónde están las fuentes? | 10 min |

La lectura se estimó a unas 200 palabras por minuto sobre el conteo de palabras del 4-oct. Las tablas se leen más lento.

## 2. El proyecto de principio a fin en 10 pasos

1. **Elegir el problema.** Las quejas tienen la peor resolución en primer contacto del banco (43,6 %) y un tercio son disputas de cargos. El 26-sep el equipo eligió el intake de disputas ([02](02-entendimiento-del-negocio.md), secciones 1 y 3).
2. **Fijar la pregunta y el éxito.** La pregunta problema de `docs/PLAN.md` sec. 1 y las métricas oficiales, baseline contra propuesto sobre la misma suite ([02](02-entendimiento-del-negocio.md), secciones 4 y 5).
3. **Perfilar los datos.** 13 tablas sintéticas en español, sin portugués ni Brasil. `fraud_score` filtra `is_fraud` y la hora del evento va 6 h corrida ([03](03-entendimiento-de-los-datos.md)).
4. **Preparar los datos.** Bronze, silver y gold en DuckDB, `amount_usd` corregido una vez y ventana con `process_date`. A Postgres viaja una copia mínima de 253 clientes ([04](04-preparacion-de-los-datos.md), secciones 1 a 5).
5. **Construir las suites antes de ajustar.** 19 casos de desarrollo y 250 held-out, congelados con su SHA-256 el 30-sep ([04](04-preparacion-de-los-datos.md), sección 7).
6. **Escribir la política como código.** La política v2.3 recorre sus cláusulas en orden fijo y cita la que decide ([05](05-modelado.md), sección 1).
7. **Sumar señales sin ceder la decisión.** El modelo de riesgo transferido de IEEE-CIS, el explicador de políticas con BM25 y el extractor de palabras clave o Jev solo entregan señales ([05](05-modelado.md), secciones 2 a 4).
8. **Evaluar.** Corrida ciega con 63,6 % (68 de 107) de resolución segura automatizada, arreglos con tests propios y corrida posterior con 98,1 % (105 de 107), cada una con sus límites ([06](06-evaluacion.md)).
9. **Desplegar.** Vercel Hobby y Supabase Free; producción corre solo reglas más el explicador ([07](07-despliegue.md)).
10. **Iterar y registrar.** Cada giro tiene su fecha, su evidencia y su lección ([08](08-iteraciones-y-decisiones.md)).

## 3. Lo que hay que tener en cuenta para entender el proyecto

1. **"Hoy" es 2026-06-17**, el último día del dataset. La ventana y la antigüedad de cuenta usan esa fecha, escrita en código y en SQL (`ops.business_today()`) ([`CLAUDE.md`](../../CLAUDE.md), "Gotchas"; [`supabase/migrations/0003_bank.sql`](../../supabase/migrations/0003_bank.sql)).
2. **El día del banco es `process_date`**, 6 h detrás de `transaction_date`. El cast simple de la fecha falla en cerca del 24 % de las filas ([`AGENTS.md`](../../AGENTS.md) sec. 7; [03](03-entendimiento-de-los-datos.md), sección 3.1).
3. **`fraud_score` filtra `is_fraud`, e `is_fraud` no tiene señal.** Sin la fuga, el modelo da ROC AUC de test 0,497 ([`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md)). Por eso el riesgo se transfiere de IEEE-CIS ([05](05-modelado.md), sección 2).
4. **El modelo propone y la política decide** ([`docs/PLAN.md`](../PLAN.md) sec. 2; `AGENTS.md` sec. 8). Ningún modelo abre un caso ni bloquea una tarjeta.
5. **La identidad sale solo del token de sesión**, del `app_metadata` de Supabase; nunca del mensaje ni del cuerpo de la petición (`AGENTS.md` sec. 4, regla 5; [`src/auth/session.py`](../../src/auth/session.py)).
6. **Suite held-out congelada, dos corridas.** La corrida ciega (63,6 %) es el resultado held-out. La posterior (98,1 %) reutiliza los casos que guiaron los arreglos (TQ-033; [06](06-evaluacion.md), sección 5).
7. **Producción corre solo reglas más el explicador BM25:** sin modelo de riesgo, sin Jev y sin respuestas de Claude ([`README.md`](../../README.md), "Limitations"; commit `a18f045`).
8. **Las personas de demo comparten estado.** Un caso abierto queda para el siguiente usuario y apaga `POL-AUT-150` ([01](01-guia-de-uso.md), sección 1.5; [`docs/HANDOFF.md`](../HANDOFF.md) sec. 3, A2).
9. **Planes gratuitos.** Vercel Hobby y un solo proyecto Supabase Free que también es producción. El plan Free pausa un proyecto inactivo y el canario planeado no existe (`README.md`, "Limitations"; [07](07-despliegue.md), sección 8).
10. **Techo de contención de 60,4 %.** El tope de 500 USD manda a humano 3.547 de los 8.967 cargos disputables de junio (39,6 %) ([`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md) sec. 5).
11. **El portugués lo generó el equipo.** Los 100 casos PT del held-out y las 30 preguntas PT del banco de política son `team-generated` (`AGENTS.md` sec. 7; `README.md`, "Data").
12. **Etiquetas de diseño, sin kappa.** Las 250 etiquetas salen de la spec y las planillas de doble etiquetado están vacías (TQ-018; [06](06-evaluacion.md), sección 9).
13. **Solo algunos merges despliegan.** Con el repo privado, Vercel Hobby despliega solo los commits atribuidos a la cuenta dueña: los merges #39 a #48 no se desplegaron en su momento y llegaron a producción con los merges web posteriores (`docs/HANDOFF.md`, nota inicial; `AGENTS.md` sec. 9; [07](07-despliegue.md), sección 7).

## 4. Mapa de fuentes

| Fase | Documentos canónicos | Código | Reportes y datos | Notebooks |
| --- | --- | --- | --- | --- |
| Negocio | [`AGENTS.md`](../../AGENTS.md) secs. 1 a 6; [`docs/PLAN.md`](../PLAN.md) secs. 1 y 2; [`docs/TEAM_BRIEF_COMPLEMENTED.md`](../TEAM_BRIEF_COMPLEMENTED.md) | No aplica | [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json) | [01](../../notebooks/01_problema_y_datos.ipynb) |
| Datos | `AGENTS.md` sec. 7; [`docs/technical-discuss-points.md`](../technical-discuss-points.md) | [`src/data/ingestion.py`](../../src/data/ingestion.py) | [`reports/ml_full/`](../../reports/ml_full/) | [01](../../notebooks/01_problema_y_datos.ipynb) a [05](../../notebooks/05_ieee_cis_feature_homologation.ipynb) |
| Preparación | [`CLAUDE.md`](../../CLAUDE.md); [`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 4 | [`src/data/`](../../src/data/), [`src/eval/heldout.py`](../../src/eval/heldout.py), [`src/ml/feature_contract.py`](../../src/ml/feature_contract.py) | [`data/eval/`](../../data/eval/), [`data/serving_customers.json`](../../data/serving_customers.json) | [01](../../notebooks/01_problema_y_datos.ipynb) |
| Modelado | [`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md), [`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md), [`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md), [`docs/specs/claude-replies-v1.md`](../specs/claude-replies-v1.md) | [`src/rules/`](../../src/rules/), [`src/ml/`](../../src/ml/), [`src/rag/`](../../src/rag/), [`src/understand/`](../../src/understand/) | [`reports/ml/`](../../reports/ml/), [`reports/rag_benchmark.md`](../../reports/rag_benchmark.md), [`data/policy_corpus.json`](../../data/policy_corpus.json) | [02](../../notebooks/02_risk_model_experiment.ipynb), [03](../../notebooks/03_fraud_signal_search.ipynb), [05](../../notebooks/05_ieee_cis_feature_homologation.ipynb) |
| Evaluación | `AGENTS.md` sec. 5; `docs/TEAM_BRIEF_COMPLEMENTED.md` sec. 5; `README.md`, "Results" | [`src/eval/`](../../src/eval/) | [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md), [`reports/eval_dev.md`](../../reports/eval_dev.md) | No aplica |
| Despliegue | `docs/SUPABASE_VERCEL.md`; [`docs/HANDOFF.md`](../HANDOFF.md); [`docs/SECURITY_AUDIT_PLAN.md`](../SECURITY_AUDIT_PLAN.md) | [`src/api/`](../../src/api/), [`src/auth/`](../../src/auth/), [`src/tools/`](../../src/tools/), [`src/ops/`](../../src/ops/), [`supabase/migrations/`](../../supabase/migrations/), [`vercel.json`](../../vercel.json) | Metadatos de GitHub (despliegues, CI) | No aplica |
| Iteración | `docs/PLAN.md`, registro de decisiones; [`docs/reviews/`](../reviews/) | `git log`; PR #1 a #53 | `data/fixtures/team_questions.json` | No aplica |

## 5. Contradicciones y preguntas abiertas

La guía las declara donde aparecen y usa la cifra indicada. "Quién decide" es una propuesta de esta guía, basada en quién respondió la pregunta del equipo relacionada o en los dueños de `docs/HANDOFF.md` sec. 3.

| # | Tema | Una fuente dice | Otra fuente dice | La guía usa | Quién decide |
| --- | --- | --- | --- | --- | --- |
| 1 | Techo de contención | 60,4 %: `docs/specs/dispute-policy-v2.3.md` sec. 5 y la salida de la celda 26 del notebook 01 | 60,5 %: `AGENTS.md` sec. 7, `docs/PLAN.md`, `docs/TEAM_BRIEF_COMPLEMENTED.md` y el texto del notebook 01 | 60,4 %, porque la spec toma la salida como fuente | Daniel |
| 2 | ROC AUC sin fuga | 0,497: `reports/ml_full/fraud_risk.md`, `README.md` | 0,50: `AGENTS.md` sec. 7, `docs/technical-discuss-points.md` sec. 5 | 0,497 | Kmilo (TQ-026) |
| 3 | Bins de la búsqueda de señal | 139: notebook 03 | 140: `docs/technical-discuss-points.md` sec. 5, TQ-023 | 139 | Kmilo |
| 4 | AUC con etiqueta sintética | 0,869: notebook 02 | 0,868: `docs/technical-discuss-points.md` sec. 5 | 0,869 | Kmilo |
| 5 | Licencia de IEEE-CIS | Aprobada: `README.md` ("Limitations"), TQ-032, fila "Uso de datos en el despliegue y en los modelos" de `docs/PLAN.md` | Pendiente: respuesta de TQ-026, fila "Modelo de riesgo transferido de IEEE-CIS" de `docs/PLAN.md`, `docs/specs/fraud-risk-model-v1-ieee-cis.md` sec. 7 | Ambas, como contradicción abierta | Daniel, que registró TQ-032, con los mentores |
| 6 | Tamaño del split de desarrollo | 19 casos: `data/eval/dev_cases.jsonl` | 18: texto de TQ-018 y fila del día 3 de `docs/PLAN.md` | 19 | Daniel (TQ-018) |
| 7 | RLS | Activo en cada tabla: `docs/SUPABASE_VERCEL.md` sec. 5.2; SEC-07 de `docs/SECURITY_AUDIT_PLAN.md` | Ninguna migración de `supabase/migrations/` lo activa (`docs/HANDOFF.md` sec. 7.1, punto 4) | Sin RLS | Quien tenga acceso al dashboard de Supabase |
| 8 | Proyectos de Supabase | Dos, dev y demo: `docs/SUPABASE_VERCEL.md` sec. 6.9 | Uno, que también es producción: `docs/HANDOFF.md` sec. 1, `README.md` | Uno | Daniel |
| 9 | Reintentos ante caída del banco | TQ-028 respondida: 2 reintentos acotados | Sin código: `README.md` ("Limitations", "no bounded retries") | Sin reintentos | Daniel (TQ-028) |
| 10 | Clave de deduplicación | `data/README.md`: `customer_id`, `transaction_date`, `amount`, `merchant_name` y la columna `amount_usd_normalized` | `src/data/ingestion.py`: con `currency`, corte al minuto y sin esa columna | El código | Equipo |
| 11 | Peso del bundle | Unos 360 MB: `docs/SUPABASE_VERCEL.md` sec. 6.1, `AGENTS.md` sec. 9 | Unos 377 MB sin E5: la sec. 6.3 del mismo documento | Ambas cifras | Equipo |
| 12 | Pestañas de la consola | Cuatro: `frontend/README.md` | Cinco, con Questions: `frontend/src/Console.tsx` | Cinco | Equipo |
| 13 | `affected_product_id` ajeno | 82 %: celda 4 del notebook 01 | 100 % de los no nulos: `AGENTS.md` sec. 7 | Ambas | Equipo |
| 14 | Canales fuera de Web y App | Las reglas los cubren: `reports/ml/fraud_risk_transfer.md` ("Caveats"), `docs/technical-discuss-points.md` sec. 7 | Nada los califica al servir: spec del modelo sec. 6 y `src/ml/transfer_scorer.py` | El código | Kmilo (TQ-026) |
| 15 | Huérfanos al publicar | En cuarentena: `docs/SUPABASE_VERCEL.md` sec. 4.3, `AGENTS.md` sec. 9 | Solo se cuentan: `src/data/publish_serving.py` | El código | Equipo |
| 16 | Filas del dataset hacia modelos externos | Nunca salen: `AGENTS.md` sec. 8 | El notebook 03 mandó 1.013 transcripciones enmascaradas a Jev (`docs/technical-discuss-points.md` sec. 5) | Ambas (inferido: no rompe la regla 10, son sintéticas) | Equipo |
| 17 | Cifras de los entregables | `docs/deliverables/SUBMISSION_EMAIL.md`: "52.4%, 123/230"; 25,0 / 85,1 ms en "native hardware"; "+94.4%" para una diferencia en puntos. `docs/deliverables/SLIDES_DECK.md`: "+44.0%" y "+24.8%" | `reports/eval_heldout.md`: 52,4 % (131 de 250); `README.md` solo dice "another one" para esa latencia | `reports/` | Quien envía el correo (`docs/HANDOFF.md` sec. 3, A5: Daniel) |

Preguntas abiertas sin respuesta registrada en el repo:

- **TQ-023:** cómo presentar la hipótesis 3 con una etiqueta sin señal. **TQ-025:** si existe un vínculo entre quejas y marcas de fraude. **TQ-002:** fallar o poner en cuarentena una fila sin tasa (el código falla) ([`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json)).
- **Hipótesis 5:** E5 contra BM25 sigue sin medir; la Tarea 4.2 está pendiente (`docs/RAG_IMPLEMENTATION_ROADMAP.md` sec. 6).
- **Modelo de registro:** el PR #45 deja al equipo elegir entre el bundle de 0,817 y el reentrenado de 0,815, y falta decidir cómo llegaría a Vercel ([05](05-modelado.md), sección 2.3).
- **Estado de producción que el repo no registra:** si se aplicó la migración 0005, si el registro público está apagado, si se rotaron las claves del 2-oct y si se borraron los casos de prueba de las personas ([07](07-despliegue.md), secciones 5, 8 y 9).

## 6. Mantenimiento

- **Las cifras salen de `reports/` y de los documentos canónicos**, nunca de `docs/deliverables/*.md`, que tienen errores conocidos (fila 17 de la sección 5).
- **Cuando cambie un reporte**, busque la cifra vieja en toda la carpeta (por ejemplo, `grep -rn "98,1" docs/crisp-dm`). Actualice 00, el archivo de la fase y esta README, y anote el commit y la fecha de la corrida. Si cambia la suite held-out, la cifra es otra versión con otro SHA-256, nunca una edición de la anterior (`CLAUDE.md`, "Gotchas").
- **Lo que solo respalda la auditoría del 4-oct**, una revisión que no está comprometida en el repo, va marcado así. Si esa auditoría se compromete, enlácela; si no, vuelva a verificar esas afirmaciones antes de repetirlas.
- **El estado de producción es una foto del 4-oct:** el commit servido (`d25891e`) y la CI de `main` (776 tests pasados) vienen de `gh api` y `gh run view`. Vuelva a leerlos después de cada merge.
- **Formato.** Español, frases cortas, números con denominador y en formato español (punto de miles, coma decimal), sin rayas largas ni medias, sin emoji y con enlaces relativos solo a archivos que existen. Nunca credenciales, rutas locales absolutas ni el enlace del diccionario de datos: `tests/test_repo_hygiene.py` falla con esos dos últimos.
