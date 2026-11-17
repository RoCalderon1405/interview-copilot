"""Offline Nova-3 streaming contracts: segment assembly, cloud opt-in and teardown."""
from __future__ import annotations

import asyncio
import json
from collections import deque

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.stt import FeedResult, SpeechFailure, SpeechOverloaded, StreamingTranscriptionPump
from app.infrastructure.deepgram import DeepgramProvider, DeepgramSession
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
    def availability(self):
        return {"provider": "deepgram", "available": True, "runtime_installed": True,
                "languages": {name: {"available": True} for name in ("en-US", "es-MX")},
                "detail": "Synthetic cloud"}
    async def open(self, language):
        self.languages.append(language)
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
            "language": "en-US", "provider": "deepgram", "consent": True})
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
        assert fake.languages == ["en-US"] and fake.session.closed
    assert not list(tmp_path.rglob("*.wav"))
