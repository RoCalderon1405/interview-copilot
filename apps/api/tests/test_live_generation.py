"""Automatic fallback integration and lifecycle, with synthetic text and fake STT/LLM."""
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.generation import GeneratedSuggestion, GenerationError, GenerationService
from app.live import FeedResult
from app.live_generation import LiveGeneration
from app.main import create_app
from app.domain.knowledge import ParsedEntry


class Models:
    async def open(self, language):
        from app.infrastructure.vosk import VoskSession
        return await VoskSession.open(self, language)

    def availability(self):
        return {"provider": "vosk", "available": True,
                "languages": {language: {"available": True} for language in ("en-US", "es-MX")}}

    def __init__(self, *results):
        self.results = list(results)

    def create_recognizer(self, language):
        return object()

    def feed(self, recognizer, audio):
        return self.results.pop(0) if self.results else FeedResult(partial="audio continues")

    def finish(self, recognizer):
        return FeedResult(final="Explain final flush?")


class Provider:
    name = "ollama"
    model = "synthetic-local"

    def __init__(self, *, slow=False, error=None):
        self.slow = slow
        self.error = error
        self.calls = []
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def generate(self, question, language):
        self.calls.append((question, language))
        self.started.set()
        try:
            if self.slow:
                await asyncio.Event().wait()
            if self.error:
                raise self.error
            return "A synthetic practical answer."
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def session(client, language="en-US"):
    sid = client.post('/sessions', json={"mode": "live"}).json()['id']
    token = client.post(f'/sessions/{sid}/live-token', json={"consent": True, "language": language}).json()['token']
    return sid, token


def start(client, token):
    ws = client.websocket_connect('/live/transcribe', headers={"origin": "http://localhost:5173"})
    return ws


def receive_final(ws):
    ws.send_bytes(b'\0\0' * 1600)
    assert ws.receive_json()['type'] == 'final'
    return ws.receive_json()


def stop(ws):
    ws.send_text('stop')
    # Existing final-flush documentary events are preserved, but never generated.
    while True:
        try:
            assert ws.receive_json()['type'] != 'generated_suggestion'
        except WebSocketDisconnect:
            break


@pytest.mark.parametrize('language,question', [('en-US', 'Explain caching?'), ('es-MX', 'Explica la caché?')])
def test_eligible_final_generates_correlated_additive_event(tmp_path, language, question):
    app = create_app(tmp_path)
    provider = Provider()
    app.state.generation = GenerationService(provider, enabled=True)
    app.state.live.models = Models(FeedResult(final=question))
    with TestClient(app) as client:
        sid, token = session(client, language)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            assert ws.receive_json()['type'] == 'ready'
            documentary = receive_final(ws)
            assert documentary['status'] == 'no_evidence'
            event = ws.receive_json()
            assert event == dict(type='generated_suggestion', kind='ai_generated', session_id=sid,
                question_id=documentary['question_id'], question=documentary['question'], language=language,
                answer='A synthetic practical answer.', provider='ollama', model='synthetic-local', source=None)
            assert 'match_type' not in event and 'status' not in event
            assert provider.calls == [(documentary['question'], language)]
            stop(ws)
    assert app.state.live.generations == {}
    assert app.state.store.get_session(sid)['mode'] == 'live'
    with app.state.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM session_answers').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['exact', 'semantic', 'disabled', 'unconfigured'])
def test_documentary_priority_and_opt_in_gate(tmp_path, kind):
    app = create_app(tmp_path)
    provider = Provider()
    app.state.generation = (GenerationService(enabled=True) if kind == 'unconfigured'
                            else GenerationService(provider, enabled=kind != 'disabled'))
    question = 'What is caching?'
    if kind == 'exact':
        app.state.store.import_document('synthetic.md', b'synthetic',
            [ParsedEntry('qa', question, 'Stored answer.', '', 'Line 1')])
    if kind == 'semantic':
        class Semantic:
            def candidate(self, question):
                return dict(status='found', answer='Possible stored answer.', match_type='semantic_qa',
                            source={"document_name": "synthetic.md", "location": "Line 1"})
        app.state.semantic = Semantic()
    app.state.live.models = Models(FeedResult(final=question))
    with TestClient(app) as client:
        _, token = session(client)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            ws.receive_json()
            event = receive_final(ws)
            assert event['status'] == ('found' if kind in ('exact', 'semantic') else 'no_evidence')
            ws.send_bytes(b'\0\0')
            assert ws.receive_json()['type'] == 'partial'
            stop(ws)
    assert provider.calls == []


