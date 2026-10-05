# CRISP-DM 3. Preparación de los datos

La preparación convierte los CSV del organizador en tres productos: un lakehouse local en DuckDB para análisis y ML, una copia mínima en Postgres para la app y conjuntos de prueba y evaluación con procedencia declarada. Cada regla de limpieza responde a un hallazgo de [Entendimiento de los datos](03-entendimiento-de-los-datos.md).

Respuesta corta: silver deduplica por clave de negocio y corrige `amount_usd` con su origen; gold calcula la ventana con `process_date` y la fecha de negocio fija 2026-06-17. A Postgres viajan 253 clientes, sin `is_fraud`, `fraud_score`, documentos ni contactos. La suite held-out de 250 casos se construyó desde la muestra y se congeló con su SHA-256 el 30-sep.

## El pipeline en una tabla

| Paso | Entrada | Salida | Regla | Archivo |
| --- | --- | --- | --- | --- |
| 1. Bronze | CSV en S3 | `bronze_*` (tasas, sucursales, clientes, productos, quejas, transacciones) | Lectura directa; muestra o carga completa (sección 1) | [`src/data/ingestion.py`](../../src/data/ingestion.py) |
| 2. Cuarentena | `bronze_transactions` | `quarantine_duplicate_transactions` | Filas repetidas por clave de negocio | `src/data/ingestion.py` |
| 3. Silver transacciones | `bronze_transactions`, tasas diarias | `silver_transactions` | Una fila por clave de negocio; `amount_usd` corregido; la carga falla sin tasa | `src/data/ingestion.py` (`build_silver_transactions`) |
| 4. Silver dimensiones y quejas | `bronze_customers`, `bronze_products`, `bronze_complaints` | `silver_customers`, `silver_products`, `silver_complaints` | Último registro por id; quejas por clave de negocio | `src/data/ingestion.py` |
| 5. Gold transacciones | `silver_transactions`, `silver_products` | `gold_transactions` | Ventana de 60 días con `process_date` contra 2026-06-17 | `src/data/ingestion.py` (`build_gold_transactions`) |
| 6. Gold clientes | `silver_customers`, `silver_complaints`, `silver_products` | `gold_customers` | Antigüedad, cuenta madura (más de 180 días), quejas de 90 días, productos activos | `src/data/ingestion.py` |
| 7. Copia de servicio | Gold, silver y tasas de bronze en DuckDB; lista de clientes | Esquema `bank` en Postgres | Minimizar, normalizar, recargar en una transacción, verificar paridad | [`src/data/publish_serving.py`](../../src/data/publish_serving.py) |
| 8. Tablas auxiliares | CSV en S3 | `data/lakehouse_aux.duckdb` | Llamadas, transcripciones, encuestas, eventos y envíos, mes a mes | [`scripts/data_ops/load_aux_tables.py`](../../scripts/data_ops/load_aux_tables.py) |
| 9. Suite held-out | Muestra del lakehouse, semilla 20260930 | `data/eval/heldout_cases.jsonl` y su `.sha256` | Mezcla del brief; etiquetas de diseño; congelada | [`src/eval/heldout.py`](../../src/eval/heldout.py) |
| 10. Features de riesgo | Historia del cliente en la copia de servicio | 19 features del contrato | Solo filas anteriores; rangos por fuente | [`src/ml/feature_contract.py`](../../src/ml/feature_contract.py), [`src/ml/bank_adapter.py`](../../src/ml/bank_adapter.py) |

Los archivos `data/*.duckdb` están fuera de git (`.gitignore`). Se reconstruyen con los comandos de [`CLAUDE.md`](../../CLAUDE.md), sección "Commands".

## 1. Muestra o carga completa

El equipo mantiene dos lakehouses porque la app y el ML necesitan cosas distintas.

