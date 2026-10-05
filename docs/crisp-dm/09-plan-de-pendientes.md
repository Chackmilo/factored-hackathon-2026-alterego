# Plan de pendientes

La auditoría del 4-oct sobre esta guía encontró que no falta ningún capítulo: falta evidencia. Tres de las cinco hipótesis no tenían medición comprometida y varias decisiones quedaron sin ejecutar. Este archivo es la lista única de esos pendientes, con su estado, cómo se cierra cada uno y quién lo destraba. Reemplaza las listas repartidas entre [00](00-resumen-ejecutivo.md), [README](README.md) sección 5, [07](07-despliegue.md) sección 10 y [08](08-iteraciones-y-decisiones.md).

Estado al 5-oct. La primera parte entró a `main` con el PR #60; las decisiones de Kmilo del mismo día (secciones 2.10 a 2.12) están en la rama `feat/crisp-decisions`. Todo resultado es offline, sobre casos guionizados o datos de competencia, no una ganancia de producción (`AGENTS.md` sec. 4, regla 11).

## Resumen en una tabla

| Estado | Cuántos | Cuáles |
| --- | --- | --- |
| Hecho | 12 | Corrida held-out con el modelo (1), modelo de registro reproducible y en git (2), E5 contra BM25 (3), Jev contra el extractor (4), comparación solo reglas contra reglas más modelo (5), intervalos y prueba pareada (6), explicador en el harness (8), fixture de llegadas tardías (10), brecha por país de la corrida ciega (11), los dos bugs de conversación reproducidos y arreglados (12), residuo numérico arreglado con el contrato 1.2, licencia de IEEE-CIS alineada |
| Siguiente, sin cuentas ni gasto | 1 | Correcciones a esta guía que dependen de otras fuentes (sección 4) |
| Necesita una decisión del equipo | 6 | Hipótesis 3, preguntas abiertas, decisiones respondidas sin código, respuestas de Claude, ratificar la regla de E5, orden del texto con varios temas |
| Necesita personas o acceso | 3 | Etiquetas humanas (7), utilidad del handoff (9), estado de producción |
| Queda como limitación | 2 | Carga y concurrencia (13), familias C y D de la competencia (14) |

## 1. Análisis pendientes

