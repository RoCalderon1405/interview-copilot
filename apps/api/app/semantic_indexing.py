"""One process-owned local indexing worker; SQLite holds only document progress."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from .semantic import SemanticIndex, SemanticInterrupted


class SemanticIndexing:
    """Coalesce automatic/manual background requests and drain native work on shutdown."""

    def __init__(self, semantic: SemanticIndex, automatic_enabled: bool = False,
                 defer_for_live: Callable[[], bool] = lambda: False):
        self.semantic = semantic
        self.automatic_enabled = automatic_enabled
        self._defer_for_live = defer_for_live
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._working = threading.Event()
        self._lifecycle = threading.Lock()
        self._thread: threading.Thread | None = None
        self._accepting = False

    def start(self) -> None:
        """Expose interrupted requests for explicit retry, without indexing old documents."""
        self.semantic.store.interrupt_semantic_indexing(self.semantic.model_name)
        self._accepting = True

    def status(self) -> dict:
        """Extend existing counts without claiming that disabled automatic indexing is active."""
        return {**self.semantic.status(), "automatic_enabled": self.automatic_enabled,
                "worker_active": self._working.is_set(), "deferred_for_live": self._defer_for_live()}

    def request(self, document_id: str) -> None:
        """Schedule cached-model work only; download consent is never persisted or inferred."""
        with self._lifecycle:
            if not self._accepting:
                raise SemanticInterrupted("La indexación se está deteniendo. Vuelve a intentarlo tras reiniciar el backend.")
            requested = self.semantic.store.request_semantic_index(self.semantic.model_name, document_id)
            if requested:
                if self._thread is None:
                    worker = threading.Thread(target=self._run, name="semantic-indexing", daemon=False)
                    try:
                        worker.start()
                    except Exception:
                        self.semantic.store.set_semantic_state(
                            self.semantic.model_name, document_id, "failed", "indexing_failed")
                        raise
                    self._thread = worker
                self._wake.set()

    def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait()
            self._wake.clear()
            while not self._stopping.is_set():
                try:
                    document_id = self.semantic.store.next_semantic_document(self.semantic.model_name)
                    if document_id is None:
                        break
                    if self._defer_for_live():
                        self._stopping.wait(0.5)
                        continue
                    self._working.set()
                    # Keep model-lock intervals smaller than the existing manual batch.
                    self.semantic.index(document_id=document_id, batch_size=4, allow_download=False,
                                        defer=self._defer_for_live)
                except sqlite3.Error:
                    # Do not spin on unavailable storage; a later explicit request may retry.
                    break
                except Exception:
                    # SemanticIndex records an allowlisted per-document reason, never private exceptions.
                    pass
                finally:
                    self._working.clear()

    def close(self) -> None:
        """Reject new work, drain the current native batch, and leave pending work retryable."""
        with self._lifecycle:
            self._accepting = False
            self._stopping.set()
            self.semantic.request_stop()
            self._wake.set()
        if self._thread is not None:
            self._thread.join()
        self.semantic.drain()
        self.semantic.store.interrupt_semantic_indexing(self.semantic.model_name)
