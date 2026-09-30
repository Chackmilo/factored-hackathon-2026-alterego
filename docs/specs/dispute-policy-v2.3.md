# Spec de la porción: motor de política de disputas v2.3

Estado: fase 1 revisada con el equipo el 2026-09-27 (respuestas P1 a P7 en `docs/technical-discuss-points.md`, sección 2). Rama: `feat/dispute-policy-v2.3`. Fecha: 2026-09-27.

- **Porción:** `src/rules/dispute_policy.py` llevado a la spec v2.3 (frente B).
- **Spec que manda:** `docs/TEAM_BRIEF_COMPLEMENTED.md` sección 2, Decision 4 (cláusulas, orden, matriz de monedas) y las filas Decididas del registro de decisiones de `docs/PLAN.md` que la tocan: "Política de disputas" (v2.3 tal cual; Transfer es disputable), "Crédito provisional" (solo marca de candidato), "Techo de escalamiento de $500" (se mantiene), "Confirmación del bloqueo preventivo" (el cliente confirma), "Cargo disputable y angustia" (`POL-DISP-TYPE`; Jev Score >= 2 con palabras clave de respaldo). Las filas Propuesta sobre umbrales de Jev no se aplican: el código lleva los umbrales del brief v2.3.
- **Precedencia:** enunciado oficial, reglas de `AGENTS.md` sección 4, brief v2.3, código.
- **Fuera de la porción:** gateway, orquestador, Jev, LightGBM, baseline, `POL-SEC-SESSION`. Las señales de Jev y el score de LightGBM entran como campos tipados de `DisputePolicyInput` alimentados por fixtures.
- **Tests:** todos los tests de la política viven en `tests/test_dispute_policy.py`, nombrados por cláusula (`test_pol_<id>_...`) para verificar la matriz con grep. Los cinco tests de política que hoy están en `tests/test_dispute_flow.py` se mueven a ese archivo, renombrados, en el commit que cambia su comportamiento (supuesto S14).

## 1. Matriz de trazabilidad

La columna "Estado en el código" describe `src/rules/dispute_policy.py` en `main` (commit 67380b7), el punto de partida de la fase 2. Al cierre de la fase 2 (27-Sep) cada fila cumple con sus tests en verde en `tests/test_dispute_policy.py` (55 tests, verificados con grep contra esta matriz); la columna se conserva como registro de la brecha cerrada.

