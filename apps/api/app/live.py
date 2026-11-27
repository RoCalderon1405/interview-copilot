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
from pydantic import BaseModel, Field, StrictBool

from .application.generation import GenerationError, GenerationService
from .application.stt import (FeedResult, SpeechUnavailable, SpeechFailure, SpeechOverloaded,
                              SpeechProvider, ProfiledSpeechProvider, SpeechSession, TranscriptionControl, TranscriptionPump,
                               StreamingSpeechSession, StreamingTranscriptionPump)
from .infrastructure.deepseek import DEEPSEEK_MODELS
from .infrastructure.vosk import VoskModelCache, MODEL_DIRECTORIES, default_models_root, _final_result
from .bootstrap import (
    cloud_llm_enabled,
    create_deepgram_provider,
    create_deepseek_generation_service,
    create_whisper_provider,
    deepseek_availability,
    windows_cloud_llm_supported,
)
from .retrieval import suggest_live
from .live_generation import LiveGeneration
from .store import KnowledgeStore
from .textnorm import normalize
from .infrastructure.technical_vocabulary import VocabularyProfile
from .infrastructure.windows_credentials import CredentialError, CredentialGate

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
    r"do you|did you|does|are you|have you|has|is|tell me|tell us about|"
    r"describe|walk me through|walk us through|explain|compare|outline|give me an example of)\b"
)
_ES_CUES = re.compile(
    r"^(?:que|como|cuando|donde|quien|cual|cuanto|puedes|podrias|me puedes|me podrias|"
    r"cuentame|cuentanos|hablame|hablanos|describe|dime|explica|explicanos|"
    r"compara|dame un ejemplo de)\b"
)

