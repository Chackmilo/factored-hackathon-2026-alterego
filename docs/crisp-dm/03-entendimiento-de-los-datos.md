# CRISP-DM 2. Entendimiento de los datos

Los datos del organizador sostienen el workflow de disputas, pero no un modelo de fraude entrenado con ellos. Esta fase resume qué trae el dataset LATAM Bank, qué trampas de calidad tiene, qué encontró el equipo al perfilarlo y qué decisión de diseño cambió cada hallazgo.

Respuesta corta: las quejas por cargos justifican el workflow, y los montos, fechas y tipos de cargo fijan los umbrales de la política. La etiqueta `is_fraud` no tiene señal aprendible y `fraud_score` la filtra. Por eso la política es código y el puntaje de riesgo viene de un modelo entrenado en un dataset externo (IEEE-CIS).

## Resumen en una tabla

| Tema | Hallazgo | Consecuencia | Fuente |
| --- | --- | --- | --- |
| Dataset | LATAM Bank v1.0.0, 100 % sintético, 13 tablas, cerca de 19 millones de filas, México, Colombia y Argentina, del 2023-06-17 al 2026-06-17 | Ningún cliente real; procedencia `synthetic-organizer` | [`AGENTS.md`](../../AGENTS.md) sec. 7 |
| Idioma | Todo el texto está en español; no hay portugués ni Brasil | Todo caso en portugués es `team-generated` | `AGENTS.md` sec. 7 |
| Tiempo | Cada partición diaria va de 06:00 a 05:59 del día siguiente; el cast simple de la fecha falla en el 24 % de las filas | La ventana se cuenta con `process_date` | `AGENTS.md` sec. 7, "Verified findings" |
| Montos | Mediana cerca de 470 USD; 3.547 de 8.967 cargos disputables de junio (39,6 %) superan 500 USD | Techo de contención de 60,4 % con `POL-ESC-500` | `AGENTS.md` sec. 7; [`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md) sec. 5 |
| Fraude | `fraud_score` filtra `is_fraud`, e `is_fraud` no tiene señal (ROC AUC de test 0,497) | Riesgo transferido de IEEE-CIS con umbral por percentil | [`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md) |
| Quejas y llamadas | Quejas, marcas de fraude y transcripciones son independientes; las transcripciones son plantillas | Ninguna métrica de "tasa de reclamo"; la señal de texto sale del chat | [`notebooks/04_claims_vs_flags_and_transcript_nlp.ipynb`](../../notebooks/04_claims_vs_flags_and_transcript_nlp.ipynb) |
| Identidad digital | `digital_events` no se puede unir a un cargo | Sin features de dispositivo ni de IP | [`docs/technical-discuss-points.md`](../technical-discuss-points.md) sec. 7 |

## 1. El dataset

LATAM Bank Dataset v1.0.0 es 100 % sintético y lo entregó el organizador (`AGENTS.md` sec. 7). Trae 13 tablas, tres países sin Brasil y monedas MXN, COP, ARS y USD con conversión diaria a USD. Todo el texto está en español, con acentos mexicano, colombiano y argentino. Vive en S3 (`us-east-2`) como CSV; los hechos están particionados por `year=/month=/day=` (cerca de 5,3 GB en unos 7.700 objetos).

El prefijo `data_backup_20260831/` es otra generación de datos, no una copia: comparte solo el 3,2 % de los ids de transacciones de julio de 2023 (3.878 de unos 121.000), con otros montos y fechas. El equipo ingiere solo `data/`.

