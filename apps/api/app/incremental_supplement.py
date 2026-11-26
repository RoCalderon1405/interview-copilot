"""Offline preparation and explicit apply of one reviewed bilingual supplement row.

The existing eight-sheet interview bank stays untouched. This operation validates
the hash-verified stored original as the canonical baseline, copies one reviewed
MSG-012 row from a separate candidate workbook into a one-row supplemental XLSX,
and plans a future additive import. Preparation is read-only for the active
database: it creates a SQLite snapshot and artifacts outside the data directory.
Apply is deliberately separate and requires a reviewed token, a stopped backend
and a fresh verified backup. No model is loaded and no indexing is scheduled.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sqlite3
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from .bilingual_reprocess import HEADERS, PAIRS_PER_LANGUAGE
from .domain.knowledge import ParsedEntry
from .parsers import MAX_ROWS_PER_SHEET, _check_zip, parse_file
from .store import insert_document
from .textnorm import normalize

RECEIPT_NAME = "preparation.json"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
EXPECTED_TEXT_FRAGMENTS = 16
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SHA256 = re.compile(r"[a-f0-9]{64}")


class SupplementError(ValueError):
    """An operator-safe refusal; messages never contain source Q&A wording."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_values(sheet, row_number: int) -> tuple[Any, ...]:
    return tuple(next(sheet.iter_rows(min_row=row_number, max_row=row_number, max_col=10, values_only=True)))


def _clean_literal(value: object) -> str:
    # Mirror parser._clean without exporting another text-cleaning policy.
    return re.sub(r"\s+", " ", str(value or "")).strip()[:15_000]


def _verify_office_zip(payload: bytes) -> None:
    """Reuse the bounded import guard before openpyxl reads an XLSX container."""
    try:
        _check_zip(payload)
    except ValueError as exc:
        raise SupplementError(str(exc)) from exc


