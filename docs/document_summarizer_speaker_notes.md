Document Summarizer Skill — Speaker Notes
=======================================

Purpose
-------
- Explain the `document_summarizer` skill design and its flexible, form-driven approach for requesting summarization parameters.
- Reference implementation: [skills/document_summarizer/skill.py](skills/document_summarizer/skill.py)

Key Messages
------------
- Intent: provide a reusable summarization capability supporting multiple summary styles (extractive, abstractive, bullet points, TL;DR).
- Generic Forms: summarization options (length, style, focus areas) are schema-driven so UIs can render choices dynamically.
- Separation of Concerns: summarization logic, option schema, and UI/rendering are separated to allow independent changes.

Behavior & Features (what to highlight)
-------------------------------------
- Multiple modes: short, long, structured bullets, question-answer format—selectable via form schema.
- Context-aware prompts: runtime can add context or follow-ups based on document metadata.
- Output metadata: include summary type, token/length budget, model/version used, and confidence metrics.
- Post-processing hooks: cleaning, redaction, or citation extraction pipelines can be attached.
- Integrations: pluggable LLM providers and citation services.

Design Rationale (architect-focused)
----------------------------------
- Maintainability: modes and parameters represented as data enable quick tuning.
- Reusability: same schema can be reused across chat, web, or batch-processing flows.
- Testability: deterministic configs allow repeatable tests and comparisons.

Risks & Mitigations
-------------------
- Hallucination risk: include provenance/citation hooks and model/version metadata.
- Latency/cost: allow budgeted summaries and batching.

Approval Ask
------------
- Approve form-driven summarization architecture and required metadata in outputs.
- Confirm allowed LLM providers and citation/compliance requirements.

Next Steps (if approved)
-----------------------
1. Publish summarization schema and example templates.
2. Add demo flows: chat integration and batch summarization job.
