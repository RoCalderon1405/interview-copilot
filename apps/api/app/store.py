"""SQLite persistence and FTS5 keyword search for the local knowledge base."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .parsers import ParsedEntry
from .textnorm import normalize

STOPWORDS = {"what", "why", "how", "are", "the", "and", "does", "with", "could", "would", "you", "your", "for", "this", "that", "is", "can", "do", "a", "an", "de", "la", "el", "los", "las", "que", "como", "por", "para", "una", "un", "cuál", "cual", "qué", "es", "en", "se", "me", "i", "to", "it", "of", "in", "on", "if"}


class DuplicateDocumentError(Exception):
    pass


class KnowledgeStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir = self.data_dir / "documents"
        self.files_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "copilot.sqlite3"
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, extension TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE, entry_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
                    body TEXT NOT NULL, location TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
                    question, answer, body, tokenize = 'unicode61 remove_diacritics 2'
                );
                -- Optional local embedding index, deleted with its document entries.
                CREATE TABLE IF NOT EXISTS qa_vectors (
                    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    PRIMARY KEY(entry_id,model)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, current_entry_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS session_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    entry_id INTEGER NOT NULL, answer TEXT NOT NULL, score INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Migrate existing v0.1 databases without discarding prior sessions.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
            if "finished_at" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN finished_at TEXT")

    def import_document(self, name: str, payload: bytes, entries: list[ParsedEntry]) -> dict:
        digest = hashlib.sha256(payload).hexdigest()
        document_id = uuid.uuid4().hex
        suffix = Path(name).suffix.lower()
        target = self.files_dir / f"{document_id}{suffix}"
        with self.connection() as db:
            if db.execute("SELECT id FROM documents WHERE sha256=?", (digest,)).fetchone():
                raise DuplicateDocumentError("This document was already imported.")
            target.write_bytes(payload)
            try:
                db.execute("INSERT INTO documents(id,name,extension,sha256,entry_count) VALUES (?,?,?,?,?)", (document_id, name, suffix, digest, len(entries)))
                for entry in entries:
                    cursor = db.execute("INSERT INTO entries(document_id,kind,question,answer,body,location) VALUES (?,?,?,?,?,?)",
                                        (document_id, entry.kind, entry.question, entry.answer, entry.body, entry.location))
                    db.execute("INSERT INTO entry_fts(rowid,question,answer,body) VALUES (?,?,?,?)",
                               (cursor.lastrowid, entry.question, entry.answer, entry.body))
            except Exception:
                target.unlink(missing_ok=True)
                raise
        return {"id": document_id, "name": name, "extension": suffix, "entry_count": len(entries)}

    def list_documents(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT id,name,extension,entry_count,imported_at FROM documents ORDER BY imported_at DESC").fetchall()
            return [dict(row) for row in rows]

    def delete_document(self, doc_id: str) -> bool:
        with self.connection() as db:
            row = db.execute("SELECT extension FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                return False
            # FTS5 external sync is explicit: remove index rows before source entries.
            db.execute("DELETE FROM entry_fts WHERE rowid IN (SELECT id FROM entries WHERE document_id=?)", (doc_id,))
            db.execute("UPDATE sessions SET current_entry_id=NULL WHERE current_entry_id IN (SELECT id FROM entries WHERE document_id=?)", (doc_id,))
            db.execute("DELETE FROM session_answers WHERE entry_id IN (SELECT id FROM entries WHERE document_id=?)", (doc_id,))
            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        (self.files_dir / f"{doc_id}{row['extension']}").unlink(missing_ok=True)
        return True

    def find_exact_qa(self, question: str) -> dict | None:
        """Fetch at most one Q&A row whose normalized question equals ``question``.

        The normalization runs inside SQLite as a deterministic UDF over the
        ``question`` column only, so the query text scan stays in the database
        and Python materializes a single row (answer + provenance) instead of
        every answer/body in the knowledge base. ``ORDER BY e.id LIMIT 1`` makes
        duplicate normalized questions deterministic: the earliest inserted
        stored answer wins, unchanged across calls.

        An empty normalized query (punctuation-only input) matches nothing, so
        it can never collide with punctuation-only stored questions.
        shortcut: O(N) question-text scan without an exact-match index; add a
        normalized-question index only if measured p95 grows with the KB.
        """
        normalized = normalize(question)
        if not normalized:
            return None
        with self.connection() as db:
            db.create_function("qa_normalize", 1, normalize, deterministic=True)
            row = db.execute("""
                SELECT e.document_id, e.answer, e.location, d.name AS document_name
                FROM entries e
                JOIN documents d ON d.id=e.document_id
                WHERE e.kind='qa' AND qa_normalize(e.question) = ?
                ORDER BY e.id LIMIT 1
                """, (normalized,)).fetchone()
            return dict(row) if row else None

    def find_matches(self, query: str, limit: int = 20) -> list[dict]:
        tokens = [token for token in re.findall(r"\w+", query.casefold()) if len(token) > 2 and token not in STOPWORDS][:15]
        if not tokens:
            return []
        expression = " OR ".join('"' + token.replace('"', '') + '"' for token in dict.fromkeys(tokens))
        with self.connection() as db:
            rows = db.execute("""
                SELECT e.*, d.name AS document_name, bm25(entry_fts,5.0,0.3,1.0) AS rank
                FROM entry_fts
                JOIN entries e ON e.id=entry_fts.rowid
                JOIN documents d ON d.id=e.document_id
                WHERE entry_fts MATCH ? ORDER BY rank LIMIT ?
                """, (expression, limit)).fetchall()
            return [dict(row) for row in rows]

    def semantic_status(self, model: str) -> dict:
        """Only Q&A questions are indexed; document excerpts remain out of scope."""
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM entries WHERE kind='qa'").fetchone()[0]
            indexed = db.execute("""SELECT COUNT(*) FROM qa_vectors v
                JOIN entries e ON e.id=v.entry_id WHERE e.kind='qa' AND v.model=?""", (model,)).fetchone()[0]
        return {"questions": total, "indexed": indexed, "pending": total - indexed}

    def unindexed_qa(self, model: str) -> list[dict]:
        """Only query text leaves SQLite for the local embedding model."""
        with self.connection() as db:
            rows = db.execute("""SELECT e.id,e.question FROM entries e
                LEFT JOIN qa_vectors v ON v.entry_id=e.id AND v.model=?
                WHERE e.kind='qa' AND v.entry_id IS NULL ORDER BY e.id""", (model,)).fetchall()
        return [dict(row) for row in rows]

    def save_qa_vectors(self, model: str, batch: list[tuple[int,int,bytes]]) -> None:
        if not batch:
            return
        with self.connection() as db:
            db.executemany("""INSERT INTO qa_vectors(entry_id,model,dimensions,embedding)
                VALUES (?,?,?,?) ON CONFLICT(entry_id,model) DO UPDATE SET
                dimensions=excluded.dimensions,embedding=excluded.embedding""",
                [(entry_id, model, dimensions, vector) for entry_id, dimensions, vector in batch])

    def semantic_candidates(self, model: str) -> list[dict]:
        """Brute-force over a small local Q&A collection; no vector-server dependency."""
        with self.connection() as db:
            rows = db.execute("""SELECT e.question,e.answer,e.document_id,e.location,
                d.name AS document_name,v.dimensions,v.embedding FROM qa_vectors v
                JOIN entries e ON e.id=v.entry_id AND e.kind='qa'
                JOIN documents d ON d.id=e.document_id
                WHERE v.model=? ORDER BY e.id""", (model,)).fetchall()
        return [dict(row) for row in rows]

    def create_session(self, mode: str) -> dict:
        session_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("INSERT INTO sessions(id,mode) VALUES (?,?)", (session_id, mode))
        return {"id": session_id, "mode": mode}

    def get_session(self, session_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                return None
            count = db.execute("SELECT COUNT(*) FROM session_answers WHERE session_id=?", (session_id,)).fetchone()[0]
            return {**dict(row), "completed_questions": count}

    def next_practice_question(self, session_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("""
                SELECT e.id,e.question,d.name AS document_name FROM entries e
                JOIN documents d ON d.id=e.document_id WHERE e.kind='qa'
                  AND e.id NOT IN (SELECT entry_id FROM session_answers WHERE session_id=?)
                AND EXISTS (SELECT 1 FROM sessions s WHERE s.id=? AND s.mode='practice' AND s.finished_at IS NULL)
                ORDER BY RANDOM() LIMIT 1
                """, (session_id, session_id)).fetchone()
            if not row:
                return None
            db.execute("UPDATE sessions SET current_entry_id=? WHERE id=?", (row['id'], session_id))
            return dict(row)

    def evaluate(self, session_id: str, answer: str, score: int) -> dict | None:
        with self.connection() as db:
            row = db.execute("""
                SELECT e.id,e.answer,e.question,e.location,d.name AS document_name FROM sessions s
                JOIN entries e ON e.id=s.current_entry_id
                JOIN documents d ON d.id=e.document_id WHERE s.id=? AND s.mode='practice' AND s.finished_at IS NULL
                """, (session_id,)).fetchone()
            if not row:
                return None
            db.execute("INSERT INTO session_answers(session_id,entry_id,answer,score) VALUES (?,?,?,?)", (session_id, row['id'], answer, score))
            db.execute("UPDATE sessions SET current_entry_id=NULL WHERE id=?", (session_id,))
            return dict(row)

    def finish_session(self, session_id: str) -> bool:
        """Close a session; never silently discard an in-progress answer."""
        with self.connection() as db:
            current = db.execute("SELECT id,current_entry_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not current:
                return False
            if current["current_entry_id"] is not None:
                raise ValueError("Submit your current answer before finishing the session")
            db.execute("UPDATE sessions SET finished_at=COALESCE(finished_at, CURRENT_TIMESTAMP) WHERE id=?", (session_id,))
        return True

    def session_reviews(self, session_id: str) -> list[dict]:
        """Read source-backed answers for reporting, without storing extra personal data."""
        with self.connection() as db:
            rows = db.execute("""
                SELECT a.score, a.answer AS actual_answer, e.answer AS expected_answer,
                       e.question, e.location, d.name AS document_name
                FROM session_answers a
                JOIN entries e ON e.id=a.entry_id
                JOIN documents d ON d.id=e.document_id
                WHERE a.session_id=? ORDER BY a.id
            """, (session_id,)).fetchall()
            return [dict(row) for row in rows]

    def get_current_practice(self, session_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT e.answer,e.question FROM sessions s JOIN entries e ON e.id=s.current_entry_id WHERE s.id=?", (session_id,)).fetchone()
            return dict(row) if row else None