# Only marked conversational boundaries are searched inside finals. Requiring
# an auxiliary (EN) or a small set of direct-question forms (ES) avoids splitting
# subordinate clauses such as "explain how it works and why it matters".
_DIRECT_QUESTION = re.compile(
    r"^(?:(?:what|why|how|when|where|who|which)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|would|will|should|have|has)\b|"
    r"why\s+(?:use|choose|prefer|avoid|test)\b|"
    r"(?:can|could|would|will|do|did|are|have)\s+you\b|"
    r"tell me\b|tell us about\b|describe\b|walk me through\b|"
    r"walk us through\b|explain\b|compare\b|outline\b|give me an example of\b|"
    r"(?:que|cual)\s+(?:es|son)\b|por que\b|"
    r"como\s+(?:resuelves|manejas|manejarias|eliges|elegirias|implementas|"
    r"implementarias|disenas|disenarias|pruebas|probarias|funciona)\b|"
    r"puedes\b|podrias\b|me puedes\b|me podrias\b|"
    r"cuentame\b|cuentanos\b|hablame\b|hablanos\b|describe\b|dime\b|"
    r"explica\b|explicanos\b|compara\b|dame un ejemplo de\b)"
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


# Narrow, transcript-only rejection of instructions about monitoring the
# copilot's display. Such utterances appeared in the owner's real Windows
# Deepgram tests; they are not interview questions even when they start with
# "tell me". Avoid blanket topic/keyword filters: "explain screen sharing"
# or "tell me about a transcription service" may be genuine interview prompts.
_OBSERVATION_REQUEST = re.compile(
    r"^(?:(?:tell me|let me know|dime|avisame)\s+(?:if|whether|what|si|que)\b|"
    r"(?:do|can|could) you (?:see|check)\b|(?:ves|puedes ver)\b)"
)
_DISPLAY_SUBJECT = re.compile(
    r"\b(?:text|texto|transcript|transcription|transcripcion|screen|pantalla)\b"
)
_DISPLAY_OBSERVATION = re.compile(
    r"\b(?:appear|appears|appearing|show|shows|showing|see|display|displayed|"
    r"visible|aparece|aparecen|muestra|muestran|ves|ver)\b|show up|se ve"
)

# Exact whole-candidate phrases only. Topic words, negations and contextual
# suffixes must not be treated as greetings or microphone checks.
_NON_INTERVIEW_UTTERANCES = frozenset({
    "hello", "hi", "how are you", "how are you doing",
    "hola", "buenos dias", "como estas", "como estan",
    "can you hear me", "can you hear me now", "can you hear us", "do you hear me",
    "is my microphone working", "is my mic working",
    "me escuchas", "me oyes", "me escuchas ahora", "puedes oirme",
    "puedes escucharme", "funciona mi microfono",
})
_HARMLESS_QUESTION_INTRO = re.compile(
    r"^(?:(?:just\s+)?(?:(?:a|one)\s+)?quick\s+question|"
    r"(?:s[oó]lo\s+)?una\s+pregunta(?:\s+r[aá]pida)?)"
    r"(?:\s*[,;:—-]\s*|\s+)",
    re.IGNORECASE,
)


def _clean_question_start(text: str) -> str:
    """Remove one harmless introduction only before a recognizable request.

    Shared by partial/final candidates, not the original transcript or shared
    RAG normalizer. Never search arbitrary prose for an embedded question.
    """
    text = _QUESTION_INTRO.sub("", _LEADING_FILLER.sub("", text.strip()), count=1).strip()
    intro = _HARMLESS_QUESTION_INTRO.match(text)
    if intro:
        suffix = text[intro.end():].strip()
        key = normalize(suffix)
        if (_EN_CUES.match(key) or _ES_CUES.match(key) or _DIRECT_QUESTION.match(key)
                or key in _NON_INTERVIEW_UTTERANCES):
            return suffix
    return text


def _is_capture_observation_request(text: str) -> bool:
    """Reject clearly operational display checks, not generic interview prompts.

    This is deliberately conservative: text alone cannot identify the speaker,
    and a technical question about a UI may be ambiguous. The check runs on
    both partial and final candidates but never hides the transcript itself.
    """
    normalized = normalize(text)
    return bool(
        _OBSERVATION_REQUEST.match(normalized)
        and _DISPLAY_SUBJECT.search(normalized)
        and _DISPLAY_OBSERVATION.search(normalized)
    )


@dataclass(frozen=True)
class LiveGrant:
    session_id: str
    language: str
    expires_at: float
    provider: str = "vosk"
    vocabulary_profile: str = "general"
    # The LLM choice is independent of STT and immutable for this connection.
    llm_provider: str = "ollama"
    llm_model: str | None = None
    llm_consent: bool = False


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
        chunk = _clean_question_start(raw)
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
        if key in _NON_INTERVIEW_UTTERANCES or _is_capture_observation_request(candidate):
            continue
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
                preceding = normalize(_clean_question_start(scan[segment_start:boundary.start()]))
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
            prefix = _clean_question_start(visible)
            normalized = normalize(prefix)
            if not (_EN_CUES.match(normalized) or _ES_CUES.match(normalized)
                    or _DIRECT_QUESTION.match(normalized)
                    or visible.rstrip().endswith("?")):
                continue
            candidate = _clean_question_start(segment).rstrip(" \t?!.;,").strip()
            key = normalize(candidate)
            if key in _NON_INTERVIEW_UTTERANCES or _is_capture_observation_request(candidate):
                continue
            if not key or key in seen:
                continue
            if len(candidates) >= limit:
                return candidates
            seen.add(key)
            candidates.append(candidate)
        sentence_start = next_start
    return candidates


def _single_question_candidate(text: str, limit: int = 1) -> list[str]:
    """Return one candidate without splitting a coordinated compound request.

    Used only for an assembled Deepgram behavioral request, where the shared
    detector would cut the coordinated follow-up ("... What was slow and what
    did you change") into a second question. The same gates still apply: a
    request cue or direct question is required, quoted text cannot create the
    candidate, and operational display checks, reported speech, greetings and
    the candidate limit are unchanged.
    """
    if limit < 1:
        return []
    visible = _QUOTED_TEXT.sub(lambda match: " " * len(match.group()), text)
    prefix = _clean_question_start(visible)
    normalized = normalize(prefix)
    if not (_EN_CUES.match(normalized) or _ES_CUES.match(normalized)
            or _DIRECT_QUESTION.match(normalized) or visible.rstrip().endswith("?")):
        return []
    if _REPORTED_SPEECH.search(normalize(visible)):
        return []
    candidate = _clean_question_start(text).rstrip(" \t?!.;,").strip()
    key = normalize(candidate)
    if not key or key in _NON_INTERVIEW_UTTERANCES or _is_capture_observation_request(candidate):
        return []
    return [candidate]


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


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Deepgram candidate assembly (connection-local, after the raw relay)
# ---------------------------------------------------------------------------

# Deepgram Nova-3 finalizes each endpoint separately (the configured 300 ms
# endpointing), so a natural pause can split one spoken question into two finals.
# These bounds keep a truncated fragment from being retrieved as a question and
# keep every hold strictly limited.
MAX_ASSEMBLED_QUESTION_CHARS = 240
MAX_ASSEMBLED_FRAGMENTS = 3
ASSEMBLY_MAX_GAP_SECONDS = 8.0
# A behavioral request ("tell me about a time when ...") is complete once its
# relative clause arrives, but its coordinated follow-up ("and what did you
# change") usually lands on the next endpoint. Only that one accumulated
# behavioral request is stabilized for a short bounded window; no other question
# is delayed. The absolute cap keeps repeated noise from extending the window.
ASSEMBLY_SETTLE_SECONDS = 1.0
ASSEMBLY_SETTLE_MAX_SECONDS = 2.0

# Provider punctuation ends an endpoint, not the thought.
_ASSEMBLY_EDGE_PUNCTUATION = "?!.;,…—–-"

# Noise that may appear between two fragments of the same spoken question.
_ASSEMBLY_FILLERS = frozenset({
    "um", "uh", "erm", "hmm", "mm", "ah", "oh", "eh", "right", "okay", "ok",
    "bueno", "pues", "este", "verdad", "so", "and", "y", "entonces",
})
# Words that open a request frame but carry no answerable content on their own.
# Predicate-like fillers ("okay", "well", "now") stay out, so ordinary yes/no
# questions such as "Is that okay?" are never held as incomplete.
_ASSEMBLY_FRAME_TOKENS = frozenset({
    "so", "and", "or", "but", "then", "also", "just", "please",
    "could", "can", "would", "will", "do", "does", "did",
    "are", "is", "was", "were", "have", "has", "you", "your", "me", "us", "we",
    "i", "tell", "explain", "describe", "walk", "through", "give", "example",
    "of", "about", "with", "for", "to", "a", "an", "the", "what", "why", "how",
    "when", "where", "which", "who", "whom", "whose", "let", "ask", "question",
    "questions", "difference", "first", "second",
    "puedes", "podrias", "nos", "cuentame", "cuentanos", "contarme", "contarnos",
    "contarte", "hablame", "hablanos", "hablarte", "explica", "explicame",
    "explicarte", "explicanos", "describeme", "decirme", "dime", "compara",
    "dame", "un", "una", "unos", "unas", "ejemplo", "de", "del", "sobre", "o",
    "pero", "bueno", "pues", "este", "que", "cual", "cuales", "como", "cuando",
    "donde", "quien", "cuanto", "por", "si", "tu", "tus", "su", "sus", "es",
    "son", "era", "eran", "hay", "tienes", "tiene", "haces", "harias",
    "manejas", "manejarias", "funciona", "diferencia", "primero", "segundo",
})
# Words that cannot end a question: the final still expects more speech.
_ASSEMBLY_TRAILING_WORDS = frozenset({
    "and", "or", "but", "so", "because", "to", "of", "the", "a", "an", "that",
    "much", "many", "long", "often",
    "y", "o", "pero", "de", "del", "el", "la", "los", "las", "un", "una",
    "para", "con", "porque", "entonces", "cuanto", "cuanta",
})
# "the difference between rest" needs its second term before it is answerable.
_ASSEMBLY_COMPARISON_JOINERS = frozenset({"and", "or", "versus", "vs", "to", "y", "o"})
# A yes/no question with a subject and a predicate is complete even when every
# word also belongs to the frame vocabulary ("Is that okay?").
_ASSEMBLY_YES_NO_QUESTION = re.compile(
    r"^(?:is|are|was|were|am|do|does|did|can|could|would|will|should|has|have)\s+"
    r"(?:you|we|they|he|she|it|this|that|these|those|there|i)\s+\S"
)
# Explicit introduction/context. The words before it must also be content-free,
# so a complete question followed by "next question" is never held.
_ASSEMBLY_INTRO_TAILS = (
    "here s the question", "here s my question", "here s a question",
    "here is the question", "the question is", "my question is",
    "the next question is", "next question is", "next question",
    "i have a question", "i have one question", "i have another question",
    "i have a couple of questions", "i have two questions",
    "i have a quick question", "we have a question", "a quick question",
    "one quick question", "let me ask you a question", "let me ask you",
    "let me ask", "may i ask", "can i ask",
    "la pregunta es", "mi pregunta es", "una pregunta", "una pregunta rapida",
    "la siguiente pregunta es", "siguiente pregunta",
    "tengo una pregunta", "tengo un par de preguntas", "tengo otra pregunta",
    "dejame hacerte una pregunta", "te hago una pregunta",
)
# Only these introductions can be joined: the shared detector already splits
# them as a final boundary, so the candidate excludes the introductory words.
_ASSEMBLY_BOUNDARY_INTROS = frozenset({
    "here s the question", "here s my question", "the question is",
    "my question is", "next question", "la pregunta es", "mi pregunta es",
    "siguiente pregunta",
})
# Narrow anchored indirect prompts. Only an explicit wh-complement is used as
# the candidate; the transcript keeps the full original wording.
_ASSEMBLY_INDIRECT_FRAME = re.compile(
    r"^(?:(?:i|we)(?:['’]?d| would)\s+like to\s+(?:know|understand|hear)"
    r"|(?:i|we)\s+want to know"
    r"|i(?:['’]?m| am)\s+curious about"
    r"|me\s+gustar[ií]a\s+(?:saber|entender|conocer)"
    r"|nos\s+gustar[ií]a\s+(?:saber|entender)"
    r"|quisiera\s+(?:saber|entender)"
    r"|quiero\s+saber"
    r"|me\s+interesa\s+saber)\b[\s,:;—–-]*",
    re.IGNORECASE,
)
_ASSEMBLY_WH_START = re.compile(
    r"^(?:what|why|how|when|where|which|who|whom|whose|"
    r"que|cual|cuales|como|cuando|donde|quien|cuanto|por que)\b"
)
_ASSEMBLY_CONDITIONAL_START = re.compile(r"^(?:if|whether|si)\b")
# English auxiliaries right after a wh-word mark an independent question. Spanish
# has no such inversion, so "cómo funciona X" stays a valid subordinate clause.
_ASSEMBLY_EN_AUXILIARY = frozenset({
    "am", "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "would", "will", "should", "shall", "may", "might", "must", "has", "have",
    "had",
})
# Sentence subjects: a short fragment that starts with one is prose, not a complement.
_ASSEMBLY_SUBJECT_PRONOUNS = frozenset({
    "i", "we", "they", "he", "she", "it", "you", "yo", "nosotros", "nosotras",
    "ellos", "ellas", "usted", "ustedes",
})
# A held fragment that stops on an auxiliary or modal has an open verb slot.
_ASSEMBLY_OPEN_SLOT_ENDINGS = frozenset({
    "am", "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "would", "will", "should", "shall", "may", "might", "must", "has", "have",
    "had", "harias", "haria", "haras", "hara", "podrias", "podria",
    "deberias", "deberia",
})
# Behavioral context tails: the request has not asked anything answerable until
# its relative clause arrives ("Can you tell me about a time" + "when ...",
# "Cuéntame sobre una vez" + "que ..."). Longest tail first.
_ASSEMBLY_BEHAVIORAL_TAILS = tuple(sorted({
    "about a time", "about a situation", "about an occasion", "about a moment",
    "about a time when", "a time when", "a time where", "a situation where",
    "an occasion when", "a moment when", "about a time that",
    "sobre una vez", "sobre una ocasion", "sobre una situacion",
    "sobre un momento", "de una vez que", "de una ocasion en la que",
    "de una situacion en la que", "alguna vez", "una vez", "una ocasion",
    "una situacion",
}, key=len, reverse=True))
# Interrogative words that can end an unfinished coordinated follow-up
# ("and what", "y qué"). They are not content by themselves.
_ASSEMBLY_WH_WORDS = frozenset({
    "what", "why", "how", "when", "where", "which", "who", "whom", "whose",
    "que", "cual", "cuales", "como", "cuando", "donde", "quien", "cuanto",
})
# A coordinated follow-up continues the same behavioral request: a bare
# conjunction plus an interrogative ("and what did you change", "y qué
# cambiaste"). A separate question with its own subject or topic is not matched.
_ASSEMBLY_COORDINATED_FOLLOW_UP = re.compile(
    r"^(?:and|y)\s+(?:what|why|how|when|where|which|who|whom|whose|"
    r"por que|que|cual|cuales|como|cuando|donde|quien|cuanto)\b"
)
# A second direct question left uncoordinated inside one accumulated fragment
# ("... a back end service What was slow"). Provider punctuation is missing in
# real Nova-3 finals, so this lexical signal is the conservative ambiguity mark.
_ASSEMBLY_EMBEDDED_QUESTION = re.compile(
    r"\b(?:(?:what|why|how|when|where|which|who)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|would|will|should|has|have)\b|"
    r"(?:que|cual|cuales|como|cuando|donde|quien|cuanto)\s+"
    r"(?:es|son|era|eran|fue|fueron|esta|estan|hay|tiene|tienen)\b)"
)
# Openings that make a complement a noun phrase instead of a clause.
_ASSEMBLY_DETERMINER_START = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "some", "any", "both",
    "each", "every", "no", "your", "their", "our", "its", "his", "her", "my",
    "about", "with", "between", "in", "on", "for", "to", "of", "from", "under",
    "over", "across",
    "el", "la", "los", "las", "un", "una", "unos", "unas", "este", "esta",
    "estos", "estas", "ese", "esa", "mi", "mis", "tu", "tus", "su", "sus",
    "nuestro", "nuestra", "sobre", "entre", "con", "sin", "para", "por", "en",
    "de", "del",
})
# High-frequency finite verb forms, used only to reject clause-shaped prose.
_ASSEMBLY_FINITE_FORMS = frozenset({
    "failed", "fails", "works", "worked", "broke", "breaks", "went", "goes",
    "came", "comes", "made", "makes", "took", "takes", "got", "gets", "gave",
    "gives", "found", "finds", "kept", "left", "ran", "runs", "saw", "says",
    "said", "told", "thought", "brought", "built", "became", "seems", "looks",
    "appears", "needs", "uses", "used", "happened", "changed", "stopped",
    "started", "migrated", "deployed",
    "es", "son", "era", "eran", "fue", "fueron", "esta", "estan", "hay",
    "tiene", "tienen", "hace", "hacen", "funciona", "funcionan", "fallo",
    "fallaron", "trabaja", "trabajan", "trabajamos", "estuve", "estuvo",
    "tenemos", "hemos", "hicimos",
})


