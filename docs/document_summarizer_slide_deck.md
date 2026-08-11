Document Summarizer Skill — Slide Deck
====================================

Slide 1 — Title
---------------
Document Summarizer Skill: Configurable Summaries

Notes: Audience: architects, product leads.

---

Slide 2 — Intent
-----------------
- Provide reusable summarization with configurable modes and budgets
- Decouple summarization logic, parameter schema, and renderers

---

Slide 3 — Form-as-Data
----------------------
- Parameters (length, style, focus) are schemas
- Renderer or batch job applies schema to produce summary

---

Slide 4 — Key Features
----------------------
- Multiple summary modes, provenance hooks, token budget controls

---

Slide 5 — Integrations
----------------------
- LLM providers, citation services, downstream workflows

---

Slide 6 — Risks & Mitigations
----------------------------
- Hallucination -> citations + model metadata
- Cost -> budgeted summaries

---

Slide 7 — Approval Ask
---------------------
- Approve form-driven summarization architecture and metadata requirements

---

Slide 8 — Next Steps
--------------------
1. Publish schema + example templates
2. Deliver demo chat and batch integrations
