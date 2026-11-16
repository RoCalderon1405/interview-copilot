"""Neutral representations shared by document parsing and persistence."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedEntry:
    """Represent an extracted Q&A or text fragment with its source location."""

    kind: str  # 'qa' or 'text'
    question: str
    answer: str
    body: str
    location: str
