Data Profiler Skill — One-Page Approval Summary
==============================================

Summary
-------
Proposal: `data_profiler` skill implemented as a data-driven, form-configurable capability that profiles datasets (summary stats, distributions, anomalies) and returns structured results.

What We Are Asking Approval For
-------------------------------
- Adopt a form-as-data architecture for data profiling controls and parameters.
- Approve registry and versioning for profiling configuration schemas.
- Require profiling outputs to include data source id, schema version, profiling config id, timestamp, and actor.

Benefits
--------
- Faster tuning: analysts can change profiling parameters via schemas without code changes.
- Reusable across UIs and pipelines: same schema supports dashboards, notebooks, or conversational flows.
- Traceability: metadata and versioned configs enable reproducible profiling runs.

Risks & Controls
----------------
- High compute on large datasets: enforce sampling defaults and async execution patterns.
- Connector variance: require adapter tests and reference implementations.

Approval Checklist
------------------
- [ ] Approve architecture and schema registry
- [ ] Approve required output metadata for audits
- [ ] Confirm connector list and SLA expectations

Next Steps
----------
1. Publish profiling schema and reference adapters.
2. Create demo profiling runs and dashboards.