| # | Pendiente | Estado | Cómo se cierra | Evidencia o bloqueo |
| --- | --- | --- | --- | --- |
| 1 | Held-out con el modelo de riesgo (H1, H2) | **Hecho** | `src.eval.run ... --model models/fraud_risk_ieee.joblib`, 3 repeticiones | [`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md); sección 2.2 |
| 2 | Modelo de registro: 0,817 o 0,815 | **Hecho** | El entrenador lee sus filas en orden fijo y dos reentrenamientos dan el mismo reporte; el bundle (contrato 1.2) está en git desde el 5-oct y llega a producción con el primer despliegue que lo incluya | Commits `0224320` y `4db45f3`; secciones 2.1 y 2.11 |
| 3 | E5 contra BM25 (H5, Tarea 4.2) | **Hecho** | Regla de decisión comprometida antes de medir (commit `8e9b9c7`); `src.eval.rag_benchmark --e5 models/e5-small` en el contenedor `dev` | [`reports/rag_evaluation_report.md`](../../reports/rag_evaluation_report.md); sección 2.6 |
| 4 | Jev contra el extractor (H4), con calibración ES y PT | **Hecho** | `src.eval.run ... --jev`: llamadas reales a Jev detrás del router, con tope de gasto propio (aprobado por Kmilo el 5-oct) | [`reports/jev_evaluation_report.md`](../../reports/jev_evaluation_report.md); sección 2.10 |
| 5 | Propuesto contra la versión solo reglas (H1) | **Hecho** | Misma suite: solo reglas contra reglas más modelo, y contra Jev, con prueba pareada | [`reports/eval_intervals.md`](../../reports/eval_intervals.md) |
| 6 | Intervalos o pruebas sobre las tasas (hallazgo H09) | **Hecho** | `src.eval.intervals` lee los reportes comprometidos, sin regenerarlos | `reports/eval_intervals.md`; sección 2.3 |
| 7 | Etiquetas humanas y kappa | Necesita personas | Dos personas etiquetan los 50 casos dobles (`data/eval/labeling/README.md`) | Las 4 planillas siguen en 0 de 300 filas; cerrada como limitación (TQ-018) |
| 8 | Explicador de políticas de punta a punta | **Hecho** el modo; la suite no lo ejercita | `src.eval.run ... --explainer data/rag_gate.json` corre lo que sirve producción | [`reports/eval_heldout_explainer.md`](../../reports/eval_heldout_explainer.md); sección 2.7 |
| 9 | Utilidad del handoff | Necesita personas | Una rúbrica y revisión humana; el código solo puede revisar que el paquete venga completo | El juez revisa la escalación y su razón, nada más |
| 10 | Fixture de llegadas tardías (`AGENTS.md` sec. 7) | **Hecho** | Fixture etiquetado con un cargo procesado tarde y una fila reprocesada, y tres tests | [`data/fixtures/late_arrival_transactions.json`](../../data/fixtures/late_arrival_transactions.json); sección 2.8 |
| 11 | Brecha por país de la corrida ciega | **Hecho** | Desglose por plantilla del reporte ciego | Sección 2.4 |
| 12 | Los dos bugs leídos del código (idioma fijo tras `new`; segunda pregunta de reglas tras un saludo) | **Hecho** | Reproducidos con tests y arreglados el 5-oct (TQ-041 y TQ-042, respondidas por Kmilo) | `tests/test_policy_rag.py`, `tests/test_dispute_orchestrator.py`; secciones 2.9 y 2.12 |
| 13 | Carga, concurrencia y costo de cómputo | Limitación | Se declara; no hay prueba de carga | `README.md`, "Limitations" |
| 14 | Familias C y D de la competencia (de 0,817 hacia 0,917) | Trabajo futuro | Seguimiento de TQ-026 | Sin código en `src/` |

## 2. Lo que se cerró el 5-oct

### 2.1 El modelo de registro ya se puede reproducir

El PR #45 dejó abierta la elección entre el bundle de 0,817 (umbral 0,0669) y un reentrenamiento de 0,815 (umbral 0,0694). La causa era el orden de las filas: 33.932 filas de la competencia comparten su marca de tiempo con otra, el motor rompe esos empates distinto en cada lectura, y dos cargas del mismo CSV difirieron en 458 posiciones. El orden llega a los agregados por tarjeta y al ajuste del modelo.

| Corrida | ROC AUC holdout | Umbral (percentil 98) |
| --- | --- | --- |
| Reporte del 30-sep (`f7c0eb5`) | 0,817 | 0,0669 |
| Reentrenamiento del PR #45 | 0,815 | 0,0694 |
| Dos reentrenamientos del 5-oct, antes del arreglo | 0,8156 y 0,8151 | 0,0748 y 0,0744 |
| Dos reentrenamientos del 5-oct, con orden fijo | 0,8170 y 0,8170 | 0,0669 y 0,0669 |

Con el orden fijo (empates por `TransactionID`; filas del banco por hora e id), los dos reentrenamientos escriben el mismo reporte, y sus cifras son las del 30-sep. El modelo de registro es ese: [`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md). Sigue sin decidirse cómo llega el archivo a Vercel (`models/*.joblib` está en `.gitignore`).

### 2.2 El held-out con el modelo tiene reporte

| Medida | Solo reglas (`reports/eval_heldout.md`) | Reglas más modelo (`reports/eval_heldout_model.md`) |
| --- | --- | --- |
| Resolución segura automatizada | 98,1 % (105 de 107) | 94,4 % (101 de 107) |
| Resultados inseguros | 8,0 % (20 de 250) | 3,6 % (9 de 250) |
| Casos de alto riesgo escalados | 0 de 20 | 11 de 20 |
| Transferencias omitidas / innecesarias | 20 / 0 | 9 / 4 |
| Recall / precisión de escalamiento | 79,6 % (78 de 98) / 100,0 % (78 de 78) | 90,8 % (89 de 98) / 95,7 % (89 de 93) |
| Resultado exacto | 88,4 % (221 de 250) | 90,8 % (227 de 250) |

Son las cifras que el PR #45 traía en su cuerpo, ahora en un reporte. Lectura:

