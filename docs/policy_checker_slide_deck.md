Policy Checker Skill — Slide Deck
================================

Slide 1 — Title
---------------
Policy Checker Skill: Data-driven Policy Evaluation

Notes: Introduce purpose and audience (architects, leads).

---

Slide 2 — Intent
-----------------
- Encapsulate policy evaluation as a reusable skill
- Decouple policy logic, schema, and presentation

Notes: Emphasize reuse and separation of concerns.

---

Slide 3 — Form-as-Data
----------------------
- Questions are schemas, not hard-coded prompts
- Renderer consumes schema and renders UI/Conversation

Notes: Show brief example: conditional follow-up based on severity.

---

Slide 4 — Key Features
----------------------
- Dynamic questioning
- Validation & coercion
- Metadata-rich findings
- Composable checks

Notes: Call out auditability and remediation suggestions.

---

Slide 5 — Integrations & Observability
-------------------------------------
- LLMs, connectors, registries via clear interfaces
- Audit trails: inputs, schema versions, decision metadata

Notes: Mention SLA and caching strategies.

---

Slide 6 — Risks & Mitigations
----------------------------
- Renderer misinterpretation -> schema contract + reference renderer
- Schema sprawl -> registry + governance
- Latency -> caching & async

---

Slide 7 — Approval Needed
------------------------
- Approve architecture, registry, and output metadata requirements
- Confirm external integrations and compliance guardrails

Notes: Ask reviewers for explicit sign-off items.

---

Slide 8 — Next Steps
--------------------
1. Publish canonical schema contract
2. Produce reference renderer + demo
3. Implement registry + governance

Notes: Offer to run a short demo once approved.
