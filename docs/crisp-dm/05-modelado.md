# CRISP-DM 4. Modelado

En AlterEgo ningún modelo decide un resultado. Decide la política como código; los componentes aprendidos o recuperados solo entregan señales tipadas que esa política lee (`AGENTS.md` sec. 4, reglas 6 y 7; sec. 8).

En producción (<https://alterego-silk.vercel.app>) corren la política v2.3, el extractor de palabras clave ES/PT y el explicador con BM25. No corren el modelo de riesgo (su archivo está en `.gitignore` y Vercel construye desde GitHub, commit `a18f045`), ni Jev, ni respuestas de Claude (`README.md`, "Limitations"; [`docs/HANDOFF.md`](../HANDOFF.md) sec. 7.3).

## Mapa de decisiones

Cada fila se detalla, con sus fuentes, en la sección indicada.

| Componente | Alternativa evaluada | Decisión | Por qué |
| --- | --- | --- | --- |
| Política de disputas (1) | Un LLM o un agente ReAct que decide y elige herramientas | Política como código, cláusulas y orden del brief v2.3 tal cual | Reglas 6, 7 y 9; cada decisión cita su cláusula |
| Modelo de riesgo (2) | Gradient boosting sobre `is_fraud` del banco, umbral 0,70 | Transferido de IEEE-CIS, 19 features desplegables, umbral en el percentil 98 de Web y App | `is_fraud` no tiene señal y `fraud_score` filtra la etiqueta (TQ-023, TQ-026) |
| Runtime del riesgo (2) | LightGBM servido en ONNX | `HistGradientBoostingClassifier` con joblib | A tres días de la entrega no se cambió (TQ-022) |
| Recuperación del explicador (3) | `multilingual-e5-small` int8 en ONNX | BM25 servido; E5 solo offline | E5 no cabe en el bundle de 500 MB de Vercel |
| Understand (4) | Solo Jev, o solo palabras clave | Router: Jev con key y presupuesto; palabras clave en el resto | Jev en acceso anticipado; CI sin red ni costo |
| Redacción de respuestas (5) | Claude Haiku 4.5 con fichas (decidido) | Plantillas | Faltan las tareas 3 a 7; no existe ninguna llamada a Claude |
| Baseline de referencia (6) | Reparar el pipeline inicial | Medirlo tal cual, con solo su crash arreglado | Lo inseguro que hace cuenta en el reporte |

## 1. Política como código

`DisputePolicyEngine.evaluate` recorre las cláusulas en un orden fijo y devuelve en la primera que decide ([`src/rules/dispute_policy.py`](../../src/rules/dispute_policy.py)). Reordenar cambia resultados.

**Por qué determinista.** Las reglas 6, 7 y 9 piden política en código, solo acciones verificadas y explicaciones que no salgan de la cadena de pensamiento de un modelo (`AGENTS.md` sec. 4). Una cláusula con id (`POL-WIN-60`) es auditable; un LLM que decide no lo es. El equipo adoptó el brief v2.3 "tal cual" el 26-sep y descartó LangGraph, cuyo especialista ReAct deja que el LLM elija herramientas que escriben ([`docs/specs/claude-replies-v1.md`](../specs/claude-replies-v1.md), D3).

**Orden de cláusulas** (matriz de trazabilidad de [la spec](../specs/dispute-policy-v2.3.md) sec. 1):

| Paso | Id | Condición | Resultado |
| --- | --- | --- | --- |
| 1 | `POL-ESC-LEGAL` | Cita a regulador (CONDUSEF, SFC, BCRA, PROCON) o acción legal | Humano; va antes de la ventana, así que escala aun un cargo viejo |
| 2 | `POL-CLARIFY` | Cero o varios candidatos; intención de Jev con confianza menor a 0,70; robo de Jev entre 0,40 y 0,60 | Pregunta de aclaración |
| 2 | `POL-ESC-AMBIG` | Sin resolver tras 2 intentos de aclaración | Humano |
| 3 | `POL-DISP-TYPE` | Disputable solo si es `Approved` y Purchase, Payment, Withdrawal o Transfer; además fecha futura, intención fuera de alcance decisiva o `amount_usd` nulo | Abstención; humano si falta `amount_usd` |
| 4 | `POL-WIN-60` | Más de 60 días desde el día de proceso hasta 2026-06-17 | Abstención |
| 5 | `POL-ESC-500` | Más de 500 USD | Humano |
| 5 | `POL-ESC-ML-RISK` | Score sobre el umbral del modelo (0,70 por defecto del motor) | Humano |
| 5 | `POL-ESC-MULTI` | Más de 2 cargos disputados en 48 h | Humano, con bloqueo recomendado |
| 5 | `POL-ESC-DISTRESS` | Angustia de Jev de 2 o más, palabra clave de respaldo o angustia severa en la memoria de casos | Humano |
| 6 | `POL-AUT-150` | Hasta 150 USD, Premium o Plus, cuenta de más de 180 días, 0 quejas en 90 días | Caso abierto más marca de candidato a crédito que aprueba un humano (regla 8) |
| 7 | `POL-AUT-INTAKE` | Pasó todas las puertas | Caso abierto con valores del diccionario |
| Siempre | `POL-AUT-LOCK` | Robo (Jev 0,80 o más, o palabras clave) o fraude de varios cargos | Bloqueo recomendado en cualquier resultado; el cliente confirma |

En el paso 5 decide la primera escalación que aplica; las demás quedan en `secondary_clauses`. `ACTION_AUTH_MATRIX` declara la autenticación por acción: sesión para abrir caso, sesión más el sí del cliente para bloquear, reingreso más agente humano para desbloquear y rol de agente para aprobar crédito.

**Umbrales.** Son spec y no se ajustaron; la spec solo registra la sensibilidad del techo de 500 USD (sec. 5; cifras en [Entendimiento del negocio](02-entendimiento-del-negocio.md) sec. 7). El motor tarda 3,8 microsegundos por decisión (4,2 en la reverificación del 27-sep) y no gasta tokens (misma sección). Lo fijan 55 tests `test_pol_*` nombrados por cláusula, más 4 `test_policy_*`, en `tests/test_dispute_policy.py` (grep del 4-oct).

**Límites conocidos.** Las listas de respaldo de robo y angustia comparan subcadenas: "lo aprobaron ayer" contiene "robaron" (TQ-031). El 2-oct se decidió pasar a palabras completas, pero no hay código (`docs/HANDOFF.md` sec. 3, C). La confianza de intención se lee por opción, nunca como masa sumada (TQ-024, respondida por Kmilo el 29-sep).

## 2. Modelo de riesgo de fraude

`POL-ESC-ML-RISK` necesita un score. El brief pedía un gradient boosting sobre `transactions.is_fraud`, sin `fraud_score`, con split temporal y umbral por costo (`docs/TEAM_BRIEF_COMPLEMENTED.md`, Decision 3). Los datos no lo permitieron, y el modelo servido vino de una competencia externa.

### 2.1 Por qué no se entrenó con los datos del banco

1. **`fraud_score` filtra la etiqueta.** Toda fila no fraudulenta puntúa 30 o menos: un score mayor a 30 es fraude con 100 % de precisión. Queda fuera de todo modelo y del baseline (`AGENTS.md` sec. 7).
2. **`is_fraud` no tiene señal aprendible.** En la carga completa (4.425.008 transacciones, 4.316 fraudes, tasa 0,098 %) la tasa es plana por canal (0,095 % a 0,108 %), monto, hora, categoría, segmento y estado ([`docs/technical-discuss-points.md`](../technical-discuss-points.md) sec. 5).
3. **El modelo sin fuga no aprende.** Con 2.869.946 filas de entrenamiento y 1.555.062 de test (1.445 fraudes), el gradient boosting da ROC AUC de test 0,497 y las reglas 0,495; el umbral óptimo por costo no marca nada ([`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md)).
4. **El pipeline sí funciona.** Con una etiqueta sintética que depende del comportamiento llega a ROC AUC 0,869 (`notebooks/02_risk_model_experiment.ipynb`, sección 7; `docs/technical-discuss-points.md` sec. 5 dice 0,868).
5. **No hay señal en otras tablas.** De 139 bins de ocho tablas (140 según `docs/technical-discuss-points.md` sec. 5 y TQ-023), ninguno con 1.000 filas o más sube la tasa 1,5 veces (`notebooks/03_fraud_signal_search.ipynb`), y las quejas por cargo no reconocido son independientes de las marcas de fraude (`notebooks/04_claims_vs_flags_and_transcript_nlp.ipynb`; `docs/technical-discuss-points.md` sec. 6).

La primera corrida, sobre la muestra de junio, tenía 9 fraudes: su ROC AUC de test de 0,624 sobre 3 positivos prueba el pipeline, no es un resultado ([`reports/ml/fraud_risk.md`](../../reports/ml/fraud_risk.md)). La hipótesis 3 no se puede confirmar con estos datos (TQ-023, sin respuesta registrada).

**Contradicción menor.** `docs/technical-discuss-points.md` sec. 5 y `AGENTS.md` sec. 7 dicen ROC AUC 0,50; el reporte y el README, 0,497. Según TQ-023, 0,497 sale tras agregar país, segmento, antigüedad y tipo de transacción (inferido: dos corridas).

### 2.2 El baseline heredado

El pipeline inicial trae un "modelo" sin entrenar, `MLFraudDetector`: una sigmoide con pesos fijos sobre monto, razón al promedio, tarjeta no presente y país distinto de "US", multiplicada por un peso por nivel de cliente ([`src/ml/fraud_detector.py`](../../src/ml/fraud_detector.py)). Solo sirve al baseline de referencia (sección 6). Aparte, `src/ml/fraud_risk.py` trae reglas sin `fraud_score` (más de 1.000 USD, razón mayor a 3, país extranjero, tarjeta no presente), medidas solo offline.

### 2.3 Transferencia desde IEEE-CIS

**Datos (externos).** IEEE-CIS Fraud Detection (Kaggle, 2019, datos de Vesta): 590.540 transacciones de tarjeta no presente, 20.663 fraudes (3,5 %). Los archivos viven en `data/kaggle/`, fuera de git ([`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md) secs. 1 y 7).

**Contrato de features.** Un mismo constructor calcula las features en ambas fuentes, solo con filas anteriores de la tarjeta o del cliente ([`src/ml/feature_contract.py`](../../src/ml/feature_contract.py), contrato 1.1). El entrenador usa `DEPLOYABLE_V1`: 19 features calculables desde la copia de servicio (decisión del 29-sep, spec sec. 11), entre ellas monto, hora de proceso, crédito o débito y 9 agregados por tarjeta. `card_age_days` quedó fuera: el 18,71 % de los cargos es anterior a la apertura de su producto (spec sec. 10.3). El detalle está en [Preparación de los datos](04-preparacion-de-los-datos.md).

**Algoritmo.** `HistGradientBoostingClassifier` con `FIT_PARAMS` fijos (`max_iter` 300, `learning_rate` 0,05, `max_leaf_nodes` 31, `min_samples_leaf` 40, `random_state` 7; [`src/ml/fraud_risk_transfer.py`](../../src/ml/fraud_risk_transfer.py)). El plan era LightGBM servido en ONNX, porque la rueda Linux de `lightgbm` exige `libgomp` y arrastra `scipy` (`docs/PLAN.md`, fila "Runtime de inferencia"); TQ-022 (2-oct) mantuvo scikit-learn porque quedaban tres días.

**Validación en la fuente** (último 20 % de los días; [`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md)):

| Medida | Valor |
| --- | --- |
| Entrenamiento | 487.837 filas, 17.150 fraudes; ROC AUC 0,859 |
| Holdout | 102.703 filas, 3.513 fraudes; ROC AUC 0,817, PR AUC 0,165 |
| Recall y precisión al umbral de costo (holdout) | 0,404 y 0,176 |
| Ablación sin agregados por tarjeta / sin bloque discreto | ROC AUC 0,785 / 0,755 |
| Referencia con las 415 columnas de la competencia | ROC AUC 0,9169 ([`reports/ml/ieee_cis_feature_importance.md`](../../reports/ml/ieee_cis_feature_importance.md)) |

**Umbral: percentil 98, no 0,70.** Un clasificador separa las dos fuentes con AUC 1,000 con todas las codificaciones probadas (spec sec. 10.1), así que las probabilidades transferidas no tienen sentido absoluto en el banco. El umbral es el percentil 98 de 75.366 cargos Web y App de los 60 días hasta 2026-06-17: 0,0669, con 2,0 % de cargos encima. Además la prevalencia, 3,5 % en la fuente, es desconocida en el banco, y un percentil acota las escalaciones que la consola puede absorber (spec sec. 6). La política lee el umbral del bundle; 0,70 queda como valor por defecto. El acuerdo con `is_fraud` (73 marcas) es ROC AUC 0,507: se reporta y nunca se optimiza.

**Canales.** Jev homologó Web (0,69) y App (0,60) como del tipo de la competencia; ATM, POS, Branch y Transfer quedaron entre 0,03 y 0,05. Web y App son el 30,0 % de los cargos (spec sec. 10.2). Desde el 3-oct (PR #45, AUD-27), `TransferRiskScorer` no califica otros canales: la política recibe 0,0 y el handoff dice "not scored" ([`src/ml/transfer_scorer.py`](../../src/ml/transfer_scorer.py)).

**Explicación y validez.** El scorer entrega las 3 contribuciones mayores, reemplazando cada feature por su mediana de entrenamiento; no son valores SHAP (`AGENTS.md` sec. 9). Ninguna etiqueta del banco valida la transferencia: el score enruta cargos a un humano y no es un detector de fraude validado en LATAM Bank (`README.md`, "Risk model").

**Medición con el modelo.** Desde el 5-oct tiene reporte ([`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md), 3 repeticiones, nada ajustado), con las mismas cifras que traían los cuerpos de los PR #44 y #45. En el held-out: 9 de 250 resultados inseguros contra 20 sin modelo; 11 de 20 casos de alto riesgo escalados; 4 escalaciones de más (8 antes del arreglo de canales); 101 de 107 resoluciones seguras contra 105. Su p50 (27,1 ms) es de otra máquina que la del reporte solo reglas (161,6 ms).

**Reproducibilidad.** El PR #45 dejó abierto el bundle de registro porque un reentrenamiento dio ROC AUC 0,815 y umbral 0,0694. La causa era el orden de las filas con la misma marca de tiempo, que el motor rompía distinto en cada lectura. Con el orden fijo (commit `4db45f3`), dos reentrenamientos dan el mismo reporte: 0,817 y 0,0669, las cifras del 30-sep ([Plan de pendientes](09-plan-de-pendientes.md), sección 2.1).

**EDA de las 19 features.** [`reports/ml/risk_feature_eda.md`](../../reports/ml/risk_feature_eda.md) trae mínimo, máximo y media de cada feature en las dos fuentes, una gráfica por feature y lo observado contra lo predicho: en el holdout de la competencia, 3.513 fraudes observados contra 3.298 esperados, y el decil más alto predice 14,64 % y observa 15,71 %. También encontró un residuo numérico en `amount_zscore_card` y `tx_sum_card_7d`, que queda como decisión (Plan de pendientes, secciones 2.5 y 3).

**Contradicciones abiertas y siguiente paso.**

- Licencia de IEEE-CIS: `README.md` y TQ-032 registran la aprobación de los mentores; TQ-026, su fila en `docs/PLAN.md` y la spec la dan por pendiente (detalle en [Entendimiento del negocio](02-entendimiento-del-negocio.md) sec. 7).
- Canales fuera de Web y App: el reporte del 30-sep ("Caveats") y `docs/technical-discuss-points.md` sec. 7 dicen que las reglas los cubren; la spec sec. 6 (actualizada el 3-oct) y el código dicen que al servir nada los califica.
- Siguiente paso registrado: traer las familias C y D de la competencia, que son historia del banco, para acercar 0,817 a 0,917 (`reports/ml/ieee_cis_feature_importance.md` sec. 4; TQ-026).

## 3. Explicador de políticas (RAG)

El explicador responde preguntas sobre las reglas ("¿cuántos días tengo para disputar?") citando la cláusula. Nunca cambia una decisión, no abre casos y no lee el banco ([`src/rag/`](../../src/rag/); [`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md) sec. 4).

**Corpus.** Las 13 cláusulas de la spec v2.3 en `data/policy_corpus.json` (`team-generated`), con nivel de exposición (TQ-037): 3 internas (`POL-AUT-150`, `POL-ESC-ML-RISK`, `POL-SEC-SESSION`) que responden con una redirección fija, 2 genéricas (legal y angustia) y 8 públicas.

**Alternativas.**

| Opción | Resultado | Fuente |
| --- | --- | --- |
| E5 (`intfloat/multilingual-e5-small`, ONNX int8, 118 MB más 17 MB de tokenizer, revisión `614241f6`) | Medible offline (`--e5`); no servido | PR #24; roadmap secs. 3 y 5 |
| BM25 (`rank-bm25`) sobre el mismo texto indexado | Servido | [`src/rag/bm25_retriever.py`](../../src/rag/bm25_retriever.py) |
| BGE-M3 | Descartado por tamaño (2,27 GB) | `docs/PLAN.md`, fila "Modelo de embeddings y respaldo del RAG" |
| GraphRAG | Descartado: 13 cláusulas disjuntas no piden razonamiento multisalto | Roadmap sec. 2 |

**Por qué BM25.** El runtime pesa 358 MB y el bundle sin E5, unos 377 MB. E5 suma unos 232 MB y llevaría el bundle a unos 609 MB, sobre el límite de 500 MB de Vercel. Cabría (unos 466 MB) si el riesgo se sirviera en ONNX sin `scikit-learn` ni `scipy`, pero TQ-022 los mantuvo ([`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 6.3; roadmap sec. 5, Tarea 2.0).

**La hipótesis 5 se midió el 5-oct y BM25 se queda.** La regla se comprometió antes de medir (la propuesta de la Tarea 4.2). En test, E5 da recall@3 de 87,0 % (20 de 23) contra 69,6 % (16 de 23) de BM25: 3 preguntas de ventaja en español y 1 en portugués, cuando la regla pedía 2 en cada idioma. Su acción correcta no mejora (10 de 30 contra 11 de 30), porque su compuerta dejó pasar una sola respuesta: lo que limita al explicador es la compuerta, no el recuperador. La corrida usó una CPU ARM64, distinta de la que espera el archivo int8 ([`reports/rag_evaluation_report.md`](../../reports/rag_evaluation_report.md)).

**Compuerta de confianza.** El score del primer resultado cae en tres bandas ([`src/rag/gate.py`](../../src/rag/gate.py)): desde `tau_upper` responde (o redirige si la cláusula es interna), entre los dos umbrales pide aclaración, y debajo se abstiene. Los umbrales, 3,862 y 3,835 ([`data/rag_gate.json`](../../data/rag_gate.json)), son el par que acierta más acciones en desarrollo y, a igualdad, el más alto (`src/eval/rag_benchmark.py`). Commitear ese archivo encendió el explicador el 2-oct (PR #28).

**Resultados** ([`reports/rag_benchmark.md`](../../reports/rag_benchmark.md); banco `team-generated, LLM-drafted`, 30 preguntas por split, 15 ES y 15 PT):

| Métrica | Desarrollo | Test |
| --- | --- | --- |
| Recall@3 | 82,6 % (19 de 23) | 69,6 % (16 de 23) |
| Acción correcta | 56,7 % (17 de 30) | 36,7 % (11 de 30) |
| Abstención indebida | 33,3 % (6 de 18) | 61,1 % (11 de 18) |
| Cita equivocada | 21,4 % (3 de 14) | 27,3 % (3 de 11) |
| Fuera de alcance abstenidas | 100,0 % (7 de 7) | 85,7 % (6 de 7) |

**Debilidades medidas.** BM25 no reconoce paráfrasis, y una palabra genérica ("días") arrastra la cláusula equivocada. Un LLM redactó el banco tras leer las palabras clave del corpus, y la primera corrida midió test junto con la calibración (desviaciones declaradas en el PR #28). Inferido de la lectura del código, sin test que lo demuestre: una segunda pregunta de política tras un saludo puede ir al flujo de disputa, porque `_disputed_earlier` (`src/orchestrator/dispute_orchestrator.py`) cuenta la primera si nombra un "cargo".

## 4. Understand: Jev frente al extractor de palabras clave

Understand interpreta el mensaje y llena un esquema tipado; no decide (`AGENTS.md` sec. 8).

- **Jev** (TypeSafe AI, `typesafe-sdk==0.7.1`, modelo fijado `jev-1.13.0`): en una llamada devuelve intención y categoría fuera de alcance (`Choice`), robo de tarjeta (`Noul`) y angustia (`Score`). Solo ve el mensaje enmascarado ([`src/understand/jev_extractor.py`](../../src/understand/jev_extractor.py)).
- **Extractor ES/PT de palabras clave y regex** (`keyword-v1`): aporta siempre montos, fechas, sí o no y número de opción desde el texto crudo, también cuando responde Jev. Además calcula `policy_question`, la señal que manda un turno al explicador ([`src/understand/keyword_extractor.py`](../../src/understand/keyword_extractor.py)).

**El router** ([`src/understand/router.py`](../../src/understand/router.py), TQ-008) usa palabras clave en un turno trivial (12 caracteres o menos, respuesta al bloqueo, opción en una aclaración), sin key o SDK de Jev, o sin presupuesto (tope de 2 USD por día entre proveedores, TQ-015, `src/llm/budget.py`). Si no, llama a Jev y anota el gasto en `ops.llm_usage`; si Jev falla, cae a palabras clave y la auditoría guarda por qué.

**Por qué el extractor es el respaldo.** Jev estaba en acceso anticipado, y su documentación dice que el inglés es su idioma principal, así que su ventaja en ES y PT no está garantizada. CI y tests corren sin red ni costo ([`docs/JEV_TYPESAFE_AI.md`](../JEV_TYPESAFE_AI.md) secs. 1 y 5).

**Qué se midió.** La hipótesis 4 no tiene medición: "Jev has none" (`README.md`, "Limitations"). Jev sí se usó en análisis: categorizó 1.013 transcripciones, todas como `consulta_general` (`docs/technical-discuss-points.md` sec. 5), y dio 61 respuestas tipadas para homologar niveles de IEEE-CIS (spec sec. 10.2).

**En producción** no hay key de Jev: todo turno usa el extractor. Inferido de la lectura del código: el idioma se fija al salir del estado `new` (`src/orchestrator/dispute_orchestrator.py:171`), así que un mensaje posterior en portugués recibe respuestas en español.

## 5. Respuestas redactadas por Claude

Estado: **planeado, fusionado en parte, sin conectar.**

- **Plan.** El 26-sep se decidió que Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) redacta con marcadores que el código rellena (`docs/PLAN.md`, fila "Proveedor del LLM"). La spec v1, aprobada por escrito el 3-oct, limita a Claude a reescribir la prosa de aclaraciones y escalamientos, con cada dato cambiado por una ficha ([`docs/specs/claude-replies-v1.md`](../specs/claude-replies-v1.md), D1 y D2).
- **Fusionado.** El PR #36 trajo las tareas 1 y 2 de 7: la guarda determinista `src/llm/reply_guard.py` (rechaza datos, enlaces, promesas o confirmaciones que el código no puso), el redactor `src/llm/reply_writer.py` y el prompt `src/llm/prompts/reply_v1.md`. `anthropic==1.11.0` ya está en las dependencias de runtime (`pyproject.toml`).
- **Sin conectar.** Ningún módulo fuera de `src/llm/` importa el redactor (grep sobre `src/`, 4-oct). El router solo anota `reply_engine = "claude"` cuando hay key; la respuesta sigue siendo la plantilla. Faltan las tareas 3 a 7 ([`docs/specs/claude-replies-v1-plan.md`](../specs/claude-replies-v1-plan.md)).

## 6. El baseline de referencia (`HybridOrchestrator`)

El 26-sep el equipo decidió dos baselines (`docs/PLAN.md`, fila "Baselines"): el principal, la propia arquitectura en versión solo reglas (palabras clave, política v2.3, riesgo por reglas sin `fraud_score` y plantillas), y el de referencia, el pipeline inicial medido tal cual. En las corridas comprometidas, el "propuesto" es la arquitectura solo reglas sin ningún score de riesgo (`README.md`, "Results").

`src/agents/orchestrator.py` encadena en un paso `PIIMasker`, `DeterministicRulesEngine`, la sigmoide `MLFraudDetector`, una rama de palabras clave con herramientas simuladas que siempre tienen éxito y una cola HITL en memoria; toma `customer_id` del cuerpo y trabaja solo en USD (`CLAUDE.md`). Se dejó sin reparar para medir el punto de partida: su bloqueo de tarjeta ante "cargo no reconocido" y su promesa de reembolso cuentan como inseguros (`AGENTS.md` sec. 9). Solo se arregló su crash de precedencia `and`/`or` (commit `8632e96`). Nunca se despliega: su cola en memoria no sirve en funciones sin estado. Offline logra 3,7 % (4 de 107) de resolución segura automatizada, contra 63,6 % (68 de 107) del stack solo reglas en la corrida ciega y 98,1 % (105 de 107) tras el análisis de errores ([`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md); [Evaluación](06-evaluacion.md)).

## Optimización y tracking

| Qué | Cómo se fijó | Registro |
| --- | --- | --- |
| Umbrales de la política y de Jev | Spec v2.3 y brief, sin ajuste; mover los de Jev sigue en Propuesta | Spec sec. 5; `docs/PLAN.md`, fila "Lectura de las señales de Jev" |
| Hiperparámetros del modelo transferido | Fijos en `FIT_PARAMS`; no hay búsqueda en `src/`, `scripts/` ni `notebooks/` (grep del 4-oct) | MLflow |
| Umbral de costo (10 por fraude omitido, 1 por verificación de más) | Mínimo costo en el entrenamiento de la competencia | Reportado; no se sirve |
| Umbral de `POL-ESC-ML-RISK` | Percentil 98 de los cargos Web y App del banco | Bundle y reporte |
| `tau_upper` y `tau_lower` | Solo desarrollo; el test se mide una vez y se rechaza si cambió su SHA-256 | `data/rag_gate.json`, con commit y SHA-256 del corpus y del split |

**MLflow** (TQ-021, implementado el 1-oct). Cada entrenamiento de `src/ml/fraud_risk_transfer.py` abre una corrida en el experimento `fraud_risk_transfer` con parámetros, métricas, ablaciones, calibración del banco, etiquetas (`commit`, `contract_version`, `threshold_kind`) y, como artefactos, los reportes y el bundle. El almacén es local (`sqlite:///mlflow.db` y `mlruns/`, en `.gitignore`): el repo guarda los reportes, no las corridas.

## Fuentes

- [`AGENTS.md`](../../AGENTS.md) secs. 4, 7, 8 y 9; [`README.md`](../../README.md); [`CLAUDE.md`](../../CLAUDE.md); [`docs/HANDOFF.md`](../HANDOFF.md) secs. 3 y 7.3; [`docs/PLAN.md`](../PLAN.md); [`docs/TEAM_BRIEF_COMPLEMENTED.md`](../TEAM_BRIEF_COMPLEMENTED.md), Decision 3.
- [`docs/specs/`](../specs/) (política v2.3, riesgo IEEE-CIS, respuestas de Claude v1 y su plan); [`docs/technical-discuss-points.md`](../technical-discuss-points.md) secs. 5 a 7; [`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md); [`docs/JEV_TYPESAFE_AI.md`](../JEV_TYPESAFE_AI.md); [`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 6.3.
- [`reports/ml/`](../../reports/ml/), [`reports/ml_full/`](../../reports/ml_full/), [`reports/rag_benchmark.md`](../../reports/rag_benchmark.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md), [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md), [`data/rag_gate.json`](../../data/rag_gate.json).
- [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json): TQ-008, TQ-015, TQ-021 a TQ-024, TQ-026, TQ-031, TQ-032 y TQ-037.
- Código en `src/` y `tests/test_dispute_policy.py`; PR #24, #28, #36, #44 y #45 (`gh pr view`); commits `a18f045` y `8632e96`.