- **Los 9 inseguros que quedan** son 9 de las 20 compras extranjeras de alto riesgo (5 por App y 4 por Web), que siguen abriendo caso: HO-164, HO-165, HO-168, HO-170, HO-171, HO-174, HO-176, HO-177 y HO-179.
- **Las 4 escalaciones de más** (HO-016, HO-038, HO-089 y HO-093) son las 4 resoluciones seguras que se pierden: el modelo las manda a humano con `HIGH_FRAUD_RISK_SCORE`.
- **La latencia** (27,1 / 313,1 ms) es de un Mac, otra máquina que la del reporte solo reglas (161,6 / 662,1 ms); no se comparan.
- **La base.** La corrida solo reglas repetida en `origin/main` (`3fe46f9`, con los PR #56 a #58) da los mismos resultados caso por caso que el reporte comprometido; solo cambian textos de respuesta.

### 2.3 Intervalos y prueba pareada

[`reports/eval_intervals.md`](../../reports/eval_intervals.md) da un intervalo de Wilson al 95 % por tasa y una prueba exacta de McNemar sobre los casos donde dos sistemas difieren.

| Comparación | Resolución segura | Inseguros |
| --- | --- | --- |
| Pipeline inicial contra propuesto, corrida ciega | 3,7 % (1,5 a 9,2) contra 63,6 % (54,1 a 72,1); p menor a 0,001 | 48,8 % (42,7 a 55,0) contra 15,6 % (11,6 a 20,6); p menor a 0,001 |
| Pipeline inicial contra propuesto, tras el análisis | 3,7 % contra 98,1 % (93,4 a 99,5); p menor a 0,001 | 48,8 % contra 8,0 % (5,2 a 12,0); p menor a 0,001 |
| Solo reglas contra reglas más modelo | 98,1 % contra 94,4 % (88,3 a 97,4); 4 casos perdidos, 0 ganados; p 0,125 | 8,0 % contra 3,6 % (1,9 a 6,7); 11 casos menos, 0 más; p menor a 0,001 |

Los casos salen de pocas plantillas, así que son menos independientes de lo que suponen las fórmulas: cada intervalo es un piso de la incertidumbre.

### 2.4 La brecha por país era la plantilla del extracto

En la corrida ciega, Colombia resolvió 15 de 36 elegibles y México 30 de 35. [06](06-evaluacion.md) sección 4 lo explicaba como inferencia. El desglose de `reports/eval_heldout_blind.json`:

| País | Con la palabra "extracto" o "extrato" | Sin ella |
| --- | --- | --- |
| Colombia | 0 de 16 | 15 de 20 |
| Argentina | 0 de 8 | 23 de 28 |
| México | 0 de 2 | 30 de 33 |
| Total | 0 de 26 | 68 de 81 |

Los 26 casos que mencionan el extracto fallaron todos (el hallazgo 1 de la corrida ciega, arreglado en el PR #13), y a Colombia le tocaron 16 de los 26. Sin esa plantilla la brecha se reduce a 75,0 % (15 de 20) contra 90,9 % (30 de 33).

### 2.5 EDA de las 19 features del modelo

[`reports/ml/risk_feature_eda.md`](../../reports/ml/risk_feature_eda.md) trae, para cada feature de `DEPLOYABLE_V1`, mínimo, máximo, media, mediana, desviación y nulos en las dos fuentes (590.540 filas de IEEE-CIS, externas; 75.366 cargos Web y App del banco en los 60 días hasta 2026-06-17), una gráfica por feature en [`reports/ml/eda/`](../../reports/ml/eda/) y lo observado contra lo predicho en la competencia. Lo escribe `src/ml/risk_feature_eda.py`.

Lo observado contra lo predicho (holdout de la competencia, 102.703 filas):

- **Totales.** 3.513 fraudes observados contra 3.298 esperados; en entrenamiento, 17.150 contra 17.131.
- **Por decil de score.** El decil más alto predice 14,64 % y observa 15,71 % (1.613 fraudes de 10.270); el más bajo predice 0,34 % y observa 0,33 %. El orden se sostiene en los diez deciles.
- **En el banco no hay nada que validar.** Las 73 marcas `is_fraud` se reparten parejo entre los deciles de score (de 4 a 11 por decil): es la misma falta de señal de [03](03-entendimiento-de-los-datos.md) sección 5.

Lo que muestran las features (valores crudos, antes de los rangos por fuente):

| Feature | Competencia | Banco | Lectura |
| --- | --- | --- | --- |
| `amount_usd` | Mediana 68,77; máximo 31.937 | Mediana 467,81; máximo 10.092 | Otros órdenes de magnitud; por eso el modelo lee rangos por fuente |
| `amount_has_cents` | 48,2 % con centavos | 98,9 % | En el banco casi no varía |
| `card_kind_debit` | 74,5 % | 9,8 % | En el banco, el 64,9 % de los cargos no es de tarjeta de crédito ni de débito |
| `tx_count_card_1d` | Media 1,97; máximo 880 | Media 0,012; máximo 2 | La velocidad por tarjeta, que separa el fraude en la competencia (de 2,8 % a 7,7 %), casi no existe en el banco |
| `days_since_prev_tx_card` | Mediana 1,9 días; 3,3 de media en fraude contra 10,3 | Mediana 24,2 días | Tarjetas de uso diario contra tarjetas con un cargo al mes |
| `hour_sin`, `hour_cos` | Medias -0,34 y 0,26 (hay horas pico) | Medias 0,00 y 0,00 | La hora del banco es uniforme |
| `address_distance_bucket` | 59,7 % nulo | 0 % nulo; media 0,09 | En el banco casi todo cargo es en la ciudad del cliente |

**Hallazgo nuevo: residuo numérico en dos features del contrato.** `amount_zscore_card` va de -66.959.892 a 528.064.394 en la competencia: cuando los cargos previos de una tarjeta son iguales, la varianza no da cero exacto sino un residuo de punto flotante, y dividir por él dispara el valor (308 filas pasan de 1.000 en valor absoluto, 667 de 50; 2.355 tienen una desviación entre 0 y 0,001). En el banco el máximo es 609,83. `tx_sum_card_7d` tiene el mismo origen: su mediana es 3,0e-09 en vez de 0. El modelo lee rangos, así que el efecto se limita a esas filas, pero su rango es ruido. Arreglarlo cambia el contrato (versión 1.2) y el modelo, así que queda como decisión (sección 3).

### 2.6 E5 contra BM25: BM25 se queda

La regla se comprometió antes de medir y es la que el roadmap proponía desde el 30-sep (Tarea 4.2), sin ratificar por el equipo: E5 se adopta solo si en test supera a BM25 en recall@3 por 2 preguntas o más en español y en portugués, sin más citas equivocadas, y si cabe en el bundle.

| Medida (test, 30 preguntas) | BM25 | E5 |
| --- | --- | --- |
| Recall@3 en español | 7 de 11 | 10 de 11 |
| Recall@3 en portugués | 9 de 12 | 10 de 12 |
| Recall@3 total | 69,6 % (16 de 23) | 87,0 % (20 de 23) |
| Acción correcta | 36,7 % (11 de 30) | 33,3 % (10 de 30) |
| Citas equivocadas | 3 de 11 | 0 de 1 |

E5 gana por 3 preguntas en español y por 1 en portugués: la regla pedía 2 en cada idioma, y además E5 no cabe en el bundle. La hipótesis 5 se cumple en dirección y no por el margen fijado; con 23 preguntas, una ventaja de 4 no se distingue del azar. El hallazgo útil es otro: recuperar mejor no dio mejores respuestas, porque la compuerta de E5 dejó pasar una sola respuesta en test. Lo que limita al explicador es la compuerta, no el recuperador. Límites: la corrida usó una CPU ARM64 y el archivo int8 está hecho para x86 con AVX-512 VNNI; el banco lo redactó un LLM.

### 2.7 El explicador encendido no cambia ningún caso del held-out

El harness ahora corre el stack propuesto con el explicador que sirve producción (`--explainer data/rag_gate.json`). Con él encendido, los 250 casos del held-out dan el mismo resultado, uno por uno, que la corrida solo reglas: 105 de 107 resoluciones seguras y 20 de 250 inseguros. La razón es que ninguna conversación de la suite hace una pregunta de reglas, así que ningún turno llega al explicador. Dos lecturas: las cifras solo reglas valen para lo que corre en producción, y la suite no mide al explicador. En el split de desarrollo, DEV-019 sí llega al explicador y recibe la cláusula correcta (`POL-WIN-60`) sin abrir caso; su etiqueta se escribió con el explicador apagado, así que el resultado exacto baja a 18 de 19 sin ningún inseguro.

### 2.8 Las llegadas tardías tienen su fixture

`data/fixtures/late_arrival_transactions.json` (`team-generated`) trae los dos casos que el dataset declara y no muestra:

- **Un cargo procesado tarde.** Evento del 15 de abril, día de proceso 20 de abril. Gold cuenta 58 días y lo deja en ventana; desde el evento serían 63. La política lo resuelve si recibe `process_date`, como hace el orquestador, y se abstiene con `POL-WIN-60` si recibe la marca cruda: para una fila tardía, fecha(`transaction_date` - 6 h) ya no es `process_date`.
- **Una fila reprocesada.** El mismo cargo llega el 10 de junio como `Pending` y el 12 como `Approved`. Silver se queda con la del 12 y la del 10 va a `quarantine_duplicate_transactions`.

Los tres tests están en `tests/test_ingestion.py`. La cuarentena pasó a ser una función (`build_quarantine_duplicate_transactions`) para poder probarla.

### 2.9 Los dos bugs de conversación se reproducen

Los dos estaban marcados como inferidos de la lectura del código ([06](06-evaluacion.md) sección 10; [07](07-despliegue.md) sección 9). Ahora cada uno tiene un test que lo reproduce, marcado como fallo esperado estricto hasta que el equipo decida el arreglo:

- **Preguntas de reglas tras un saludo (TQ-041).** La primera llega al explicador. La segunda va al flujo de disputa y recibe "No encontramos un cargo que coincida con su descripción". La tercera termina en un handoff con `POL-ESC-AMBIG`: un humano recibe a un cliente que no disputó nada. Es peor de lo que la guía describía, y el explicador está encendido en producción.
- **Idioma fijo (TQ-042).** Un cliente que saluda en español y luego escribe la disputa en portugués recibe la confirmación del caso en español. El caso sí se abre.

### 2.10 Jev contra el extractor: no lo supera

Kmilo aprobó el gasto el 5-oct. El harness corrió la suite held-out con Jev (`jev-1.13.0`) detrás del router, como lo arma la API: 300 llamadas reales por repetición, 0,035 USD en las tres repeticiones, y Jev solo ve el mensaje enmascarado.

| Medida | Extractor de palabras clave | Jev detrás del router |
| --- | --- | --- |
| Resolución segura automatizada | 98,1 % (105 de 107) | 98,1 % (105 de 107) |
| Resultados inseguros | 8,0 % (20 de 250) | 10,4 % (26 de 250) |
| Recall de escalamiento | 79,6 % (78 de 98) | 73,5 % (72 de 98) |
| Resultado exacto | 88,4 % (221 de 250) | 85,2 % (213 de 250) |
| Latencia p50, misma máquina | 24,8 ms | 447,4 ms |

La hipótesis 4 no se sostiene en esta suite. Ninguna resolución segura se gana ni se pierde, y 6 casos pasan a inseguros sin que ninguno deje de serlo (prueba exacta de McNemar, p 0,031). Lectura:

- **Por qué empeora.** Los 6 casos piden humano y terminan en una aclaración que nadie recibe. En tres, el primer mensaje cuenta en una sola frase una tarjeta robada y un cargo no reconocido: Jev reparte su respuesta entre las dos intenciones y su confianza cae bajo el 0,70 que pide `POL-CLARIFY` (0,42, 0,68 y 0,64). En los otros tres la diferencia aparece en un turno posterior.
- **La intención del primer mensaje no los separa.** Sobre 225 primeros mensajes, los dos motores distinguen disputa de fuera de alcance en todos (134 de 134 en español, 91 de 91 en portugués): la suite sale de pocas plantillas.
- **Calibración.** Jev peca de poca confianza, no de error: los 8 mensajes bajo 0,70 están bien leídos (2 de 2 en español, 6 de 6 en portugués) y los 8 son frases de tarjeta perdida o robada.
- **No es determinista.** En el split de desarrollo su resolución segura osciló entre 7 y 8 de 9 en tres repeticiones.

### 2.11 Contrato 1.2 y modelo en git

- **Residuo numérico (TQ-043, "arreglarlo").** El contrato 1.2 trata como cero una dispersión por tarjeta o una suma de 7 días que solo es residuo de punto flotante. Kmilo preguntó si bastaba una bandera `is_error`: no, porque el valor absurdo seguiría en la feature y la bandera sumaría una vigésima; poner el residuo en cero es la regla que el contrato ya tenía para una dispersión exactamente cero. Tras el arreglo ninguna dispersión queda entre 0 y 0,001, y los 22 z-scores sobre 1.000 que quedan en la competencia son reales: tarjetas cuyos cargos previos difieren por centavos.
- **Modelo reentrenado.** ROC AUC de holdout 0,816 y umbral 0,0637 (contrato 1.1: 0,817 y 0,0669); dos reentrenamientos dan el mismo reporte. En el held-out con el modelo, las cifras de la sección 2.2 no cambian: 101 de 107, 9 de 250 y los mismos casos. Las cifras del EDA de la sección 2.5 son del contrato 1.1; `reports/ml/risk_feature_eda.md` ya trae las del 1.2 (holdout: 3.513 fraudes observados contra 3.315 esperados).
- **Modelo en producción ("sí").** `models/fraud_risk_ieee.joblib` (1,3 MB) está en git, fuera de la regla que ignora los demás `.joblib`, y un test lo mantiene igual al reporte. Producción lo sirve desde el primer despliegue que incluya ese commit; un merge desde la cuenta de Kmilo queda bloqueado en Vercel Hobby, así que hace falta un merge de la cuenta dueña.
- **Licencia de IEEE-CIS ("sí, si explicamos por qué").** TQ-026, la fila de `docs/PLAN.md` y la spec del modelo ya dicen lo mismo que TQ-032: uso aprobado, con la condición de explicar por qué se usan datos externos. La explicación está en el README y en la sección 1 de la spec: la etiqueta del banco no tiene señal aprendible. El repo guarda el modelo entrenado, nunca los archivos de la competencia.

### 2.12 Los dos bugs de conversación, arreglados

- **TQ-041.** Un mensaje con `policy_question` ya no cuenta como disputa previa: tras un saludo, tres preguntas de reglas seguidas llegan las tres al explicador y ninguna termina en un humano. Una pregunta de reglas después de una disputa real sigue en el flujo de disputa.
- **TQ-042 ("en caso de duda, preguntar al cliente").** El primer mensaje fija el idioma. Uno posterior lo cambia solo con evidencia clara: dos marcas o más del otro idioma y al menos el doble que las del actual (una sola no basta: "pesos" contiene una marca de español). Si el mensaje mezcla los dos sin que uno domine, el turno se atiende igual y la respuesta ofrece el otro idioma, escrita en ese idioma. Un mensaje que solo nombra un idioma ("português", "en español por favor") lo cambia sin responder nada pendiente, y deja `LANGUAGE_CHANGED` en la auditoría. Jev no interviene.
- **Sin efecto en la suite.** Con los dos arreglos, las corridas solo reglas y con explicador dan el mismo resultado en los 250 casos del held-out, y ninguna respuesta de la suite lleva la pregunta de idioma.

### 2.13 Temas: un mensaje con varias afirmaciones se atiende uno por uno (TQ-044)

Decisión de Kmilo del 5-oct tras la medición de Jev. Cada afirmación del mensaje es un tema, leído por separado: tarjeta perdida o robada (criticidad 1), disputa de un cargo (2), pregunta sobre las reglas (3) y pedidos que este canal no atiende (4). `src/understand/topics.py` define cada uno con lo que incluye y lo que deja fuera.

- **Jev** responde una pregunta de sí o no por afirmación, en vez de elegir una intención entre cinco. Dos afirmaciones verdaderas ya no se reparten la confianza.
- **El cliente** lee que sus temas se atienden uno por uno, empezando por el más urgente, y que lo que no es una disputa de cargos no se atiende por este canal. El conteo de temas queda en las señales y en la auditoría (`TOPICS_DETECTED`), nunca en la respuesta.
- **Sin estados en paralelo.** La conversación sigue preguntando una cosa a la vez; el estado es el tema que se está preguntando.

Medido de nuevo con Jev (`reports/jev_evaluation_report.md`): los inseguros vuelven de 26 a 20 de 250, la cifra del extractor, y el resultado exacto sube a 223 de 250 (extractor: 221). En desarrollo, 9 de 9 y 0 de 19 en las tres repeticiones. Solo reglas, los 250 casos conservan su resultado y 11 respuestas ganan el aviso de "uno por uno". La hipótesis 4 queda sin probar: dos casos de ventaja no se distinguen del azar en esta suite.

El flujo completo, con diagrama, está en [`docs/deliverables/flujo_conversacion_agente.docx`](../deliverables/flujo_conversacion_agente.docx).

### 2.14 La hipótesis 4, probada en un banco de mensajes variados

El held-out no podía probarla: sus mensajes salen de pocas plantillas y los dos motores leen bien los 225. Se escribió un banco de 140 mensajes de cliente (`team-generated, LLM-drafted`; 40 de desarrollo y 100 de test, mitad español y mitad portugués), con paráfrasis, habla regional, errores de tipeo y varios temas por mensaje. Las reglas de decisión se comprometieron antes de medir (commit `fd7f1d1`).

| Mensajes de test bien leídos | Español | Portugués | Total |
| --- | --- | --- | --- |
| Extractor de palabras clave | 22 de 50 | 27 de 50 | 49,0 % (49 de 100) |
| Jev | 46 de 50 | 46 de 50 | 92,0 % (92 de 100) |
| Mezcla que llama a Jev solo si las palabras clave dudan | 40 de 50 | 41 de 50 | 81,0 % (81 de 100) |

- **La hipótesis 4 se sostiene en este banco.** Jev acierta 44 mensajes que el extractor falla, contra 1 al revés (McNemar exacto, p menor a 0,0001), y va adelante en los dos idiomas.
- **Qué pierde el extractor.** Lo que no viene dicho con sus palabras: 18 de 24 tarjetas perdidas o robadas, 19 de 62 disputas y 15 de 26 pedidos de otro canal.
- **Calibración, casi igual en los dos idiomas.** Error de calibración esperado: 0,07 y 0,09 en "disputa un cargo", 0,04 y 0,05 en "tarjeta perdida o robada", 0,12 y 0,12 en "pide otra cosa" (español y portugués).
- **Jev se equivoca dudando.** En sus 8 errores la respuesta fallida está entre 0,40 y 0,48, la banda en la que la política ya pregunta al cliente.
- **La mezcla por "qué tan seguro está el extractor" no conviene.** Ahorra el 42 % de las llamadas y pierde 11 mensajes: cuando el extractor encuentra una frase de disputa se da por seguro y no ve lo demás que dice el mensaje. La estructura que sí respaldan los datos es la del router: Jev lee el significado, el extractor lee los datos exactos (montos, fechas, sí o no, opción) y toma los turnos triviales y las caídas de Jev.

Límites: una sola persona (el asistente) escribió mensajes y etiquetas el mismo día; el banco se escribió para variar la redacción, que es donde una lista de palabras es más débil; y mide la lectura de un mensaje, no el resultado de una conversación. Detalle en [`reports/intent_hypothesis4_report.md`](../../reports/intent_hypothesis4_report.md).

## 3. Decisiones que necesitan al equipo

| Tema | Qué hay que decidir | Recomendación de esta guía |
| --- | --- | --- |
| Hipótesis 3 | La fila de `docs/PLAN.md` sigue en Propuesta y TQ-023 no tiene respuesta | Reportar el resultado negativo con el pipeline (opción a de TQ-023) |
| Preguntas abiertas | TQ-002, TQ-004, TQ-016, TQ-023, TQ-025 y TQ-040 no tienen respuesta; TQ-038 y TQ-039 dependen del PR #59. TQ-041 a TQ-043 las respondió Kmilo el 5-oct | Responderlas en el archivo; TQ-002 y TQ-004 ya están implementadas como se recomendó |
| Respondidas sin código | TQ-028 (reintentos), TQ-029 (pregunta para reportes de pérdida) y TQ-031 (palabras completas) | Declararlas como límite o implementarlas con su test |
| Respuestas de Claude | Faltan las tareas 3 a 7 y una key | Declarar como trabajo futuro |
| Jev en producción (sección 2.14) | Jev lee mejor los mensajes variados, pero producción no tiene key | Decidir si se pone `TYPESAFE_API_KEY` en Vercel, con el tope diario de 2 USD; y pedir que una segunda persona revise las etiquetas del banco |
| Regla de E5 contra BM25 | Se usó la regla que proponía el roadmap, sin ratificar | Ratificarla; el resultado no cambia lo que sirve Vercel |
| Orden del texto con varios temas (sección 2.13) | La respuesta nombra al especialista antes de ofrecer el bloqueo, aunque el bloqueo es lo pendiente | Invertir el orden del texto; y, tras la entrega, una lista de temas abiertos por conversación |

## 4. Correcciones pendientes a esta guía

- **Cifras del modelo.** [02](02-entendimiento-del-negocio.md) (H1 y H2), [05](05-modelado.md) sección 2.3 y [06](06-evaluacion.md) sección 7 dicen que la medición con el modelo no tiene reporte comprometido; ahora lo tiene.
- **Brecha por país.** [06](06-evaluacion.md) sección 4 la deja como inferencia; la sección 2.4 de este archivo la mide.
- **Preguntas abiertas.** [README](README.md) sección 5 lista TQ-002, TQ-023 y TQ-025; faltan TQ-004 y TQ-016, y desde el 4-oct TQ-038 a TQ-040.
- **Decisiones sin ejecutar.** La tabla de [08](08-iteraciones-y-decisiones.md) omite TQ-029.
- **Foto del estado.** La guía cita `main` en `c71cc09` y los PR #1 a #53; `origin/main` está en `3fe46f9` (PR #58) y el PR #59 está abierto.
- **Auditoría del 4-oct.** Varias afirmaciones dependen de una auditoría que no está en el repo: comprometerla o volver a verificarlas.

## 5. Operación (fuera del repo)

Nada de esto se puede comprobar desde el código; lo destraba quien tenga el acceso ([`docs/HANDOFF.md`](../HANDOFF.md) sec. 7.1):

- Rotar las claves expuestas el 2-oct.
- Aplicar la migración 0005 en producción.
- Confirmar que el registro público está apagado y que la Data API no expone `bank` ni `ops`.
- Borrar las filas de prueba de `cliente-hasta-150`.
- Canario o revisión manual contra la pausa de Supabase (8, 12 y 15 de octubre).
- Repo público sin historial y correo de entrega con las cifras de `reports/`.

## Cómo reproducir

```bash
uv run python -m src.ml.fraud_risk_transfer --competition data/kaggle --lakehouse data/lakehouse_full.duckdb --out reports/ml --model models/fraud_risk_ieee.joblib
uv run python -m src.ml.risk_feature_eda --competition data/kaggle --lakehouse data/lakehouse_full.duckdb --model models/fraud_risk_ieee.joblib --out reports/ml
uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout_model --repeats 3 --systems proposed --model models/fraud_risk_ieee.joblib
uv run python -m src.eval.intervals --out reports/eval_intervals
uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout_explainer --repeats 3 --systems proposed --explainer data/rag_gate.json
uv run python -m src.eval.rag_benchmark --out reports/rag_benchmark_e5 --e5 models/e5-small   # en el contenedor dev
uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout_jev --repeats 3 --systems proposed --jev   # llamadas reales y facturadas a Jev
```

## Fuentes

- Reportes: [`reports/jev_evaluation_report.md`](../../reports/jev_evaluation_report.md), [`reports/eval_heldout_jev.md`](../../reports/eval_heldout_jev.md), [`reports/rag_evaluation_report.md`](../../reports/rag_evaluation_report.md), [`reports/rag_benchmark_e5.md`](../../reports/rag_benchmark_e5.md), [`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md), [`reports/ml/risk_feature_eda.md`](../../reports/ml/risk_feature_eda.md), [`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md), [`reports/eval_intervals.md`](../../reports/eval_intervals.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md), [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md) y sus `.json`.
- Código: `src/ml/risk_feature_eda.py`, `src/ml/ieee_cis_adapter.py`, `src/ml/bank_adapter.py`, `src/ml/feature_contract.py`, `src/eval/intervals.py`; tests `tests/test_risk_feature_eda.py`, `tests/test_eval_intervals.py` y `tests/test_fraud_risk_transfer.py`.
- [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json) en `origin/main` (40 preguntas al 5-oct); [`docs/HANDOFF.md`](../HANDOFF.md) secs. 3 y 7; cuerpo del PR #45 (`gh pr view`).
- [`data/eval/heldout_cases.jsonl`](../../data/eval/heldout_cases.jsonl) para los desgloses por caso, canal y plantilla.
