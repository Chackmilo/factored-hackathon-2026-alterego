# Iteraciones y decisiones

AlterEgo cambió de rumbo varias veces en once días, y casi siempre porque una medición o una auditoría contradijo el plan. Tres giros pesan más. La etiqueta de fraude del banco no tenía señal, y el modelo pasó a transferirse desde IEEE-CIS. La primera corrida ciega del held-out encontró siete problemas, y seis se arreglaron con tests sin tocar la suite. Y las restricciones de Vercel decidieron qué componente se sirve.

Este capítulo ordena esas iteraciones por fecha y fase CRISP-DM, con su evidencia. Las fechas son las de `git log --date=short` (hora local del autor) y las del registro de decisiones. Los PR se citan por número; su contenido se leyó con `gh pr view`.

## Hoja de ruta: plan contra real

El plan fijó cinco gates hasta el 5 de octubre ([docs/PLAN.md](../PLAN.md), "Hoja de ruta"). Así quedaron:

| Gate | Plan | Real | Evidencia |
| --- | --- | --- | --- |
| G0, decisiones cerradas | 26 sep | Hecho el 26 sep, en una sesión de grilling | `docs/PLAN.md`, registro de decisiones |
| G1, conversación ES de punta a punta | 28 sep | Hecho el 27 sep | [docs/HANDOFF.md](../HANDOFF.md) sec. 1 |
| G2, modelo mejor que el baseline y suite congelada | 30 sep | A medias: suite congelada el 30 sep; el modelo no tiene medición comprometida y faltan las etiquetas humanas | `docs/HANDOFF.md` sec. 1; [06-evaluacion.md](06-evaluacion.md) |
| G3, métricas y URL pública | 2 oct | URL en vivo el 3 oct; el canario contra la pausa de Supabase no existe | `CLAUDE.md`; `docs/PLAN.md`, fila "Despliegue" |
| G4, entrega | 5 oct | Pendiente al 4 oct | `docs/HANDOFF.md` sec. 1 |

