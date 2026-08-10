"""Extractive document summarization.

A deliberately dependency-free reference skill: it demonstrates the authoring
contract (decorator, docstring-derived schema, structured output) without
requiring a model call, so it runs in CI and in air-gapped environments.
"""

from __future__ import annotations

import re
from collections import Counter

from sa_skills import skill

# Words that carry no topical signal and would otherwise dominate the scoring.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by for from has have he her his if in into is it
    its of on or that the their then there these they this to was were will with
    we you your our not no been had do does did can could should would may might
    """.split()
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\b[\w'-]+\b")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text.strip()) if s.strip()]


def _score_sentences(sentences: list[str]) -> list[tuple[int, str, float]]:
    """Rank sentences by the frequency of the content words they contain."""
    frequencies: Counter[str] = Counter()
    for sentence in sentences:
        for word in _WORD.findall(sentence.lower()):
            if word not in _STOPWORDS and len(word) > 2:
                frequencies[word] += 1

    if not frequencies:
        return [(i, s, 0.0) for i, s in enumerate(sentences)]

    peak = max(frequencies.values())
    scored: list[tuple[int, str, float]] = []

    for index, sentence in enumerate(sentences):
        words = [w for w in _WORD.findall(sentence.lower()) if w not in _STOPWORDS and len(w) > 2]
        if not words:
            scored.append((index, sentence, 0.0))
            continue
        # Normalise by length so a long sentence does not win on volume alone.
        score = sum(frequencies[w] / peak for w in words) / len(words)
        # Mild positional prior: opening sentences usually carry the thesis.
        if index == 0:
            score *= 1.25
        scored.append((index, sentence, score))

    return scored


@skill(
    name="document.summarize",
    version="1.0.0",
    description="Summarize a document into an abstract and key points.",
    category="analysis",
    stability="stable",
    owner="knowledge-platform",
    tags=["text", "summarization"],
    max_retries=2,
)
async def summarize_document(
    text: str,
    max_points: int = 5,
    max_summary_sentences: int = 3,
) -> dict:
    """Summarize a document into an abstract and a list of key points.

    Call this when a reader needs the gist of a long document before deciding
    whether to read all of it.

    Args:
        text: The full document text to summarize.
        max_points: Maximum number of key points to extract.
        max_summary_sentences: Maximum sentences in the abstract.
    """
    from sa_platform.errors import ValidationError

    if not text or not text.strip():
        raise ValidationError("text must not be empty", details={"field": "text"})

    sentences = _sentences(text)
    original_words = len(_WORD.findall(text))

    if not sentences:
        raise ValidationError("no sentences could be extracted from the text")

    scored = _score_sentences(sentences)
    ranked = sorted(scored, key=lambda row: row[2], reverse=True)

    # Re-sort the winners into document order so the abstract still reads.
    abstract_rows = sorted(ranked[:max_summary_sentences], key=lambda row: row[0])
    summary = " ".join(row[1] for row in abstract_rows)

    key_points = [row[1] for row in ranked[:max_points] if row[2] > 0]
    summary_words = len(_WORD.findall(summary))

    return {
        "summary": summary,
        "key_points": key_points,
        "original_words": original_words,
        "summary_words": summary_words,
        "compression_ratio": round(summary_words / original_words, 4) if original_words else 0.0,
    }
