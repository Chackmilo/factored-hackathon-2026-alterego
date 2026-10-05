# Plan de pendientes

La auditoría del 4-oct sobre esta guía encontró que no falta ningún capítulo: falta evidencia. Tres de las cinco hipótesis no tenían medición comprometida y varias decisiones quedaron sin ejecutar. Este archivo es la lista única de esos pendientes, con su estado, cómo se cierra cada uno y quién lo destraba. Reemplaza las listas repartidas entre [00](00-resumen-ejecutivo.md), [README](README.md) sección 5, [07](07-despliegue.md) sección 10 y [08](08-iteraciones-y-decisiones.md).

Estado al 5-oct, en la rama `analysis/crisp-pending` (creada desde `origin/main` en `3fe46f9`). Todo resultado es offline, sobre casos guionizados o datos de competencia, no una ganancia de producción (`AGENTS.md` sec. 4, regla 11).

## Resumen en una tabla

| Estado | Cuántos | Cuáles |
| --- | --- | --- |
| Hecho en esta rama | 5 | Corrida held-out con el modelo (1), modelo de registro reproducible (2, falta decidir cómo llega a Vercel), comparación solo reglas contra reglas más modelo (5), intervalos y prueba pareada (6), brecha por país de la corrida ciega (11) |
| Siguiente, sin cuentas ni gasto | 5 | E5 contra BM25 (3), explicador en el harness (8), fixture de llegadas tardías (10), tests de los dos bugs leídos del código (12), correcciones a esta guía |
| Necesita una decisión del equipo | 6 | Gasto de Jev (4), residuo numérico del contrato de features (nuevo), licencia de IEEE-CIS, hipótesis 3, preguntas abiertas, respuestas de Claude |
| Necesita personas o acceso | 3 | Etiquetas humanas (7), utilidad del handoff (9), estado de producción |
| Queda como limitación | 2 | Carga y concurrencia (13), familias C y D de la competencia (14) |

## 1. Análisis pendientes