| Tabla | Filas documentadas | Filas observadas | Fuente de lo observado |
| --- | --- | --- | --- |
| transactions | 5.000.000 | 4.425.008 (carga completa) | `AGENTS.md` sec. 7 |
| call_center_interactions | 800.000 | 686.296 | `AGENTS.md` sec. 7 |
| complaints | 80.000 | 67.095 | `AGENTS.md` sec. 7 |
| call_transcripts | 200.000 | 171.321 | notebook 04, celda 1 |
| satisfaction_surveys | 250.000 | 212.759 | notebook 04, parte B3 |
| customers | 150.000 | 150.000 | `AGENTS.md` sec. 7 |
| products | 400.000 | 400.000 | `AGENTS.md` sec. 7, sondeo de duplicados |
| daily_exchange_rates | 3.000 | 13.164 (1.097 fechas por 12 pares) | notebook 01, celda 5; `docs/technical-discuss-points.md` sec. 1.1 |

Las otras cinco tablas no tienen un conteo completo observado en el repo (inferido por búsqueda). `AGENTS.md` anota la brecha de los hechos junto a la trampa de particiones tardías, pero esa trampa no se observó (sección 3).

## 2. Las tablas que importan para disputas

Seis tablas modelan el ciclo de vida de una disputa (regla 1, un solo workflow; `AGENTS.md` sec. 7; [`notebooks/01_problema_y_datos.ipynb`](../../notebooks/01_problema_y_datos.ipynb), celda 4):

- **`transactions`:** el cargo disputado, con tipo, estado, monto, `amount_usd`, canal, comercio y `process_date`.
- **`customers`:** segmento, país y fecha de registro. La identidad sale del token, nunca del documento (regla 5).
- **`products`:** estado de la tarjeta para el bloqueo preventivo. `product_number` tiene forma de número de tarjeta y no viaja a la copia de servicio.
- **`complaints`:** quejas de los últimos 90 días (`POL-AUT-150`).
- **`call_center_interactions`:** resolución en primer contacto y minutos por motivo; no se une a las quejas.
- **`daily_exchange_rates`:** COP y ARS a USD con la tasa del día de proceso.

Las demás tablas quedan fuera del flujo; varias sí entraron en la búsqueda de señal de fraude (sección 5).

## 3. Trampas de calidad: declaradas contra encontradas

El organizador declara cinco trampas (`AGENTS.md` sec. 7, "Intentional quality traps"). El equipo las sondeó el 26-sep sobre la muestra de junio de 2026, julio de 2023, un enero por año, todas las quejas y las dimensiones completas, y las revisó de nuevo en la carga completa del 27-sep.

| Trampa declarada | Lo que encontró el equipo | Consecuencia |
| --- | --- | --- |
| Duplicados, cerca de 2 % | No observada: 0 en junio de 2026 y julio de 2023 (por id, fila exacta, clave de negocio y claves más laxas), en los 150.000 clientes, en las 67.095 quejas y, por clave de negocio, en la carga completa; solo 6 `product_number` repetidos entre 400.000 productos | Se reporta como no observada. Silver igual deduplica ([Preparación](04-preparacion-de-los-datos.md), sección 2) |
| Nulos, cerca de 5 % | `amount_usd` nulo en el 5,15 % de las filas COP y ARS de abril a junio (514 ARS y 755 COP); en la carga completa, 99.477 filas (5,0 % de las no USD). `fraud_score` nulo en el 20,9 % de la muestra de junio (notebook 01, celda 17) | Relleno en silver con la tasa diaria y una columna de origen |
| Llegadas tardías | No observada: en junio de 2026 y julio de 2023 (principal y respaldo), `process_date` siempre es el día de la partición | `AGENTS.md` pide demostrarla con un fixture etiquetado: desde el 5-oct es [`data/fixtures/late_arrival_transactions.json`](../../data/fixtures/late_arrival_transactions.json), con sus tests en `tests/test_ingestion.py` |
| Evolución de esquema | El encabezado de transacciones es idéntico (25 columnas) en todos los años; la deriva está en los valores | Normalizar nombres y escribir solo valores del diccionario |
| Huérfanos, porcentaje pequeño | Solo `customers.registration_branch_id` (149.995 de 150.000 no apuntan a ninguna sucursal); 0 en las FK del workflow | Ninguno toca disputas |

Hallazgos verificados que el organizador no declaró (`AGENTS.md` sec. 7, "Verified findings"):