| Id | Regla (una línea) | Entradas que usa | Resultado esperado | Estado en el código | Tests que la fijan |
| --- | --- | --- | --- | --- | --- |
| `POL-SEC-SESSION` | Token vencido o inválido: 401 sin revelar nada; registro de otro cliente: 403 con auditoría y el mismo error externo que "no existe" | Token de sesión, `customer_id` del registro | 401 o 403 desde auth y gateway | Fuera de la porción. Hoy HS256 en `src/auth/session.py` y guardas de propiedad en `src/tools/gateway.py`; Supabase Auth decidida y sin código | Existentes en `tests/test_dispute_flow.py`: `test_session_token_verification_and_expiry`, `test_lock_card_rejects_other_customers_card`, `test_open_dispute_rejects_other_customers_transaction` |
| `POL-ESC-LEGAL` | Cita a regulador (CONDUSEF, SFC, BCRA, PROCON) o acción legal: HITL. Corre antes de la ventana, así que escala hasta un cargo prescrito | `customer_message` | `MANDATORY_HITL_ESCALATION`, `escalation_reason = REGULATOR_OR_LEGAL_CITING`, `action_required = ESCALATE`, `cited_clauses = [POL-ESC-LEGAL]`, sin bloqueo de tarjeta salvo reclamo de robo | Diverge: la ventana corre primero (`dispute_policy.py:67`) y la escalación ordena bloquear la tarjeta (`dispute_policy.py:91`) | `test_pol_esc_legal_regulator_keyword_escalates`, `test_pol_esc_legal_pt_legal_keyword_escalates`, `test_pol_esc_legal_precedes_window`, `test_pol_esc_legal_escalates_without_card_hold` |
| `POL-CLARIFY` | Exactamente un cargo candidato: continúa. Cero o varios: pregunta de aclaración listando candidatos. Confianza de intención de Jev < 0,70 (también para `fuera_de_alcance`: la barrera contra decidir en ambigüedad), o probabilidad de robo de Jev entre 0,40 y 0,60: pregunta de aclaración | `candidate_charges_count`, `intent_confidence`, `is_stolen_reported`, `dispute_intent` | `CLARIFICATION_REQUIRED`, `action_required = ASK_CLARIFICATION`, `clarification_reason` en {`NO_CANDIDATE_CHARGE`, `MULTIPLE_CANDIDATE_CHARGES`, `LOW_INTENT_CONFIDENCE`, `STOLEN_CARD_AMBIGUOUS`}, `cited_clauses = [POL-CLARIFY]`, sin caso | Falta | `test_pol_clarify_zero_candidates_asks`, `test_pol_clarify_several_candidates_asks`, `test_pol_clarify_single_candidate_continues`, `test_pol_clarify_intent_confidence_boundary`, `test_pol_clarify_stolen_card_band_boundaries`, `test_pol_clarify_yields_to_legal`, `test_pol_clarify_single_candidate_requires_charge`, `test_pol_clarify_ambiguous_out_of_scope_asks` |
| `POL-ESC-AMBIG` | Sigue sin resolverse después de 2 intentos de aclaración: HITL | Las de `POL-CLARIFY` más `clarification_attempts` | `MANDATORY_HITL_ESCALATION`, `escalation_reason = UNRESOLVED_AFTER_CLARIFICATIONS`, `cited_clauses = [POL-CLARIFY, POL-ESC-AMBIG]` | Falta | `test_pol_esc_ambig_after_two_attempts` |
| `POL-DISP-TYPE` | Disputable: débito `Approved` de tipo Purchase, Payment, Withdrawal o Transfer. Declined, Reversed o Pending, Deposit o Adjustment: explica y no abre caso. Cargo fechado después de hoy: error de datos, explica, no abre caso y marca revisión de calidad. Intención `fuera_de_alcance` con confianza decisiva: abstención que nombra la categoría no soportada (`out_of_scope_category`, lista cerrada) y dónde acudir. `amount_usd` nulo: escalación a humano con el vacío nombrado (P2) | `transaction_type`, `transaction_status`, `transaction_date` (día de proceso), `current_date`, `dispute_intent`, `intent_confidence`, `out_of_scope_category`, `amount_usd` | `SAFE_POLICY_ABSTENTION` con `action_required = ABSTAIN` y `escalation_reason` en {`NOT_DISPUTABLE_CHARGE`, `DATA_ERROR_FUTURE_DATE`, `OUT_OF_SCOPE_INTENT`}; `MANDATORY_HITL_ESCALATION` con `DATA_GAP_AMOUNT_USD`; `data_quality_flag` en los casos de datos; `cited_clauses = [POL-DISP-TYPE]` | Falta el tipo y el estado. Diverge la fecha futura: hoy la ventana la absorbe y explica "hace -1 días" (`dispute_policy.py:67` y `:76`) | `test_pol_disp_type_transfer_is_disputable`, `test_pol_disp_type_not_approved_abstains`, `test_pol_disp_type_credit_types_abstain`, `test_pol_disp_type_future_dated_charge_is_data_error`, `test_pol_disp_type_out_of_scope_intent_abstains`, `test_pol_disp_type_out_of_scope_names_category`, `test_pol_disp_type_missing_amount_usd_is_data_gap`, `test_pol_disp_type_precedes_window` |
| `POL-WIN-60` | Elegible si `process_date` está a 60 días calendario o menos de hoy (2026-06-17). Más viejo: abstención segura, explica la política y dirige a una sucursal | `transaction_date` (se resta 6 h si es timestamp; se usa tal cual si ya es el día de proceso), `current_date` | Día 60 continúa; día 61 `SAFE_POLICY_ABSTENTION`, `escalation_reason = OUT_OF_POLICY_WINDOW`, `action_required = ABSTAIN`, `cited_clauses = [POL-DISP-TYPE, POL-WIN-60]` | Cumple la regla y el día de proceso (`dispute_policy.py:63` a `:67`); diverge en la rama negativa (va a `POL-DISP-TYPE`) y en la posición (hoy va primera) | `test_pol_win_60_out_of_window_abstention`, `test_pol_win_60_counts_bank_process_day` (días 60 y 61), `test_pol_win_60_fixture_abstains` (`data/fixtures/abstention_pol_win_60.json`) |
| `POL-ESC-500` | Monto reclamado > $500 USD equivalente: HITL | `amount_usd` | Exactamente $500 continúa; $500,01 `MANDATORY_HITL_ESCALATION`, `escalation_reason = AMOUNT_EXCEEDS_500_USD`, `action_required = ESCALATE`, sin bloqueo de tarjeta | Cumple el umbral (`dispute_policy.py:97`); diverge la acción `HOLD_CARD_AND_ESCALATE` (`:105`) | `test_pol_esc_500_exactly_500_continues`, `test_pol_esc_500_above_500_escalates`, `test_pol_esc_500_currency_matrix` |
| `POL-ESC-ML-RISK` | Score de riesgo aprendido > 0,70: HITL | `ml_risk_score` (contrato de entrada de LightGBM, hoy alimentado por fixture) | 0,70 continúa; 0,71 `MANDATORY_HITL_ESCALATION`, `escalation_reason = HIGH_FRAUD_RISK_SCORE`, texto sin promesa de bloqueo | Cumple el umbral (`dispute_policy.py:111`); diverge la acción (`:119`) y el texto "Aplicamos bloqueo preventivo" (`:120`) | `test_pol_esc_ml_risk_boundary`, `test_pol_esc_ml_risk_promises_no_lock` |
| `POL-ESC-MULTI` | Más de 2 cargos disputados distintos en 48 h: HITL, con bloqueo recomendado por fraude de varios cargos | `recent_disputed_charges_count` | 2 continúa; 3 `MANDATORY_HITL_ESCALATION`, `escalation_reason = MULTIPLE_CHARGES_48H`, `card_lock_recommended = True`, `card_lock_reason = MULTI_CHARGE_FRAUD` | Cumple el umbral (`dispute_policy.py:125`); el bloqueo sale hoy por la acción genérica (`:133`), no por una recomendación explícita | `test_pol_esc_multi_two_charges_continue`, `test_pol_esc_multi_three_charges_escalate_with_lock` |
| `POL-ESC-DISTRESS` | Angustia severa: Jev Score >= 2, o la lista de palabras clave ES/PT como respaldo, o una marca de angustia severa en la memoria de casos (`prior_distress_max_30d >= 2`, P3): HITL | `customer_distress_score` (contrato de Jev, fixture), `customer_message` para el respaldo, `prior_distress_max_30d` (memoria de casos, fixture) | 1,99 continúa; 2,0 `MANDATORY_HITL_ESCALATION`, `escalation_reason = SEVERE_DISTRESS`. Sin score de Jev, una palabra clave de angustia escala. La memoria escala aunque el score actual sea bajo | Falta | `test_pol_esc_distress_score_boundary`, `test_pol_esc_distress_keyword_fallback_es_pt`, `test_pol_esc_distress_jev_score_overrides_keywords`, `test_pol_esc_distress_case_memory_escalates` |
| Orden de escalaciones | $500, luego riesgo ML, luego varios cargos, luego angustia; la primera que decide gana. Las demás que también aplican quedan en `secondary_clauses` (P1) | Las anteriores | La cláusula decisoria es la primera del orden que aplica; `secondary_clauses` lista las otras que dispararon, sin cambiar resultado ni razón | Cumple para las tres existentes; la angustia y las secundarias faltan | `test_pol_esc_order_500_before_ml_risk`, `test_pol_esc_order_ml_risk_before_multi`, `test_pol_esc_order_multi_before_distress`, `test_pol_esc_order_secondary_clauses_recorded` |
| `POL-AUT-LOCK` (acción autónoma 6; id aceptado el 27-Sep, P7) | Bloqueo temporal solo cuando el cliente reclama robo (Jev >= 0,80 o palabras clave de respaldo) o hay fraude de varios cargos; solo tarjetas activas; el cliente confirma primero; el bloqueo se recomienda en cualquier resultado (P5) | `is_stolen_reported`, `customer_message` para el respaldo, `recent_disputed_charges_count` | `card_lock_recommended = True`, `card_lock_reason` en {`STOLEN_CARD_CLAIM`, `MULTI_CHARGE_FRAUD`} y `card_lock_required_authentication = SESSION_AND_CUSTOMER_CONFIRMATION`, en cualquier resultado; 0,79 no recomienda, 0,80 sí. Guardas de producto y confirmación: fuera de la porción | Diverge: hoy toda escalación bloquea (`:91`, `:105`, `:119`, `:133`) y ningún intake autónomo puede recomendar el bloqueo | `test_pol_aut_lock_stolen_probability_boundary`, `test_pol_aut_lock_keyword_fallback_es_pt`, `test_pol_aut_lock_rides_along_autonomous_intake`, `test_pol_aut_lock_on_out_of_window_stolen_claim`, `test_pol_aut_lock_requires_customer_confirmation`, `test_pol_aut_lock_multi_charge_on_any_outcome`, `test_pol_aut_lock_stolen_claim_names_the_reason_over_multi_charge` |
| `POL-AUT-INTAKE` | Abrir el caso con valores del diccionario: `case_type = Claim`, `category = Transactions`, `subcategory` en {Cargo no reconocido, Cobro indebido}, `reception_channel = App`, `status = Open` | Las de las puertas previas, `dispute_intent` para la subcategoría | `AUTONOMOUS_RESOLUTION`, `action_required = OPEN_DISPUTE_ONLY`, `case_values` con los cinco valores, `cited_clauses = [POL-DISP-TYPE, POL-WIN-60, POL-AUT-INTAKE]`, texto "registrado y en revisión" | Cumple el resultado (`dispute_policy.py:157`); diverge el texto "Ticket INTAKE_RECEIVED" (`:164`, valor ajeno al diccionario) y faltan los valores del caso | `test_pol_aut_intake_opens_case_with_dictionary_values`, `test_pol_aut_intake_subcategory_follows_intent`, `test_pol_aut_intake_above_150_is_not_candidate` |
| `POL-AUT-150` | Marca de candidato a crédito provisional cuando TODO se cumple: monto <= $150 USD, segmento Premium o Plus leído del sistema de registro, cuenta > 180 días, 0 quejas en 90 días. Recomendación simulada que un humano aprueba en la consola; el cliente nunca oye que se aplicó crédito | `amount_usd`, `customer_segment`, `account_age_days`, `complaints_last_90d` | `AUTONOMOUS_RESOLUTION`, `action_required = OPEN_DISPUTE_ONLY`, `provisional_credit_candidate = True`, `provisional_credit_amount_usd = amount_usd`, `cited_clauses = [POL-DISP-TYPE, POL-WIN-60, POL-AUT-INTAKE, POL-AUT-150]`; $150 sí, $150,01 no; 180 días no, 181 sí; ningún texto menciona crédito | Diverge: crédito como resultado autónomo, `OPEN_DISPUTE_AND_CREDIT` y texto "Se ha aplicado un crédito provisional simulado" (`dispute_policy.py:145` a `:153`); umbrales correctos (`:140`, `:142`) | `test_pol_aut_150_exactly_150_is_candidate`, `test_pol_aut_150_account_age_boundary`, `test_pol_aut_150_segment_and_complaints_gate`, `test_pol_aut_150_customer_never_hears_credit`, `test_pol_aut_150_currency_matrix` |
| Matriz de autenticación por acción (P5, sin id en el brief) | Cada acción soportada lleva un nivel de riesgo y una autenticación proporcional, declarados en la política como código y aplicados por gateway y consola: abrir caso y escalar (bajo, sesión), bloqueo temporal (medio, sesión más el sí del cliente), desbloqueo (alto, reingreso más aprobación de un agente humano; nunca desde el chat) y aprobación de crédito (alto, rol de agente en el token con auditoría) | `action_required`, `card_lock_recommended` | `required_authentication` en la decisión según la acción; `DisputePolicyEngine.ACTION_AUTH_MATRIX` expone la matriz completa, incluido `UNLOCK_CARD = STEP_UP_AND_AGENT` y `APPROVE_CREDIT_CANDIDATE = AGENT_ROLE` | Falta | `test_policy_required_authentication_by_action`, `test_policy_action_auth_matrix_unlock_is_high`, `test_policy_escalation_without_eligible_charge_is_not_eligible` |
| Passthroughs (P1, P3) | La decisión devuelve sin leerlos `risk_top_features` y `case_memory` para el handoff | `risk_top_features`, `prior_escalations_180d`, `prior_cases_180d`, `prior_lock_refused` | Los mismos valores en la decisión | Falta | `test_policy_risk_and_memory_passthrough` |
| Matriz de monedas | Todos los límites se calculan en USD con la tasa diaria de la fecha de la transacción; equivalentes al 2026-06-17: $150 son ~2.550 MXN, ~608.000 COP, ~53.400 ARS; $500 son ~8.510 MXN, ~2.027.000 COP, ~178.000 ARS. Las transacciones no traen MXN | `amount_usd` (ya convertido por la capa de datos), `transaction_amount` y `transaction_currency` solo para los textos | 608.000 COP (149,95 USD) es candidato; 2.027.000 COP (499,91 USD) es intake sin escalación; 178.000 ARS (500,13 USD) escala | Cumple: el motor compara `amount_usd`; la conversión vive en `gold_transactions.amount_usd_normalized` (fuera de la porción) | `test_pol_aut_150_currency_matrix`, `test_pol_esc_500_currency_matrix` |

