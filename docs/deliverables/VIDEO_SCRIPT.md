# AlterEgo: 3-Minute Video Demo Script
**Factored AI & Data Hackathon 2026 — Team AlterEgo**  
**Target Duration:** Exactly 3:00 (180 seconds)  
**Tools Recommended:** OBS Studio, Loom, or Windows Game Bar (`Win + Alt + R`)  
**Resolution:** 1080p (16:9), Fullscreen Browser at [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app)

> [!CAUTION]
> **Recording Safety Rule:** Never show `.env`, `personas.local.json`, Supabase API secret keys, or browser developer tools with tokens during the recording.

---

## Part 1: The Problem & Motivation (0:00 – 0:20 | 20s)
**Visual:** Show Slide 1 or the Architecture overview (`alterego-system.html`), highlighting the call center metrics.  
**Action:** Mouse hover over the FCR metric (43.6%) and Disputed Charges (36.5%).  
**Spoken Voiceover (English):**
> "In retail banking across LATAM, transaction complaints are the costliest customer friction point: they have the lowest first-contact resolution at 43%, and 63% require manual follow-up. Most AI solutions deploy chatbots that hallucinate refunds or break under adversarial inputs.
>
> We built **AlterEgo**: an AI-first dispute intake engine that follows one core principle: **The model proposes, deterministic policy disposes**."

---

## Part 2: Live Production Demo (0:20 – 1:40 | 80s)
**URL:** [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app)

### Demo 1: Safe Automated Resolution Under $150 (0:20 – 0:40 | 20s)
**Action:** 
1. Log in as `cliente-hasta-150`.
2. Type in Spanish:  
   `"No reconozco un cargo de 113.65 USD del 3 de junio"`
3. Press Send.  
**Visual on Screen:**
- The assistant identifies the transaction, confirms eligibility within the 60-day window (`POL-WIN-60`), and automatically opens a dispute case under policy clause `POL-AUT-150`.
- The case number, disputed amount ($113.65 USD), and resolution timeline (3-5 business days) are displayed.  
**Spoken Voiceover:**
> "First, a standard dispute under 150 dollars. The customer claims an unrecognized charge. AlterEgo extracts the intent and date hints, validates that the charge exists and is within the 60-day window, executes the case creation through our secure gateway, and reads back the committed case ID before confirming. Zero human intervention needed."

---

### Demo 2: Multilingual Support in Portuguese (0:40 – 0:55 | 15s)
**Action:**
1. In the same session or with a new message, type in Portuguese:  
   `"Olá! Não reconheço uma cobrança suspeita feita ontem"`
2. Press Send.  
**Visual on Screen:**
- The assistant detects Portuguese seamlessly, queries available charges, and responds in fluent Portuguese asking for clarification or confirming details without language drift.  
**Spoken Voiceover:**
> "AlterEgo features native bilingual parity. When the user switches to Portuguese, the system maintains 99.2% language accuracy, adhering strictly to bank policies while communicating naturally in Portuguese."

---

### Demo 3: Proactive Card Locking upon Lost Card Report (0:55 – 1:20 | 25s)
**Action:**
1. Log in as `cliente-tarjeta-perdida`.
2. Type:  
   `"Perdí la tarjeta y no reconozco un cargo de 168.88 USD del 9 de junio"`
3. Press Send.  
**Visual on Screen:**
- The assistant detects the disputed charge, opens the dispute case, AND immediately identifies the security risk (`POL-AUT-LOCK`).
- Assistant replies: Offers an immediate, preventive card lock and asks for explicit confirmation:  
  `"¿Deseas que procedamos a bloquear preventivamente tu tarjeta terminada en XXXX para proteger tus fondos?"`
4. User replies: `"Sí, por favor bloquéala"`.
5. Visual confirms: The card is locked, read back from Postgres `ops.card_locks`, and confirmed to the customer.  
**Spoken Voiceover:**
> "Safety goes beyond forms. When a customer reports a lost card or fraud pattern, AlterEgo triggers our proactive protection policy. It files the dispute and immediately offers a preventive card lock. Only upon explicit customer confirmation does the tool gateway execute the lock and read it back from the operational store."

---

### Demo 4: The HITL Agent Console (1:20 – 1:40 | 20s)
**Action:**
1. Sign out and sign in with the `agente` persona.
2. The UI switches automatically to the English **HITL (Human-in-the-Loop) Console**.
3. Click on the escalated ticket from `cliente-mas-de-500` (dispute of $4,259.97 USD).  
**Visual on Screen:**
- Structured handoff packet: Customer metadata, verified transaction history, triggered policy clauses (`POL-ESC-500`), risk indicators, and recommendation for provisional credit.  
**Spoken Voiceover:**
> "When a dispute exceeds 500 dollars or flags anomalous risk, AlterEgo enforces mandatory escalation. In the HITL Console, bank specialists receive a structured handoff packet with verified facts, triggered clauses, and an advisory credit recommendation. No black-box summaries—only verifiable operational data."

---

## Part 3: Architecture & Security Rigor (1:40 – 2:30 | 50s)
**Visual:** Show the interactive Archify diagram [alterego-system.html](file:///d:/Hackaton/.archify/architecture-alterego-system-20261004-090340/alterego-system.html).  
**Action:** Pan from Client Channels -> Auth Guard -> 5-Stage Orchestrator -> Postgres `bank` & `ops` schemas.  
**Spoken Voiceover:**
> "Under the hood, AlterEgo runs a 5-stage deterministic pipeline: Understand, Decide, Act, Verify, and Escalate.
>
> 1. **Identity is cryptographically verified** via Supabase Auth ES256 session tokens. We never accept customer IDs from request bodies or model prompts.
> 2. **PII is masked** before any model sees it, protecting DNI, CPF, and card numbers.
> 3. **The Policy Engine is pure code:** 13 deterministic clauses control decisions. The LLM only proposes structured parameters; code disposes.
> 4. **Least-Privilege Tool Gateway:** Writes to Supabase Postgres `ops` schema with ownership validation and read-back before answering.
> 5. **Immutable Audit:** Every turn and decision is recorded in an append-only audit log."

---

## Part 4: Quantitative Results & Honest Limitations (2:30 – 3:00 | 30s)
**Visual:** Show Slide 4 (Evaluation Results Table) and Slide 5 (Limitations).  
**Action:** Highlight the comparison numbers on screen.  
**Spoken Voiceover:**
> "We evaluated AlterEgo on a frozen held-out suite of 250 cases, including 25 adversarial cases:
> - **Safe automated resolution** reached **98.1%** of eligible cases, compared to 3.7% in the starter baseline.
> - **Unnecessary escalations** dropped from 72 to **exactly zero**.
> - **Unsafe outcomes** decreased from 48.8% to 8%, with deterministic in-process execution.
>
> In accordance with hackathon rules, we state our limits honestly: Portuguese data was synthesized because the bank dataset only covers Spanish; production runs in rules-only mode to prevent hallucinations; and money movement is strictly reserved for authorized human bankers.
>
> AlterEgo proves that reliable banking AI isn't about chatty models—it's about deterministic policy, verified identity, and rigorous engineering. Thank you."

---

## Video Checklist Before Submitting:
- [ ] Duration is under 3 minutes and 5 seconds.
- [ ] Audio is crisp and intelligible.
- [ ] Production URL [https://alterego-silk.vercel.app](https://alterego-silk.vercel.app) is clearly visible in the browser address bar.
- [ ] No API keys, passwords, or personal email addresses visible on screen.