| Hallazgo | Evidencia | Consecuencia en el diseño |
| --- | --- | --- |
| Hora del evento desplazada | Ver sección 3.1 | Ventana y velocidad con `process_date` |
| No hay MXN en transacciones | Los clientes de México transaccionan en USD; `amount_usd` es nulo cuando `currency = 'USD'` | Topes y features en USD; MXN solo aparece en `complaints.claimed_amount` |
| Comercio casi nunca conocido | `merchant_name` nulo en el 77 %; nombres genéricos ("Super Ahorro", "Cine Premium") | El cruce del cargo usa monto y fecha; el comercio es una pista débil |
| Cargos no disputables | El 23,4 % de la muestra de junio es Deposit, Adjustment o no aprobado | La política necesita `POL-DISP-TYPE` |
| Enlaces de quejas rotos | Los 44.570 `affected_product_id` no nulos son productos de otro cliente; `origin_interaction_id` vacío en las 67.095 quejas | Nunca inferir el producto reclamado ni unir quejas con llamadas |
| Deriva de nombres y enums | "México" y "Mexico"; `status` de quejas sin `INTAKE_RECEIVED`, `category` sin `Fraud`, `reception_channel` sin `Chat` | Normalizar a "México"; escribir casos con valores del diccionario |
| Bandera de reincidente | `is_repeat_complainer` verdadera en el 15 % de las quejas | Se publica en `bank.complaints`; la política no la lee (inferido por búsqueda en `src/`) |
| Apertura de productos | El 18,71 % de los cargos es anterior a la apertura de su producto | La antigüedad de la tarjeta queda fuera del modelo de riesgo (sección 7) |

### 3.1 El desfase de 6 horas

`process_date` es la fecha de proceso del banco (UTC-6). Las marcas crudas no traen zona. `transaction_date - 6 h` reproduce `process_date` en el 100 % de las filas de junio; el cast simple acierta en el 76 % (notebook 01, celda 25). Con el cast simple, 227 cargos del 17 de junio caen el 18 y aparecen con -1 días (notebook 01, celda 28; [`CLAUDE.md`](../../CLAUDE.md), "Gotchas"). Tampoco es el día local del cliente: Colombia está en UTC-5 y Argentina en UTC-3 (`AGENTS.md` sec. 7). La corrección en el código está en [Preparación](04-preparacion-de-los-datos.md), sección 4.

### 3.2 Monedas y `amount_usd`

En la muestra de junio hay 6.449 filas USD, 3.214 COP y 2.040 ARS (notebook 01, celda 30). El nulo de `amount_usd` mezcla dos casos (`docs/technical-discuss-points.md` sec. 1.1): las 6.449 filas USD no lo traen por diseño, porque el monto ya está en dólares; 291 filas COP y ARS (185 y 106) son un vacío real, y todas tienen tasa diaria para su `process_date`.

Donde existe, el `amount_usd` nativo es `amount` por la tasa media del día de proceso, con un ruido simétrico de hasta 2,01 % en junio (2,1 % de abril a junio según `AGENTS.md` sec. 7). El relleno cambia decisiones: de las 291 filas, 138 pasan de 500 USD y 45 quedan en 150 USD o menos; 226 son cargos disputables en ventana (2,5 % de 8.967).

## 4. Qué cargos se pueden disputar: el embudo de junio

El embudo aplica la política v2.3 a los 11.703 movimientos de junio de 2026 de la muestra de 25.000 clientes, sin mensaje, sin señales de Jev y con riesgo 0,0 (spec v2.3 sec. 5, línea base del 27-sep).

