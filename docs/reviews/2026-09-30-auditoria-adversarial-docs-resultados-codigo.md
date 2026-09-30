# Auditoría Adversarial: Documentación, Resultados y Código, Revisión en Profundidad (v2)

Fecha: 2026-09-30 (Día 6 de 10 del Hackathon).  
Alcance: Contraste exhaustivo entre la documentación oficial del certamen, las especificaciones del equipo (`README.md`, `AGENTS.md`, `docs/PLAN.md`, `docs/TEAM_BRIEF_COMPLEMENTED.md`, `docs/SUPABASE_VERCEL.md`, `docs/JEV_TYPESAFE_AI.md`), los reportes de resultados (`reports/eval_dev.md`, `reports/ml/`) y la implementación en código (`src/`, `frontend/`, `supabase/`, `tests/`).  
Revisión: Segundo pase en profundidad, corrigiendo y ampliando los 14 hallazgos originales y agregando 11 nuevos (AUD-15 a AUD-25).

---

## 1. Veredicto Ejecutivo

El **núcleo determinista** (máquina de estados y política v2.3) sigue siendo sólido: 85 pruebas unitarias verifican las cláusulas en su orden estricto, la arquitectura de "el modelo propone, el código decide" se cumple fielmente en `dispute_policy.py` y `dispute_orchestrator.py`, y el patrón Act-and-Verify con read-back está implementado en las acciones críticas (apertura de caso, bloqueo de tarjeta, creación de handoff).

Sin embargo, la **brecha entre lo documentado/afirmado y lo ejecutable** es amplia y sistémica. Afecta la **credibilidad** del entregable ante jurados de ingeniería de datos, ML e IA:

### Riesgos Bloqueantes (Descalificación o Impugnación de Métricas)

1. **AUD-01 (Regla 4): Modelo de riesgo sobre datos no aprobados.** TQ-026 sigue abierta.
2. **AUD-02 (Regla 5): Frontend sin credenciales reales.** Login por clic en ID.
3. **AUD-10 (Métricas): SAR 100.0% sobre denominador recortado** vs 50.0% sobre casos in-scope.
4. **AUD-11 (Evaluación): Suite held-out circular** y sin reporte publicado.

### Riesgos Altos (Falsedad de Capacidades Declaradas)

5. **AUD-03: Claude Haiku 4.5 y motor RAG inexistentes.**
6. **AUD-04: Modelo serializado ausente** (`models/` no existe).
7. **AUD-05: Despliegue Vercel documentado con métodos ficticios.**
8. **AUD-12: Reporte compara reglas vs baseline roto.**
9. **AUD-15 (nuevo): ONNX Runtime declarado pero no en dependencias.**
10. **AUD-16 (nuevo): Playwright smoke test prometido pero inexistente.**

---

## 2. Matriz Consolidada de Hallazgos (AUD-01 a AUD-25)

### Hallazgos Confirmados del Primer Pase (AUD-01 a AUD-14)

| ID | Severidad | Categoría | Afirmación en Docs | Realidad en Código | Confirmado v2 |
|---|---|---|---|---|---|
| **AUD-01** | Bloqueante | Datos / Regla 4 | Modelo IEEE-CIS como modelo de registro | Kaggle no aprobado; TQ-026 abierta; ROC AUC 0.507 | Sin cambio |
| **AUD-02** | Bloqueante | Seguridad / Regla 5 | Supabase Auth ES256, credenciales | `@supabase/supabase-js` no en `package.json`; login por clic; 404 en producción | Sin cambio |
| **AUD-03** | Alta | Arquitectura / LLM | Claude Haiku 4.5 + RAG | `anthropic` no en deps; respuestas son plantillas; no hay embeddings | Sin cambio |
| **AUD-04** | Alta | ML / Runtime | `TransferRiskScorer` activo | `models/` no existe; score siempre 0.0 | Sin cambio |
| **AUD-05** | Alta | Infraestructura | Despliegue Vercel con `app.frontend()` | Método inexistente; no hay `vercel.json` | Sin cambio |
| **AUD-06** | Media/Alta | Confiabilidad | Llaves de idempotencia y atomicidad | No implementadas | Sin cambio |
| **AUD-07** | Media | Backend / DB | `execute_open_dispute` normalizado | Escribe `Fraud`, `Chat`, `INTAKE_RECEIVED`; código muerto | Verificado: nunca llamado por el orquestador |
| **AUD-08** | Media | Observabilidad | OpenTelemetry | No en deps; no hay `trace_id` | Sin cambio |
| **AUD-09** | Media | Seguridad / API | API securizada | 4 endpoints legados sin autenticación | Confirmado |
| **AUD-10** | Alta | Evaluación | SAR 100.0% | Denominador sobre 9 elegibles, no 18 in-scope | Sin cambio |
| **AUD-11** | Alta | Evaluación | Suite held-out validada | Frases coinciden con regex; labels de diseño; sin reporte | Confirmado en profundidad |
| **AUD-12** | Alta | Evaluación | Comparación propuesto vs baseline | Ambos son reglas; metadata lo declara | Sin cambio |
| **AUD-13** | Alta | Resiliencia | DuckDB desacoplado | `.df().to_dict()` fuerza `pandas` | Líneas 74 y 114 de `gateway.py` |
| **AUD-14** | Baja | Pruebas | Tests unitarios verdes | `México` sin UTF-8 en Windows | Sin cambio |

