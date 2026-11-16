"""Speech contracts and bounded, connection-scoped PCM orchestration.

No transport, document retrieval, generation or native runtime dependency.
PCM is mono signed little-endian 16-bit audio at 16 kHz, held only in memory.
"""
from __future__ import annotations

import asyncio
import math
import struct
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Literal, Protocol, TypedDict

SAMPLE_RATE = 16000
MAX_SEGMENT_BYTES = 8 * SAMPLE_RATE * 2


class SpeechUnavailable(Exception):
    """A local speech runtime or trusted model cannot be used."""


class SpeechFailure(Exception):
    """A bounded speech operation failed without exposing private content."""


class SpeechOverloaded(SpeechFailure):
    """The receiver cannot accept more PCM without exceeding its memory budget."""


@dataclass(frozen=True)
class FeedResult:
    """Provider-independent transcript; timestamps use the connection PCM clock."""

    partial: str | None = None
    final: str | None = None
    last_word_end_seconds: float | None = None
    end_of_speech_latency_ms: float | None = None
    utterance_complete: bool = True


class SpeechSession(Protocol):
    """One language-bound recognizer; close must drain or terminate native work."""

    async def feed(self, pcm: bytes) -> FeedResult: ...
    async def finish(self) -> FeedResult: ...
    async def close(self) -> None: ...


class LanguageAvailability(TypedDict):
    """Public availability for one allowlisted language, without local paths."""

    available: bool


class SpeechAvailability(TypedDict):
    """Provider status shared by composition and transport, not native objects."""

    provider: str
    available: bool
    runtime_installed: bool
    languages: dict[str, LanguageAvailability]
    detail: str


class SpeechProvider(Protocol):
    """Composition-selected local engine, never selected by a request path."""

    def availability(self) -> SpeechAvailability: ...
    async def open(self, language: str) -> SpeechSession: ...


class TranscriptionControl:
    """Allow session finish to interrupt startup/inference and await full teardown."""

    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.closed = asyncio.Event()

    async def close(self) -> None:
        """Signal cancellation and wait until the transport releases speech resources."""
        self.stop.set()
        await self.closed.wait()


@dataclass(frozen=True)
class SpeechSegment:
    """A bounded PCM interval and its estimated last voiced sample receipt time."""

    pcm: bytes
    start_sample: int
    speech_end_at: float
    reason: Literal["silence", "limit"]


class SpeechSegmenter:
    """Energy endpointing with 20 ms analysis, pre-roll and a hard utterance cap.

    This is not semantic VAD. Quiet speech may be missed and sustained noise may
    trigger a segment. Forced cuts can split words; no context or audio is saved.
    """

    FRAME_BYTES = 640
    PRE_ROLL_FRAMES = 10
    END_SILENCE_FRAMES = 25
    MIN_VOICE_FRAMES = 10
    RMS_THRESHOLD = 0.008

    def __init__(self) -> None:
        self._remainder = bytearray()
        self._pre_roll: deque[bytes] = deque(maxlen=self.PRE_ROLL_FRAMES)
        self._audio = bytearray()
        self._sample = 0
        self._start = 0
        self._voice_frames = 0
        self._silence = 0
        self._speech_end_at = 0.0

    @property
    def buffered_bytes(self) -> int:
        """Report all retained PCM, including analysis remainder and pre-roll."""
        return len(self._audio) + len(self._remainder) + sum(map(len, self._pre_roll))

    def feed(self, pcm: bytes, received_at: float) -> list[SpeechSegment]:
        """Segment valid bounded PCM without awaiting inference or retaining silence."""
        if len(pcm) % 2 or len(pcm) > 64000:
            raise SpeechFailure("invalid_pcm")
        self._remainder.extend(pcm)
        segments: list[SpeechSegment] = []
        frames = len(self._remainder) // self.FRAME_BYTES
        for index in range(frames):
            offset = index * self.FRAME_BYTES
            frame = bytes(self._remainder[offset:offset + self.FRAME_BYTES])
            values = struct.unpack("<320h", frame)
            voiced = math.sqrt(sum(value * value for value in values) / 320) / 32768 >= self.RMS_THRESHOLD
            if not self._audio:
                if voiced:
                    self._start = self._sample - len(self._pre_roll) * 320
                    self._audio.extend(b"".join(self._pre_roll))
                    self._pre_roll.clear()
                else:
                    self._pre_roll.append(frame)
            if self._audio or voiced:
                self._audio.extend(frame)
                if voiced:
                    self._voice_frames += 1
                    self._silence = 0
                    remaining_bytes = len(self._remainder) - (offset + self.FRAME_BYTES)
                    self._speech_end_at = received_at - remaining_bytes / 32000
                else:
                    self._silence += 1
                limit = len(self._audio) >= MAX_SEGMENT_BYTES
                if limit or self._silence >= self.END_SILENCE_FRAMES:
                    if self._voice_frames >= self.MIN_VOICE_FRAMES:
                        segments.append(SpeechSegment(bytes(self._audio), self._start,
                                                      self._speech_end_at, "limit" if limit else "silence"))
                    # Preserve only a bounded silence pre-roll after an endpoint.
                    if not voiced:
                        count = min(self._silence, self.PRE_ROLL_FRAMES)
                        tail = self._audio[-count * self.FRAME_BYTES:]
                        self._pre_roll.extend(bytes(tail[offset:offset + self.FRAME_BYTES])
                                              for offset in range(0, len(tail), self.FRAME_BYTES))
                    self._audio.clear()
                    self._voice_frames = self._silence = 0
            self._sample += 320
        del self._remainder[:frames * self.FRAME_BYTES]
        return segments

    def clear(self) -> None:
        """Discard in-memory unfinished speech at stop/disconnect."""
        self._audio.clear()
        self._pre_roll.clear()
        self._remainder.clear()
        self._sample = self._start = self._voice_frames = self._silence = 0
        self._speech_end_at = 0.0


