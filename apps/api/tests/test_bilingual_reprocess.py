"""Focused safety contracts for the existing row-4, eight-sheet workbook repair."""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from array import array
from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.bilingual_reprocess import HEADERS, apply_reprocess, preview_reprocess
from app.domain.knowledge import ParsedEntry
from app.parsers import parse_file
from app.retrieval import suggest, suggest_live
from app.semantic import MODEL
from app.store import KnowledgeStore


def legacy_bank(tmp_path):
    workbook = Workbook()
    for number in range(8):
        sheet = workbook.active if number == 0 else workbook.create_sheet()
        sheet.title = f"Sheet {number + 1}"
        sheet.append(["Synthetic interview bank"])
        sheet.append(["Context, not a Q&A"])
        sheet.append([])
        sheet.append(list(HEADERS))
        for index in range(250 if number == 0 else 1):
            key = f"{number}-{index}"
            # Deliberately outside the request-word detector's vocabulary.
            sheet.append([key, "P1", "testing", f"Describe pruebas {key}", f"Respuesta original {key}",
                          f"Describe testing {key}", f"Original answer {key}", "", "", ""])
    data = io.BytesIO()
    workbook.save(data)
    # The actual bank omits optional worksheet dimensions. Keep the fixture
    # faithful so read-only max_row=None cannot break preview/apply again.
    dimensionless = io.BytesIO()
    with zipfile.ZipFile(data) as source, zipfile.ZipFile(dimensionless, 'w', zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename.startswith('xl/worksheets/sheet'):
                content = re.sub(rb'<dimension\b[^>]*/>', b'', content)
            target.writestr(item, content)
    payload = dimensionless.getvalue()
    parsed = parse_file("bank.xlsx", payload)
    old = [replace(entry, language=None, location=entry.location.split(" · columnas ")[0])
           for entry in parsed if entry.language != "en"]
    store = KnowledgeStore(tmp_path)
    document = store.import_document("bank.xlsx", payload, old)
    other = store.import_document("other.md", b"unrelated original", [
        ParsedEntry("qa", "What is unrelated?", "Other original.", "", "Line 1")])
    session = store.create_session("practice")["id"]
    with store.connection() as db:
        ids = [row[0] for row in db.execute("SELECT id FROM entries WHERE document_id=? AND kind='qa'", (document["id"],))]
        db.executemany("INSERT INTO qa_vectors VALUES (?,?,?,?)", [(entry_id, MODEL, 2, array('f', [1, 0]).tobytes()) for entry_id in ids])
        db.execute("INSERT INTO semantic_index_state VALUES (?,?,'completed',NULL)", (document["id"], MODEL))
        db.execute("UPDATE sessions SET current_entry_id=? WHERE id=?", (ids[1], session))
        db.execute("INSERT INTO session_answers(session_id,entry_id,answer,score) VALUES (?,?,?,?)", (session, ids[0], "Saved Practice", 85))
    return store, document, other, parsed


def snapshot(store):
    with store.connection() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("documents", "entries", "entry_fts", "qa_vectors", "sessions", "session_answers", "semantic_index_state")}