### Nuevos Hallazgos de la Revisión en Profundidad (AUD-15 a AUD-25)

| ID | Severidad | Categoría | Afirmación en Docs | Realidad en Código | Riesgo ante el Jurado |
|---|---|---|---|---|---|
| **AUD-15** | Alta | ML / Deps | "Model served through ONNX Runtime" (TEAM_BRIEF L49, PLAN L65, L77) | `onnxruntime` no está en `pyproject.toml`. `joblib` sería el cargador si el modelo existiera. No hay ningún archivo `.onnx` en el repo. | Falsedad en tecnología declarada de serving del modelo. |
| **AUD-16** | Media/Alta | Testing / Docs | "Playwright smoke test covers the three case types and the console 403" (TEAM_BRIEF L52, PLAN L187, L227, L263) | No existe `playwright` en dependencias (ni Python ni npm). No hay ningún archivo de test e2e. | Compromiso de testing E2E no cumplido. |
| **AUD-17** | Media | Seguridad / API | "One domain, no CORS" (TEAM_BRIEF L53) | No hay middleware CORS en `app.py`. En desarrollo local, React en `:5173` y API en `:8000` necesitan Vite proxy. | Funcionalidad rota en topología multi-dominio. |
| **AUD-18** | Media | Seguridad / API | Los endpoints requieren token Bearer | No hay rate limiting en ningún endpoint. | DoS trivial; enumeración de clientes. |
| **AUD-19** | Baja/Media | Código / Deprecación | Python 3.12 en CI | 13 ocurrencias de `datetime.utcnow()` deprecado. | Warnings en CI; deuda técnica visible. |
| **AUD-20** | Alta | Evaluación / Held-out | 20 `high_fraud_anomaly` esperan escalamiento por ML risk | Sin modelo serializado, score=0.0, `POL-ESC-ML-RISK` nunca dispara. **20 de 250 held-out fallarán** (8%). | 20 unsafe outcomes distorsionan todas las métricas. |
| **AUD-21** | Media | Lógica / Orquestador | Multi-charge claim dispara `POL-ESC-MULTI` | Funciona para multi-turno (3 mensajes); no para single-message multi-charge. Limitación no documentada. | Comportamiento correcto para suite pero parcial. |
| **AUD-22** | Media | Seguridad / PII | "prompt-injection filter" en AGENTS.md | No hay filtro separado. Defensa por XML wrapping y ausencia de LLM. | Componente documentado que no existe; adecuado sin LLM. |
| **AUD-23** | Baja/Media | Coherencia / Datos | "Use or reconcile `is_repeat_complainer`" | Hardcodeado `False` en código muerto; no reconciliado. | Hallazgo documentado no abordado. |
| **AUD-24** | Media | Seguridad / Gateway PG | `execute_lock_card` respeta el parámetro `reason` | L103: insert hardcodea `reason='STOLEN_CARD_CLAIM'` ignorando el parámetro. | Dato incorrecto en auditoría de producción. |
| **AUD-25** | Media | Evaluación / Seguridad | Impersonation cases verifican no-disclosure | Transacción de la víctima está en el fixture, pero el filtro `WHERE customer_id = ?` la excluye. Test correcto por diseño del gateway, no del fixture. | Falso sentido de seguridad si el fixture se modificara. |

---

## 3. Análisis Detallado de Hallazgos Nuevos

### 3.1. Capacidades Declaradas que No Existen (AUD-15, AUD-16)

