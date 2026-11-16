"""Bounded, connection-scoped generation lifecycle for final Live questions."""
from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable

from .application.generation import GeneratedSuggestion, GenerationError, GenerationLanguage, GenerationService
from .store import KnowledgeStore


class LiveGeneration:
    """Keep one active call and one replaceable latest question, never a queue.

    Replacement cancels the active call; the worker waits for its cleanup before
    starting another. Revision checks discard cancellation-resistant results.
    No question or answer is persisted or logged.
    """

    def __init__(self, service: GenerationService, store: KnowledgeStore, session_id: str,
                 language: GenerationLanguage, send: Callable[[dict], Awaitable[None]],
                 send_lock: asyncio.Lock) -> None:
        self._service = service
        self._store = store
        self.session_id = session_id
        self._language = language
        self._send = send
        self._send_lock = send_lock
        self._revision = 0
        self._connection_id = secrets.token_hex(8)
        self._closed = False
        self._pending: tuple[int, str] | None = None
        self._active: asyncio.Task[GeneratedSuggestion] | None = None
        self._worker: asyncio.Task[None] | None = None

    @property
    def question_id(self) -> str:
        """Identify the current final question within this session."""
        return f"{self.session_id}:{self._connection_id}:{self._revision}"

    def supersede(self) -> None:
        """Invalidate older work even when the newer question has a document answer."""
        self._revision += 1
        self._pending = None
        if self._active is not None:
            self._active.cancel()

    def submit(self, question: str) -> None:
        """Schedule only the latest eligible final without awaiting inference."""
        if self._closed or not self._service.available:
            return
        self._pending = (self._revision, question)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def _session_open(self) -> bool:
        session = await asyncio.to_thread(self._store.get_session, self.session_id)
        return bool(session and session["mode"] == "live" and not session["finished_at"])

    async def _run(self) -> None:
        while not self._closed and self._pending is not None:
            revision, question = self._pending
            self._pending = None
            try:
                if not await self._session_open() or revision != self._revision or self._closed:
                    continue
                self._active = asyncio.create_task(self._service.generate(question, self._language))
                result = await self._active
                if not await self._session_open():
                    continue
                async with self._send_lock:
                    if self._closed or revision != self._revision:
                        continue
                    await self._send({
                        "type": "generated_suggestion", "kind": "ai_generated",
                        "session_id": self.session_id,
                        "question_id": self.question_id,
                        "question": question, "language": self._language,
                        "answer": result.answer, "provider": result.provider,
                        "model": result.model, "source": None,
                    })
            except asyncio.CancelledError:
                if self._closed:
                    return
            except GenerationError:
                # Keep the existing no-evidence card; capture continues.
                pass
            except Exception:
                # Includes disconnect/send failures; never log private payloads.
                pass
            finally:
                self._active = None

    async def close(self) -> None:
        """Suppress sends immediately and drain provider cancellation on teardown."""
        self._closed = True
        self.supersede()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
