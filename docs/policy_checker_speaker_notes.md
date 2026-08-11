Policy Checker Skill — Speaker Notes
=================================

Purpose
-------
- Explain the `policy_checker` skill design and why it uses a generic, form-driven approach rather than fixed questions.
- Reference implementation: [skills/policy_checker/skill.py](skills/policy_checker/skill.py)

Key Messages
------------
- Intent: encapsulate policy-evaluation logic as a reusable capability, not a fixed UI.
- Generic Forms: questions are modelled as data (form-as-data). The runtime computes and renders prompts based on context and policy metadata.
- Separation of Concerns: policy evaluation, form schema, and presentation are decoupled to enable independent evolution.

Behavior & Features (what to highlight)
-------------------------------------
- Dynamic Questioning: conditional fields, computed defaults, and follow-ups driven by prior answers or evaluation results.
- Validation & Coercion: field-level validation ensures structured, normalized data for downstream checks.
- Metadata-rich Findings: outputs contain policy id, severity, rationale, suggested remediation, and evidence references.
- Composable Checks: multiple modular checks can be combined, sequenced, or run in parallel and merged into a unified result.
- Integrations: clear interfaces for LLMs, connectors, and registries so external providers can be swapped without changing core logic.
- Observability & Audit: record inputs, policy/schema versions, and decisions for auditability and RCA.
- Consent & Data Handling: supports policy-driven redaction and consent flows before evaluation.
- Retry/Error Handling: classifies transient vs permanent errors and supports retry/backoff for external dependencies.

Design Rationale (architect-focused)
----------------------------------
- Maintainability: moving forms out of code reduces churn. Business changes live in schemas and policy data.
- Flexibility: renderers (web, chat, console) can present the same schema without reauthoring policy logic.
- Testability: form generation and policy evaluation are independently unit-testable; schemas enable deterministic E2E tests.
- Governance: versioned schemas + audit trails support compliance and change control.
- Scalability: data-driven runtime supports many policies and UIs with modest engineering overhead.

Risks & Mitigations
-------------------
- Renderer misinterpretation: mitigate by publishing a small, strict schema contract and reference renderer components.
- Schema sprawl: mitigate via a schema registry, enforced versioning, and a governance workflow for schema changes.
- External latency: mitigate with caching, async execution, and graceful degradation.

Approval Ask
------------
- Approve the data-driven, form-as-config architecture for policy skills.
- Approve separation of policy evaluation, form schemas, and renderers.
- Approve schema registry and required metadata in outputs (policy id, schema version, timestamp, actor).
- Confirm integrations (LLM provider, connectors) and compliance guardrails.

Next Steps (if approved)
-----------------------
1. Publish a canonical form schema contract and a reference renderer.
2. Populate sample policy schemas and a small end-to-end demo.
3. Establish schema registry and release/migration process.
4. Define observability SLAs and dashboards for policy evaluations.

Notes for presenters
-------------------
- Keep examples concrete: show a short example of a conditional form (e.g., follow-up when severity high).
- Demonstrate how a policy change can be rolled out by swapping a schema file.
