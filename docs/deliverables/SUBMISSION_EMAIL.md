# Submission Email Draft
**Factored AI & Data Hackathon 2026 — Team AlterEgo**

**To:** `hackathon.admin@factored.ai`  
**Subject:** Submission: Factored AI & Data Hackathon 2026 — Team AlterEgo  
**Date:** October 4, 2026  

---

Dear Factored Hackathon Organizing Committee and Jury,

We are proud to present **AlterEgo**, our AI-first transaction dispute intake and customer protection system for retail banking in Latin America, developed for the **Factored AI & Data Hackathon 2026**.

AlterEgo addresses the most costly and friction-heavy workflow in the LATAM Bank dataset—transaction disputes and improper charges (accounting for 36.5% of all complaints, with a 43.6% First-Contact Resolution rate). Rather than deploying a generic conversational chatbot, AlterEgo is built as a deterministic, policy-governed intake engine centered around one core engineering principle: **The model proposes, deterministic policy disposes**.

---

### 1. Key Submission Links
- **Public GitHub Repository:** [https://github.com/Chackmilo/Factored_Hackaton](https://github.com/Chackmilo/Factored_Hackaton)  
  *(Clean architecture, full commit history, comprehensive docs, and reproducible evaluation harnesses)*
- **Live Production Deployment:** [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app)  
  *(API Health check: `https://alterego-silk.vercel.app/health`)*
- **Interactive Architecture & Workflow Artifacts:** Included in repository at `.archify/`
- **Video Demonstration (3 minutes):** `[INSERT_YOUTUBE_OR_LOOM_LINK_HERE]`
- **Presentation Deck (PDF / Slides):** `[INSERT_GOOGLE_SLIDES_OR_DRIVE_LINK_HERE]`

---

### 2. Team Members
- **Daniel Camilo Pardo** (`Chackmilo`) — Full-Stack Architecture, Identity, Ops Gateway & Deployment (`chackmilo@gmail.com`)
- **Kmilo Aparicio** (`Trajano81`) — Machine Learning, Feature Homologation, Data Engineering & Evaluation Harness (`kmilo.aparicio55@gmail.com`)

---

### 3. Jury Evaluation Credentials (Live Test Personas)
You can test the live system directly at [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app) using our pre-seeded test personas:

| Persona / Role | Email Address | Password | Intended Test Scenario |
| :--- | :--- | :--- | :--- |
| **Client ($\le \$150$)** | `[YOUR_EMAIL]+cliente-hasta-150@gmail.com` | `[COPIA_DE_personas.local.json]` | Standard dispute resolved automatically without a human (`POL-AUT-150`).<br>*Test prompt:* `"No reconozco un cargo de 113.65 USD del 3 de junio"` |
| **Client ($> \$500$)** | `[YOUR_EMAIL]+cliente-mas-de-500@gmail.com` | `[COPIA_DE_personas.local.json]` | Policy-mandated human escalation (`POL-ESC-500`).<br>*Test prompt:* `"No reconozco un cargo de 4259.97 USD del 12 de junio"` |
| **Client (Lost Card)** | `[YOUR_EMAIL]+cliente-tarjeta-perdida@gmail.com` | `[COPIA_DE_personas.local.json]` | Proactive card lock offer (`POL-AUT-LOCK`). Files dispute and offers card lock upon confirmation.<br>*Test prompt:* `"Perdí la tarjeta y no reconozco un cargo de 168.88 USD del 9 de junio"` |
| **HITL Bank Agent** | `[YOUR_EMAIL]+agente@gmail.com` | `[COPIA_DE_personas.local.json]` | **English HITL Console**: Accesses the escalation queue, structured handoff packets with verified facts, and advisory provisional credit notes. |

*(Note: The system supports Spanish and Portuguese seamlessly. You may interact in Portuguese with any persona, e.g., "Olá, não reconheço uma cobrança suspeita feita ontem").*

---

### 4. Summary of Empirical Results (Frozen 250-Case Held-Out Suite)
Evaluated across 250 frozen held-out cases (including 25 adversarial cases) with 3 full repeats comparing our proposed architecture against the starter baseline:
- **Safe Automated Resolution (Eligible cases):** Improved from **3.7% (4/107) to 98.1% (105/107)** (+94.4%).
- **Safe Automated Resolution (All in-scope cases):** Improved from **1.7% (4/230) to 45.7% (105/230)** (Automation attempted: 52.4%, 123/230).
- **Containment Rate:** Improved from **44.0% to 68.8%** (172/250).
- **Unnecessary Human Transfers:** Reduced from **72 to 0** (100% precision on escalations).
- **Unsafe Outcomes:** Reduced from **48.8% to 8.0%** (The 20 remaining cases correspond to high-risk foreign charges evaluated in rules-only mode where the ML model was not serving).
- **Cross-Lingual Parity:** 96.7% safe resolution in Spanish (59/61) vs. 100.0% in Portuguese (46/46), with 99.2% reply language accuracy.
- **In-Process Latency:** p50 of **161.6 ms** (p95: 662.1 ms) in containerized test environment; **25.0 ms / 85.1 ms** on native hardware.

---

### 5. Compliance with Hackathon Rules
- **Rule 1 (One workflow, deep):** Complete focus on transaction dispute intake and customer protection.
- **Rule 4 & 11 (Data rigor & honest limitations):** All Portuguese cases explicitly labeled as team-generated (since LATAM Bank dataset has no native Portuguese); data leakage on `fraud_score` documented and excluded; production deployed with deterministic rules-only runtime and BM25 policy explainer; zero money movement authorized by AI.
- **Rule 5 (Cryptographic Identity):** Identity verified exclusively through Supabase Auth ES256 tokens (`app_metadata.customer_id`), never user-asserted.
- **Rule 7 (Verification before action):** Every action is verified via database read-back before customer confirmation.

We look forward to your review and feedback!

Best regards,  
**Team AlterEgo**  
Factored AI & Data Hackathon 2026
