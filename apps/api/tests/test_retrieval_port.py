"""Retrieval orchestration against a small in-memory read-port implementation."""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path
from typing import Any, get_type_hints

import pytest

from app.application.ports import RetrievalReader
from app.retrieval import suggest, suggest_live


class MemoryReader:
    """Return configured synthetic rows and record which read path was used."""

    def __init__(self, exact: dict[str, Any] | None = None, matches: list[dict[str, Any]] | None = None):
        self.exact = exact
        self.matches = matches or []
        self.calls: list[tuple[str, str]] = []

    def find_exact_qa(self, question: str) -> dict[str, Any] | None:
        self.calls.append(("exact", question))
        return self.exact

    def find_matches(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        self.calls.append(("lexical", query))
        return self.matches[:limit]


class SemanticStub:
    def __init__(self, result: dict[str, Any] | None):
        self.result = result
        self.calls: list[str] = []

    def candidate(self, question: str) -> dict[str, Any] | None:
        self.calls.append(question)
        return self.result


def synthetic_row(kind: str = "qa") -> dict[str, Any]:
    return {
        "kind": kind,
        "question": "How does authentication work?",
        "answer": "Synthetic stored identity answer.",
        "body": "Authentication verifies identity.",
        "document_id": "synthetic-doc",
        "document_name": "synthetic.md",
        "location": "Line 1",
    }


def test_port_exposes_only_the_required_reads():
    methods = {name for name, value in vars(RetrievalReader).items()
               if not name.startswith("_") and inspect.isfunction(value)}
    assert methods == {"find_exact_qa", "find_matches"}
    assert inspect.signature(RetrievalReader.find_matches).parameters["limit"].default == 20
    assert get_type_hints(suggest)["store"] is RetrievalReader
    assert get_type_hints(suggest_live)["store"] is RetrievalReader


@pytest.mark.parametrize("live", [False, True])
def test_exact_answer_has_priority_with_an_in_memory_reader(live):
    memory = MemoryReader(exact=synthetic_row(), matches=[synthetic_row()])
    reader: RetrievalReader = memory
    semantic = SemanticStub({"unexpected": "must not be queried"})
    result = suggest_live(reader, "What is authentication?", semantic) if live else suggest(reader, "What is authentication?")
    assert result == {
        "status": "found", "answer": "Synthetic stored identity answer.",
        "source": {"document_id": "synthetic-doc", "document_name": "synthetic.md", "location": "Line 1"},
        "match_type": "exact_qa", "note": "Stored answer from your document",
    }
    assert memory.calls == [("exact", "What is authentication?")]
    assert semantic.calls == []


@pytest.mark.parametrize("kind,match_type", [("qa", "similar_qa"), ("text", "document_excerpt")])
def test_manual_search_falls_back_to_lexical_candidates(kind, match_type):
    best = synthetic_row(kind)
    irrelevant = {**synthetic_row(), "question": "zzzz", "answer": "Wrong candidate"}
    memory = MemoryReader(matches=[irrelevant, best])
    result = suggest(memory, "What is authentication?")
    assert memory.calls == [("exact", "What is authentication?"), ("lexical", "What is authentication?")]
    assert result == {
        "status": "found", "answer": best["answer"] if kind == "qa" else best["body"],
        "source": {"document_id": "synthetic-doc", "document_name": "synthetic.md", "location": "Line 1"},
        "match_type": match_type,
        "note": "Stored answer from your document" if kind == "qa" else "Original document excerpt; not an AI-generated answer",
    }


@pytest.mark.parametrize("weak_candidate", [False, True])
def test_manual_search_abstains_on_missing_or_weak_evidence(weak_candidate):
    rows = [{**synthetic_row(), "question": "zzzz"}] if weak_candidate else []
    memory = MemoryReader(matches=rows)
    assert suggest(memory, "What is authentication?") == {
        "status": "no_evidence", "answer": None, "source": None, "match_type": None,
    }
    assert [operation for operation, _ in memory.calls] == ["exact", "lexical"]


def test_live_search_preserves_semantic_candidate_and_never_uses_lexical_fallback():
    memory = MemoryReader(matches=[synthetic_row()])
    candidate = {
        "status": "found", "answer": "Synthetic stored identity answer.",
        "source": {"document_id": "synthetic-doc", "document_name": "synthetic.md", "location": "Line 1"},
        "match_type": "semantic_qa", "matched_question": "What is authentication?",
        "similarity": 0.9, "note": "Potentially related stored answer; requires user review",
    }
    semantic = SemanticStub(candidate)
    assert suggest_live(memory, "Explain identity verification", semantic) is candidate
    assert memory.calls == [("exact", "Explain identity verification")]
    assert semantic.calls == ["Explain identity verification"]


@pytest.mark.parametrize("with_semantic", [False, True])
def test_live_search_abstains_without_a_semantic_candidate(with_semantic):
    memory = MemoryReader(matches=[synthetic_row()])
    semantic = SemanticStub(None) if with_semantic else None
    assert suggest_live(memory, "Unrelated question", semantic) == {
        "status": "no_evidence", "answer": None, "source": None, "match_type": None,
    }
    assert memory.calls == [("exact", "Unrelated question")]
    if semantic is not None:
        assert semantic.calls == ["Unrelated question"]


def test_knowledge_store_remains_structurally_compatible(tmp_path):
    from app.domain.knowledge import ParsedEntry
    from app.store import KnowledgeStore

    store = KnowledgeStore(tmp_path)
    reader: RetrievalReader = store
    assert RetrievalReader not in KnowledgeStore.__mro__
    store.import_document(
        "synthetic.md", b"synthetic knowledge",
        [ParsedEntry("qa", "What is authentication?", "Stored identity answer.", "", "Line 1")],
    )
    exact = reader.find_exact_qa("what is authentication")
    assert exact is not None
    assert exact["answer"] == "Stored identity answer."
    assert reader.find_matches("authentication", limit=1)[0]["question"] == "What is authentication?"
    assert suggest(reader, "what is authentication")["match_type"] == "exact_qa"
    assert suggest(reader, "Explain authentication")["match_type"] == "similar_qa"
    assert suggest_live(reader, "what is authentication")["answer"] == "Stored identity answer."


def test_retrieval_and_port_import_without_sqlite_or_concrete_storage():
    script = """
import importlib.abc
import sys

sys.path.insert(0, sys.argv[1])
blocked = (
    'sqlite3', 'app.store', 'app.main', 'app.live', 'app.semantic', 'app.parsers',
    'fastapi', 'pydantic', 'docx', 'openpyxl', 'pypdf', 'vosk', 'fastembed',
)

def forbidden(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)

class RejectStorage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError('Unexpected dependency: ' + fullname)
        return None

sys.meta_path.insert(0, RejectStorage())
from app.application.ports import RetrievalReader
from app.retrieval import suggest, suggest_live

class EmptyReader:
    def find_exact_qa(self, question):
        return None
    def find_matches(self, query, limit=20):
        return []

reader = EmptyReader()
assert suggest(reader, 'Synthetic question')['status'] == 'no_evidence'
assert suggest_live(reader, 'Synthetic question')['status'] == 'no_evidence'
assert not [name for name in sys.modules if forbidden(name)]
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(Path(__file__).resolve().parents[1])],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
