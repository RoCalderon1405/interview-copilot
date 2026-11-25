"""Optional, local semantic retrieval for stored Q&A only.

FastEmbed runs on-device. Indexing is manual or explicitly enabled on import; the
Live path never fetches models or indexes documents. Vectors are SQLite BLOBs.
"""
from __future__ import annotations

import importlib.util
import math
import threading
from array import array
from collections.abc import Callable
from typing import Any

from .store import KnowledgeStore
from .domain.language import matches_question_language

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MIN_SIMILARITY = 0.80  # Conservative starting hypothesis; validate on real Q&A before tuning.
MIN_MARGIN = 0.06  # Abstain if two different answers are nearly indistinguishable.
BATCH_SIZE = 32


class SemanticUnavailable(RuntimeError):
    """Optional model is missing, unavailable locally, or cannot initialize."""


class SemanticInterrupted(RuntimeError):
    """Indexing is shutting down; no new native work may start."""


def _unit(values: Any) -> list[float]:
    vector = [float(v) for v in values]
    if not vector or not all(math.isfinite(v) for v in vector):
        raise ValueError("Invalid embedding vector")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm < 1e-10:
        raise ValueError("Zero embedding vector")
    return [v / norm for v in vector]


class SemanticIndex:
    """Cache one multilingual embedding model and store only user Q&A vectors.

    embedder is injectable to test retrieval deterministically with no downloads.
    """

    def __init__(self, store: KnowledgeStore, embedder: Any = None, model: str = MODEL):
        self.store = store
        self.model_name = model
        self._embedder = embedder
        self._lock = threading.RLock()
        self._index_lock = threading.Lock()
        self._stopping = threading.Event()
        self.cache_dir = store.data_dir / "embedding-models"

    def _model(self, allow_download: bool = False):
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir),
                    local_files_only=not allow_download,
                    threads=2,
                )
            except (ImportError, OSError, ValueError, RuntimeError) as exc:
                raise SemanticUnavailable(
                    "Modelo semántico no disponible. Instala requirements-semantic.txt "
                    "y prepara el índice con descarga explícita."
                ) from exc
        return self._embedder

    def status(self) -> dict:
        return {
            **self.store.semantic_status(self.model_name),
            "model": self.model_name,
            "runtime_installed": importlib.util.find_spec("fastembed") is not None or self._embedder is not None,
            "policy": "candidate_only",
            "documents": self.store.semantic_documents(self.model_name),
        }

    def index(self, allow_download: bool = False, document_id: str | None = None,
              *, batch_size: int = BATCH_SIZE, defer: Callable[[], bool] | None = None) -> dict:
        """Serialize index writers, sharing the model with retrieval only for each small batch."""
        if not 1 <= batch_size <= BATCH_SIZE:
            raise ValueError("Invalid indexing batch size")
        with self._index_lock:
            self._check_running()
            for document in self.store.semantic_documents(self.model_name, document_id):
                if not document["pending"]:
                    continue
                doc_id = document["document_id"]
                try:
                    self._check_running()
                    self.store.set_semantic_state(self.model_name, doc_id, "indexing")
                    while True:
                        self._check_running()
                        batch = self.store.unindexed_qa(self.model_name, doc_id, batch_size)
                        if not batch:
                            break
                        with self._lock:
                            self._check_running()
                            if defer is not None and defer():
                                self.store.set_semantic_state(self.model_name, doc_id, "pending")
                                return self.status()
                            model = self._model(allow_download=allow_download)
                            vectors = list(model.embed([row["question"] for row in batch]))
                        if len(vectors) != len(batch):
                            raise ValueError("Embedding model returned the wrong vector count")
                        stored = []
                        for row, vector in zip(batch, vectors):
                            packed = array("f", _unit(vector))
                            stored.append((row["id"], len(packed), packed.tobytes()))
                        self._check_running()
                        self.store.save_qa_vectors(self.model_name, stored)
                    self._check_running()
                    self.store.set_semantic_state(self.model_name, doc_id, "completed")
                except Exception as exc:
                    code = "interrupted" if isinstance(exc, SemanticInterrupted) else (
                        "model_unavailable" if isinstance(exc, SemanticUnavailable) else "indexing_failed")
                    self.store.set_semantic_state(self.model_name, doc_id, "failed", code)
                    raise
            return self.status()

    def _check_running(self) -> None:
        if self._stopping.is_set():
            raise SemanticInterrupted("La indexación se está deteniendo. Vuelve a intentarlo tras reiniciar el backend.")

    def request_stop(self) -> None:
        """Suppress subsequent batches and discard an in-flight batch before its write."""
        self._stopping.set()

    def drain(self) -> None:
        """Wait for an active index writer; native inference cannot be forcibly cancelled."""
        with self._index_lock:
            pass

    def candidate(self, question: str) -> dict | None:
        """Suggest stored wording only if score and runner-up margin meet policy.

        Does not re-index automatically, fetch a model or invent an answer.
        """
        candidates = [row for row in self.store.semantic_candidates(self.model_name)
                      if matches_question_language(question, row["question"], row.get("language"))]
        if not candidates:
            return None
        with self._lock:
            try:
                query = _unit(next(iter(self._model(allow_download=False).embed([question]))))
            except (SemanticUnavailable, StopIteration, OSError, RuntimeError, ValueError):
                return None
        scored = []
        for row in candidates:
            vector = array("f")
            vector.frombytes(row["embedding"])
            if len(vector) != row["dimensions"] or len(vector) != len(query):
                continue
            similarity = sum(v * q for v, q in zip(vector, query))
            if math.isfinite(similarity):
                scored.append((similarity, row))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        # Identical normalized question duplicates may carry different answers:
        # abstain when the top vectors cannot distinguish them.
        runner_up = scored[1][0] if len(scored) > 1 else -1.0
        if best_score < MIN_SIMILARITY or best_score - runner_up < MIN_MARGIN:
            return None
        return {
            "status": "found",
            "answer": best["answer"],
            "source": {
                "document_id": best["document_id"],
                "document_name": best["document_name"],
                "location": best["location"],
                **({"language": best["language"]} if best.get("language") is not None else {}),
            },
            "match_type": "semantic_qa",
            "matched_question": best["question"],
            "similarity": round(min(1.0, max(-1.0, best_score)), 4),
            "note": "Potentially related stored answer; requires user review",
        }
