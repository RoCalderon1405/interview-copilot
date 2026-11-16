"""Local subprocess speech adapter: bounded pipe protocol and hard cancellation."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
from typing import Any

from ..application.stt import FeedResult, MAX_SEGMENT_BYTES, SpeechAvailability, SpeechFailure, SpeechUnavailable

WORKER = Path(__file__).with_name("whisper_worker.py")
LANGUAGES = {"en-US": "en", "es-MX": "es"}
STARTUP_TIMEOUT_SECONDS = 30.0
INFERENCE_TIMEOUT_SECONDS = 10.0
REAP_TIMEOUT_SECONDS = 2.0


class FasterWhisperProvider:
    """Explicitly configured CPU Small multilingual runtime; never install/download."""

    def __init__(self, python: Path | None = None, model: Path | None = None) -> None:
        self.python = python or Path(os.environ.get("COPILOT_WHISPER_PYTHON", sys.executable))
        configured = os.environ.get("COPILOT_WHISPER_MODEL_DIR")
        self.model = model or (Path(configured) if configured else
                               Path(__file__).resolve().parents[4] / "local-data/models/faster-whisper-small")
        self._probe: tuple[float, bool] | None = None
        self._probe_lock = threading.Lock()

    def availability(self) -> SpeechAvailability:
        """Probe native CPU imports, without loading a model or returning local paths."""
        files = all((self.model / name).is_file() for name in
                    ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"))
        installed = False
        if files and self.python.is_file():
            with self._probe_lock:
                if self._probe is None or time.monotonic() - self._probe[0] > 30:
                    try:
                        probe = subprocess.run([str(self.python), "-I", "-B", str(WORKER), "--check"],
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
                        installed = probe.returncode == 0 and json.loads(probe.stdout) == {"type": "ready"}
                    except (OSError, subprocess.SubprocessError, ValueError):
                        installed = False
                    self._probe = (time.monotonic(), installed)
                installed = self._probe[1]
        available = files and installed
        detail = ("Local Faster-Whisper Small multilingual CPU INT8 is available."
                  if available else "Faster-Whisper is unavailable. Configure a local multilingual Small model "
                  "and a compatible CPU Python runtime with COPILOT_WHISPER_MODEL_DIR/COPILOT_WHISPER_PYTHON. "
                  "Vosk remains the default; no automatic downloads or fallback.")
        return {"provider": "faster-whisper", "available": available, "runtime_installed": installed,
                "languages": {language: {"available": available} for language in LANGUAGES}, "detail": detail}

    async def open(self, language: str) -> WhisperSession:
        """Start one language-bound native worker and clean it up on failed startup."""
        if language not in LANGUAGES or not (await asyncio.to_thread(self.availability))["available"]:
            raise SpeechUnavailable("Local Faster-Whisper is unavailable")
        session = WhisperSession()
        try:
            session.launch = asyncio.create_task(asyncio.create_subprocess_exec(
                str(self.python), "-I", "-B", str(WORKER), "--model", str(self.model.resolve()),
                "--language", LANGUAGES[language], stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=32768,
            ))
            session.process = await asyncio.shield(session.launch)
            payload = await asyncio.wait_for(session.read(), timeout=STARTUP_TIMEOUT_SECONDS)
            if payload != {"type": "ready"}:
                raise SpeechUnavailable("Local Faster-Whisper could not start")
            return session
        except BaseException:
            await session.close()
            raise


class WhisperSession:
    """One serialized inference process, terminated and reaped on every close."""

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.launch: asyncio.Task[asyncio.subprocess.Process] | None = None

    async def read(self) -> dict[str, Any]:
        """Read one bounded native response, never accepting arbitrary output."""
        if self.process is None or self.process.stdout is None:
            raise SpeechFailure("worker_unavailable")
        try:
            raw = await self.process.stdout.readline()
            if not raw or len(raw) > 32768:
                raise SpeechFailure("invalid_worker_output")
            result = json.loads(raw)
        except (ValueError, OSError) as exc:
            raise SpeechFailure("invalid_worker_output") from exc
        if not isinstance(result, dict):
            raise SpeechFailure("invalid_worker_output")
        return result

    async def feed(self, pcm: bytes) -> FeedResult:
        """Recognize one bounded segment with a fixed 10 second inference deadline."""
        if not 0 < len(pcm) <= MAX_SEGMENT_BYTES or len(pcm) % 2:
            raise SpeechFailure("invalid_pcm")
        process = self.process
        if process is None or process.stdin is None:
            raise SpeechFailure("worker_unavailable")
        try:
            async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
                process.stdin.write(struct.pack("<I", len(pcm)) + pcm)
                await process.stdin.drain()
                payload = await self.read()
        except (TimeoutError, OSError) as exc:
            raise SpeechFailure("worker_timeout_or_exit") from exc
        text, end = payload.get("text"), payload.get("end")
        if payload.get("type") != "final" or not isinstance(text, str) or len(text) > 3000:
            raise SpeechFailure("invalid_worker_output")
        if end is not None and (isinstance(end, bool) or not isinstance(end, (int, float))
                                or not math.isfinite(end) or not 0 <= end <= len(pcm) / 32000):
            raise SpeechFailure("invalid_worker_timing")
        return FeedResult(final=text or None, last_word_end_seconds=end)

    async def finish(self) -> FeedResult:
        """Whisper has no native streaming tail; stop cancels unfinished segments."""
        return FeedResult()

    async def close(self) -> None:
        """Terminate native CPU work instead of abandoning an uninterruptible thread."""
        if self.process is None and self.launch is not None:
            try:
                self.process = await asyncio.shield(self.launch)
            except Exception:
                self.launch = None
                return
        self.launch = None
        process = self.process
        if process is None:
            return
        self.process = None
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        if process.stdin is not None:
            process.stdin.close()
        try:
            # communicate also drains/closes Windows Proactor pipe transports;
            # wait() alone can leave pending pipe cleanup at event-loop shutdown.
            # Only one bounded protocol response can remain after cancellation.
            await asyncio.wait_for(process.communicate(), timeout=REAP_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            await process.communicate()