## 2. Criterios de aceptación

Base común salvo que el criterio diga otra cosa: cliente Plus de Colombia, cuenta de 300 días, 0 quejas, un solo candidato, sin señales de Jev (`None`), riesgo ML 0,0, 1 cargo disputado, mensaje vacío, cargo Purchase Approved de $100 USD del 2026-06-10, hoy 2026-06-17.

### POL-ESC-LEGAL

1. **Dado** un mensaje "voy a poner la queja en CONDUSEF", **cuando** se evalúa, **entonces** el resultado es `MANDATORY_HITL_ESCALATION` con razón `REGULATOR_OR_LEGAL_CITING`, acción `ESCALATE` y la cláusula citada es `POL-ESC-LEGAL`. Test: `test_pol_esc_legal_regulator_keyword_escalates`.
2. **Dado** un mensaje en portugués "vou falar com meu advogado", **cuando** se evalúa, **entonces** escala igual. Test: `test_pol_esc_legal_pt_legal_keyword_escalates`.
3. **Dado** un cargo de hace 90 días y un mensaje que cita a la SFC, **cuando** se evalúa, **entonces** escala por `POL-ESC-LEGAL` y no se abstiene por ventana. Test: `test_pol_esc_legal_precedes_window`.
4. **Dado** el mensaje legal sin reclamo de robo, **cuando** se evalúa, **entonces** `card_lock_recommended` es falso. Test: `test_pol_esc_legal_escalates_without_card_hold`.

