Policy Checker Skill — One-Page Approval Summary
===============================================

Summary
-------
This proposal outlines the `policy_checker` skill design: a data-driven, form-as-config policy-evaluation capability that separates policy logic, form schema, and rendering. The skill evaluates inputs against modular policies and returns structured, auditable findings.

What We Are Asking Approval For
-------------------------------
- Adopt a form-as-data architecture for policy-related skills.
- Approve separation between policy evaluation, form schemas, and renderers.
- Establish a schema registry with versioning and an approval workflow.
- Require structured outputs to include policy id, schema version, timestamp, and actor for auditability.

Benefits
--------
- Faster iteration: policy or question changes are schema-driven—no code changes required.
- Multi-channel: same schema supports web, chat, or console renderers.
- Compliance: versioned schemas + audit logs improve traceability.
- Testability: schemas enable deterministic unit and E2E tests.

Risks & Controls
----------------
- Renderer mismatch: publish a strict schema contract and a reference renderer.
- Schema sprawl: gate through registry and governance.
- External latency: use caching, async execution, and graceful degradation.

Approval Checklist (proposed)
----------------------------
- [ ] Approve architecture (form-as-data + separation of concerns)
- [ ] Approve schema registry and versioning policy
- [ ] Approve required output metadata fields for audit
- [ ] Confirm external integration list (LLM provider(s), connectors, observability)

Next Steps Once Approved
------------------------
1. Create canonical form schema contract and reference renderer components.
2. Add a small E2E demo and test suite using sample schemas.
3. Implement schema registry and governance process.
