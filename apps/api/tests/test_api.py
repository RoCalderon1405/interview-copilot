"""Real integration tests: SQLite, FTS5, uploads, deletion and practice sessions."""
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from reportlab.pdfgen.canvas import Canvas

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        yield c


def upload(client, name, payload):
    return client.post("/documents", files={"file": (name, payload, "application/octet-stream")})


def xlsx_file():
    book = Workbook()
    sheet = book.active
    sheet.title = "Security"
    sheet.append(["Question", "Answer"])
    sheet.append(["What is authentication?", "Authentication verifies identity."])
    sheet.append(["What is authorization?", "Authorization determines permissions."])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def test_excel_exact_match_source_and_delete(client):
    # Reuse the exact same bytes: openpyxl ZIP output can include a new
    # timestamp on each call, so regenerating would change the SHA-256 and the
    # duplicate check would (correctly) treat it as a different document.
    payload = xlsx_file()
    uploaded = upload(client, "security.xlsx", payload)
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["entry_count"] == 2
    result = client.post("/answers", json={"question": "What is authentication?"}).json()
    assert result["match_type"] == "exact_qa"
    assert result["answer"] == "Authentication verifies identity."
    assert "fila 2" in result["source"]["location"]
    duplicate = upload(client, "security.xlsx", payload)
    assert duplicate.status_code == 409
    assert client.delete("/documents/" + uploaded.json()["id"]).status_code == 200
    assert client.post("/answers", json={"question": "What is authentication?"}).json()["status"] == "no_evidence"


def test_practice_questions_and_feedback(client):
    upload(client, "security.xlsx", xlsx_file())
    session = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    question = client.post(f"/sessions/{session}/next")
    assert question.status_code == 200
    assert "answer" not in question.json()
    assert client.post(f"/sessions/{session}/next").status_code == 409
    feedback = client.post(f"/sessions/{session}/evaluate", json={"answer": "Authentication verifies identity"})
    assert feedback.status_code == 200
    assert feedback.json()["method"] == "keyword_coverage_only"
    assert "expected_answer" in feedback.json()
    assert feedback.json()["assessment"]["status"] == "not_assessed"
    assert feedback.json()["assessment"]["total_score"] is None
    assert client.get(f"/sessions/{session}").json()["completed_questions"] == 1


def test_text_markdown_docx_pdf_and_unsupported(client):
    assert upload(client, "qa.md", b"Q: What is OAuth?\nA: OAuth is an authorization framework.").status_code == 201
    assert client.post("/answers", json={"question": "What is OAuth?"}).json()["status"] == "found"
    doc = Document()
    doc.add_paragraph("Dependency injection provides external dependencies to components.")
    buffer = io.BytesIO()
    doc.save(buffer)
    assert upload(client, "guide.docx", buffer.getvalue()).status_code == 201
    pdf = io.BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(70, 700, "Unit testing verifies isolated components")
    canvas.save()
    assert upload(client, "notes.pdf", pdf.getvalue()).status_code == 201
    assert upload(client, "tips.txt", b"Kubernetes coordinates container deployment.").status_code == 201
    assert upload(client, "bad.exe", b"binary").status_code == 415
    assert len(client.get("/documents").json()["documents"]) == 4


def test_no_evidence_and_malformed_upload(client):
    assert client.post("/answers", json={"question": "Explain interstellar navigation"}).json()["status"] == "no_evidence"
    assert upload(client, "empty.txt", b"").status_code == 422
    assert upload(client, "fake.xlsx", b"not a zip").status_code == 422
    assert upload(client, "fake.pdf", b"not a pdf").status_code == 422


def test_cross_origin_upload_denied(client):
    result = client.post('/documents', files={'file': ('question.txt', b'Q: test?\nA: test')}, headers={'Origin': 'https://random-site.example'})
    assert result.status_code == 403


def test_answer_from_rephrased_question(client):
    upload(client, 'security.xlsx', xlsx_file())
    result = client.post('/answers', json={'question': 'Could you explain authentication?'}).json()
    assert result['status'] == 'found'
    assert result['answer'] == 'Authentication verifies identity.'


def test_spanish_labeled_excel_columns(client):
    workbook = Workbook()
    ws = workbook.active
    ws.title = 'Entrevistas'
    ws.append(['Categoría', 'Pregunta (ES)', 'Respuesta (EN)'])
    ws.append(['Security', '¿Qué significa JWT?', 'JWT stands for JSON Web Token.'])
    stream = io.BytesIO()
    workbook.save(stream)
    result = upload(client, 'preguntas.xlsx', stream.getvalue())
    assert result.status_code == 201
    found = client.post('/answers', json={'question': '¿Qué significa JWT?'}).json()
    assert found['answer'] == 'JWT stands for JSON Web Token.'


def test_docx_qa_table(client):
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for left, right in [('Pregunta', 'Respuesta'), ('What is CORS?', 'CORS is a browser security mechanism.')]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = left, right
    stream = io.BytesIO()
    doc.save(stream)
    assert upload(client, 'table.docx', stream.getvalue()).status_code == 201
    found = client.post('/answers', json={'question': 'What is CORS?'}).json()
    assert found['answer'] == 'CORS is a browser security mechanism.'


def test_practice_report_and_session_close(client):
    assert upload(client, 'security.xlsx', xlsx_file()).status_code == 201
    sid = client.post('/sessions', json={'mode': 'practice'}).json()['id']
    question = client.post(f'/sessions/{sid}/next').json()
    assert client.post(f'/sessions/{sid}/finish').status_code == 409
    reference = {
        'What is authentication?': 'Authentication verifies identity.',
        'What is authorization?': 'Authorization determines permissions.',
    }
    response = client.post(f'/sessions/{sid}/evaluate', json={'answer': reference[question['question']]})
    assert response.status_code == 200
    result = client.post(f'/sessions/{sid}/finish')
    assert result.status_code == 200
    body = result.json()
    assert body['finished'] is True
    assert body['coverage_score'] == 100
    assert body['answered_questions'] == 1
    assert body['areas_to_improve'] == []
    assert 'Not a technical accuracy' in body['warning']
    assert body['questions'][0]['source']['document_name'] == 'security.xlsx'
    assert body['assessment']['total_score'] is None
    assert body['questions'][0]['assessment']['status'] == 'not_assessed'
    assert client.get(f'/sessions/{sid}/report').json() == body
    assert client.post(f'/sessions/{sid}/next').status_code == 409
    assert client.post(f'/sessions/{sid}/evaluate', json={'answer': 'test'}).status_code == 409


def test_missing_concepts_report_and_unscored_live(client):
    upload(client, 'security.xlsx', xlsx_file())
    sid = client.post('/sessions', json={'mode': 'practice'}).json()['id']
    client.post(f'/sessions/{sid}/next')
    client.post(f'/sessions/{sid}/evaluate', json={'answer': 'I do not know'})
    body = client.get(f'/sessions/{sid}/report').json()
    assert body['coverage_score'] == 0
    assert body['areas_to_improve']
    assert body['recommendations']
    empty_sid = client.post('/sessions', json={'mode': 'practice'}).json()['id']
    no_answers = client.post(f'/sessions/{empty_sid}/finish').json()
    assert no_answers['coverage_score'] is None
    live_sid = client.post('/sessions', json={'mode': 'live'}).json()['id']
    live = client.post(f'/sessions/{live_sid}/finish').json()
    assert live['coverage_score'] is None
    assert live['method'] == 'not_scored'
    assert client.get('/sessions/not-found/report').status_code == 404