### POL-CLARIFY y POL-ESC-AMBIG

5. **Dado** `candidate_charges_count = 0` y sin cargo, **cuando** se evalúa, **entonces** el resultado es `CLARIFICATION_REQUIRED`, acción `ASK_CLARIFICATION`, razón `NO_CANDIDATE_CHARGE` y no hay caso. Test: `test_pol_clarify_zero_candidates_asks`.
6. **Dado** `candidate_charges_count = 2`, **cuando** se evalúa, **entonces** pide aclaración con razón `MULTIPLE_CANDIDATE_CHARGES`. Test: `test_pol_clarify_several_candidates_asks`.
7. **Dado** `candidate_charges_count = 1` y un cargo válido, **cuando** se evalúa, **entonces** no pide aclaración y llega a `POL-AUT-INTAKE`. Test: `test_pol_clarify_single_candidate_continues`.
8. **Dado** `intent_confidence = 0,69`, **cuando** se evalúa, **entonces** pide aclaración con razón `LOW_INTENT_CONFIDENCE`; **dado** 0,70, continúa. Test: `test_pol_clarify_intent_confidence_boundary`.
9. **Dado** `is_stolen_reported` en 0,39, 0,40, 0,60 y 0,61, **cuando** se evalúa, **entonces** 0,40 y 0,60 piden aclaración con razón `STOLEN_CARD_AMBIGUOUS`, y 0,39 y 0,61 continúan. Test: `test_pol_clarify_stolen_card_band_boundaries`.
10. **Dado** cero candidatos y un mensaje que cita a un regulador, **cuando** se evalúa, **entonces** gana `POL-ESC-LEGAL`. Test: `test_pol_clarify_yields_to_legal`.
11. **Dado** un solo candidato pero sin alguno de los datos del cargo (`transaction_id`, `transaction_date`, `transaction_amount`, `transaction_currency`, `transaction_type` o `transaction_status` en `None`), **cuando** se evalúa, **entonces** el motor lanza `ValueError` (error de programación del orquestador, supuesto S3). Test: `test_pol_clarify_single_candidate_requires_charge` (parametrizado por campo).
12. **Dado** cero candidatos con `clarification_attempts = 1`, **cuando** se evalúa, **entonces** vuelve a preguntar; **dado** `clarification_attempts = 2`, **entonces** escala con razón `UNRESOLVED_AFTER_CLARIFICATIONS` citando `POL-CLARIFY` y `POL-ESC-AMBIG`. Test: `test_pol_esc_ambig_after_two_attempts`.

### POL-DISP-TYPE

13. **Dado** un cargo Transfer Approved, **cuando** se evalúa, **entonces** es disputable y llega al intake (fila Decidida "Transfer es disputable"). Test: `test_pol_disp_type_transfer_is_disputable`.
14. **Dado** un cargo Purchase en estado Declined, Reversed o Pending, **cuando** se evalúa, **entonces** `SAFE_POLICY_ABSTENTION` con razón `NOT_DISPUTABLE_CHARGE`, acción `ABSTAIN` y sin caso. Test: `test_pol_disp_type_not_approved_abstains`.
15. **Dado** un Deposit o Adjustment Approved, **cuando** se evalúa, **entonces** se abstiene con razón `NOT_DISPUTABLE_CHARGE`. Test: `test_pol_disp_type_credit_types_abstain`.
16. **Dado** un cargo con día de proceso 2026-06-18 (timestamp 2026-06-18 06:00 UTC), **cuando** se evalúa, **entonces** se abstiene con razón `DATA_ERROR_FUTURE_DATE`, `data_quality_flag = FUTURE_DATED_CHARGE`, cita `POL-DISP-TYPE` y no `POL-WIN-60`, y el texto no dice "hace -1 días". Test: `test_pol_disp_type_future_dated_charge_is_data_error`.
17. **Dado** `dispute_intent = fuera_de_alcance` con confianza 0,9 y cero candidatos, **cuando** se evalúa, **entonces** se abstiene con razón `OUT_OF_SCOPE_INTENT` y explica el alcance (supuesto S4). Test: `test_pol_disp_type_out_of_scope_intent_abstains`.
17b. **Dado** `out_of_scope_category = prestamo_o_credito`, **entonces** el texto ES y PT nombra la categoría y dónde acudir; **dado** una categoría fuera de la lista cerrada, el motor lanza `ValueError`. Test: `test_pol_disp_type_out_of_scope_names_category`.
17c. **Dado** `fuera_de_alcance` con confianza 0,65, **entonces** no se abstiene: pide aclaración con razón `LOW_INTENT_CONFIDENCE` (barrera contra decidir en ambigüedad, P4). Test: `test_pol_clarify_ambiguous_out_of_scope_asks`.
18. **Dado** un cargo en COP con `amount_usd = None`, **cuando** se evalúa, **entonces** escala a humano con razón `DATA_GAP_AMOUNT_USD`, `data_quality_flag = MISSING_AMOUNT_USD` y `cited_clauses = [POL-DISP-TYPE]` (P2: tras la limpieza aguas arriba un nulo es un defecto de datos que debe ver una persona). Test: `test_pol_disp_type_missing_amount_usd_is_data_gap`.
19. **Dado** un cargo Declined de hace 90 días, **cuando** se evalúa, **entonces** la razón es `NOT_DISPUTABLE_CHARGE`, no la ventana. Test: `test_pol_disp_type_precedes_window`.

### POL-WIN-60

20. **Dado** un cargo del 2026-03-01, **cuando** se evalúa, **entonces** `SAFE_POLICY_ABSTENTION`, `OUT_OF_POLICY_WINDOW`, acción `ABSTAIN`, y el texto en español menciona "60 días". Test: `test_pol_win_60_out_of_window_abstention` (existente, renombrado).
21. **Dado** el timestamp 2026-04-18 03:00 UTC (día de proceso 2026-04-17, 61 días), **cuando** se evalúa, **entonces** se abstiene; **dado** 2026-04-18 06:00 UTC (día de proceso 2026-04-18, 60 días), continúa. Test: `test_pol_win_60_counts_bank_process_day` (existente, renombrado).
22. **Dado** el fixture `data/fixtures/abstention_pol_win_60.json` (cargo real de 77 días que sería candidato `POL-AUT-150`), **cuando** se evalúa con sus valores, **entonces** el resultado coincide con el bloque `expected` del fixture. Test: `test_pol_win_60_fixture_abstains`.

