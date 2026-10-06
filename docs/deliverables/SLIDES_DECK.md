# AlterEgo: Slide Deck Specification (Pitch / Submission)
**Factored AI & Data Hackathon 2026**  
**Team AlterEgo** | Production Link: [alterego-silk.vercel.app](https://alterego-silk.vercel.app)  
**Format:** 6 Slides (16:9) | **Language:** English

---

## Slide 1: The Problem — Broken Intake in Banking Customer Service

### Header & Subhead
- **Title:** The High Cost of Ambiguity: Transaction Disputes in LATAM Banking
- **Subtitle:** Why we focused deeply on one critical workflow rather than building another superficial chatbot.

### Core Content & Data Justification
- **The Operational Bottleneck (LATAM Bank Dataset Analysis):**
  - **Quejas (Complaints)** represent the costliest call-center interaction:
    - Lowest First-Contact Resolution (**FCR: 43.6%** vs 91.5% for transactional).
    - Highest repeat rate (**63% require manual follow-up**).
    - Longest handle time (**7.2 minutes average**).
  - **The Core Driver:** "Cargo no reconocido" (18.3%) + "Cobro indebido" (18.2%) account for **36.5% of all complaints**.
- **The Real Customer Pain:**
  - Customers face rigid IVRs or hallucinatory chatbots that promise refunds they cannot authorize, fail to verify identity, or leave cards vulnerable to cascading fraud.
- **AlterEgo Mission:**
  - Build an end-to-end, deterministic intake engine for transaction disputes in **Spanish and Portuguese** that understands intent, applies enforceable bank policy, safeguards cardholders, and verifies every single action against the system of record.

### Key Visuals / Callouts
- Stat Callout: `36.5% of Complaints = Disputed Charges`
- Stat Callout: `63% Follow-Up Rate in Baseline Call Center`
- Tagline: *"Not a chatbot. A verified resolution and escalation engine."*

---

## Slide 2: Core Philosophy & 5-Stage Architecture

### Header & Subhead
- **Title:** The Architecture: The Model Proposes, Deterministic Policy Disposes
- **Subtitle:** A 5-stage lifecycle ensuring policy compliance, verified containment, and full auditability.

### 5-Stage Execution Flow (The Golden Path)
1. **Understand (System 1):**
   - Natural language intake in Spanish & Portuguese.
   - PII masking (CURP, DNI, CC, CPF) and prompt injection filtering before language processing.
   - Extracts structured intent, transaction references, amount hints, and temporal context into a strict Pydantic contract.
2. **Decide (System 2):**
   - Policy-as-Code engine executing 13 synthetic dispute policy clauses (v2.3 specification).
   - Strict monetary and temporal boundaries: $150 automated threshold (`POL-AUT-150`), $500 containment ceiling (`POL-ESC-500`), 60-day dispute window (`POL-WIN-60`).
3. **Act (Tool Gateway):**
   - Least-privilege database gateway executing state-machine-gated operations on Postgres (`ops` schema).
   - Zero direct model access to write APIs. Pre-write ownership check and case existence checks prevent redundant cases.
4. **Verify (Read-Back Loop):**
   - The system never acknowledges an action to the customer until it reads back the committed record from the database.
5. **Escalate (HITL Handover):**
   - Structured JSON handoff packet with verified facts, triggered policy clauses, and risk assessment for human agents.

### Key Visual / Reference
- Diagram: *Refer to the interactive architecture diagram:* `alterego-system.html` (Generated via Archify).
- Architecture Highlights:
  - Frontend: React + TypeScript on Vercel.
  - Edge & Auth: Supabase Auth (ES256 JWKS verification).
  - Backend API: FastAPI on Vercel Serverless.
  - Storage & State: Supabase Postgres (`bank` read-only gold replica + `ops` least-privilege operational store).

---

## Slide 3: Trust, Security & Compliance by Design

### Header & Subhead
- **Title:** Enterprise Security: Defense in Depth
- **Subtitle:** How AlterEgo enforces banking-grade boundaries across authentication, authorization, and data privacy.

### Key Pillars
1. **Cryptographic Identity, Not Assertions:**
   - Identity is derived strictly from verified Supabase ES256 session tokens (`app_metadata.customer_id`).
   - Customer IDs provided in request bodies or model prompts are ignored. Agents require `app_metadata.app_role = 'agent'`.
2. **Deterministic Guardrails & Policy Isolation:**
   - Models only propose signals: Jev classifies the message and the transferred model scores risk. They never execute actions, grant credits or alter bank rules, and every reply is a policy template.
   - Money movement is strictly disabled by design (provisional credit recommendations exist only as an advisory flag in the human handoff packet for eligible low-value claims).
3. **Proactive Fraud & Risk Protection:**
   - Multi-charge anomalies or reports of lost/stolen cards trigger immediate, proactive offers for **preventive card locking** (`POL-AUT-LOCK`).
   - Locks require explicit customer confirmation before executing through the gateway.
4. **Immutable Auditability:**
   - Append-only audit log (`ops.audit_log`) captures every turn, intent, policy clause evaluation, and gateway call.
   - Zero reliance on hidden model chain-of-thought for audit compliance.

---

## Slide 4: Quantitative Results: Frozen 250-Case Held-Out Suite

### Header & Subhead
- **Title:** Rigorous Evaluation: Baseline vs. Proposed Stack
- **Subtitle:** Tested on a frozen held-out benchmark of 250 complex cases (including 25 adversarial cases) across ES & PT.

### Benchmark Results Table
| Official Metric | Starter Baseline | AlterEgo (Proposed) | Improvement |
| :--- | :---: | :---: | :---: |
| **Safe Automated Resolution (Eligible Cases)** | **3.7%** (4 / 107) | **98.1%** (105 / 107) | **+94.4%** |
| **Safe Automated Resolution (All In-Scope)** | 1.7% (4 / 230) | **45.7%** (105 / 230) | **+44.0%** (Attempted: 52.4%) |
| **Containment Rate** | 44.0% (110 / 250) | **68.8%** (172 / 250) | **+24.8%** |
| **Escalation Precision** | 48.6% (68 / 140) | **100.0%** (78 / 78) | **0 unnecessary transfers** |
| **Escalation Recall** | 69.4% (68 / 98) | **79.6%** (78 / 98) | **+10.2%** |
| **Unsafe Outcomes** | 48.8% (122 / 250) | **8.0%** (20 / 250)* | **-40.8% reduction** |
| **Language Accuracy** | 59.7% (142 / 238) | **99.2%** (236 / 238) | **Near-perfect parity** |
| **In-Process Latency (p50 / p95)** | 0.1 ms / 0.2 ms | **161.6 ms / 662.1 ms**\*\* | Rules-only run |

*\*Note on Unsafe Outcomes: the 20 remaining cases of the rules-only run are high-risk foreign online purchases that it opens as cases. With the transferred risk model, which production serves since October 5, unsafe outcomes fall to 9/250 (3.6%) and safe automated resolution to 101/107 (94.4%). The deployed combination (risk model, Jev and policy explainer together) was not measured as a whole.*  
*\*\*Rules-only run, in process with no network, in the dev container on a Windows laptop; latency depends on the machine.*

### Cross-Cutting Slices
- **Language Parity:** Spanish (96.7% safe resolution) | Portuguese (100.0% safe resolution).
- **Segment Parity:** Basic (100%), Plus (100%), Premium (96.8%), Student (96.0%).
- **Country Parity:** Argentina (97.2%), Colombia (97.2%), Mexico (100.0%).

---

## Slide 5: Data Rigor, Leakage Analysis & Honest Limitations

### Header & Subhead
- **Title:** Engineering Rigor: What the Data Taught Us & Honest Limitations
- **Subtitle:** Adhering strictly to Hackathon Rules 4 & 11 through transparent discovery and documentation.

### Data Profiling Discoveries
- **`transactions.fraud_score` Leakage:**
  - Profiling revealed that `fraud_score` leaked the ground truth: 100% of non-fraud rows scored $\le 30.0$.
  - *Engineering Decision:* We explicitly barred `fraud_score` from all feature pipelines and baseline models to eliminate data leakage.
- **Behavioral Signal Absence in Dataset:**
  - Rigorous cross-table modeling confirmed `transactions.is_fraud` was distributed uniformly across channels, amounts, and merchant categories (ROC-AUC ~0.50).
  - *Engineering Decision:* We transferred a risk model from IEEE-CIS on 19 homologated features (holdout ROC AUC 0.816). It serves in production behind `POL-ESC-ML-RISK`, with its threshold at the 98th percentile of the bank's Web and App charges. No bank label validates it, so it routes charges to a human; it is not a fraud detector validated on LATAM Bank.

### Documented System Limitations (Transparency First)
1. **Language Scope:** The LATAM Bank dataset natively contains only Spanish; all Portuguese evaluation cases and utterances were team-generated and explicitly labeled.
2. **Containment Ceiling:** By policy, charges $> \$500$ mandatorily escalate to humans, capping theoretical automated containment at $\sim 60.4\%$ of disputable charges.
3. **No Money Movement:** AlterEgo handles intake, dispute filing, and card protection. Provisional credit is an advisory recommendation inside the human handoff packet.
4. **Free Tier Operational Limits:** Supabase and Vercel serverless free tiers introduce cold starts; Supabase Free pauses after 7 days without queries.
5. **Unmeasured Combination:** production runs the risk model, Jev and the policy explainer together. Each was measured on its own; the combination was not.

---

## Slide 6: Live Production Demo & Team AlterEgo

### Header & Subhead
- **Title:** Live Deployment & Team
- **Subtitle:** Experience AlterEgo live in production with verified test personas.

### Live Environment Details
- **Production URL:** [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app)
- **API Health Endpoint:** [https://alterego-silk.vercel.app/health](https://alterego-silk.vercel.app/health)
- **Interactive Architecture Artifacts:** Visualized workflows and component state machines.

### Verified Demo Personas
1. `cliente-hasta-150`: single-turn dispute opened without a human (`POL-AUT-150` or `POL-AUT-INTAKE`).
2. `cliente-mas-de-500`: Mandatory policy escalation over $500 (`POL-ESC-500`) with instant HITL handoff.
3. `cliente-tarjeta-perdida`: Immediate proactive offer for preventive card lock (`POL-AUT-LOCK`).
4. `agente`: Dedicated English HITL Console for reviewing structured packets and auditing decisions.

### The AlterEgo Team
- **Daniel Camilo Pardo** (`Chackmilo`) — Full-Stack Architecture, Identity, Ops Gateway & Deployment
- **Kmilo Aparicio** (`Trajano81`) — Machine Learning, Feature Homologation, Data Engineering & Evaluation Harness
