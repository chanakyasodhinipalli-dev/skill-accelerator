Skills Overview — How they work together
======================================

Scope
-----
This document summarizes the primary skills in the repository and how they compose into an end-to-end workflow. Primary skills covered:
- `data_profiler` — profiles tabular datasets
- `document_summarizer` — generates concise summaries and key points
- `policy_checker` — evaluates text against declarative rules

Overall Goal
------------
Provide a modular, audit-friendly pipeline that ingests data and content, profiles and summarizes it, and evaluates it against compliance policies before downstream use (publishing, analytics, or human review).

How the skills interact
----------------------
1. Ingest & Discover
   - Connectors (pluggable adapters) pull data and documents into the system.
   - `data_profiler` is run on newly ingested tabular datasets to produce a structured profile (types, null rates, distributions).

2. Summarize for Humans
   - `document_summarizer` produces abstracts and key points for long documents so reviewers can triage quickly.
   - Summaries and key points are used by reviewers and by downstream automated checks (e.g., quick risk heuristics).

3. Policy Evaluation (Gate)
   - `policy_checker` evaluates content (original documents, summaries, or generated text) against declarative rule sets provided by compliance teams.
   - Rules are data (id, pattern, severity, message, expect) so policy owners can maintain them without code changes.

4. Orchestration & Presentation
   - An orchestrator coordinates the steps: ingestion → profiling → summarization → policy evaluation.
   - Form schemas (form-as-data) determine what parameters to present to users at each step (profiling options, summarization modes, policy fail thresholds).
   - Renderers (console, web, chat) consume schemas and present dynamic UIs or conversational prompts.

5. Audit & Remediation
   - Each skill outputs metadata: schema/policy versions, timestamps, and actor ids to enable traceability.
   - If `policy_checker` reports blocking findings, the orchestrator can trigger remediation flows (editorial review, automated redaction, or rollback).

Design Principles
-----------------
- Form-as-data: All user-facing parameterization is schema-driven so UIs and workflows can be changed without code updates.
- Separation of concerns: Skills produce machine-readable outputs and avoid coupling to specific UIs.
- Composability: Skills are small, testable, and designed to be chained by the orchestrator.
- Auditability: Outputs include required metadata for compliance and RCA.

Example end-to-end flow
-----------------------
1. New dataset arrives via a connector.
2. `data_profiler` profiles the dataset; warnings are surfaced to data owners.
3. For documents, `document_summarizer` produces TL;DRs for human review.
4. `policy_checker` runs on both raw and summarized content using current policy rules.
5. If blocking findings appear, the flow records the event and notifies reviewers; otherwise, content is promoted to production.
