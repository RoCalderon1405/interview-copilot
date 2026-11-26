"""SQLite persistence and FTS5 keyword search for the local knowledge base."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .domain.knowledge import ParsedEntry
from .domain.language import matches_question_language, question_language
from .domain.text import STOPWORDS as STOPWORDS  # Preserve the public store import.
from .textnorm import normalize


class DuplicateDocumentError(Exception):
    pass


def insert_document(
    db: sqlite3.Connection,
    files_dir: Path,
    name: str,
    payload: bytes,
    entries: list[ParsedEntry],
) -> dict:
    """Insert one document, its entries and FTS rows on an existing transaction.

    The caller owns commit/rollback and must hold the offline single-writer
    precondition for its own workflow. Rows are inserted only after the source
    file is written; a row failure removes that file so the caller can roll back
    without leaving a partial import behind. Cross-filesystem atomicity is not
    claimed: a process crash between the file write and the transaction commit
    can leave an orphan source file but never committed rows.
    """
    digest = hashlib.sha256(payload).hexdigest()
    document_id = uuid.uuid4().hex
    suffix = Path(name).suffix.lower()
    target = files_dir / f"{document_id}{suffix}"
    if db.execute("SELECT id FROM documents WHERE sha256=?", (digest,)).fetchone():
        raise DuplicateDocumentError("This document was already imported.")
    target.write_bytes(payload)
    try:
        db.execute("INSERT INTO documents(id,name,extension,sha256,entry_count) VALUES (?,?,?,?,?)",
                   (document_id, name, suffix, digest, len(entries)))
        for entry in entries:
            cursor = db.execute("INSERT INTO entries(document_id,kind,question,answer,body,location,language) VALUES (?,?,?,?,?,?,?)",
                                (document_id, entry.kind, entry.question, entry.answer, entry.body, entry.location, entry.language))
            db.execute("INSERT INTO entry_fts(rowid,question,answer,body) VALUES (?,?,?,?)",
                       (cursor.lastrowid, entry.question, entry.answer, entry.body))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"id": document_id, "name": name, "extension": suffix, "entry_count": len(entries)}


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
                CREATE TABLE IF NOT EXISTS semantic_index_state (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','indexing','completed','failed')),
                    error TEXT,
                    PRIMARY KEY(document_id,model)
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
            entry_columns = {row["name"] for row in db.execute("PRAGMA table_info(entries)")}
            if "language" not in entry_columns:
                db.execute("ALTER TABLE entries ADD COLUMN language TEXT")

    def import_document(self, name: str, payload: bytes, entries: list[ParsedEntry]) -> dict:
        with self.connection() as db:
            return insert_document(db, self.files_dir, name, payload, entries)

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
        every answer/body in the knowledge base. One declared exact-source
        language resolves uncertain request wording; bilingual collisions need
        an identifiable query language. Legacy-only duplicates retain their
        existing language-eligible first-insertion behavior.

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
            db.create_function("qa_language_matches", 2,
                lambda language, stored: matches_question_language(question, stored, language), deterministic=True)
            row = db.execute("""
                WITH exact AS (
                    SELECT e.id,e.document_id,e.question,e.answer,e.location,e.language,d.name AS document_name
                    FROM entries e JOIN documents d ON d.id=e.document_id
                    WHERE e.kind='qa' AND qa_normalize(e.question)=?
                ), policy AS (
                    SELECT COUNT(language) AS labelled,
                        CASE WHEN COUNT(DISTINCT language)=1 THEN MIN(language) ELSE ? END AS target_language
                    FROM exact WHERE language IN ('es','en')
                )
                SELECT document_id,question,answer,location,language,document_name FROM exact CROSS JOIN policy
                WHERE language=target_language OR (language IS NULL AND labelled=0
                    AND qa_language_matches(language,question))
                ORDER BY id LIMIT 1
                """, (normalized, question_language(question))).fetchone()
            return dict(row) if row else None

    def find_matches(self, query: str, limit: int = 20) -> list[dict]:
        tokens = [token for token in re.findall(r"\w+", query.casefold()) if len(token) > 2 and token not in STOPWORDS][:15]
        if not tokens:
            return []
        expression = " OR ".join('"' + token.replace('"', '') + '"' for token in dict.fromkeys(tokens))
        with self.connection() as db:
            db.create_function("qa_language_matches", 2,
                lambda language, stored: matches_question_language(query, stored, language), deterministic=True)
            rows = db.execute("""
                SELECT e.*, d.name AS document_name, bm25(entry_fts,5.0,0.3,1.0) AS rank
                FROM entry_fts
                JOIN entries e ON e.id=entry_fts.rowid
                JOIN documents d ON d.id=e.document_id
                WHERE entry_fts MATCH ? AND (e.kind!='qa' OR qa_language_matches(e.language,e.question))
                ORDER BY CASE WHEN e.language=? THEN 0 ELSE 1 END,rank LIMIT ?
                """, (expression, question_language(query), limit)).fetchall()
            return [dict(row) for row in rows]

    def semantic_status(self, model: str) -> dict:
        """Only Q&A questions are indexed; document excerpts remain out of scope."""
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM entries WHERE kind='qa'").fetchone()[0]
            indexed = db.execute("""SELECT COUNT(*) FROM qa_vectors v
                JOIN entries e ON e.id=v.entry_id WHERE e.kind='qa' AND v.model=?""", (model,)).fetchone()[0]
        return {"questions": total, "indexed": indexed, "pending": total - indexed}

    def semantic_documents(self, model: str, document_id: str | None = None) -> list[dict]:
        """Return per-document progress, deriving readiness from existing vectors."""
        with self.connection() as db:
            rows = db.execute("""SELECT d.id AS document_id, d.name,
                COUNT(e.id) AS questions, COUNT(v.entry_id) AS indexed,
                s.state, s.error FROM documents d
                LEFT JOIN entries e ON e.document_id=d.id AND e.kind='qa'
                LEFT JOIN qa_vectors v ON v.entry_id=e.id AND v.model=?
                LEFT JOIN semantic_index_state s ON s.document_id=d.id AND s.model=?
                WHERE (? IS NULL OR d.id=?) GROUP BY d.id ORDER BY d.rowid""",
                (model, model, document_id, document_id)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            missing = item["questions"] - item["indexed"]
            item["pending"] = missing
            item["requested"] = missing > 0 and item["state"] in ("pending", "indexing")
            item["state"] = "completed" if not missing else item["state"] or "pending"
            if not missing:
                item["error"] = None
            result.append(item)
        return result

    def request_semantic_index(self, model: str, document_id: str) -> bool:
        """Request missing Q&A only; coalesce requests already pending or running."""
        with self.connection() as db:
            db.execute("""INSERT INTO semantic_index_state(document_id,model,state,error)
                SELECT d.id,?,'pending',NULL FROM documents d
                WHERE d.id=? AND EXISTS (SELECT 1 FROM entries e
                    WHERE e.document_id=d.id AND e.kind='qa' AND NOT EXISTS
                    (SELECT 1 FROM qa_vectors v WHERE v.entry_id=e.id AND v.model=?))
                ON CONFLICT(document_id,model) DO UPDATE SET state='pending',error=NULL
                WHERE semantic_index_state.state NOT IN ('pending','indexing')""",
                (model, document_id, model))
            row = db.execute("""SELECT state FROM semantic_index_state
                WHERE document_id=? AND model=?""", (document_id, model)).fetchone()
        return row is not None and row["state"] == "pending"

    def next_semantic_document(self, model: str) -> str | None:
        """Select one requested document without materializing an in-memory queue."""
        with self.connection() as db:
            row = db.execute("""SELECT document_id FROM semantic_index_state
                WHERE model=? AND state='pending' ORDER BY document_id LIMIT 1""", (model,)).fetchone()
        return row["document_id"] if row else None

    def set_semantic_state(self, model: str, document_id: str, state: str, error: str | None = None) -> None:
        """Update status only while its document still exists, including after deletion races."""
        with self.connection() as db:
            db.execute("""INSERT INTO semantic_index_state(document_id,model,state,error)
                SELECT id,?,?,? FROM documents WHERE id=?
                ON CONFLICT(document_id,model) DO UPDATE SET state=excluded.state,error=excluded.error""",
                (model, state, error, document_id))

    def interrupt_semantic_indexing(self, model: str) -> None:
        """Make interrupted work explicitly retryable without changing stored embeddings."""
        with self.connection() as db:
            db.execute("""UPDATE semantic_index_state SET state='failed',error='interrupted'
                WHERE model=? AND state IN ('pending','indexing')""", (model,))

    def unindexed_qa(self, model: str, document_id: str | None = None, limit: int = 32) -> list[dict]:
        """Read a bounded batch of missing questions, never document answers or fragments."""
        with self.connection() as db:
            rows = db.execute("""SELECT e.id,e.question FROM entries e
                LEFT JOIN qa_vectors v ON v.entry_id=e.id AND v.model=?
                WHERE e.kind='qa' AND v.entry_id IS NULL AND (? IS NULL OR e.document_id=?)
                ORDER BY e.id LIMIT ?""", (model, document_id, document_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def save_qa_vectors(self, model: str, batch: list[tuple[int,int,bytes]]) -> None:
        """Atomically skip deleted entries and preserve vectors already written by another call."""
        if not batch:
            return
        with self.connection() as db:
            db.executemany("""INSERT INTO qa_vectors(entry_id,model,dimensions,embedding)
                SELECT id,?,?,? FROM entries WHERE id=? AND kind='qa'
                ON CONFLICT(entry_id,model) DO NOTHING""",
                [(model, dimensions, vector, entry_id) for entry_id, dimensions, vector in batch])

    def semantic_candidates(self, model: str) -> list[dict]:
        """Brute-force over a small local Q&A collection; no vector-server dependency."""
        with self.connection() as db:
            rows = db.execute("""SELECT e.question,e.answer,e.document_id,e.location,e.language,
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
