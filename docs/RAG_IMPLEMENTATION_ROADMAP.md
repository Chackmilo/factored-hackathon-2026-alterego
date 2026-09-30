# Plan de Implementación y Roadmap: Motor RAG de Explicaciones de Política

**Estado:** Aprobado para implementación  
**Fecha de Creación:** 2026-09-30  
**Basado en:** Hallazgos del Notebook *Augmented Generation* (`11d894be-6dd0-4680-ad7e-d9a2e8457d76`), reglas de [`AGENTS.md`](../AGENTS.md), especificación [`docs/specs/dispute-policy-v2.3.md`](specs/dispute-policy-v2.3.md) y resolución de hallazgos **AUD-03 / AUD-15** de [`docs/reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md`](reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md).

---

## 1. Contexto y Objetivos del Proyecto

En el sistema bancario de atención a reclamos de fraude y disputas (Hackathon Factored 2026), el componente de RAG tiene un mandato estricto y delimitado:
1. **El modelo propone, la política determinista dispone:** El motor de políticas como código (`src/rules/dispute_policy.py`) es la única autoridad que decide si un caso es elegible, si se escala a un agente humano (HITL) o si se recomienda bloqueo preventivo.
2. **Rol exclusivo del RAG:** Responder preguntas informativas de los clientes sobre las políticas del banco en **Español y Portugués**, citar con precisión el identificador oficial de la cláusula (`[POL-XXX]`), y **abstenerse con seguridad** cuando la pregunta escape al alcance normativo o carezca de fundamento.
3. **Restricción de infraestructura:** Despliegue en Vercel con un límite estricto de bundle de **500 MB**. Se prohíbe el uso de PyTorch pesado (~800 MB); se debe usar **ONNX Runtime** local cuantizado a int8 o caer transparentemente al baseline de **BM25**.

---

## 2. Hallazgos Clave del Notebook *Augmented Generation* y su Aplicación

El análisis de las 29 fuentes del notebook revela lecciones críticas que evitan errores comunes de diseño y guían directamente nuestra implementación:

| Arquitectura / Concepto | Hallazgo en el Notebook | Implicación Directa en Nuestro Proyecto |
| :--- | :--- | :--- |
| **Naive RAG (Riesgo de "Fe Ciega")** | El LLM asume ciegamente que los fragmentos recuperados son válidos. Si el retriever falla o trae fragmentos irrelevantes, el modelo alucina respuestas inventadas con alta convicción. | **Crítico:** No podemos inyectar texto sin filtrar. Necesitamos una compuerta de confianza con umbral mínimo de similitud ($\tau$). Si no se supera, el sistema se abstiene (`SAFE_POLICY_ABSTENTION`). |
| **CRAG (Corrective RAG Cerrado)** | En dominios normativos/bancarios cerrados, **el fallback web de CRAG está prohibido** para evitar contaminación regulatoria. Se adapta a un evaluador tripartito: *Alta Confianza* ($\ge 0.78$), *Ambivalente* ($0.60 - 0.77$) y *Baja Confianza / No Relevante* ($< 0.60$). | **Patrón a adoptar:** Evaluador pre-generación que valida la similitud del retrieval. Si es *Alta*, genera con cita; si es *Ambivalente*, pide aclaración sobre la norma; si es *Baja*, emite **abstención regulatoria segura** explícita (*"No se encontró evidencia suficiente en la política vigente..."*). |
| **CAG (Cache-Augmented Generation)** | Precarga el corpus estático en contexto / memoria para latencia sub-segundo (< 1 s) y cero omisión en bases de conocimiento pequeñas y estables. | **Aplicación In-Memory:** Nuestro corpus es pequeño (~15 cláusulas, < 5.000 tokens). Aplicamos el principio de CAG precargando el corpus JSON y los vectores precomputados en memoria RAM al arrancar FastAPI. Cero I/O de disco en runtime y latencia ultra-baja. |
| **GraphRAG / ArchRAG** | Destacan en razonamiento multisalto sobre cientos de entidades interconectadas, pero su costo de indexación es $\mathcal{O}(N^2)$ (3-5x más tokens) y latencia alta (5-15 s). | **Descarte justificado:** Para un corpus normativo acotado de 15 cláusulas disjuntas, GraphRAG añade complejidad y latencia injustificadas. El retriever denso vectorial (ONNX) + léxico (BM25) es la solución óptima comprobada por el notebook para QA fáctico local. |
| **Self-RAG (Verificación Fáctica `IsSup`)** | Valida que cada afirmación generada esté 100% respaldada (`Fully Supported`) por el contexto extraído antes de entregar la respuesta final. | **Garantía regulatoria:** La respuesta del agente debe construirse exclusivamente a partir de los campos estructurados de la cláusula (`official_text`, `parameters`), prohibiendo terminantemente prometer reembolsos, inventar plazos o simular créditos provisionales al cliente. |