El plan también preveía un deploy esqueleto el 28 de septiembre. La configuración de Vercel llegó el 2 de octubre (PR #30). La primera publicación, el 3 de octubre, servía el front, pero todas las rutas de la API daban `FUNCTION_INVOCATION_FAILED` hasta el arreglo del entrypoint (PR #34).

## Línea de tiempo

| Fecha | Fase CRISP-DM | Iteración o decisión | Por qué | Evidencia |
| --- | --- | --- | --- | --- |
| 2026-09-24 | Entendimiento del negocio | El repo arranca con el starter "OmniGuard AI": pipeline de un paso, mocks que siempre tienen éxito | Punto de partida; luego será el baseline de referencia | commit `473249b`; `AGENTS.md` sec. 9 |
| 2026-09-25 | Entendimiento del negocio | `AGENTS.md` fija reglas, métricas y datos del reto | Una sola fuente de reglas para personas y agentes | PR #1 |
| 2026-09-26 | Entendimiento del negocio | Workflow: intake de disputas; se descarta la elegibilidad de crédito | Las quejas tienen la peor resolución en primer contacto | `docs/PLAN.md`, fila "Workflow"; [02-entendimiento-del-negocio.md](02-entendimiento-del-negocio.md) |
| 2026-09-26 | Modelado | Política v2.3 del brief tal cual; `POL-AUT-150` solo marca un candidato a crédito que aprueba un humano | Regla 8: ningún crédito sin humano | `docs/PLAN.md`, filas "Política de disputas" y "Crédito provisional"; en código el 27 sep (commit `8026f39`) |
| 2026-09-26 | Evaluación | Dos baselines: la arquitectura en modo solo reglas, y el pipeline inicial medido tal cual con solo su crash arreglado | Medir el punto de partida; lo inseguro que hace cuenta en el reporte | `docs/PLAN.md`, fila "Baselines"; crash arreglado en el commit `8632e96` (`AGENTS.md` sec. 9) |
| 2026-09-26 | Despliegue | Supabase Auth y Postgres (`bank` de solo lectura, `ops` para escribir) y Vercel Hobby, en lugar de JWT propio, SQLite y Render | `customer_id` sale del token verificado; planes gratis | `docs/PLAN.md`, filas "Identidad", "Base de operación" y "Despliegue"; [docs/SUPABASE_VERCEL.md](../SUPABASE_VERCEL.md) |
| 2026-09-26 | Entendimiento de los datos | `fraud_score` fuera de todo modelo; la ventana se cuenta por día de proceso (desfase de 6 h) | `fraud_score` filtra `is_fraud`; la fecha cruda misfecha cerca del 24 % de las filas | `docs/PLAN.md`, fila "`fraud_score`"; `AGENTS.md` sec. 7 |
| 2026-09-26 | Entendimiento del negocio | Revisión adversarial del plan y revisión tecnológica; sus recomendaciones entran como filas "Propuesta" | Atacar el plan antes de construir | [docs/reviews/](../reviews/) (tres archivos del 26 sep); PR #3 |
| 2026-09-27 | Preparación de los datos | `amount_usd` corregido en silver con columna legada y origen; carga completa 2023 a 2026 en un archivo aparte | 291 vacíos reales en COP y ARS; el modelo necesita toda la historia | TQ-001, TQ-003, TQ-013; `docs/PLAN.md`, fila "Limpieza de `amount_usd`" |
| 2026-09-27 | Modelado | Política v2.3 en código con tests por cláusula; resoluciones P1 a P7 ratificadas ("ratify all") | Reglas 6 y 7: el código decide y verifica | commits `8ef2938` a `8026f39` (rama `feat/dispute-policy-v2.3`); TQ-005 |
| 2026-09-27 | Despliegue | Stack de disputas conectado a la API: orquestador de cinco etapas, ops store y consola | G1: una conversación completa y verificada | commit `3ceeb35`; `CLAUDE.md` ("wired to the API since 27-Sep") |
| 2026-09-27 | Evaluación | Harness con 18 casos de desarrollo y adaptador del baseline; CI con Postgres | Medir desde el primer flujo | commit `fc1ab25`; `AGENTS.md` sec. 9 |
| 2026-09-27 | Modelado | Llega la key de Jev; router Jev o palabras clave con tope de 2 USD por día | Jev estaba en acceso anticipado; ningún test llama al Jev real | TQ-017, TQ-015, TQ-008; `docs/JEV_TYPESAFE_AI.md`; `CLAUDE.md` |
| 2026-09-27 y 28 | Entendimiento de los datos | Modelo sin fuga sobre la historia completa: ROC AUC de test 0,497; quejas y marcas de fraude independientes | Saber si `is_fraud` es un objetivo entrenable | commits `c6a336b`, `b7c1194`, `b4c9e42`; [reports/ml_full/fraud_risk.md](../../reports/ml_full/fraud_risk.md); TQ-023 y TQ-025, sin respuesta |
| 2026-09-29 | Modelado | Se acepta transferir el riesgo desde IEEE-CIS (externo): 19 features desplegables y umbral en el percentil 98 | El banco no tiene objetivo entrenable | TQ-026 (Kmilo); commit `f7c0eb5`; [docs/specs/fraud-risk-model-v1-ieee-cis.md](../specs/fraud-risk-model-v1-ieee-cis.md) |
| 2026-09-29 | Modelado | Confianza de intención por opción, sin sumar intenciones; MLflow para el modelo | Intenciones independientes; tracking del entrenamiento | TQ-024, TQ-021 |
| 2026-09-30 | Evaluación | Held-out de 250 casos congelado con SHA-256, con ataques por la API, fallas inyectadas y kit de etiquetado | Medir antes de ajustar | commit `e726127`; PR #12 |
| 2026-09-30 | Evaluación | Corrida ciega: 68 de 107 resoluciones seguras, 31 de 250 inseguros con el juez original (39 con el actual), 9 crashes; 7 hallazgos | Primera medición sobre casos no vistos | PR #12; [reports/eval_heldout_blind.md](../../reports/eval_heldout_blind.md) |
| 2026-09-30 | Modelado | Seis arreglos, cada uno con su test, sin tocar la suite ni umbrales; la rama de 115 commits entra a `main` de una vez, sin revisión cruzada por decisión de Daniel | Los hallazgos eran bugs reales | PR #13; PR #14 |
| 2026-09-30 | Evaluación | Auditoría v3: 31 hallazgos; el held-out ya no es ciego (AUD-26) y "no es mío" no cuenta como disputa (AUD-28) | Contrastar docs, resultados y código | [auditoría v3](../reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md); PR #15 |
| 2026-09-30 | Modelado | Lote A de la auditoría: "no es mío", varios cargos en un mensaje, UTF-8; resolución segura de 92 a 105 de 107 | AUD-28 explicaba 16 fallos | PR #17 |
| 2026-09-30 y 10-01 | Modelado | Explicador de políticas: corpus de 13 cláusulas con nivel de exposición, BM25, compuerta, ruteo apagado hasta calibrar, benchmark | Responder preguntas de reglas sin decidir nada | TQ-037; PR #18, #20, #21 y #22 |
| 2026-10-01 | Despliegue | Dependencias de runtime separadas del grupo `dev`: de 595 a 358 MB | El límite de la función de Vercel es 500 MB | PR #23; `docs/PLAN.md`, fila "Presupuesto de 500 MB" |
| 2026-10-02 | Modelado | Se mantiene scikit-learn con joblib; E5 queda offline y Vercel sirve BM25 | Quedan tres días; con scikit-learn, E5 no cabe en el bundle | TQ-022; PR #24 |
| 2026-10-02 | Evaluación | La corrida ciega es el resultado held-out (TQ-033); dos denominadores (TQ-034); abstenerse ante un caso de humano es inseguro (TQ-035) | Que la métrica no favorezca al sistema | PR #27; TQ-033 a TQ-035 |
| 2026-10-02 | Despliegue | Explicador encendido con la compuerta calibrada en desarrollo, sabiendo que acierta 36,7 % (11 de 30) de las acciones en test | Decisión de Daniel, con los límites declarados | PR #28; [reports/rag_benchmark.md](../../reports/rag_benchmark.md) |
| 2026-10-02 | Despliegue | Login con Supabase Auth, `APP_ENV` que falla cerrado y configuración de Vercel | AUD-02: la URL pública no tenía login | PR #29; PR #30 |
| 2026-10-03 | Despliegue | Conexiones sin prepared statements y entrypoint arreglado (todas las rutas de la API daban `FUNCTION_INVOCATION_FAILED`); URL en vivo | Fallas que solo aparecen en Vercel y su pooler | PR #31; PR #34; `CLAUDE.md` |
| 2026-10-03 | Modelado | El handoff dice "riesgo no calificado" en vez de 0,00; el bloqueo solo toma una tarjeta propia y activa | No mostrar un puntaje que no existe | PR #32 |
| 2026-10-03 | Modelado | Respuestas de Claude: tareas 1 y 2 de 7 (guarda y redactor), sin conectar | Avanzar la redacción con marcadores | PR #36; [docs/specs/claude-replies-v1.md](../specs/claude-replies-v1.md) |
| 2026-10-03 | Entendimiento del negocio | El equipo queda en dos personas; Kmilo sigue solo con lo pendiente | Reasignar el trabajo antes de la entrega | PR #37 y #38; `docs/HANDOFF.md` |
| 2026-10-03 (noche) | Evaluación | Kmilo mergea #39 a #48: bloqueo con varias tarjetas (#39), TQ-034 y TQ-035 en código con los reportes held-out comprometidos (#42), harness con modelo (#44), features de servicio (#45), pregunta de reglas tras un saludo (#46), gitleaks limpio (#41) | Cerrar las tareas A4, B1 y B4 del handoff | PR #39 a #48; `main` en `9efb497`; `docs/HANDOFF.md` sec. 7.2 |
| 2026-10-03 | Despliegue | Ninguno de esos merges se despliega | Con el repo privado, Vercel Hobby solo despliega commits del dueño | `docs/HANDOFF.md`, nota del 4 oct; `AGENTS.md` sec. 9 |
| 2026-10-04 | Despliegue | Higiene antes de publicar el repo; merges desde la web que sí despliegan | Repo público para la entrega | PR #49 |
| 2026-10-04 | Evaluación | Reportes regenerados en `9efb497`: 105 de 107, 20 de 250 inseguros, 221 de 250 exactos | Cifras finales del README | PR #50; commit `4762ddc` |
| 2026-10-04 | Evaluación | Sin kappa ni etiquetas humanas (TQ-018); reportes en el repo (TQ-019); sin OpenTelemetry (TQ-036) | Plazo de entrega (TQ-018); peso del bundle de Vercel (TQ-036) | PR #51; `docs/HANDOFF.md` sec. 7.3 |
| 2026-10-04 | Despliegue | Se corrige la razón de producción sin modelo: el `.joblib` está ignorado y Vercel construye desde GitHub, no "cero alucinaciones" | La afirmación del PR #51 era inexacta | commit `a18f045` |
| 2026-10-04 | Evaluación | CI rota en `main` tras el PR #51 (tests que suponían TQ-019 abierta), arreglada | Tests atados a un id de pregunta | PR #52 |
| 2026-10-04 | Despliegue | Entregables y diagramas en `docs/deliverables/` | Material de la entrega | PR #53 |

### Estado al cierre (4 de octubre)

Comprobado al escribir este capítulo con `git`, `gh` y el código:

- **`main` y CI.** `main` está en `c71cc09`. Su CI terminó en "success" con 776 tests pasados, 1 omitido y 6 deseleccionados (`gh run view`).
- **Producción.** Sirve `d25891e`, el merge del PR #53: su deployment de GitHub dice "Deployment has completed", y el de `c71cc09`, un commit directo, "Deployment was blocked" (`gh api`, deployments). `/health` devuelve `status`, `app`, `version` y `env` ([src/api/app.py](../../src/api/app.py)); `docs/HANDOFF.md` sec. 7.3 registra la prueba de humo con "AlterEgo dispute intake". Las rutas de desarrollo responden 404 fuera de `APP_ENV` development o test (`CLAUDE.md`).
- **Casos de demo.** Cada caso que la app abre en producción cuenta en las quejas de 90 días del cliente: `ops.v_customer_policy_facts` cuenta los casos de `ops` creados desde el día de negocio menos 90, y las filas de `ops` llevan fecha de reloj (`CLAUDE.md`, Gotchas). `POL-AUT-150` exige cero quejas en 90 días (`src/rules/dispute_policy.py`), y un cargo con caso abierto recibe `DUPLICATE_CASE_PREVENTED` (`src/orchestrator/dispute_orchestrator.py`). Inferido: una persona de demo que ya abrió un caso deja de mostrar el candidato a crédito hasta que se borre ese caso.
- **Repo.** `Chackmilo/Factored_Hackaton` es privado (`gh repo view`). El PR #49 quitó de los docs el enlace al diccionario de datos, cuyo PDF trae las keys de AWS del bucket, pero dejó el enlace en la historia: "Rewriting history is not worth it before the deadline". Inferido: si el repo se publica con su historia, el enlace queda público. El nombre decidido para el repo público es `factored-hackathon-2026-alterego` (`docs/PLAN.md`, fila "Nombre del equipo y repo").
- **Dos comportamientos que la suite no ve** (inferidos de la lectura del código). Una segunda pregunta de política tras un saludo puede ir al flujo de disputa: `_disputed_earlier` cuenta la primera pregunta si nombra un "cargo". El idioma de la conversación queda fijo al salir del estado `new` (`src/orchestrator/dispute_orchestrator.py:171`).
- **Contradicción abierta.** README ("Limitations"), TQ-032 y la fila "Uso de datos en el despliegue y en los modelos" de `docs/PLAN.md` dicen que los mentores aprobaron el uso de IEEE-CIS. La respuesta de TQ-026, la fila "Modelo de riesgo transferido de IEEE-CIS" de `docs/PLAN.md` y la spec del modelo dicen que la licencia sigue pendiente.
- **Entregables con errores.** `docs/deliverables/SUBMISSION_EMAIL.md` cita "52.4%, 123/230" (el reporte dice 131 de 250) y atribuye 25,0 / 85,1 ms a hardware nativo; el README solo dice que es otra máquina, en un reporte reemplazado ([06-evaluacion.md](06-evaluacion.md), sección 3).

## Decisiones tomadas y no ejecutadas

Varias preguntas quedaron respondidas sin código. Conviene saberlo antes de leer una respuesta como un hecho del sistema:

| Pregunta | Respuesta | Estado en el código | Evidencia |
| --- | --- | --- | --- |
| TQ-028, caída del banco | Mantener el handoff, sumar 2 reintentos acotados y pasar a un humano la oferta de bloqueo perdida | Sin reintentos; si falla la lista de tarjetas, la oferta solo se pierde | README, "Limitations" ("no bounded retries"); `CLAUDE.md` |
| TQ-029, reporte de pérdida sin cargo | Una pregunta propia para esos reportes y otro texto tras el no | Sin código: es un cambio de texto de la política y pide actualizar la spec | `docs/HANDOFF.md` sec. 3, C; TQ-029 |
| TQ-031, palabras de robo y angustia | Comparar palabras completas | Siguen las subcadenas ("aprobaron" contiene "robaron") | `docs/HANDOFF.md`; `src/rules/dispute_policy.py`; [05-modelado.md](05-modelado.md) sec. 1 |
| TQ-026, cherry-picking de variables | Elegir entre unas 400 variables de la competencia | El modelo usa solo las 19 de `DEPLOYABLE_V1`; inferido: el proceso no empezó (sin código en `src/`) | `src/ml/feature_contract.py`; `reports/ml/ieee_cis_feature_importance.md` |
| Canario contra la pausa de Supabase | Cron doble con una persona dedicada | No existe | `docs/PLAN.md`, filas "Pausa de Supabase" y "Despliegue" |
| Etiquetado humano con kappa | 4 personas, 50 casos dobles | Planillas vacías; cerrada como limitación | TQ-018 |

## Lecciones

1. **Commitear la corrida ciega el mismo día.** El reporte de la corrida ciega no entró al repo hasta el PR #42 del 3 de octubre; hasta entonces su tabla vivía en el cuerpo del PR #12. La cifra que circulaba después, 86,0 %, ya venía de arreglos elegidos con la misma suite. La auditoría v3 lo marcó como bloqueante (AUD-26) y el equipo tuvo que decidir qué cifra presentar (TQ-033). Evidencia: PR #12, PR #42, [reports/eval_heldout_blind.md](../../reports/eval_heldout_blind.md).

2. **Revisar la etiqueta antes de modelar.** En dos días se vio que `fraud_score` filtra `is_fraud` y que `is_fraud` no tiene señal (ROC AUC 0,497 sobre 1.555.062 filas de test). Eso movió el modelo a datos externos. El giro fue rápido, pero dejó abierta la licencia de IEEE-CIS, y hoy las fuentes del repo se contradicen. Evidencia: [reports/ml_full/fraud_risk.md](../../reports/ml_full/fraud_risk.md), TQ-023, TQ-026, TQ-032.

3. **Un modelo sin artefacto desplegable no llega al cliente.** El harness no cargó el scorer hasta el PR #44 (AUD-29). El archivo del modelo está en `.gitignore` y Vercel construye desde GitHub, así que producción corre sin él. Las cifras con modelo existen solo en los cuerpos de los PR #44 y #45. La forma de entregar el artefacto debió decidirse al elegir el modelo. Evidencia: PR #44, PR #45, commit `a18f045`.

4. **Desplegar temprano.** El deploy esqueleto del 28 de septiembre no ocurrió. El despliegue del 2 y 3 de octubre trajo problemas que ningún test local mostraba: el pooler de transacciones no admite prepared statements (anticipado y arreglado antes de fallar, PR #31), el entrypoint que Vercel carga por ruta de archivo tumbó todas las rutas de la API (PR #34), y el plan Hobby bloqueó los merges de otro colaborador (PR #49). El límite de 500 MB además decidió BM25 sobre E5. Evidencia: PR #31, PR #34, PR #49, TQ-022.

5. **Cada afirmación necesita su archivo, y cada merge su CI.** El PR #51 dio una razón inexacta para correr sin modelo, corregida en `a18f045`. El mismo PR rompió la CI de `main` (PR #52). El correo de entrega del PR #53 trae dos cifras mal atribuidas. La auditoría v3 halló que 4 de los 25 hallazgos de la v2 eran falsos. Evidencia: commit `a18f045`, PR #52, PR #53, auditoría v3 sec. 1.

6. **Las etiquetas de diseño guardan el comportamiento viejo.** Seis etiquetas del held-out premiaban bloquear la primera tarjeta activa, y el arreglo correcto del PR #39 bajó la exactitud de 227 a 221. Con etiquetas humanas, esas expectativas se habrían corregido en una versión nueva de la suite; el equipo, ya de dos personas, no las produjo. Evidencia: README ("Results"), PR #39, TQ-018, `docs/HANDOFF.md` sec. 7.1.

## Fuentes

- `git log --first-parent main --date=short` y `git log --all` (commits citados; los del 27 al 30 sep viven en la rama `feat/dispute-policy-v2.3`)
- `gh pr list --state all -L 60` y cuerpos de los PR #12, #13, #14, #17, #28, #31, #34, #42, #44, #45, #49 a #53 (`gh pr view`); `gh run view` y `gh api` (deployments) para el estado al cierre
- [docs/PLAN.md](../PLAN.md): registro de decisiones y hoja de ruta
- [data/fixtures/team_questions.json](../../data/fixtures/team_questions.json): TQ-001, TQ-003, TQ-005, TQ-008, TQ-013, TQ-015, TQ-017, TQ-018, TQ-019, TQ-021 a TQ-028, TQ-031 a TQ-037
- [docs/reviews/](../reviews/): revisiones del 26 sep, auditoría parcial del 29 sep y auditoría v3 del 30 sep
- [docs/HANDOFF.md](../HANDOFF.md) secs. 1 y 7
- [README.md](../../README.md) ("Results", "Limitations"); [AGENTS.md](../../AGENTS.md) secs. 7 y 9; [CLAUDE.md](../../CLAUDE.md)
- [reports/eval_heldout.md](../../reports/eval_heldout.md), [reports/eval_heldout_blind.md](../../reports/eval_heldout_blind.md), [reports/ml_full/fraud_risk.md](../../reports/ml_full/fraud_risk.md), [reports/rag_benchmark.md](../../reports/rag_benchmark.md)
- Código: `src/api/app.py`, `src/orchestrator/dispute_orchestrator.py`, `src/rules/dispute_policy.py`, `src/ml/feature_contract.py`
