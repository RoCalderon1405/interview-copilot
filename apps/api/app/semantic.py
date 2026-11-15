"""Optional, local semantic retrieval for stored Q&A only.

FastEmbed runs on-device. Indexing is an explicit operation; the Live path never
fetches models, writes recordings, or generates answers. Vectors are SQLite BLOBs.
"""
from __future__ import annotations

import importlib.util
import math
import threading
from array import array
from typing import Any

from .store import KnowledgeStore

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MIN_SIMILARITY = 0.80  # Conservative starting hypothesis; validate on real Q&A before tuning.
MIN_MARGIN = 0.06  # Abstain if two different answers are nearly indistinguishable.
BATCH_SIZE = 32


class SemanticUnavailable(RuntimeError):
    """Optional model is missing, unavailable locally, or cannot initialize."""


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
        }

    def index(self, allow_download: bool = False) -> dict:
        """Prepare missing Q&A only. No download unless caller opts in."""
        with self._lock:
            pending = self.store.unindexed_qa(self.model_name)
            if not pending:
                return self.status()
            model = self._model(allow_download=allow_download)
            for start in range(0, len(pending), BATCH_SIZE):
                batch = pending[start:start+BATCH_SIZE]
                vectors = list(model.embed([row["question"] for row in batch]))
                if len(vectors) != len(batch):
                    raise ValueError("Embedding model returned the wrong vector count")
                stored = []
                for row, vector in zip(batch, vectors):
                    normalized = _unit(vector)
                    packed = array("f", normalized)
                    stored.append((row["id"], len(packed), packed.tobytes()))
                self.store.save_qa_vectors(self.model_name, stored)
            return self.status()

    def candidate(self, question: str) -> dict | None:
        """Suggest stored wording only if score and runner-up margin meet policy.

        Does not re-index automatically, fetch a model or invent an answer.
        """
        candidates = self.store.semantic_candidates(self.model_name)
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
            },
            "match_type": "semantic_qa",
            "matched_question": best["question"],
            "similarity": round(min(1.0, max(-1.0, best_score)), 4),
            "note": "Potentially related stored answer; requires user review",
        }