---

## 3. Diagnóstico de Brechas Actuales (Gap Analysis)

| Área | Requisito del Proyecto / Auditoría | Estado Actual en el Repositorio | Brecha Identificada |
| :--- | :--- | :--- | :--- |
| **1. Corpus de Políticas** | Corpus estructurado de 15 cláusulas (política v2.3) con texto explicativo en ES y PT y metadatos de parámetros. | Existe la lógica en `dispute_policy.py` y la spec en `dispute-policy-v2.3.md`, pero no un archivo canónico estructurado. | Falta archivo canónico `data/policy_corpus.json` con los fragmentos listos para indexación y búsqueda. |
| **2. Dependencias de Serving** | Servir embeddings locales en ONNX (`onnxruntime`) y baseline `rank-bm25`. | Ni `onnxruntime` ni `rank-bm25` están en `pyproject.toml` (observado en **AUD-15**). | Falta incorporar dependencias ligeras y compatibles con Vercel (< 500 MB). |
| **3. Modelo de Embeddings** | Modelo multilingüe cuantizado a int8 (`multilingual-e5-small` o `paraphrase-multilingual-MiniLM-L12-v2`). | No hay archivos `.onnx` ni pipeline de vectorización en local. | Falta script de descarga/exportación del modelo ONNX y precomputación de embeddings en build time (`data/policy_embeddings.npy`). |
| **4. Baseline Comparativo** | Baseline BM25 obligatorio para contrastar `Recall@3` contra los embeddings neuronales. | No existe implementación ni archivo de benchmarking de BM25. | Falta módulo `src/rag/bm25_retriever.py` con tokenización multilingüe ES/PT. |
| **5. Evaluación y Métrica** | Banco de 30 preguntas etiquetadas en ES y PT con su `ground_truth_clause_id` para medir Recall@1, Recall@3 y MRR. | No existe el conjunto de preguntas de evaluación de políticas. | Falta `data/eval_policy_questions.json` y el script de benchmarking `scripts/eval_rag_benchmark.py`. |
| **6. Enrutamiento del Orquestador** | Enrutar consultas informativas directas de política (`consulta_general`) al RAG en lugar de forzar un matching de cargo inexistente. | El orquestador envía todo a `DisputePolicyEngine.evaluate`, disparando `POL-CLARIFY` (`NO_CANDIDATE_CHARGE`) si no hay un cargo en la consulta. | Modificar `_handle_dispute_turn` en `src/orchestrator/dispute_orchestrator.py` para consultar `PolicyExplainer` ante intenciones informativas. |

---

## 4. Arquitectura Propuesta: *Lightweight CRAG-CAG Policy Engine*