### POL-ESC-500 y matriz de monedas

23. **Dado** `amount_usd = 500,00`, **cuando** se evalúa, **entonces** no escala y llega al intake sin candidato. Test: `test_pol_esc_500_exactly_500_continues`.
24. **Dado** `amount_usd = 850`, **cuando** se evalúa, **entonces** `MANDATORY_HITL_ESCALATION`, `AMOUNT_EXCEEDS_500_USD`, acción `ESCALATE`, sin candidato y sin bloqueo recomendado. Test: `test_pol_esc_500_above_500_escalates` (existente, actualizado).
25. **Dado** 178.000 ARS a 355,912847 (500,12 USD), **cuando** se evalúa, **entonces** escala; **dado** 2.027.000 COP a 4.054,70 (499,91 USD), continúa y el texto muestra el monto en COP. Test: `test_pol_esc_500_currency_matrix`.

### POL-ESC-ML-RISK

26. **Dado** `ml_risk_score = 0,70`, continúa; **dado** 0,71, escala con `HIGH_FRAUD_RISK_SCORE`. Test: `test_pol_esc_ml_risk_boundary`.
27. **Dado** riesgo 0,9, **cuando** se evalúa, **entonces** `card_lock_recommended` es falso y los textos ES y PT no dicen "bloqueo" ni "bloqueio". Test: `test_pol_esc_ml_risk_promises_no_lock`.

### POL-ESC-MULTI

28. **Dado** `recent_disputed_charges_count = 2`, continúa. Test: `test_pol_esc_multi_two_charges_continue`.
29. **Dado** 3, **entonces** escala con `MULTIPLE_CHARGES_48H`, `card_lock_recommended = True` y `card_lock_reason = MULTI_CHARGE_FRAUD`. Test: `test_pol_esc_multi_three_charges_escalate_with_lock`.

### POL-ESC-DISTRESS

30. **Dado** `customer_distress_score = 1,99`, continúa; **dado** 2,0, escala con `SEVERE_DISTRESS`. Test: `test_pol_esc_distress_score_boundary`.
31. **Dado** score `None` y el mensaje "estoy desesperada, no tengo para comer" o "estou desesperado, não tenho como pagar", **entonces** escala por el respaldo de palabras clave. Test: `test_pol_esc_distress_keyword_fallback_es_pt`.
32. **Dado** score 0,5 y un mensaje con palabra clave de angustia, **entonces** no escala (el respaldo aplica solo sin señal de Jev; supuesto S7). Test: `test_pol_esc_distress_jev_score_overrides_keywords`.
32b. **Dado** score 0,5 en el mensaje actual y `prior_distress_max_30d = 2,5` en la memoria de casos, **entonces** escala con `SEVERE_DISTRESS` (P3: la memoria decide también en modo respaldo). Test: `test_pol_esc_distress_case_memory_escalates`.

### Orden de escalaciones (empates)

33. **Dado** $850 y riesgo 0,9, **entonces** la cláusula decisoria es `POL-ESC-500`. Test: `test_pol_esc_order_500_before_ml_risk`.
34. **Dado** riesgo 0,9 y 3 cargos, **entonces** decide `POL-ESC-ML-RISK`. Test: `test_pol_esc_order_ml_risk_before_multi`.
35. **Dado** 3 cargos y angustia 3,0, **entonces** decide `POL-ESC-MULTI`. Test: `test_pol_esc_order_multi_before_distress`.
35b. **Dado** $850, riesgo 0,9 y 3 cargos, **entonces** decide `POL-ESC-500` y `secondary_clauses = [POL-ESC-ML-RISK, POL-ESC-MULTI]`; en un intake autónomo la lista está vacía. Test: `test_pol_esc_order_secondary_clauses_recorded`.

### Bloqueo preventivo

36. **Dado** `is_stolen_reported = 0,79`, **entonces** no recomienda bloqueo; **dado** 0,80, recomienda con `STOLEN_CARD_CLAIM`. Test: `test_pol_aut_lock_stolen_probability_boundary`.
37. **Dado** señal `None` y "me robaron la tarjeta" o "roubaram meu cartão", **entonces** recomienda bloqueo. Test: `test_pol_aut_lock_keyword_fallback_es_pt`.
38. **Dado** robo 0,9 y un cargo de $80 elegible, **entonces** el resultado es `AUTONOMOUS_RESOLUTION` con `OPEN_DISPUTE_ONLY` y `card_lock_recommended = True`. Test: `test_pol_aut_lock_rides_along_autonomous_intake`.
39. **Dado** robo 0,9 y un cargo de hace 90 días, **entonces** se abstiene por ventana y aun así recomienda el bloqueo (P5). Test: `test_pol_aut_lock_on_out_of_window_stolen_claim`.
39b. **Dado** cualquier decisión con bloqueo recomendado, **entonces** `card_lock_required_authentication = SESSION_AND_CUSTOMER_CONFIRMATION`. Test: `test_pol_aut_lock_requires_customer_confirmation`.
39e. **Dado** 3 cargos en 48 h y un mensaje legal, o 3 cargos y un cargo de hace 90 días, **entonces** la decisión es legal o ventana y aun así `card_lock_recommended` con razón `MULTI_CHARGE_FRAUD`; con robo 0,9 y 3 cargos la razón es `STOLEN_CARD_CLAIM`. Tests: `test_pol_aut_lock_multi_charge_on_any_outcome`, `test_pol_aut_lock_stolen_claim_names_the_reason_over_multi_charge`.
39f. **Dado** una escalación sin cargo elegible (`POL-ESC-AMBIG` o `DATA_GAP_AMOUNT_USD`), **entonces** `is_eligible` es falso. Test: `test_policy_escalation_without_eligible_charge_is_not_eligible`.
39c. **Dado** un intake autónomo, **entonces** `required_authentication = SESSION`; **dado** una escalación, `SESSION`; y la matriz de la clase dice `UNLOCK_CARD` y `APPROVE_CREDIT_CANDIDATE` son de nivel `HIGH` con `STEP_UP_AND_AGENT`. Tests: `test_policy_required_authentication_by_action`, `test_policy_action_auth_matrix_unlock_is_high`.
39d. **Dado** `risk_top_features` y los campos de memoria en la entrada, **entonces** la decisión los devuelve sin cambios en `risk_top_features` y `case_memory`. Test: `test_policy_risk_and_memory_passthrough`.

### POL-AUT-INTAKE