def test_preview_apply_preserves_ids_vectors_practice_originals_and_is_idempotent(tmp_path):
    store, document, other, parsed = legacy_bank(tmp_path)
    before = snapshot(store)
    preview = preview_reprocess(store.db_path, document["id"])
    assert (preview["qa_es"], preview["qa_en"], preview["qa_total"]) == (257, 257, 514)
    assert preview["entries_after"] == 530 and preview["context_fragments"] == 16
    assert preview["metadata_updates"] == preview["new_entries"] == 257
    assert preview["preserved_vectors_by_model"] == {MODEL: 257}
    assert preview["practice_answers_preserved"] == preview["current_practice_references_preserved"] == 1
    assert snapshot(store) == before and not (tmp_path / "reprocess-backups").exists()
    original = (store.files_dir / (document["id"] + ".xlsx")).read_bytes()
    result = apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    after = snapshot(store)
    assert after["qa_vectors"] == before["qa_vectors"]
    assert after["sessions"] == before["sessions"] and after["session_answers"] == before["session_answers"]
    assert {row[0] for row in before["entries"]} <= {row[0] for row in after["entries"]}
    assert len(after["documents"]) == 2
    assert [row for row in after["documents"] if row[0] == other["id"]] == [row for row in before["documents"] if row[0] == other["id"]]
    assert [row for row in after["entries"] if row[1] == other["id"]] == [row for row in before["entries"] if row[1] == other["id"]]
    assert (store.files_dir / (document["id"] + ".xlsx")).read_bytes() == original
    backup = Path(result["backup_directory"])
    assert (backup / (document["id"] + ".xlsx")).read_bytes() == original
    with sqlite3.connect(backup / "copilot.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == len(before["entries"])
    status = store.semantic_documents(MODEL, document["id"])[0]
    assert (status["questions"], status["indexed"], status["pending"], status["requested"]) == (514, 257, 257, False)
    for entry in parsed:
        if entry.kind == "qa":
            for retrieve in (suggest, suggest_live):
                answer = retrieve(store, entry.question)
                assert answer["match_type"] == "exact_qa" and answer["answer"] == entry.answer
                assert answer["source"]["language"] == entry.language and answer["source"]["location"] == entry.location
    again = preview_reprocess(store.db_path, document["id"])
    assert again["new_entries"] == again["metadata_updates"] == 0
    assert apply_reprocess(store.db_path, document["id"], again["preview_token"])["already_current"]
    assert snapshot(store) == after


def test_refuses_stale_preview_changed_source_and_changed_wording_without_partial_writes(tmp_path):
    store, document, _, _ = legacy_bank(tmp_path)
    preview = preview_reprocess(store.db_path, document["id"])
    with store.connection() as db:
        db.execute("UPDATE entries SET language='es' WHERE id=(SELECT min(id) FROM entries WHERE kind='qa')")
    current = snapshot(store)
    with pytest.raises(ValueError, match="stale"):
        apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    assert snapshot(store) == current and not (tmp_path / "reprocess-backups").exists()
    with store.connection() as db:
        db.execute("UPDATE entries SET answer='Changed wording' WHERE id=(SELECT min(id) FROM entries WHERE kind='qa')")
    current = snapshot(store)
    with pytest.raises(ValueError, match="wording/provenance"):
        preview_reprocess(store.db_path, document["id"])
    original = store.files_dir / (document["id"] + ".xlsx")
    original.write_bytes(original.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash"):
        apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    assert snapshot(store) == current


def test_backup_failure_and_indexing_conflict_do_not_modify_entries(tmp_path, monkeypatch):
    store, document, _, _ = legacy_bank(tmp_path)
    preview = preview_reprocess(store.db_path, document["id"])
    before = snapshot(store)
    write = Path.write_bytes

    def fail_backup(path, payload):
        if "reprocess-backups" in path.parts:
            raise OSError("Synthetic backup failure")
        return write(path, payload)

    monkeypatch.setattr(Path, "write_bytes", fail_backup)
    with pytest.raises(OSError):
        apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    assert snapshot(store) == before
    monkeypatch.undo()
    with store.connection() as db:
        db.execute("""CREATE TRIGGER refuse_new_pair BEFORE INSERT ON entries WHEN NEW.language='en'
            BEGIN SELECT RAISE(ABORT, 'Synthetic transaction failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    assert snapshot(store) == before  # Metadata updates before the failed insertion also roll back.
    with store.connection() as db:
        db.execute("UPDATE semantic_index_state SET state='indexing' WHERE document_id=?", (document["id"],))
    current = snapshot(store)
    with pytest.raises(ValueError, match="queued/running"):
        apply_reprocess(store.db_path, document["id"], preview["preview_token"])
    assert snapshot(store) == current


def test_exact_source_language_resolves_unknown_wording_but_not_bilingual_collisions(tmp_path):
    store = KnowledgeStore(tmp_path)
    store.import_document("source.xlsx", b"synthetic source", [
        ParsedEntry("qa", "Describe IS", "Original ES answer.", "", "Row 5 ES", "es"),
        ParsedEntry("qa", "JWT", "Original ES JWT.", "", "Row 6 ES", "es"),
        ParsedEntry("qa", "JWT", "Original EN JWT.", "", "Row 6 EN", "en"),
    ])
    for retrieve in (suggest, suggest_live):
        assert retrieve(store, "Describe IS")["answer"] == "Original ES answer."
        assert retrieve(store, "JWT")["status"] == "no_evidence"
