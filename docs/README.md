# Documentation Map & Knowledge Base

This directory contains the canonical system architecture, policy specifications, deployment designs, security audit plans, and historical technical reviews for the **Factored AI & Data Hackathon 2026** transaction dispute system (**AlterEgo**).

---

## Precedence Rules (When Sources Disagree)

As established in `AGENTS.md` Section 2:
1. **Official Problem Statement & Kickoff Slides** (absolute constraints).
2. **Hackathon Non-Negotiable Rules** (`AGENTS.md` Section 4).
3. **Canonical Master Plan & Decision Log** (`docs/PLAN.md`).
4. **Complemented Team Brief & Policy Spec** (`docs/TEAM_BRIEF_COMPLEMENTED.md`).
5. **Component Design Specs** (`docs/SUPABASE_VERCEL.md`, `docs/JEV_TYPESAFE_AI.md`).
6. **Codebase Implementation** *(code that disagrees with the brief is a gap to plan, not a spec change)*.

---

## Document Index

### 1. System Architecture & Master Planning

| Document | Language | Purpose & Content |
| :--- | :--- | :--- |
| [**`PLAN.md`**](PLAN.md) | Spanish | **Canonical Master Plan.** Problem question, 5-stage architecture diagram, decision log with closed/open gates, team ownership lanes, and day-by-day roadmap. |
| [**`TEAM_BRIEF_COMPLEMENTED.md`**](TEAM_BRIEF_COMPLEMENTED.md) | English | **Dispute Policy Specification (v2.5).** Exact clause IDs (`POL-WIN-60`, `POL-ESC-500`, etc.), data contracts, structured handoff packet, held-out evaluation suite design, and official metric formulas. |
| [**`SUPABASE_VERCEL.md`**](SUPABASE_VERCEL.md) | Spanish | **Identity, Data & Deployment Architecture.** Supabase Auth (ES256 JWKS), `bank` (read-only serving) & `ops` schemas, database security/RLS, Vercel Hobby deployment, and double canary design. |
| [**`JEV_TYPESAFE_AI.md`**](JEV_TYPESAFE_AI.md) | Spanish | **Cognitive Separation (System 1 vs System 2).** Jev (TypeSafe AI) typed signals (`Choice`, `Noul`, `Score`), policy integration, and fallback keyword extractor baseline. |
| [**`SECURITY_AUDIT_PLAN.md`**](SECURITY_AUDIT_PLAN.md) | Spanish | **Security & Compliance Audit.** Cloudflare methodology findings SEC-01 to SEC-10, zero-trust session checks, PII redaction, and prompt injection defense. |

---

### 2. Specialized Subdirectories

- [**`docs/reviews/`**](reviews/):
  - `2026-09-26-revision-adversarial-plan.md`: Adversarial review of team plan, risk mitigations, and blindspot analysis.
  - `2026-09-26-revision-tecnologica.md`: Technical stack evaluation (ONNX vs PyTorch, Vercel vs Render, Supabase vs SQLite).
  - `2026-09-26-reuso-lead-agent-crm-starter.md`: Starter code reuse analysis and extraction plan.
- [**`docs/prompts/`**](prompts/):
  - `fable_sdd_tdd.md`: Prompt engineering guides for Schema-Driven & Test-Driven Development.
- [**`docs/reference/`**](reference/):
  - `Datathon_2026_Kickoff.pdf`: Official kickoff presentation slides.
  - `Factored_AI_Data_Hackathon_2026.pdf`: Official problem statement and evaluation rubric.
  - `LATAM_Bank_Dataset_Summary.pdf`: Synthetic dataset structure and volume metrics.
  - `LATAM_Bank_Complete_Data_Dictionary.pdf`: Complete 13-table column schemas and foreign key graph *(git-ignored to protect embedded AWS keys)*.

---

## Writing & Documentation Standards

- **Language discipline:** Customer-facing texts in Spanish/Portuguese; code, schemas, and public deliverables in English; internal architecture notes in Spanish.
- **Punctuation:** Never use em-dashes (`—`) or en-dashes (`–`) in human-facing markdown files; use commas, periods, colons, or parentheses.
- **Data provenance:** Every dataset sample, test fixture, or eval case must declare its label: `synthetic-organizer`, `team-generated`, or `derived`.
