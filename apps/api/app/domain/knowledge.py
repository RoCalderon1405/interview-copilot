"""Neutral representations shared by document parsing and persistence."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedEntry:
    """Represent stored source wording; language is an optional explicit source label."""

    kind: str  # 'qa' or 'text'
    question: str
    answer: str
    body: str
    location: str
    language: str | None = None
