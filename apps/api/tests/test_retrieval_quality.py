"""Synthetic labeled retrieval-quality checks for the local lexical baseline.

Every document and query is invented (see tests/fixtures/); nothing here is
real user data and no network access is involved. The measured metrics are
explicitly NOT hybrid or semantic retrieval quality:

- top1 correct-source rate: end-to-end ``suggest()`` returned the labeled
  stored literal answer from the labeled source document.
- FTS Recall@5 / MRR: candidate-generation quality of ``store.find_matches()``
  alone (SQLite FTS5, bounded to 20 candidates). Candidate metric only.
- unsupported-answer rate: labeled-unanswerable queries that returned
  ``found`` (grounded stored text, never fabricated).
- exact-QA priority: normalized exact questions answered before any FTS
  candidate search, preserving the stored answer and provenance.
- automatic Live coverage: ``suggest_live()`` answers exactly 17/27 answerable
  labels and abstains on all 10 paraphrases and all 10 unanswerables (manual
  ``suggest()`` keeps its broader behavior).
"""
import json
import statistics
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parsers import ParsedEntry
from app.retrieval import suggest, suggest_live
from app.store import KnowledgeStore

FIXTURES = Path(__file__).parent / "fixtures"
KB_DIR = FIXTURES / "retrieval_kb"


def load_queries() -> list[dict]:
    payload = json.loads((FIXTURES / "retrieval_queries.json").read_text(encoding="utf-8"))
    return payload["queries"]


