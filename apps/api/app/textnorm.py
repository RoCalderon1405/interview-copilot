"""Shared text normalization for exact Q&A matching.

Single definition used by both the query side (``retrieval``) and the SQLite
comparison side (``store``) so an exact match means the same thing everywhere.
``retrieval.normalize`` re-exports this function for import compatibility.
Deterministic and locale-independent: no network, no dependencies.
"""
from __future__ import annotations

import re
import unicodedata

# ``\w+`` alone drops the significant suffixes of C++, C# and F#, so "What is
# C#" would collide with "What is C". Only these language names keep a
# suffix; ordinary trailing punctuation (?, !, ., ,) stays insignificant.
_TOKEN = re.compile(r"c\+\+|c#|f#|\w+")


def normalize(text: str) -> str:
    """Casefold, strip diacritics and join tokens with single spaces.

    ``"¿Qué es la API?"`` and ``"que es la api"`` both normalize to
    ``"que es la api"``; punctuation-only input normalizes to ``""``.
    Programming-language names stay distinct: ``"What is C++?"`` →
    ``"what is c++"``, ``"What is C#?"`` → ``"what is c#"``, while
    ``"What is C?"`` → ``"what is c"``.
    """
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(_TOKEN.findall(text))
