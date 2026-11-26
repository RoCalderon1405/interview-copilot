"""Focused contracts for one-row supplemental preparation and offline apply."""
from __future__ import annotations

import hashlib
import io
import sqlite3
import sys
from array import array
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.bilingual_reprocess import HEADERS
from app.domain.knowledge import ParsedEntry
from app.incremental_supplement import SupplementError, apply_supplement, prepare_supplement
from app.parsers import parse_file
from app.retrieval import suggest, suggest_live
from app.semantic import MODEL
from app.store import KnowledgeStore

SHEET_NAMES = (
    "01 RH", "02 Python FastAPI", "03 TypeScript Backend", "04 Frontend",
    "05 Bases de Datos", "06 Arquitectura Cloud", "07 Testing Coding", "08 AI Engineering",
)
TARGET_SHEET = "06 Arquitectura Cloud"
TARGET_ROW = 45
CANDIDATE_ID = "MSG-012"
ES_QUESTION = "Explica un patrón de diseño para servicios"
EN_QUESTION = "Explain a design pattern for services"


def _add_candidate_row(sheet, *, es_question: str = ES_QUESTION, en_question: str = EN_QUESTION) -> None:
    values = [CANDIDATE_ID, "P1", "Arquitectura", es_question,
              "Respuesta revisada sintetica para el patron.", en_question,
              "Synthetic reviewed answer for the pattern.", "", "Revisión aprobada", "No"]
    for column, value in enumerate(values, 1):
        sheet.cell(row=TARGET_ROW, column=column, value=value)


def bilingual_bank(base: Path, *, with_vectors: bool = False, include_row_id: bool = False):
    """Create a synthetic 257-row bank with the documented 530 stored entries."""
    base.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    for number, name in enumerate(SHEET_NAMES):
        sheet = workbook.active if number == 0 else workbook.create_sheet()
        sheet.title = name
        sheet.append(["Synthetic interview bank"])
        sheet.append(["Context, not a Q&A"])
        sheet.append([])
        sheet.append(list(HEADERS))
        count = 211 if number == 0 else 40 if name == TARGET_SHEET else 1
        for index in range(count):
            key = f"{number}-{index}"
            sheet.append([key, "P1", "testing", f"Describe pruebas {key}", f"Respuesta sintetica {key}",
                          f"Describe testing {key}", f"Synthetic answer {key}", "", "", ""])
        if include_row_id and name == TARGET_SHEET:
            _add_candidate_row(sheet)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    payload = buffer.getvalue()
    parsed = parse_file("Full_Stack_Senior_Interview_Bank_ES_EN.xlsx", payload)
    store = KnowledgeStore(base / "data")
    document = store.import_document("Full_Stack_Senior_Interview_Bank_ES_EN.xlsx", payload, parsed)
    if with_vectors:
        session = store.create_session("practice")["id"]
        with store.connection() as db:
            ids = [row[0] for row in db.execute(
                "SELECT id FROM entries WHERE document_id=? AND kind='qa'", (document["id"],))]
            db.executemany("INSERT INTO qa_vectors VALUES (?,?,?,?)",
                           [(entry_id, MODEL, 2, array("f", [1, 0]).tobytes()) for entry_id in ids])
            db.execute("INSERT INTO semantic_index_state VALUES (?,?,'completed',NULL)", (document["id"], MODEL))
            db.execute("UPDATE sessions SET current_entry_id=? WHERE id=?", (ids[1], session))
            db.execute("INSERT INTO session_answers(session_id,entry_id,answer,score) VALUES (?,?,?,?)",
                       (session, ids[0], "Saved Practice", 85))
    return store, document, payload


def candidate_workbook(base: Path, bank_payload: bytes, *, es_question: str = ES_QUESTION,
                       en_question: str = EN_QUESTION) -> tuple[Path, bytes, str]:
    workbook = load_workbook(io.BytesIO(bank_payload))
    _add_candidate_row(workbook[TARGET_SHEET], es_question=es_question, en_question=en_question)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    payload = buffer.getvalue()
    path = base / "Full_Stack_Senior_Interview_Bank_ES_EN_rev2_MSG-012.xlsx"
    path.write_bytes(payload)
    return path, payload, hashlib.sha256(payload).hexdigest()