40. **Dado** un cargo de $300 de un cliente Basic, **entonces** `AUTONOMOUS_RESOLUTION`, `OPEN_DISPUTE_ONLY`, `case_values` igual a {`case_type: Claim`, `category: Transactions`, `subcategory: Cargo no reconocido`, `reception_channel: App`, `status: Open`}, cláusulas `[POL-DISP-TYPE, POL-WIN-60, POL-AUT-INTAKE]`, y los textos no contienen "INTAKE_RECEIVED". Test: `test_pol_aut_intake_opens_case_with_dictionary_values`.
41. **Dado** `dispute_intent = cobro_indebido`, **entonces** `subcategory = Cobro indebido`. Test: `test_pol_aut_intake_subcategory_follows_intent`.
42. **Dado** $150,01 y $500 de un cliente que cumple lo demás, **entonces** intake sin candidato. Test: `test_pol_aut_intake_above_150_is_not_candidate`.

### POL-AUT-150

43. **Dado** exactamente $150 de un cliente Plus, 250 días, 0 quejas, **entonces** `provisional_credit_candidate = True`, monto 150, acción `OPEN_DISPUTE_ONLY`, cita `POL-AUT-INTAKE` y `POL-AUT-150`. Test: `test_pol_aut_150_exactly_150_is_candidate`.
44. **Dado** cuenta de 180 días, no es candidato; **dado** 181, sí. Test: `test_pol_aut_150_account_age_boundary`.
45. **Dado** segmento Basic o Student, o 1 queja en 90 días, **entonces** no es candidato. Test: `test_pol_aut_150_segment_and_complaints_gate`.
46. **Dado** un candidato, **entonces** ni `explanation_es` ni `explanation_pt` contienen "crédito", y dicen que el caso quedó registrado y en revisión. Test: `test_pol_aut_150_customer_never_hears_credit` (reemplaza al test existente de crédito provisional).
47. **Dado** 608.000 COP a 4.054,70 (149,95 USD), **entonces** es candidato y `provisional_credit_amount_usd = 149,95`. Test: `test_pol_aut_150_currency_matrix`.

## 3. Supuestos

- **S1. Vocabulario de resultados.** `policy_outcome` gana `CLARIFICATION_REQUIRED`; `action_required` gana `ASK_CLARIFICATION` y `ESCALATE` reemplaza a `HOLD_CARD_AND_ESCALATE`; `OPEN_DISPUTE_AND_CREDIT` desaparece. Nada fuera de los tests usa los valores viejos (grep del 27-Sep).
- **S2. El bloqueo es una recomendación, no un resultado.** `card_lock_recommended`, `card_lock_reason` y `card_lock_required_authentication` se calculan una vez a partir de las señales (reclamo de robo, o más de 2 cargos en 48 h) y viajan con cualquier decisión, incluida una abstención o una escalación legal (confirmado por el equipo, P5). Si aplican las dos, la razón más específica (`STOLEN_CARD_CLAIM`) nombra el bloqueo. Las guardas de producto (solo tarjetas en estado Active) y la confirmación Sí o No del cliente viven en gateway y orquestador. Id `POL-AUT-LOCK` aceptado (P7).
- **S3. Campos del cargo opcionales.** Cuando `POL-CLARIFY` detiene la evaluación por cero o varios candidatos no hay un cargo, así que `transaction_*` y `amount_usd` aceptan `None`. Pasada `POL-CLARIFY` con un solo candidato, un cargo ausente es un error de programación y el motor lanza `ValueError`.
- **S4. Fuera de alcance sin candidatos.** Con `dispute_intent = fuera_de_alcance` la cuenta de candidatos no se evalúa (no hay cargo que identificar); `POL-DISP-TYPE` se abstiene solo con confianza decisiva (>= 0,70 o sin valor, que es el extractor de respaldo) y nombra la categoría de la lista cerrada `OUT_OF_SCOPE_CATEGORIES` (prestamo_o_credito, saldo_o_extracto, inversion_o_seguro, soporte_de_tarjeta, otro_producto, no_determinado). Con confianza menor, `POL-CLARIFY` pregunta antes (P4).
- **S5. Intentos de aclaración.** `clarification_attempts` cuenta preguntas ya hechas. Con una condición de aclaración vigente y 2 intentos o más, `POL-ESC-AMBIG` escala en vez de preguntar de nuevo.
- **S6. Bordes.** Confianza < 0,70 estricto; banda de robo inclusiva [0,40, 0,60]; bloqueo >= 0,80; angustia >= 2,0 sobre el valor esperado, sin redondeo; monto > 500 estricto y <= 150 inclusivo; antigüedad > 180 estricto; ventana <= 60 inclusivo; varios cargos > 2 estricto.
- **S7. Respaldo por palabras clave y memoria de casos.** Las señales de Jev llegan como `Optional[float]`. `None` activa el respaldo de palabras clave (angustia y robo) o salta la comprobación (confianza de intención, que el extractor de respaldo no produce). Con un valor de Jev presente, las palabras clave no se consultan. La memoria de casos (`prior_distress_max_30d`, `prior_escalations_180d`, `prior_cases_180d`, `prior_lock_refused`) entra como campos tipados alimentados por fixtures hasta que exista el agregado en `ops`; una marca de angustia severa en la memoria escala en los dos modos (P3).
- **S8. Listas de respaldo.** El brief no da las listas ES/PT de angustia ni de robo. Se parte de listas cortas escritas por el equipo en el código, como constantes con nombre: angustia ES (desesperado, desesperada, no tengo para comer, no tengo dinero, me quedé sin nada, emergencia, urgente) y PT (desesperado, desesperada, não tenho como, não tenho dinheiro, fiquei sem nada, emergência, urgente); robo ES (me robaron, robaron, robo, perdí la tarjeta, extravié) y PT (roubaram, roubo, perdi o cartão, extraviei). Se extienden en el split de desarrollo.
- **S9. `amount_usd` nulo.** Los 291 vacíos reales de la muestra (COP y ARS) se rellenan aguas arriba con la tasa diaria, con marca y columna legada (`docs/technical-discuss-points.md` sección 1). Un nulo que llegue al motor es un defecto de datos: escalación a humano bajo `POL-DISP-TYPE` con razón `DATA_GAP_AMOUNT_USD` y marca `MISSING_AMOUNT_USD` (P2).
- **S10. Cláusulas citadas.** `cited_clauses` lleva las puertas superadas que importan al caso (`POL-DISP-TYPE`, `POL-WIN-60`) y la cláusula decisoria al final. `POL-ESC-LEGAL` y `POL-CLARIFY` citan solo su cláusula porque corren antes de las puertas; `POL-ESC-AMBIG` cita `POL-CLARIFY` y a sí misma. `secondary_clauses` lista las escalaciones que también dispararon detrás de la decisoria, en el orden de la política, sin cambiar resultado ni razón (P1).
- **S11. Valores del caso.** `case_values` sale del motor con los cinco valores del diccionario; la subcategoría es "Cobro indebido" cuando la intención es `cobro_indebido` y "Cargo no reconocido" en cualquier otro caso. `recent_disputed_charges_count` incluye el cargo evaluado; contar cargos distintos y listar los candidatos en la pregunta de aclaración son tareas del orquestador (el motor devuelve la razón y el texto base).
- **S12. `is_eligible`.** Verdadero cuando un cargo superó las puertas (`POL-DISP-TYPE`, `POL-WIN-60`), es decir en escalaciones por monto, riesgo, cargos o angustia y en resultados autónomos; falso en aclaraciones, en toda abstención y en las escalaciones que ocurren sin cargo elegible (`POL-ESC-AMBIG`, `DATA_GAP_AMOUNT_USD`). `POL-ESC-LEGAL` mantiene verdadero (el cargo no se evaluó, pero el caso sí es de disputa).
- **S13. Textos.** Siempre se generan ES y PT. Ningún texto menciona crédito, ningún texto de escalación promete una acción (el de riesgo ML pierde "Aplicamos bloqueo preventivo"), y el intake dice que el caso quedó registrado y en revisión.
- **S14. Tests v2.0.** Los cinco tests de política de `tests/test_dispute_flow.py` (ventana, ventana por día de proceso, crédito provisional, alto valor, legal) se mueven a `tests/test_dispute_policy.py` renombrados por cláusula; los que codifican v2.0 cambian en el mismo commit que cierra su brecha. `tests/conftest.py::sample_dispute_input` gana `transaction_type` y `transaction_status`.
- **S15. Palabras clave legales.** Se conserva la lista actual del código (reguladores, superintendencia, demanda, abogado, tribunal, denuncia penal, processo, advogado, denúncia).
- **S16. Segmento del sistema de registro.** El motor recibe `customer_segment` ya leído; que venga del sistema de registro y no del token es responsabilidad del orquestador (fuera de la porción).
- **S18. Autenticación por acción.** `DisputePolicyEngine.ACTION_AUTH_MATRIX` declara nivel de riesgo y autenticación por acción: `OPEN_DISPUTE_ONLY` y `ESCALATE` (LOW, SESSION), `ASK_CLARIFICATION` y `ABSTAIN` (LOW, SESSION), `LOCK_CARD` (MEDIUM, SESSION_AND_CUSTOMER_CONFIRMATION), `UNLOCK_CARD` (HIGH, STEP_UP_AND_AGENT) y `APPROVE_CREDIT_CANDIDATE` (HIGH, AGENT_ROLE: rol de agente en el token con auditoría, como en la tabla de `docs/technical-discuss-points.md` 2.4). La decisión lleva `required_authentication` para su acción principal. El desbloqueo no es un resultado del motor ni una acción del chat: es una acción de la consola pendiente de fila en el registro de decisiones (P5).
- **S19. Passthroughs.** `risk_top_features` (contrato de SHAP, fixture) y la memoria de casos entran tipados y salen sin leerse en `risk_top_features` y `case_memory`, para el handoff (P1, P3).
- **S17. Documentación.** Al cerrar la fase 2 se actualizan el párrafo de la política en `CLAUDE.md`, la fila "Dispute policy" de `AGENTS.md` sección 9 y la nota "(new) = added in v2.1, not yet in code" del brief.

