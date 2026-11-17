"""Opt-in Deepgram Nova-3 streaming adapter; all credentials remain server-side.

The fixed upstream endpoint accepts only PCM16 mono 16 kHz. Interim text is
shown immediately, but finalized chunks are combined until speech_final before
an utterance is eligible for the application's documentary/LLM workflow.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from ..application.stt import FeedResult, SpeechAvailability, SpeechFailure, SpeechUnavailable

KEY_ENV = "COPILOT_DEEPGRAM_API_KEY"
MAX_TEXT_CHARS = 3000
UPSTREAM = "wss://api.deepgram.com/v1/listen"
QUERY = {
    "model": "nova-3",
    "language": "en-US",  # replaced by the provider-supported language code on connection
    "encoding": "linear16",
    "sample_rate": "16000",
    "channels": "1",
    "interim_results": "true",
    "endpointing": "300",
    "punctuate": "true",
}
LANGUAGE_CODES = {"en-US": "en-US", "es-MX": "es"}
LANGUAGES = frozenset(LANGUAGE_CODES)


def _websockets_installed() -> bool:
    try:
        return importlib.util.find_spec("websockets") is not None
    except (ImportError, ValueError):
        return False


def _word_end(alternative: dict[str, Any]) -> float | None:
    """Return the provider's last word timestamp, not a wall-clock latency."""
    words = alternative.get("words")
    if not isinstance(words, list) or not words:
        return None
    last = words[-1]
    value = last.get("end") if isinstance(last, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 3600:
        return float(value)
    return None


class DeepgramProvider:
    """Explicit cloud STT provider, unavailable unless both runtime and key exist."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        settings = os.environ if environ is None else environ
        self._key = settings.get(KEY_ENV, "").strip()

    def availability(self) -> SpeechAvailability:
        installed = _websockets_installed()
        configured = bool(self._key) and "\n" not in self._key and "\r" not in self._key
        available = installed and configured
        detail = ("Deepgram Nova-3 streaming is configured; audio is sent to the cloud and may incur charges."
                  if available else "Deepgram requires the websockets runtime and COPILOT_DEEPGRAM_API_KEY on the API process.")
        return {"provider": "deepgram", "available": available, "runtime_installed": installed,
                "languages": {language: {"available": available} for language in sorted(LANGUAGES)},
                "detail": detail}

    async def open(self, language: str) -> DeepgramSession:
        """Open only the fixed Deepgram host; never log or return the API key."""
        if language not in LANGUAGES or not self.availability()["available"]:
            raise SpeechUnavailable("deepgram_unavailable")
        from websockets.asyncio.client import connect

        query = {**QUERY, "language": LANGUAGE_CODES[language]}
        url = UPSTREAM + "?" + urlencode(query)
        try:
            connection = await connect(
                url,
                additional_headers={"Authorization": f"Token {self._key}"},
                open_timeout=10,
                close_timeout=2,
                max_size=65536,
                max_queue=4,
                compression=None,
                proxy=None,
            )
        except Exception:
            raise SpeechFailure("deepgram_connect_failed") from None
        return DeepgramSession(connection)


class DeepgramSession:
    """Asynchronous upstream sender/receiver with bounded transcript assembly."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._send_lock = asyncio.Lock()
        self._parts: list[str] = []
        self._end: float | None = None
        self._closed = False
        self._last_send = time.monotonic()
        self._keepalive_task = asyncio.create_task(self._keepalive())

    async def _keepalive(self) -> None:
        """Keep an upstream connection alive if system audio temporarily stops."""
        try:
            while not self._closed:
                await asyncio.sleep(4)
                async with self._send_lock:
                    if self._closed:
                        return
                    if time.monotonic() - self._last_send >= 4:
                        await asyncio.wait_for(self._connection.send('{"type":"KeepAlive"}'), timeout=5)
                        self._last_send = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Close causes the normal receiver/pump to report a provider failure.
            try:
                await self._connection.close()
            except Exception:
                pass

    async def feed(self, pcm: bytes) -> FeedResult:
        """Transmit PCM without buffering it beyond the application's bounded queue."""
        if self._closed:
            raise SpeechFailure("deepgram_closed")
        try:
            async with self._send_lock:
                await asyncio.wait_for(self._connection.send(pcm), timeout=5)
                self._last_send = time.monotonic()
        except Exception:
            raise SpeechFailure("deepgram_send_failed") from None
        return FeedResult()

    async def receive(self) -> FeedResult:
        """Read one meaningful update; upstream events are not tied to PCM writes."""
        while not self._closed:
            try:
                raw = await self._connection.recv()
                if not isinstance(raw, str):
                    raise SpeechFailure("deepgram_invalid_event")
                data = json.loads(raw)
            except (SpeechFailure, asyncio.CancelledError):
                raise
            except Exception:
                raise SpeechFailure("deepgram_receive_failed") from None
            if not isinstance(data, dict):
                raise SpeechFailure("deepgram_invalid_event")
            kind = data.get("type")
            if kind == "Error":
                raise SpeechFailure("deepgram_upstream_error")
            if kind != "Results":
                continue
            channel = data.get("channel")
            alternatives = channel.get("alternatives") if isinstance(channel, dict) else None
            if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict):
                raise SpeechFailure("deepgram_invalid_event")
            candidate = alternatives[0]
            text = candidate.get("transcript", "")
            if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
                raise SpeechFailure("deepgram_invalid_event")
            text = text.strip()
            is_final = data.get("is_final") is True
            speech_final = data.get("speech_final") is True
            if is_final and text:
                self._parts.append(text)
                self._end = _word_end(candidate) or self._end
            combined = " ".join(self._parts)
            if len(combined) > MAX_TEXT_CHARS:
                raise SpeechFailure("transcript_too_large")
            if speech_final:
                self._parts.clear()
                end, self._end = self._end, None
                if combined:
                    return FeedResult(final=combined, last_word_end_seconds=end, utterance_complete=True)
                continue
            partial = combined if is_final else " ".join(filter(None, (combined, text)))
            if len(partial) > MAX_TEXT_CHARS:
                raise SpeechFailure("transcript_too_large")
            if partial:
                return FeedResult(partial=partial)
        raise SpeechFailure("deepgram_closed")

    async def finish(self) -> FeedResult:
        """Explicit stop discards incomplete cloud transcripts (no AI on stop)."""
        return FeedResult()

    async def close(self) -> None:
        """Release upstream network resources and in-memory transcript fragments."""
        if self._closed:
            return
        self._closed = True
        self._keepalive_task.cancel()
        await asyncio.gather(self._keepalive_task, return_exceptions=True)
        self._parts.clear()
        self._end = None
        try:
            await asyncio.wait_for(self._connection.close(), timeout=3)
        except Exception:
            pass
