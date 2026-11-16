"""Lazy local Vosk adapter; preserves the existing cache and frame semantics."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from ..application.stt import FeedResult, LanguageAvailability, SAMPLE_RATE, SpeechAvailability, SpeechUnavailable

T = TypeVar("T")

MODEL_DIRECTORIES = {"en-US": "vosk-model-small-en-us-0.15", "es-MX": "vosk-model-small-es-0.42"}


def default_models_root() -> Path:
    """Return only the trusted operator-configured model root; never download."""
    configured = os.environ.get("COPILOT_MODELS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "local-data" / "models"


def _vosk_installed() -> bool:
    try:
        return importlib.util.find_spec("vosk") is not None
    except (ImportError, ValueError):
        return False


def _final_result(payload_text: str) -> FeedResult:
    payload = json.loads(payload_text)
    text = (payload.get("text") or "").strip()
    end = None
    words = payload.get("result") or payload.get("words") or []
    if words and isinstance(words[-1], dict) and isinstance(words[-1].get("end"), (int, float)):
        end = float(words[-1]["end"])
    return FeedResult(final=text or None, last_word_end_seconds=end)


class VoskModelCache:
    """Shared at-most-two-language cache with serialized native inference."""

    def __init__(self, models_root: Path | None = None, max_models: int = 2):
        self.models_root = Path(models_root) if models_root is not None else default_models_root()
        self.max_models = max_models
        self._models: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def model_dir(self, language: str) -> Path:
        """Resolve an allowlisted Vosk language below the trusted root."""
        return self.models_root / MODEL_DIRECTORIES[language]

    def is_model_available(self, language: str) -> bool:
        """Check the same model sentinel files as the original Live adapter."""
        directory = self.model_dir(language)
        return (directory / "am" / "final.mdl").is_file() and (directory / "conf" / "model.conf").is_file()

    def availability(self) -> SpeechAvailability:
        """Preserve the existing Vosk status contract."""
        installed = _vosk_installed()
        languages: dict[str, LanguageAvailability] = {
            language: {"available": bool(installed and self.is_model_available(language))}
            for language in MODEL_DIRECTORIES}
        available = [language for language, entry in languages.items() if entry["available"]]
        if not installed:
            detail = "Optional local Vosk runtime is not installed; speech-to-text is unavailable."
        elif not available:
            detail = "Local Vosk model files are not available; speech-to-text is unavailable."
        elif len(available) == len(languages):
            detail = "Local Vosk speech-to-text is available for English and Spanish."
        else:
            detail = f"Local Vosk speech-to-text is available only for {available[0]}."
        return {"provider": "vosk", "available": bool(available), "runtime_installed": installed,
                "languages": languages, "detail": detail}

    def create_recognizer(self, language: str) -> Any:
        """Load a cached model and create a word-timed streaming recognizer."""
        with self._lock:
            if not _vosk_installed() or not self.is_model_available(language):
                raise SpeechUnavailable("Local speech model is unavailable")
            import vosk

            vosk.SetLogLevel(-1)
            model = self._models.get(language)
            if model is None:
                if len(self._models) >= self.max_models:
                    self._models.popitem(last=False)
                model = vosk.Model(str(self.model_dir(language)))
                self._models[language] = model
            else:
                self._models.move_to_end(language)
            recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            recognizer.SetWords(True)
            return recognizer

    def feed(self, recognizer: Any, audio: bytes) -> FeedResult:
        """Retain original final/partial parsing and native locking."""
        with self._lock:
            if recognizer.AcceptWaveform(audio):
                return _final_result(recognizer.Result())
            payload = json.loads(recognizer.PartialResult())
            partial = (payload.get("partial") or "").strip()
            return FeedResult(partial=partial or None)

    def finish(self, recognizer: Any) -> FeedResult:
        """Flush the same Vosk final result, without synthetic partials."""
        with self._lock:
            return _final_result(recognizer.FinalResult())

    async def open(self, language: str) -> VoskSession:
        """Adapt the legacy cache to the asynchronous application speech port."""
        return await VoskSession.open(self, language)


class VoskSession:
    """Drain native calls before releasing a connection, even on task cancellation."""

    def __init__(self, cache: VoskModelCache) -> None:
        self.cache = cache
        self.recognizer: Any = None
        self._active: asyncio.Task[Any] | None = None

    @classmethod
    async def open(cls, cache: VoskModelCache, language: str) -> VoskSession:
        """Create one recognizer without blocking the event loop."""
        session = cls(cache)
        try:
            session.recognizer = await session._call(cache.create_recognizer, language)
            return session
        except BaseException:
            await session.close()
            raise

    async def _call(self, function: Callable[..., T], *args: object) -> T:
        active = asyncio.create_task(asyncio.to_thread(function, *args))
        self._active = active
        try:
            return await asyncio.shield(active)
        finally:
            if active.done():
                self._active = None

    async def feed(self, pcm: bytes) -> FeedResult:
        """Run a bounded frame through the original native implementation."""
        return await self._call(self.cache.feed, self.recognizer, pcm)

    async def finish(self) -> FeedResult:
        """Flush on an explicit Vosk stop."""
        return await self._call(self.cache.finish, self.recognizer)

    async def close(self) -> None:
        """Drain a non-interruptible native call; never send its stale result."""
        if self._active is not None:
            await asyncio.gather(self._active, return_exceptions=True)
            self._active = None
        self.recognizer = None