| Paso | Cargos | Denominador |
| --- | --- | --- |
| No disputables (`POL-DISP-TYPE`) | 2.736 (23,4 %): 1.930 por tipo y 806 por estado | 11.703 |
| Disputables en ventana | 8.967 (76,6 %) | 11.703 |
| Más de 500 USD (`POL-ESC-500`) | 3.547 (39,6 %) | 8.967 |
| Candidatos `POL-AUT-150` (un humano decide el crédito) | 482 (5,4 %) | 8.967 |
| Intake sin candidato (`POL-AUT-INTAKE`) | 4.938 (55,1 %) | 8.967 |
| **Techo de contención** (caso abierto sin humano) | **60,4 %** | 8.967 |

Lectura:

- **Es un techo, no una predicción.** Se calcula antes de los escalamientos por riesgo, legales, de varios cargos y de aclaración.
- **El umbral pesa mucho.** Con 300 USD el techo baja a 36,0 %; con 1.000 USD sube a 67,3 %. El equipo mantuvo 500 USD (spec v2.3, "Sensibilidad del techo").
- **Junio no tiene cargos fuera de ventana** (va de 0 a 16 días). Abril de 2026 aporta 9.358 cargos disputables de 61 a 77 días; uno es el fixture de abstención `FX-ABST-WIN60-001` ([`data/fixtures/abstention_pol_win_60.json`](../../data/fixtures/abstention_pol_win_60.json); notebook 01, celda 27).
- **El cliente que califica no es el cargo que califica.** El 32,1 % de los clientes (8.021 de 25.000) cumple los criterios de cliente de `POL-AUT-150`, pero solo el 5,4 % de los cargos es candidato (notebook 01, celdas 22 y 28).

Un sondeo de solo lectura en S3 (1 de abril al 17 de junio de 2026, 54.157 transacciones de 18.756 clientes) midió los patrones que la suite necesita (`AGENTS.md` sec. 7): 32.109 cargos disputables en ventana; un solo par de cargos del mismo monto a 7 días o menos, así que la ambigüedad real sale de pistas vagas de fecha o comercio; 1.629 clientes con 2 o más cargos disputables en 48 h (70 con 3 o más); 429 compras extranjeras por Web o App; y 42 filas con `is_fraud` (22 disputables en ventana), por eso los casos de fraude quedan en el tope de 20.

## 5. El hallazgo crítico: `fraud_score` filtra `is_fraud`, e `is_fraud` no tiene señal

**La fuga.** En la carga completa hay 4.316 fraudes entre 4.425.008 transacciones (0,098 %): 814 en 2023, 1.485 en 2024, 1.414 en 2025 y 603 en 2026 (`AGENTS.md` sec. 7). Toda fila no fraudulenta puntúa 30 o menos (media 15,0); las fraudulentas van de 0,01 a 99,99 (media 49,5) (`docs/technical-discuss-points.md` sec. 5). Un score mayor a 30 es fraude con 100 % de precisión pero con recall parcial: en los días de test, las 798 filas por encima de 30 son fraude, de 1.445 fraudes ([`notebooks/02_risk_model_experiment.ipynb`](../../notebooks/02_risk_model_experiment.ipynb), secciones 5 y 8). Decisión: `fraud_score` queda fuera de todo modelo y del baseline, y se presenta como hallazgo de calidad de datos. Sigue en `gold_transactions` solo para análisis y nunca viaja a la copia de servicio.

**La etiqueta no tiene señal.** La tasa de fraude es plana en todas las variables previas a la autorización (carga completa, tasa base 0,098 %; `docs/technical-discuss-points.md` sec. 5):

| Variable | Tasa por valor (%) |
| --- | --- |
| Canal | POS 0,095; ATM 0,100; Web 0,099; App 0,096; Branch 0,108; Transfer 0,095 |
| Monto en USD | menos de 50: 0,107; 150 a 500: 0,099; más de 1.000: 0,095 |
| Segmento | Basic 0,098; Plus 0,099; Premium 0,089; Student 0,103 |
| Estado | Approved 0,098; Declined 0,097; Pending 0,089; Reversed 0,080 |

Otras pruebas:

