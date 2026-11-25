"""Offline Nova-3 streaming contracts: segment assembly, cloud opt-in and teardown."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import live
from app.application.stt import FeedResult, SpeechFailure, SpeechOverloaded, StreamingTranscriptionPump
from app.infrastructure.deepgram import DeepgramProvider, DeepgramSession
from app.infrastructure.technical_vocabulary import (GLOSSARY, PROFILE_GROUPS,
                                                    MAX_ACTIVE_KEYTERMS, MAX_ACTIVE_CHARACTERS, keyterms_for)
from app.live import (ASSEMBLY_MAX_GAP_SECONDS, MAX_ASSEMBLED_QUESTION_CHARS,
                      DeepgramQuestionAssembly, detect_questions)
from app.main import create_app
from app.parsers import ParsedEntry

HEADERS = {"origin": "http://localhost:5173"}


def result(text, *, is_final=False, speech_final=False, end=1.5):
    return json.dumps({"type": "Results", "channel": {"alternatives": [{
        "transcript": text, "words": [{"end": end}] if text else []}]},
        "is_final": is_final, "speech_final": speech_final})


class FakeConnection:
    def __init__(self, messages=()):
        self.messages = deque(messages)
        self.sent = []
        self.closed = False

    async def send(self, pcm):
        self.sent.append(pcm)

    async def recv(self):
        if not self.messages:
            await asyncio.Event().wait()
        return self.messages.popleft()

    async def close(self):
        self.closed = True


def test_deepgram_assembles_interim_and_final_chunks_only_at_speech_endpoint():
    async def run():
        ws = FakeConnection([
            result("Could you explain", is_final=False),
            result("Could you explain", is_final=True, end=1.0),
            result("how authentication works", is_final=False),
            result("how authentication works?", is_final=True, speech_final=True, end=3.0),
            result("Next question?", is_final=True, speech_final=True, end=4.0),
        ])
        session = DeepgramSession(ws)
        assert (await session.receive()).partial == "Could you explain"
        assert (await session.receive()).partial == "Could you explain"
        assert (await session.receive()).partial == "Could you explain how authentication works"
        answer = await session.receive()
        assert answer == FeedResult(final="Could you explain how authentication works?",
                                    last_word_end_seconds=3.0, utterance_complete=True)
        assert (await session.receive()).final == "Next question?"
        await session.feed(bytes(3200))
        assert ws.sent == [bytes(3200)]
        await session.close()
        assert ws.closed

    asyncio.run(run())


@pytest.mark.parametrize("invalid", [
    json.dumps({"type": "Results"}), json.dumps({"type": "Error", "message": "secret-should-not-leak"}),
    result("x" * 3001),
    json.dumps({"type": "Results", "channel": {"alternatives": []}}),
])
def test_deepgram_rejects_invalid_upstream_messages_without_echoing_text(invalid):
    async def run():
        with pytest.raises(SpeechFailure) as error:
            await DeepgramSession(FakeConnection([invalid])).receive()
        assert "secret" not in str(error.value)
        assert "x" * 100 not in str(error.value)
    asyncio.run(run())


def test_deepgram_availability_requires_explicit_api_key(monkeypatch):
    monkeypatch.setattr("app.infrastructure.deepgram._websockets_installed", lambda: True)
    unavailable = DeepgramProvider({}).availability()
    assert not unavailable["available"]
    assert not unavailable["languages"]["en-US"]["available"]
    configured = DeepgramProvider({"COPILOT_DEEPGRAM_API_KEY": "private-value"}).availability()
    assert configured["available"] and configured["languages"]["es-MX"]["available"]
    assert "private-value" not in str(configured)


def test_deepgram_maps_spanish_locale_and_never_exposes_key(monkeypatch):
    import websockets.asyncio.client as client_module

    calls = []
    async def connect(url, **kwargs):
        calls.append((url, kwargs))
        return FakeConnection()
    monkeypatch.setattr(client_module, "connect", connect)

    async def run():
        provider = DeepgramProvider({"COPILOT_DEEPGRAM_API_KEY": "private-key"})
        session = await provider.open("es-MX")
        await session.close()
    asyncio.run(run())
    assert "language=es" in calls[0][0]
    assert "language=es-MX" not in calls[0][0]
    assert "interim_results=true" in calls[0][0]
    assert calls[0][1]["proxy"] is None
    assert calls[0][1]["additional_headers"]["Authorization"] == "Token private-key"
    assert "private-key" not in str(DeepgramProvider({"COPILOT_DEEPGRAM_API_KEY": "private-key"}).availability())


def test_streaming_pump_delivers_results_without_waiting_for_new_pcm():
    async def run():
        class Session:
            closed = False
            def __init__(self):
                self.events = asyncio.Queue()
                self.audio = []
            async def feed(self, pcm):
                self.audio.append(pcm)
                return FeedResult()
            async def receive(self):
                return await self.events.get()
            async def close(self):
                self.closed = True
        session = Session()
        emitted = []
        event = asyncio.Event()
        async def emit(result, stopping):
            emitted.append((result, stopping))
            event.set()
        pump = StreamingTranscriptionPump(session, emit=emit)
        pump.feed(bytes(3200))
        await asyncio.sleep(.01)
        assert session.audio == [bytes(3200)]
        await session.events.put(FeedResult(partial="Recognized while silence follows"))
        await asyncio.wait_for(event.wait(), 1)
        assert emitted[0][0].partial == "Recognized while silence follows"
        assert emitted[0][1] is False
        await pump.close()
        assert session.closed and pump.queued_bytes == 0
    asyncio.run(run())


def test_cloud_pump_has_explicit_byte_and_item_limits():
    async def run():
        class Blocking:
            async def feed(self, pcm): await asyncio.Event().wait()
            async def receive(self): await asyncio.Event().wait()
            async def close(self): pass
        pump = StreamingTranscriptionPump(Blocking(), emit=lambda *_: None)
        try:
            for _ in range(20):
                pump.feed(bytes(3200))
            with pytest.raises(SpeechOverloaded):
                pump.feed(bytes(3200))
        finally:
            await pump.close()
        assert pump.queued_bytes == 0
    asyncio.run(run())


class FakeCloudProvider:
    def __init__(self):
        self.session = None
        self.languages = []
        self.profiles = []
    def availability(self):
        return {"provider": "deepgram", "available": True, "runtime_installed": True,
                "languages": {name: {"available": True} for name in ("en-US", "es-MX")},
                "detail": "Synthetic cloud"}
    async def open(self, language, *, vocabulary_profile="general"):
        self.languages.append(language)
        self.profiles.append(vocabulary_profile)
        self.session = FakeCloudSession()
        return self.session


class FakeCloudSession:
    def __init__(self):
        self.events = asyncio.Queue()
        self.closed = False
    async def feed(self, pcm):
        await self.events.put(FeedResult(partial="What is auth"))
        await self.events.put(FeedResult(final="What is authentication?"))
        return FeedResult()
    async def receive(self):
        return await self.events.get()
    async def close(self):
        self.closed = True


def test_deepgram_reuses_final_only_retrieval_and_local_capture_contract(tmp_path):
    app = create_app(tmp_path)
    fake = FakeCloudProvider()
    app.state.live.deepgram = fake
    app.state.store.import_document("kb.md", b"synthetic",
                                  [ParsedEntry("qa", "What is authentication?", "Documented answer.", "", "Line 1")])
    with TestClient(app) as client:
        status = client.get("/live/status").json()
        assert status["default_provider"] == "vosk"
        assert status["providers"]["deepgram"]["available"]
        sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
        token_response = client.post(f"/sessions/{sid}/live-token", json={
            "language": "en-US", "provider": "deepgram", "consent": True,
            "vocabulary_profile": "data-analyst"})
        assert token_response.status_code == 200
        token = token_response.json()["token"]
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": token, "provider": "deepgram", "language": "en-US"})
            ready = ws.receive_json()
            assert ready["type"] == "ready" and ready["provider"] == "deepgram", ready
            ws.send_bytes(bytes(3200))
            assert ws.receive_json() == {"type": "partial", "text": "What is auth", "language": "en-US"}
            final = ws.receive_json()
            assert final["type"] == "final" and final["text"] == "What is authentication?"
            suggestion = ws.receive_json()
            assert suggestion["match_type"] == "exact_qa"
            assert suggestion["answer"] == "Documented answer."
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert fake.languages == ["en-US"] and fake.profiles == ["data-analyst"] and fake.session.closed
    assert not list(tmp_path.rglob("*.wav"))


@pytest.mark.parametrize("profile", tuple(PROFILE_GROUPS))
@pytest.mark.parametrize("language", ["en-US", "es-MX"])
def test_vocabulary_profiles_are_bounded_and_deterministic(profile, language):
    first = keyterms_for(profile, language)
    assert first == keyterms_for(profile, language)
    assert 20 <= len(first) <= MAX_ACTIVE_KEYTERMS
    assert sum(map(len, first)) <= MAX_ACTIVE_CHARACTERS
    assert len({term.casefold() for term in first}) == len(first)
    assert "GraphQL" in first
    assert not any("\n" in term or "\r" in term or ":0.15" in term for term in first)


def test_technical_glossary_covers_all_professions_and_subfields():
    assert len(GLOSSARY) >= 12
    unique = {value.casefold() for terms in GLOSSARY.values() for value in terms}
    assert len(unique) >= 500
    for term in ("GraphQL", "Kubernetes", "Model Context Protocol", "LangGraph",
                 "Power BI", "DAX", "Snowflake", "Databricks", "Terraform",
                 "OAuth", "Playwright", "SwiftUI", "Apache Airflow"):
        assert term.casefold() in unique
    assert "Power BI" in keyterms_for("data-analyst")
    assert "Kubernetes" in keyterms_for("cloud-devops")
    assert "Machine Learning" in keyterms_for("ai-engineer")


def test_vocabulary_rejects_profiles_and_languages_not_on_the_allowlist():
    with pytest.raises(ValueError, match="unsupported_vocabulary_profile"):
        keyterms_for("freeform injection", "en-US")
    with pytest.raises(ValueError, match="unsupported_vocabulary_language"):
        keyterms_for("general", "fr-FR")


def test_deepgram_sends_repeated_encoded_keyterms_for_selected_profile(monkeypatch):
    import websockets.asyncio.client as client_module

    received = []

    async def connect(url, **kwargs):
        received.append((url, kwargs))
        return FakeConnection()

    monkeypatch.setattr(client_module, "connect", connect)

    async def run():
        provider = DeepgramProvider({"COPILOT_DEEPGRAM_API_KEY": "secret-value"})
        session = await provider.open("en-US", vocabulary_profile="ai-engineer")
        await session.close()

    asyncio.run(run())
    url, kwargs = received[0]
    params = parse_qs(urlparse(url).query)
    assert params["model"] == ["nova-3"]
    assert params["language"] == ["en-US"]
    assert params["keyterm"] == list(keyterms_for("ai-engineer", "en-US"))
    assert params["keyterm"].count("GraphQL") == 1
    assert "Machine Learning" in params["keyterm"]
    assert "keywords" not in params
    assert "keyterm=Machine+Learning" in url
    assert "secret-value" not in url
    assert kwargs["additional_headers"]["Authorization"] == "Token secret-value"


def test_unknown_vocabulary_profile_rejected_before_any_cloud_connection(tmp_path):
    app = create_app(tmp_path)
    app.state.live.deepgram = FakeCloudProvider()
    with TestClient(app) as client:
        sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
        response = client.post(f"/sessions/{sid}/live-token", json={
            "language": "en-US", "provider": "deepgram", "consent": True,
            "vocabulary_profile": "../../invalid", 
        })
        assert response.status_code == 422
        assert app.state.live.deepgram.profiles == []


@pytest.mark.parametrize('outcome', ['success', 'timeout'])
def test_deepgram_recognized_direct_comparison_reaches_suggestion(tmp_path, outcome):
    """A completed cloud final must reach detection, even with no stored match."""
    class ComparisonSession(FakeCloudSession):
        async def feed(self, pcm):
            await self.events.put(FeedResult(final="compare rest and graft twelve"))
            return FeedResult()

    class ComparisonProvider(FakeCloudProvider):
        async def open(self, language, *, vocabulary_profile="general"):
            self.languages.append(language)
            self.profiles.append(vocabulary_profile)
            self.session = ComparisonSession()
            return self.session

    app = create_app(tmp_path)
    from app.application.generation import GenerationError, GenerationService
    class LocalProvider:
        name = 'ollama'
        model = 'synthetic-local'
        calls = 0
        async def generate(self, question, language):
            self.calls += 1
            if outcome == 'timeout':
                raise GenerationError('timeout')
            return 'A synthetic technical explanation.'
    local = LocalProvider()
    app.state.generation = GenerationService(local, enabled=True)
    fake = ComparisonProvider()
    app.state.live.deepgram = fake
    with TestClient(app) as client:
        sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
        grant = client.post(f"/sessions/{sid}/live-token", json={
            "language": "en-US", "provider": "deepgram", "consent": True,
            "vocabulary_profile": "fullstack",
        })
        assert grant.status_code == 200
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant.json()["token"],
                          "provider": "deepgram", "language": "en-US"})
            assert ws.receive_json()["type"] == "ready"
            ws.send_bytes(bytes(3200))
            final = ws.receive_json()
            suggestion = ws.receive_json()
            assert final["type"] == "final"
            assert suggestion["type"] == "suggestion", suggestion
            assert suggestion["question"] == "compare rest and graft twelve"
            assert suggestion["status"] == "no_evidence"
            generation = ws.receive_json()
            assert generation['session_id'] == sid and generation['question_id'] == suggestion['question_id']
            if outcome == 'success':
                assert generation['type'] == 'generated_suggestion'
                assert generation['kind'] == 'ai_generated' and generation['source'] is None
            else:
                assert generation == dict(type='generation_failed', code='timeout', session_id=sid,
                                          question_id=suggestion['question_id'])
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert fake.profiles == ["fullstack"]
    assert local.calls == 1


# --- Pause-split candidate assembly (Deepgram only) --------------------------


class GatedSession:
    """Real DeepgramSession behind a gate: upstream results start after first PCM.

    The gate keeps the deterministic replay ordered behind ``ready``; the adapter,
    the streaming pump, the emit boundary, detection and retrieval are real.
    """

    def __init__(self, messages):
        self.inner = DeepgramSession(FakeConnection(messages))
        self.allowed = asyncio.Event()

    async def feed(self, pcm):
        self.allowed.set()
        return FeedResult()

    async def receive(self):
        await self.allowed.wait()
        return await self.inner.receive()

    async def close(self):
        await self.inner.close()


class GatedProvider:
    """Synthetic cloud provider replaying one message list per opened connection."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.languages = []
        self.sessions = []

    def availability(self):
        return {"provider": "deepgram", "available": True, "runtime_installed": True,
                "languages": {name: {"available": True} for name in ("en-US", "es-MX")},
                "detail": "Synthetic stream"}

    async def open(self, language, *, vocabulary_profile="general"):
        self.languages.append(language)
        session = GatedSession(self.batches.pop(0))
        self.sessions.append(session)
        return session