def _assembly_filler_only(key: str) -> bool:
    """True when the normalized final contains only filler or connective noise."""
    return all(token in _ASSEMBLY_FILLERS for token in key.split())


def _assembly_intro_prefix(key: str) -> str | None:
    """Return the words preceding an explicit introduction, or None."""
    for tail in _ASSEMBLY_INTRO_TAILS:
        if key == tail:
            return ""
        if key.endswith(" " + tail):
            return key[: -(len(tail) + 1)]
    return None


def _assembly_yes_no_question(key: str) -> bool:
    """True for a complete yes/no question even when built from frame words."""
    match = _ASSEMBLY_YES_NO_QUESTION.match(key)
    return bool(match and key.split()[2] not in _ASSEMBLY_FRAME_TOKENS)


def _assembly_incomplete_syntax(key: str) -> bool:
    """Detect that a final still expects more speech (narrow, lexical rules)."""
    tokens = key.split()
    if not tokens:
        return True
    if tokens[-1] in _ASSEMBLY_TRAILING_WORDS or tokens[-1] in _ASSEMBLY_OPEN_SLOT_ENDINGS:
        return True
    for opener in ("between", "entre"):
        if opener in tokens:
            rest = tokens[tokens.index(opener) + 1:]
            if not any(token in _ASSEMBLY_COMPARISON_JOINERS for token in rest):
                return True
    return False