def _connect_readonly(database: Path) -> sqlite3.Connection:
    """Open an existing database without creating, migrating or writing it."""
    if not database.is_file():
        raise SupplementError("Database file not found; this operation never creates one.")
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _connect_readwrite(database: Path) -> sqlite3.Connection:
    """Open an existing database for the explicit offline apply only."""
    if not database.is_file():
        raise SupplementError("Database file not found; this operation never creates one.")
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _get_document(db: sqlite3.Connection, document_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{32}", document_id):
        raise SupplementError("Select the existing bilingual XLSX document by its 32-character ID.")
    row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if row is None:
        raise SupplementError("Baseline document not found.")
    document = dict(row)
    if document["extension"] != ".xlsx":
        raise SupplementError("The baseline document is not the expected XLSX workbook.")
    return document


def _counts(db: sqlite3.Connection) -> dict[str, int]:
    return {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("documents", "entries", "entry_fts", "qa_vectors",
                      "semantic_index_state", "sessions", "session_answers")
    }


def _expected_counts_match(counts: dict[str, int], expected: dict[str, int]) -> bool:
    return all(counts[table] == expected[f"{table}_after"] for table in counts)


def _database_signature(db: sqlite3.Connection, *, exclude_document_id: str | None = None) -> str:
    """Fingerprint relevant database state without exposing source wording."""
    excluded_entry_ids: set[int] = set()
    if exclude_document_id is not None:
        excluded_entry_ids = {
            row[0] for row in db.execute("SELECT id FROM entries WHERE document_id=?", (exclude_document_id,))
        }
    digest = hashlib.sha256()

    def add(label: str, values: list[tuple[Any, ...]]) -> None:
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        for value in values:
            digest.update(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii"))
            digest.update(b"\n")

    documents = [tuple(row) for row in db.execute(
        "SELECT id,name,extension,sha256,entry_count,imported_at FROM documents ORDER BY id")]
    if exclude_document_id is not None:
        documents = [row for row in documents if row[0] != exclude_document_id]
    add("documents", documents)

    entries = [tuple(row) for row in db.execute(
        "SELECT id,document_id,kind,question,answer,body,location,language FROM entries ORDER BY id")]
    if exclude_document_id is not None:
        entries = [row for row in entries if row[1] != exclude_document_id]
    add("entries", entries)

    fts = [tuple(row) for row in db.execute(
        "SELECT rowid,question,answer,body FROM entry_fts ORDER BY rowid")
        if row[0] not in excluded_entry_ids]
    add("entry_fts", fts)

    vectors = []
    for row in db.execute("SELECT entry_id,model,dimensions,embedding FROM qa_vectors ORDER BY entry_id,model"):
        vectors.append((row[0], row[1], row[2], hashlib.sha256(row[3]).hexdigest()))
    add("qa_vectors", vectors)

    add("semantic_index_state", [tuple(row) for row in db.execute(
        "SELECT document_id,model,state,error FROM semantic_index_state ORDER BY document_id,model")])
    add("sessions", [tuple(row) for row in db.execute(
        "SELECT id,mode,current_entry_id,created_at,finished_at FROM sessions ORDER BY id")])
    add("session_answers", [tuple(row) for row in db.execute(
        "SELECT id,session_id,entry_id,answer,score,created_at FROM session_answers ORDER BY id")])
    return digest.hexdigest()


def _inspect_candidate(payload: bytes, row_id: str) -> dict[str, Any]:
    """Find exactly one reviewed row and retain its literal cells and sheet headers."""
    if len(payload) > MAX_SOURCE_BYTES:
        raise SupplementError("Candidate workbook exceeds the existing 20 MB import limit.")
    _verify_office_zip(payload)
    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    headers: dict[str, tuple[Any, ...]] = {}
    matches: list[tuple[str, int, tuple[Any, ...]]] = []
    alternate: list[tuple[str, int]] = []
    try:
        for sheet in workbook.worksheets:
            headers[sheet.title] = _row_values(sheet, 4)
            for row_number, row in enumerate(sheet.iter_rows(min_row=5, max_col=10, values_only=True), 5):
                if row_number > MAX_ROWS_PER_SHEET:
                    raise SupplementError("Candidate sheet dimensions exceed the bounded import format.")
                values = tuple(row)
                if not any(value is not None and str(value).strip() for value in values):
                    continue
                key = str(values[0]).strip() if values[0] is not None else ""
                if not key:
                    raise SupplementError("Candidate contains a data row without an ID; review it offline.")
                if key.casefold() == row_id.casefold():
                    if key != row_id:
                        alternate.append((sheet.title, row_number))
                    else:
                        matches.append((sheet.title, row_number, values))
    finally:
        workbook.close()
    if alternate:
        raise SupplementError("Candidate workbook ID differs by spelling or casing from the reviewed ID.")
    if not matches:
        raise SupplementError("Reviewed workbook ID was not found in the candidate.")
    if len(matches) > 1:
        raise SupplementError("Reviewed workbook ID appears more than once in the candidate.")
    sheet_title, row_number, values = matches[0]
    if not all(values[index] is not None and str(values[index]).strip() for index in (3, 4, 5, 6)):
        raise SupplementError("Candidate row does not contain a complete ES/EN question and answer pair.")
    return {
        "sha256": _sha256_bytes(payload),
        "payload": payload,
        "sheet": sheet_title,
        "row": row_number,
        "values": values,
        "headers": headers,
    }


def _inspect_baseline(database: Path, document: dict[str, Any], candidate: dict[str, Any],
                      row_id: str) -> dict[str, Any]:
    """Verify the stored original and derive sheet, header and blank next row."""
    original = database.parent / "documents" / (document["id"] + document["extension"])
    if not original.is_file():
        raise SupplementError("Stored baseline original is missing; no preparation created.")
    if original.stat().st_size > MAX_SOURCE_BYTES:
        raise SupplementError("Stored original exceeds the existing 20 MB import limit.")
    payload = original.read_bytes()
    if _sha256_bytes(payload) != document["sha256"]:
        raise SupplementError("Stored original hash differs from the imported document; no preparation created.")
    _verify_office_zip(payload)
    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    headers: dict[str, tuple[Any, ...]] = {}
    last_rows: dict[str, int] = {}
    row_counts: dict[str, int] = {}
    ids: set[str] = set()
    try:
        if len(workbook.worksheets) != 8:
            raise SupplementError("Expected the documented eight-sheet interview bank.")
        for sheet in workbook.worksheets:
            header = _row_values(sheet, 4)
            if header != HEADERS:
                raise SupplementError("Every baseline sheet must keep the documented headers on row 4.")
            headers[sheet.title] = header
            last = 4
            count = 0
            for row_number, row in enumerate(sheet.iter_rows(min_row=5, max_col=10, values_only=True), 5):
                if row_number > MAX_ROWS_PER_SHEET:
                    raise SupplementError("Baseline sheet dimensions exceed the bounded import format.")
                values = tuple(row)
                if not any(value is not None and str(value).strip() for value in values):
                    continue
                key = str(values[0]).strip() if values[0] is not None else ""
                if not key:
                    raise SupplementError("Baseline contains a data row without an ID; no preparation created.")
                if key.casefold() == row_id.casefold():
                    raise SupplementError("Reviewed workbook ID is already present in the stored baseline.")
                if key in ids:
                    raise SupplementError("Baseline contains duplicate IDs; no preparation created.")
                if not all(values[index] is not None and str(values[index]).strip() for index in (3, 4, 5, 6)):
                    raise SupplementError("Baseline contains an incomplete ES/EN pair; no preparation created.")
                ids.add(key)
                count += 1
                last = row_number
            last_rows[sheet.title] = last
            row_counts[sheet.title] = count
    finally:
        workbook.close()
    if candidate["sheet"] not in headers:
        raise SupplementError("Candidate sheet is not present in the stored baseline.")
    if sum(row_counts.values()) != PAIRS_PER_LANGUAGE or len(ids) != PAIRS_PER_LANGUAGE:
        raise SupplementError("Expected 257 complete bilingual rows in the canonical baseline.")
    if candidate["headers"].get(candidate["sheet"]) != headers[candidate["sheet"]]:
        raise SupplementError("Candidate sheet headers differ from the hash-verified baseline header.")
    expected_row = last_rows[candidate["sheet"]] + 1
    if candidate["row"] != expected_row:
        raise SupplementError("Candidate row is not at the baseline's expected blank next row.")
    return {
        "document": document,
        "payload": payload,
        "source_sha256": document["sha256"],
        "sheet": candidate["sheet"],
        "header": headers[candidate["sheet"]],
        "expected_row": expected_row,
        "last_row": last_rows[candidate["sheet"]],
    }


def _supplement_name(document: dict[str, Any], row_id: str, candidate_sha256: str) -> str:
    stem = Path(document["name"]).stem or "interview_bank"
    safe_row = re.sub(r"[^A-Za-z0-9._-]+", "_", row_id)
    return f"{stem}_SUPPLEMENT_{safe_row}_{candidate_sha256[:8]}.xlsx"


def _parse_supplement(payload: bytes, name: str, baseline: dict[str, Any],
                      candidate: dict[str, Any]) -> dict[str, Any]:
    """Parse the supplement and prove it contains only the reviewed one-row pair."""
    entries = parse_file(name, payload)
    if len(entries) != 2:
        raise SupplementError("Supplement must parse to exactly one ES and one EN Q&A entry.")
    expected_locations = {
        "es": f"Hoja '{baseline['sheet']}' · fila {baseline['expected_row']} · columnas D/E · ES",
        "en": f"Hoja '{baseline['sheet']}' · fila {baseline['expected_row']} · columnas F/G · EN",
    }
    cleaned = [_clean_literal(candidate["values"][index]) for index in (3, 4, 5, 6)]
    expected = (("es", cleaned[0], cleaned[1]), ("en", cleaned[2], cleaned[3]))
    for entry, (language, question, answer) in zip(entries, expected):
        if (entry.kind != "qa" or entry.language != language or entry.question != question
                or entry.answer != answer or entry.body != ""
                or entry.location != expected_locations[language]):
            raise SupplementError("Supplement wording or provenance differs from the reviewed candidate row.")
    content = {
        "sheet": baseline["sheet"],
        "row": baseline["expected_row"],
        "header": list(baseline["header"]),
        "cells": [None if value is None else str(value) for value in candidate["values"][:10]],
        "entries": [asdict(entry) for entry in entries],
    }
    return {
        "name": name,
        "payload": payload,
        "sha256": _sha256_bytes(payload),
        "content_digest": _json_digest(content),
        "entries": entries,
        "content": content,
    }


def _make_supplement(baseline: dict[str, Any], candidate: dict[str, Any], name: str) -> dict[str, Any]:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = baseline["sheet"]
    for column, value in enumerate(baseline["header"], 1):
        sheet.cell(row=4, column=column, value=value)
    for column, value in enumerate(candidate["values"][:10], 1):
        if value is not None and str(value).strip():
            sheet.cell(row=baseline["expected_row"], column=column, value=value)
    buffer = io.BytesIO()
    try:
        workbook.save(buffer)
    finally:
        workbook.close()
    payload = buffer.getvalue()
    return _parse_supplement(payload, name, baseline, candidate)


def _plan(db: sqlite3.Connection, document_id: str, candidate: dict[str, Any],
          baseline: dict[str, Any], supplement: dict[str, Any], row_id: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    """Recheck the canonical baseline, collisions and counts before any write."""
    if "language" not in {row[1] for row in db.execute("PRAGMA table_info(entries)")}:
        raise SupplementError("Start and stop the updated backend once to apply its additive language schema first.")
    document = _get_document(db, document_id)
    for field in ("name", "extension", "sha256", "entry_count"):
        if document[field] != baseline["document"][field]:
            raise SupplementError("Baseline document metadata changed; no preparation or apply allowed.")
    entries = [dict(row) for row in db.execute(
        "SELECT id,document_id,kind,question,answer,body,location,language FROM entries WHERE document_id=? ORDER BY id",
        (document_id,))]
    if len(entries) != document["entry_count"]:
        raise SupplementError("Stored baseline entry count is inconsistent; no changes allowed.")
    qa_counts = Counter(entry["language"] for entry in entries if entry["kind"] == "qa")
    text_counts = Counter(entry["language"] for entry in entries if entry["kind"] == "text")
    if qa_counts != Counter({"es": PAIRS_PER_LANGUAGE, "en": PAIRS_PER_LANGUAGE}):
        raise SupplementError("Expected 257 ES and 257 EN baseline Q&A entries.")
    if text_counts != Counter({None: EXPECTED_TEXT_FRAGMENTS}):
        raise SupplementError("Expected 16 retained baseline context fragments.")
    if len(entries) != PAIRS_PER_LANGUAGE * 2 + EXPECTED_TEXT_FRAGMENTS:
        raise SupplementError("Baseline total entry count is inconsistent; no changes allowed.")

    if len(supplement["entries"]) != 2:
        raise SupplementError("Supplement must contain exactly two Q&A entries.")
    if db.execute("SELECT 1 FROM documents WHERE sha256=?", (supplement["sha256"],)).fetchone():
        raise SupplementError("The supplemental workbook bytes were already imported.")
    for row in db.execute("SELECT name FROM documents"):
        if row_id.casefold() in str(row["name"]).casefold():
            raise SupplementError("Reviewed workbook ID is already present in a document name.")
    questions = [normalize(entry.question) for entry in supplement["entries"]]
    if "" in questions:
        raise SupplementError("Reviewed questions must not normalize to empty text.")
    if len(set(questions)) != len(questions):
        raise SupplementError("Reviewed supplement questions normalize to the same text; no changes allowed.")
    targets = set(questions)
    for row in db.execute("SELECT question FROM entries WHERE kind='qa'"):
        if normalize(row["question"]) in targets:
            raise SupplementError("A normalized exact question already exists in the knowledge base.")

    counts = _counts(db)
    expected = {
        "documents_after": counts["documents"] + 1,
        "entries_after": counts["entries"] + len(supplement["entries"]),
        "entry_fts_after": counts["entry_fts"] + len(supplement["entries"]),
        "qa_vectors_after": counts["qa_vectors"],
        "semantic_index_state_after": counts["semantic_index_state"],
        "sessions_after": counts["sessions"],
        "session_answers_after": counts["session_answers"],
    }
    signature = _database_signature(db)
    row_digest = _json_digest([None if value is None else str(value) for value in candidate["values"][:10]])
    token_signature = {
        "version": 1,
        "row_id": row_id,
        "baseline": {
            "id": document["id"],
            "name": document["name"],
            "extension": document["extension"],
            "sha256": document["sha256"],
            "entry_count": document["entry_count"],
            "source_sha256": baseline["source_sha256"],
            "sheet": baseline["sheet"],
            "expected_row": baseline["expected_row"],
        },
        "candidate": {
            "sha256": candidate["sha256"],
            "sheet": candidate["sheet"],
            "row": candidate["row"],
            "row_digest": row_digest,
        },
        "supplement": {
            "name": supplement["name"],
            "content_digest": supplement["content_digest"],
        },
        "database_signature": signature,
        "counts_before": counts,
        "expected_counts_after": expected,
    }
    preview = {
        "status": "prepared",
        "applied": False,
        "preview_token": _json_digest(token_signature),
        "row_id": row_id,
        "baseline": token_signature["baseline"],
        "candidate": token_signature["candidate"],
        "supplement": {
            "name": supplement["name"],
            "sha256": supplement["sha256"],
            "content_digest": supplement["content_digest"],
            "entries": len(supplement["entries"]),
            "languages": [entry.language for entry in supplement["entries"]],
        },
        "counts_before": counts,
        "expected_changes": {
            "documents": 1,
            "entries": len(supplement["entries"]),
            "entry_fts": len(supplement["entries"]),
            "qa_vectors": 0,
            "semantic_index_state": 0,
            "sessions": 0,
            "session_answers": 0,
        },
        "expected_counts_after": expected,
        "normalized_collisions": 0,
        "semantic_indexing_scheduled": False,
        "apply_requirements": {
            "backend_and_capture_stopped": True,
            "reviewed_preview_token": True,
            "fresh_verified_backup": True,
            "offline_single_writer": True,
        },
    }
    return preview, signature, counts


def _backup_database(source_path: Path, destination_path: Path) -> None:
    """Create a standalone SQLite snapshot from a read-only source connection."""
    source = _connect_readonly(source_path)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _verify_backup(path: Path, expected_counts: dict[str, int] | None = None,
                   *, strict: bool = False) -> dict[str, int]:
    db = _connect_readonly(path)
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SupplementError("Backup integrity check failed; operation aborted.")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SupplementError("Backup foreign-key check failed; operation aborted.")
        counts = _counts(db)
    finally:
        db.close()
    if expected_counts is not None and counts != expected_counts and strict:
        raise SupplementError("Database changed while the backup was created; stop the backend and retry.")
    return counts


def _validate_output_dir(output_dir: Path, database: Path) -> Path:
    output = output_dir.resolve()
    data_root = database.parent.resolve()
    if output == data_root or output.is_relative_to(data_root):
        raise SupplementError("Choose a unique private output directory outside the data directory.")
    if output.is_relative_to(REPOSITORY_ROOT):
        raise SupplementError("Choose a unique private output directory outside the repository.")
    if output.exists():
        raise SupplementError("Output directory already exists; choose a new unique private directory.")
    return output


def prepare_supplement(database: Path, document_id: str, candidate: Path, output_dir: Path,
                       *, expected_candidate_sha256: str | None = None,
                       row_id: str = "MSG-012") -> dict[str, Any]:
    """Create the supplement, a consistent SQLite snapshot and a read-only receipt.

    The active database and stored originals are opened read-only. No document,
    entry, vector, semantic state, session or Practice row is written. The return
    value contains aggregate counts, hashes and a token, never source Q&A text.
    """
    database = database.resolve()
    output = _validate_output_dir(output_dir, database)
    candidate_payload = candidate.read_bytes()
    if len(candidate_payload) > MAX_SOURCE_BYTES:
        raise SupplementError("Candidate workbook exceeds the existing 20 MB import limit.")
    candidate_sha256 = _sha256_bytes(candidate_payload)
    if expected_candidate_sha256 is not None:
        expected = expected_candidate_sha256.strip().lower()
        if not _SHA256.fullmatch(expected):
            raise SupplementError("Expected candidate SHA-256 must be 64 lowercase hexadecimal characters.")
        if candidate_sha256 != expected:
            raise SupplementError("Candidate hash differs from the reviewed hash; no preparation created.")
    candidate_info = _inspect_candidate(candidate_payload, row_id)

    source = _connect_readonly(database)
    try:
        document = _get_document(source, document_id)
        baseline = _inspect_baseline(database, document, candidate_info, row_id)
        supplement_name = _supplement_name(document, row_id, candidate_sha256)
        supplement = _make_supplement(baseline, candidate_info, supplement_name)
        source_counts = _counts(source)
    finally:
        source.close()

    staging = output.with_name(output.name + ".partial-" + uuid.uuid4().hex)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        baseline_copy = staging / f"baseline-{document['id']}{document['extension']}"
        baseline_copy.write_bytes(baseline["payload"])
        candidate_copy = staging / f"candidate-{candidate_sha256[:12]}.xlsx"
        candidate_copy.write_bytes(candidate_payload)
        supplement_path = staging / supplement_name
        supplement_path.write_bytes(supplement["payload"])
        if _sha256_file(supplement_path) != supplement["sha256"]:
            raise SupplementError("Supplement file verification failed; no preparation created.")

        backup_path = staging / "copilot.sqlite3"
        _backup_database(database, backup_path)
        backup_counts = _verify_backup(backup_path)
        backup = _connect_readonly(backup_path)
        try:
            backup_document = _get_document(backup, document_id)
            if (backup_document["sha256"] != document["sha256"]
                    or backup_document["entry_count"] != document["entry_count"]):
                raise SupplementError("Preparation backup does not contain the same baseline document.")
            preview, _, _ = _plan(backup, document_id, candidate_info, baseline, supplement, row_id)
        finally:
            backup.close()

        receipt = {
            **preview,
            "prepared_at": _utc_timestamp(),
            "database": str(database),
            "output_dir": str(output),
            "baseline_copy": str(output / baseline_copy.name),
            "baseline_copy_sha256": _sha256_file(baseline_copy),
            "candidate_copy": str(output / candidate_copy.name),
            "candidate_copy_sha256": _sha256_file(candidate_copy),
            "supplement_path": str(output / supplement_path.name),
            "preparation_backup": str(output / backup_path.name),
            "preparation_backup_sha256": _sha256_file(backup_path),
            "preparation_backup_counts": backup_counts,
            "source_counts_at_preparation": source_counts,
            "concurrent_writer_detected": source_counts != backup_counts,
            "baseline_source_verified": True,
            "candidate_source_verified": True,
            "limitations": [
                "Preparation is read-only for the active database and does not apply the supplement.",
                "The SQLite snapshot and source copies contain private data; keep this directory protected.",
                "Apply is not atomic across SQLite and the documents directory; stop all writers first.",
                "No semantic indexing is scheduled; the new document will appear pending until explicitly indexed.",
            ],
        }
        (staging / RECEIPT_NAME).write_text(
            json.dumps(receipt, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        staging.rename(output)
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def apply_supplement(database: Path, prepared_dir: Path, reviewed_token: str,
                     *, backend_stopped: bool = False) -> dict[str, Any]:
    """Apply a previously prepared supplement after explicit offline confirmation.

    The caller must stop capture and every backend process. A fresh verified
    SQLite backup is created immediately before the write transaction. The
    reviewed token is recomputed against that backup and again under
    ``BEGIN IMMEDIATE``. Existing rows are verified unchanged before commit.
    No model is loaded and no indexing is scheduled.
    """
    if not backend_stopped:
        raise SupplementError("Apply requires explicit backend/capture stopped confirmation.")
    if not reviewed_token:
        raise SupplementError("Apply requires the reviewed preparation token.")
    database = database.resolve()
    prepared = prepared_dir.resolve()
    if prepared.is_relative_to(database.parent.resolve()) or prepared.is_relative_to(REPOSITORY_ROOT):
        raise SupplementError("Prepared artifacts must remain in the private external directory.")
    receipt_path = prepared / RECEIPT_NAME
    if not receipt_path.is_file():
        raise SupplementError("Preparation receipt is missing; prepare again.")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "prepared" or receipt.get("applied") is not False:
        raise SupplementError("Preparation receipt is not an unapplied preparation.")
    if not receipt.get("database") or Path(receipt["database"]).resolve() != database:
        raise SupplementError("Prepared receipt belongs to a different database path.")
    if reviewed_token != receipt.get("preview_token"):
        raise SupplementError("Reviewed token differs from the prepared token.")
    row_id = receipt.get("row_id")
    if not row_id:
        raise SupplementError("Prepared receipt has no reviewed row ID.")

    baseline_copy = Path(receipt["baseline_copy"])
    candidate_copy = Path(receipt["candidate_copy"])
    supplement_path = Path(receipt["supplement_path"])
    preparation_backup = Path(receipt["preparation_backup"])
    for path in (baseline_copy, candidate_copy, supplement_path, preparation_backup):
        if not path.is_file():
            raise SupplementError("Prepared artifacts are incomplete; prepare again.")
    if _sha256_file(preparation_backup) != receipt["preparation_backup_sha256"]:
        raise SupplementError("Preparation backup hash changed; prepare again.")
    if _sha256_file(baseline_copy) != receipt["baseline"]["source_sha256"]:
        raise SupplementError("Prepared baseline copy hash changed; prepare again.")
    candidate_payload = candidate_copy.read_bytes()
    if _sha256_bytes(candidate_payload) != receipt["candidate"]["sha256"]:
        raise SupplementError("Prepared candidate copy hash changed; prepare again.")
    supplement_payload = supplement_path.read_bytes()
    if _sha256_bytes(supplement_payload) != receipt["supplement"]["sha256"]:
        raise SupplementError("Prepared supplement bytes changed; prepare again.")

    source = _connect_readonly(database)
    try:
        document = _get_document(source, receipt["baseline"]["id"])
        source_counts = _counts(source)
    finally:
        source.close()
    for field in ("name", "extension", "sha256", "entry_count"):
        if document[field] != receipt["baseline"][field]:
            raise SupplementError("Active baseline document metadata changed; prepare again.")

    candidate_info = _inspect_candidate(candidate_payload, row_id)
    if candidate_info["sha256"] != receipt["candidate"]["sha256"]:
        raise SupplementError("Prepared candidate hash changed; prepare again.")
    if _json_digest([None if value is None else str(value) for value in candidate_info["values"][:10]]) != receipt["candidate"]["row_digest"]:
        raise SupplementError("Prepared candidate row changed; prepare again.")
    baseline = _inspect_baseline(database, document, candidate_info, row_id)
    if baseline["source_sha256"] != receipt["baseline"]["source_sha256"]:
        raise SupplementError("Active stored original hash changed; prepare again.")
    supplement = _parse_supplement(supplement_payload, supplement_path.name, baseline, candidate_info)
    if supplement["sha256"] != receipt["supplement"]["sha256"]:
        raise SupplementError("Prepared supplement hash changed; prepare again.")
    if supplement["content_digest"] != receipt["supplement"]["content_digest"]:
        raise SupplementError("Prepared supplement content changed; prepare again.")

    backup_root = prepared / "apply-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_path = backup_dir / "copilot.sqlite3"
    try:
        _backup_database(database, backup_path)
        backup_counts = _verify_backup(backup_path, expected_counts=source_counts, strict=True)
        backup_sha256 = _sha256_file(backup_path)
        stored_original = database.parent / "documents" / (document["id"] + document["extension"])
        apply_baseline_copy = backup_dir / stored_original.name
        apply_baseline_copy.write_bytes(stored_original.read_bytes())
        if _sha256_file(apply_baseline_copy) != document["sha256"]:
            raise SupplementError("Stored original changed while backing up; apply aborted.")
        shutil.copyfile(candidate_copy, backup_dir / candidate_copy.name)
        shutil.copyfile(supplement_path, backup_dir / supplement_path.name)
    except Exception:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise

    backup = _connect_readonly(backup_path)
    try:
        backup_document = _get_document(backup, document["id"])
        if (backup_document["sha256"] != document["sha256"]
                or backup_document["entry_count"] != document["entry_count"]):
            raise SupplementError("Apply backup does not contain the same baseline document.")
        planned, _, _ = _plan(
            backup, document["id"], candidate_info, baseline, supplement, row_id)
    finally:
        backup.close()
    if planned["preview_token"] != reviewed_token:
        raise SupplementError("Preparation token is stale; no apply performed.")

    files_dir = database.parent / "documents"
    if not files_dir.is_dir():
        raise SupplementError("Documents directory is missing; apply aborted.")
    db = _connect_readwrite(database)
    inserted: dict[str, Any] | None = None
    committed = False
    try:
        db.execute("BEGIN IMMEDIATE")
        current_document = _get_document(db, document["id"])
        for field in ("name", "extension", "sha256", "entry_count"):
            if current_document[field] != document[field]:
                raise SupplementError("Active baseline document changed before apply; rolled back.")
        current_candidate = _inspect_candidate(candidate_payload, row_id)
        current_baseline = _inspect_baseline(database, current_document, current_candidate, row_id)
        current_supplement = _parse_supplement(supplement_payload, supplement_path.name, current_baseline, current_candidate)
        current, current_signature, _ = _plan(
            db, current_document["id"], current_candidate, current_baseline, current_supplement, row_id)
        if current["preview_token"] != reviewed_token:
            raise SupplementError("Preparation token is stale under the write lock; no apply performed.")
        inserted = insert_document(
            db, files_dir, current_supplement["name"], current_supplement["payload"], current_supplement["entries"])
        if _database_signature(db, exclude_document_id=inserted["id"]) != current_signature:
            raise SupplementError("Existing knowledge-base state changed during apply; rolled back.")
        post_counts = _counts(db)
        if not _expected_counts_match(post_counts, current["expected_counts_after"]):
            raise SupplementError("Unexpected post-apply counts; rolled back.")
        new_document = db.execute(
            "SELECT id,name,sha256,entry_count FROM documents WHERE id=?", (inserted["id"],)).fetchone()
        if (new_document is None or new_document["sha256"] != current_supplement["sha256"]
                or new_document["entry_count"] != len(current_supplement["entries"])):
            raise SupplementError("New supplemental document verification failed; rolled back.")
        new_entries = [tuple(row) for row in db.execute(
            "SELECT kind,question,answer,body,location,language FROM entries WHERE document_id=? ORDER BY id",
            (inserted["id"],))]
        expected_entries = [(entry.kind, entry.question, entry.answer, entry.body, entry.location, entry.language)
                            for entry in current_supplement["entries"]]
        if new_entries != expected_entries:
            raise SupplementError("New supplemental entries verification failed; rolled back.")
        db.execute("COMMIT")
        committed = True
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        # Never remove the stored source of a committed document.
        if inserted is not None and not committed:
            (files_dir / f"{inserted['id']}{inserted['extension']}").unlink(missing_ok=True)
        raise
    finally:
        db.close()

    result = {
        **current,
        "status": "applied",
        "applied": True,
        "applied_at": _utc_timestamp(),
        "prepared_dir": str(prepared),
        "apply_backup": str(backup_path),
        "apply_backup_sha256": backup_sha256,
        "apply_backup_counts": backup_counts,
        "new_document_id": inserted["id"],
        "new_document_name": inserted["name"],
        "new_entries": len(current_supplement["entries"]),
        "counts_after": post_counts,
        "existing_state_preserved": True,
        "semantic_indexing_scheduled": False,
    }
    receipt_path = backup_dir / "apply.json"
    try:
        receipt_path.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    except OSError:
        # The database transaction already committed: report success plus an explicit warning.
        result["apply_receipt"] = None
        result["receipt_warning"] = (
            "Database changes were committed, but apply.json could not be written in the apply backup directory.")
    else:
        result["apply_receipt"] = str(receipt_path)
    return result