@pytest.mark.parametrize('ending', ['stop', 'disconnect', 'finish'])
def test_slow_generation_does_not_block_pcm_and_teardown_cancels(tmp_path, ending):
    app = create_app(tmp_path)
    provider = Provider(slow=True)
    app.state.generation = GenerationService(provider, enabled=True)
    app.state.live.models = Models(FeedResult(final='Explain caching?'))
    with TestClient(app) as client:
        sid, token = session(client)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            ws.receive_json()
            receive_final(ws)
            assert provider.started.wait(2)
            ws.send_bytes(b'\0\0')
            assert ws.receive_json() == dict(type='partial', text='audio continues', language='en-US')
            if ending == 'stop':
                stop(ws)
            elif ending == 'finish':
                assert client.post(f'/sessions/{sid}/finish').status_code == 200
                assert provider.cancelled.wait(2)
                stop(ws)
            # Exiting without stop exercises WS disconnect cancellation.
    assert provider.cancelled.wait(2)
    assert len(provider.calls) == 1
    assert app.state.live.generations == {}


@pytest.mark.parametrize('failure', ['unavailable', 'timeout'])
def test_generation_failure_keeps_audio_alive(tmp_path, failure, caplog):
    app = create_app(tmp_path)
    provider = Provider(slow=failure == 'timeout', error=GenerationError('unavailable'))
    app.state.generation = GenerationService(provider, enabled=True, timeout_seconds=0.01)
    app.state.live.models = Models(FeedResult(final='Explain caching?'))
    with TestClient(app) as client:
        _, token = session(client)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            ws.receive_json()
            receive_final(ws)
            assert provider.started.wait(2)
            if failure == 'timeout':
                assert provider.cancelled.wait(2)
            ws.send_bytes(b'\0\0')
            assert ws.receive_json()['type'] == 'partial'
            stop(ws)
    assert len(provider.calls) == 1
    assert 'Explain caching' not in caplog.text


def test_content_rejection_keeps_no_evidence_audio_and_teardown_without_retry(
        tmp_path, caplog):
    # EN/ES lexical variants belong to unit tests; this case protects the Live path.
    language, question = 'es-MX', 'Explica la caché?'
    answer = 'Dirigí un equipo y aumenté los ingresos un 30%.'

    class UnsafeProvider(Provider):
        async def generate(self, question, language):
            await super().generate(question, language)
            return answer

    app = create_app(tmp_path)
    provider = UnsafeProvider()
    app.state.generation = GenerationService(provider, enabled=True)
    app.state.live.models = Models(FeedResult(final=question))
    with TestClient(app) as client:
        _, token = session(client, language)
        with start(client, token) as ws:
            ws.send_json({'type': 'start', 'token': token})
            assert ws.receive_json()['type'] == 'ready'
            assert receive_final(ws)['status'] == 'no_evidence'
            assert provider.started.wait(2)
            ws.send_bytes(b'\0\0')
            assert ws.receive_json()['type'] == 'partial'
            stop(ws)  # Fails on any generated event, including a late replacement.
    assert len(provider.calls) == 1
    assert app.state.live.generations == {}
    assert answer not in caplog.text


def test_partials_never_generate_even_when_repeated(tmp_path):
    app = create_app(tmp_path)
    provider = Provider()
    app.state.generation = GenerationService(provider, enabled=True)
    app.state.live.models = Models(*[FeedResult(partial='Explain caching?') for _ in range(6)])
    with TestClient(app) as client:
        _, token = session(client)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            ws.receive_json()
            for _ in range(6):
                ws.send_bytes(b'\0\0')
                assert ws.receive_json()['type'] == 'partial'
            stop(ws)
    assert provider.calls == []


def test_invalid_configuration_does_not_prevent_startup(tmp_path, monkeypatch):
    monkeypatch.setenv('COPILOT_LLM_ENABLED', 'true')
    monkeypatch.setenv('COPILOT_OLLAMA_MODEL', 'local')
    monkeypatch.setenv('COPILOT_LLM_TIMEOUT_SECONDS', 'invalid')
    app = create_app(tmp_path)
    assert not app.state.generation.available
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200