def _assembly_behavioral_context(key: str) -> bool:
    """True when a request stops on an unfinished behavioral context tail.

    The words before the tail must be content-free request frame words, so
    "tell me about a time" and "cuéntame sobre una vez" hold while prose such as
    "we were talking about a time" does not.
    """
    for tail in _ASSEMBLY_BEHAVIORAL_TAILS:
        if key == tail:
            return False
        if not key.endswith(" " + tail):
            continue
        prefix = key[: -(len(tail) + 1)]
        tokens = prefix.split()
        return bool(tokens) and set(tokens) <= _ASSEMBLY_FRAME_TOKENS
    return False


def _assembly_coordinated_follow_up(key: str) -> bool:
    """True for "and what did you change"-shaped continuations of a request."""
    return bool(_ASSEMBLY_COORDINATED_FOLLOW_UP.match(key))


def _assembly_coordinated_incomplete(key: str) -> bool:
    """True when a coordinated follow-up stops before its verb is spoken.

    "and what did you" and "y qué" still expect a predicate; emitting them would
    produce an unanswerable compound. The check is lexical and deliberately
    narrow to the coordinated form, not general parsing.
    """
    tokens = key.split()
    if not tokens or tokens[-1] in _ASSEMBLY_WH_WORDS:
        return True
    return (len(tokens) >= 2 and tokens[-2] in _ASSEMBLY_EN_AUXILIARY
            and tokens[-1] in _ASSEMBLY_SUBJECT_PRONOUNS)


def _assembly_embedded_question(key: str) -> bool:
    """True when a second, uncoordinated direct question starts inside the text.

    An expected coordinated follow-up ("and what did you change") is ignored.
    This is an ambiguity signal, not a sentence boundary: it only prevents
    elapsed quiet from being treated as completion.
    """
    for match in _ASSEMBLY_EMBEDDED_QUESTION.finditer(key):
        before = key[:match.start()].rstrip()
        if not before:
            continue
        if before.rsplit(" ", 1)[-1] in {"and", "y", "or", "o"}:
            continue
        return True
    return False


def _assembly_compound_complete(key: str) -> bool:
    """Return True only for positive completion evidence of a settled compound.

    Provider punctuation is not evidence: it ends an endpoint, not the thought.
    Completion requires closed syntax, no unfinished coordinated suffix and no
    second uncoordinated direct question ("... a service What was slow"). The
    coordinated follow-up itself is the explicit completion when it arrives and
    is joined by the caller without this check.
    """
    return (_assembly_hold_kind(key) is None
            and not _assembly_coordinated_incomplete(key)
            and not _assembly_embedded_question(key))


def _assembly_hold_kind(key: str) -> str | None:
    """Classify an incomplete final by shape; None means it can stand alone."""
    if not key or key in _NON_INTERVIEW_UTTERANCES:
        return None
    if _assembly_yes_no_question(key):
        return None
    intro_prefix = _assembly_intro_prefix(key)
    if intro_prefix is not None and (not intro_prefix or set(intro_prefix.split()) <= _ASSEMBLY_FRAME_TOKENS):
        return "intro"
    if _assembly_behavioral_context(key):
        return "behavioral"
    tokens = key.split()
    if all(token in _ASSEMBLY_FRAME_TOKENS for token in tokens):
        return "wh" if _ASSEMBLY_WH_START.match(key) else "request"
    if _assembly_incomplete_syntax(key):
        return "trailing"
    return None


def _assembly_continuation_shape(key: str, *, sentence_ended: bool = False) -> str | None:
    """Recognize a positive continuation shape: subordinate wh or noun phrase.

    Anything else - an independent question, a clause-shaped statement or
    arbitrary prose - returns None and must never be merged into a hold. A short
    fragment is only accepted as a noun phrase when it is not a subject-leading
    sentence and the provider did not end it as an explicit sentence.
    """
    tokens = key.split()
    if not tokens:
        return None
    if tokens[0] in _ASSEMBLY_EN_AUXILIARY:
        return None  # "Is that all?", "Does it cost?": an independent yes/no question
    if _ASSEMBLY_WH_START.match(key):
        if len(tokens) > 1 and tokens[1] in _ASSEMBLY_EN_AUXILIARY:
            return None
        return "wh"
    if tokens[0] in _ASSEMBLY_DETERMINER_START:
        if len(tokens) > 8:
            return None
        if any(token in _ASSEMBLY_EN_AUXILIARY or token in _ASSEMBLY_FINITE_FORMS
               for token in tokens[1:]):
            return None
        return "np"
    if sentence_ended or tokens[0] in _ASSEMBLY_SUBJECT_PRONOUNS:
        return None  # "I agree." and other short prose are not complements
    if len(tokens) <= 3 and not any(token in _ASSEMBLY_FINITE_FORMS for token in tokens):
        return "np"
    return None


def _assembly_open_verb_slot(pending: str | None) -> bool:
    """True when the held fragment stops on an auxiliary or modal verb slot."""
    tokens = normalize(pending or "").split()
    return bool(tokens) and tokens[-1] in _ASSEMBLY_OPEN_SLOT_ENDINGS