## 4. Preguntas para el equipo (resueltas el 27-Sep; detalle en `docs/technical-discuss-points.md`, sección 2)

- **P1.** Resuelta: `secondary_clauses` en la decisión y passthrough de `risk_top_features`; el resto de la propuesta (perfil, SHAP, herramientas, consola) va en `docs/specs/customer-profile-risk-explanation-spec.docx` para discusión.
- **P2.** Resuelta: limpieza aguas arriba con marca y columna legada; el motor escala con el vacío nombrado.
- **P3.** Resuelta: la memoria de casos alimenta la decisión determinista en los dos modos; `POL-ESC-DISTRESS` escala por memoria.
- **P4.** Resuelta: lista cerrada de categorías no soportadas, Jev las define con contexto profundo, y sin confianza decisiva no se decide.
- **P5.** Resuelta: bloqueo recomendado en cualquier resultado y matriz de autenticación por acción; el desbloqueo es una acción de consola de nivel alto pendiente de fila en el registro.
- **P6.** Resuelta: listas de respaldo como se propusieron.
- **P7.** Resuelta: `POL-AUT-LOCK`.

Texto original de las preguntas, para el registro:

- **P1.** Cuando aplican varias escalaciones a la vez ($850 con riesgo 0,9), ¿el handoff necesita las cláusulas secundarias? La spec dice que la primera regla decide; el motor cita solo esa. Si el handoff las necesita, se agrega un campo `secondary_clauses` en otra porción.
- **P2.** `amount_usd` nulo: ¿abstención (lectura literal del error de datos en `POL-DISP-TYPE`, supuesto S9) o escalación a humano para que complete el caso? Una escalación omitida cuesta 10 veces una innecesaria, pero aquí no hay escalación requerida, hay un dato faltante.
- **P3.** Con Jev presente y un score de angustia bajo, ¿debe una palabra clave de angustia escalar de todos modos (cinturón y tirantes) o rige la señal de Jev? El brief dice "como respaldo"; el motor sigue esa lectura (supuesto S7).
- **P4.** Intención `fuera_de_alcance` con cero candidatos: ¿abstención por alcance (supuesto S4) o pregunta de aclaración con cero candidatos, como diría el orden literal?
- **P5.** Reclamo de robo sobre un cargo fuera de ventana o no disputable: ¿se recomienda el bloqueo igual (supuesto S2)? Protege al cliente aunque no haya caso.
- **P6.** Las listas ES/PT de angustia y de robo del supuesto S8: validar las palabras antes del split de desarrollo.
- **P7.** ¿Se acepta `POL-AUT-LOCK` como id de la regla de bloqueo en el brief, o se deja sin id?

## 5. Medición y optimización (fase 3)

