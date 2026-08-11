Data Profiler Skill — Slide Deck
================================

Slide 1 — Title
---------------
Data Profiler Skill: Schema-driven Profiling

Notes: Audience: architects, data leads.

---

Slide 2 — Intent
-----------------
- Provide reusable profiling capabilities (summary, distributions, anomalies)
- Decouple profiling logic, config schema, and presentation

Notes: Emphasize data-driven configs.

---

Slide 3 — Form-as-Data
----------------------
- Profiling parameters are schemas (columns, sample size, checks)
- Renderer or notebook executes profiling based on schema

Notes: Example: enable outlier detection for numeric columns only.

---

Slide 4 — Key Features
----------------------
- Adaptive checks, sampling controls, distribution outputs, anomaly flags
- Metadata and provenance for reproducibility

---

Slide 5 — Integrations
----------------------
- Connectors, dashboards, downstream skills, storage
- Audit trail: data source version, profiling config id

---

Slide 6 — Risks & Mitigations
----------------------------
- Large data: sampling & async
- Connector variance: adapters + tests

---

Slide 7 — Approval Ask
---------------------
- Approve form-driven profiling architecture and registry

---

Slide 8 — Next Steps
--------------------
1. Publish schema + reference adapters
2. Deliver demo profiling runs and dashboards