def _assembly_commands_continuation(key: str, sentence_ended: bool) -> bool:
    """Accept a narrow verb phrase as the complement of an open verb slot.

    Only used after a held fragment that already stopped on an auxiliary
    ("how you would"), so ordinary statements, independent questions and
    sentence-ended prose remain excluded.
    """
    tokens = key.split()
    if not tokens or sentence_ended or len(tokens) > 6:
        return False
    if tokens[0] in _ASSEMBLY_SUBJECT_PRONOUNS or tokens[0] in _ASSEMBLY_EN_AUXILIARY:
        return False
    return not any(token in _ASSEMBLY_FINITE_FORMS for token in tokens)


def _assembly_indirect(text: str) -> tuple[bool, str]:
    """Split a narrow anchored indirect prompt; the complement is '' when absent."""
    match = _ASSEMBLY_INDIRECT_FRAME.match(text)
    if not match:
        return False, ""
    return True, text[match.end():].strip()


@dataclass(frozen=True)
class AssembledCandidate:
    """One Deepgram candidate decision produced by ``DeepgramQuestionAssembly``.

    ``compound`` marks a behavioral request assembled from a context tail, its
    relative clause and an optional coordinated follow-up: the shared detector
    must not split that follow-up into a second question.
    """

    text: str
    compound: bool = False