#### [AUD-15] ONNX Runtime Declarado Pero Inexistente
* **Evidencia documental:**
  * `docs/TEAM_BRIEF_COMPLEMENTED.md` L49: *"served through ONNX Runtime (proposed)"*.
  * `docs/PLAN.md` L65: *"Modelo de riesgo LightGBM, servido en ONNX"*.
  * `docs/PLAN.md` L77: *"RAG explicativo de la política (embeddings ONNX locales)"*.
* **Evidencia en código:**
  * `onnxruntime` no aparece en `pyproject.toml`.
  * `src/ml/fraud_risk_transfer.py` carga con `joblib`, no con ONNX.
  * No existe ningún archivo `.onnx` en el repositorio.

#### [AUD-16] Playwright Smoke Test Inexistente
* **Evidencia documental:**
  * `docs/TEAM_BRIEF_COMPLEMENTED.md` L52: *"a Playwright smoke test covers the three case types and the console 403"*.
  * `docs/PLAN.md` L187, L227, L263.
* **Evidencia en código:**
  * `playwright` no está en `pyproject.toml`, `package.json` ni `uv.lock`.
  * No existe ningún directorio o archivo de test e2e en el repositorio.

### 3.2. Seguridad y Resiliencia (AUD-17 a AUD-19, AUD-22, AUD-24)

#### [AUD-17] CORS No Configurada
* No hay `CORSMiddleware` en `src/api/app.py`. Justificación documental válida ("one domain"), pero en desarrollo local React y API corren en puertos distintos y requieren el Vite proxy.

#### [AUD-18] Ausencia Total de Rate Limiting
* No hay `slowapi`, `fastapi-limiter` u otro en dependencias. Los endpoints de chat y test-session no tienen límite de requests.

#### [AUD-19] `datetime.utcnow()` Deprecado
* 13 ocurrencias en `src/`. Python 3.12 emite `DeprecationWarning`. CI corre 3.12.
* Corrección: `datetime.now(timezone.utc)`.

#### [AUD-22] Filtro de Inyección de Prompt Inexistente
* `AGENTS.md` L222 documenta *"prompt-injection filter"*. Solo existe el wrapping XML de merchants. Sin LLM activo, la defensa es suficiente. Si Claude se integra, hace falta un filtro real.

#### [AUD-24] Hardcodeo de `STOLEN_CARD_CLAIM` en Postgres Gateway
* `gateway_postgres.py` L103: `reason='STOLEN_CARD_CLAIM'` en el INSERT ignora el parámetro `reason`.

### 3.3. Evaluación y Métricas: Análisis en Profundidad

#### [AUD-20] 20 Held-Out Cases Fallarán Sin Modelo
1. `high_fraud_anomaly` genera 20 casos con `expected = escalation(lang, "HIGH_FRAUD_RISK_SCORE")`.
2. Sin modelo, `ml_risk_score = 0.0 < ml_risk_threshold = 0.70`.
3. `POL-ESC-ML-RISK` no dispara. Montos entre 60-480 USD (≤ 500).
4. El sistema abrirá caso autónomo → **20 fallas, 20 unsafe outcomes**.

#### [AUD-11, Profundización] Circularidad de la Suite Held-Out
1. Templates de `TEMPLATES["dispute"]` usan frases idénticas a las keywords del extractor.
2. Templates de `lock_yes` coinciden exactamente con `YES_WORDS`.
3. Todos los labels son `label_source: "design"`.
4. TQ-018 (etiquetado humano con kappa) no ejecutado.
5. `reports/eval_heldout.md` no existe.

---

## 4. Plan de Acción Revisado

### Fase 1: Resiliencia Crítica (Hoy 30 Sep, Noche)

| # | Acción | Hallazgo | Esfuerzo |
|---|---|---|---|
| 1 | Desacoplar DuckDB de Pandas en `gateway.py` L74, L114 | AUD-13 | 15 min |
| 2 | Corregir codificación UTF-8 en `test_heldout_suite.py` | AUD-14 | 5 min |
| 3 | Reemplazar `datetime.utcnow()` por `datetime.now(timezone.utc)` (13 sitios) | AUD-19 | 20 min |
| 4 | Corregir hardcodeo `STOLEN_CARD_CLAIM` en `gateway_postgres.py` L103 | AUD-24 | 5 min |
| 5 | Eliminar o proteger endpoints legados en `app.py` | AUD-09 | 15 min |

### Fase 2: Identidad, Modelo y Métricas (1 Oct)

