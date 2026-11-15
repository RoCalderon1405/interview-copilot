"""Deterministic, source-grounded retrieval. LLM and embeddings are later adapters."""
from __future__ import annotations

from difflib import SequenceMatcher

from .store import KnowledgeStore, STOPWORDS
from .textnorm import normalize  # re-exported: retrieval.normalize stays importable


def overlap(left: str, right: str) -> float:
    a = {x for x in normalize(left).split() if x not in STOPWORDS}
    b = {x for x in normalize(right).split() if x not in STOPWORDS}
    if not a or not b:
        return 0
    return len(a & b) / max(1, len(a))


def _exact_qa(store: KnowledgeStore, question: str) -> dict | None:
    """Return the stored literal Q&A only when its normalized question matches exactly."""
    row = store.find_exact_qa(question)
    if row is None:
        return None
    return {
        "status": "found",
        "answer": row["answer"],
        "source": {"document_id": row["document_id"], "document_name": row["document_name"], "location": row["location"]},
        "match_type": "exact_qa",
        "note": "Stored answer from your document",
    }


def suggest(store: KnowledgeStore, question: str) -> dict:
    """Answer from the stored literal Q&A when the question matches exactly.

    The normalized exact match runs BEFORE the bounded FTS candidate search:
    FTS drops very short tokens (e.g. "AI") and the 20-candidate bound can
    crowd out an exact question, so detecting exactness only after retrieval
    would not guarantee exact-Q&A priority. Falls back to FTS candidates with
    lexical scoring; never generates or invents answer text.
    """
    exact = _exact_qa(store, question)
    if exact:
        return exact

    entries = store.find_matches(question)
    if not entries:
        return {"status": "no_evidence", "answer": None, "source": None, "match_type": None}

    def quality(row: dict) -> float:
        target = row["question"] if row["kind"] == "qa" else row["body"]
        similarity = SequenceMatcher(None, normalize(question), normalize(target[:500])).ratio()
        coverage = overlap(question, target)
        return 0.55 * coverage + 0.45 * similarity + (0.08 if row["kind"] == "qa" else 0)

    best = max(entries, key=quality)
    score = quality(best)
    if score < 0.3:
        return {"status": "no_evidence", "answer": None, "source": None, "match_type": None}
    is_qa = best["kind"] == "qa"
    # Exact matches already returned above; anything here is similar or an excerpt.
    return {
        "status": "found",
        "answer": best["answer"] if is_qa else best["body"],
        "source": {"document_id": best["document_id"], "document_name": best["document_name"], "location": best["location"]},
        "match_type": "similar_qa" if is_qa else "document_excerpt",
        "note": "Stored answer from your document" if is_qa else "Original document excerpt; not an AI-generated answer",
    }


def suggest_live(store: KnowledgeStore, question: str, semantic=None) -> dict:
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
