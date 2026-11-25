"""Conservative EN/ES documentary selection, independent of interface and providers."""
from __future__ import annotations

from typing import Literal

from ..textnorm import normalize

Language = Literal["en", "es"]
_EN = frozenset({"what", "how", "why", "when", "where", "which", "who", "is", "are", "does",
                 "could", "would", "explain", "tell", "please", "your"})
_ES = frozenset({"que", "como", "por", "para", "cuando", "donde", "cual", "quien", "es", "son",
                 "puedes", "podrias", "explica", "explicame", "dime", "una", "un", "los", "las", "tu"})


def question_language(question: str) -> Language | None:
    """Identify clear EN/ES question wording; do not guess from shared technical terms."""
    terms = set(normalize(question).split())
    en, es = len(terms & _EN), len(terms & _ES)
    if en > es:
        return "en"
    if es > en:
        return "es"
    return None


def matches_question_language(query: str, stored_question: str, declared: str | None) -> bool:
    """Require declared evidence to match; reject clear legacy question-language mismatches.

    Unlabelled legacy evidence stays unlabelled. Its question can rule out a clear
    mismatch but cannot establish or certify the language of its stored answer.
    """
    requested = question_language(query)
    if declared is not None:
        return requested is not None and declared == requested
    inferred = question_language(stored_question)
    return requested is None or inferred is None or requested == inferred