def test_worker_replaces_pending_and_discards_cancellation_resistant_result():
    async def scenario():
        class Store:
            def get_session(self, sid):
                return dict(mode='live', finished_at=None)

        class Service:
            available = True
            def __init__(self):
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()
                self.release = asyncio.Event()
                self.calls = []
                self.active = self.max_active = 0

            async def generate(self, question, language):
                self.calls.append(question)
                self.active += 1
                self.max_active = max(self.active, self.max_active)
                try:
                    if len(self.calls) == 1:
                        self.started.set()
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            self.cancelled.set()
                            await self.release.wait()
                    return GeneratedSuggestion(question, 'ollama', 'local')
                finally:
                    self.active -= 1

        service = Service()
        events = []
        sent = asyncio.Event()
        async def send(event):
            events.append(event)
            sent.set()

        worker = LiveGeneration(service, Store(), 'synthetic', 'en-US', send, asyncio.Lock())
        worker.supersede()
        worker.submit('Old question?')
        await asyncio.wait_for(service.started.wait(), 2)
        worker.supersede()
        worker.submit('Middle question?')
        await asyncio.wait_for(service.cancelled.wait(), 2)
        worker.supersede()
        worker.submit('Latest question?')
        service.release.set()
        await asyncio.wait_for(sent.wait(), 2)
        assert service.calls == ['Old question?', 'Latest question?']
        assert service.max_active == 1
        assert len(events) == 1 and events[0]['question'] == 'Latest question?'
        assert events[0]['question_id'] == worker.question_id
        await worker.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('newer_document', [False, True])
def test_newer_final_supersedes_old_generation_without_overwriting(tmp_path, newer_document):
    class FirstSlow(Provider):
        async def generate(self, question, language):
            self.slow = not self.calls
            return await super().generate(question, language)

    app = create_app(tmp_path)
    provider = FirstSlow()
    app.state.generation = GenerationService(provider, enabled=True)
    if newer_document:
        app.state.store.import_document('synthetic.md', b'synthetic',
            [ParsedEntry('qa', 'What is authentication?', 'Stored answer.', '', 'Line 1')])
    app.state.live.models = Models(FeedResult(final='Explain caching?'), FeedResult(final='What is authentication?'))
    with TestClient(app) as client:
        _, token = session(client)
        with start(client, token) as ws:
            ws.send_json({"type": "start", "token": token})
            ws.receive_json()
            old = receive_final(ws)
            assert provider.started.wait(2)
            new = receive_final(ws)
            assert old['question_id'] != new['question_id']
            assert provider.cancelled.wait(2)
            if newer_document:
                assert new['match_type'] == 'exact_qa'
                assert len(provider.calls) == 1
            else:
                result = ws.receive_json()
                assert result['type'] == 'generated_suggestion'
                assert result['question_id'] == new['question_id']
                assert result['question'] == new['question']
                assert len(provider.calls) == 2
            stop(ws)


@pytest.mark.parametrize('ending', ['supersede', 'close', 'session_finished'])
def test_completed_but_unsent_result_is_suppressed(ending):
    async def scenario():
        class Store:
            finished = False
            def get_session(self, sid):
                return dict(mode='live', finished_at='finished' if self.finished else None)

        class Service:
            available = True
            def __init__(self):
                self.started = asyncio.Event()
                self.release = asyncio.Event()
            async def generate(self, question, language):
                self.started.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    # An obsolete result must still be rejected if cancellation is swallowed.
                    pass
                return GeneratedSuggestion('Obsolete answer.', 'ollama', 'local')

        store, service = Store(), Service()
        events = []
        async def send(event):
            events.append(event)

        worker = LiveGeneration(service, store, 'synthetic', 'en-US', send, asyncio.Lock())
        worker.supersede()
        worker.submit('Old question?')
        await asyncio.wait_for(service.started.wait(), 2)
        if ending == 'supersede':
            worker.supersede() # newer documentary question; no replacement generation
        elif ending == 'close':
            await worker.close()
        else:
            store.finished = True
        service.release.set()
        await asyncio.wait_for(worker._worker, 2)
        assert events == []
        await worker.close()

    asyncio.run(scenario())