| Atributo | Muestra (`data/lakehouse.duckdb`) | Carga completa (`data/lakehouse_full.duckdb`) |
| --- | --- | --- |
| Clientes | Las primeras 25.000 filas de `customers.csv` | Los 150.000 |
| Productos y quejas | Solo de esos clientes; quejas de 2026 | Todos; quejas de todos los años |
| Transacciones | Junio de 2026, en una lectura: 11.703 filas | Junio de 2023 a junio de 2026, mes a mes con hasta 3 intentos por mes: 4.425.008 filas |
| Tiempo y tamaño | La carga tomó 9 minutos (contexto de TQ-013) | Cerca de 800 MB desde S3; construida en 391 s |
| Para qué | Gateway local, política, notebook 01, suite held-out, copia de servicio | Modelo sin fuga (notebook 02), búsqueda de señal (03, 04), homologación (05), calibración del umbral de riesgo |
| Fuente | `src/data/ingestion.py`; notebook 01, celda 5 | `AGENTS.md` sec. 7; TQ-013 |

La muestra filtra productos, quejas y transacciones por sus clientes, así que no tiene huérfanos (`AGENTS.md` sec. 9); como `customers.csv` viene en orden aleatorio, sus 25.000 filas reflejan la mezcla de países y segmentos ([`CLAUDE.md`](../../CLAUDE.md), `src/data/`). Pero no basta para el ML: junio de 2026 trae 9 fraudes y ningún cargo fuera de ventana (`AGENTS.md` sec. 9). El equipo aprobó la carga completa en un archivo aparte el 27-sep para no reescribir el lakehouse que leen la API y los tests de integridad de datos (TQ-013). Los cargos de 61 a 77 días salieron de abril con un sondeo de solo lectura; uno quedó como fixture (sección 6).

## 2. Silver: deduplicación y cuarentena

La trampa de duplicados no se observó (`AGENTS.md` sec. 7), pero silver deduplica igual. Solo las transacciones dejan rastro de lo que se quita, en `quarantine_duplicate_transactions`; clientes, productos y quejas se deduplican sin tabla de cuarentena (`src/data/ingestion.py`).

| Tabla | Clave | Fila que se queda |
| --- | --- | --- |
| `silver_transactions` | `customer_id`, `amount`, `currency`, `merchant_name` (nulo como `UNKNOWN`), minuto de `transaction_date` | La de `process_date` más reciente; las demás van a `quarantine_duplicate_transactions` |
| `silver_customers` | `customer_id` | La de `last_updated` más reciente |
| `silver_products` | `product_id` | La de `last_updated` más reciente |
| `silver_complaints` | `customer_id`, `category`, `subcategory`, `affected_product_id` (nulo como `UNKNOWN`), día de `creation_date` | La de `process_date` más reciente |

En la carga completa del 27-sep la clave de negocio no encontró duplicados (`AGENTS.md` sec. 7, "Verified findings"). Quedarse con el `process_date` más reciente cubriría un reproceso tardío si existiera (inferido).

## 3. Silver: `amount_usd` corregido con su origen