class CountingStore:
    """Delegating store that records every exact Q&A lookup."""

    def __init__(self, store):
        self._store = store
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._store, name)

    def find_exact_qa(self, question):
        self.calls.append(question)
        return self._store.find_exact_qa(question)


def connect(client, language="en-US"):
    """Return ``(session_id, token)`` for a Deepgram Live connection."""
    sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
    token = client.post(f"/sessions/{sid}/live-token", json={
        "language": language, "provider": "deepgram", "consent": True}).json()["token"]
    return sid, token


def begin(ws, token, language="en-US"):
    ws.send_json({"type": "start", "token": token, "provider": "deepgram", "language": language})
    ready = ws.receive_json()
    assert ready["type"] == "ready" and ready["provider"] == "deepgram", ready
    # The gated session releases its deterministic replay after the first frame.
    ws.send_bytes(bytes(3200))


def assemble_app(tmp_path, batches, questions=()):
    """Build an app whose Deepgram session replays ``batches`` deterministically."""
    app = create_app(tmp_path)
    app.state.live.deepgram = GatedProvider(batches)
    for question in questions:
        app.state.store.import_document("kb.md", b"synthetic", [
            ParsedEntry("qa", question, "Synthetic answer.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    return app, counter


def finals(*texts):
    """Deterministic is_final + speech_final replay for one endpoint per text."""
    return [result(text, is_final=True, speech_final=True, end=float(index + 1))
            for index, text in enumerate(texts)]


def observed(assembly, text):
    """Return the candidate texts for one final, hiding the outcome wrapper."""
    return [candidate.text for candidate in assembly.observe(text)]


def test_deepgram_pause_split_assembles_one_question_without_early_retrieval(tmp_path):
    messages = [
        result("Could you explain?", is_final=False),
        result("Could you explain?", is_final=True, speech_final=True, end=1.2),
        result("how authentication works?", is_final=False, end=2.6),
        result("how authentication works?", is_final=True, speech_final=True, end=2.6),
    ]
    app, counter = assemble_app(tmp_path, [messages],
                                questions=["Could you explain how authentication works"])
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            assert ws.receive_json() == {"type": "partial", "text": "Could you explain?", "language": "en-US"}
            held = ws.receive_json()
            # The bare cue keeps provider punctuation and stays incomplete: the
            # transcript is relayed unchanged but nothing is retrieved yet.
            assert held == {"type": "final", "text": "Could you explain?", "language": "en-US",
                            "last_word_end_seconds": 1.2}
            # No suggestion can appear between the finals: the next event is the
            # partial of the second fragment.
            assert ws.receive_json()["type"] == "partial"
            final = ws.receive_json()
            assert final["text"] == "how authentication works?"
            suggestion = ws.receive_json()
            assert suggestion["question"] == "Could you explain how authentication works"
            assert suggestion["match_type"] == "exact_qa"
            assert suggestion["answer"] == "Synthetic answer."
            assert counter.calls == ["Could you explain how authentication works"]
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_deepgram_slow_spanish_question_survives_a_filler_only_final(tmp_path):
    messages = [
        result("Podrías contarme", is_final=False),
        result("Podrías contarme", is_final=True, speech_final=True, end=1.0),
        result("Eh", is_final=True, speech_final=True, end=1.6),
        result("sobre tu último proyecto", is_final=False, end=3.0),
        result("sobre tu último proyecto?", is_final=True, speech_final=True, end=3.0),
    ]
    app, counter = assemble_app(tmp_path, [messages],
                                questions=["Podrías contarme sobre tu último proyecto"])
    with TestClient(app) as client:
        _sid, token = connect(client, "es-MX")
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token, "es-MX")
            assert ws.receive_json()["type"] == "partial"
            assert ws.receive_json()["text"] == "Podrías contarme"
            assert ws.receive_json() == {"type": "final", "text": "Eh", "language": "es-MX",
                                         "last_word_end_seconds": 1.6}
            assert ws.receive_json()["type"] == "partial"
            assert ws.receive_json()["text"] == "sobre tu último proyecto?"
            suggestion = ws.receive_json()
            assert suggestion["question"] == "Podrías contarme sobre tu último proyecto"
            assert suggestion["match_type"] == "exact_qa"
            assert counter.calls == ["Podrías contarme sobre tu último proyecto"]
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


@pytest.mark.parametrize(("pending", "next_final", "expected"), [
    ("Could you explain", "What is your notice period?", "What is your notice period"),
    ("Could you explain", "I worked at Acme for five years.", None),
    ("Could you explain", "The build failed yesterday.", None),
    ("Cuéntanos sobre", "Trabajé en Acme cinco años.", None),
])
def test_deepgram_never_joins_new_questions_or_unrelated_statements(tmp_path, pending, next_final, expected):
    messages = finals(pending, next_final)
    questions = (expected,) if expected else ()
    app, counter = assemble_app(tmp_path, [messages], questions=questions)
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            assert ws.receive_json()["text"] == pending
            # The held fragment produced no suggestion: the next event is the final.
            assert ws.receive_json()["text"] == next_final
            if expected is None:
                ws.send_text("stop")
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
                assert counter.calls == []
            else:
                suggestion = ws.receive_json()
                assert suggestion["question"] == expected
                assert counter.calls == [expected]
                ws.send_text("stop")
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()


@pytest.mark.parametrize(("spoken", "expected"), [
    # Subordinate wh syntax after a request frame (English and Spanish).
    (("Could you explain", "how authentication works?"),
     "Could you explain how authentication works?"),
    (("Explícame", "cómo funciona OAuth?"), "Explícame cómo funciona OAuth?"),
    # A new incomplete start replaces the held request instead of being glued.
    (("Could you explain", "What is", "OAuth?"), "What is OAuth?"),
    # A join that is still incomplete keeps holding until the term arrives.
    (("What is the difference", "between rest", "and graphql?"),
     "What is the difference between rest and graphql?"),
    # Clause-shaped prose is never merged: the hold is dropped.
    (("Could you explain", "The build failed yesterday."), "The build failed yesterday."),
    (("Could you explain", "The system was down."), "The system was down."),
    # A new direct question after leading fillers is not a continuation.
    (("Could you explain", "So what is your notice period?"), "So what is your notice period?"),
    # Ordinary complete yes/no questions are neither held nor merged.
    (("Is that okay?",), "Is that okay?"),
    (("Could you explain", "Is that all?"), "Is that all?"),
    # A true short standalone question is emitted immediately, never held.
    (("What was slow?",), "What was slow?"),
    # A truncated indirect complement is held, never evaluated on its own.
    (("I'd like to know how you would",), None),
    (("I'd like to know", "how you would"), None),
    (("I'd like to know how you would", "design a resilient pipeline?"),
     "how you would design a resilient pipeline?"),
    (("I'd like to know if you would",), None),
    (("I'd like to know if you would", "relocate?"), "if you would relocate?"),
    # Short prose is not a noun-phrase complement.
    (("Could you explain", "I agree"), "I agree"),
    (("Could you explain", "Not really."), "Not really."),
])
def test_deepgram_recognized_continuations_build_one_candidate(spoken, expected):
    assembly = DeepgramQuestionAssembly()
    results = [observed(assembly, text) for text in spoken]
    assert results[-1] == ([] if expected is None else [expected])
    assert results[:-1] == [[]] * (len(spoken) - 1)


@pytest.mark.parametrize(("spoken", "expected"), [
    (("I'd like to know how you would design a resilient pipeline.",),
     "how you would design a resilient pipeline"),
    (("Me gustaría saber cómo funciona el sistema de autenticación.",),
     "cómo funciona el sistema de autenticación"),
    (("I'd like to know", "how you would design a resilient pipeline?"),
     "how you would design a resilient pipeline"),
])
def test_deepgram_indirect_prompts_use_the_recognized_complement(tmp_path, spoken, expected):
    app, counter = assemble_app(tmp_path, [finals(*spoken)], questions=[expected])
    with TestClient(app) as client:
        language = "es-MX" if spoken[0].startswith("Me gustaría") else "en-US"
        _sid, token = connect(client, language)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token, language)
            for text in spoken:
                assert ws.receive_json()["text"] == text
            suggestion = ws.receive_json()
            assert suggestion["question"] == expected
            assert suggestion["match_type"] == "exact_qa"
            assert counter.calls == [expected]
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_deepgram_assembly_is_bounded_by_fragments_characters_and_gap():
    now = [0.0]
    assembly = DeepgramQuestionAssembly(clock=lambda: now[0])

    # Fragment cap: only a connective can extend a hold, and it is bounded.
    assert observed(assembly, "Could you explain") == []
    assert observed(assembly, "and") == []  # filler keeps the hold, adds no fragment
    assert observed(assembly, "and why") == []
    assert observed(assembly, "and how") == []
    # Fourth fragment exceeds MAX_ASSEMBLED_FRAGMENTS: the chain is dropped and
    # the new final stands alone.
    assert observed(assembly, "does it apply?") == ["does it apply?"]

    # Character cap: a long trailing hold cannot be completed by a short term.
    assembly.reset()
    tail = "in my previous role we discussed " + "many topics " * 17 + "and"
    assert len(tail) <= MAX_ASSEMBLED_QUESTION_CHARS and observed(assembly, tail) == []
    assert len(tail) + 1 + len("rest?") > MAX_ASSEMBLED_QUESTION_CHARS
    assert observed(assembly, "rest?") == ["rest?"]

    # Bounded age/gap is evaluated at the next final, without any timer.
    assembly.reset()
    now[0] = 0.0
    assert observed(assembly, "Could you explain") == []
    now[0] = ASSEMBLY_MAX_GAP_SECONDS + 0.5
    assert observed(assembly, "how authentication works?") == ["how authentication works?"]


def test_deepgram_incomplete_fragment_is_discarded_on_stop_and_restart(tmp_path):
    provider = GatedProvider([
        finals("Could you explain"),
        finals("What is authentication?"),
    ])
    app = create_app(tmp_path)
    app.state.live.deepgram = provider
    app.state.store.import_document("kb.md", b"synthetic", [
        ParsedEntry("qa", "What is authentication?", "Authentication verifies identity.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            assert ws.receive_json()["text"] == "Could you explain"
            ws.send_text("stop")
            # Never flush an incomplete request on stop.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert counter.calls == []

        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            assert ws.receive_json()["text"] == "What is authentication?"
            suggestion = ws.receive_json()
            # Restart starts from empty assembly state: no cross-connection join.
            assert suggestion["question"] == "What is authentication"
            assert suggestion["answer"] == "Authentication verifies identity."
            assert counter.calls == ["What is authentication"]


# --- Behavioral compound requests (Deepgram only) ----------------------------

# The owner-supplied finals of one real endpoint-split behavioral request.
BEHAVIORAL_FRAGMENTS = (
    "Can you tell me about a time",
    "when you improved a back end service What was slow",
    "and what did you change",
)
BEHAVIORAL_QUESTION = " ".join(BEHAVIORAL_FRAGMENTS)

# The same request split before the second question and without an embedded
# second question: positive completion evidence, so the short window applies.
COMPLETE_BEHAVIORAL_FRAGMENTS = (
    "Can you tell me about a time",
    "when you improved a back end service",
)
COMPLETE_BEHAVIORAL_QUESTION = " ".join(COMPLETE_BEHAVIORAL_FRAGMENTS)


def test_deepgram_behavioral_story_is_one_question_and_one_retrieval(tmp_path):
    """The three reported finals yield exactly one suggestion and one lookup."""
    # The shared detector cuts the coordinated follow-up into a second question,
    # so this compound must bypass splitting while keeping every other filter.
    assert detect_questions(BEHAVIORAL_QUESTION) == [
        " ".join(BEHAVIORAL_FRAGMENTS[:2]), "what did you change"]
    app, counter = assemble_app(tmp_path, [finals(*BEHAVIORAL_FRAGMENTS)],
                               questions=[BEHAVIORAL_QUESTION])
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            # The transcript is relayed verbatim and in order; nothing is
            # retrieved while the fragments are held or settled.
            for fragment in BEHAVIORAL_FRAGMENTS:
                final = ws.receive_json()
                assert final["type"] == "final" and final["text"] == fragment
            suggestion = ws.receive_json()
            assert suggestion["type"] == "suggestion"
            assert suggestion["question"] == BEHAVIORAL_QUESTION
            assert suggestion["match_type"] == "exact_qa"
            assert suggestion["answer"] == "Synthetic answer."
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    # One retrieval for the whole request: no bare prefix or continuation lookup.
    assert counter.calls == [BEHAVIORAL_QUESTION]


def test_deepgram_delayed_coordinated_follow_up_is_not_split_by_the_settle_window(tmp_path):
    """A pause longer than the short window must not deliver the ambiguous prefix."""
    from app.application.generation import GenerationService

    class LocalProvider:
        name = "ollama"
        model = "synthetic-local"
        calls = 0

        async def generate(self, question, language):
            self.calls += 1
            return "Synthetic explanation."

    gate = threading.Event()
    release = None
    local = LocalProvider()
    app = create_app(tmp_path)
    app.state.generation = GenerationService(local, enabled=True)
    app.state.live.deepgram = PausedProvider(
        finals(*BEHAVIORAL_FRAGMENTS), hold_before_result=2, gate=gate)
    app.state.store.import_document("kb.md", b"synthetic", [
        ParsedEntry("qa", BEHAVIORAL_QUESTION, "Synthetic answer.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    try:
        with TestClient(app) as client:
            _sid, token = connect(client)
            with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
                begin(ws, token)
                for fragment in BEHAVIORAL_FRAGMENTS[:2]:
                    assert ws.receive_json()["text"] == fragment
                # Hold the third final for longer than the old 1 s wait window.
                release = threading.Timer(1.5, gate.set)
                release.daemon = True
                release.start()
                third = ws.receive_json()
                assert third["type"] == "final" and third["text"] == BEHAVIORAL_FRAGMENTS[2]
                # Nothing was retrieved or generated for the ambiguous prefix.
                assert counter.calls == [] and local.calls == 0
                suggestion = ws.receive_json()
                assert suggestion["type"] == "suggestion"
                assert suggestion["question"] == BEHAVIORAL_QUESTION
                assert suggestion["match_type"] == "exact_qa"
                ws.send_text("stop")
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
    finally:
        gate.set()
        if release is not None:
            release.cancel()
    assert counter.calls == [BEHAVIORAL_QUESTION]
    assert local.calls == 0


def test_deepgram_ambiguous_prefix_expires_without_lookup_or_generation(tmp_path, monkeypatch):
    """An expired ambiguous prefix is dropped; the later final stands alone."""
    monkeypatch.setattr("app.live.ASSEMBLY_MAX_GAP_SECONDS", 0.2)
    gate = threading.Event()
    release = None
    app = create_app(tmp_path)
    app.state.live.deepgram = PausedProvider(
        finals(*BEHAVIORAL_FRAGMENTS[:2], NEXT_QUESTION_FINAL),
        hold_before_result=2, gate=gate)
    app.state.store.import_document("kb.md", b"synthetic", [
        ParsedEntry("qa", NEXT_QUESTION, "Synthetic answer.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    try:
        with TestClient(app) as client:
            _sid, token = connect(client)
            with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
                begin(ws, token)
                for fragment in BEHAVIORAL_FRAGMENTS[:2]:
                    assert ws.receive_json()["text"] == fragment
                # Release the independent final after the gap deadline expired.
                release = threading.Timer(0.6, gate.set)
                release.daemon = True
                release.start()
                assert ws.receive_json()["text"] == NEXT_QUESTION_FINAL
                # No prefix suggestion, retrieval or generation was emitted.
                assert counter.calls == []
                suggestion = ws.receive_json()
                assert suggestion["type"] == "suggestion"
                assert suggestion["question"] == NEXT_QUESTION
                assert suggestion["match_type"] == "exact_qa"
                ws.send_text("stop")
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
    finally:
        gate.set()
        if release is not None:
            release.cancel()
    assert counter.calls == [NEXT_QUESTION]


@pytest.mark.parametrize(("spoken", "expected"), [
    (("Can you tell me about a time", "when you improved a back end service"),
     "Can you tell me about a time when you improved a back end service"),
    (("Cuéntame sobre una vez", "que mejoraste el tiempo de respuesta"),
     "Cuéntame sobre una vez que mejoraste el tiempo de respuesta"),
])
def test_deepgram_behavioral_context_holds_its_relative_clause(spoken, expected):
    """EN/ES context tails are never retrieved alone; the compound settles."""
    assembly = DeepgramQuestionAssembly()
    results = [observed(assembly, text) for text in spoken]
    assert results == [[]] * len(spoken)
    assert assembly.settle_deadline() is not None
    settled = assembly.take_settled()
    assert settled is not None and settled.compound
    assert settled.text == expected


def test_deepgram_provider_period_does_not_bypass_settlement():
    """A period ends the endpoint, not the thought: the follow-up can still join."""
    assembly = DeepgramQuestionAssembly()
    assert observed(assembly, "Can you tell me about a time") == []
    assert observed(assembly, "when you improved a back end service.") == []
    candidates = assembly.observe("and what did you change?")
    assert [candidate.text for candidate in candidates] == [
        "Can you tell me about a time when you improved a back end service and what did you change"]
    assert candidates[0].compound


def test_deepgram_incomplete_coordinated_suffix_is_not_emitted():
    """A follow-up that stops before its verb keeps holding, never retrievable."""
    assembly = DeepgramQuestionAssembly()
    assert observed(assembly, "Can you tell me about a time") == []
    assert observed(assembly, "when you improved a back end service") == []
    assert observed(assembly, "and what did you") == []
    assert assembly.settle_deadline() is not None


def test_deepgram_ambiguous_behavioral_prefix_is_never_glued_to_a_later_final():
    now = [0.0]
    assembly = DeepgramQuestionAssembly(clock=lambda: now[0])
    assert observed(assembly, BEHAVIORAL_FRAGMENTS[0]) == []
    assert observed(assembly, BEHAVIORAL_FRAGMENTS[1]) == []
    # The prefix still contains an unpunctuated second question ("What was
    # slow"): a different final inside the window drops it and stands alone.
    now[0] = 0.2
    assert observed(assembly, "What is your notice period?") == ["What is your notice period?"]
    assert assembly.settle_deadline() is None and assembly.take_settled() is None


def test_deepgram_ambiguous_behavioral_prefix_expires_without_a_candidate():
    now = [0.0]
    assembly = DeepgramQuestionAssembly(clock=lambda: now[0])
    assert observed(assembly, BEHAVIORAL_FRAGMENTS[0]) == []
    assert observed(assembly, BEHAVIORAL_FRAGMENTS[1]) == []
    # Ambiguity is not completion: the candidate stays joinable up to the gap
    # bound, beyond the short stabilization window.
    assert assembly.settle_deadline() == pytest.approx(ASSEMBLY_MAX_GAP_SECONDS)
    now[0] = ASSEMBLY_MAX_GAP_SECONDS + 0.1
    # Expiry drops the prefix: no candidate, retrieval, dedupe entry or generation.
    assert assembly.take_settled() is None
    assert assembly.settle_deadline() is None


def test_deepgram_settled_behavioral_request_is_emitted_after_its_window(tmp_path, monkeypatch):
    """A completed two-fragment request is not stranded when no follow-up comes."""
    monkeypatch.setattr("app.live.ASSEMBLY_SETTLE_SECONDS", 0.05)
    spoken = COMPLETE_BEHAVIORAL_FRAGMENTS
    question = COMPLETE_BEHAVIORAL_QUESTION
    app, counter = assemble_app(tmp_path, [finals(*spoken)], questions=[question])
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            for fragment in spoken:
                assert ws.receive_json()["text"] == fragment
            # The bounded window elapses: one suggestion, no fixed test sleep.
            suggestion = ws.receive_json()
            assert suggestion["question"] == question
            assert suggestion["match_type"] == "exact_qa"
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert counter.calls == [question]


def test_deepgram_behavioral_story_stop_restart_and_repeat_retrieve_once(tmp_path):
    """Pending settlement never flushes on stop; a repeated story is deduped."""
    provider = GatedProvider([
        finals(*BEHAVIORAL_FRAGMENTS[:2]),
        finals(*BEHAVIORAL_FRAGMENTS) + finals(*BEHAVIORAL_FRAGMENTS),
    ])
    app = create_app(tmp_path)
    app.state.live.deepgram = provider
    app.state.store.import_document("kb.md", b"synthetic", [
        ParsedEntry("qa", BEHAVIORAL_QUESTION, "Synthetic answer.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            for fragment in BEHAVIORAL_FRAGMENTS[:2]:
                assert ws.receive_json()["text"] == fragment
            ws.send_text("stop")
            # A pending stabilization window is cancelled, never flushed.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert counter.calls == []

        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            for _repeat in range(2):
                for fragment in BEHAVIORAL_FRAGMENTS:
                    assert ws.receive_json()["text"] == fragment
                if _repeat == 0:
                    assert ws.receive_json()["question"] == BEHAVIORAL_QUESTION
            ws.send_text("stop")
            # The repeated story produced no second suggestion before the close.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert counter.calls == [BEHAVIORAL_QUESTION]


NEXT_QUESTION_FINAL = "What was the phase two audit?"
NEXT_QUESTION = "What was the phase two audit"


class PausedSession:
    """Real adapter that holds one result until the test releases it."""

    def __init__(self, inner, hold_before_result, gate):
        self.inner = inner
        self.allowed = asyncio.Event()
        self.hold_before_result = hold_before_result
        self.gate = gate
        self.results = 0

    async def feed(self, pcm):
        self.allowed.set()
        return FeedResult()

    async def receive(self):
        await self.allowed.wait()
        if self.results == self.hold_before_result:
            await asyncio.to_thread(self.gate.wait, 10)
        self.results += 1
        return await self.inner.receive()

    async def close(self):
        await self.inner.close()


class PausedProvider(GatedProvider):
    """One connection whose replay pauses before its third result."""

    def __init__(self, messages, hold_before_result, gate):
        super().__init__([messages])
        self.hold_before_result = hold_before_result
        self.gate = gate

    async def open(self, language, *, vocabulary_profile="general"):
        self.languages.append(language)
        session = PausedSession(DeepgramSession(FakeConnection(self.batches.pop(0))),
                                self.hold_before_result, self.gate)
        self.sessions.append(session)
        return session


def test_deepgram_started_delivery_is_not_lost_to_a_new_final(tmp_path, monkeypatch):
    """A settled delivery in flight wins over a following final; nothing is dropped."""
    monkeypatch.setattr("app.live.ASSEMBLY_SETTLE_SECONDS", 0.05)
    retrieval_started = threading.Event()
    retrieval_release = threading.Event()
    next_final_gate = threading.Event()
    settled_question = COMPLETE_BEHAVIORAL_QUESTION
    real_retrieve = live._retrieve_live

    def blocked_retrieve(store, question, semantic=None):
        if question == settled_question:
            retrieval_started.set()
            assert retrieval_release.wait(10)
        return real_retrieve(store, question, semantic)

    monkeypatch.setattr("app.live._retrieve_live", blocked_retrieve)
    app = create_app(tmp_path)
    app.state.live.deepgram = PausedProvider(
        finals(*COMPLETE_BEHAVIORAL_FRAGMENTS, NEXT_QUESTION_FINAL),
        hold_before_result=2, gate=next_final_gate)
    for index, question in enumerate((settled_question, NEXT_QUESTION)):
        app.state.store.import_document(f"kb{index}.md", f"synthetic-{index}".encode(), [
            ParsedEntry("qa", question, "Synthetic answer.", "", "Line 1")])
    counter = CountingStore(app.state.store)
    app.state.store = counter
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            for fragment in COMPLETE_BEHAVIORAL_FRAGMENTS:
                assert ws.receive_json()["text"] == fragment
            # The window elapsed and its retrieval is blocked upstream.
            assert retrieval_started.wait(10)
            # A new final is relayed while that delivery is in flight.
            next_final_gate.set()
            assert ws.receive_json()["text"] == NEXT_QUESTION_FINAL
            retrieval_release.set()
            # The settled delivery still arrives, then the independent question.
            settled = ws.receive_json()
            assert settled["question"] == settled_question
            assert settled["match_type"] == "exact_qa"
            independent = ws.receive_json()
            assert independent["question"] == NEXT_QUESTION
            assert independent["match_type"] == "exact_qa"
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    # Retrieval order proves the in-flight delivery was awaited, not cancelled.
    assert counter.calls == [settled_question, NEXT_QUESTION]


@pytest.mark.parametrize("text", [
    '"Can you tell me about a time when you improved it"',
    "Tell me if the transcript appears on screen",
    "Can you tell me about a time when you said the build failed",
])
def test_deepgram_compound_candidate_keeps_shared_safety_filters(text):
    """Quoted text, office-display checks and reported speech stay rejected."""
    assert live._single_question_candidate(text) == []


def test_deepgram_settled_delivery_failure_is_reported_once(tmp_path, monkeypatch):
    """A failed settled delivery is reported without new PCM or the idle timeout."""
    monkeypatch.setattr("app.live.ASSEMBLY_SETTLE_SECONDS", 0.05)

    def failing_retrieve(store, question, semantic=None):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("app.live._retrieve_live", failing_retrieve)
    app, _counter = assemble_app(tmp_path, [finals(*COMPLETE_BEHAVIORAL_FRAGMENTS)])
    with TestClient(app) as client:
        _sid, token = connect(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            begin(ws, token)
            for fragment in COMPLETE_BEHAVIORAL_FRAGMENTS:
                assert ws.receive_json()["text"] == fragment
            # No further PCM is sent: the failure signal must wake the receive loop.
            started = time.perf_counter()
            error = ws.receive_json()
            elapsed = time.perf_counter() - started
            assert error["type"] == "error" and error["code"] == "internal_error"
            assert elapsed < 5.0
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


@pytest.mark.parametrize(("fragment", "expected"), [
    ("¿Y qué cambiaste después?",
     "Cuéntame sobre una vez que mejoraste el tiempo de respuesta ¿Y qué cambiaste después"),
    ("y cómo lo mediste",
     "Cuéntame sobre una vez que mejoraste el tiempo de respuesta y cómo lo mediste"),
    ("Y POR QUÉ FALLÓ EL SERVICIO",
     "Cuéntame sobre una vez que mejoraste el tiempo de respuesta Y POR QUÉ FALLÓ EL SERVICIO"),
])
def test_deepgram_spanish_coordinated_follow_up_is_appended(fragment, expected):
    """The reported Spanish forms join the settled compound as one candidate."""
    assembly = DeepgramQuestionAssembly()
    assert observed(assembly, "Cuéntame sobre una vez") == []
    assert observed(assembly, "que mejoraste el tiempo de respuesta") == []
    candidates = assembly.observe(fragment)
    assert len(candidates) == 1 and candidates[0].compound
    assert candidates[0].text == expected
    # The compound was emitted once: no settled candidate or deadline remains.
    assert assembly.take_settled() is None and assembly.settle_deadline() is None
