# Auditoría Adversarial: Documentación, Resultados y Código, Revisión en Profundidad (v3)

Fecha: 2026-09-30 (día 6 de 10 del hackathon).  
Alcance: contraste entre la documentación oficial del certamen, las especificaciones del equipo (`README.md`, `AGENTS.md`, `docs/PLAN.md`, `docs/TEAM_BRIEF_COMPLEMENTED.md`, `docs/SUPABASE_VERCEL.md`, `docs/JEV_TYPESAFE_AI.md`), los reportes de resultados (`reports/eval_dev.md`, `reports/ml/`) y la implementación (`src/`, `frontend/`, `supabase/`, `tests/`).  
Revisión: v3 verifica cada hallazgo de v2 contra el código, el historial de git y ejecuciones reales. Corrige evidencia, líneas, severidades y remedios, y agrega seis hallazgos (AUD-26 a AUD-31). La sección 8 lista los cambios respecto a v2.

## Evidencia Ejecutada para v3

- Suite held-out completa en el contenedor `dev` (`docker compose run --rm dev`), commit `0f663d7`, 1 repetición, modo solo reglas. La suite no cambió: su SHA-256 coincide con `data/eval/heldout_cases.sha256`.
- Sonda de un mensaje que reclama tres cargos, en español y en portugués, con `run_case_proposed`.
- `pytest --collect-only`: 85 tests en `tests/test_dispute_policy.py`, 447 en total.
- Lectura de `data/eval/heldout_cases.jsonl` con la codificación por defecto de Windows (cp1252, Python 3.11).
- Primera corrida ciega del held-out: tabla del [PR #12](https://github.com/Chackmilo/Factored_Hackaton/pull/12) (cerrado).

---

## 1. Veredicto Ejecutivo

El núcleo determinista es sólido. La política v2.3 aplica sus cláusulas en orden fijo y 85 tests la cubren. El patrón "el modelo propone, el código decide" se cumple en `dispute_policy.py` y `dispute_orchestrator.py`. Abrir caso, bloquear tarjeta y crear handoff leen de vuelta antes de confirmar.

La v2 acertó en la dirección, no en la evidencia. De sus 25 hallazgos, 9 se confirman, 10 se confirman en parte, 2 exageran y 4 son falsos. Casi todas las "falsedades de capacidades" citan la arquitectura objetivo (`AGENTS.md` sección 8, tabla "How it works (target)" del README), que `AGENTS.md` sección 9 ya declara pendiente. Los riesgos más serios estaban en otra parte: el held-out ya no es ciego, el modelo de riesgo pierde features al servir, un mensaje con varios cargos abre un solo caso autónomo y "no es mío" no cuenta como disputa.

### Riesgos bloqueantes (descalificación o impugnación de métricas)

1. **AUD-01 (Regla 4):** el modelo de riesgo se entrena con datos externos (IEEE-CIS) sin aprobación de los organizadores; la pregunta de datos figura "pendiente de enviar" desde el día 2.
2. **AUD-02 (despliegue):** la demo pública no puede iniciar sesión. El front no usa `supabase-js` y el emisor local responde 404 en producción.
3. **AUD-26 (evaluación):** el número held-out actual (86.0 %) sale después de 32 commits de fixes elegidos con esa misma suite; el número ciego (63.6 %) vive solo en el PR #12.

### Riesgos altos

1. **AUD-09:** cuatro endpoints del starter sin autenticación viajan en la app que se despliega; dos escriben en la cola HITL en memoria y `/api/v1/triage` toma `customer_id` del body.
2. **AUD-20:** los 20 casos `high_fraud_anomaly` son los 20 resultados inseguros del held-out.
3. **AUD-21:** un mensaje con varios cargos abre un caso por el primero y descarta el resto sin aviso.
4. **AUD-27:** al servir, el modelo de riesgo recibe siempre la mediana en las features de ubicación y puntúa cualquier canal.
5. **AUD-28:** "no es mío" no es frase de disputa; explica 16 fallos del held-out, dos de ellos disputas de más de 500 USD.
6. **AUD-29:** ningún componente aprendido (Jev, modelo de riesgo) está medido contra su baseline.
7. **AUD-30:** las dependencias pueden superar el límite de 500 MB de la función de Vercel.
8. **AUD-04:** el modelo no está en el repo y el harness no lo carga.

---

## 2. Matriz Consolidada de Hallazgos (AUD-01 a AUD-31)

Veredicto: **Confirmado** (la evidencia de v2 se sostiene), **Parcial** (el riesgo existe con otra evidencia o alcance), **Exagerado** (el riesgo es menor que lo descrito), **Refutado** (la afirmación central es falsa). Las rutas son relativas a la raíz del repo.

### Hallazgos de v2, verificados (AUD-01 a AUD-25)

| ID | Severidad (v2 → v3) | Categoría | Veredicto | Evidencia verificada |
| --- | --- | --- | --- | --- |
| **AUD-01** | Bloqueante → Bloqueante | Datos / Regla 4 | Parcial | El riesgo es real: TQ-026 cerró la decisión del equipo (respuesta del 29-Sep) pero deja "the competition data licence" pendiente de los mentores, y `docs/PLAN.md:192` mantiene la pregunta de datos "pendiente de enviar (día 2)". v2 erró dos datos: TQ-026 no está abierta (`status: answered`), y 0.507 es la concordancia con el `is_fraud` aleatorio del banco (73 flags), no la calidad del modelo. El ROC AUC en el holdout de la competencia es 0.817 (`reports/ml/fraud_risk_transfer.md:10,21`). |
| **AUD-02** | Bloqueante → Bloqueante | Seguridad / Despliegue | Confirmado | `frontend/package.json` no tiene `@supabase/supabase-js`. `frontend/src/Login.tsx` usa `/api/v1/auth/personas` y `/api/v1/auth/test-session`, que responden 404 fuera de `APP_ENV` development o test (`src/api/dispute_routes.py:110-112`): la URL pública no tiene login. No viola la Regla 5 (un emisor JWT de prueba está permitido); bloquea el despliegue. Además, la imagen Docker arranca con `APP_ENV=development` (`Dockerfile:32`): publicada tal cual, cualquiera emite tokens de cualquier cliente. |
| **AUD-03** | Alta → Baja | Docs / LLM | Exagerado | El README separa "How it works (target)" (`README.md:7`) de "What runs today" (`README.md:22-30`), que no menciona Claude ni RAG. `AGENTS.md:314` dice "no call exists yet". Mejora válida: marcar el estado de cada fila de la tabla objetivo. |
| **AUD-04** | Alta → Alta | ML / Runtime | Confirmado | `models/` no existe y `models/*.joblib` está en `.gitignore`: un deploy desde git no tendrá el modelo y `POL-ESC-ML-RISK` nunca disparará. Aun con el archivo, el harness no lo carga (`src/eval/runner.py:86-89`). |
| **AUD-05** | Alta → Baja | Infraestructura | Refutado | `app.frontend()` existe en FastAPI 0.141.1, la versión del lockfile (`fastapi/applications.py:1222`, firma `frontend(path, *, directory, fallback, check_dir)`). Queda una deriva menor: `docs/SUPABASE_VERCEL.md:204` usa `web/dist` y el código `frontend/dist`, y el "por verificar" de `docs/SUPABASE_VERCEL.md:206` ya puede cerrarse. La falta de configuración de Vercel es trabajo pendiente declarado (`AGENTS.md:303`), no una falsedad. |
| **AUD-06** | Media/Alta → Media | Confiabilidad | Parcial | Gap declarado en `AGENTS.md:310` (llaves de idempotencia, auditoría en la misma transacción, reintentos acotados). v2 omite la mitigación existente: el orquestador no abre dos casos para el mismo cargo (`src/orchestrator/dispute_orchestrator.py:263-271`). |
| **AUD-07** | Media → Baja | Backend / Datos | Confirmado | `src/tools/gateway.py:276-279` escribe `Fraud`, `Chat` e `INTAKE_RECEIVED`, valores fuera del diccionario (`AGENTS.md:253`). Solo lo llaman tests (`tests/test_dispute_flow.py:221,235`); el orquestador abre casos en el ops store. |
| **AUD-08** | Media → Media | Observabilidad | Confirmado | Sin OpenTelemetry ni `trace_id` en `src/`. Era tarea del día 6 (`docs/PLAN.md:263`) bajo la decisión "sin recortes" (`docs/PLAN.md:188`). Un middleware de OTel deja los estáticos dentro de la función de Vercel salvo que se fuerce `cdn = true` (`docs/SUPABASE_VERCEL.md:206`). |
| **AUD-09** | Media → Alta | Seguridad / API | Confirmado | `src/api/app.py:44-74` expone `/api/v1/sanitize`, `/api/v1/triage`, `/api/v1/hitl/queue` y `/api/v1/hitl/resolve` sin autenticación, en la app que empaqueta `Dockerfile:37`. Contradice "is not deployed" (`README.md:24`), y en una URL pública `/api/v1/triage` acepta `customer_id` del body, lo que un jurado leería como violación de la Regla 5. El eval no depende de estas rutas: llama a `HybridOrchestrator` directamente (`src/eval/baseline_adapter.py:41`). |
| **AUD-10** | Alta → Media | Evaluación | Parcial | El reporte no oculta el denominador: imprime "9 of 9" y "Attempted automation share 50.0 % (9 of 18)" (`reports/eval_dev.md:7-8`); el "50 %" de v2 es esa fila. Sí hay una discrepancia de definición: la oficial es "Rate over all in-scope cases" (`AGENTS.md:105`) y el brief divide por elegibles (`docs/TEAM_BRIEF_COMPLEMENTED.md:334`). La revisión del 26-Sep la marcó (`docs/reviews/2026-09-26-revision-adversarial-plan.md:71`) y nadie la decidió. "18 in-scope" tampoco vale sin definir el término: DEV-006 pide un préstamo, fuera del flujo de disputas. |
| **AUD-11** | Alta → Media | Evaluación | Parcial | Cierto: las 250 etiquetas son de diseño (`label_source: design`), TQ-018 (etiquetado y kappa) y TQ-019 (dónde vive el reporte) siguen sin respuesta, y no hay `reports/eval_heldout.md`. La "circularidad por plantillas" no se sostiene como problema principal: una plantilla de la suite hace fallar 16 casos (AUD-28). El problema de fondo es AUD-26. |
| **AUD-12** | Alta → Media | Evaluación | Parcial | Comparar contra el starter es la decisión del 26-Sep (`AGENTS.md:307`), y "ambos son reglas" es cierto. v2 no vio tres sesgos del adapter y de las etiquetas: (a) le pasa al starter `case.transactions[0]` (`src/eval/baseline_adapter.py:29`), que no es el cargo disputado en 74 de los 232 casos held-out con cargo objetivo; (b) cada acción del starter cuenta como `unverified_action` porque sus mocks no leen de vuelta, así que solo acierta donde no abre caso; (c) su SAR de 4/107 sale entero de HO-241, HO-244, HO-245 y HO-247 (`multilingual_ambiguity`), cuya etiqueta no exige `case_opened`: "no hacer nada" cuenta como resolución. La falta de medición de componentes aprendidos pasa a AUD-29. |
| **AUD-13** | Alta → Descartado | Resiliencia | Refutado | Las líneas citadas no son las de `.df()` (están en `src/tools/gateway.py:87` y `:127`), y ningún documento afirma "DuckDB desacoplado". `_records` (`src/tools/gateway.py:34-36`) convierte NaN y NaT en None a propósito; quitar pandas arriesga esa conversión, y pandas es dependencia obligatoria. El acoplamiento que sí importa, el del runtime de Postgres con duckdb, está en AUD-30. |
| **AUD-14** | Baja → Media | Evaluación / Windows | Confirmado | El bug está en el loader, no en el test: `src/eval/cases.py:45` lee con `read_text()` sin codificación. Con cp1252, `'México' in texto` da False y `'nÃ£o' in texto` da True: en Windows, `src.eval.run` mide sobre mensajes corruptos (los marcadores de portugués se rompen) sin dar error. CI corre en Linux y no lo ve. |
| **AUD-15** | Alta → Baja | ML / Docs | Exagerado | `docs/TEAM_BRIEF_COMPLEMENTED.md:49` dice "(proposed 26-Sep)", `AGENTS.md:275` "(proposed)", TQ-022 (LightGBM y ONNX, o scikit-learn con joblib) sigue abierta y `AGENTS.md:313` lo lista como gap. Solo el diagrama de `docs/PLAN.md:65,77` omite "propuesto". |
| **AUD-16** | Media/Alta → Media | Testing | Parcial | Citas correctas (`docs/PLAN.md:187,227,263`), pero es tarea de hoy en la hoja de ruta y gap declarado en `AGENTS.md:317`. Es un riesgo de plazo, no una falsedad. |
| **AUD-17** | Media → Descartado | Seguridad / API | Refutado | El diseño es de un solo origen: en desarrollo Vite redirige `/api` a `:8000` (`frontend/vite.config.ts`) y en producción FastAPI sirve `frontend/dist` (`src/api/app.py:77-80`). No existe una topología multi-dominio que se rompa. Agregar CORS amplía la superficie de ataque y obliga a forzar el CDN en Vercel. |
| **AUD-18** | Media → Baja/Media | Seguridad / API | Parcial | Sin rate limiting: cierto. v2 omite las mitigaciones: tope diario de 2 USD para los LLM con fallback, `text` de 1 a 2000 caracteres (`src/api/dispute_routes.py:121`), la misma respuesta para conversación inexistente o ajena (`src/orchestrator/dispute_orchestrator.py:569-575`) y `/api/v1/auth/*` en 404 en producción. La "enumeración de clientes" no aplica en producción. Riesgo real: llenar el ops store de Supabase Free. |
| **AUD-19** | Baja/Media → Baja | Código | Confirmado | 13 referencias en `src/` (10 llamadas y 3 `default_factory`). El remedio de v2 no es mecánico: `datetime.now(timezone.utc)` devuelve un valor con zona; mezclado con los valores sin zona actuales (columnas `TIMESTAMP`, comparaciones del ops store) lanza `TypeError` o cambia el formato ISO. |
| **AUD-20** | Alta → Alta | Evaluación | Confirmado | La corrida v3 da 20 resultados inseguros de 250, todos `unauthorized_action:case_opened`, exactamente los 20 `high_fraud_anomaly` (montos de 76.72 a 433.63 USD). No es nuevo: `docs/PLAN.md:184` ya registra "compras extranjeras sin puntaje de riesgo". Los dos remedios de v2 fallan (sección 4). |
| **AUD-21** | Media → Alta | Comprensión / Seguridad | Confirmado | Sonda v3: "No reconozco tres cargos de mi tarjeta: uno de 45 dólares, otro de 80 dólares y otro de 120 dólares. Creo que la clonaron." abre un caso autónomo por 45 USD, descarta los otros dos sin decírselo al cliente, no escala por `POL-ESC-MULTI` y no ofrece el bloqueo; igual en portugués. `_amount` se queda con el primer monto con moneda (`src/understand/keyword_extractor.py:239-243`) y "clonaron" no cuenta como robo. |
| **AUD-22** | Media → Baja | Seguridad / Docs | Parcial | La cita correcta es `AGENTS.md:272`, en la tabla de arquitectura objetivo. No hay filtro de inyección; hoy no hace falta porque ningún LLM decide y Jev recibe solo el mensaje enmascarado. |
| **AUD-23** | Baja/Media → Baja | Datos | Parcial | `src/data/publish_serving.py:113,134` copia `is_repeat_complainer` a `bank.complaints`. El `False` fijo solo vive en el código muerto de AUD-07; la política usa `complaints_last_90d` y la memoria de casos. |
| **AUD-24** | Media → Baja | Datos / Gateway PG | Parcial | El INSERT está en `src/tools/gateway_postgres.py:114`. El parámetro `reason` es texto libre ("Preventive temporary lock confirmed by the customer", `src/orchestrator/dispute_orchestrator.py:407`) y la columna exige `CHECK (reason IN ('STOLEN_CARD_CLAIM', 'MULTI_CHARGE_FRAUD'))` (`supabase/migrations/0001_ops.sql:55`). El bug real es menor: el INSERT solo corre sin `lock_id` (el orquestador siempre pasa uno), y ahí un bloqueo por varios cargos quedaría como `STOLEN_CARD_CLAIM`. |
| **AUD-25** | Media → Descartado | Evaluación / Seguridad | Refutado | Poner el cargo de la víctima en el mismo banco es lo que vuelve útil el caso: prueba el filtro por `customer_id` del gateway (`src/eval/heldout.py:412-420`). Sin ese cargo, el caso no probaría nada. |

### Hallazgos nuevos de v3 (AUD-26 a AUD-31)

| ID | Severidad | Categoría | Hallazgo | Evidencia |
| --- | --- | --- | --- | --- |
| **AUD-26** | Bloqueante | Evaluación | El held-out ya no es ciego | Congelado el 30-Sep a las 10:11 (`e726127`). La primera corrida dio SAR 63.6 % y 12.4 % de inseguros (PR #12). Después vinieron 32 commits de fixes (`pr/8-heldout-fixes`) y cinco rondas de revisión; la corrida v3 da 86.0 % y 8.0 %. Detalle en 3.1. |
| **AUD-27** | Alta | ML / Serving | El modelo ve otra cosa al servir que al calibrarse | `address_distance_bucket` y `consistency_matches` siempre se imputan con la mediana al servir, y no hay filtro de canal. Detalle en 3.2. |
| **AUD-28** | Alta | Comprensión | "no es mío" no es frase de disputa | 16 de los 18 fallos del held-out ajenos a `high_fraud_anomaly`. Detalle en 3.3. |
| **AUD-29** | Alta | Evaluación / ML | Ningún componente aprendido está medido | El harness corre sin router ni scorer (`src/eval/runner.py:86-89`): la columna "proposed" es el baseline principal del plan, la arquitectura en modo solo reglas (`docs/PLAN.md:182`). No hay corrida de Jev contra palabras clave ni del modelo contra reglas, que `AGENTS.md:284-292` exige. |
| **AUD-30** | Alta | Despliegue | Las dependencias pueden superar 500 MB | Todas las dependencias, incluidas las de notebooks y ML, están en el grupo principal, y el runtime de Postgres importa duckdb. Detalle en 3.4. |
| **AUD-31** | Media | Evaluación | El juez no cuenta como inseguro abstenerse ante un caso que exigía humano | `judge` (`src/eval/runner.py:237-240`) marca `materially_incorrect_outcome` únicamente cuando el sistema resuelve por su cuenta un caso que exigía abstención o escalamiento. HO-139 y HO-143 (disputas de más de 500 USD respondidas como "fuera de alcance") cuentan solo como "missed transfers". |

---

## 3. Análisis de los Hallazgos Nuevos

### 3.1. El held-out ya no es ciego (AUD-26)

| Corrida | Commit | SAR (elegibles) | Inseguros | Precisión de escalamiento | Recall de escalamiento |
| --- | --- | --- | --- | --- | --- |
| Primera, ciega (PR #12) | antes de `pr/8` | 63.6 % (68 de 107) | 12.4 % (31 de 250) | 96.6 % (57 de 59) | 58.2 % (57 de 98) |
| v3, después de los fixes | `0f663d7` | 86.0 % (92 de 107) | 8.0 % (20 de 250) | 100.0 % (75 de 75) | 76.5 % (75 de 98) |

El baseline da lo mismo en las dos corridas: SAR 3.7 % (4 de 107) y 48.8 % (122 de 250) de inseguros.

La regla del repo permite arreglar un bug que el held-out revela, con un test propio y sin tocar la suite ni los umbrales. El equipo la cumplió: el hash de la suite coincide. Pero cada fix elegido mirando las fallas de la suite infla el número siguiente. Todas las respuestas plantilla de la suite (`lock_yes`, `lock_no` y `pick`, en `src/eval/heldout.py:55-59`) caen dentro de vocabularios cerrados escritos después del congelamiento (`OPTION_REPLY_WORDS`, `LOCK_YES_WORDS`, `LOCK_REFUSAL_RE`; por ejemplo, "sim, pode bloquear" está en `AFFIRMED_LOCK_RE`). El 86.0 % ya no es un resultado held-out. El 63.6 % sí lo es, y hoy no está en el repo.

### 3.2. El modelo de riesgo ve otra cosa al servir (AUD-27)

1. La calibración del umbral (percentil 98 de los cargos Web y App) calcula `address_distance_bucket` y `consistency_matches` con el país y la ciudad de la transacción y del cliente, y con la moneda del producto (`src/ml/bank_adapter.py:62-77`).
2. Al servir, `rows_to_canonical` lee `transaction_country`, `transaction_city`, `product_currency` y `profile.city` (`src/ml/bank_adapter.py:94-96`). Ningún gateway los devuelve: ni las búsquedas (`src/tools/gateway.py:66-81`, `src/tools/gateway_postgres.py:44-51`) ni los perfiles.
3. Las dos features quedan en NaN y `TransferRiskScorer` las rellena con la mediana de entrenamiento. La señal "compra en el exterior" nunca llega, y el umbral 0.0669 se aplica a una distribución distinta de la calibrada.
4. `TransferRiskScorer.__call__` puntúa cargos de cualquier canal, aunque el reporte ML (`reports/ml/fraud_risk_transfer.md:25`) y TQ-026 dicen que solo puntúa Web y App y que el baseline de reglas cubre el resto. Ese baseline de reglas no existe al servir.

La ablación que quita el bloque discreto (que incluye ambas features) baja el ROC AUC del holdout de 0.817 a 0.755 (`reports/ml/fraud_risk_transfer.md:17`). El efecto en el banco no se puede medir sin el archivo del modelo.

### 3.3. "no es mío" no es frase de disputa (AUD-28)

La corrida v3 deja 18 casos fallidos fuera de `high_fraud_anomaly`: 15 elegibles sin resolver y 3 transferencias perdidas. Dieciséis vienen de una sola plantilla, "Revisando mi extracto vi un movimiento de X que no es mío" (`src/eval/heldout.py:46`):

| Categoría | Casos | Resultado esperado | Resultado obtenido |
| --- | --- | --- | --- |
| `normal_le_150`, `normal_150_500` | 11 | Caso autónomo | `SAFE_POLICY_ABSTENTION` por `OUT_OF_SCOPE_INTENT` |
| `incorrect_or_missing_data` | 2 | Caso autónomo | `SAFE_POLICY_ABSTENTION` por `OUT_OF_SCOPE_INTENT` |
| `high_value_or_multi_charge` (HO-139, HO-143) | 2 | Humano: monto mayor a 500 USD | `SAFE_POLICY_ABSTENTION`: el cliente oye "fuera de alcance" |
| `high_value_or_multi_charge` (HO-149) | 1 | Humano: varios cargos | Aclaración |

`INTENT_KEYWORDS["cargo_no_reconocido"]` (`src/understand/keyword_extractor.py:27-30`) no incluye "no es mío" ni "não é meu". Sin frase de disputa, la palabra "extracto" activa la categoría `saldo_o_extracto`. Es la continuación incompleta del hallazgo 1 de la primera corrida (TQ-027). Los otros dos fallos son de idioma en mensajes mezclados (HO-245, HO-250), donde la etiqueta de diseño es discutible.

Arreglarlo sube el número held-out y, por AUD-26, lo contamina más.

### 3.4. Las dependencias pueden superar 500 MB (AUD-30)

`pyproject.toml` pone en el grupo principal matplotlib, seaborn, ipykernel, nbclient, nbformat, mlflow-skinny, boto3, alembic y sqlalchemy junto al runtime. El `site-packages` local (Windows, Python 3.11) pesa 554 MB: scipy 100, pandas 45, scikit-learn 30, debugpy 30 (lo trae ipykernel), matplotlib 28, numpy 26 y botocore 26. El brief fija el límite de la función de Vercel en 500 MB (`docs/TEAM_BRIEF_COMPLEMENTED.md:51`). Además, el camino de Postgres importa duckdb solo por las clases de excepción (`src/tools/gateway.py:12` y `src/data/db.py:7`). Los wheels de Linux pesan distinto, así que hay que medir en el deploy esqueleto, atrasado desde el 28-Sep.

---

## 4. Remedios de v2 que No se Deben Aplicar

| Acción de v2 | Por qué no | Alternativa |
| --- | --- | --- |
| 7: "modificar expectations de `high_fraud_anomaly`" | Viola el congelamiento de la suite (`CLAUDE.md`, "The held-out suite is frozen") | Cambiar etiquetas solo con el etiquetado humano adjudicado (TQ-018), como versión nueva con SHA-256 nuevo |
| 7: "serializar modelo mínimo" | El runner no carga ningún scorer, así que el resultado no cambia; y entrenar un modelo para que esos 20 casos escalen es ajustar al held-out | Correr en modo completo con el modelo de registro ya entrenado y reportar lo que salga |
| 4: usar el parámetro `reason` en el INSERT de `gateway_postgres.py` | El texto libre viola el `CHECK` de `ops.card_locks`: `psycopg` lanza `CheckViolation`, el orquestador no la captura y la API responde 500 | Pasar el código de la decisión (`card_lock_reason`) en un argumento propio |
| 6: campo de credencial en el login y validación en `test-session` | Construye una autenticación propia, contra la decisión del 26-Sep (Supabase Auth) | `supabase-js` en el front y personas de prueba creadas por script |
| 3: reemplazar `utcnow()` por `datetime.now(timezone.utc)` en los 13 sitios | Mezcla fechas con zona y sin zona | `datetime.now(UTC).replace(tzinfo=None)`, o migrar sitio por sitio con test |
| 1: quitar pandas de `gateway.py` | No trae beneficio y arriesga la conversión de NaN y NaT a None | Ninguna; el acoplamiento que importa está en AUD-30 |
| 9: corregir los enums de `execute_open_dispute` | El método es código muerto | Borrar el método y sus tests |

---

## 5. Plan de Acción Revisado (v3)

### Fase 1: Decisiones del equipo (30 Sep noche y 1 Oct temprano)

| # | Acción | Hallazgo | Esfuerzo |
| --- | --- | --- | --- |
| 1 | Enviar a los mentores la pregunta de datos: licencia IEEE-CIS y publicación del subconjunto en Supabase. Sin respuesta, declarar el modelo experimental y mostrar que el sistema funciona sin él | AUD-01 | 15 min |
| 2 | Decidir cómo se reporta el held-out: la corrida ciega como resultado held-out y la de `0f663d7` como posterior al análisis de errores, o una suite v2 para el número final. Llevar la tabla del PR #12 al repo, donde decida TQ-019 | AUD-26, AUD-11 | 30 min |
| 3 | Decidir el denominador del SAR (qué cuenta como "in-scope") y reportarlo en `metrics.py` y en el reporte junto al de elegibles | AUD-10 | 30 min |
| 4 | Decidir la semántica del juez para abstenciones en casos que exigían humano | AUD-31 | 15 min |
| 5 | Decidir OpenTelemetry: descartarlo en el registro de decisiones o hacerlo mínimo | AUD-08 | 10 min |

### Fase 2: Correcciones con test primero (1 Oct)

| # | Acción | Hallazgo | Esfuerzo |
| --- | --- | --- | --- |
| 6 | `supabase-js` en el login, personas por script y `APP_ENV=production` en la imagen que se publique | AUD-02 | 3 h |
| 7 | Varios montos en un mensaje: preguntar cuál o escalar como multi-cargo | AUD-21 | 1.5 h |
| 8 | Devolver país, ciudad y moneda del producto en ambos gateways y la ciudad en el perfil; filtro Web y App en el scorer | AUD-27 | 1.5 h |
| 9 | `encoding="utf-8"` en `src/eval/cases.py:45` | AUD-14 | 5 min |
| 10 | Rutas del starter solo con `APP_ENV` development o test | AUD-09 | 20 min |
| 11 | "no es mío" y "não é meu" como frases de disputa, sabiendo que contamina el held-out | AUD-28 | 30 min |

### Fase 3: Corridas y reporte (1 y 2 Oct)

| # | Acción | Hallazgo | Esfuerzo |
| --- | --- | --- | --- |
| 12 | Corrida con el modelo de registro y con Jev contra el baseline de reglas, sobre los mismos casos | AUD-29, AUD-20, AUD-04 | 2 h |
| 13 | Reporte held-out que declare las etiquetas de diseño, muestre la corrida ciega y la posterior, los sesgos del adapter del starter y el análisis de errores | AUD-11, AUD-12, AUD-26 | 2 h |

### Fase 4: Despliegue y limpieza (2 y 3 Oct)

| # | Acción | Hallazgo | Esfuerzo |
| --- | --- | --- | --- |
| 14 | Separar dependencias por grupo (runtime, ML, notebooks, dev), mover las excepciones del gateway a un módulo sin duckdb y medir el paquete en el deploy esqueleto | AUD-30 | 2 h |
| 15 | Llevar el modelo al deploy (artefacto fuera de git) o declarar que la demo corre sin él | AUD-04 | 1 h |
| 16 | Borrar `execute_open_dispute` de DuckDB y sus tests | AUD-07, AUD-23 | 10 min |
| 17 | Pasar `utcnow()` a UTC sin zona, con test | AUD-19 | 30 min |
| 18 | Código de razón del bloqueo en un argumento propio | AUD-24 | 15 min |
| 19 | Rate limit básico para la demo pública (Vercel o por sesión) | AUD-18 | 1 h |

### Fase 5: Documentación (3 Oct)

| # | Acción | Hallazgo | Esfuerzo |
| --- | --- | --- | --- |
| 20 | Estado por fila en la tabla objetivo del README; ONNX, Playwright, OpenTelemetry, idempotencia y filtro de inyección como pendientes donde falte | AUD-03, AUD-06, AUD-15, AUD-16, AUD-22 | 30 min |
| 21 | `docs/SUPABASE_VERCEL.md`: `frontend/dist` y cierre del "por verificar" de `app.frontend()` | AUD-05 | 10 min |
| 22 | `AGENTS.md:309`: 85 tests de política, no 55 | Sección 8 | 5 min |

---

## 6. Resumen de Severidades (v3)

| Severidad | Conteo | IDs |
| --- | --- | --- |
| **Bloqueante** | 3 | AUD-01, AUD-02, AUD-26 |
| **Alta** | 8 | AUD-04, AUD-09, AUD-20, AUD-21, AUD-27, AUD-28, AUD-29, AUD-30 |
| **Media** | 8 | AUD-06, AUD-08, AUD-10, AUD-11, AUD-12, AUD-14, AUD-16, AUD-31 |
| **Baja/Media** | 1 | AUD-18 |
| **Baja** | 8 | AUD-03, AUD-05, AUD-07, AUD-15, AUD-19, AUD-22, AUD-23, AUD-24 |
| **Descartado** | 3 | AUD-13, AUD-17, AUD-25 |
| **Total** | 31 | |

---

## 7. Hallazgos Positivos

1. **Política v2.3 implementada:** 12 cláusulas en orden fijo, 85 tests con nombres por cláusula e ids trazables.
2. **Act-and-verify:** lectura de vuelta obligatoria; si falla, el turno escala con `ACTION_VERIFICATION_FAILED`.
3. **`customer_id` del token en el stack de disputas:** nunca del body ni del modelo. La excepción son las rutas del starter (AUD-09).
4. **Inyección de fallas en la suite:** `_Faulty` simula `missing`, `verification_error` y `timeout`.
5. **Máscara PII con patrones LATAM:** CURP, CPF, DNI, cédula o CC, sin enmascarar montos de 7 dígitos.
6. **Dos backends, una interfaz:** DuckDB y Postgres, con el SQL del ops store reescrito automáticamente.
7. **Presupuesto diario de LLM:** tope de 2 USD, fallback automático y registro de uso solo de inserción (permisos `SELECT, INSERT`).
8. **Frontera contra inyección en comercios:** etiquetas XML con `html.escape`.
9. **Suite held-out de 250 casos en 10 categorías,** con ataques de token y de acceso cruzado por la API y fallas de herramientas inyectadas. Encuentra fallas reales (AUD-28).
10. **Multi-turno real:** aclaración, confirmación del bloqueo y reinicio.

---

## 8. Cambios Respecto a v2

- Severidades unificadas: v2 daba a AUD-10, AUD-11, AUD-16 y AUD-25 severidades distintas en sus secciones 1, 2 y 5.
- Citas corregidas: AUD-13 (`.df()` está en `gateway.py:87,127`, no en 74 y 114), AUD-22 (`AGENTS.md:272`, no 222) y AUD-24 (`gateway_postgres.py:114`, no 103).
- Afirmación retirada: ningún documento dice "DuckDB desacoplado" (AUD-13).
- Datos corregidos en AUD-01: TQ-026 está respondida y 0.507 no mide la calidad del modelo.
- Hallazgos refutados: AUD-05 (`app.frontend()` existe), AUD-13, AUD-17 y AUD-25.
- Remedios retirados: los de la sección 4.
- Positivo 3 acotado al stack de disputas, porque contradecía AUD-09.
- La columna "Confirmado v2" remitía a un primer pase que no está en el repo; v3 la reemplaza por el veredicto verificado.
- Agregados AUD-26 a AUD-31 y la evidencia ejecutada.
- Deriva de docs que v2 no marcó: `AGENTS.md:309` dice 55 tests de política (hay 85) y el estado del README sigue en el 29-Sep.
