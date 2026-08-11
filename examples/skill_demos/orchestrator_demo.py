#!/usr/bin/env python3
"""Simple orchestrator demo chaining the skills end-to-end.

Workflow:
 - Profile a dataset
 - Summarize a document
 - Run policy checks on both the document and the summary
 - Emit a consolidated report indicating pass/fail and recommendations
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def add_repo_root_to_path():
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))


async def orchestrate():
    from skills.data_profiler.skill import profile_dataset
    from skills.document_summarizer.skill import summarize_document
    from skills.policy_checker.skill import check_policy

    # Sample inputs
    rows = [
        {"id": 1, "value": 10, "status": "ok"},
        {"id": 2, "value": 12, "status": "ok"},
        {"id": 3, "value": None, "status": "missing"},
    ]

    document = (
        "Employee confidential note: employee SSN 987-65-4321 was recorded. "
        "Please review for PII handling. The model should flag sensitive items."
    )

    policy_rules = [
        {"id": "ssn", "pattern": r"\b\d{3}-\d{2}-\d{4}\b", "severity": "critical", "message": "SSN found"},
    ]

    report: dict = {"profile": None, "summary": None, "policy": {}}

    # Profile dataset
    profile = await profile_dataset(rows=rows)
    report["profile"] = profile

    # Summarize document
    summary = await summarize_document(text=document, max_points=3, max_summary_sentences=2)
    report["summary"] = summary

    # Policy checks: run on original and on summary text
    doc_policy = await check_policy(content=document, rules=policy_rules, fail_on="high")
    sum_policy = await check_policy(content=summary["summary"], rules=policy_rules, fail_on="high")

    report["policy"]["document"] = doc_policy
    report["policy"]["summary"] = sum_policy

    # Consolidated decision
    passed = doc_policy["passed"] and sum_policy["passed"]
    report["conclusion"] = {"passed": passed}

    print("=== Orchestrator Report ===")
    print(json.dumps(report, indent=2))


def main():
    add_repo_root_to_path()
    asyncio.run(orchestrate())


if __name__ == "__main__":
    main()