| # | Pendiente | Estado | Cómo se cierra | Evidencia o bloqueo |
| --- | --- | --- | --- | --- |
| 1 | Held-out con el modelo de riesgo (H1, H2) | **Hecho** | `src.eval.run ... --model models/fraud_risk_ieee.joblib`, 3 repeticiones | [`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md); sección 2.2 |
| 2 | Modelo de registro: 0,817 o 0,815 | **Hecho** el modelo; **pendiente** su llegada a Vercel | El entrenador lee sus filas en orden fijo y dos reentrenamientos dan el mismo reporte | Commits `0224320` y `4db45f3`; sección 2.1 |
| 3 | E5 contra BM25 (H5, Tarea 4.2) | Siguiente | `src.rag.onnx_retriever download` y `src.eval.rag_benchmark --e5 models/e5-small` en el contenedor `dev` (`onnxruntime` no tiene rueda para macOS 13) | `reports/rag_benchmark.md` no mide E5 |
| 4 | Jev contra el extractor (H4), con calibración ES y PT | Necesita decisión | Llamadas reales y facturadas a Jev sobre los mensajes del held-out, dentro del tope de 2 USD por día | Falta el visto bueno del gasto y definir la etiqueta de intención (sección 3) |
| 5 | Propuesto contra la versión solo reglas (H1) | **Hecho** para el modelo; falta Jev | Misma suite, reglas contra reglas más modelo, con prueba pareada | [`reports/eval_intervals.md`](../../reports/eval_intervals.md) |
| 6 | Intervalos o pruebas sobre las tasas (hallazgo H09) | **Hecho** | `src.eval.intervals` lee los reportes comprometidos, sin regenerarlos | `reports/eval_intervals.md`; sección 2.3 |
| 7 | Etiquetas humanas y kappa | Necesita personas | Dos personas etiquetan los 50 casos dobles (`data/eval/labeling/README.md`) | Las 4 planillas siguen en 0 de 300 filas; cerrada como limitación (TQ-018) |
| 8 | Explicador de políticas de punta a punta | Siguiente | Un modo del harness con el explicador encendido, y comparar caso por caso con la corrida sin él | El harness corre sin explicador; producción lo tiene encendido |
| 9 | Utilidad del handoff | Necesita personas | Una rúbrica y revisión humana; el código solo puede revisar que el paquete venga completo | El juez revisa la escalación y su razón, nada más |
| 10 | Fixture de llegadas tardías (`AGENTS.md` sec. 7) | Siguiente | Un fixture etiquetado y un test: silver se queda con el `process_date` más reciente | No hay ninguno en `tests/`, `src/` ni `data/fixtures/` |
| 11 | Brecha por país de la corrida ciega | **Hecho** | Desglose por plantilla del reporte ciego | Sección 2.4 |
| 12 | Tests de los dos bugs leídos del código (idioma fijo tras `new`; segunda pregunta de reglas tras un saludo) | Siguiente | Un test que reproduzca cada uno. El arreglo espera la decisión del equipo | Ningún test los demuestra |
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

## 3. Decisiones que necesitan al equipo

| Tema | Qué hay que decidir | Recomendación de esta guía |
| --- | --- | --- |
| Gasto de Jev (H4) | Si se autorizan llamadas facturadas para medir Jev contra el extractor, y qué etiqueta de intención se usa | Medir sobre los 250 primeros mensajes del held-out, con la intención esperada derivada de la etiqueta de diseño |
| Residuo numérico (sección 2.5) | Si se trata una desviación menor a un épsilon como cero, con contrato 1.2 y modelo nuevo | Sí, después de la entrega; registrar como pregunta del equipo (la siguiente libre es TQ-041) |
| Licencia de IEEE-CIS | TQ-032 y `README.md` dicen aprobada; TQ-026, una fila de `docs/PLAN.md` y la spec del modelo, pendiente | Alinear las cuatro fuentes con la respuesta de TQ-032, si Kmilo confirma la aprobación |
| Hipótesis 3 | La fila de `docs/PLAN.md` sigue en Propuesta y TQ-023 no tiene respuesta | Reportar el resultado negativo con el pipeline (opción a de TQ-023) |
| Preguntas abiertas | TQ-002, TQ-004, TQ-016, TQ-023, TQ-025 y TQ-040 no tienen respuesta en `origin/main`; TQ-038 y TQ-039 dependen del PR #59 | Responderlas en el archivo; TQ-002 y TQ-004 ya están implementadas como se recomendó |
| Respondidas sin código | TQ-028 (reintentos), TQ-029 (pregunta para reportes de pérdida) y TQ-031 (palabras completas) | Declararlas como límite o implementarlas con su test |
| Respuestas de Claude | Faltan las tareas 3 a 7 y una key | Declarar como trabajo futuro |
| Cómo llega el modelo a Vercel | El `.joblib` pesa 1,3 MB y está en `.gitignore` | Decidir si se versiona el bundle o se construye en el build |

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
```

## Fuentes

- Reportes: [`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md), [`reports/ml/risk_feature_eda.md`](../../reports/ml/risk_feature_eda.md), [`reports/eval_heldout_model.md`](../../reports/eval_heldout_model.md), [`reports/eval_intervals.md`](../../reports/eval_intervals.md), [`reports/eval_heldout.md`](../../reports/eval_heldout.md), [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md) y sus `.json`.
- Código: `src/ml/risk_feature_eda.py`, `src/ml/ieee_cis_adapter.py`, `src/ml/bank_adapter.py`, `src/ml/feature_contract.py`, `src/eval/intervals.py`; tests `tests/test_risk_feature_eda.py`, `tests/test_eval_intervals.py` y `tests/test_fraud_risk_transfer.py`.
- [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json) en `origin/main` (40 preguntas al 5-oct); [`docs/HANDOFF.md`](../HANDOFF.md) secs. 3 y 7; cuerpo del PR #45 (`gh pr view`).
- [`data/eval/heldout_cases.jsonl`](../../data/eval/heldout_cases.jsonl) para los desgloses por caso, canal y plantilla.
