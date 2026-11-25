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


def test_cross_language_excel_headers_are_rejected_without_importing_a_mispaired_answer(client):
    workbook = Workbook()
    ws = workbook.active
    ws.title = 'Entrevistas'
    ws.append(['Categoría', 'Pregunta (ES)', 'Respuesta (EN)'])
    ws.append(['Security', '¿Qué significa JWT?', 'JWT stands for JSON Web Token.'])
    stream = io.BytesIO()
    workbook.save(stream)
    result = upload(client, 'preguntas.xlsx', stream.getvalue())
    assert result.status_code == 422
    assert 'matching language labels' in result.json()['detail']
    assert client.get('/documents').json()['documents'] == []


def bilingual_xlsx_file():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Entrevistas'
    # Non-adjacent columns must be paired by declared language, not first Q/first A.
    sheet.append(['Pregunta (ES)', 'Question (EN)', 'Respuesta (ES)', 'Answer (EN)'])
    sheet.append(['¿Qué es autorización?', 'What is authorization?',
                  'La autorización controla permisos.', 'Authorization controls permissions.'])
    sheet.append(['¿Qué es un decorator?', 'What is a decorator?',
                  'Un decorator puede comprobar autorización.', 'A decorator can check authorization.'])
    sheet.append(['¿Qué es SQL?', 'What is SQL?', 'SQL permite consultar datos.', None])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_bilingual_excel_import_preserves_all_complete_pairs_original_file_and_provenance(client):
    from app.parsers import parse_file

    payload = bilingual_xlsx_file()
    entries = parse_file('bank.xlsx', payload)
    assert [(entry.question, entry.answer, entry.language) for entry in entries[:2]] == [
        ('¿Qué es autorización?', 'La autorización controla permisos.', 'es'),
        ('What is authorization?', 'Authorization controls permissions.', 'en'),
    ]
    assert len(entries) == 5  # The empty English answer must not borrow Spanish wording.
    assert entries[0].location == "Hoja 'Entrevistas' · fila 2 · columnas A/C · ES"
    assert entries[1].location == "Hoja 'Entrevistas' · fila 2 · columnas B/D · EN"
    imported = upload(client, 'bank.xlsx', payload)
    assert imported.status_code == 201 and imported.json()['entry_count'] == 5
    store = client.app.state.store
    assert (store.files_dir / (imported.json()['id'] + '.xlsx')).read_bytes() == payload
    assert upload(client, 'renamed.xlsx', payload).status_code == 409
    with store.connection() as db:
        assert [row[0] for row in db.execute('SELECT language FROM entries ORDER BY id')] == ['es', 'en', 'es', 'en', 'es']
    status = client.get('/semantic/status').json()
    assert status['questions'] == 5 and status['indexed'] == 0


def test_bilingual_documentary_answers_follow_query_not_interface_and_refuse_missing_language(client):
    from app.retrieval import suggest_live

    legacy = upload(client, 'legacy.md', b'Q: What is authorization?\nA: La autorizacion controla permisos.')
    assert legacy.status_code == 201
    assert upload(client, 'bank.xlsx', bilingual_xlsx_file()).status_code == 201
    for query, language, expected, match_type in [
        ('What is authorization?', 'en', 'Authorization controls permissions.', 'exact_qa'),
        ('que es autorización', 'es', 'La autorización controla permisos.', 'exact_qa'),
        ('Could you explain authorization?', 'en', 'Authorization controls permissions.', 'similar_qa'),
        ('Explica la autorización', 'es', 'La autorización controla permisos.', 'similar_qa'),
    ]:
        response = client.post('/answers', json={'question': query},
                               headers={'Accept-Language': 'es' if language == 'en' else 'en'})
        result = response.json()
        assert result['answer'] == expected and result['match_type'] == match_type
        assert result['source']['language'] == language
        assert result['source']['document_name'] == 'bank.xlsx'
        assert 'fila 2' in result['source']['location'] and language.upper() in result['source']['location']
        if match_type == 'exact_qa':
            assert suggest_live(client.app.state.store, query)['answer'] == expected
    for query in ['What is SQL?', 'Could you explain SQL?', 'SQL']:
        assert client.post('/answers', json={'question': query}).json()['status'] == 'no_evidence'
        assert suggest_live(client.app.state.store, query)['status'] == 'no_evidence'
    with client.app.state.store.connection() as db:
        old = db.execute('SELECT answer,language FROM entries WHERE document_id=?', (legacy.json()['id'],)).fetchone()
        assert old['answer'] == 'La autorizacion controla permisos.' and old['language'] is None


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
