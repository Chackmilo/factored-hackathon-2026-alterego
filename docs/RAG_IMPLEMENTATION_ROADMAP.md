# Plan de Implementación y Roadmap: Motor RAG de Explicaciones de Política

**Estado:** Aprobado con revisiones técnicas incorporadas. TQ-037 respondida el 30-Sep (opción 1); hechas la Tarea 1.1 (`data/policy_corpus.json`), el camino BM25 en `src/rag/` (2.1, 2.2, 3.1 a 3.3), el desvío al explicador (5.1), la herramienta de la 4.1, la medida de la 2.0 (E5 no cabe en el bundle con el código de hoy; cabe si el modelo de riesgo pasa a ONNX, TQ-022) y el buscador E5 de la 2.3, que se mide offline; el explicador sigue apagado hasta que la 4.1, corrida sobre el banco de la 1.2, escriba `data/rag_gate.json` con los umbrales calibrados.  
**Fecha de Actualización:** 2026-10-01 (Tareas 4.1, 2.0 y 2.3; la segunda revisión del 30-Sep, con sus cambios y motivos, está en la sección 7)  
**Basado en:** Hallazgos del Notebook *Augmented Generation* (`11d894be-6dd0-4680-ad7e-d9a2e8457d76`), reglas de [`AGENTS.md`](../AGENTS.md), especificación [`docs/specs/dispute-policy-v2.3.md`](specs/dispute-policy-v2.3.md), revisión tecnológica [`docs/reviews/2026-09-26-revision-tecnologica.md`](reviews/2026-09-26-revision-tecnologica.md), model card de [`intfloat/multilingual-e5-small`](https://huggingface.co/intfloat/multilingual-e5-small) y resolución de hallazgos **AUD-03 / AUD-15** de [`docs/reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md`](reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md).

---

## 1. Contexto y Objetivos del Proyecto

En el sistema bancario de atención a reclamos de fraude y disputas (Hackathon Factored 2026), el componente de RAG tiene un mandato estricto y delimitado:

1. **El modelo propone, la política determinista dispone:** El motor de políticas como código (`src/rules/dispute_policy.py`) es la única autoridad que decide si un caso es elegible, si se escala a un agente humano (HITL) o si se recomienda bloqueo preventivo.
2. **Rol exclusivo del RAG:** Responder preguntas informativas de los clientes sobre la política de disputas del banco en **Español y Portugués**, citar el identificador oficial de la cláusula (`[POL-XXX]`) y **abstenerse con seguridad** (`SAFE_POLICY_ABSTENTION`) cuando la pregunta escape al alcance normativo o carezca de fundamento. El RAG nunca cambia una decisión, no promete reembolsos ni mueve dinero, y no atiende turnos con señal de disputa, legal o de angustia: esos siguen el flujo actual (sección 4).
3. **Política en español, respuesta en el idioma del cliente:** Conforme a [`docs/PLAN.md:181`](PLAN.md#L181), el texto de política se redacta en español y solo la interacción con el cliente va en ES o PT. Cada cláusula que el cliente puede leer lleva su respuesta en ES y en PT (`answer_es`, `answer_pt`); el contenido en portugués es siempre `team-generated` ([`AGENTS.md`](../AGENTS.md), sección 11). Ningún modelo redacta texto: la respuesta es una plantilla.
4. **No todas las cláusulas se explican al cliente:** `POL-AUT-150` (el cliente nunca oye que se aplicó crédito: [spec, fila POL-AUT-150](specs/dispute-policy-v2.3.md#L30), y regla 8 de AGENTS.md), `POL-SEC-SESSION` (control de autenticación fuera de la política de disputas: [spec:8](specs/dispute-policy-v2.3.md#L8)) y `POL-ESC-ML-RISK` (umbral interno del modelo de fraude). Decidido en TQ-037 (30-Sep): se indexan, pero se responden con un texto fijo de redirección.
5. **Restricción de infraestructura:** Despliegue en Vercel con un límite de bundle de **500 MB**, sin PyTorch. E5 se despliega en ONNX int8 solo si cabe (Tarea 2.0); si no, el motor es **BM25**, que ya es el respaldo decidido ([`docs/PLAN.md:211`](PLAN.md#L211)).

---

## 2. Hallazgos Clave del Notebook *Augmented Generation* y su Aplicación

El análisis de las 29 fuentes del notebook deja lecciones que guían el diseño. Los nombres CRAG, CAG y Self-RAG señalan la idea que se toma prestada: el sistema no implementa esas técnicas, y la documentación no debe decir que lo hace (es el tipo de hallazgo de AUD-03).

| Arquitectura / Concepto | Hallazgo en el Notebook | Implicación Directa en Nuestro Proyecto |
| :--- | :--- | :--- |
| **Naive RAG (Riesgo de "Fe Ciega")** | El LLM asume ciegamente que los fragmentos recuperados son válidos. Si el retriever falla o trae fragmentos irrelevantes, el modelo alucina respuestas inventadas con alta convicción. | **Crítico:** No se entrega texto recuperado sin filtrar. Una compuerta con umbrales $(\tau_{upper}, \tau_{lower})$ por retriever decide si se responde, se aclara o se abstiene (`SAFE_POLICY_ABSTENTION`). |
| **CRAG (Corrective RAG Cerrado)** | En dominios normativos/bancarios cerrados, **el fallback web de CRAG está prohibido** para evitar contaminación regulatoria. Se adapta a un evaluador tripartito: *Alta Confianza*, *Ambivalente* y *No Relevante*. | **Se toma la compuerta tripartita, no el evaluador entrenado de CRAG:** aquí la compuerta es un umbral sobre el score del retriever. *Alta*: responde con la plantilla y la cita. *Ambivalente*: lista las cláusulas candidatas. *Baja*: abstención segura explícita (*"No se encontró evidencia suficiente en la política de disputas vigente..."*). |
| **Calibración de Umbrales** | En literatura CRAG se usan bandas ilustrativas (ej. 0.7 y 0.3), pero en entornos de misión crítica los umbrales deben calibrarse empíricamente sobre un split de desarrollo. | **Gobernanza:** Los umbrales son hiperparámetros por retriever, calibrados solo en el split dev del banco de preguntas de política (Tarea 1.2). No sirve `data/eval/dev_cases.jsonl`: son 18 casos de disputa sin cláusula esperada. E5 concentra el coseno entre 0.7 y 1.0 (FAQ 3 de su model card: temperatura 0.01) y BM25 no tiene escala fija, así que no hay umbral común ni semilla universal. |
| **CAG (Cache-Augmented Generation)** | Precarga el corpus estático en memoria para latencia sub-segundo (< 1 s) y cero omisión en bases de conocimiento pequeñas y estables. | **Se toma la precarga, no la técnica:** CAG pone el corpus en el contexto de un LLM, y aquí no hay LLM en la respuesta. El corpus (13 cláusulas, < 4.000 tokens), el índice BM25 y los vectores viven en RAM. El modelo E5 (118 MB) se carga en el primer turno `consulta_politica` de cada instancia, así que el arranque en frío se mide (Tarea 2.0). |
| **GraphRAG / ArchRAG** | Destacan en razonamiento multisalto sobre cientos de entidades interconectadas, pero su costo de indexación es $\mathcal{O}(N^2)$ (3-5x más tokens) y latencia alta (5-15 s). | **Descarte justificado:** Para 13 cláusulas disjuntas, GraphRAG añade complejidad y latencia sin beneficio. Basta un retriever léxico (BM25) o denso (E5); la Hipótesis 5 decide cuál. |
| **Self-RAG (Verificación Fáctica `IsSup`)** | Valida que cada afirmación generada esté 100% respaldada (`Fully Supported`) por el contexto extraído antes de entregar la respuesta final. | **Se toma la garantía, no la técnica:** Self-RAG entrena un crítico sobre texto generado, y aquí no se genera texto. La respuesta es la plantilla de la cláusula (`answer_es` / `answer_pt`), respaldada por construcción. Prohibido prometer reembolsos, inventar plazos o mencionar crédito provisional. |

---

## 3. Diagnóstico de Brechas Actuales (Gap Analysis)

| Área | Requisito del Proyecto / Auditoría | Estado Actual en el Repositorio | Brecha Identificada |
| :--- | :--- | :--- | :--- |
| **1. Corpus de Políticas** | Corpus canónico de las 13 cláusulas de la [spec v2.3](specs/dispute-policy-v2.3.md), cada una con nivel de exposición (TQ-037), texto en español, respuesta al cliente en ES y PT y parámetros. | Existe la lógica en `dispute_policy.py` y la spec, pero no un archivo canónico estructurado. | Falta `data/policy_corpus.json`. |
| **2. Dependencias de Serving** | `rank-bm25` siempre; `onnxruntime` y `tokenizers` solo si E5 se despliega. | `rank-bm25` está en `pyproject.toml` desde el 30-Sep (Tarea 2.1); `onnxruntime` y `tokenizers` no (observado en **AUD-15**). | Agregar `onnxruntime` y `tokenizers` tras la Tarea 2.0, dentro del límite de 500 MB. |
| **3. Modelo de Embeddings** | `intfloat/multilingual-e5-small`, artefacto oficial `onnx/model_qint8_avx512_vnni.onnx` (118 MB) con `onnx/tokenizer.json` (17 MB), fijado por commit y SHA-256; prefijos `"query: "` / `"passage: "`; average pooling y normalización L2 (model card). | No hay archivos `.onnx`. `.gitignore` solo ignora `models/*.joblib`, y el modelo supera el límite de 100 MB por archivo de GitHub: un commit accidental rompe el push. | Script de descarga en el build con commit y SHA-256, carpeta del modelo en `.gitignore`, embeddings del corpus precomputados (`data/policy_embeddings.npy`). |
| **4. Baseline Comparativo** | Baseline BM25 obligatorio para contrastar `Recall@3` contra los embeddings ([Hipótesis 5](PLAN.md#L26)). | `src/rag/bm25_retriever.py` existe desde el 30-Sep (Tarea 2.2). | Falta el benchmark contra E5 (Tarea 4.1). |
| **5. Evaluación y Métrica** | Banco de preguntas de política con split dev (calibración) y test (reporte, congelado con SHA-256), cláusula esperada y acción esperada (`answer`, `clarify`, `abstain`). | No existe. `data/eval/dev_cases.jsonl` tiene 18 casos de disputa sin cláusula esperada: no sirve para calibrar el RAG. | Faltan `data/eval/policy_questions_dev.jsonl`, `data/eval/policy_questions_test.jsonl` y `src/eval/rag_benchmark.py`. |
| **6. Enrutamiento del Orquestador** | Intent `consulta_politica` que no secuestre `consulta_general` ni se salte las escalaciones. | `consulta_general` cubre saldos y extractos ([`jev_extractor.py:29`](../src/understand/jev_extractor.py#L29)) y es el valor por defecto de palabras clave ([`keyword_extractor.py:141`](../src/understand/keyword_extractor.py#L141)). POL-ESC-LEGAL y POL-ESC-DISTRESS se evalúan dentro de `DisputePolicyEngine.evaluate` ([`dispute_policy.py:297`](../src/rules/dispute_policy.py#L297)), y el ajuste que convierte en disputa un mensaje con monto o cargo solo actúa sobre `consulta_general` ([`keyword_extractor.py:215`](../src/understand/keyword_extractor.py#L215)). | Hecho el 30-Sep con una señal `policy_question` en lugar de un intent nuevo (Tarea 5.1); falta encenderlo con los umbrales de la 4.1. |

---

## 4. Arquitectura Propuesta: Explicador de Política con Compuerta de Abstención

```text
                    [Turno del cliente, ya enmascarado (ES / PT)]
                                         │
                                         ▼
                     ┌─────────────────────────────────────┐
                     │ Understand existente                │
                     │ (idioma de la conversación, intent) │
                     └──────────────────┬──────────────────┘
                                        ▼
                     ┌─────────────────────────────────────┐
                     │ Guarda de desvío: estado new,       │
                     │ intent consulta_politica y ninguna  │
                     │ señal de disputa, legal ni angustia │
                     └─────────┬─────────────────┬─────────┘
                            sí │                 │ no
                               ▼                 ▼
          ┌───────────────────────────┐   ┌───────────────────────────┐
          │ Retriever (en RAM)        │   │ Flujo de disputa actual   │
          │ BM25, o E5 ONNX int8 si   │   │ (DisputePolicyEngine,     │
          │ gana H5 y cabe en el      │   │  POL-ESC-LEGAL primero)   │
          │ bundle                    │   └───────────────────────────┘
          └─────────────┬─────────────┘
                        ▼
          ┌───────────────────────────┐
          │ Compuerta de confianza    │
          │ (umbrales por retriever,  │
          │  calibrados en split dev) │
          └─────────────┬─────────────┘
                        │
    ┌───────────────────┼─────────────────────┐
    │ score ≥ τ_upper   │ τ_lower ≤ score     │ score < τ_lower
    │                   │ < τ_upper           │
    ▼                   ▼                     ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Responde con   │ │ Aclara: lista  │ │ Abstención     │
│ la plantilla   │ │ los títulos de │ │ segura         │
│ ES/PT y cita   │ │ las cláusulas  │ │ (SAFE_POLICY_  │
│ [POL-XXX]      │ │ candidatas     │ │  ABSTENTION)   │
└────────────────┘ └────────────────┘ └────────────────┘
```

Reglas del desvío:

- **Precedencia de la disputa:** la señal `policy_question` del extractor de palabras clave pide una pregunta (signo o palabra interrogativa al inicio) sobre las reglas (plazos, proceso, qué se puede disputar, devoluciones, desbloqueo) y se apaga ante un monto, una fecha, un demostrativo ("este cargo"), una frase de disputa, una cláusula que disputa un cargo, una tarjeta robada u otro producto. "¿Cuánto plazo tengo para el cargo de 300 que no reconozco?" es una disputa; "¿Cuánto tiempo tengo para disputar un cargo?" es una pregunta de política. Ante la duda dice que no, porque un falso negativo deja el comportamiento de hoy.
- **Escalaciones primero:** si POL-ESC-LEGAL o POL-ESC-DISTRESS dispararían, el turno sigue el flujo de disputa. La guarda llama a `DisputePolicyEngine.message_escalation`, que reutiliza la detección legal y de angustia de la política (con la señal de Jev y la memoria de casos) en vez de copiar listas. Con Jev, una probabilidad de robo de 0.40 o más o el intent `fuera_de_alcance` también dejan el turno en el flujo de disputa.
- **Solo en estado `new`** (`closed` y `escalated` ya vuelven a `new`: [`dispute_orchestrator.py:177`](../src/orchestrator/dispute_orchestrator.py#L177)). En `awaiting_clarification` y `awaiting_lock_confirmation` sigue el flujo actual; responder ahí queda para después del MVP.
- **Cláusula `internal` recuperada:** texto fijo de redirección, sin contenido ni parámetros de la cláusula (TQ-037).
- **Datos y auditoría:** el retriever ve solo el mensaje enmascarado ([`docs/PLAN.md:178`](PLAN.md#L178)). La respuesta deja la conversación en `new`, no abre caso, no lee el banco y se registra en `ops.audit_log` como `POLICY_EXPLAINED` (retriever, acción, banda de la compuerta, ids y scores del top 3; con E5 se sumará el commit del modelo). El resultado del turno es `POLICY_EXPLANATION`, o `SAFE_POLICY_ABSTENTION` cuando se abstiene.
- **Un retriever en producción:** el que elija la Tarea 4.2; el benchmark corre ambos. No hay fusión híbrida.

---

## 5. Roadmap de Implementación (Paso a Paso)

```text
[Fase 1: Corpus y Preguntas] ──► [Fase 2: Retrievers] ──► [Fase 3: Compuerta y Respuestas] ──► [Fase 4: Benchmark] ──► [Fase 5: Integración y Cierre]
```

**Orden de ejecución:** primero el camino BM25 de punta a punta (1.1, 2.1, 2.2, 3.1, 3.2, 3.3, 5.1), que ya es el respaldo decidido; en paralelo 1.2 y 2.0; después 2.3, 4.1 y 4.2. La comparación de la Hipótesis 5 corre offline aunque E5 no quepa en el bundle: la Tarea 2.0 decide su despliegue, no su medición.

### Fase 1: Corpus Normativo y Banco de Preguntas

- [x] **Tarea 1.1:** Crear `data/policy_corpus.json` con las **13 cláusulas** de la política v2.3 ([spec](specs/dispute-policy-v2.3.md)), según TQ-037. Hecha el 30-Sep; falta que el equipo revise el portugués:
  - Cláusulas: `POL-SEC-SESSION`, `POL-ESC-LEGAL`, `POL-CLARIFY`, `POL-ESC-AMBIG`, `POL-DISP-TYPE`, `POL-WIN-60`, `POL-ESC-500`, `POL-ESC-ML-RISK`, `POL-ESC-MULTI`, `POL-ESC-DISTRESS`, `POL-AUT-LOCK`, `POL-AUT-INTAKE`, `POL-AUT-150`.
  - Estructura por entrada: `clause_id`, `exposure` (`public`, `public_generic` o `internal`), `title_es`, `title_pt`, `category`, `official_text_es`, `answer_es`, `answer_pt`, `keywords_es`, `keywords_pt`, `parameters`, `provenance` (`team-generated`).
  - Exposición decidida en TQ-037: `internal` para `POL-AUT-150`, `POL-SEC-SESSION` y `POL-ESC-ML-RISK`; `public_generic` (dice que un especialista revisa ciertos casos, sin listar los disparadores) para `POL-ESC-LEGAL` y `POL-ESC-DISTRESS`; `public` para el resto.
  - Las respuestas solo dan los parámetros que la política ya dice al cliente: 60 días ([`dispute_policy.py:401`](../src/rules/dispute_policy.py#L401)), 500 USD ([L200](../src/rules/dispute_policy.py#L200)), 48 horas ([L212](../src/rules/dispute_policy.py#L212)) y la respuesta formal en 3 a 5 días hábiles ([L186](../src/rules/dispute_policy.py#L186)). Nunca 150 USD, el umbral de riesgo ni el comportamiento de autenticación; nunca mencionan crédito ni prometen reembolso o bloqueo.
  - BM25 y E5 indexan el mismo texto (`official_text_es` + `keywords_es` + `keywords_pt`), para que la Hipótesis 5 no dependa de qué ve cada retriever.
- [ ] **Tarea 1.2:** Crear el banco de preguntas de política en `data/eval/` (JSONL con LF, ya cubierto por `.gitattributes`):
  - `policy_questions_test.jsonl`: las ~30 preguntas decididas para el reporte ([`TEAM_BRIEF_COMPLEMENTED.md:73`](TEAM_BRIEF_COMPLEMENTED.md#L73)), 15 ES (variantes de México, Colombia, Argentina) y 15 PT, congeladas con commit y `policy_questions_test.sha256` antes de calibrar nada.
  - `policy_questions_dev.jsonl`: otras ~30 con la misma mezcla, para calibrar umbrales.
  - Mezcla por split: ~18 directas sobre cláusulas, ~5 ambiguas y ~7 fuera de alcance, incluidas preguntas vecinas (saldo, préstamo, devolución del dinero) y preguntas que tocan cláusulas `internal`.
  - Campos: `question_id`, `language`, `text`, `expected_action` (`answer`, `clarify` o `abstain`), `expected_clause_ids` (vacío al abstenerse), `provenance`.
  - Autoría: las escriben integrantes distintos del autor del corpus, sin ver `keywords_*`. Un LLM solo parafrasea, con revisión humana ([`docs/PLAN.md:184`](PLAN.md#L184)).

### Fase 2: Retrievers y Dependencias Ligeras

- [x] **Tarea 2.0 (antes de 2.3):** Prueba de bundle y arranque en frío en el contenedor Linux (`docker compose run --rm dev`), ya que el repo aún no tiene configuración de Vercel (medida el 1-Oct, detalle en [`docs/SUPABASE_VERCEL.md`](SUPABASE_VERCEL.md) 6.3 y 6.5; falta la comparación int8 contra fp32, que espera el split dev de la 1.2):
  - Tamaño instalado de `onnxruntime` + `tokenizers` + modelo + tokenizer, sumado a las dependencias de runtime actuales, contra 500 MB. Medido: el runtime bajó de 595 MB a 358 MB al pasar al grupo `dev` lo que la API no importa; E5 suma 232 MB (97 de paquetes, 118,3 del modelo int8 y 17,1 del tokenizer) y, con los 18,7 MB del repo, el bundle llegaría a unos 609 MB. **E5 no cabe con el código de hoy**; cabe (unos 466 MB) si el modelo de riesgo se sirve en ONNX y salen `scikit-learn` y `scipy` (TQ-022).
  - Carga de la sesión ONNX en frío, p50/p95 ([`docs/PLAN.md:211`](PLAN.md#L211)). Medido con un hilo en 10 procesos nuevos: importar p50 0,65 s; sesión y tokenizer p50 1,18 s, máximo 4,24 s (con 10 corridas, el máximo hace de p95); primera consulta 10 ms; en caliente p50 8,4 ms y p95 10,2 ms.
  - El artefacto oficial está pensado para CPUs con AVX-512 VNNI; sin esa extensión, la cuantización puede perder exactitud por saturación. Comparar su ranking con el de `onnx/model.onnx` (fp32) sobre el split dev, en el contenedor y luego en Vercel (Tarea 5.2). Si diverge, cuantizar el fp32 en el build con `onnxruntime.quantization.quantize_dynamic`. La CPU de la medida (Intel i7-10510U) no tiene AVX-512 ni VNNI: el modelo corre, y su ranking queda por comparar.
  - Si no cabe o no se valida, E5 no se despliega (BM25 queda como motor) y se documenta.
  - Archivos medidos, para fijarlos en la 2.3: commit `614241f622f53c4eeff9890bdc4f31cfecc418b3` del repo del modelo; `onnx/model_qint8_avx512_vnni.onnx`, 118.346.824 bytes, SHA-256 `dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88`; `onnx/tokenizer.json`, 17.082.730 bytes, SHA-256 `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`.
- [x] **Tarea 2.1:** Dependencias en `pyproject.toml` (hecha el 30-Sep para BM25):
  - `rank-bm25` (baseline léxico, siempre).
  - `onnxruntime` y `tokenizers` (`onnxruntime` no tokeniza), en el grupo `dev` desde el 1-Oct para medir E5 offline; pasan al runtime solo si E5 se despliega (Tarea 2.0). Sin torch ni `transformers`.
- [x] **Tarea 2.2:** Implementar `src/rag/bm25_retriever.py` (hecha el 30-Sep):
  - Tokenización ES/PT con stopwords y el `_strip_accents` de [`keyword_extractor.py:97`](../src/understand/keyword_extractor.py#L97), sin stemming.
  - Índice en RAM al instanciar, sobre `Clause.index_text` (`src/rag/corpus.py`), el texto que también indexará E5.
- [x] **Tarea 2.3:** Implementar `src/rag/onnx_retriever.py` (hecha el 1-Oct para medirlo offline; servirlo espera que quepa en el bundle, TQ-022, y la decisión de la 4.2):
  - Modelo `intfloat/multilingual-e5-small`: `onnx/model_qint8_avx512_vnni.onnx` (118 MB) y `onnx/tokenizer.json`, descargados a `models/e5-small/` (carpeta git-ignorada) con `uv run python -m src.rag.onnx_retriever download`, fijados al commit y al SHA-256 medidos en la 2.0. La descarga solo guarda un archivo que coincide, y el embedder vuelve a verificar al cargar.
  - Prefijos `"passage: "` para el corpus y `"query: "` para la pregunta; average pooling con la máscara de atención y normalización L2, como el ejemplo de la model card; similitud coseno con `numpy`. Hecho, con un hilo como la función Hobby.
  - Embeddings del corpus precomputados en el build (`data/policy_embeddings.npy`), con el SHA-256 del corpus y del modelo al lado: si no coinciden al cargar, falla en vez de servir vectores viejos. Queda para cuando E5 se sirva: offline, los 13 pasajes se codifican al crear el buscador (1,3 s).
  - Carga perezosa en el primer turno `consulta_politica`: los turnos de disputa no pagan la carga del modelo. Queda para cuando E5 se sirva; hoy `onnxruntime` se importa recién al crear el embedder, y la API nunca importa el módulo (`src/rag/__init__.py` no lo exporta; `tests/test_runtime_dependencies.py`).
  - Los tests usan un embedder falso; el modelo real no se descarga en CI. Hecho: prefijos, coseno, k y empates, pooling, una pregunta en portugués contra el corpus en español y la verificación de los archivos, más un test con el modelo real que se salta si no está descargado (pasó en el contenedor el 1-Oct).

### Fase 3: Compuerta, Respuestas y Tests

- [x] **Tarea 3.1:** Implementar la compuerta `src/rag/gate.py` (hecha el 30-Sep: `ConfidenceGate` exige los dos umbrales y rechaza un inferior mayor que el superior):
  - Tres bandas con umbrales por retriever $(\tau_{upper}, \tau_{lower})$: *Alta* ($\text{Score} \ge \tau_{upper}$), *Ambivalente* ($\tau_{lower} \le \text{Score} < \tau_{upper}$) y *No Relevante* ($\text{Score} < \tau_{lower}$).
  - Sin valores semilla universales: con E5 una semilla de 0.50 nunca abstendría, y BM25 necesita su propia escala. Los valores salen solo del split dev (Tarea 4.1); evaluar también el margen entre el primer y el segundo resultado para la banda ambivalente.
- [x] **Tarea 3.2:** Implementar el explicador `src/rag/policy_explainer.py`, sin generación de texto (hecha el 30-Sep; acciones `answer`, `redirect`, `clarify` y `abstain`, y los hits del top 3 para la auditoría):
  - *Alta*, cláusula `public` o `public_generic`: `answer_es` o `answer_pt` con la cita `[POL-XXX]`.
  - *Alta*, cláusula `internal`: texto fijo de redirección, sin contenido ni parámetros de la cláusula.
  - *Ambivalente*: lista `title_es` o `title_pt` de las cláusulas públicas candidatas y pide aclaración; si todas las candidatas son internas, se abstiene.
  - *No Relevante*: `SAFE_POLICY_ABSTENTION`, texto fijo en ES y PT.
- [x] **Tarea 3.3:** Crear `tests/test_policy_rag.py` (hecha el 30-Sep para el corpus, BM25, la compuerta y el explicador: 55 casos, y cada una de 14 mutaciones realistas del código o del corpus rompe al menos uno; lo de la 5.1 llegó con ella y lo de E5 con la 2.3):
  - Recuperación por cláusula con BM25 y con el embedder falso (este, con la Tarea 2.3); preguntas en portugués contra el corpus en español.
  - Abstención en preguntas fuera de alcance.
  - Precedencia (hecha con la Tarea 5.1): legal ("Superintendencia", "abogado"), angustia y mensaje mixto (monto más pregunta) siguen el flujo de disputa y no pasan por el RAG; un turno en `awaiting_clarification` o `awaiting_lock_confirmation` tampoco.
  - Ninguna respuesta menciona crédito, 150 USD, el score de riesgo ni detalles de sesión, y los números del corpus son los que aplica el motor.
  - Al final (hecho con la Tarea 5.1): ningún intent cambia, y la señal `policy_question` no se activa en ninguno de los 345 turnos de la suite held-out ni en los 24 del split de desarrollo. Ese conteo se midió una vez y no ajustó ningún patrón: la suite está congelada.

### Fase 4: Benchmark y Validación de la Hipótesis 5

- [ ] **Tarea 4.1:** Implementar `src/eval/rag_benchmark.py` (`uv run python -m src.eval.rag_benchmark`), junto al resto del harness (herramienta lista el 1-Oct; falta correrla con el banco de la 1.2):
  - Corre BM25 y, con `--e5 models/e5-small`, E5 sobre dev y test; el archivo de compuerta sigue siendo el de BM25, el único que se puede servir hoy. Los umbrales de cada retriever se calibran solo en dev; test se mide una vez, con los umbrales fijados, y se rechaza si ya no coincide con su `.sha256`.
  - Calibración: entre los puntajes top observados en dev (más infinito), el par de umbrales que acierta más acciones; a igualdad, el más alto, que es el que menos responde y menos cita mal. Una redirección (cláusula interna) cuenta como respuesta que cita la cláusula recuperada.
  - `--write-gate data/rag_gate.json` escribe el archivo que enciende el explicador, con el SHA-256 del split dev y del corpus y el commit; commitearlo es la decisión de encenderlo.
  - Recuperación (preguntas con cláusula esperada): `Recall@1`, `Recall@3` y `MRR`, por idioma.
  - Compuerta (todas las preguntas): acción correcta (`answer`, `clarify`, `abstain`), abstención en fuera de alcance, abstención indebida y cita equivocada (responde con una cláusula fuera de `expected_clause_ids`).
  - Latencia p50/p95 en caliente; el arranque en frío viene de la Tarea 2.0.
  - Cada métrica con su denominador. Los retrievers son deterministas: las 3 repeticiones de las reglas de reporte no aplican a la recuperación, y el reporte lo dice.
- [ ] **Tarea 4.2:** Generar `reports/rag_evaluation_report.md`:
  - Regla de decisión fijada antes de medir. Propuesta: E5 se adopta si en test supera a BM25 en `Recall@3` por al menos 2 preguntas en ES y en PT, sin más citas equivocadas, y pasó la Tarea 2.0; si no, BM25 ([`revisión tecnológica:97`](reviews/2026-09-26-revision-tecnologica.md#L97)). Con 15 preguntas por idioma, una pregunta vale 6.7 puntos.
  - Cortes por idioma con advertencia de muestra pequeña; modelo, commit y SHA-256 registrados; resultado offline, etiquetado como tal.

### Fase 5: Integración con el Sistema y Cierre de Auditoría

- [x] **Tarea 5.1:** Conectar `PolicyExplainer` al orquestador conversacional (hecha el 30-Sep, apagada hasta que exista `data/rag_gate.json`):
  - Cambio frente al plan: en lugar del intent `consulta_politica` hay una señal `policy_question` en `UnderstandResult`, calculada por el extractor de palabras clave (que corre en cada turno, también con Jev). Un intent nuevo habría cambiado intents y resultados aun con el explicador apagado, y la lista de opciones de Jev que el equipo etiqueta; la señal no toca ninguno de los dos. `consulta_general` sigue siendo saldos y movimientos.
  - `DisputeOrchestrator` recibe `explainer` (por defecto `None`) y desvía un turno al explicador solo cuando pasa la guarda de la sección 4, con el mensaje enmascarado; si no, el turno sigue por `_handle_dispute_turn` como hoy.
  - `get_orchestrator` construye el explicador con `load_policy_explainer(RAG_GATE_PATH)` (por defecto `data/rag_gate.json`, con `retriever`, `tau_upper` y `tau_lower`). Sin ese archivo no hay explicador: encenderlo es commitear los umbrales de la 4.1.
  - La aclaración del explicador ya no numera los temas: en estado `new` un "1" iría al flujo de disputa; el cliente nombra el tema.
- [ ] **Tarea 5.2:** Verificar el bundle real en Vercel cuando exista el deploy (< 500 MB); la medida temprana es la Tarea 2.0.
- [ ] **Tarea 5.3:** Actualizar la auditoría en `docs/reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md`, solo en su parte RAG:
  - **AUD-03** sigue abierto por Claude Haiku 4.5 (`anthropic` no está en las dependencias); se cierra la parte del RAG.
  - **AUD-15** sigue abierto por LightGBM en ONNX (el modelo de fraude carga con `joblib`). Si gana BM25, `onnxruntime` no entra y la parte RAG se cierra corrigiendo los docs que declaran embeddings ONNX.

---

## 6. Cuadro de Control y Seguimiento

Entrega: 2026-10-05 ([`AGENTS.md`](../AGENTS.md), sección 3). La corrida RAG contra BM25 estaba agendada para el 1-oct ([`docs/PLAN.md:264`](PLAN.md#L264)).

| Tarea / Hito | Responsable | Estimación | Estado | Evidencia / Archivo |
| :--- | :---: | :---: | :---: | :--- |
| **1.1 Corpus (13 cláusulas con exposición, respuestas ES/PT)** | B | 2.0 h | Hecha (falta revisar el portugués) | `data/policy_corpus.json` |
| **1.2 Banco de preguntas (dev + test congelado)** | A / C (no B) | 2.5 h | Pendiente | `data/eval/policy_questions_{dev,test}.jsonl` |
| **2.0 Prueba de bundle y arranque en frío** | B | 1.0 h | Medida (1-Oct): E5 no cabe hoy; cabe si TQ-022 sirve el riesgo en ONNX | `docs/SUPABASE_VERCEL.md` 6.3 y 6.5 |
| **2.1 Dependencias `pyproject.toml`** | B | 0.5 h | Hecha (E5 en el grupo `dev` mientras no se despliegue) | `pyproject.toml` |
| **2.2 Retriever BM25** | B | 1.0 h | Hecha | `src/rag/bm25_retriever.py` |
| **2.3 Retriever E5 ONNX int8** | B | 2.5 h | Hecha offline (1-Oct); servirla espera TQ-022 y la 4.2 | `src/rag/onnx_retriever.py` |
| **3.1 Compuerta por retriever** | B | 1.0 h | Hecha (umbrales con la 4.1) | `src/rag/gate.py` |
| **3.2 Explicador por plantillas** | B | 1.0 h | Hecha | `src/rag/policy_explainer.py` |
| **3.3 Tests (precedencia y exposición incluidas)** | B | 2.0 h | Hecha | `tests/test_policy_rag.py` |
| **4.1 Benchmark y calibración en dev** | A / B | 1.5 h | Herramienta lista con BM25 y E5 (1-Oct); espera el banco (1.2) | `src/eval/rag_benchmark.py` |
| **4.2 Reporte y decisión H5** | A | 1.0 h | Pendiente | `reports/rag_evaluation_report.md` |
| **5.1 Señal `policy_question` y desvío seguro** | B | 2.0 h | Hecha, apagada hasta `data/rag_gate.json` (4.1) | `src/understand/`, `src/orchestrator/` |
| **5.2 Bundle real en Vercel** | B | 0.5 h | Pendiente | Logs de deploy |
| **5.3 AUD-03 / AUD-15, parte RAG** | B / PM | 0.5 h | Pendiente | `docs/reviews/` |

Total: 19 h. El camino BM25 de punta a punta (1.1, 2.1, 2.2, 3.1, 3.2, 3.3, 5.1) suma 9.5 h.

---

## 7. Registro de Cambios (30-Sep, segunda revisión)

| Cambio | Motivo | Evidencia |
| :--- | :--- | :--- |
| Exposición por cláusula; `POL-AUT-150`, `POL-SEC-SESSION` y `POL-ESC-ML-RISK` se responden con redirección | El cliente nunca oye que se aplicó crédito; la autenticación y el umbral de riesgo son internos | [spec:30](specs/dispute-policy-v2.3.md#L30), [spec:8](specs/dispute-policy-v2.3.md#L8), regla 8 de AGENTS.md, TQ-037 |
| Respuestas `answer_es` y `answer_pt` por cláusula | La política queda en español, pero la interacción va en el idioma del cliente | [PLAN:181](PLAN.md#L181) |
| Desvío solo en `new` y sin señal de disputa, legal ni de angustia | POL-ESC-LEGAL y POL-ESC-DISTRESS viven dentro de `evaluate`; el ajuste a disputa solo cubre `consulta_general` | [dispute_policy.py:297](../src/rules/dispute_policy.py#L297), [keyword_extractor.py:215](../src/understand/keyword_extractor.py#L215) |
| Banco propio con split dev y test congelado | El split de desarrollo existente son 18 casos de disputa sin cláusula esperada | `data/eval/dev_cases.jsonl` |
| Umbrales por retriever, sin semillas | E5 concentra el coseno entre 0.7 y 1.0; BM25 no tiene escala fija | Model card de E5, FAQ 3 |
| Métricas de compuerta | `Recall@k` y `MRR` no miden la abstención | Tarea 4.1 |
| Modelo git-ignorado, descargado con commit y SHA-256 | 118 MB supera el límite de 100 MB por archivo de GitHub | Carpeta `onnx/` del repo del modelo |
| `tokenizers`, average pooling y normalización L2 | `onnxruntime` no tokeniza; el pooling es el del ejemplo de la model card | Model card de E5 |
| Tarea 2.0 antes de E5 y carga perezosa | El bundle decide el despliegue de E5; cada arranque en frío carga 118 MB | [PLAN:211](PLAN.md#L211) |
| CRAG, CAG y Self-RAG descritos como inspiración | La respuesta es una plantilla; declarar técnicas no implementadas repetiría AUD-03 | Auditoría, AUD-03 |
| AUD-03 y AUD-15 se cierran solo en su parte RAG | AUD-03 incluye Claude; AUD-15 incluye LightGBM en ONNX | Auditoría, AUD-03 y AUD-15 |
| Autores distintos para corpus y preguntas; regla de decisión previa | El vocabulario compartido favorece a BM25; una pregunta vale 6.7 puntos por idioma | Tareas 1.2 y 4.2 |
| Sin detector de idioma propio | Understand ya fija el idioma de la conversación | [dispute_orchestrator.py:166](../src/orchestrator/dispute_orchestrator.py#L166) |
| Benchmark en `src/eval/` y preguntas en `data/eval/` | El harness vive en `src/eval/` y las suites en `data/eval/` | `CLAUDE.md` |

**Después, el mismo 30-Sep:** TQ-037 se respondió con la opción 1 y la Tarea 1.1 quedó en `data/policy_corpus.json`. La respuesta formal en 3 a 5 días hábiles, que el texto de registro ya da al cliente, entra en los parámetros públicos por la misma regla de TQ-037.
