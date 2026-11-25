"""Deterministic, source-grounded retrieval. LLM and embeddings are later adapters."""
from __future__ import annotations

from difflib import SequenceMatcher

from .application.ports import RetrievalReader
from .domain.language import matches_question_language, question_language
from .domain.text import STOPWORDS as STOPWORDS  # Preserve the public retrieval import.
from .textnorm import normalize  # re-exported: retrieval.normalize stays importable


# Local to manual Q&A matching: do not change FTS selection, Practice scoring or Live normalization.
_QUESTION_BOILERPLATE = frozenset({
    "explain", "describe", "define", "tell", "please", "actually", "about", "work", "works",
    "explica", "explicame", "explicar", "dime", "puedes", "podrias", "favor", "funciona", "funcionan",
})


def _question_terms(text: str) -> list[str]:
    """Keep normalized question-topic terms, excluding generic EN/ES request wording."""
    return [term for term in normalize(text).split() if term not in STOPWORDS and term not in _QUESTION_BOILERPLATE]


def overlap(left: str, right: str) -> float:
    a = {x for x in normalize(left).split() if x not in STOPWORDS}
    b = {x for x in normalize(right).split() if x not in STOPWORDS}
    if not a or not b:
        return 0
    return len(a & b) / max(1, len(a))


def _exact_qa(store: RetrievalReader, question: str) -> dict | None:
    """Return the stored literal Q&A only when its normalized question matches exactly."""
    row = store.find_exact_qa(question)
    if row is None:
        return None
    # An unambiguous exact source question establishes its declared language even
    # when heuristic request-word detection abstains. Storage resolves collisions.
    labelled_exact = row.get("language") in {"es", "en"} and normalize(row.get("question", "")) == normalize(question)
    if not labelled_exact and not matches_question_language(question, row.get("question", question), row.get("language")):
        return None
    return {
        "status": "found",
        "answer": row["answer"],
        "source": _document_source(row),
        "match_type": "exact_qa",
        "note": "Stored answer from your document",
    }


def _document_source(row: dict) -> dict:
    """Return original provenance; never infer a source-language label from UI or query text."""
    source = {"document_id": row["document_id"], "document_name": row["document_name"], "location": row["location"]}
    if row.get("language") is not None:
        source["language"] = row["language"]
    return source


def suggest(store: RetrievalReader, question: str) -> dict:
    """Answer from the stored literal Q&A when the question matches exactly.

    The normalized exact match runs BEFORE the bounded FTS candidate search:
    FTS drops very short tokens (e.g. "AI") and the 20-candidate bound can
    crowd out an exact question, so detecting exactness only after retrieval
    would not guarantee exact-Q&A priority. Falls back to FTS candidates with
    lexical scoring; similar Q&A require a shared question-topic term before
    scoring. Answer-only FTS hits and boilerplate cannot establish relevance.
    Never generates or invents answer text.
    """
    exact = _exact_qa(store, question)
    if exact:
        return exact

    entries = store.find_matches(question)
    if not entries:
        return {"status": "no_evidence", "answer": None, "source": None, "match_type": None}

    query_terms = _question_terms(question)
    query_topics = set(query_terms)

    def quality(row: dict) -> float:
        if row["kind"] == "qa":
            if not matches_question_language(question, row["question"], row.get("language")):
                return 0.0
            target_terms = _question_terms(row["question"])
            shared = query_topics & set(target_terms)
            if not shared:
                return 0.0
            coverage = len(shared) / len(query_topics)
            similarity = SequenceMatcher(None, " ".join(query_terms), " ".join(target_terms)[:500]).ratio()
            return 0.55 * coverage + 0.45 * similarity + 0.08
        # Fragments remain explicitly labeled excerpts, with their existing scoring.
        similarity = SequenceMatcher(None, normalize(question), normalize(row["body"][:500])).ratio()
        return 0.55 * overlap(question, row["body"]) + 0.45 * similarity

    scored = [(quality(row), row) for row in entries]
    eligible = [(score, row) for score, row in scored if score >= 0.3]
    if not eligible:
        return {"status": "no_evidence", "answer": None, "source": None, "match_type": None}
    language = question_language(question)
    _, best = max(eligible, key=lambda item: (language is not None and item[1].get("language") == language, item[0]))
    is_qa = best["kind"] == "qa"
    # Exact matches already returned above; anything here is similar or an excerpt.
    return {
        "status": "found",
        "answer": best["answer"] if is_qa else best["body"],
        "source": _document_source(best),
        "match_type": "similar_qa" if is_qa else "document_excerpt",
        "note": "Stored answer from your document" if is_qa else "Original document excerpt; not an AI-generated answer",
    }


