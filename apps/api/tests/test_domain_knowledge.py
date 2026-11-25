"""Compatibility and dependency boundaries for extracted knowledge entries."""
from __future__ import annotations

import inspect
import subprocess
import sys
from dataclasses import MISSING, FrozenInstanceError, fields
from pathlib import Path
from typing import get_type_hints

import pytest

from app.domain.knowledge import ParsedEntry
from app.parsers import ParsedEntry as ParserEntry, parse_file
from app.store import ParsedEntry as StoreEntry


def test_parsed_entry_public_imports_share_one_class():
    assert ParserEntry is ParsedEntry
    assert StoreEntry is ParsedEntry
    entries = parse_file("synthetic.md", b"Q: What is authentication?\nA: It verifies identity.")
    assert type(entries[0]) is ParsedEntry


def test_parsed_entry_preserves_required_fields_and_adds_optional_source_language():
    names = ["kind", "question", "answer", "body", "location"]
    assert [field.name for field in fields(ParsedEntry)] == names + ["language"]
    assert get_type_hints(ParsedEntry) == {**dict.fromkeys(names, str), "language": str | None}
    assert list(inspect.signature(ParsedEntry).parameters) == names + ["language"]
    assert all(field.default is MISSING and field.default_factory is MISSING for field in fields(ParsedEntry)[:5])
    assert fields(ParsedEntry)[5].default is None
    assert all(parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
               for parameter in inspect.signature(ParsedEntry).parameters.values())


@pytest.mark.parametrize("kind", ["qa", "text"])
def test_parsed_entry_preserves_construction_equality_and_frozen_values(kind):
    positional = ParserEntry(kind, "Synthetic question", "Synthetic answer", "Synthetic body", "Line 1")
    keyword = ParsedEntry(
        kind=kind, question="Synthetic question", answer="Synthetic answer",
        body="Synthetic body", location="Line 1",
    )
    assert positional == keyword
    assert positional != ParsedEntry(kind, "Other question", "Synthetic answer", "Synthetic body", "Line 1")
    assert (positional.kind, positional.question, positional.answer, positional.body, positional.location) == (
        kind, "Synthetic question", "Synthetic answer", "Synthetic body", "Line 1",
    )
    assert ParsedEntry.__dataclass_params__.frozen is True
    with pytest.raises(FrozenInstanceError):
        setattr(positional, "answer", "Changed")
    with pytest.raises(FrozenInstanceError):
        delattr(positional, "location")


@pytest.mark.parametrize("module_name", ["app.domain.knowledge", "app.store"])
def test_knowledge_imports_do_not_load_document_libraries_or_frameworks(module_name):
    # A fresh interpreter prevents prior pytest imports from concealing an
    # accidental dependency. Block imports as well as inspecting loaded modules.
    script = """
import importlib
import importlib.abc
import sys

sys.path.insert(0, sys.argv[1])
blocked = (
    'docx', 'openpyxl', 'pypdf', 'fastapi', 'pydantic', 'vosk', 'fastembed',
    'app.parsers', 'app.main', 'app.live', 'app.retrieval', 'app.semantic',
    'app.infrastructure', 'app.presentation',
)
if sys.argv[2] == 'app.domain.knowledge':
    blocked += ('sqlite3', 'app.store')

def forbidden(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)

class RejectInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError('Unexpected dependency: ' + fullname)
        return None

sys.meta_path.insert(0, RejectInfrastructure())
module = importlib.import_module(sys.argv[2])
from app.domain.knowledge import ParsedEntry
assert module.ParsedEntry is ParsedEntry
assert not [name for name in sys.modules if forbidden(name)]
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(Path(__file__).resolve().parents[1]), module_name],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