1. **Modelo contra reglas.** ROC AUC de test 0,497 del gradient boosting sin fuga contra 0,495 de las reglas, sobre 1.555.062 filas (1.445 fraudes) (`reports/ml_full/fraud_risk.md`); con una etiqueta sintética que depende del comportamiento, el mismo pipeline llega a 0,869 (notebook 02, sección 7). Detalle en [Modelado](05-modelado.md), sección 2.1.
2. **El fraude no se agrupa.** 78 clientes tienen 2 o más fraudes, contra 87,4 esperados si fuera independiente por fila; un fraude previo no sube la tasa (0,089 % contra 0,098 %) (`docs/technical-discuss-points.md` sec. 5).
3. **Ninguna otra tabla aporta.** De 139 bins de clientes, productos, quejas, llamadas, transcripciones, eventos, campañas y encuestas, ninguno con 1.000 filas o más sube la tasa 1,5 veces ([`notebooks/03_fraud_signal_search.ipynb`](../../notebooks/03_fraud_signal_search.ipynb), parte C).
4. **La muestra de junio no sirve para medir.** Tiene 9 fraudes; su ROC AUC de test de 0,624 sobre 3 positivos es una prueba del pipeline ([`reports/ml/fraud_risk.md`](../../reports/ml/fraud_risk.md)).

La hipótesis 3 del plan no se puede confirmar con estos datos (`AGENTS.md` sec. 7). TQ-023 sigue sin respuesta registrada en [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json).

## 6. Quejas contra marcas de fraude, y NLP de las llamadas

Quejas, marcas y transcripciones se generaron por separado (notebook 04; `docs/technical-discuss-points.md` sec. 6):

- **Volumen.** 12.297 quejas "Cargo no reconocido" contra 4.316 marcas `is_fraud` en 2023 a 2026: entre 2,7 y 3,2 quejas por marca cada año.
- **No se tocan.** El 0,35 % de los cargos marcados tiene una queja de cargo no reconocido en 60 días, contra 0,45 % de los no marcados (Fisher, odds ratio 0,77, p 0,40). Esas quejas traen una marca previa con la misma frecuencia que las demás (chi cuadrado sobre 10 tipos, p 0,859). Los clientes con alguna marca reclaman igual (7,96 % contra 7,92 %). Solo 3 quejas nombran el producto de un cargo marcado, y ninguna coincide en monto ni moneda.
- **Transcripciones.** 171.321 de 101.951 clientes, en español, armadas con 42 plantillas de cliente y 42 de agente. Un léxico de fraude en español y portugués no encuentra coincidencias en transcripciones, descripciones de quejas ni comentarios de encuestas. Cerca de cargos marcados la mezcla de plantillas difiere solo a 7 días (69 transcripciones, p de permutación 0,052) y vuelve a la de la población a 30 y 90 días.

Consecuencias: una "tasa de reclamo" (quejas sobre marcas) no es un número de negocio, y la intención sale del chat (palabras clave y Jev sobre el mensaje enmascarado). TQ-025, que pregunta a los mentores por un vínculo no encontrado, sigue sin respuesta.

## 7. Homologación con IEEE-CIS

IEEE-CIS Fraud Detection es **externo**: transacciones reales de e-commerce, desidentificadas, de una competencia pública de Kaggle (`README.md`, "Limitations"). Tiene 590.540 transacciones de tarjeta no presente con 3,5 % de fraude, 394 columnas de transacción y 41 de identidad para el 24 % de las filas, en 183 días ([`notebooks/05_ieee_cis_feature_homologation.ipynb`](../../notebooks/05_ieee_cis_feature_homologation.ipynb), secciones 1 y 2). Los archivos viven en `data/kaggle/`, fuera de git. El notebook 05 calculó el mismo contrato de features en las dos fuentes:

