# 🛡️ OmniGuard AI — Hybrid Customer Interaction & Fraud Resolution Engine
### *Factored AI & Data Hackathon 2026 Submission Foundation*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/uv-Fast%20Packaging-DE5FE9)](https://github.com/astral-sh/uv)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production%20Ready-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/pytest-13%20passed-green)](file:///d:/Hackaton/tests)
[![Docker](https://img.shields.io/badge/Docker-Multi--stage-2496ED?logo=docker&logoColor=white)](file:///d:/Hackaton/Dockerfile)

---

## 📖 Visión General del Proyecto

En el ámbito bancario y fintech de escala Fortune 500, confiar únicamente en modelos generativos (LLMs) para procesar interacciones de clientes y eventos de fraude es inviable: introduce **latencia innecesaria (2-5 segundos)**, **costos crecientes de tokens**, **riesgo de inyección de prompts** y **falta de determinismo en acciones críticas**.

**OmniGuard AI** implementa una arquitectura híbrida de 4 fases que balancea de manera explícita **Autonomía, Precisión, Latencia, Costo y Supervisión Humana (HITL)**:

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                 OmniGuard AI Architecture                                 │
└───────────────────────────────────────────────────────────────────────────────────────────┘

 1. INGESTIÓN & PRIVACIDAD (PII Redaction)
    [ Mensaje de Cliente / Transacción ] ──► [ Redactor Determinista PII (Regex/NER) ]
                                                            │
 2. MOTOR DE REGLAS DETERMINISTAS (< 2ms)                  ▼
    ¿Comando crítico (e.g. "Bloquear tarjeta") o Ataque? ──► [SI] ──► Bloqueo Inmediato (<2ms, $0)
                                                            │ [NO]
 3. SCORING DE FRAUDE TABULAR ML (< 10ms)                  ▼
    Evaluación de anomalías, velocidad y país             ──► [Prob > 85%] ──► Pausa de Seguridad & HITL
                                                            │ [Riesgo Controlado]
 4. AGENTE DE RESOLUCIÓN & HUMAN-IN-THE-LOOP (HITL)        ▼
    ¿Monto dentro de límite autónomo (< $500)?            ──► [SI] ──► Herramienta Bancaria Autónoma
                                                          └──► [NO] ──► Cola HITL de Especialista Humano
```

---

## 🎯 Alineación con la Rúbrica de Factored (7 Pilares)

| Pilar de Factored | Implementación en OmniGuard AI | Ubicación en el Código |
|---|---|---|
| **1. Architecture** | Clean Architecture desacoplada: Domain, Core, Privacy, Rules, ML, Agents, HITL, API. | [`src/`](file:///d:/Hackaton/src/) |
| **2. Reliability** | Circuit-breakers lógicos, fallbacks estructurados, validación estricta en tiempo de entrada. | [`src/domain/schemas.py`](file:///d:/Hackaton/src/domain/schemas.py) |
| **3. Reproducibility** | Entorno ultra-rápido y determinista con `uv.lock`, `Dockerfile` multi-stage y suite `pytest`. | [`pyproject.toml`](file:///d:/Hackaton/pyproject.toml), [`Dockerfile`](file:///d:/Hackaton/Dockerfile) |
| **4. Data Quality** | Contratos de datos Pydantic v2 con validación de tipo y limpieza automática. | [`src/domain/schemas.py`](file:///d:/Hackaton/src/domain/schemas.py) |
| **5. Business Reasoning** | Matriz de impacto financiero: protege capital en fraude grave sin crear fricción innecesaria. | [`src/agents/orchestrator.py`](file:///d:/Hackaton/src/agents/orchestrator.py) |
| **6. Privacy & Fairness** | Anonimización estricta de tarjetas, teléfonos, emails y SSN previo a cualquier inferencia. | [`src/privacy/pii_masker.py`](file:///d:/Hackaton/src/privacy/pii_masker.py) |
| **7. Production Thinking** | Justificación explícita de trade-offs (Deterministic vs ML vs Agentic vs HITL). | [`src/rules/engine.py`](file:///d:/Hackaton/src/rules/engine.py), [`src/core/telemetry.py`](file:///d:/Hackaton/src/core/telemetry.py) |

---

## ⚡ Guía de Inicio Rápido

### Prerrequisitos
- Python 3.11+
- `uv` instalado (`pip install uv` o `curl -LsSf https://astral.sh/uv/install.sh`)

### 1. Clonar e Instalar Dependencias
```bash
git clone <repo-url>
cd Hackaton
uv sync
```

### 2. Ejecutar la Suite de Pruebas
```bash
uv run pytest -v
```

### 3. Iniciar el Servidor de API (FastAPI)
```bash
uv run uvicorn src.api.app:app --reload --port 8000
```
La documentación Swagger interactiva estará disponible en: `http://localhost:8000/docs`

### 4. Ejecución en Contenedores (Docker)
```bash
docker-compose up --build -d
```

---

## 📡 Ejemplos de Uso de la API

### Escenario 1: Bloqueo de Emergencia (Fast-Path Determinista)
```bash
curl -X POST http://localhost:8000/api/v1/triage \
  -H "Content-Type: application/json" \
  -d '{
    "interaction_id": "REQ-101",
    "customer_id": "USR-552",
    "channel": "chat",
    "message_text": "Please lock my card immediately, someone stole my purse!"
  }'
```
*Respuesta:* `routing: "DETERMINISTIC_FASTPATH"`, latencia total `< 5ms`, costo `$0.00`.

### Escenario 2: Alerta de Fraude Anómalo (Escalamiento a HITL)
```bash
curl -X POST http://localhost:8000/api/v1/triage \
  -H "Content-Type: application/json" \
  -d '{
    "interaction_id": "REQ-102",
    "customer_id": "USR-881",
    "channel": "chat",
    "message_text": "What is this charge on my statement?",
    "transaction": {
      "transaction_id": "TX-998",
      "amount": 3400.0,
      "currency": "USD",
      "merchant_name": "Luxury Electronics",
      "merchant_category": "electronics",
      "location_country": "RU",
      "historical_avg_amount": 40.0
    }
  }'
```
*Respuesta:* `routing: "HITL_ESCALATION"`, ticket generado en la cola de revisión humana con los factores de riesgo identificados.