class DeepgramQuestionAssembly:
    """Hold one clearly incomplete Deepgram final and join it with the next final.

    Deepgram finalizes per endpoint, so a 300 ms pause can cut a spoken question
    in half. This helper is connection-local and runs after the raw transcript is
    relayed: transcript events and their order never change, and a held fragment
    is discarded rather than emitted as a question. A join requires a positive
    shape: a subordinate wh clause ("how authentication works"), a narrow noun
    phrase for an open object slot ("OAuth"), an explicit wh-complement after a
    narrow indirect prompt ("I'd like to know how ...") or a relative clause
    after a behavioral context tail ("about a time", "una vez"). Independent
    questions and clause-shaped prose are never concatenated: the held fragment
    is dropped and only the new final is considered. A join that is still
    incomplete ("the difference between rest") keeps holding within the same
    bounds.

    A behavioral context completed by its relative clause is a compound request
    whose coordinated follow-up ("and what did you change") usually arrives on
    the next endpoint. That one accumulated candidate is stabilized instead of
    being emitted immediately. A completed compound uses the short
    ``ASSEMBLY_SETTLE_SECONDS`` window (absolute cap
    ``ASSEMBLY_SETTLE_MAX_SECONDS``); an ambiguous one - an unfinished
    coordinated suffix or a second uncoordinated question inside the fragment -
    stays joinable up to ``ASSEMBLY_MAX_GAP_SECONDS`` only. When that deadline
    expires, an ambiguous candidate is dropped rather than retrieved: elapsed
    quiet and provider punctuation are not completion evidence. The deadline
    belongs to the caller: ``settle_deadline`` reports the remaining time and
    ``take_settled`` consumes a completed candidate, so no background timer is
    created here and a discarded hold is never flushed.

    Bounds are explicit: ``MAX_ASSEMBLED_QUESTION_CHARS``,
    ``MAX_ASSEMBLED_FRAGMENTS``, ``ASSEMBLY_MAX_GAP_SECONDS`` measured at the
    next final only, and the settle window above. The rules are lexical
    heuristics, not semantic understanding: a fragment that ends on a content
    word ("Explain why the database") cannot be recognized as truncated.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._pending: str | None = None
        self._kind = ""
        self._fragments = 0
        self._pending_at = 0.0
        self._settle_at = 0.0

    def observe(self, text: str) -> list[AssembledCandidate]:
        """Return the ordered candidates to evaluate now; usually none or one.

        A settled compound and the unrelated final that arrives after its window
        are both returned, oldest first, so neither question is lost.
        """
        text = text.strip()
        if not text:
            return []
        now = self.clock()
        if self._pending is not None and now - self._pending_at > ASSEMBLY_MAX_GAP_SECONDS:
            self.reset()
        key = normalize(text)
        if not key:
            return []
        if _assembly_filler_only(key):
            # Filler noise between fragments keeps a hold but never creates one.
            return []
        framed, complement = _assembly_indirect(text)
        if framed:
            self.reset()
            complement_key = normalize(complement)
            if (complement and (_ASSEMBLY_WH_START.match(complement_key)
                                or _ASSEMBLY_CONDITIONAL_START.match(complement_key))):
                if _assembly_hold_kind(complement_key) is not None:
                    # The complement is itself truncated: hold it, never retrieve it.
                    return self._hold(complement, "indirect", now)
                if len(complement) <= MAX_ASSEMBLED_QUESTION_CHARS:
                    return [AssembledCandidate(complement.rstrip(_ASSEMBLY_EDGE_PUNCTUATION))]
                return []
            if not complement:
                return self._hold(text, "indirect", now)
            return []
        if self._pending is None:
            return self._start(text, key, now)
        if key == normalize(self._pending):
            return []
        return self._continue(text, key, now)

    def reset(self) -> None:
        """Discard the held fragment; stop, restart and errors never flush it."""
        self._pending = None
        self._kind = ""
        self._fragments = 0
        self._pending_at = 0.0
        self._settle_at = 0.0

    def settle_deadline(self) -> float | None:
        """Remaining seconds before the settled compound is resolved, or None.

        A completed compound uses the short stabilization window. An ambiguous
        one stays joinable up to the normal gap bound; its expiry drops it
        instead of delivering a possibly incomplete prefix.
        """
        if self._kind != "settle" or self._pending is None:
            return None
        if _assembly_compound_complete(normalize(self._pending)):
            deadline = min(self._pending_at + ASSEMBLY_SETTLE_SECONDS,
                           self._settle_at + ASSEMBLY_SETTLE_MAX_SECONDS)
        else:
            deadline = self._pending_at + ASSEMBLY_MAX_GAP_SECONDS
        return max(0.0, deadline - self.clock())

    def take_settled(self) -> AssembledCandidate | None:
        """Consume a completed settled compound; drop an ambiguous one.

        Expiry is not completion: an ambiguous accumulated fragment is discarded
        without retrieval, dedupe or generation.
        """
        if self._kind != "settle" or self._pending is None:
            return None
        if not _assembly_compound_complete(normalize(self._pending)):
            self.reset()
            return None
        candidate = AssembledCandidate(self._pending, compound=True)
        self.reset()
        return candidate

    def _continue(self, text: str, key: str, now: float) -> list[AssembledCandidate]:
        clean = _clean_question_start(text)
        clean_key = normalize(clean)
        sentence_ended = text.rstrip().endswith(".")
        if self._kind == "settle":
            if _assembly_coordinated_follow_up(key):
                return self._join_coordinated(text, now)
            pending_key = normalize(self._pending or "")
            if (_assembly_coordinated_incomplete(pending_key)
                    and _assembly_commands_continuation(clean_key, sentence_ended)):
                return self._join(text, now)
            # A different final arrived first. Only a completed compound may be
            # emitted; an ambiguous one is dropped, never retrieved as a prefix.
            settled = self._pending or ""
            complete = _assembly_compound_complete(normalize(settled))
            self.reset()
            prefix = [AssembledCandidate(settled, compound=True)] if complete else []
            return [*prefix, *self._start(text, key, now)]
        if _assembly_hold_kind(clean_key) == "intro":
            # A new explicit introduction ends the previous thought.
            self.reset()
            return self._start(text, key, now)
        shape = _assembly_continuation_shape(clean_key, sentence_ended=sentence_ended)
        commands = (_assembly_open_verb_slot(self._pending)
                    and _assembly_commands_continuation(clean_key, sentence_ended))
        if self._kind == "indirect":
            framed, complement = _assembly_indirect(self._pending or "")
            if framed and not complement:
                # A bare frame carries no content: evaluate the new final alone,
                # through the same hold/complete logic as any other final.
                self.reset()
                return self._start(text, key, now)
            if shape is None and not commands:
                self.reset()
                return self._start(text, key, now)
            return self._join(text, now)
        if shape is None and not commands:
            self.reset()
            return self._start(text, key, now)
        if shape is not None and self._kind == "wh" and shape == "wh":
            self.reset()
            return self._start(text, key, now)
        if self._kind == "intro" and (shape != "wh" or not self._boundary_intro()):
            self.reset()
            return self._start(text, key, now)
        return self._join(text, now)

    def _join(self, text: str, now: float) -> list[AssembledCandidate]:
        """Bounded join; a still-incomplete result keeps holding."""
        combined = f"{self._pending} {text}"
        if not self._bounded(combined):
            self.reset()
            return self._start(text, normalize(text), now)
        if _assembly_hold_kind(normalize(combined)) is not None:
            self._pending = combined.rstrip(_ASSEMBLY_EDGE_PUNCTUATION)
            self._fragments += 1
            self._pending_at = now
            return []
        if self._kind == "behavioral":
            # The relative clause completed the behavioral request, but one
            # coordinated follow-up may still follow: settle it, never evaluate
            # the fragments separately. Provider punctuation is not completion
            # evidence: a period ends the endpoint, not the thought, so a
            # sentence-ended clause is stabilized exactly like an unpunctuated one.
            self._pending = combined.rstrip(_ASSEMBLY_EDGE_PUNCTUATION)
            self._kind = "settle"
            self._fragments += 1
            self._pending_at = now
            self._settle_at = now
            return []
        compound = self._kind in {"behavioral", "settle"}
        self.reset()
        return [AssembledCandidate(combined, compound=compound)]

    def _join_coordinated(self, text: str, now: float) -> list[AssembledCandidate]:
        """Append the coordinated follow-up and emit the compound request once."""
        combined = f"{self._pending} {text}"
        if not self._bounded(combined):
            self.reset()
            return self._start(text, normalize(text), now)
        combined = combined.rstrip(_ASSEMBLY_EDGE_PUNCTUATION)
        if (_assembly_hold_kind(normalize(combined)) is not None
                or _assembly_coordinated_incomplete(normalize(combined))):
            # The follow-up itself is truncated ("and what did you"): keep the
            # one hold instead of emitting an incomplete compound. The ordinary
            # fragment bound still applies.
            self._pending = combined
            self._fragments += 1
            self._pending_at = now
            return []
        self.reset()
        return [AssembledCandidate(combined, compound=True)]

    def _start(self, text: str, key: str, now: float) -> list[AssembledCandidate]:
        kind = _assembly_hold_kind(key)
        if kind is None:
            return [AssembledCandidate(text)]
        return self._hold(text, kind, now)

    def _hold(self, text: str, kind: str, now: float) -> list[AssembledCandidate]:
        if len(text) > MAX_ASSEMBLED_QUESTION_CHARS:
            return []
        # Provider punctuation ends the endpoint, not the thought: drop it from the
        # held fragment so a join never creates a sentence boundary. The relayed
        # transcript keeps the original wording and punctuation.
        self._pending = text.rstrip(_ASSEMBLY_EDGE_PUNCTUATION)
        self._kind = kind
        self._fragments = 1
        self._pending_at = now
        self._settle_at = 0.0
        return []

    def _bounded(self, combined: str) -> bool:
        return (len(combined) <= MAX_ASSEMBLED_QUESTION_CHARS
                and self._fragments < MAX_ASSEMBLED_FRAGMENTS)

    def _boundary_intro(self) -> bool:
        key = normalize(self._pending or "")
        return any(key == tail or key.endswith(" " + tail) for tail in _ASSEMBLY_BOUNDARY_INTROS)


@dataclass
class AssemblySettleWindow:
    """One connection-owned stabilization deadline for a settled compound.

    ``delivering`` becomes true once the deadline elapsed and the candidate is
    being emitted, so a newer final never cancels a delivery that already
    started. The task is always owned (and drained) by the connection.
    """

    task: asyncio.Task | None = None
    delivering: bool = False


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

    def issue(self, session_id: str, language: str, provider: str = "vosk",
              vocabulary_profile: str = "general", llm_provider: str = "ollama",
              llm_model: str | None = None, llm_consent: bool = False) -> str:
        with self._lock:
            now = self.clock()
            self._prune(now)
            for token in [key for key, grant in self._tokens.items() if grant.session_id == session_id]:
                del self._tokens[token]
            if len(self._tokens) >= self.capacity:
                self._tokens.pop(next(iter(self._tokens)))
            token = secrets.token_urlsafe(32)
            self._tokens[token] = LiveGrant(
                session_id, language, now + self.ttl_seconds, provider, vocabulary_profile,
                llm_provider, llm_model, llm_consent,
            )
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
                 deepgram: ProfiledSpeechProvider | None = None):
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

    @property
    def connection_active(self) -> bool:
        """Report capture contention without exposing or acquiring the Live connection slot."""
        with self._connection_lock:
            return self._connection_active


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
    # A pending assembly deadline must never emit after stop, error or disconnect.
    settle = getattr(websocket.state, "assembly_settle", None)
    tasks = []
    if settle is not None:
        websocket.state.assembly_settle = None
        if settle.task is not None:
            settle.task.cancel()
            tasks.append(settle.task)
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


async def _send_final_transcript(websocket: WebSocket, result: FeedResult, text: str, language: str) -> None:
    """Relay one provider final verbatim; assembly never edits transcript order."""
    await _send_live(websocket, {
        "type": "final",
        "text": text,
        "language": language,
        "last_word_end_seconds": result.last_word_end_seconds,
        **({"end_of_speech_latency_ms": result.end_of_speech_latency_ms}
           if result.end_of_speech_latency_ms is not None else {}),
    })


async def _emit_questions(
    websocket: WebSocket,
    store: KnowledgeStore,
    text: str,
    result: FeedResult,
    language: str,
    dedupe: RecentFinalDedupe,
    generation: LiveGeneration | None = None,
    *,
    split: bool = True,
) -> None:
    """Run the unchanged detector, dedupe, retrieval and generation path.

    ``split`` is False only for one assembled compound behavioral request, where
    the shared detector would cut its coordinated follow-up into a second
    question. Dedupe, retrieval, provenance and generation are unchanged.
    """
    questions = detect_questions(text) if split else _single_question_candidate(text)
    for question in questions:
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


async def _emit_final(
    websocket: WebSocket,
    store: KnowledgeStore,
    result: FeedResult,
    language: str,
    dedupe: RecentFinalDedupe,
    generation: LiveGeneration | None = None,
) -> None:
    text = (result.final or "").strip()
    if not text:
        return
    await _send_final_transcript(websocket, result, text, language)
    await _emit_questions(websocket, store, text, result, language, dedupe, generation)


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


def _connection_generation_service(websocket: WebSocket, grant: LiveGrant) -> GenerationService:
    """Snapshot the grant-selected LLM for this connection without fallback.

    Local Ollama keeps the existing application-owned service and environment
    semantics. DeepSeek is built from the local key at connection start; a
    missing/invalid key yields an unconfigured service so documentary retrieval
    remains usable and generation reports ``not_configured`` without a call.
    """
    if grant.llm_provider == "ollama":
        service = getattr(websocket.app.state, "generation", None)
        return service if service is not None else GenerationService(enabled=True)
    if (grant.llm_provider == "deepseek" and grant.llm_consent
            and isinstance(grant.llm_model, str) and grant.llm_model in DEEPSEEK_MODELS):
        try:
            return create_deepseek_generation_service(grant.llm_model)
        except GenerationError:
            return GenerationService(enabled=True)
    return GenerationService(enabled=True)


async def _open_speech(websocket: WebSocket, runtime: LiveRuntime, grant: LiveGrant,
                       control: TranscriptionControl) -> SpeechSession | None:
    """Watch stop/disconnect during native startup, not just after model loading."""
    selected = {"vosk": runtime.models, "faster-whisper": runtime.whisper,
                "deepgram": runtime.deepgram}[grant.provider]
    # Only the opt-in cloud recognizer accepts a vocabulary profile.
    opening = (asyncio.create_task(runtime.deepgram.open(grant.language, vocabulary_profile=grant.vocabulary_profile))
               if grant.provider == "deepgram" else asyncio.create_task(selected.open(grant.language)))
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
    # The LLM grant is immutable for this connection. Cloud use additionally
    # requires explicit consent and one adapter-approved model, even if a token
    # was created outside the HTTP route.
    if grant.llm_provider not in {"ollama", "deepseek"}:
        await _fail(websocket, "unsupported_llm_provider", "Unsupported language model provider")
        return
    if grant.llm_provider == "deepseek" and (
            not grant.llm_consent or not isinstance(grant.llm_model, str)
            or grant.llm_model not in DEEPSEEK_MODELS):
        await _fail(websocket, "invalid_llm_selection", "Cloud generation requires explicit consent and a supported model")
        return
    if "llm_provider" in payload and payload["llm_provider"] != grant.llm_provider:
        await _fail(websocket, "llm_provider_mismatch", "The token is bound to a different language model provider")
        return
    if "llm_model" in payload and payload["llm_model"] != grant.llm_model:
        await _fail(websocket, "llm_model_mismatch", "The token is bound to a different language model")
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
    # Deepgram-only, connection-local: deepgram finalizes per endpoint, so a
    # natural pause can split one question. Vosk/Whisper keep the unchanged path.
    assembly = DeepgramQuestionAssembly(clock=runtime.clock) if grant.provider == "deepgram" else None
    # Serializes candidate work so a settled delivery and a new final never
    # interleave their dedupe, retrieval or send steps.
    emit_lock = asyncio.Lock()
    # Connection-local signal completed by a failed settled delivery. It joins the
    # main receive wait set, so the failure is reported without waiting for new
    # PCM or the idle timeout, and no exception payload is carried.
    assembly_failure: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    generation_service = _connection_generation_service(websocket, grant)
    generation = LiveGeneration(generation_service, store, grant.session_id,
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
            if assembly is None:
                await _emit_final(websocket, store, result, language, dedupe,
                                  generation if not stopping and result.utterance_complete else None)
                return
            # A deadline that has not started delivering is obsolete; one that is
            # already delivering is awaited below, never cancelled, so its
            # retrieval, dedupe entry and suggestion are not lost.
            _cancel_waiting_settle(websocket)
            # Relay the provider final verbatim and in order first; a held
            # fragment is discarded, never emitted as a question.
            text = (result.final or "").strip()
            if not text:
                return
            await _send_final_transcript(websocket, result, text, language)
            async with emit_lock:
                for candidate in assembly.observe(text):
                    await _emit_questions(websocket, store, candidate.text, result, language, dedupe,
                                          generation if not stopping and result.utterance_complete else None,
                                          split=not candidate.compound)
                remaining = None if stopping else assembly.settle_deadline()
                if remaining is not None:
                    _arm_settle(websocket, remaining, result)

    def _cancel_waiting_settle(current: WebSocket) -> None:
        """Retire only a deadline that has not started delivering its candidate."""
        window = getattr(current.state, "assembly_settle", None)
        if window is None or window.delivering:
            return
        current.state.assembly_settle = None
        if window.task is not None:
            window.task.cancel()

    def _arm_settle(current: WebSocket, delay: float, result: FeedResult) -> None:
        """Own exactly one connection-scoped deadline for the settled compound."""
        _cancel_waiting_settle(current)
        window = AssemblySettleWindow()
        current.state.assembly_settle = window
        window.task = asyncio.create_task(_deliver_settled(current, window, delay, result),
                                          name="live.settle")

    async def _deliver_settled(current: WebSocket, window: AssemblySettleWindow,
                               delay: float, result: FeedResult) -> None:
        """Emit the settled compound once, serialized with final processing."""
        try:
            await asyncio.sleep(delay)
            if assembly is None or control.stop.is_set() or pump.stopping:
                return
            # From here the delivery is committed: a newer final waits for the
            # emission lock instead of cancelling it.
            window.delivering = True
            async with emit_lock:
                candidate = assembly.take_settled()
                if candidate is None:
                    return
                await _emit_questions(current, store, candidate.text, result, language, dedupe,
                                      generation if result.utterance_complete else None,
                                      split=not candidate.compound)
        except asyncio.CancelledError:
            # Stop, error, disconnect or a superseded waiting deadline.
            return
        except Exception:
            # The receive loop observes this signal and reports the bounded
            # connection error; no exception payload or content is carried.
            if not assembly_failure.done():
                assembly_failure.set_result(None)
        finally:
            if getattr(current.state, "assembly_settle", None) is window:
                current.state.assembly_settle = None

    async def _drain_settle(current: WebSocket) -> None:
        """Cancel and await the deadline so closing never races its delivery."""
        window = getattr(current.state, "assembly_settle", None)
        current.state.assembly_settle = None
        if window is not None and window.task is not None:
            window.task.cancel()
            await asyncio.gather(window.task, return_exceptions=True)

    pump = (StreamingTranscriptionPump(cast(StreamingSpeechSession, speech), emit=emit) if grant.provider == "deepgram"
            else TranscriptionPump(speech, segmented=grant.provider == "faster-whisper", emit=emit))
    websocket.state.transcription_pump = pump
    await _send_live(websocket, {
        "type": "ready",
        "session_id": grant.session_id,
        "language": language,
        "provider": grant.provider,
        "llm_provider": grant.llm_provider,
        "llm_model": grant.llm_model,
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
            done, _ = await asyncio.wait({incoming, stopping, pump.task, assembly_failure},
                                         timeout=max(0, min(runtime.idle_timeout_seconds, remaining)),
                                         return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                await _fail(websocket, "session_finished", "The Live session is already finished")
                return
            if pump.task in done:
                await pump.task
                return
            if assembly_failure in done:
                # Stop and disconnect keep priority when they arrive in the same
                # wake-up: only an unrelated failure is reported here.
                pending = incoming.result() if incoming in done else None
                closing = pending is not None and (
                    pending.get("type") == "websocket.disconnect"
                    or _is_stop_control((pending.get("text") or "").strip()))
                if not closing:
                    await _fail(websocket, "internal_error", "The Live connection could not continue", 1011)
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
        # Drain the deadline before the connection closes so no delivery survives
        # it; a held fragment and its state never cross a connection.
        await _drain_settle(websocket)
        if assembly is not None:
            assembly.reset()


router = APIRouter()


class LiveTokenRequest(BaseModel):
    language: Language
    provider: Provider = "vosk"
    vocabulary_profile: VocabularyProfile = "general"
    # Consent is an explicit opt-in; a missing or false value is rejected by validation.
    consent: Literal[True]
    # LLM selection is independent of STT and defaults to the existing local service.
    llm_provider: Literal["ollama", "deepseek"] = "ollama"
    llm_model: str | None = Field(default=None, max_length=200)
    # Separate from STT consent. Strict JSON boolean: strings/numbers are
    # rejected instead of being coerced. Omitted/false remains the Ollama legacy path.
    llm_consent: StrictBool = False


@router.get("/live/status")
def live_status(request: Request):
    runtime: LiveRuntime = request.app.state.live
    vosk = runtime.models.availability()
    generation = getattr(request.app.state, "generation", None)
    ollama_available = bool(getattr(generation, "available", False))
    return {**vosk, "default_provider": "vosk",
            "providers": {"vosk": vosk, "faster-whisper": runtime.whisper.availability(),
                           "deepgram": runtime.deepgram.availability()},
            "llm": {
                "default_provider": "ollama",
                "providers": {
                    "ollama": {"provider": "ollama", "available": ollama_available,
                               "selection": "backend"},
                    "deepseek": deepseek_availability(),
                },
            }}


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
    llm_model = request.llm_model or None
    if request.llm_provider == "deepseek":
        # Explicit cloud consent is distinct from audio consent and is enforced
        # here, before any token can authorize a detected question.
        if not request.llm_consent:
            raise HTTPException(status_code=400, detail="Cloud question consent is required for the selected language model.")
        if llm_model not in DEEPSEEK_MODELS:
            raise HTTPException(status_code=400, detail="Select one supported DeepSeek model; no implicit model is used.")
        if not windows_cloud_llm_supported():
            raise HTTPException(status_code=503, detail="Cloud language models are available only in the Windows development flow.")
        if not cloud_llm_enabled():
            raise HTTPException(status_code=503, detail=(
                "Cloud language models are disabled by the backend developer gate. "
                "Set COPILOT_ALLOW_CLOUD_LLM=true for the backend and restart; "
                "explicit per-session selection and consent are still required."
            ))
    elif llm_model is not None:
        raise HTTPException(status_code=400, detail="The local Ollama model is fixed by backend configuration.")
    runtime: LiveRuntime = http_request.app.state.live
    provider = ({"vosk": runtime.models, "faster-whisper": runtime.whisper,
                 "deepgram": runtime.deepgram})[request.provider]
    status = provider.availability()
    if not status.get("languages", {}).get(request.language, {}).get("available"):
        raise HTTPException(status_code=503, detail=f"Selected provider ({request.provider}) is unavailable for {request.language}. "
                            "Check the selected runtime/model or cloud API Key; no automatic fallback.")
    profile = request.vocabulary_profile if request.provider == "deepgram" else "general"
    # A missing or invalid DeepSeek key does not fall back to Ollama. The token
    # can still start documentary-only capture; connection setup yields an
    # unconfigured generation service and no remote request.
    token = runtime.tokens.issue(
        session_id, request.language, request.provider, profile,
        request.llm_provider, llm_model, request.llm_consent,
    )
    return {
        "token": token,
        "session_id": session_id,
        "language": request.language,
        "provider": request.provider,
        "llm_provider": request.llm_provider,
        "llm_model": llm_model,
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
    credential_lease = None
    try:
        try:
            credential_lease = CredentialGate(exclusive=False)
        except CredentialError:
            await websocket.accept()
            await _fail(websocket, "credentials_busy", "Credential management is active or its capture guard is unavailable", 1013)
            return
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
                if credential_lease is not None:
                    credential_lease.close()
                _diagnostic("cleanup.complete")
