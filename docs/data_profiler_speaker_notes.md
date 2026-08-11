Data Profiler Skill — Speaker Notes
=================================

Purpose
-------
- Explain the `data_profiler` skill design and its generic, form-driven approach.
- Reference implementation: [skills/data_profiler/skill.py](skills/data_profiler/skill.py)

Key Messages
------------
- Intent: encapsulate data-profiling capabilities (summary stats, distributions, anomalies) as a reusable skill rather than a fixed UI.
- Generic Forms: profiling parameters and questions are modelled as data; the runtime computes profiling flows based on dataset metadata and user intent.
- Separation of Concerns: profiling logic, form schema, and presentation are decoupled to enable independent evolution.

Behavior & Features (what to highlight)
-------------------------------------
- Adaptive Profiling: choose which checks to run (nulls, cardinality, outliers) based on schema and user selections.
- Sampling & Performance Controls: form-driven options for sample size, histograms bins, and approximation strategies.
- Validation & Normalization: input validation for column selectors and type coercion for consistent analysis.
- Metadata-rich Output: results include field-level summaries, distributions, anomalies, and confidence metrics.
- Composable Checks: profiling steps are modular and can be combined or scheduled.
- Integrations: pluggable connectors for data sources; outputs can feed downstream skills or dashboards.
- Auditability: record data source versions, profiling parameters, and execution metadata.

Design Rationale (architect-focused)
----------------------------------
- Maintainability: profiling behaviors expressed as schemas allow non-developers to tune analyses.
- Scalability: supports distributed or sampled profiling strategies without changing core code.
- Testability: unit-testable components for schema parsing, sampling, and metric calculations.

Risks & Mitigations
-------------------
- Large datasets: mitigate with sampling strategies and async execution.
- Connector inconsistency: provide adapter interfaces and reference connectors.

Approval Ask
------------
- Approve form-driven profiling architecture and schema contract.
- Approve metadata requirements for outputs and registry/versioning for profiling configs.

Next Steps (if approved)
-----------------------
1. Publish canonical profiling schema and reference connector adapters.
2. Add sample profiles and demo notebooks/dashboards.
3. Implement registry for profiling configs and versioning.
