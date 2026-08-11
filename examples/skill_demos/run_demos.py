#!/usr/bin/env python3
"""Run small demos of the repository skills.

This script attempts to import the skills directly from the workspace and
invoke them with sample inputs. It adds the repository root to `sys.path`
so the local packages are importable.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def add_repo_root_to_path():
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))


async def run_policy_checker():
    from skills.policy_checker.skill import check_policy

    content = "Customer SSN 123-45-6789 appears in this document."
    rules = [
        {"id": "no-ssn", "pattern": r"\b\d{3}-\d{2}-\d{4}\b", "severity": "high", "message": "SSN detected"},
        {"id": "no-test-words", "pattern": r"testword", "severity": "low", "message": "test word found"},
    ]

    result = await check_policy(content=content, rules=rules, fail_on="high")
    print("--- policy_checker result ---")
    print(json.dumps(result, indent=2))


async def run_data_profiler():
    from skills.data_profiler.skill import profile_dataset

    rows = [
        {"id": 1, "value": 10, "status": "ok"},
        {"id": 2, "value": 12, "status": "ok"},
        {"id": 3, "value": None, "status": "missing"},
    ]

    result = await profile_dataset(rows=rows)
    print("--- data_profiler result ---")
    print(json.dumps(result, indent=2))


async def run_document_summarizer():
    from skills.document_summarizer.skill import summarize_document

    text = (
        "OpenAI released a new model that improves performance on reasoning tasks. "
        "Organizations use summarization to help users triage long documents quickly. "
        "This demo shows a short summary and key points."
    )

    result = await summarize_document(text=text, max_points=3, max_summary_sentences=2)
    print("--- document_summarizer result ---")
    print(json.dumps(result, indent=2))


async def main():
    add_repo_root_to_path()
    await run_policy_checker()
    await run_data_profiler()
    await run_document_summarizer()


if __name__ == "__main__":
    asyncio.run(main())
