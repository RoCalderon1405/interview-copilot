"""Local Live audio transport: authorized speech, question detection and retrieval.

Privacy and lifecycle boundaries for this slice:

* Audio is processed frame by frame in memory and never written to disk.
* The optional Vosk runtime and model files are loaded lazily, so the rest of
  the API keeps working when they are absent.
* Model paths are fixed under the project's ignored ``local-data/models``
  directory (or an explicitly trusted ``COPILOT_MODELS_DIR`` root). No request
  input can select a path and Vosk never downloads a model automatically.
* Tokens are ephemeral, memory-only, single-use and bound to one Live session.
* Automatic suggestions preserve exact Q&A priority; an optional, local semantic
  candidate is visibly labeled and never treated as a verified exact answer.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Literal, cast

import anyio
from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel

from .application.stt import (FeedResult, SpeechUnavailable, SpeechFailure, SpeechOverloaded,
                              SpeechProvider, SpeechSession, TranscriptionControl, TranscriptionPump,
                               StreamingSpeechSession, StreamingTranscriptionPump)
from .infrastructure.vosk import VoskModelCache, MODEL_DIRECTORIES, default_models_root, _final_result
from .bootstrap import create_deepgram_provider, create_whisper_provider
from .retrieval import suggest_live
from .live_generation import LiveGeneration
from .store import KnowledgeStore
from .textnorm import normalize

Language = Literal["en-US", "es-MX"]
Provider = Literal["vosk", "faster-whisper", "deepgram"]

SAMPLE_RATE = 16000
MAX_FRAME_BYTES = 64000
MAX_HANDSHAKE_CHARS = 2048
MAX_CONTROL_CHARS = 2048
MAX_TRANSCRIPT_CHARS = 3000
MAX_QUESTION_CANDIDATES = 8
HANDSHAKE_TIMEOUT_SECONDS = 5.0
TOKEN_TTL_SECONDS = 30.0
TOKEN_CAPACITY = 64
DEDUPE_TTL_SECONDS = 120.0
DEDUPE_CAPACITY = 32
# Four consecutive identical ~100 ms Vosk partials before an early exact Q&A lookup.
PARTIAL_STABILITY_FRAMES = 4
IDLE_TIMEOUT_SECONDS = 30.0
SESSION_LIMIT_SECONDS = 3600.0

# Development renderer origins only. WS handshakes are validated explicitly
# here instead of relying on HTTP CORS middleware.
ALLOWED_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "testserver"})

_DIAGNOSTIC_STAGES = frozenset({
    "ws.accepted", "token.accepted", "recognizer.begin", "recognizer.ready",
    "pcm.first-receipt", "cleanup.complete",
})


def _diagnostic(stage: str) -> None:
    """Emit only fixed local startup stages; never accept request data or disrupt cleanup."""
    if os.environ.get("COPILOT_LIVE_DIAGNOSTICS") != "1" or stage not in _DIAGNOSTIC_STAGES:
        return
    try:
        print("[live-diag:api] " + json.dumps({"stage": stage}), flush=True)
    except Exception:
        pass

# Sentence boundaries for the heuristic detector. Unpunctuated finals remain
# one chunk, which is why cue-prefix detection is also applied.
_SENTENCE_SPLIT = re.compile(r"(?<=[?;.!])\s+|\n+")
_LEADING_FILLER = re.compile(
    r"^(?:(?:so|okay|ok|well|and|um|uh|ah|oh|sure|bueno|pues|entonces|y|eh)\b[\s,;-]*)+",
    re.IGNORECASE,
)
# Vosk returns unpunctuated final speech in chunks. A natural introduction can
# precede the actual question; remove only explicit introductions, not arbitrary
# preceding speech (which could be a statement quoting a question).
_QUESTION_INTRO = re.compile(
    r"^(?:(?:got it|i see|ya veo)\s+)?(?:the question is|my question is|la pregunta es)\s+",
    re.IGNORECASE,
)
# Vosk may finalize an entire interviewer turn without punctuation. Strip the
# preceding conversation ONLY when an explicit question-introduction phrase is
# present. Do not search for question words anywhere in arbitrary statements.
_EMBEDDED_QUESTION_INTRO = re.compile(
    r"\b(?:here(?:'s|s| is) (?:the|my) question|"
    r"(?:the|my) question is|(?:la|mi) pregunta es)\b[\s,:;-]*",
    re.IGNORECASE,
)
# Heuristics only: these are question cues, not semantic question detection.
_EN_CUES = re.compile(
    r"^(?:what|why|how|when|where|who|whom|whose|which|can you|could you|would you|will you|"
    r"do you|did you|does|are you|have you|has|is|tell me|describe|walk me through|explain)\b"
)
_ES_CUES = re.compile(
    r"^(?:que|como|cuando|donde|quien|cual|cuanto|puedes|podrias|me puedes|me podrias|"
    r"cuentame|hablame|describe|dime|explica)\b"
)

# Only marked conversational boundaries are searched inside finals. Requiring
# an auxiliary (EN) or a small set of direct-question forms (ES) avoids splitting
# subordinate clauses such as "explain how it works and why it matters".
_DIRECT_QUESTION = re.compile(
    r"^(?:(?:what|why|how|when|where|who|which)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|would|will|should|have|has)\b|"
    r"why\s+(?:use|choose|prefer|avoid|test)\b|"
    r"(?:can|could|would|will|do|did|are|have)\s+you\b|"
    r"tell me\b|describe\b|walk me through\b|explain\b|"
    r"(?:que|cual)\s+(?:es|son)\b|por que\b|"
    r"como\s+(?:resuelves|manejas|manejarias|eliges|elegirias|implementas|"
    r"implementarias|disenas|disenarias|pruebas|probarias|funciona)\b|"
    r"puedes\b|podrias\b|me puedes\b|me podrias\b|"
    r"cuentame\b|hablame\b|describe\b|dime\b|explica\b)"
)
_FINAL_BOUNDARY = re.compile(
    r"\b(?:(?:and|so|y|entonces)\s+)?(?P<intro>"
    r"here(?:'s|s| is) (?:the|my) question|(?:the|my) question is|"
    r"next question|(?:la|mi) pregunta es|(?:la )?siguiente pregunta)\b[\s,:;-]*|"
    r"\b(?:(?:and|y)\s+)?(?P<number>"
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"first|second|third|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|"
    r"primero|segundo|tercero|[1-9]|10)\b[\s.):;-]+|"
    r"\b(?P<transition>so|entonces|ahora|and|y)\b[\s,:;-]+",
    re.IGNORECASE,
)
_QUOTED_TEXT = re.compile(r'"[^"\n]*"|“[^”\n]*”|«[^»\n]*»|(?<!\w)\'[^\'\n]*\'(?!\w)')
_REPORTED_SPEECH = re.compile(
    r"\b(?:i|we|they|he|she|you)\s+(?:(?:already|previously)\s+)?"
    r"(?:discussed|answered|asked|quoted|said|wrote)\b|"
    r"\b(?:document|example|article|transcript)\s+(?:says|contains|quotes|reads)\b|"
    r"\b(?:discutimos|respondimos|preguntamos|dijeron|dijo|cito)\b|"
    r"\b(?:documento|ejemplo|articulo)\s+(?:dice|contiene|cita)\b"
)
_SUBORDINATE_PROMPT = re.compile(
    r"^(?:(?:can|could|would) you )?(?:explain|describe|tell me)\s+"
    r"(?:how|why|what|which|when|where)\b|"
    r"^(?:(?:puedes|podrias) )?(?:explica|explicar|describe|describir|dime)\s+"
    r"(?:como|por que|que|cual|cuando|donde)\b"
)


@dataclass(frozen=True)
class LiveGrant:
    session_id: str
    language: str
    expires_at: float
    provider: str = "vosk"


def _detect_partial_questions(text: str, limit: int = MAX_QUESTION_CANDIDATES) -> list[str]:
    """Preserve the original prefix/explicit-introduction policy for partials.

    This is intentionally lexical: no punctuation is required ("what is
    authentication", "como resuelves..."), and leading fillers and explicit
    question-introduction phrases are removed. Statements without a question
    cue are ignored. Long turns are scanned for explicit introductions such
    as "here's the question", without scanning arbitrary quoted statements.
    It is not a semantic detector and may still miss unusual phrasing.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(text):
        if len(candidates) >= limit:
            break
        chunk = _LEADING_FILLER.sub("", raw.strip()).strip()
        chunk = _QUESTION_INTRO.sub("", chunk, count=1).strip()
        # Natural speech: "... so here's the question when designing an API
        # how do you choose ...". Vosk emits it as one unpunctuated final.
        # Prefer the suffix after an explicit introduction; keep the context
        # ("when designing an API") because it changes the question's meaning.
        if not (_EN_CUES.match(normalize(chunk)) or _ES_CUES.match(normalize(chunk))):
            introductions = list(_EMBEDDED_QUESTION_INTRO.finditer(chunk))
            if introductions:
                chunk = chunk[introductions[-1].end():].strip()
        if not chunk:
            continue
        normalized = normalize(chunk)
        if not normalized:
            continue
        is_punctuated_question = raw.rstrip().endswith("?")
        if not is_punctuated_question and not (_EN_CUES.match(normalized) or _ES_CUES.match(normalized)):
            continue
        candidate = chunk.rstrip(" \t?!.;,").strip()
        key = normalize(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def detect_questions(text: str, limit: int = MAX_QUESTION_CANDIDATES) -> list[str]:
    """Extract ordered EN/ES final candidates at conservative marked boundaries.

    Explicit introductions, numbered questions and direct questions following
    conversational transitions can delimit an unpunctuated turn. Unmarked
    embedded interrogatives are deliberately not scanned. Quoted text cannot
    create boundaries; reporting cues suppress embedded extraction. This is a
    lexical heuristic, not a guarantee of sentence boundaries or intent.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    # Mask only for boundary discovery, retaining offsets and original wording.
    masked = _QUOTED_TEXT.sub(lambda match: " " * len(match.group()), text)
    sentence_start = 0
    sentence_ends = [match.span() for match in _SENTENCE_SPLIT.finditer(masked)]
    for sentence_end, next_start in [*sentence_ends, (len(text), len(text))]:
        raw = text[sentence_start:sentence_end]
        scan = masked[sentence_start:sentence_end]
        segment_start = 0
        segments: list[str] = []
        for boundary in _FINAL_BOUNDARY.finditer(scan):
            suffix = scan[boundary.end():].lstrip(" ¿:,-;")
            normalized = normalize(suffix)
            if boundary.lastgroup in {"intro", "number"}:
                is_question = bool(_EN_CUES.match(normalized) or _ES_CUES.match(normalized)
                                   or _DIRECT_QUESTION.match(normalized))
            else:
                is_question = bool(_DIRECT_QUESTION.match(normalized))
            if not is_question or _REPORTED_SPEECH.search(normalize(scan[:boundary.start()])):
                continue
            # A bare conjunction only separates questions, not arbitrary prose.
            if boundary.group("transition") and boundary.group("transition").casefold() in {"and", "y"}:
                preceding = scan[segment_start:boundary.start()]
                preceding = normalize(_LEADING_FILLER.sub("", preceding.strip()))
                if (not (_EN_CUES.match(preceding) or _ES_CUES.match(preceding)
                         or _DIRECT_QUESTION.match(preceding))
                        or _SUBORDINATE_PROMPT.match(preceding)):
                    continue
            segments.append(raw[segment_start:boundary.start()])
            segment_start = boundary.end()
        segments.append(raw[segment_start:])
        for segment in segments:
            # Do not let the legacy introduction fallback rediscover quoted or
            # reported questions that boundary discovery intentionally rejected.
            visible = _QUOTED_TEXT.sub(lambda match: " " * len(match.group()), segment)
            prefix = _QUESTION_INTRO.sub("", _LEADING_FILLER.sub("", visible.strip()), count=1).strip()
            normalized = normalize(prefix)
            if not (_EN_CUES.match(normalized) or _ES_CUES.match(normalized)
                    or _DIRECT_QUESTION.match(normalized)
                    or visible.rstrip().endswith("?")):
                continue
            candidate = _QUESTION_INTRO.sub(
                "", _LEADING_FILLER.sub("", segment.strip()), count=1
            ).rstrip(" \t?!.;,").strip()
            key = normalize(candidate)
            if not key or key in seen:
                continue
            if len(candidates) >= limit:
                return candidates
            seen.add(key)
            candidates.append(candidate)
        sentence_start = next_start
    return candidates


class StablePartialQuestion:
    """Return only stable question-shaped Vosk partials, once per candidate.

    Partial hypotheses may change as more speech arrives. Require repeated
    identical text before checking the user's exact Q&A, and bound attempts
    so the recognizer cannot cause a database lookup on every audio frame.
    Ordinary final transcripts still run independently.
    """

    def __init__(self):
        self._last_key = ""
        self._stable_frames = 0
        self._attempted: OrderedDict[str, None] = OrderedDict()

    def observe(self, partial: str) -> str | None:
        questions = _detect_partial_questions(partial, limit=2)
        if len(questions) != 1:
            self.reset()
            return None
        question = questions[0]
        key = normalize(question)
        if not key:
            self.reset()
            return None
        if key != self._last_key:
            self._last_key = key
            self._stable_frames = 1
        else:
            self._stable_frames += 1
        if self._stable_frames < PARTIAL_STABILITY_FRAMES or key in self._attempted:
            return None
        if len(self._attempted) >= DEDUPE_CAPACITY:
            self._attempted.popitem(last=False)
        self._attempted[key] = None
        return question

    def reset(self) -> None:
        self._last_key = ""
        self._stable_frames = 0


class RecentFinalDedupe:
    """Bounded per-connection dedupe of normalized final question candidates.

    A repeated final transcript should not trigger the same retrieval and
    suggestion repeatedly. Entries expire after ``ttl_seconds`` and the oldest
    entry is evicted at ``capacity`` so memory is strictly bounded.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = DEDUPE_TTL_SECONDS,
        capacity: int = DEDUPE_CAPACITY,
    ):
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._seen: dict[str, float] = {}

    def seen(self, text: str) -> bool:
        key = normalize(text)
        if not key:
            return False
        now = self.clock()
        for expired in [name for name, stamp in self._seen.items() if now - stamp >= self.ttl_seconds]:
            del self._seen[expired]
        if key in self._seen:
            return True
        if len(self._seen) >= self.capacity:
            self._seen.pop(next(iter(self._seen)))
        self._seen[key] = now
        return False


class LiveTokenManager:
    """Ephemeral single-use Live connection tokens.

    Tokens live only in this process. Issuing a token revokes earlier tokens
    for the same session, and the dictionary is capped at ``capacity`` entries
    with expired entries pruned first.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = TOKEN_TTL_SECONDS,
        capacity: int = TOKEN_CAPACITY,
    ):
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._tokens: dict[str, LiveGrant] = {}
        self._lock = threading.Lock()

    def issue(self, session_id: str, language: str, provider: str = "vosk") -> str:
        with self._lock:
            now = self.clock()
            self._prune(now)
            for token in [key for key, grant in self._tokens.items() if grant.session_id == session_id]:
                del self._tokens[token]
            if len(self._tokens) >= self.capacity:
                self._tokens.pop(next(iter(self._tokens)))
            token = secrets.token_urlsafe(32)
            self._tokens[token] = LiveGrant(session_id, language, now + self.ttl_seconds, provider)
            return token

    def consume(self, token: str) -> LiveGrant | None:
        with self._lock:
            grant = self._tokens.pop(token, None)
            if grant is None or self.clock() >= grant.expires_at:
                return None
            return grant

    def _prune(self, now: float) -> None:
        for token in [key for key, grant in self._tokens.items() if now >= grant.expires_at]:
            del self._tokens[token]


class LiveRuntime:
    """Process-wide Live resources: token store and the single connection slot."""

    def __init__(self, models: VoskModelCache | None = None, clock: Callable[[], float] = time.monotonic,
                 whisper: SpeechProvider | None = None,
                 deepgram: SpeechProvider | None = None):
        self.models = models or VoskModelCache()
        self.whisper = whisper or create_whisper_provider()
        self.deepgram = deepgram or create_deepgram_provider()
        self.clock = clock
        self.tokens = LiveTokenManager(clock=clock)
        self.idle_timeout_seconds = IDLE_TIMEOUT_SECONDS
        self.session_limit_seconds = SESSION_LIMIT_SECONDS
        self.handshake_timeout_seconds = HANDSHAKE_TIMEOUT_SECONDS
        self.max_frame_bytes = MAX_FRAME_BYTES
        self._connection_lock = threading.Lock()
        self._connection_active = False
        self.generations: dict[str, LiveGeneration] = {}
        self.transcriptions: dict[str, TranscriptionControl] = {}

    def acquire_connection(self) -> bool:
        with self._connection_lock:
            if self._connection_active:
                return False
            self._connection_active = True
            return True

    def release_connection(self) -> None:
        with self._connection_lock:
            self._connection_active = False


def _origin_and_host_allowed(websocket: WebSocket) -> bool:
    """Validate Origin and Host for the WS handshake itself.

    WS validation is explicit and independent of HTTP CORS; missing, ``null``
    and external origins/hosts are rejected.
    """
    if websocket.headers.get("origin") not in ALLOWED_ORIGINS:
        return False
    host = websocket.headers.get("host", "").strip().lower()
    hostname = host.rsplit(":", 1)[0] if ":" in host else host
    return hostname in ALLOWED_HOSTNAMES


async def _send_live(websocket: WebSocket, event: dict) -> None:
    """Serialize normal and generated events on the same connection."""
    async with websocket.state.send_lock:
        await websocket.send_json(event)


async def _close_live_work(websocket: WebSocket) -> None:
    """Invalidate both result streams before concurrently draining their resources."""
    pump = getattr(websocket.state, "transcription_pump", None)
    generation = getattr(websocket.state, "generation", None)
    tasks = []
    if pump is not None:
        pump.closed = True
        pump.task.cancel()
        tasks.append(pump.close())
    else:
        speech = getattr(websocket.state, "speech_session", None)
        if speech is not None:
            tasks.append(speech.close())
    if generation is not None:
        generation.supersede()
        tasks.append(generation.close())
    await asyncio.gather(*tasks, return_exceptions=True)


async def _fail(websocket: WebSocket, code: str, message: str, close_code: int = 1008) -> None:
    await _close_live_work(websocket)
    try:
        await _send_live(websocket, {"type": "error", "code": code, "message": message})
    finally:
        await websocket.close(code=close_code)


def _is_stop_control(text: str) -> bool:
    stripped = text.strip()
    if stripped.casefold() == "stop":
        return True
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("type") == "stop"


def _retrieve_live(store: KnowledgeStore, question: str, semantic=None) -> tuple[dict, float]:
    started = time.perf_counter()
    result = suggest_live(store, question, semantic=semantic)
    return result, round((time.perf_counter() - started) * 1000, 2)


def _transcript_too_large(text: str | None) -> bool:
    return bool(text and len(text) > MAX_TRANSCRIPT_CHARS)


async def _emit_final(
    websocket: WebSocket,
    runtime: LiveRuntime,
    store: KnowledgeStore,
    result: FeedResult,
    language: str,
    dedupe: RecentFinalDedupe,
    generation: LiveGeneration | None = None,
) -> None:
    text = (result.final or "").strip()
    if not text:
        return
    await _send_live(websocket, {
        "type": "final",
        "text": text,
        "language": language,
        "last_word_end_seconds": result.last_word_end_seconds,
        **({"end_of_speech_latency_ms": result.end_of_speech_latency_ms}
           if result.end_of_speech_latency_ms is not None else {}),
    })
    for question in detect_questions(text):
        if dedupe.seen(question):
            continue
        if generation is not None:
            generation.supersede()
        suggestion, retrieval_ms = await asyncio.to_thread(
            _retrieve_live, store, question, getattr(websocket.app.state, "semantic", None)
        )
        await _send_live(websocket, {
            "type": "suggestion",
            "question": question,
            **({"session_id": generation.session_id, "question_id": generation.question_id} if generation else {}),
            "language": language,
            "status": suggestion["status"],
            "answer": suggestion.get("answer"),
            "source": suggestion.get("source"),
            "match_type": suggestion.get("match_type"),
            "matched_question": suggestion.get("matched_question"),
            "similarity": suggestion.get("similarity"),
            "retrieval_ms": retrieval_ms,
            "last_word_end_seconds": result.last_word_end_seconds,
        })
        if generation is not None and suggestion["status"] == "no_evidence":
            generation.submit(question)


async def _emit_stable_partial_exact(
    websocket: WebSocket,
    store: KnowledgeStore,
    partial: str,
    language: str,
    tracker: StablePartialQuestion,
    dedupe: RecentFinalDedupe,
) -> None:
    """Offer an early answer ONLY after a repeated partial matches stored Q&A exactly.

    Unknown or incomplete partials do not produce question cards. A final
    transcript is still emitted and evaluated, even if partial speech was wrong.
    """
    question = tracker.observe(partial)
    if not question:
        return
    suggestion, retrieval_ms = await asyncio.to_thread(_retrieve_live, store, question)
    if suggestion.get("match_type") != "exact_qa" or dedupe.seen(question):
        return
    await _send_live(websocket, {
        "type": "suggestion",
        "question": question,
        "language": language,
        "status": suggestion["status"],
        "answer": suggestion["answer"],
        "source": suggestion["source"],
        "match_type": "exact_qa",
        "retrieval_ms": retrieval_ms,
        "last_word_end_seconds": None,
        "from_partial": True,
    })


async def _open_speech(websocket: WebSocket, runtime: LiveRuntime, grant: LiveGrant,
                       control: TranscriptionControl) -> SpeechSession | None:
    """Watch stop/disconnect during native startup, not just after model loading."""
    selected = {"vosk": runtime.models, "faster-whisper": runtime.whisper,
                "deepgram": runtime.deepgram}[grant.provider]
    opening = asyncio.create_task(selected.open(grant.language))
    incoming = asyncio.create_task(websocket.receive())
    stopping = asyncio.create_task(control.stop.wait())
    claimed = False
    try:
        done, _ = await asyncio.wait({opening, incoming, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            await _fail(websocket, "session_finished", "The Live session is already finished")
            return None
        if incoming in done:
            message = incoming.result()
            if message.get("type") != "websocket.disconnect":
                text = message.get("text") or ""
                if len(text) > MAX_CONTROL_CHARS:
                    await _fail(websocket, "control_too_large", f"Text control is limited to {MAX_CONTROL_CHARS} characters", 1009)
                elif _is_stop_control(text):
                    await websocket.close(code=1000)
                else:
                    await _fail(websocket, "not_ready", "Wait for ready before sending PCM")
            return None
        result = await opening
        claimed = True
        return result
    finally:
        with anyio.CancelScope(shield=True):
            for task in (incoming, stopping, opening):
                if not task.done():
                    task.cancel()
            await asyncio.gather(incoming, stopping, opening, return_exceptions=True)
            if not claimed and opening.done() and not opening.cancelled() and opening.exception() is None:
                await opening.result().close()


async def _run_transcription(websocket: WebSocket, runtime: LiveRuntime, store: KnowledgeStore) -> None:
    loop = asyncio.get_running_loop()
    try:
        first = await asyncio.wait_for(websocket.receive(), timeout=runtime.handshake_timeout_seconds)
    except asyncio.TimeoutError:
        await _fail(websocket, "handshake_timeout", "A start message is required within 5 seconds")
        return
    if first.get("type") == "websocket.disconnect":
        return
    raw = first.get("text")
    if raw is None:
        await _fail(websocket, "handshake_required", "The first message must be JSON text")
        return
    if len(raw) > MAX_HANDSHAKE_CHARS:
        await _fail(websocket, "handshake_too_large", "The start message is too large", 1009)
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await _fail(websocket, "invalid_handshake", "The start message must be valid JSON")
        return
    if not isinstance(payload, dict) or payload.get("type") != "start":
        await _fail(websocket, "invalid_handshake", "Expected a start message with a token")
        return
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        await _fail(websocket, "invalid_token", "A valid Live token is required")
        return
    grant = runtime.tokens.consume(token)
    if grant is None:
        await _fail(websocket, "invalid_token", "The Live token is invalid, expired or already used")
        return
    _diagnostic("token.accepted")
    if "language" in payload and payload["language"] != grant.language:
        await _fail(websocket, "language_mismatch", "The token is bound to a different language")
        return
    if grant.provider not in {"vosk", "faster-whisper", "deepgram"}:
        await _fail(websocket, "unsupported_provider", "Unsupported speech provider")
        return
    if "provider" in payload and payload["provider"] != grant.provider:
        await _fail(websocket, "provider_mismatch", "The token is bound to a different provider")
        return
    control = TranscriptionControl()
    websocket.state.transcription_control = control
    websocket.state.session_id = grant.session_id
    runtime.transcriptions[grant.session_id] = control
    session = await asyncio.to_thread(store.get_session, grant.session_id)
    if not session or session["mode"] != "live":
        await _fail(websocket, "not_live", "The token is not bound to a Live session")
        return
    if session["finished_at"]:
        await _fail(websocket, "session_finished", "The Live session is already finished", 1008)
        return
    try:
        _diagnostic("recognizer.begin")
        speech = await _open_speech(websocket, runtime, grant, control)
        if speech is None:
            return
        websocket.state.speech_session = speech
    except SpeechUnavailable:
        await _fail(websocket, "speech_unavailable", "Selected speech provider/runtime/configuration is unavailable", 1013)
        return
    except Exception:
        await _fail(websocket, "speech_error", "Selected speech recognition could not start", 1011)
        return

    language = grant.language
    _diagnostic("recognizer.ready")
    dedupe = RecentFinalDedupe(clock=runtime.clock)
    stable_partial = StablePartialQuestion()
    generation = LiveGeneration(websocket.app.state.generation, store, grant.session_id,
                                language, websocket.send_json, websocket.state.send_lock)
    websocket.state.generation = generation
    runtime.generations[grant.session_id] = generation

    async def emit(result: FeedResult, stopping: bool) -> None:
        if _transcript_too_large(result.partial) or _transcript_too_large(result.final):
            raise SpeechFailure("transcript_too_large")
        if result.partial:
            await _send_live(websocket, {"type": "partial", "text": result.partial, "language": language})
            if grant.provider != "deepgram":
                await _emit_stable_partial_exact(websocket, store, result.partial, language, stable_partial, dedupe)
        if result.final:
            stable_partial.reset()
            await _emit_final(websocket, runtime, store, result, language, dedupe,
                              generation if not stopping and result.utterance_complete else None)

    pump = (StreamingTranscriptionPump(cast(StreamingSpeechSession, speech), emit=emit) if grant.provider == "deepgram"
            else TranscriptionPump(speech, segmented=grant.provider == "faster-whisper", emit=emit))
    websocket.state.transcription_pump = pump
    await _send_live(websocket, {
        "type": "ready",
        "session_id": grant.session_id,
        "language": language,
        "provider": grant.provider,
        "sample_rate": SAMPLE_RATE,
        "sample_format": "pcm_s16le",
        "channels": 1,
        "max_frame_bytes": runtime.max_frame_bytes,
    })

    deadline = loop.time() + runtime.session_limit_seconds
    received_pcm = False
    incoming = asyncio.create_task(websocket.receive())
    stopping = asyncio.create_task(control.stop.wait())
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await _fail(websocket, "session_limit", "The Live session time limit was reached", 4408)
                return
            done, _ = await asyncio.wait({incoming, stopping, pump.task},
                                         timeout=max(0, min(runtime.idle_timeout_seconds, remaining)),
                                         return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                await _fail(websocket, "session_finished", "The Live session is already finished")
                return
            if pump.task in done:
                await pump.task
                return
            if not done:
                if loop.time() >= deadline:
                    await _fail(websocket, "session_limit", "The Live session time limit was reached", 4408)
                else:
                    await _fail(websocket, "idle_timeout", "No audio was received before the idle timeout", 4408)
                return
            message = incoming.result()
            if message.get("type") == "websocket.disconnect":
                return
            audio = message.get("bytes")
            if audio is not None:
                if len(audio) > runtime.max_frame_bytes or len(audio) % 2:
                    await _fail(websocket, "invalid_audio", "Expected PCM16 mono frames up to 64000 bytes")
                    return
                if audio:
                    if not received_pcm:
                        received_pcm = True
                        _diagnostic("pcm.first-receipt")
                    pump.feed(audio)
                incoming = asyncio.create_task(websocket.receive())
                continue
            text = message.get("text")
            if text is not None:
                if len(text) > MAX_CONTROL_CHARS:
                    await _fail(websocket, "control_too_large", f"Text control is limited to {MAX_CONTROL_CHARS} characters", 1009)
                    return
                if not _is_stop_control(text):
                    await _fail(websocket, "unsupported_control", "Only stop is accepted as text")
                    return
                pump.stopping = True
                if grant.provider in {"faster-whisper", "deepgram"}:
                    await _close_live_work(websocket)
                else:
                    await generation.close()
                    await pump.finish()
                await websocket.close(code=1000)
                return
            incoming = asyncio.create_task(websocket.receive())
    except SpeechOverloaded:
        detail = ("Try Vosk." if grant.provider == "faster-whisper" else
                  "Check your network before restarting Deepgram." if grant.provider == "deepgram" else
                  "Check CPU load before restarting Vosk.")
        await _fail(websocket, "speech_overloaded", f"Speech inference cannot keep up; capture stopped. {detail}", 1013)
    except SpeechFailure as exc:
        if exc.args == ("transcript_too_large",):
            await _fail(websocket, "transcript_too_large", f"The transcript exceeded the {MAX_TRANSCRIPT_CHARS} character limit", 1009)
        else:
            await _fail(websocket, "speech_error", "Selected speech recognition failed or exceeded its deadline", 1011)
    except Exception:
        await _fail(websocket, "speech_error", "Selected speech recognition failed", 1011)
    finally:
        incoming.cancel()
        stopping.cancel()
        await asyncio.gather(incoming, stopping, return_exceptions=True)


router = APIRouter()


class LiveTokenRequest(BaseModel):
    language: Language
    provider: Provider = "vosk"
    # Consent is an explicit opt-in; a missing or false value is rejected by validation.
    consent: Literal[True]


@router.get("/live/status")
def live_status(request: Request):
    runtime: LiveRuntime = request.app.state.live
    vosk = runtime.models.availability()
    return {**vosk, "default_provider": "vosk",
            "providers": {"vosk": vosk, "faster-whisper": runtime.whisper.availability(),
                           "deepgram": runtime.deepgram.availability()}}


@router.post("/sessions/{session_id}/live-token")
def create_live_token(session_id: str, request: LiveTokenRequest, http_request: Request):
    store: KnowledgeStore = http_request.app.state.store
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["mode"] != "live":
        raise HTTPException(status_code=400, detail="Not a live session")
    if session["finished_at"]:
        raise HTTPException(status_code=409, detail="Session already finished")
    runtime: LiveRuntime = http_request.app.state.live
    provider = ({"vosk": runtime.models, "faster-whisper": runtime.whisper,
                 "deepgram": runtime.deepgram})[request.provider]
    status = provider.availability()
    if not status.get("languages", {}).get(request.language, {}).get("available"):
        raise HTTPException(status_code=503, detail=f"Selected provider ({request.provider}) is unavailable for {request.language}. "
                            "Check the selected runtime/model or cloud API Key; no automatic fallback.")
    token = runtime.tokens.issue(session_id, request.language, request.provider)
    return {
        "token": token,
        "session_id": session_id,
        "language": request.language,
        "provider": request.provider,
        "expires_in_seconds": int(TOKEN_TTL_SECONDS),
    }


@router.websocket("/live/transcribe")
async def live_transcribe(websocket: WebSocket):
    websocket.state.send_lock = asyncio.Lock()
    runtime: LiveRuntime = websocket.app.state.live
    store: KnowledgeStore = websocket.app.state.store
    if not _origin_and_host_allowed(websocket):
        # Close before accept: the handshake must not proceed for untrusted origins.
        await websocket.close(code=1008)
        return
    if not runtime.acquire_connection():
        await websocket.accept()
        await _fail(websocket, "busy", "Another Live transcription connection is active", 1013)
        return
    try:
        await websocket.accept()
        _diagnostic("ws.accepted")
        try:
            await _run_transcription(websocket, runtime, store)
        except asyncio.CancelledError:
            # ASGI disconnect/shutdown still runs shielded native teardown below.
            pass
        except Exception:
            # Keep the boundary free of transcript/path detail and never leak a traceback to the client.
            try:
                generation = getattr(websocket.state, "generation", None)
                if generation is not None:
                    await generation.close()
                await _send_live(websocket, {
                    "type": "error",
                    "code": "internal_error",
                    "message": "The Live connection could not continue",
                })
                await websocket.close(code=1011)
            except Exception:
                pass
    finally:
        # ASGI/AnyIO cancellation must not interrupt reaping a native worker.
        with anyio.CancelScope(shield=True):
            try:
                generation = getattr(websocket.state, "generation", None)
                if generation is not None:
                    runtime.generations.pop(generation.session_id, None)
                await _close_live_work(websocket)
            finally:
                control = getattr(websocket.state, "transcription_control", None)
                if control is not None:
                    runtime.transcriptions.pop(websocket.state.session_id, None)
                    control.closed.set()
                runtime.release_connection()
                _diagnostic("cleanup.complete")
