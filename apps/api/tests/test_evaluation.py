"""Synthetic EN/ES contract tests for the explicit not-assessed evaluation object.

These tests prove contract groundwork only: the lexical keyword-coverage proxy
never fabricates a technical, communication or overall grade. They are NOT
semantic-evaluator calibration validation.
"""
import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import create_app
from app.retrieval import assess_answer

DIMENSIONS = [
    "technical_accuracy",
    "completeness",
    "clarity_structure",
    "practical_examples",
    "relevance",
    "communication_quality",
    "pronunciation",
]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        yield c


def upload(client, name, payload):
    return client.post("/documents", files={"file": (name, payload, "application/octet-stream")})


def xlsx_file():
    book = Workbook()
    sheet = book.active
    sheet.append(["Question", "Answer"])
    sheet.append(["What is authentication?", "Authentication verifies identity."])
    sheet.append(["What is authorization?", "Authorization determines permissions."])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def assert_not_assessed(assessment):
    """Shared contract: every dimension is explicitly not assessed, with a reason."""
    assert assessment["status"] == "not_assessed"
    assert assessment["total_score"] is None
    assert assessment["evaluator"]["id"]
    assert assessment["evaluator"]["version"]
    assert [d["name"] for d in assessment["dimensions"]] == DIMENSIONS
    for dimension in assessment["dimensions"]:
        assert dimension["status"] == "not_assessed"
        assert dimension["score"] is None
        assert dimension["reason"]


def test_identical_answer_en_is_never_a_technical_grade():
    analysis = assess_answer("Authentication verifies identity.", "Authentication verifies identity.")
    assert analysis["method"] == "keyword_coverage_only"
    assert analysis["score"] == 100  # legacy coverage contract preserved
    assert analysis["missing_concepts"] == []
    assert_not_assessed(analysis["assessment"])
    # Coverage must not be re-labelled as the assessment total.
    assert analysis["assessment"]["total_score"] != analysis["score"]


def test_paraphrase_en_stays_not_assessed():
    analysis = assess_answer(
        "Verifying who the user is defines authentication.",
        "Authentication verifies identity.",
    )
    assert_not_assessed(analysis["assessment"])


def test_contradiction_with_high_coverage_gets_no_technical_grade():
    # Same keywords as the reference but the opposite claim.
    analysis = assess_answer("Authentication never verifies identity.", "Authentication verifies identity.")
    assert analysis["score"] >= 90  # lexical overlap is high despite contradiction
    assert_not_assessed(analysis["assessment"])


def test_spanish_identical_and_paraphrase_stay_not_assessed():
    reference = "La autenticación verifica la identidad del usuario."
    identical = assess_answer(reference, reference)
    assert identical["score"] == 100
    assert_not_assessed(identical["assessment"])
    paraphrase = assess_answer("Verificar quién es el usuario forma parte de la autenticación.", reference)
    assert_not_assessed(paraphrase["assessment"])


def test_empty_answer_and_missing_reference_inputs():
    empty_answer = assess_answer("", "Authentication verifies identity.")
    assert empty_answer["score"] == 0
    assert_not_assessed(empty_answer["assessment"])
    no_reference = assess_answer("Authentication verifies identity.", "")
    assert no_reference["score"] == 0
    assert_not_assessed(no_reference["assessment"])


def test_evaluate_endpoint_exposes_assessment(client):
    upload(client, "security.xlsx", xlsx_file())
    sid = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    client.post(f"/sessions/{sid}/next")
    feedback = client.post(f"/sessions/{sid}/evaluate", json={"answer": "Authentication verifies identity."}).json()
    assert feedback["method"] == "keyword_coverage_only"  # legacy contract preserved
    assert "expected_answer" in feedback
    assert_not_assessed(feedback["assessment"])


def test_report_questions_expose_assessment_and_keep_sources(client):
    upload(client, "security.xlsx", xlsx_file())
    sid = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    question = client.post(f"/sessions/{sid}/next").json()
    reference = {
        "What is authentication?": "Authentication verifies identity.",
        "What is authorization?": "Authorization determines permissions.",
    }
    client.post(f"/sessions/{sid}/evaluate", json={"answer": reference[question["question"]]})
    body = client.post(f"/sessions/{sid}/finish").json()
    assert body["coverage_score"] == 100  # legacy report contract preserved
    assert_not_assessed(body["assessment"])
    entry = body["questions"][0]
    assert entry["question"] == question["question"]
    assert entry["source"]["document_name"] == "security.xlsx"
    assert_not_assessed(entry["assessment"])


def test_empty_and_live_reports_remain_unscored(client):
    empty_sid = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    empty = client.post(f"/sessions/{empty_sid}/finish").json()
    assert empty["coverage_score"] is None
    assert empty["method"] == "not_scored"
    assert empty["questions"] == []
    assert_not_assessed(empty["assessment"])

    live_sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
    live = client.post(f"/sessions/{live_sid}/finish").json()
    assert live["coverage_score"] is None
    assert live["method"] == "not_scored"
    assert live["questions"] == []
    assert_not_assessed(live["assessment"])


def test_repeated_finish_returns_identical_report(client):
    upload(client, "security.xlsx", xlsx_file())
    sid = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    question = client.post(f"/sessions/{sid}/next").json()
    reference = {
        "What is authentication?": "Authentication verifies identity.",
        "What is authorization?": "Authorization determines permissions.",
    }
    client.post(f"/sessions/{sid}/evaluate", json={"answer": reference[question["question"]]})
    first = client.post(f"/sessions/{sid}/finish")
    assert first.status_code == 200
    second = client.post(f"/sessions/{sid}/finish")
    assert second.status_code == 200
    assert second.json() == first.json()
    assert client.get(f"/sessions/{sid}/report").json() == first.json()


def test_deleted_source_report_never_leaks_answers(client):
    upload(client, "security.xlsx", xlsx_file())
    sid = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    client.post(f"/sessions/{sid}/next")
    private_note = "Authentication verifies identity. My private salary expectation is 90k."
    client.post(f"/sessions/{sid}/evaluate", json={"answer": private_note})
    doc_id = client.get("/documents").json()["documents"][0]["id"]
    assert client.delete(f"/documents/{doc_id}").status_code == 200
    body = client.post(f"/sessions/{sid}/finish").json()
    assert body["answered_questions"] == 0
    assert body["coverage_score"] is None
    assert "private salary" not in json.dumps(body)
    assert "verifies identity" not in json.dumps(body)