def snapshot(store: KnowledgeStore) -> dict[str, list[tuple]]:
    with store.connection() as db:
        return {
            table: [tuple(row) for row in db.execute(
                "SELECT rowid,* FROM entry_fts ORDER BY rowid" if table == "entry_fts"
                else f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("documents", "entries", "entry_fts", "qa_vectors",
                          "semantic_index_state", "sessions", "session_answers")
        }


class RaisingSemantic:
    def candidate(self, question: str) -> dict:
        raise AssertionError("Semantic retrieval must not run for exact matches")


def test_prepare_is_read_only_stable_and_apply_only_adds_the_supplement(tmp_path):
    store, document, bank_payload = bilingual_bank(tmp_path / "case", with_vectors=True)
    candidate_path, _, candidate_sha = candidate_workbook(tmp_path / "case", bank_payload)
    before = snapshot(store)
    output = tmp_path / "prepared"
    receipt = prepare_supplement(store.db_path, document["id"], candidate_path, output,
                                 expected_candidate_sha256=candidate_sha)
    assert snapshot(store) == before
    assert receipt["status"] == "prepared" and receipt["applied"] is False
    assert receipt["counts_before"]["entries"] == 530
    assert receipt["expected_counts_after"]["entries_after"] == 532
    assert receipt["expected_changes"] == {
        "documents": 1, "entries": 2, "entry_fts": 2, "qa_vectors": 0,
        "semantic_index_state": 0, "sessions": 0, "session_answers": 0,
    }
    assert receipt["supplement"]["languages"] == ["es", "en"]
    assert "SUPPLEMENT" in receipt["supplement"]["name"] and CANDIDATE_ID in receipt["supplement"]["name"]
    supplement_path = output / receipt["supplement"]["name"]
    assert supplement_path.is_file() and (output / "copilot.sqlite3").is_file()
    assert (output / "preparation.json").is_file()
    entries = parse_file(supplement_path.name, supplement_path.read_bytes())
    assert [(entry.language, entry.location) for entry in entries] == [
        ("es", f"Hoja '{TARGET_SHEET}' · fila {TARGET_ROW} · columnas D/E · ES"),
        ("en", f"Hoja '{TARGET_SHEET}' · fila {TARGET_ROW} · columnas F/G · EN"),
    ]
    second = prepare_supplement(store.db_path, document["id"], candidate_path, tmp_path / "prepared-again",
                                expected_candidate_sha256=candidate_sha)
    assert second["preview_token"] == receipt["preview_token"]

    applied = apply_supplement(store.db_path, output, receipt["preview_token"], backend_stopped=True)
    after = snapshot(store)
    assert applied["applied"] is True and applied["existing_state_preserved"] is True
    assert after["qa_vectors"] == before["qa_vectors"]
    assert after["semantic_index_state"] == before["semantic_index_state"]
    assert after["sessions"] == before["sessions"]
    assert after["session_answers"] == before["session_answers"]
    assert [row for row in after["documents"] if row[0] != applied["new_document_id"]] == before["documents"]
    assert [row for row in after["entries"] if row[1] != applied["new_document_id"]] == before["entries"]
    new_entry_ids = {row[0] for row in after["entries"] if row[1] == applied["new_document_id"]}
    assert [row for row in after["entry_fts"] if row[0] not in new_entry_ids] == before["entry_fts"]
    assert len(new_entry_ids) == 2
    new_document = next(row for row in after["documents"] if row[0] == applied["new_document_id"])
    assert new_document[1] == receipt["supplement"]["name"] and new_document[4] == 2
    assert (store.files_dir / (applied["new_document_id"] + ".xlsx")).read_bytes() == supplement_path.read_bytes()

    new_entries = [row for row in after["entries"] if row[1] == applied["new_document_id"]]
    for entry in new_entries:
        question, answer, location, language = entry[3], entry[4], entry[6], entry[7]
        for retrieve in (lambda text: suggest(store, text),
                         lambda text: suggest_live(store, text, semantic=RaisingSemantic())):
            result = retrieve(question)
            assert result["status"] == "found" and result["match_type"] == "exact_qa"
            assert result["answer"] == answer and result["source"]["location"] == location
            assert result["source"]["language"] == language
    status = store.semantic_documents(MODEL, applied["new_document_id"])[0]
    assert (status["questions"], status["indexed"], status["pending"], status["requested"]) == (2, 0, 2, False)

    current = snapshot(store)
    with pytest.raises(SupplementError):
        apply_supplement(store.db_path, output, receipt["preview_token"], backend_stopped=True)
    assert snapshot(store) == current
    with pytest.raises(SupplementError):
        prepare_supplement(store.db_path, document["id"], candidate_path, tmp_path / "prepared-refused",
                           expected_candidate_sha256=candidate_sha)


def test_prepare_refuses_changed_hashes_present_id_and_normalized_collision(tmp_path):
    store, document, payload = bilingual_bank(tmp_path / "hash")
    candidate, _, candidate_sha = candidate_workbook(tmp_path / "hash", payload)
    with pytest.raises(SupplementError, match="Candidate hash"):
        prepare_supplement(store.db_path, document["id"], candidate, tmp_path / "hash-out",
                           expected_candidate_sha256="0" * 64)

    drifted, drift_document, drift_payload = bilingual_bank(tmp_path / "drift")
    drift_candidate, _, drift_candidate_sha = candidate_workbook(tmp_path / "drift", drift_payload)
    original = drifted.files_dir / (drift_document["id"] + ".xlsx")
    original.write_bytes(original.read_bytes() + b"changed")
    with pytest.raises(SupplementError, match="hash"):
        prepare_supplement(drifted.db_path, drift_document["id"], drift_candidate, tmp_path / "drift-out",
                           expected_candidate_sha256=drift_candidate_sha)

    present, present_document, present_payload = bilingual_bank(tmp_path / "present", include_row_id=True)
    present_candidate, _, present_candidate_sha = candidate_workbook(tmp_path / "present", present_payload)
    with pytest.raises(SupplementError, match="already present"):
        prepare_supplement(present.db_path, present_document["id"], present_candidate, tmp_path / "present-out",
                           expected_candidate_sha256=present_candidate_sha)

    collision, collision_document, collision_payload = bilingual_bank(tmp_path / "collision")
    collision_candidate, _, collision_candidate_sha = candidate_workbook(tmp_path / "collision", collision_payload)
    collision.import_document("collision.md", b"collision", [
        ParsedEntry("qa", "EXPLICA UN PATRON DE DISENO PARA SERVICIOS", "Other answer", "", "Line 1", "es")])
    with pytest.raises(SupplementError, match="normalized exact question"):
        prepare_supplement(collision.db_path, collision_document["id"], collision_candidate,
                           tmp_path / "collision-out", expected_candidate_sha256=collision_candidate_sha)

    repeated, repeated_document, repeated_payload = bilingual_bank(tmp_path / "repeated")
    repeated_candidate, _, repeated_sha = candidate_workbook(
        tmp_path / "repeated", repeated_payload, en_question=ES_QUESTION)
    with pytest.raises(SupplementError, match="same text"):
        prepare_supplement(repeated.db_path, repeated_document["id"], repeated_candidate,
                           tmp_path / "repeated-out", expected_candidate_sha256=repeated_sha)

    invalid_candidate = tmp_path / "invalid-candidate.xlsx"
    invalid_candidate.write_bytes(b"not an office zip container")
    with pytest.raises(SupplementError, match="ZIP"):
        prepare_supplement(store.db_path, document["id"], invalid_candidate, tmp_path / "invalid-out",
                           expected_candidate_sha256=hashlib.sha256(invalid_candidate.read_bytes()).hexdigest())


def test_cli_requires_reviewed_candidate_hash(monkeypatch):
    from supplement_bilingual_xlsx import main

    monkeypatch.setattr(sys, "argv", [
        "supplement_bilingual_xlsx.py", "--database", "copilot.sqlite3",
        "--document-id", "0" * 32, "--candidate", "candidate.xlsx", "--output-dir", "prepared",
    ])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2


def test_apply_reports_committed_state_when_receipt_write_fails(tmp_path, monkeypatch):
    store, document, payload = bilingual_bank(tmp_path / "receipt")
    candidate, _, candidate_sha = candidate_workbook(tmp_path / "receipt", payload)
    output = tmp_path / "receipt-prepared"
    receipt = prepare_supplement(store.db_path, document["id"], candidate, output,
                                 expected_candidate_sha256=candidate_sha)
    original_write_text = Path.write_text

    def refuse_apply_receipt(self, *args, **kwargs):
        if self.name == "apply.json":
            raise OSError("Synthetic receipt failure")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse_apply_receipt)
    applied = apply_supplement(store.db_path, output, receipt["preview_token"], backend_stopped=True)
    assert applied["status"] == "applied" and applied["applied"] is True
    assert applied["apply_receipt"] is None
    assert "could not be written" in applied["receipt_warning"]
    assert applied["counts_after"]["documents"] == applied["counts_before"]["documents"] + 1
    assert (store.files_dir / (applied["new_document_id"] + ".xlsx")).is_file()


def test_apply_refuses_stale_token_and_failures_without_partial_writes(tmp_path, monkeypatch):
    stale, stale_document, stale_payload = bilingual_bank(tmp_path / "stale")
    stale_candidate, _, stale_sha = candidate_workbook(tmp_path / "stale", stale_payload)
    stale_out = tmp_path / "stale-prepared"
    stale_receipt = prepare_supplement(stale.db_path, stale_document["id"], stale_candidate, stale_out,
                                       expected_candidate_sha256=stale_sha)
    stale.import_document("unrelated.md", b"unrelated", [
        ParsedEntry("qa", "What is unrelated?", "Other original.", "", "Line 1", "en")])
    before_stale = snapshot(stale)
    with pytest.raises(SupplementError, match="stale"):
        apply_supplement(stale.db_path, stale_out, stale_receipt["preview_token"], backend_stopped=True)
    assert snapshot(stale) == before_stale

    broken, broken_document, broken_payload = bilingual_bank(tmp_path / "backup")
    broken_candidate, _, broken_sha = candidate_workbook(tmp_path / "backup", broken_payload)
    broken_out = tmp_path / "backup-prepared"
    broken_receipt = prepare_supplement(broken.db_path, broken_document["id"], broken_candidate, broken_out,
                                        expected_candidate_sha256=broken_sha)
    before_broken = snapshot(broken)

    def fail_backup(source, destination):
        raise OSError("Synthetic backup failure")

    monkeypatch.setattr("app.incremental_supplement._backup_database", fail_backup)
    with pytest.raises(OSError):
        apply_supplement(broken.db_path, broken_out, broken_receipt["preview_token"], backend_stopped=True)
    assert snapshot(broken) == before_broken
    monkeypatch.undo()

    database_failure, failure_document, failure_payload = bilingual_bank(tmp_path / "transaction")
    failure_candidate, _, failure_sha = candidate_workbook(tmp_path / "transaction", failure_payload)
    failure_out = tmp_path / "transaction-prepared"
    failure_receipt = prepare_supplement(database_failure.db_path, failure_document["id"], failure_candidate,
                                         failure_out, expected_candidate_sha256=failure_sha)
    with database_failure.connection() as db:
        db.execute("""CREATE TRIGGER refuse_new_pair BEFORE INSERT ON entries WHEN NEW.language='en'
            BEGIN SELECT RAISE(ABORT, 'Synthetic transaction failure'); END""")
    before_failure = snapshot(database_failure)
    documents_before = sorted(path.name for path in database_failure.files_dir.iterdir())
    with pytest.raises(sqlite3.IntegrityError):
        apply_supplement(database_failure.db_path, failure_out, failure_receipt["preview_token"],
                         backend_stopped=True)
    assert snapshot(database_failure) == before_failure
    assert sorted(path.name for path in database_failure.files_dir.iterdir()) == documents_before