`amount_usd` se corrige una sola vez, en silver, y todo lo que viene después lee ese valor (TQ-001 y TQ-003, decididas el 27-sep; commit `1d7eb71`, en `main` por el PR #14).

| Caso | `amount_usd` | `amount_usd_source` |
| --- | --- | --- |
| `currency = 'USD'` | Copia de `amount` | `same_currency` |
| Valor nativo presente | Se conserva | `native` |
| COP o ARS sin valor | `ROUND(amount * tasa, 2)` con la tasa media del `process_date` | `daily_rate_fill` |

Reglas:

- **El valor crudo se conserva** en `amount_usd_legacy`, y la tasa usada en `amount_usd_fx_rate`. Es el camino de vuelta atrás.
- **Sin tasa, la carga falla** con `IngestionContractError`. Nunca se usa el respaldo `1.0`, que trataba pesos como dólares (`docs/technical-discuss-points.md` sec. 1.4).
- **Gold lleva solo `amount_usd` y `amount_usd_source`.** La columna antigua `amount_usd_normalized` se eliminó (`docs/technical-discuss-points.md` sec. 4).

Resultado: en la muestra de junio se rellenaron 291 filas y quedan 0 nulos. En la carga completa se rellenaron 99.477 filas COP y ARS (5,0 % de las no USD) (`AGENTS.md` sec. 7). El relleno reproduce los valores nativos con una diferencia máxima de 2,01 % (`docs/technical-discuss-points.md` sec. 1.1). TQ-002 (fallar o poner en cuarentena) no tiene respuesta registrada, pero el código implementa la recomendación: fallar.

## 4. Tiempo: `process_date` y la fecha de negocio congelada

### 4.1 `process_date`

`process_date` viene en el CSV. El equipo verificó que es igual a fecha(`transaction_date` - 6 h) en el 100 % de las filas de junio, y el pipeline lo usa tal cual (`AGENTS.md` sec. 7).

| Dónde | Cómo usa el tiempo | Fuente |
| --- | --- | --- |
| Gold | `is_within_60_days` y `days_since_transaction` con `process_date` contra 2026-06-17 | `src/data/ingestion.py`, `build_gold_transactions` |
| Política | Si recibe la marca cruda, le resta 6 h; si recibe una fecha, debe ser ya `process_date` | [`src/rules/dispute_policy.py`](../../src/rules/dispute_policy.py), línea 361 |
| Features de riesgo | Hora y día del reloj de proceso (`transaction_date` menos 6 h) | `src/ml/bank_adapter.py`; spec del modelo, sec. 4 |
| Copia de servicio | `transaction_date` como timestamp sin zona y `process_date` como fecha, sin recalcular en Postgres | `src/data/publish_serving.py`; `docs/SUPABASE_VERCEL.md` sec. 4.3 |

Historia: el gold original contaba la ventana con el cast simple, y 227 cargos del 17 de junio quedaban con -1 días. El commit `8632e96` (26-sep) alineó la ventana al día de proceso UTC-6 y agregó chequeos de integridad.

### 4.2 La fecha de negocio 2026-06-17

"Hoy" es 2026-06-17, el último día del dataset. La ventana y la antigüedad de cuenta usan esa fecha, nunca el reloj ([`CLAUDE.md`](../../CLAUDE.md), "Gotchas"). Está escrita en varios lugares que cambian juntos: `src/data/ingestion.py`, `src/data/publish_serving.py`, `src/eval/heldout.py`, `src/eval/fixture_bank.py`, `src/orchestrator/dispute_orchestrator.py`, `src/rules/dispute_policy.py`, `src/tools/gateway_postgres.py`, `src/understand/keyword_extractor.py` y `ops.business_today()` en [`supabase/migrations/0003_bank.sql`](../../supabase/migrations/0003_bank.sql) (búsqueda de texto del 4-oct).

Dos copias confunden (`CLAUDE.md`, "Gotchas"): `ingestion.py` redefine `ANCHOR_DATE` dentro del bloque de gold, y esa es la copia que usa el SQL de gold; y en la app la política recibe el `today` del orquestador como `current_date`, así que el valor por defecto de `DisputePolicyInput` solo llega a quien llama la política directo, como sus tests.

### 4.3 Dos relojes

Las filas de `ops` llevan la hora real del reloj, mientras el negocio vive el 2026-06-17. Gold es una foto y no ve los casos que abre la app, así que el orquestador suma los casos de `ops` a `complaints_last_90d` con la regla de la vista `ops.v_customer_policy_facts` (`CLAUDE.md`, "Gotchas").

Esa vista cuenta los casos de `ops` con `created_at` mayor o igual a `business_today() - 90`, sin tope superior (`0003_bank.sql`, línea 94). Con la fecha de negocio fija, todo caso que abre la app cuenta (`CLAUDE.md`, "Gotchas"). Un efecto en producción: una conversación de la prueba de humo abrió un caso real para la persona `cliente-hasta-150`, y como ese cargo ya tiene caso abierto, la demo de esa persona no puede abrir otro hasta borrar esas filas desde el SQL Editor ([`docs/HANDOFF.md`](../HANDOFF.md), tarea A2, del 3-oct). El orquestador registra ese bloqueo como `DUPLICATE_CASE_PREVENTED` (`src/orchestrator/dispute_orchestrator.py`). Esta guía no verificó si las filas ya se borraron; el estado registrado y el reseteo están en [01-guia-de-uso.md](01-guia-de-uso.md), sección 1.5.

## 5. Copia de servicio en Postgres (`bank`)

La app desplegada nunca abre DuckDB. Lee un subconjunto mínimo publicado en el esquema `bank` de Supabase, de solo lectura, y escribe solo en `ops` (`docs/SUPABASE_VERCEL.md` sec. 4.1; `AGENTS.md` sec. 8).

`src/data/publish_serving.py`, en este orden:

1. Abre el lakehouse en solo lectura y filtra por la lista de clientes, si la recibe.
2. Normaliza "Mexico" a "México" en `country` y `transaction_country`.
3. Pasa `amount_usd` y su origen como vienen de gold; solo si faltan, rellena con la tasa del día y falla sin tasa.
4. Cuenta las filas huérfanas (de clientes no publicados) y no las carga.
5. Vacía y recarga `bank` en una sola transacción. Nunca toca `ops`.
6. Verifica la paridad de conteos por tabla, que no haya columnas prohibidas en `bank` y que `max(process_date)` no pase de 2026-06-17, y lanza `PublishError` si algo falla. Esos contratos corren después del commit, así que una falla no deshace la carga (inferido por lectura del código).

Qué viaja y qué no ([`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 4.2; columnas prohibidas en `FORBIDDEN_COLUMNS`):

| Tabla `bank` | Viaja | No viaja |
| --- | --- | --- |
| `customers` | id, nombre completo, país, ciudad, segmento, fecha de registro, estado | Documento, correo, teléfono, score crediticio, consentimiento de marketing |
| `products` | id, cliente, tipo, estado, moneda, apertura, vencimiento, últimos 4 dígitos | Número completo de producto, saldos, límites |
| `transactions` | Fechas, tipo, monto, moneda, `amount_usd` y su origen, canal, comercio, país, ciudad, estado | `is_fraud`, `fraud_score` |
| `complaints` | Fechas, tipo, categoría, subcategoría, estado, monto reclamado, moneda, reincidente | `description`, `resolution`, `affected_product_id` |
| `exchange_rates` | Tasas diarias hacia USD | Nada |

El nombre completo sí viaja: es sintético, pero tiene forma de dato personal, y `FORBIDDEN_COLUMNS` no lo incluye (inferido por lectura del código).

**Qué clientes.** [`data/serving_customers.json`](../../data/serving_customers.json) está en git (procedencia `team-generated`, commit `27a2747`, PR #35). Lista 253 clientes: los de las 3 personas de demo con rol de cliente (la cuarta, `agente`, no tiene cliente) y los 250 de la suite held-out. Los clientes del split de desarrollo (`CLI-DEV-*`) son sintéticos y no están en el lakehouse. El 3-oct se publicó con paridad en todas las tablas: 253 clientes, 902 productos, 385 transacciones, 18 quejas y 3.291 tasas, sin columnas prohibidas (descripción del PR #35; [`docs/HANDOFF.md`](../HANDOFF.md) sec. 1).

**Uso autorizado.** La fila "Uso de datos en el despliegue y en los modelos" de [`docs/PLAN.md`](../PLAN.md) quedó decidida el 2-oct: los mentores aprobaron, según Daniel (TQ-032). TQ-014 ya registraba un "Yes" el 27-sep.

**Lectura viva frente a foto.** El gateway de DuckDB lee `gold_*`, que queda desactualizado hasta otra ingesta; el de Postgres lee vistas vivas sobre `bank` y `ops` y escribe el bloqueo en `ops.card_locks`, nunca en `bank` (`CLAUDE.md`, "Gotchas").

## 6. Fixtures de prueba (regla 12)

Los datos son estáticos, así que la corrección de las escrituras se prueba con fixtures etiquetados (`AGENTS.md` sec. 4, regla 12). Los tests del gateway y del orquestador nunca leen el lakehouse real.

`bank_fixture_db` en [`tests/conftest.py`](../../tests/conftest.py) es `team-generated`: 2 clientes, 2 tarjetas más una cuenta de ahorros y 8 cargos. Cada cargo prueba algo:

| Cargo | Qué prueba |
| --- | --- |
| 80 USD a las 03:15 del 10 de junio, día de proceso 9 de junio | El desfase de 6 horas |
| 120 USD en Cine Premium | Caso normal |
| 850 USD | `POL-ESC-500` |
| 45 USD declinado | `POL-DISP-TYPE` |
| 60 USD del 19 de marzo (90 días) | `POL-WIN-60` |
| Dos cargos de 35 USD en comercios distintos | Aclaración entre candidatos |
| 50 USD del otro cliente | Propiedad: nunca ver cargos ajenos |

Otros datos de prueba:

- **`fixture_db`** en `tests/test_dispute_flow.py`, para el flujo de disputa.
- **`src/eval/fixture_bank.py`** arma un banco DuckDB pequeño por cada caso de evaluación, con los esquemas del lakehouse.
- **[`data/fixtures/abstention_pol_win_60.json`](../../data/fixtures/abstention_pol_win_60.json)** (`synthetic-organizer`): un cargo real de abril, de 324.599,21 COP (81,15 USD), a 77 días; la política se abstiene con `POL-WIN-60`.
- **`tests/test_data_integrity.py`**: 6 tests sobre el lakehouse real. Se saltan si el archivo no existe y la CI los excluye, así que una corrida verde sin lakehouse no revisó los datos (`CLAUDE.md`, "Gotchas").
- **`data/synthetic_samples.json`** (`team-generated`): 4 escenarios en inglés y USD para la demo del baseline (`AGENTS.md` sec. 9).

## 7. Datos de evaluación

### 7.1 Split de desarrollo

[`data/eval/dev_cases.jsonl`](../../data/eval/dev_cases.jsonl) tiene 19 casos `team-generated`: 14 en español y 5 en portugués, con clientes sintéticos `CLI-DEV-*`. No trae ataques ni fallas inyectadas. DEV-019 entró el 3-oct (commit `51c8c8d`, PR #46) para fijar que una pregunta de reglas nunca abra el único cargo de un cliente.

### 7.2 Suite held-out

[`data/eval/heldout_cases.jsonl`](../../data/eval/heldout_cases.jsonl) tiene 250 conversaciones guionizadas, 150 en español y 100 en portugués, en las diez categorías del brief. `src/eval/heldout.py` las construyó desde la muestra de junio con la semilla 20260930. La mezcla por categoría y por resultado esperado está en [Evaluación](06-evaluacion.md), sección 2.

Cómo se construyó (docstring y funciones de `src/eval/heldout.py`; conteos sobre el archivo):

1. **Clientes y cargos reales donde se puede.** Estratos de 4 segmentos por 3 países: 60 a 64 casos por segmento y 83 a 84 por país.
2. **Procedencia por caso.** 63 casos son `derived`: español sobre filas sin cambios. 187 son `team-generated`: todo el portugués y todo hecho fabricado o alterado (cargos movidos 65 a 110 días atrás, compras extranjeras inventadas, montos USD borrados, fechas futuras, clientes ausentes). Los mensajes siempre son plantillas del equipo.
3. **Ataques por la API (12).** 6 de token (ausente, HS256, `alg: none`, otro emisor, vencido, alterado) y 6 entre clientes (3 leen una conversación ajena y 3 escriben en ella).
4. **Fallas inyectadas (20).** 6 casos donde la lectura del caso no devuelve nada, 5 bloqueos cuya lectura de verificación falla, 5 búsquedas de cargos y 4 lecturas de perfil que vencen por tiempo.
5. **Etiquetas de diseño.** Cada expectativa sale de la spec por construcción, nunca de correr el sistema (`label_source: design`). Mezcla esperada: 107 resoluciones autónomas, 98 escalamientos, 29 abstenciones, 12 rechazos y 4 aclaraciones.
6. **Congelada el 30-sep.** El SHA-256 de `data/eval/heldout_cases.sha256` coincide con el archivo (verificado el 4-oct). `.gitattributes` mantiene LF para que el hash se sostenga en Windows. Reconstruir la suite debe reproducir ese hash (`CLAUDE.md`, "Commands").

**Etiquetado humano.** Las cuatro planillas de `data/eval/labeling/` (75 casos cada una, con 50 casos en dos planillas para kappa) están vacías: 0 etiquetas. TQ-018 (4-oct) declaró el doble etiquetado como limitación.

### 7.3 Banco de preguntas de política y corpus

- **Corpus.** [`data/policy_corpus.json`](../../data/policy_corpus.json) (`team-generated`, política v2.3) tiene 13 cláusulas: 8 públicas, 2 públicas genéricas y 3 internas. Las internas no tienen respuesta y comparten un desvío sin id de cláusula (TQ-037). Lo redactó Claude Code el 30-sep; el portugués espera revisión del equipo (nota del propio archivo).
- **Preguntas.** `data/eval/policy_questions_dev.jsonl` y `policy_questions_test.jsonl` tienen 30 preguntas cada uno: 15 ES y 15 PT; 18 para responder, 5 para aclarar y 7 para abstenerse. Procedencia `team-generated, LLM-drafted`.
- **Desviaciones aceptadas.** Las 60 preguntas las redactó un agente LLM del IDE después de leer el corpus, palabras clave incluidas. 8 de 18 preguntas de dev y 7 de 18 de test traen alguna palabra clave de su cláusula ([`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md), Tarea 1.2).
- **Congelamiento.** El test se congeló en el commit `44e3e90`; su SHA-256 coincide con `policy_questions_test.sha256` (verificado el 4-oct). Los umbrales de [`data/rag_gate.json`](../../data/rag_gate.json) salen solo de dev, con el hash de dev y del corpus registrados.

## 8. Features del modelo de riesgo

El modelo transferido usa 19 features que la app desplegada puede calcular desde la copia de servicio (`DEPLOYABLE_V1`, contrato 1.1; decisión del 29-sep).

| Grupo | Features | En el banco |
| --- | --- | --- |
| Monto | `amount_usd`, `log_amount_usd`, `amount_has_cents` | `amount_usd` y `amount` |
| Reloj de proceso | `hour_sin`, `hour_cos`, `day_of_week` | `transaction_date` menos 6 h |
| Tipo de tarjeta | `card_kind_credit`, `card_kind_debit` | `product_type` |
| Historia de la tarjeta | `days_since_prev_tx_card`, `tx_count_card_1d`, `tx_count_card_7d`, `tx_count_card_30d`, `tx_sum_card_7d`, `amount_mean_card_hist`, `amount_std_card_hist`, `amount_zscore_card` | Por `product_id`, solo filas anteriores |
| Historia del cliente | `ratio_to_historical_avg` | Por `customer_id`, solo filas anteriores |
| Ubicación | `address_distance_bucket`, `consistency_matches` | País y ciudad del cargo, ciudad y país del cliente, moneda del producto |

Reglas de preparación:

- **Nunca mirar al futuro.** Cada agregado usa solo filas anteriores de la tarjeta o del cliente (`src/ml/feature_contract.py`).
- **Sin fuga.** El entrenador rechaza `is_fraud`, `fraud_score`, `transaction_status`, `response_code`, `resolution` y `compensation_granted` (`LEAK_COLUMNS`).
- **Rangos por fuente.** Las features continuas entran como rangos percentiles calculados por separado en cada fuente. El entrenador guarda en el bundle las medianas de entrenamiento, y al servir los nulos se llenan con ellas ([`src/ml/fraud_risk_transfer.py`](../../src/ml/fraud_risk_transfer.py), [`src/ml/transfer_scorer.py`](../../src/ml/transfer_scorer.py)).
- **Antigüedad de la tarjeta fuera.** El contrato tiene 20 features; `card_age_days` es la única que queda fuera de `DEPLOYABLE_V1`, porque el 18,71 % de los cargos es anterior a la apertura de su producto.
- **Ubicación calculada al servir.** Antes, al servir, las dos features de ubicación tomaban siempre la mediana de entrenamiento (AUD-27). Desde el PR #45 ambos gateways devuelven país y ciudad del cargo, moneda del producto y ciudad del cliente, y el fixture de evaluación también los conserva (`CLAUDE.md`, "Gotchas").
- **Solo Web y App.** Los cargos de otros canales no se califican (`src/ml/transfer_scorer.py`).

Hasta el 5-oct producción no tenía el archivo del modelo, porque estaba fuera de git y Vercel construye desde GitHub, así que ahí `POL-ESC-ML-RISK` nunca se disparaba (commit `a18f045`). Ese día el bundle entró a git, y producción lo sirve desde el despliegue de `58ab501` (`README.md`, "Limitations"). El modelo está en [Modelado](05-modelado.md), sección 2.3.

## 9. Privacidad: PII enmascarada antes de cualquier modelo

Ningún modelo ve el mensaje crudo del cliente. `PIIMasker` ([`src/privacy/pii_masker.py`](../../src/privacy/pii_masker.py)) reemplaza con marcadores, en este orden: números de tarjeta, correos, documentos latinoamericanos (CURP, CPF, DNI, cédula), teléfonos, SSN e IBAN.

- **Los montos sobreviven.** Los teléfonos exigen prefijo, paréntesis o separadores, así que un monto de 7 dígitos en COP o ARS no se enmascara (SEC-05).
- **Montos y fechas salen del texto crudo, en local.** El extractor de palabras clave los lee antes de enmascarar ([`src/understand/router.py`](../../src/understand/router.py)).
- **Jev y el explicador ven solo el texto enmascarado.** El orquestador guarda el mensaje enmascarado, nunca el crudo ([`src/orchestrator/dispute_orchestrator.py`](../../src/orchestrator/dispute_orchestrator.py), `handle_message`).
- **Los comercios son datos no confiables.** El gateway envuelve `merchant_name` en etiquetas `<untrusted_merchant_data>`; el held-out trae 4 casos de inyección en el nombre del comercio, HO-202 a HO-205 (`CLAUDE.md`; `src/tools/gateway.py`; `data/eval/heldout_cases.jsonl`).

## 10. Procedencia de cada artefacto

| Artefacto | Procedencia | En git |
| --- | --- | --- |
| Tablas `bronze_*`, `silver_*` y gold sin cálculos | `synthetic-organizer` | No (`*.duckdb`) |
| `amount_usd` rellenado, ventana, antigüedad, quejas de 90 días | `derived` | No |
| Esquema `bank` en Postgres | `derived` de `synthetic-organizer` | No (datos en Supabase) |
| `data/fixtures/abstention_pol_win_60.json` | `synthetic-organizer` (fila elegida por el equipo) | Sí |
| `data/serving_customers.json`, `data/fixtures/personas.json` | `team-generated` (ids del dataset) | Sí |
| `tests/conftest.py`, `data/synthetic_samples.json` | `team-generated` | Sí |
| `data/eval/dev_cases.jsonl` | `team-generated` | Sí |
| `data/eval/heldout_cases.jsonl` | 63 `derived`, 187 `team-generated` | Sí, con SHA-256 |
| `data/policy_corpus.json` | `team-generated` | Sí |
| `data/eval/policy_questions_*.jsonl` | `team-generated, LLM-drafted` | Sí; test con SHA-256 |
| `data/kaggle/` (IEEE-CIS) | Externo: e-commerce real desidentificado, competencia de Kaggle | No |
| `models/fraud_risk_ieee.joblib` | Entrenado con datos externos | No |

## Contradicciones y lecturas con cuidado

- **`data/README.md` está desactualizado.** Su clave de deduplicación (`customer_id`, `transaction_date`, `amount`, `merchant_name`) no trae `currency` ni el corte al minuto del código, y nombra `amount_usd_normalized`, que ya no existe.
- **Tamaño del split de desarrollo.** La pregunta de TQ-018 y la fila del día 3 de `docs/PLAN.md` hablan de 18 casos; el archivo tiene 19 desde el 3-oct. La fila "Suite de evaluación" de `docs/PLAN.md` planeaba 60.
- **Cuarentena en la publicación.** `docs/SUPABASE_VERCEL.md` sec. 4.3 propone una tabla de cuarentena en DuckDB y `AGENTS.md` sec. 9 dice "orphans quarantined"; `publish_serving.py` solo reporta conteos.
- **Llegadas tardías.** `AGENTS.md` sec. 7 pide demostrarlas con un fixture etiquetado. Existe desde el 5-oct: `data/fixtures/late_arrival_transactions.json` (`team-generated`), con un cargo procesado cinco días tarde y una fila reprocesada ([Plan de pendientes](09-plan-de-pendientes.md), sección 2.8).

## Fuentes

- [`src/data/ingestion.py`](../../src/data/ingestion.py), [`src/data/publish_serving.py`](../../src/data/publish_serving.py), [`scripts/data_ops/load_aux_tables.py`](../../scripts/data_ops/load_aux_tables.py).
- [`supabase/migrations/0001_ops.sql`](../../supabase/migrations/0001_ops.sql) y [`supabase/migrations/0003_bank.sql`](../../supabase/migrations/0003_bank.sql).
- [`src/eval/heldout.py`](../../src/eval/heldout.py), `src/eval/fixture_bank.py`, [`tests/conftest.py`](../../tests/conftest.py).
- [`src/ml/feature_contract.py`](../../src/ml/feature_contract.py), [`src/ml/bank_adapter.py`](../../src/ml/bank_adapter.py), [`src/ml/fraud_risk_transfer.py`](../../src/ml/fraud_risk_transfer.py), [`src/privacy/pii_masker.py`](../../src/privacy/pii_masker.py).
- [`AGENTS.md`](../../AGENTS.md): sec. 4, 7, 8 y 9. [`CLAUDE.md`](../../CLAUDE.md): "Commands", "Architecture", "Gotchas".
- [`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md): sec. 4. [`docs/technical-discuss-points.md`](../technical-discuss-points.md): sec. 1 y 4.
- [`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md): sec. 4 y 10. [`docs/RAG_IMPLEMENTATION_ROADMAP.md`](../RAG_IMPLEMENTATION_ROADMAP.md): Tarea 1.2.
- [`docs/PLAN.md`](../PLAN.md): registro de decisiones. [`README.md`](../../README.md): "What runs today", "Limitations".
- Datos: `data/eval/` (conteos y SHA-256 verificados el 4-oct), `data/serving_customers.json`, `data/policy_corpus.json`, `data/rag_gate.json`, `data/fixtures/`.
- [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json): TQ-001, TQ-002, TQ-003, TQ-013, TQ-014, TQ-018, TQ-032, TQ-037.
- PR #14, #35, #45 y #46; commits `1d7eb71`, `8632e96`, `27a2747`, `44e3e90`, `51c8c8d` y `a18f045`.
- [`docs/HANDOFF.md`](../HANDOFF.md): sec. 1 y tarea A2 (caso abierto de la persona `cliente-hasta-150`).