- **La señal existe solo en la competencia:** mejores AUC univariadas de 0,56 a 0,68; contra `is_fraud` del banco, todas en 0,50 (`docs/technical-discuss-points.md` sec. 7.1).
- **Los mundos son distintos.** Mediana del monto de 68,77 USD en la competencia y 467,24 USD en el banco; percentil 95 de 445,00 contra 7.556,05 USD. Un clasificador adversarial separa las fuentes con AUC 1,000, también con rangos por fuente: por eso el umbral es un percentil.
- **Canales cubiertos.** Jev marcó solo Web (0,69) y App (0,60) como del tipo de la competencia; son el 30,0 % de los cargos ([`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md) sec. 10.2).
- **Fuera: antigüedad de la tarjeta e identidad digital.** El 18,71 % de los cargos es anterior a la apertura de su producto (spec sec. 10.3). De 205.943 cargos Web y App de 2026, 170 tienen un evento del mismo cliente a menos de una hora y ninguno del mismo producto el mismo día (`docs/technical-discuss-points.md` sec. 7).

El modelo, su validación, su umbral y la ganancia pendiente están en [Modelado](05-modelado.md), sección 2.3.

## 8. Qué no usar como señal y qué sí se usa

**No entrenar con esto ni presentarlo como señal** (`AGENTS.md` sec. 7): `complaints.description` (una plantilla por categoría); `sla_breached` (cerca de 20 %), `compensation_granted` (cerca de 7 %) y `resolution_satisfaction` (cerca de 3,0), planos entre categorías; `complaints.resolution` (5 textos, cerca de 77 % nulo); `call_transcripts.detected_intents` (casi siempre `consulta_general`, con placeholders sin llenar como `{monto}`); y `fraud_score` (sección 5).

**`is_fraud`** (0,098 %, sin señal) se usa una sola vez, para reportar la concordancia del modelo transferido, nunca para entrenar (`docs/technical-discuss-points.md` sec. 7; TQ-026).

**Lo que la política sí lee** (`gold_transactions`, `gold_customers` y la vista `ops.v_customer_policy_facts`): tipo y estado del cargo, `amount_usd`, `process_date`, segmento, antigüedad de la cuenta, quejas de 90 días y estado de la tarjeta. Son hechos deterministas, no señales aprendidas.

## 9. Por qué los datos justifican la respuesta a la pregunta problema

La pregunta problema ([Entendimiento del negocio](02-entendimiento-del-negocio.md), sección 4) pide resolver de forma segura y verificada los cargos no reconocidos elegibles, en español y portugués, con más resolución segura automatizada que el baseline y sin aumentar los resultados inseguros. Además de las consecuencias de las secciones 3 a 5:

| Hecho de los datos | Decisión de diseño | Fuente |
| --- | --- | --- |
| Queja tiene la peor resolución en primer contacto (43,6 % contra 91,5 %); cargo no reconocido (18,3 %) y cobro indebido (18,2 %) suman cerca del 36 % de las quejas | El intake de disputas es el único workflow | `AGENTS.md` sec. 6 y 7 |
| 1.629 clientes con 2 o más cargos disputables en 48 h | `POL-ESC-MULTI` con el conteo de cargos nombrados | `AGENTS.md` sec. 7 |
| No hay portugués ni Brasil | Los 100 casos PT del held-out y las 30 preguntas PT de política (15 por split) son `team-generated`; el límite se declara | `README.md`, "Data"; `data/eval/` |
| Las quejas no enlazan producto ni llamada | El caso se abre en `ops.dispute_cases` con el `transaction_id` del cargo encontrado; las quejas del dataset solo cuentan para los 90 días | [`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 4.4; [`supabase/migrations/0001_ops.sql`](../../supabase/migrations/0001_ops.sql) |

Lo que los datos no justifican: un detector de fraude validado en el banco, una cifra de minutos ahorrados o un ROI ([Entendimiento del negocio](02-entendimiento-del-negocio.md), secciones 1 y 7).

## 10. Notebooks

Los cinco notebooks de [`notebooks/`](../../notebooks/) se comprometieron con sus salidas ejecutadas y sus gráficas (`01_*.png` a `21_*.png`); sus resultados se citan arriba. El 01 corre sobre la muestra de 25.000 clientes (corrida del 26-sep); el 02 a 04, sobre la carga completa y las tablas auxiliares; el 05, sobre IEEE-CIS (externo) y la carga completa. Leen lakehouses locales fuera de git (`data/lakehouse.duckdb`, `data/lakehouse_full.duckdb`, `data/lakehouse_aux.duckdb`) y, el 05, `data/kaggle/`; rehacerlos exige las llaves de S3 (inferido). Del 01 sale además la justificación del workflow: Queja con FCR de 45,0 % en la muestra de marzo de 2025 (celda 8), contra 43,6 % en la carga completa de interacciones (`AGENTS.md` sec. 7).

## Contradicciones y lecturas con cuidado

- **Techo de 60,4 % o 60,5 %.** La salida del notebook 01 (celda 26) y la spec v2.3 dan 3.547 cargos sobre 500 USD (39,6 %) y 60,4 %. El texto de la celda 28 da 3.546 (39,5 %) y 60,5 %, `AGENTS.md` sec. 7 y `docs/TEAM_BRIEF_COMPLEMENTED.md` repiten 39,5 % y 60,5 %, y `docs/PLAN.md` (sec. 1 y fila "Techo de escalamiento de $500") repite 60,5 %. La spec declara que manda la salida de la celda; esta guía usa 60,4 %.
- **Bins de la búsqueda cruzada.** El notebook 03 dice 139; `docs/technical-discuss-points.md` sec. 5 y TQ-023 dicen 140.
- **AUC sin fuga.** `AGENTS.md` sec. 7 y `docs/technical-discuss-points.md` sec. 5 dicen 0,50; el reporte y el notebook 02, 0,497. Etiqueta sintética: 0,868 en el documento técnico, 0,869 en el notebook.
- **`affected_product_id`.** La celda 4 del notebook 01 dice 82 % de productos ajenos; `AGENTS.md` sec. 7 dice el 100 % de los no nulos (44.570 de 44.570).
- **`data/README.md` está desactualizado.** Da la clave `[customer_id, transaction_date, amount, merchant_name]` y la columna `amount_usd_normalized`, eliminada el 27-sep (`docs/technical-discuss-points.md` sec. 4).
- **Dataset hacia un modelo externo.** `AGENTS.md` sec. 8 dice que las filas del dataset no salen en llamadas a modelos externos, pero el notebook 03 envió 1.013 transcripciones enmascaradas a Jev (`docs/technical-discuss-points.md` sec. 5). Son sintéticas, así que no rompe la regla 10 (inferido), pero matiza esa frase.
- **Licencia de IEEE-CIS (abierta).** `README.md` y TQ-032 registran la aprobación de los mentores; TQ-026, una fila de `docs/PLAN.md` y la spec del modelo la dan por pendiente ([Entendimiento del negocio](02-entendimiento-del-negocio.md), sección 7).

## Fuentes

[`AGENTS.md`](../../AGENTS.md) sec. 6, 7 y 8; [`docs/technical-discuss-points.md`](../technical-discuss-points.md) sec. 1, 4, 5, 6 y 7; [`docs/specs/dispute-policy-v2.3.md`](../specs/dispute-policy-v2.3.md) sec. 5; [`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md) sec. 10; [`docs/SUPABASE_VERCEL.md`](../SUPABASE_VERCEL.md) sec. 4.4; [`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md) y [`reports/ml/fraud_risk.md`](../../reports/ml/fraud_risk.md); notebooks 01 a 05 en [`notebooks/`](../../notebooks/), leídos por celdas de texto y salidas; [`data/fixtures/team_questions.json`](../../data/fixtures/team_questions.json) (TQ-023, TQ-025, TQ-026, TQ-032); [`data/fixtures/abstention_pol_win_60.json`](../../data/fixtures/abstention_pol_win_60.json); [`README.md`](../../README.md) ("Data", "Limitations") y [`CLAUDE.md`](../../CLAUDE.md) ("Gotchas").
