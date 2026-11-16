"""Narrow read contracts required by the existing retrieval functions."""
from __future__ import annotations

from typing import Any, Protocol


class RetrievalReader(Protocol):
    """Read stored Q&A and lexical candidates without requiring SQLite.

    Rows keep their existing dictionary representation; implementations supply
    stored wording and source metadata, not generated answer text.
    """

    def find_exact_qa(self, question: str) -> dict[str, Any] | None:
        """Return the normalized exact Q&A with source metadata, or None."""
        ...

    def find_matches(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return bounded lexical candidates in the existing row format."""
        ...
