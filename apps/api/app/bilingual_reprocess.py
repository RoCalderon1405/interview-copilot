"""Explicit, additive repair of the eight-sheet bilingual interview bank.

Run offline through reprocess_bilingual_xlsx.py. Preview never initializes the
database, loads a model or writes files. Existing source wording must match the
stored original exactly before any metadata or additional entries can be saved.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sqlite3
import uuid
from array import array
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .domain.knowledge import ParsedEntry
from .parsers import MAX_ROWS_PER_SHEET, parse_file

HEADERS = ("ID", "Prioridad", "Tema", "Pregunta (ES)", "Respuesta (ES)", "Question (EN)",
           "Answer (EN)", "Repregunta / práctica", "Origen", "Repaso")
PAIRS_PER_LANGUAGE = 257


def _connect(database: Path, *, writable: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(database.resolve().as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _source(database: Path, document: dict[str, Any]) -> tuple[bytes, list[ParsedEntry], list[dict[str, Any]]]:
    if not re.fullmatch(r"[a-f0-9]{32}", document["id"]) or document["extension"] != ".xlsx":
        raise ValueError("Select the existing bilingual XLSX document by its ID.")
    original = database.parent / "documents" / (document["id"] + ".xlsx")
    if original.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Stored original exceeds the 20 MB import limit.")
    payload = original.read_bytes()
    if hashlib.sha256(payload).hexdigest() != document["sha256"]:
        raise ValueError("Stored original hash differs from the imported document; no changes allowed.")
    entries = parse_file(document["name"], payload)  # Applies the existing archive/resource limits first.
    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    sheets: list[dict[str, Any]] = []
    ids: set[str] = set()
    try:
        if len(workbook.worksheets) != 8:
            raise ValueError("Expected the documented eight-sheet interview bank.")
        for sheet in workbook.worksheets:
            if sheet.max_row is not None and sheet.max_row > MAX_ROWS_PER_SHEET:
                raise ValueError("Source sheet dimensions exceed the existing bounded import format.")
            header = tuple(next(sheet.iter_rows(min_row=4, max_row=4, max_col=10, values_only=True)))
            if header != HEADERS:
                raise ValueError("Every sheet must have the documented bilingual headers on row 4.")
            count = 0
            # XLSX writers may omit the optional dimension element. Read-only
            # openpyxl then reports None; retain the parser's explicit row cap.
            for row in sheet.iter_rows(min_row=5, max_row=sheet.max_row or MAX_ROWS_PER_SHEET, max_col=10, values_only=True):
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                key = str(row[0]).strip() if row[0] is not None else ""
                if not key or key in ids or not all(value is not None and str(value).strip() for value in row[3:7]):
                    raise ValueError("Missing/duplicate ID or incomplete bilingual pair; review the original offline.")
                ids.add(key)
                count += 1
            sheets.append({"sheet": sheet.title, "es": count, "en": count})
    finally:
        workbook.close()
    counts = Counter(entry.language for entry in entries if entry.kind == "qa")
    if counts != {"es": PAIRS_PER_LANGUAGE, "en": PAIRS_PER_LANGUAGE} or len(ids) != PAIRS_PER_LANGUAGE:
        raise ValueError("Expected exactly 257 ES and 257 EN Q&A pairs with unique IDs.")
    return payload, entries, sheets


def _key(entry: dict[str, Any]) -> tuple[str, ...]:
    # Legacy locations have no column/language suffix. Do not match by question
    # alone: answer/body and the source sheet/row must also remain unchanged.
    return tuple(entry[field] for field in ("kind", "question", "answer", "body")) + (
        entry["location"].split(" · columnas ")[0],)


def _plan(db: sqlite3.Connection, database: Path, document_id: str) -> tuple[dict[str, Any], list[tuple[int, ParsedEntry]], list[ParsedEntry], bytes]:
    document_row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if document_row is None:
        raise ValueError("Document not found.")
    if "language" not in {row[1] for row in db.execute("PRAGMA table_info(entries)")}:
        raise ValueError("Start and stop the updated backend once to apply its additive language schema first.")
    document = dict(document_row)
    payload, parsed, sheets = _source(database, document)
    existing = [dict(row) for row in db.execute("SELECT * FROM entries WHERE document_id=? ORDER BY id", (document_id,))]
    if document["entry_count"] != len(existing):
        raise ValueError("Stored entry count is inconsistent; no changes allowed.")
    pending = db.execute("SELECT 1 FROM semantic_index_state WHERE document_id=? AND state IN ('pending','indexing')", (document_id,)).fetchone()
    if pending:
        raise ValueError("Indexing is queued/running. Stop the backend normally and preview again.")
    available: dict[tuple[str, ...], ParsedEntry] = {}
    for entry in parsed:
        key = _key(asdict(entry))
        if key in available:
            raise ValueError("Ambiguous source entries; no changes allowed.")
        available[key] = entry
    updates: list[tuple[int, ParsedEntry]] = []
    for old in existing:
        target = available.pop(_key(old), None)
        if target is None or old["language"] not in (None, target.language):
            raise ValueError("Existing wording/provenance differs from the original; no changes allowed.")
        if old["location"] != target.location or old["language"] != target.language:
            updates.append((old["id"], target))
    additions = list(available.values())
    vectors = [dict(row) for row in db.execute("""SELECT v.* FROM qa_vectors v JOIN entries e ON e.id=v.entry_id
        WHERE e.document_id=? ORDER BY v.entry_id,v.model""", (document_id,))]
    for vector in vectors:
        values = array("f")
        if vector["dimensions"] <= 0 or len(vector["embedding"]) != 4 * vector["dimensions"]:
            raise ValueError("Existing embedding has invalid dimensions; no changes allowed.")
        values.frombytes(vector["embedding"])
        if not all(math.isfinite(value) for value in values) or not math.isclose(sum(value * value for value in values), 1.0, abs_tol=0.001):
            raise ValueError("Existing embedding is not a finite unit vector; no changes allowed.")
        vector["embedding"] = hashlib.sha256(vector["embedding"]).hexdigest()
    practice = [dict(row) for row in db.execute("""SELECT a.* FROM session_answers a JOIN entries e ON e.id=a.entry_id
        WHERE e.document_id=? ORDER BY a.id""", (document_id,))]
    current = [dict(row) for row in db.execute("""SELECT s.* FROM sessions s JOIN entries e ON e.id=s.current_entry_id
        WHERE e.document_id=? ORDER BY s.id""", (document_id,))]
    states = [dict(row) for row in db.execute("SELECT * FROM semantic_index_state WHERE document_id=? ORDER BY model", (document_id,))]
    signature = {"document": document, "existing": existing, "parsed": [asdict(entry) for entry in parsed],
                 "vectors": vectors, "practice": practice, "current": current, "states": states}
    token = hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    preview = {"document_id": document_id, "source_sha256": document["sha256"], "preview_token": token,
               "sheets": sheets, "qa_es": 257, "qa_en": 257, "qa_total": 514,
               "context_fragments": sum(entry.kind == "text" for entry in parsed),
               "stored_entries_before": len(existing), "entries_after": len(parsed),
               "retained_entry_ids": len(existing), "metadata_updates": len(updates), "new_entries": len(additions),
               "preserved_vectors_by_model": dict(Counter(vector["model"] for vector in vectors)),
               "practice_answers_preserved": len(practice), "current_practice_references_preserved": len(current),
               "semantic_status_reset": bool(additions and states), "indexing_scheduled": False}
    return preview, updates, additions, payload


def preview_reprocess(database: Path, document_id: str) -> dict[str, Any]:
    """Read the stored original and return a content-bound, aggregate-only repair preview."""
    db = _connect(database)
    try:
        db.execute("BEGIN")
        return _plan(db, database, document_id)[0]
    finally:
        db.close()


def apply_reprocess(database: Path, document_id: str, preview_token: str) -> dict[str, Any]:
    """Back up and atomically add missing pairs while preserving old IDs, wording and vectors.

    The caller must stop the backend/capture first. A stale preview, changed source,
    ambiguous match or backup failure aborts without editing stored entries.
    No model is loaded and no indexing is scheduled by this operation.
    """
    db = _connect(database, writable=True)
    try:
        db.execute("BEGIN IMMEDIATE")
        preview, updates, additions, payload = _plan(db, database, document_id)
        if preview_token != preview["preview_token"]:
            raise ValueError("Preview is stale. Run preview again and review its counts before confirming.")
        if not updates and not additions:
            return {**preview, "applied": False, "already_current": True}
        backup = database.parent / "reprocess-backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)
        backup.mkdir(parents=True, exist_ok=False)
        # BEGIN IMMEDIATE prevents other writers. A second read connection can
        # back up the committed state before this connection makes any changes.
        source = _connect(database)
        destination = sqlite3.connect(backup / "copilot.sqlite3")
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        (backup / (document_id + ".xlsx")).write_bytes(payload)
        (backup / "preview.json").write_text(json.dumps(preview, indent=2, ensure_ascii=True), encoding="utf-8")
        if (database.parent / "documents" / (document_id + ".xlsx")).read_bytes() != payload:
            raise ValueError("Stored original changed during backup; no changes allowed.")
        for entry_id, entry in updates:
            db.execute("UPDATE entries SET location=?,language=? WHERE id=? AND document_id=?",
                       (entry.location, entry.language, entry_id, document_id))
        for entry in additions:
            cursor = db.execute("""INSERT INTO entries(document_id,kind,question,answer,body,location,language)
                VALUES (?,?,?,?,?,?,?)""", (document_id, entry.kind, entry.question, entry.answer, entry.body, entry.location, entry.language))
            db.execute("INSERT INTO entry_fts(rowid,question,answer,body) VALUES (?,?,?,?)",
                       (cursor.lastrowid, entry.question, entry.answer, entry.body))
        db.execute("UPDATE documents SET entry_count=? WHERE id=?", (preview["entries_after"], document_id))
        if additions:
            # Progress derives from existing vectors. Remove only this document's
            # obsolete completion/error marker, not vectors or queued model work.
            db.execute("DELETE FROM semantic_index_state WHERE document_id=?", (document_id,))
        db.commit()
        return {**preview, "applied": True, "backup_directory": str(backup)}
    finally:
        db.close()  # Rolls back every uncommitted change on failure.