| # | Acción | Hallazgo | Esfuerzo |
|---|---|---|---|
| 6 | Añadir campo de credencial en frontend Login y validar en `test-session` | AUD-02 | 2 h |
| 7 | Resolver AUD-20: serializar modelo mínimo O modificar expectations de `high_fraud_anomaly` | AUD-04, AUD-20 | 2 h |
| 8 | Doble denominador SAR en `metrics.py` (elegibles + in-scope) | AUD-10 | 30 min |
| 9 | Eliminar enums prohibidos de `execute_open_dispute` en `gateway.py` | AUD-07 | 10 min |

### Fase 3: Sinceramiento Documental (1-2 Oct)

| # | Acción | Hallazgo | Esfuerzo |
|---|---|---|---|
| 10 | Actualizar README y AGENTS: Claude y RAG son "planned, not implemented" | AUD-03 | 30 min |
| 11 | Actualizar docs: ONNX es "proposed, not implemented" | AUD-15 | 15 min |
| 12 | Documentar Playwright como pendiente | AUD-16 | 15 min |
| 13 | Documentar despliegue real (FastAPI + `StaticFiles`) | AUD-05 | 15 min |
| 14 | Documentar llaves de idempotencia y OpenTelemetry como trabajo futuro (Regla 11) | AUD-06, AUD-08 | 15 min |
| 15 | Documentar filtro de prompt injection como no necesario sin LLM | AUD-22 | 10 min |
| 16 | Documentar `is_repeat_complainer` como pendiente | AUD-23 | 5 min |

### Fase 4: Evaluación Held-Out y Cierre (2-3 Oct)

| # | Acción | Hallazgo | Esfuerzo |
|---|---|---|---|
| 17 | Ejecutar suite held-out y publicar `reports/eval_heldout.md` | AUD-11 | 2 h |
| 18 | Declarar en reporte: labels de diseño, frases sintéticas, sobreajuste admitido | AUD-11 | 30 min |
| 19 | Comparar contra baseline en el reporte con los mismos 250 casos | AUD-12 | 1 h |
| 20 | Decidir TQ-026 (datos Kaggle): documentar como experimental si no hay respuesta | AUD-01 | Equipo |

### Fase 5: Despliegue y Video (4-5 Oct)

| # | Acción | Hallazgo | Esfuerzo |
|---|---|---|---|
| 21 | Deploy público con verificación manual | AUD-05 | 3 h |
| 22 | Video: transparencia sobre lo implementado vs planned | Todos | 2 h |
| 23 | Rate limiting básico para demo pública | AUD-18 | 1 h |

---

## 5. Resumen de Severidades

| Severidad | Conteo | IDs |
|---|---|---|
| **Bloqueante** | 2 | AUD-01, AUD-02 |
| **Alta** | 10 | AUD-03, AUD-04, AUD-05, AUD-10, AUD-11, AUD-12, AUD-13, AUD-15, AUD-20, AUD-25 |
| **Media/Alta** | 2 | AUD-06, AUD-16 |
| **Media** | 8 | AUD-07, AUD-08, AUD-09, AUD-17, AUD-18, AUD-21, AUD-22, AUD-24 |
| **Baja/Media** | 2 | AUD-19, AUD-23 |
| **Baja** | 1 | AUD-14 |
| **Total** | 25 | - |

---

## 6. Hallazgos Positivos (Lo que Funciona Bien)

1. **Política v2.3 completamente implementada:** 12 cláusulas en orden estricto con 85 tests, clause ids trazables.
2. **Act-and-Verify riguroso:** Read-back obligatorio con manejo de falla (escalamiento automático).
3. **Zero-trust en customer_id:** Sale siempre del token, nunca del body ni del modelo.
4. **Suite con inyección de fallas:** `_Faulty` wrapper simula `missing`, `verification_error` y `timeout`.
5. **Máscara PII con patrones LATAM:** CURP, CPF, DNI, CC, cédula; protección contra falsos positivos en montos.
6. **Desacoplamiento DuckDB/Postgres:** Una interfaz, dos backends, SQL reescrito automáticamente.
7. **Presupuesto diario de LLM:** $2/día cap, fallback automático, append-only usage log.
8. **Defensa contra inyección en merchant:** XML boundaries con `html.escape`.
9. **250 held-out cases en 10 categorías** con ataques de seguridad y fallas de herramientas inyectadas.
10. **Multi-turno genuino:** Clarificación, confirmación de bloqueo, re-inicio.