class TranscriptionPump:
    """One consumer with explicit byte/item backpressure, independent of reception.

    Streaming Vosk keeps its frame/partial/final API. Whisper receives only
    speech segments. There is no result queue: the callback is awaited before
    consuming more audio, bounding slow downstream processing as well.
    """

    def __init__(self, session: SpeechSession, *, segmented: bool,
                 emit: Callable[[FeedResult, bool], Awaitable[None]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.session = session
        self.segmenter = SpeechSegmenter() if segmented else None
        self._emit = emit
        self._clock = clock
        self._queue: asyncio.Queue[bytes | SpeechSegment | None] = asyncio.Queue(maxsize=1 if segmented else 20)
        self._byte_limit = MAX_SEGMENT_BYTES if segmented else 64000
        self.queued_bytes = 0
        self.closed = False
        self.stopping = False
        self.task = asyncio.create_task(self._run())

    def feed(self, pcm: bytes) -> None:
        """Accept PCM synchronously or fail explicitly; never drop queued speech."""
        if self.closed or self.stopping:
            raise SpeechFailure("closed")
        if len(pcm) % 2 or len(pcm) > 64000:
            raise SpeechFailure("invalid_pcm")
        if not pcm:
            return
        chunks: list[bytes | SpeechSegment] = list(self.segmenter.feed(pcm, self._clock())) if self.segmenter else [pcm]
        for chunk in chunks:
            size = len(chunk.pcm) if isinstance(chunk, SpeechSegment) else len(chunk)
            if self._queue.full() or self.queued_bytes + size > self._byte_limit:
                raise SpeechOverloaded("pcm_backpressure")
            self._queue.put_nowait(chunk)
            self.queued_bytes += size

    async def _run(self) -> None:
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                result = await self.session.finish()
                if not self.closed:
                    await self._emit(result, True)
                return
            pcm = chunk.pcm if isinstance(chunk, SpeechSegment) else chunk
            self.queued_bytes -= len(pcm)
            result = await self.session.feed(pcm)
            if self.closed:
                return
            if isinstance(chunk, SpeechSegment):
                end = result.last_word_end_seconds
                result = replace(result,
                                 last_word_end_seconds=(end + chunk.start_sample / SAMPLE_RATE) if end is not None else None,
                                 end_of_speech_latency_ms=(round(max(0, self._clock() - chunk.speech_end_at) * 1000, 2)
                                                           if chunk.reason == "silence" else None),
                                 utterance_complete=chunk.reason == "silence")
            await self._emit(result, self.stopping)

    async def finish(self) -> None:
        """Preserve Vosk stop flush; Whisper stop cancels unfinished/queued speech."""
        self.stopping = True
        if self.segmenter:
            await self.close()
        else:
            sentinel = asyncio.create_task(self._queue.put(None))
            try:
                done, _ = await asyncio.wait({sentinel, self.task}, return_when=asyncio.FIRST_COMPLETED)
                if self.task in done:
                    await self.task
                else:
                    await sentinel
                    await self.task
            finally:
                sentinel.cancel()
                await asyncio.gather(sentinel, return_exceptions=True)

    async def close(self) -> None:
        """Suppress stale callbacks, clear PCM and release native resources."""
        self.closed = True
        if self.segmenter:
            self.segmenter.clear()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
        self.queued_bytes = 0
        await self.session.close()