def suggest_live(store: RetrievalReader, question: str, semantic=None) -> dict:
    """Live: exact answer first, then an explicitly labeled semantic candidate.

    A semantic match is never presented as verified Q&A. With no local model or
    indexed vectors, the previous exact-only behavior remains unchanged.
    """
    exact = _exact_qa(store, question)
    if exact:
        return exact
    if semantic is not None:
        candidate = semantic.candidate(question)
        if candidate is not None:
            return candidate
    return {"status": "no_evidence", "answer": None, "source": None, "match_type": None}


def build_assessment() -> dict:
    """Explicit not-assessed contract for every rubric dimension.

    The only implemented evaluator is a lexical keyword-coverage proxy, so it
    can report no dimension score and no overall/weighted technical grade.
    Coverage numbers must never be copied into this object; a validated
    evaluator with evidence will replace the reasons later.
    """
    return {
        "status": "not_assessed",
        "total_score": None,
        "evaluator": {"id": "lexical_keyword_coverage", "version": "0.1.2"},
        "reason": (
            "Keyword coverage is a lexical proxy and cannot validate any "
            "assessment dimension."
        ),
        "dimensions": [
            {
                "name": name,
                "status": "not_assessed",
                "score": None,
                "reason": reason,
            }
            for name, reason in (
                ("technical_accuracy", "Lexical overlap cannot verify factual correctness against the reference answer."),
                ("completeness", "Keyword presence does not establish conceptual completeness."),
                ("clarity_structure", "Text overlap does not measure organization or logical flow."),
                ("practical_examples", "Coverage cannot confirm a correct, non-invented example."),
                ("relevance", "Coverage cannot judge whether the answer addresses the question."),
                ("communication_quality", "Coverage cannot assess grammar or vocabulary in the chosen language."),
                ("pronunciation", "Pronunciation requires validated audio evidence and is never inferred from text."),
            )
        ],
    }


def assess_answer(actual: str, expected: str) -> dict:
    """Keyword feedback is an approximation, never a semantic or language grade."""
    terms = [t for t in normalize(expected).split() if len(t) >= 4 and t not in STOPWORDS]
    actual_terms = set(normalize(actual).split())
    distinct = list(dict.fromkeys(terms))
    matched = [term for term in distinct if term in actual_terms]
    coverage = len(matched) / len(distinct) if distinct else 0
    score = round(coverage * 100)
    return {
        "score": score,
        "method": "keyword_coverage_only",
        "feedback": "This is a basic keyword-coverage estimate, not an AI or spoken-English evaluation.",
        "missing_concepts": [term for term in distinct if term not in actual_terms][:6],
        "assessment": build_assessment(),
    }


def build_session_report(session: dict, reviews: list[dict]) -> dict:
    """Summarize keyword coverage without mislabeling it as an interview-grade assessment.

    The v0.1 evaluator cannot assess technical correctness, speaking, or pronunciation;
    reporting those dimensions as scores would fabricate capabilities.
    """
    answered = len(reviews)
    score = round(sum(item["score"] for item in reviews) / answered) if answered else None
    missing_counts: dict[str, int] = {}
    questions = []
    for review in reviews:
        analysis = assess_answer(review["actual_answer"], review["expected_answer"])
        for concept in analysis["missing_concepts"]:
            missing_counts[concept] = missing_counts.get(concept, 0) + 1
        questions.append({
            "question": review["question"],
            "coverage_score": review["score"],
            "missing_concepts": analysis["missing_concepts"],
            "source": {"document_name": review["document_name"], "location": review["location"]},
            "assessment": analysis["assessment"],
        })
    top_missing = [name for name, _ in sorted(missing_counts.items(), key=lambda kv: (-kv[1], kv[0]))][:8]
    suggestions = (
        ["Review these concepts in your source material: " + ", ".join(top_missing) + "."]
        if top_missing else (["Keep practicing with new questions and concrete examples."] if answered else [])
    )
    return {
        "session_id": session["id"],
        "mode": session["mode"],
        "finished": bool(session["finished_at"]),
        "answered_questions": answered,
        "coverage_score": score if session["mode"] == "practice" else None,
        "method": "keyword_coverage_only" if session["mode"] == "practice" and answered else "not_scored",
        "assessment": build_assessment(),
        "warning": (
            "Keyword overlap with stored answers only. Not a technical accuracy, fluency, "
            "pronunciation, communication or overall interview grade."
        ) if answered else "No assessable responses were recorded; no score is available.",
        "areas_to_improve": top_missing if session["mode"] == "practice" else [],
        "recommendations": suggestions if session["mode"] == "practice" else [],
        "questions": questions if session["mode"] == "practice" else [],
    }