**Carga:** los 11.703 movimientos de junio 2026 de la muestra de 25.000 clientes en `data/lakehouse.duckdb` (abierta en solo lectura), unidos a `gold_customers`. Cada fila entra al motor con mensaje vacío, sin señales de Jev, riesgo ML 0,0 y 1 cargo disputado, como hace el notebook `notebooks/01_problema_y_datos.ipynb`.

**Línea base medida el 27-Sep** (script `measure_policy.py` en el scratchpad de la sesión; motor en el commit 48cbcaf; lakehouse reconstruido el 27-Sep con `sample_only=True`; cada fila entra con mensaje vacío, sin señales de Jev, riesgo ML 0,0, 1 cargo disputado, `transaction_date = process_date`, `amount_usd = amount_usd_normalized`):

| Métrica | Notebook (celda 26 y celda 28) | Motor v2.3 | Denominador |
| --- | --- | --- | --- |
| Movimientos evaluados | 11.703 | 11.703 | muestra de junio 2026 |
| Abstenciones `POL-DISP-TYPE` (`NOT_DISPUTABLE_CHARGE`) | 2.736 (1.930 por tipo, 806 por estado) | 2.736 | 11.703 |
| Disputables en ventana | 8.967 | 8.967 (0 fuera de ventana, 0 con fecha futura, 0 vacíos de `amount_usd`) | 11.703 |
| `POL-ESC-500` | 3.547 (39,6 %) en la salida de la celda; 3.546 (39,5 %) en el texto | 3.547 (39,6 %) | 8.967 |
| Candidatos `POL-AUT-150` | 482 (5,4 %) | 482 (5,4 %) | 8.967 |
| Intake sin candidato | 4.938 (55,1 %) en la salida; 4.939 en el texto | 4.938 (55,1 %) | 8.967 |
| Techo de contención (monto <= $500) | 60,4 % en la salida; 60,5 % en el texto | 60,4 % | 8.967 |
| Latencia del motor | no medida | 3,8 microsegundos por decisión (mediana de 3 repeticiones: 3,8, 3,8, 3,8); 0 tokens | 11.703 decisiones por repetición |

Verificado de nuevo el 27-Sep sobre el lakehouse reconstruido con `amount_usd` corregido en silver (commit 1d7eb71): cifras idénticas (291 filas rellenadas con la tasa diaria, 0 nulos, 4,2 microsegundos por decisión). Diferencias explicadas: el motor coincide con la salida ejecutada de la celda 26 en todas las cifras. Las cifras del texto de la celda 28 (3.546, 4.939, 60,5 %) difieren en una fila: el texto se redactó a mano y no se regeneró tras la última corrida; la salida de la celda es la fuente. Ninguna fila cae en `POL-WIN-60` porque la muestra de junio va de 0 a 16 días; el fixture de abril cubre la abstención por ventana.

**Efecto de `amount_usd` nulo (P2):** si el motor recibiera la columna cruda en vez de la normalizada, 291 filas COP y ARS llegarían con `amount_usd` nulo: 65 se abstienen antes por no ser disputables y 226 (2,5 % de los 8.967) escalarían a humano como `DATA_GAP_AMOUNT_USD`. Con la limpieza aguas arriba (`docs/technical-discuss-points.md` sección 1) ese número es 0.

**Sensibilidad del techo** (cálculo sobre los montos de los 8.967 cargos disputables; el umbral del motor es spec y no se movió):

| Techo | Cargos por encima | Techo de contención |
| --- | --- | --- |
| $300 | 5.741 (64,0 %) | 36,0 % |
| $500 (spec) | 3.547 (39,6 %) | 60,4 % |
| $1.000 | 2.932 (32,7 %) | 67,3 % |

Evidencia para la fila Decidida "Techo de escalamiento de $500": subir a $1.000 gana 6,9 puntos de contención a cambio de decidir sin humano cargos de hasta $1.000; bajar a $300 pierde 24,4 puntos. La decisión queda como está.

**Perillas legítimas:** ninguna en esta porción. Los umbrales de la política son spec; los de Jev y LightGBM se fijan en el split de desarrollo, que aún no existe, sobre motores que aún no existen. La fase termina con la línea base, la tabla de sensibilidad y las propuestas registradas en `docs/PLAN.md` (filas Propuesta del 27 sep).

**Tabla de intentos:**

| Hipótesis | Cambio | Métrica antes | Métrica después | n | Decisión |
| --- | --- | --- | --- | --- | --- |
| Sin intentos: no hay perillas delegadas a esta porción | | | | | La línea base queda registrada; los umbrales de Jev y del modelo se ajustan en sus porciones sobre el split de desarrollo |

## 6. Contrato de entrada y salida (referencia para el orquestador)

`DisputePolicyInput`, campos nuevos o cambiados: `transaction_id`, `transaction_date`, `transaction_amount`, `transaction_currency`, `amount_usd` pasan a `Optional` con `None`; nuevos `transaction_type: Optional[str] = None`, `transaction_status: Optional[str] = None`, `candidate_charges_count: int = 1`, `clarification_attempts: int = 0`, `dispute_intent: Optional[str] = None`, `intent_confidence: Optional[float] = None`, `out_of_scope_category: Optional[str] = None`, `is_stolen_reported: Optional[float] = None`, `customer_distress_score: Optional[float] = None`, `risk_top_features: list = []`, `prior_distress_max_30d: Optional[float] = None`, `prior_escalations_180d: int = 0`, `prior_cases_180d: int = 0`, `prior_lock_refused: bool = False`. Sin cambios: `ml_risk_score`, `recent_disputed_charges_count`, `customer_message`, `current_date`.

`DisputePolicyDecision`, campos nuevos o cambiados: `provisional_credit_candidate` (antes `provisional_credit_eligible`), `card_lock_recommended: bool`, `card_lock_reason: Optional[str]`, `card_lock_required_authentication: Optional[str]`, `clarification_reason: Optional[str]`, `data_quality_flag: Optional[str]`, `case_values: dict`, `secondary_clauses: list`, `required_authentication: str`, `risk_top_features: list`, `case_memory: dict`. Vocabulario: `policy_outcome` en {`AUTONOMOUS_RESOLUTION`, `SAFE_POLICY_ABSTENTION`, `MANDATORY_HITL_ESCALATION`, `CLARIFICATION_REQUIRED`}; `action_required` en {`OPEN_DISPUTE_ONLY`, `ESCALATE`, `ABSTAIN`, `ASK_CLARIFICATION`}.
