Document Summarizer Skill — One-Page Approval Summary
=====================================================

Summary
-------
Proposal: `document_summarizer` as a form-driven, configurable summarization skill supporting multiple summary modes and metadata-rich outputs.

What We Are Asking Approval For
-------------------------------
- Approve form-as-data approach for summarization parameters.
- Require output metadata: summary mode, model/version, token budget, and provenance/citation info.

Benefits
--------
- Rapid iteration: change summary templates and parameters without code changes.
- Multi-channel reuse: same schema supports chat, web UI, and batch jobs.
- Compliance: provenance and citation hooks aid validation.

Risks & Controls
----------------
- Hallucination: require citation/extraction step and model/version metadata.
- Cost/latency: support budgeted summaries and batching.

Approval Checklist
------------------
- [ ] Approve architecture and metadata requirements
- [ ] Confirm approved LLM providers and citation workflows

Next Steps
----------
1. Publish summarization schema and templates.
2. Create demo integrations (chat + batch).