```
                           [Consulta del Cliente (ES / PT)]
                                          │
                                          ▼
                             ┌─────────────────────────┐
                             │    Detector de Idioma   │
                             └────────────┬────────────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
         ┌───────────────────────┐                 ┌───────────────────────┐
         │  Retriever Denso ONNX │                 │    Retriever Léxico   │
         │ (multilingual-e5 int8)│                 │        (BM25)         │
         │   [Principio CAG:     │                 │   [Principio CAG:     │
         │   Precarga en RAM]    │                 │   Precarga en RAM]    │
         └───────────┬───────────┘                 └───────────┬───────────┘
                     │                                         │
                     └────────────────────┬────────────────────┘
                                          ▼
                             ┌─────────────────────────┐
                             │   CRAG Confidence Gate  │  ◄── [Evaluador Tripartito]
                             │   (Evaluación de Score) │
                             └────────────┬────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         │ (Score >= 0.78)                │ (0.60 <= Score < 0.78)         │ (Score < 0.60)
         ▼                                ▼                                ▼
┌──────────────────┐            ┌──────────────────┐            ┌──────────────────┐
│  Alta Confianza  │            │  Rango Incierto  │            │  Baja Confianza  │
│  (Correcto)      │            │  (Ambivalente)   │            │  (No Relevante)  │
└────────┬─────────┘            └────────┬─────────┘            └────────┬─────────┘
         │                               │                               │
         ▼                               ▼                               ▼
┌──────────────────┐            ┌──────────────────┐            ┌──────────────────┐
│ Generación Cita  │            │ Aclaración con   │            │ Abstención       │
│ Estricta (Self-  │            │ Opciones de      │            │ Segura Normativa │
│ RAG [IsSup]):    │            │ Cláusulas        │            │ (SAFE_POLICY_    │
│ "[POL-XXX]..."   │            │ Candidatas       │            │ ABSTENTION)      │
└──────────────────┘            └──────────────────┘            └──────────────────┘
```

---

## 5. Roadmap de Implementación (Paso a Paso)

```
[Fase 1: Datos y Corpus] ──► [Fase 2: Motores de Búsqueda] ──► [Fase 3: Capa CRAG/CAG] ──► [Fase 4: Benchmark] ──► [Fase 5: Integración y Cierre]
```

### Fase 1: Formalización del Corpus Normativo y Banco de Evaluación
- [ ] **Tarea 1.1:** Crear `data/policy_corpus.json` con las 15 cláusulas oficiales de la política v2.3:
  - Cada entrada con: `clause_id` (ej. `POL-WIN-60`), `title_es`, `title_pt`, `category`, `official_text_es`, `official_text_pt`, `keywords_es`, `keywords_pt`, `parameters` (ej. `window_days: 60`, `max_amount_usd: 500`).
- [ ] **Tarea 1.2:** Crear `data/eval_policy_questions.json` con 30 casos de prueba etiquetados:
  - 15 consultas en español (mexicano, colombiano, argentino).
  - 15 consultas en portugués brasileño.
  - Mix calibrado: 20 consultas directas sobre cláusulas, 5 ambiguas y 5 fuera del alcance normativo (que deben disparar abstención segura).

### Fase 2: Implementación de Motores de Búsqueda y Dependencias Ligeras
- [ ] **Tarea 2.1:** Agregar dependencias a `pyproject.toml`:
  - `onnxruntime` (o `onnxruntime` slim para CPU compatible con Vercel).
  - `rank-bm25`.
- [ ] **Tarea 2.2:** Implementar `src/rag/bm25_retriever.py`:
  - Tokenización multilingüe (stopwords ES/PT y normalización de acentos `_strip_accents`).
  - Indexación en memoria RAM al instanciar (principio CAG).
- [ ] **Tarea 2.3:** Implementar `src/rag/onnx_retriever.py`:
  - Utilizar modelo ligero multilingüe en formato ONNX int8 (`multilingual-e5-small` o `paraphrase-multilingual-MiniLM-L12-v2`, tamaño ~50-110 MB).
  - Generar embeddings estáticos precomputados del corpus en build time (`data/policy_embeddings.npy`).
  - Cálculo de similitud coseno vectorial en memoria con `numpy` puro.

### Fase 3: Capa Metacognitiva CRAG, Verificación Fáctica (Self-RAG) y Tests
- [ ] **Tarea 3.1:** Implementar el evaluador de relevancia y compuerta de confianza `src/rag/evaluator.py`:
  - Clasificación tripartita CRAG: *Alta Confianza* ($\ge 0.78$), *Incierta/Ambivalente* ($0.60 - 0.77$), *No Relevante* ($< 0.60$).