@pytest.fixture
def kb(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        for path in sorted(KB_DIR.glob("*.md")):
            response = client.post("/documents", files={"file": (path.name, path.read_bytes(), "text/markdown")})
            assert response.status_code == 201, response.text
        yield client, app.state.store


def is_correct_source(result: dict, query: dict) -> bool:
    """True only when the literal stored answer and its document match the label."""
    return (
        result["status"] == "found"
        and result["answer"] == query["expected_answer"]
        and result["source"]["document_name"] == query["expected_document"]
    )


class SpyStore:
    """Delegating store that counts find_matches calls (ordering evidence)."""

    def __init__(self, store):
        self._store = store
        self.find_matches_calls = 0

    def __getattr__(self, name):
        return getattr(self._store, name)

    def find_matches(self, query, limit=20):
        self.find_matches_calls += 1
        return self._store.find_matches(query, limit)


def test_normalize_reexport_compatibility():
    """retrieval.normalize remains importable and identical to the shared helper."""
    from app.retrieval import normalize as retrieval_normalize
    from app.textnorm import normalize

    assert retrieval_normalize("¿Qué es la API?") == normalize("¿Qué es la API?") == "que es la api"


def test_normalization_ignores_ordinary_punctuation():
    """Ordinary sentence punctuation stays insignificant (unchanged behavior)."""
    from app.textnorm import normalize

    assert normalize("What is a REST API?!") == "what is a rest api"
    assert normalize("Hello, world.") == "hello world"
    assert normalize("C++/C#/F#") == "c++ c# f#"


def test_programming_language_suffixes_are_significant():
    """C/C++/C#/F/F# stay distinct; ordinary trailing punctuation stays ignored."""
    from app.retrieval import normalize as retrieval_normalize
    from app.textnorm import normalize

    cases = {
        "What is C?": "what is c",
        "What is C++?": "what is c++",
        "What is C#?": "what is c#",
        "What is F?": "what is f",
        "What is F#?": "what is f#",
        "What is C++?!": "what is c++",
    }
    for text, expected in cases.items():
        assert normalize(text) == expected, text
        assert retrieval_normalize(text) == expected, text


def test_language_suffix_questions_answer_their_own_sources(tmp_path):
    """With C, C++, C#, F and F# stored, each question returns its literal source."""
    store = KnowledgeStore(tmp_path)
    entries = [
        ("lang-c.md", "What is C?", "C is a procedural language.", "Línea 1"),
        ("lang-cpp.md", "What is C++?", "C++ adds object-oriented features to C.", "Línea 1"),
        ("lang-csharp.md", "What is C#?", "C# is a managed .NET language.", "Línea 1"),
        ("lang-f.md", "What is F?", "F is the letter F reference.", "Línea 1"),
        ("lang-fsharp.md", "What is F#?", "F# is a functional .NET language.", "Línea 1"),
    ]
    for index, (name, question, answer, location) in enumerate(entries):
        store.import_document(
            name, f"payload-{index}".encode(), [ParsedEntry("qa", question, answer, "", location)]
        )
    for name, question, answer, location in entries:
        for query in (question, question.rstrip("?") + "?!"):
            result = suggest_live(store, query)
            assert result["status"] == "found", query
            assert result["match_type"] == "exact_qa", query
            assert result["answer"] == answer, query
            assert result["source"]["document_name"] == name, query
            assert result["source"]["location"] == location, query


def test_language_suffix_collision_never_returns_another_language(tmp_path):
    """Supervisor repro: only C++ stored must not answer 'What is C#?'."""
    store = KnowledgeStore(tmp_path)
    store.import_document(
        "only-cpp.md",
        b"only cpp",
        [ParsedEntry("qa", "What is C++?", "C++ reference answer.", "", "Línea 1")],
    )
    for query in ("What is C#?", "What is C?", "What is F#?"):
        result = suggest_live(store, query)
        assert result["status"] == "no_evidence", query
        assert result["answer"] is None and result["source"] is None, query
        # Manual /answers must not borrow the C++ answer either.
        assert suggest(store, query)["status"] == "no_evidence", query
    found = suggest_live(store, "What is C++?")
    assert found["answer"] == "C++ reference answer."
    assert found["source"]["document_name"] == "only-cpp.md"


def test_dataset_shape_meets_acceptance():
    queries = load_queries()
    kinds = [q["kind"] for q in queries]
    assert len(queries) >= 30
    assert kinds.count("exact") >= 15
    assert kinds.count("paraphrase") >= 10
    assert kinds.count("unanswerable") >= 10
    assert {q["language"] for q in queries} == {"en", "es"}
    answerable = [q for q in queries if q["kind"] in {"exact", "paraphrase"}]
    assert {q["domain"] for q in answerable} == {"technical", "hr"}
    assert {q["category"] for q in queries if q["kind"] == "unanswerable"} == {
        "out_of_domain",
        "keyword_adjacent",
    }
    # Labels are complete for answerable cases and absent for unanswerable ones.
    for query in answerable:
        assert query["expected_answer"] and query["expected_document"], query["id"]
    for query in queries:
        if query["kind"] == "unanswerable":
            assert "expected_answer" not in query, query["id"]


def test_exact_short_acronym_question_matches_before_fts(kb):
    """'What is AI?' must be answered exactly even though FTS drops the 2-char token."""
    _client, store = kb
    spy = SpyStore(store)
    result = suggest(spy, "What is AI?")
    assert spy.find_matches_calls == 0, "exact matching must run before FTS candidate search"
    assert result["match_type"] == "exact_qa"
    assert result["answer"] == (
        "Artificial intelligence is software that performs tasks that typically require human intelligence."
    )
    assert result["source"]["document_name"] == "synthetic-technical-en.md"
    # Provenance preserved: the exact stored line of the question.
    content = (KB_DIR / "synthetic-technical-en.md").read_text(encoding="utf-8")
    line = content[:content.index("Q: What is AI?")].count("\n") + 1
    assert result["source"]["location"] == f"Línea {line}"


def test_exact_question_outside_fts_candidate_top20(kb):
    """Crowded same-keyword fixture: the exact entry sits beyond the bounded top20."""
    _client, store = kb
    query = next(q for q in load_queries() if q["id"] == "exact-en-crowded")
    candidates = store.find_matches(query["query"])
    assert len(candidates) >= 20, "crowded fixture must fill the candidate bound"
    top20_answers = {row["answer"] for row in candidates[:20]}
    assert query["expected_answer"] not in top20_answers, (
        "dataset precondition: labeled exact entry must be outside FTS top20"
    )
    result = suggest(store, query["query"])
    assert result["match_type"] == "exact_qa"
    assert is_correct_source(result, query)


def test_exact_qa_priority_for_every_exact_label(kb):
    _client, store = kb
    exact_queries = [q for q in load_queries() if q["kind"] == "exact"]
    assert len(exact_queries) >= 15
    for query in exact_queries:
        spy = SpyStore(store)
        result = suggest(spy, query["query"])
        assert spy.find_matches_calls == 0, query["id"]
        assert result["match_type"] == "exact_qa", query["id"]
        assert is_correct_source(result, query), query["id"]


def test_suggest_live_exact_only_policy(kb):
    """Automatic Live answers only exact normalized Q&A; everything else abstains."""
    _client, store = kb
    queries = load_queries()
    exact = [q for q in queries if q["kind"] == "exact"]
    paraphrase = [q for q in queries if q["kind"] == "paraphrase"]
    unanswerable = [q for q in queries if q["kind"] == "unanswerable"]
    refused = {"status": "no_evidence", "answer": None, "source": None, "match_type": None}
    assert (len(queries), len(exact), len(paraphrase), len(unanswerable)) == (37, 17, 10, 10)

    for query in exact:
        result = suggest_live(store, query["query"])
        assert result["status"] == "found", query["id"]
        assert result["match_type"] == "exact_qa", query["id"]
        assert is_correct_source(result, query), query["id"]
    # No similar-question or document-excerpt fallback: paraphrases and labeled
    # unanswerables must produce the explicit abstention, not a near match.
    automatic_unsupported = 0
    for query in paraphrase + unanswerable:
        result = suggest_live(store, query["query"])
        automatic_unsupported += query["kind"] == "unanswerable" and result["status"] == "found"
        assert result == refused, query["id"]
    # The automatic path never consults FTS candidates at all.
    spy = SpyStore(store)
    assert suggest_live(spy, paraphrase[0]["query"]) == refused
    assert spy.find_matches_calls == 0

    coverage = len(exact) / (len(exact) + len(paraphrase))
    print(
        "\nLIVE_POLICY "
        + json.dumps(
            {
                "exact_answered": len(exact),
                "paraphrases_abstained": len(paraphrase),
                "unanswerable_refused": len(unanswerable),
                "automatic_coverage": round(coverage, 4),
                "automatic_unsupported_answer_rate": automatic_unsupported / len(unanswerable),
            },
            sort_keys=True,
        )
    )
    assert coverage == 17 / 27
    # Manual /answers behavior is unchanged: paraphrases still resolve via FTS.
    for query in paraphrase:
        assert suggest(store, query["query"])["status"] == "found", query["id"]


def test_duplicate_normalized_questions_first_insertion_wins(tmp_path):
    """Duplicate normalized Q&A resolve deterministically to the first insert."""
    store = KnowledgeStore(tmp_path)
    first = store.import_document(
        "first.md",
        b"first document",
        [ParsedEntry("qa", "What is caching?", "Caching stores copies to reduce latency.", "", "Línea 1")],
    )
    store.import_document(
        "second.md",
        b"second document",
        [ParsedEntry("qa", "what IS caching?!", "Second duplicate answer.", "", "Línea 1")],
    )
    result = suggest(store, "What is caching?")
    assert result["match_type"] == "exact_qa"
    assert result["answer"] == "Caching stores copies to reduce latency."
    assert result["source"] == {"document_id": first["id"], "document_name": "first.md", "location": "Línea 1"}
    assert suggest(store, "what is CACHING") == result


def test_punctuation_only_questions_never_match(tmp_path):
    """Empty normalization cannot collide with a punctuation-only stored question."""
    store = KnowledgeStore(tmp_path)
    store.import_document(
        "punct.md",
        b"punctuation only",
        [ParsedEntry("qa", "?!", "Punctuation answer.", "", "Línea 1")],
    )
    assert suggest(store, "What is caching?")["status"] == "no_evidence"
    for query in ("?!", "???", "..."):
        assert suggest_live(store, query)["status"] == "no_evidence", query
        assert suggest(store, query)["status"] == "no_evidence", query


def test_measured_retrieval_metrics(kb):
    """Prints measured rates; floors are loose regression guards, not quality claims."""
    _client, store = kb
    queries = load_queries()
    answerable = [q for q in queries if q["kind"] in {"exact", "paraphrase"}]
    unanswerable = [q for q in queries if q["kind"] == "unanswerable"]

    top1 = {"exact": 0, "paraphrase": 0}
    recall5 = 0
    reciprocal_rank = 0.0
    unsupported = {"out_of_domain": 0, "keyword_adjacent": 0}
    for query in answerable:
        if is_correct_source(suggest(store, query["query"]), query):
            top1[query["kind"]] += 1
        # Candidate-only metric: correct entry among the first 5 FTS candidates.
        candidates = store.find_matches(query["query"])
        ranks = [
            rank
            for rank, row in enumerate(candidates[:20], start=1)
            if row["answer"] == query["expected_answer"]
        ]
        if ranks and ranks[0] <= 5:
            recall5 += 1
        if ranks:
            reciprocal_rank += 1 / ranks[0]
    for query in unanswerable:
        if suggest(store, query["query"])["status"] == "found":
            unsupported[query["category"]] += 1

    n_answerable = len(answerable)
    n_unanswerable = len(unanswerable)
    exact_total = sum(1 for q in answerable if q["kind"] == "exact")
    paraphrase_total = sum(1 for q in answerable if q["kind"] == "paraphrase")
    metrics = {
        "answerable_cases": n_answerable,
        "exact_cases": exact_total,
        "paraphrase_cases": paraphrase_total,
        "unanswerable_cases": n_unanswerable,
        "top1_correct_source_rate": round(sum(top1.values()) / n_answerable, 4),
        "exact_top1_correct_source_rate": round(top1["exact"] / exact_total, 4),
        "paraphrase_top1_correct_source_rate": round(top1["paraphrase"] / paraphrase_total, 4),
        "fts_candidate_recall_at_5": round(recall5 / n_answerable, 4),
        "fts_candidate_mrr": round(reciprocal_rank / n_answerable, 4),
        "unsupported_answer_rate": round(sum(unsupported.values()) / n_unanswerable, 4),
        "unsupported_by_category": unsupported,
    }
    print("\nRETRIEVAL_METRICS " + json.dumps(metrics, sort_keys=True))

    # Hard contract: every exact question is answered from the right source.
    assert top1["exact"] == exact_total
    # Loose regression guards (not tuned targets; measured values are printed
    # above and recorded in docs/live-pipeline-validation.md).
    assert sum(top1.values()) / n_answerable >= 0.85
    assert top1["paraphrase"] / paraphrase_total >= 0.5
    assert recall5 / n_answerable >= 0.5
    assert reciprocal_rank / n_answerable >= 0.4


def test_unanswerable_refusal_and_no_fabricated_answers(kb):
    _client, store = kb
    queries = load_queries()
    with store.connection() as db:
        stored_answers = {row[0] for row in db.execute("SELECT answer FROM entries")}
    assert stored_answers, "fixture knowledge base must be populated"

    for query in queries:
        result = suggest(store, query["query"])
        if result["status"] == "found":
            # Grounding contract: never fabricated — the literal stored answer
            # must exist verbatim in the local knowledge base, with a source.
            assert result["answer"] in stored_answers, query["id"]
            assert result["match_type"] in {"exact_qa", "similar_qa", "document_excerpt"}, query["id"]
            assert result["source"]["document_name"], query["id"]
        elif query["kind"] != "unanswerable":
            pytest.fail(f"answerable labeled query was refused: {query['id']}")

    # Out-of-domain questions must be refused outright (no evidence, no answer).
    out_of_domain = [q for q in queries if q.get("category") == "out_of_domain"]
    assert len(out_of_domain) >= 5
    for query in out_of_domain:
        result = suggest(store, query["query"])
        assert result["status"] == "no_evidence", query["id"]
        assert result["answer"] is None and result["source"] is None, query["id"]


def test_local_retrieval_latency_percentiles(kb):
    """p50/p95 of local suggest() over the labeled set via perf_counter."""
    _client, store = kb
    queries = [q["query"] for q in load_queries()]
    for query in queries:  # warm-up: exclude first-touch SQLite page-cache effects
        suggest(store, query)
    samples = []
    for _ in range(3):
        for query in queries:
            start = time.perf_counter()
            suggest(store, query)
            samples.append(time.perf_counter() - start)
    samples.sort()
    p50 = statistics.quantiles(samples, n=100, method="inclusive")[49]
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    print(
        f"\nRETRIEVAL_LATENCY samples={len(samples)} "
        f"p50_ms={p50 * 1000:.3f} p95_ms={p95 * 1000:.3f}"
    )
    # Generous local-SQLite regression guard, not an SLA or a tuned target.
    assert p95 < 0.5


def test_deleting_all_synthetic_documents_removes_db_fts_disk_and_sources(kb):
    client, store = kb
    documents = client.get("/documents").json()["documents"]
    assert len(documents) == 5
    for document in documents:
        assert client.delete("/documents/" + document["id"]).status_code == 200
    assert client.get("/documents").json()["documents"] == []

    with store.connection() as db:
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("documents", "entries", "entry_fts", "entry_fts_docsize")
        }
    assert counts == {"documents": 0, "entries": 0, "entry_fts": 0, "entry_fts_docsize": 0}
    assert list(store.files_dir.iterdir()) == [], "raw file must be removed from disk"

    for query in load_queries():
        result = suggest(store, query["query"])
        assert result["status"] == "no_evidence", query["id"]
        assert result["source"] is None and result["answer"] is None, query["id"]
        automatic = suggest_live(store, query["query"])
        assert automatic["status"] == "no_evidence", query["id"]
        assert automatic["source"] is None and automatic["answer"] is None, query["id"]
