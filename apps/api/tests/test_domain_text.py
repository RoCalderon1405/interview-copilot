"""Stopword compatibility, import independence and lexical behavior regressions."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.knowledge import ParsedEntry
from app.domain.text import STOPWORDS
from app.retrieval import STOPWORDS as RetrievalStopwords, assess_answer, overlap
from app.store import STOPWORDS as StoreStopwords, KnowledgeStore


def test_stopwords_preserve_existing_content_and_mutable_set_type():
    expected = set(
        "what why how are the and does with could would you your for this that is can do a an "
        "de la el los las que como por para una un cuál cual qué es en se me i to it of in on if".split()
    )
    assert type(STOPWORDS) is set
    assert STOPWORDS == expected


def test_stopwords_public_imports_reference_the_same_object():
    assert StoreStopwords is STOPWORDS
    assert RetrievalStopwords is STOPWORDS


@pytest.mark.parametrize(
    ("question", "reference", "expected"),
    [
        ("What is authentication?", "Authentication verifies identity.", 1.0),
        ("What is authentication and authorization?", "Authentication verifies identity.", 0.5),
        ("¿Qué es la autenticación?", "La autenticación verifica identidad.", 1.0),
        ("cómo resuelves un conflicto", "resuelves conflictos", 0.5),
        ("what why cuál qué", "authentication", 0.0),
        ("authentication", "authorization", 0.0),
        ("", "authentication", 0.0),
    ],
)
def test_lexical_overlap_keeps_existing_en_es_results(question, reference, expected):
    assert overlap(question, reference) == expected


def test_fts_filtering_keeps_existing_stopword_and_content_token_behavior(tmp_path):
    store = KnowledgeStore(tmp_path)
    store.import_document(
        "synthetic.md", b"synthetic lexical entries",
        [
            ParsedEntry("qa", "what why how with could would cuál qué", "Synthetic answer", "", "Line 1"),
            ParsedEntry("qa", "What is authentication?", "Identity verification", "", "Line 2"),
        ],
    )
    # The first entry deliberately contains the excluded words: a missing filter
    # would return it instead of abstaining on a stopword-only query.
    assert store.find_matches("what why how with could would cuál qué") == []
    assert [row["question"] for row in store.find_matches("what is authentication")] == [
        "What is authentication?"
    ]


def test_keyword_feedback_still_excludes_stopwords():
    feedback = assess_answer("authentication", "what authentication authorization")
    assert feedback["score"] == 50
    assert feedback["missing_concepts"] == ["authorization"]
    assert feedback["method"] == "keyword_coverage_only"


def test_domain_text_import_does_not_load_infrastructure_or_frameworks():
    script = """
import importlib.abc
import sys

sys.path.insert(0, sys.argv[1])
blocked = (
    'sqlite3', 'fastapi', 'pydantic', 'docx', 'openpyxl', 'pypdf', 'vosk', 'fastembed',
    'app.store', 'app.retrieval', 'app.parsers', 'app.live', 'app.semantic', 'app.main',
    'app.infrastructure', 'app.presentation',
)

def forbidden(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)

class RejectInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError('Unexpected dependency: ' + fullname)
        return None

sys.meta_path.insert(0, RejectInfrastructure())
from app.domain.text import STOPWORDS
assert type(STOPWORDS) is set
assert not [name for name in sys.modules if forbidden(name)]
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(Path(__file__).resolve().parents[1])],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