- [ ] **Tarea 3.2:** Implementar el motor explicativo `src/rag/policy_explainer.py`:
  - Si *No Relevante*: genera abstención segura citando que la inquietud no corresponde a la política de disputas (`SAFE_POLICY_ABSTENTION`).
  - Si *Ambivalente*: sugiere las cláusulas más próximas y solicita aclaración.
  - Si *Alta Confianza*: genera respuesta explicativa fundamentada en los parámetros de la cláusula (Self-RAG `IsSup`), citando obligatoriamente `[POL-XXX]` sin inventar hechos.
- [ ] **Tarea 3.3:** Crear pruebas unitarias `tests/test_policy_rag.py`:
  - Cobertura de recuperación exacta de cláusulas por ID y similitud.
  - Cobertura de consultas en portugués contra corpus bilingüe.
  - Validación de abstención segura en preguntas fuera de alcance normativo.

### Fase 4: Benchmark y Validación de Hipótesis (Baseline vs Propuesto)
- [ ] **Tarea 4.1:** Implementar script de evaluación automatizada `scripts/eval_rag_benchmark.py`:
  - Ejecutar las 30 preguntas de prueba sobre BM25 y sobre el modelo ONNX.
  - Medir y comparar: `Recall@1`, `Recall@3`, `Mean Reciprocal Rank (MRR)` y `Latencia p50/p95 (ms)`.
- [ ] **Tarea 4.2:** Generar reporte técnico en `reports/rag_evaluation_report.md`:
  - Tabla comparativa oficial que demuestre la superioridad del modelo propuesto en consultas multilingües complejas y la viabilidad del fallback en BM25.

### Fase 5: Integración con el Sistema y Cierre de Auditoría
- [ ] **Tarea 5.1:** Conectar `PolicyExplainer` al orquestador conversacional (`src/orchestrator/dispute_orchestrator.py`):
  - Enrutar intenciones informativas (`consulta_general` o preguntas directas sobre normas) al explicador RAG antes de forzar el matching de cargos.
- [ ] **Tarea 5.2:** Verificar el tamaño total del bundle de despliegue para Vercel (< 500 MB).
- [ ] **Tarea 5.3:** Actualizar la matriz de auditoría en `docs/reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md`:
  - Cerrar formalmente los riesgos **AUD-03** (RAG operativo) y **AUD-15** (ONNX implementado en dependencias y código).

---

## 6. Cuadro de Control y Seguimiento

| Tarea / Hito | Responsable | Estimación | Estado | Evidencia / Archivo |
| :--- | :---: | :---: | :---: | :--- |
| **1.1 Corpus Normativo** | B | 1.5 h | Pendiente | `data/policy_corpus.json` |
| **1.2 Dataset de Evaluación (30 casos)** | A / B | 1.5 h | Pendiente | `data/eval_policy_questions.json` |
| **2.1 Dependencias `pyproject.toml`** | B | 0.5 h | Pendiente | `pyproject.toml` |
| **2.2 Retriever BM25** | B | 1.0 h | Pendiente | `src/rag/bm25_retriever.py` |
| **2.3 Retriever ONNX Multilingüe** | B | 2.5 h | Pendiente | `src/rag/onnx_retriever.py` |
| **3.1 Evaluador y Compuerta CRAG** | B | 1.5 h | Pendiente | `src/rag/evaluator.py` |
| **3.2 Generador de Explicaciones (Self-RAG)** | B | 1.0 h | Pendiente | `src/rag/policy_explainer.py` |
| **3.3 Tests Unitarios** | B | 1.5 h | Pendiente | `tests/test_policy_rag.py` |
| **4.1 Benchmark de Evaluación** | A / B | 1.5 h | Pendiente | `scripts/eval_rag_benchmark.py` |
| **4.2 Reporte de Resultados** | A | 1.0 h | Pendiente | `reports/rag_evaluation_report.md` |
| **5.1 Integración Orquestador** | B | 1.5 h | Pendiente | `src/orchestrator/dispute_orchestrator.py` |
| **5.2 Cierre Auditoría AUD-03/15** | B / PM | 0.5 h | Pendiente | `docs/reviews/` |
