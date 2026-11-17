"""Synthetic CPU-independent contracts for bounded speech and provider selection."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
import sys
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.stt import (FeedResult, MAX_SEGMENT_BYTES, SpeechFailure, SpeechOverloaded,
                                 SpeechSegmenter, TranscriptionPump)
from app.infrastructure.faster_whisper import FasterWhisperProvider, WhisperSession
from app.main import create_app
from app.parsers import ParsedEntry

VOICE = struct.pack("<h", 1500) * 1600
SILENCE = bytes(3200)
HEADERS = {"origin": "http://localhost:5173"}


def utterance(segmenter: SpeechSegmenter) -> list:
    results = []
    for index, frame in enumerate([VOICE] * 3 + [SILENCE] * 5):
        results.extend(segmenter.feed(frame, (index + 1) / 10))
    return results


def test_segmenter_silence_and_analysis_remainder_stay_bounded():
    segmenter = SpeechSegmenter()
    for index in range(10000):
        assert segmenter.feed(bytes(642), index / 50) == []
        assert segmenter.buffered_bytes <= 6400 + 638
    segmenter.clear()
    assert segmenter.buffered_bytes == 0


def test_segmenter_endpoint_preroll_voice_gate_and_hard_cap():
    segmenter = SpeechSegmenter()
    segmenter.feed(SILENCE * 2, 0.2)
    chunks = utterance(segmenter)
    assert len(chunks) == 1
    assert chunks[0].reason == "silence"
    assert chunks[0].pcm.startswith(SILENCE * 2)
    assert chunks[0].start_sample == 0
    assert len(chunks[0].pcm) <= MAX_SEGMENT_BYTES
    short = SpeechSegmenter()
    assert short.feed(VOICE + SILENCE * 5, 0.6) == []
    long = SpeechSegmenter()
    forced = []
    for index in range(200):
        forced.extend(long.feed(VOICE, index / 10))
        assert long.buffered_bytes <= MAX_SEGMENT_BYTES + 6400
    assert len(forced) == 2
    assert all(chunk.reason == "limit" and len(chunk.pcm) == MAX_SEGMENT_BYTES for chunk in forced)
    assert forced[1].start_sample == 8 * 16000


def test_endpoint_preroll_keeps_original_quiet_pcm_not_repeated_last_frame():
    segmenter = SpeechSegmenter()
    segmenter.feed(VOICE * 3, 0.3)
    quiet = [struct.pack("<h", value) * 320 for value in range(1, 26)]
    assert len(segmenter.feed(b"".join(quiet), 0.8)) == 1
    chunks = utterance(segmenter)
    assert chunks[0].pcm.startswith(b"".join(quiet[-10:]))


@pytest.mark.parametrize("pcm", [b"x", bytes(64002)])
def test_segmenter_rejects_invalid_pcm(pcm):
    with pytest.raises(SpeechFailure):
        SpeechSegmenter().feed(pcm, 0)


class FakeSession:
    def __init__(self, text="What is authentication?", slow=False):
        self.text = text
        self.slow = slow
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.closed = False
        self.calls = []

    async def feed(self, pcm):
        self.calls.append(pcm)
        self.started.set()
        try:
            if self.slow:
                await asyncio.Event().wait()
            return FeedResult(final=self.text, last_word_end_seconds=0.2)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def finish(self):
        return FeedResult(final="How do you test code?")

    async def close(self):
        self.closed = True


class FakeWhisper:
    def __init__(self, session=None, available=True, slow_open=False):
        self.session = session or FakeSession()
        self.available = available
        self.languages = []
        self.slow_open = slow_open
        self.opened = threading.Event()
        self.open_cancelled = threading.Event()

    def availability(self):
        return {"provider": "faster-whisper", "available": self.available,
                "languages": {language: {"available": self.available} for language in ("en-US", "es-MX")}}

    async def open(self, language):
        self.languages.append(language)
        self.opened.set()
        try:
            if self.slow_open:
                await asyncio.Event().wait()
            return self.session
        except asyncio.CancelledError:
            self.open_cancelled.set()
            raise


def test_pump_one_active_one_pending_and_cancel_discards_pcm_and_results():
    async def run():
        session = FakeSession(slow=True)
        events = []

        async def emit(result, stopping):
            events.append(result)

        pump = TranscriptionPump(session, segmented=True, emit=emit)
        for frame in [VOICE] * 3 + [SILENCE] * 5:
            pump.feed(frame)
        await asyncio.sleep(0)
        assert session.started.is_set()
        for frame in [VOICE] * 3 + [SILENCE] * 5:
            pump.feed(frame)
        assert 0 < pump.queued_bytes <= MAX_SEGMENT_BYTES
        with pytest.raises(SpeechOverloaded):
            for frame in [VOICE] * 3 + [SILENCE] * 5:
                pump.feed(frame)
        await pump.close()
        assert pump.queued_bytes == 0 and pump.segmenter.buffered_bytes == 0
        assert session.closed and session.cancelled.is_set() and not events
    asyncio.run(run())


def test_pump_offsets_timestamps_measures_endpoint_and_preserves_streaming_stop():
    async def run():
        events = []

        async def emit(result, stopping):
            events.append((result, stopping))

        pump = TranscriptionPump(FakeSession(), segmented=True, emit=emit, clock=lambda: 10)
        for _ in range(10):
            pump.feed(SILENCE)
        for frame in [VOICE] * 3 + [SILENCE] * 5:
            pump.feed(frame)
        await asyncio.sleep(0)
        result = events[0][0]
        assert result.partial is None
        assert result.last_word_end_seconds == pytest.approx(1.0)
        assert result.end_of_speech_latency_ms is not None
        await pump.close()
        events.clear()
        streaming = TranscriptionPump(FakeSession(), segmented=False, emit=emit)
        streaming.feed(VOICE)
        await streaming.finish()
        assert [item[0].final for item in events] == ["What is authentication?", "How do you test code?"]
        assert all(item[1] for item in events)
        await streaming.close()
    asyncio.run(run())


def test_forced_cut_is_not_an_eos_measurement_or_complete_utterance():
    async def run():
        results = []

        async def emit(result, stopping): results.append(result)

        pump = TranscriptionPump(FakeSession(), segmented=True, emit=emit)
        for _ in range(80): pump.feed(VOICE)
        await asyncio.sleep(0)
        assert len(results) == 1 and results[0].utterance_complete is False
        assert results[0].end_of_speech_latency_ms is None
        await pump.close()
    asyncio.run(run())


@pytest.mark.parametrize("tiny_frames", [False, True])
def test_streaming_queue_enforces_independent_item_and_byte_limits(tiny_frames):
    async def run():
        session = FakeSession(slow=True)

        async def emit(result, stopping): pass

        pump = TranscriptionPump(session, segmented=False, emit=emit)
        pump.feed(VOICE)
        await asyncio.sleep(0)
        for _ in range(20 if tiny_frames else 1):
            pump.feed(b"\0\0" if tiny_frames else bytes(64000))
        with pytest.raises(SpeechOverloaded): pump.feed(b"\0\0")
        await pump.close()
        assert pump.queued_bytes == 0
    asyncio.run(run())


def token(client, language="en-US", provider="faster-whisper"):
    sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
    response = client.post(f"/sessions/{sid}/live-token", json={"language": language, "provider": provider, "consent": True})
    assert response.status_code == 200, response.text
    return sid, response.json()["token"]


def test_provider_status_defaults_and_unavailable_or_unsupported_selection(tmp_path):
    app = create_app(tmp_path)
    app.state.live.whisper = FakeWhisper(available=False)
    # Avoid relying on optional locally installed Vosk models for API selection.
    class AvailableVosk:
        def availability(self):
            return {"provider": "vosk", "available": True, "runtime_installed": True,
                    "languages": {"en-US": {"available": True}, "es-MX": {"available": True}},
                    "detail": "Synthetic Vosk"}
    app.state.live.models = AvailableVosk()
    with TestClient(app) as client:
        status = client.get("/live/status").json()
        assert status["provider"] == status["default_provider"] == "vosk"
        assert set(status["providers"]) == {"vosk", "faster-whisper", "deepgram"}
        sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
        for provider, expected in (("deepgram", 503), ("faster-whisper", 503), ("invalid", 422)):
            response = client.post(f"/sessions/{sid}/live-token",
                                   json={"language": "en-US", "provider": provider, "consent": True})
            assert response.status_code == expected
        default = client.post(f"/sessions/{sid}/live-token", json={"language": "en-US", "consent": True}).json()
        assert default["provider"] == "vosk"


@pytest.mark.parametrize("field,value,code", [("provider", "vosk", "provider_mismatch"),
                                             ("language", "es-MX", "language_mismatch")])
def test_token_binds_provider_and_language_and_remains_single_use(tmp_path, field, value, code):
    app = create_app(tmp_path)
    fake = FakeWhisper()
    app.state.live.whisper = fake
    with TestClient(app) as client:
        _, grant = token(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant, field: value})
            assert ws.receive_json()["code"] == code
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant})
            assert ws.receive_json()["code"] == "invalid_token"
        assert not fake.languages


@pytest.mark.parametrize("language,question", [("en-US", "What is authentication?"),
                                              ("es-MX", "Qué es la autenticación?")])
def test_whisper_final_uses_existing_documentary_pipeline(tmp_path, language, question):
    app = create_app(tmp_path)
    fake = FakeWhisper(FakeSession(question))
    app.state.live.whisper = fake
    app.state.store.import_document("synthetic.md", b"synthetic",
                                    [ParsedEntry("qa", question, "Stored wording.", "", "Line 1")])
    with TestClient(app) as client:
        _, grant = token(client, language)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant})
            assert ws.receive_json()["provider"] == "faster-whisper"
            for frame in [VOICE] * 3 + [SILENCE] * 5:
                ws.send_bytes(frame)
            final = ws.receive_json()
            assert final["type"] == "final" and final["language"] == language
            assert final["end_of_speech_latency_ms"] >= 0
            suggestion = ws.receive_json()
            assert suggestion["match_type"] == "exact_qa"
            assert suggestion["answer"] == "Stored wording."
            assert suggestion["source"]["document_name"] == "synthetic.md"
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert fake.languages == [language] and fake.session.closed
    assert not list(tmp_path.rglob("*.wav"))


@pytest.mark.parametrize("ending", ["stop", "disconnect", "finish"])
@pytest.mark.parametrize("during_startup", [False, True])
def test_stop_disconnect_and_session_finish_cancel_startup_or_inference(tmp_path, ending, during_startup):
    app = create_app(tmp_path)
    fake = FakeWhisper(FakeSession(slow=True), slow_open=during_startup)
    app.state.live.whisper = fake
    with TestClient(app) as client:
        sid, grant = token(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant})
            if during_startup:
                assert fake.opened.wait(2)
            else:
                assert ws.receive_json()["type"] == "ready"
                for frame in [VOICE] * 3 + [SILENCE] * 5:
                    ws.send_bytes(frame)
                assert fake.session.started.wait(2)
                # PCM reception stays responsive while inference is suspended.
                for _ in range(30):
                    ws.send_bytes(SILENCE)
            if ending == "disconnect":
                ws.close()
            elif ending == "finish":
                assert client.post(f"/sessions/{sid}/finish").status_code == 200
                assert ws.receive_json()["code"] == "session_finished"
            else:
                ws.send_text("stop")
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
        assert (fake.open_cancelled if during_startup else fake.session.cancelled).wait(2)
        assert not app.state.live.transcriptions
        assert app.state.live.acquire_connection()
        app.state.live.release_connection()


def test_native_subprocess_is_terminated_and_reaped_on_cancellation(tmp_path, monkeypatch):
    script = tmp_path / "fake_worker.py"
    script.write_text("import sys,time\nprint('{\"type\":\"ready\"}',flush=True)\nsys.stdin.buffer.read(4)\ntime.sleep(60)\n")
    monkeypatch.setattr("app.infrastructure.faster_whisper.WORKER", script)
    provider = FasterWhisperProvider(Path(sys.executable), tmp_path)
    monkeypatch.setattr(provider, "availability", lambda: {"available": True})

    async def run():
        session = await provider.open("en-US")
        process = session.process
        active = asyncio.create_task(session.feed(VOICE))
        await asyncio.sleep(0.05)
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
        await session.close()
        assert process.returncode is not None
        await session.close()
    asyncio.run(run())


@pytest.mark.parametrize("payload", [{"type": "error"}, {"type": "final", "text": "x" * 3001},
                                     {"type": "final", "text": "synthetic", "end": -1},
                                     {"type": "final", "text": "synthetic", "end": 100},
                                     {"type": "final", "text": "synthetic", "end": True}])
def test_whisper_adapter_rejects_unbounded_or_invalid_native_results(payload):
    class Input:
        def write(self, pcm): pass
        async def drain(self): pass

    async def run():
        session = WhisperSession()
        from types import SimpleNamespace
        session.process = SimpleNamespace(stdin=Input())

        async def read(): return payload
        session.read = read
        with pytest.raises(SpeechFailure):
            await session.feed(VOICE)
    asyncio.run(run())


def test_ws_overload_fails_explicitly_without_switching_provider(tmp_path):
    app = create_app(tmp_path)
    fake = FakeWhisper(FakeSession(slow=True))
    app.state.live.whisper = fake
    with TestClient(app) as client:
        _, grant = token(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant})
            assert ws.receive_json()["type"] == "ready"
            for frame in [VOICE] * 3 + [SILENCE] * 5:
                ws.send_bytes(frame)
            assert fake.session.started.wait(2)
            for frame in ([VOICE] * 3 + [SILENCE] * 5) * 2:
                ws.send_bytes(frame)
            assert ws.receive_json()["code"] == "speech_overloaded"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert fake.session.closed and len(fake.languages) == 1


@pytest.mark.parametrize("kind", ["semantic", "generated", "disabled", "limit"])
def test_whisper_keeps_semantic_priority_and_opt_in_ollama_contract(tmp_path, kind):
    from app.application.generation import GenerationService

    class Generation:
        name = "ollama"
        model = "synthetic-local"

        def __init__(self): self.calls = []

        async def generate(self, question, language):
            self.calls.append((question, language))
            return "Synthetic generated suggestion."

    class Semantic:
        def candidate(self, question):
            return dict(status="found", answer="Possible stored answer.", match_type="semantic_qa",
                        source={"document_name": "synthetic.md", "location": "Line 1"})

    app = create_app(tmp_path)
    fake = FakeWhisper(FakeSession("Explain authentication?"))
    app.state.live.whisper = fake
    generation = Generation()
    app.state.generation = GenerationService(generation, enabled=kind != "disabled")
    if kind == "semantic":
        app.state.semantic = Semantic()
    with TestClient(app) as client:
        _, grant = token(client)
        with client.websocket_connect("/live/transcribe", headers=HEADERS) as ws:
            ws.send_json({"type": "start", "token": grant})
            assert ws.receive_json()["type"] == "ready"
            for frame in ([VOICE] * 80 if kind == "limit" else [VOICE] * 3 + [SILENCE] * 5):
                ws.send_bytes(frame)
            assert ws.receive_json()["type"] == "final"
            suggestion = ws.receive_json()
            if kind == "semantic":
                assert suggestion["match_type"] == "semantic_qa"
            else:
                assert suggestion["status"] == "no_evidence"
            if kind == "generated":
                generated = ws.receive_json()
                assert generated["type"] == "generated_suggestion" and generated["source"] is None
                assert generated["provider"] == "ollama" and len(generation.calls) == 1
            else:
                assert not generation.calls
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect): ws.receive_json()


def test_native_worker_startup_cancellation_reaps_child(tmp_path, monkeypatch):
    script = tmp_path / "slow_start.py"
    script.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr("app.infrastructure.faster_whisper.WORKER", script)
    provider = FasterWhisperProvider(Path(sys.executable), tmp_path)
    monkeypatch.setattr(provider, "availability", lambda: {"available": True})
    original = asyncio.create_subprocess_exec
    processes = []

    async def start(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)

    async def run():
        opening = asyncio.create_task(provider.open("es-MX"))
        while not processes:
            await asyncio.sleep(0.01)
        opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)
        assert processes[0].returncode is not None
    asyncio.run(run())


@pytest.mark.parametrize("language", ["en", "es"])
def test_mocked_native_worker_uses_cpu_int8_local_only_and_bounded_final(tmp_path, monkeypatch, language):
    import io
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.infrastructure import whisper_worker

    model = MagicMock()
    model.model.device = "cpu"
    model.model.is_multilingual = True
    model.transcribe.return_value = (iter([SimpleNamespace(text=" synthetic ", words=[SimpleNamespace(end=0.1)])]), None)
    factory = MagicMock(return_value=model)
    numpy = MagicMock()
    output = io.BytesIO()
    with monkeypatch.context() as context:
        for key in ("CUDA_VISIBLE_DEVICES", "HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "OMP_NUM_THREADS"):
            context.setenv(key, "test-only")
        context.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
        context.setitem(sys.modules, "numpy", numpy)
        context.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_supported_compute_types=lambda device: {"int8"}))
        context.setattr(sys, "argv", ["worker", "--model", str(tmp_path), "--language", language])
        context.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(struct.pack("<I", len(VOICE)) + VOICE)))
        context.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        whisper_worker.main()
        import os
        assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"
        assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert [json.loads(line) for line in output.getvalue().splitlines()] == [
        {"type": "ready"}, {"type": "final", "text": "synthetic", "end": 0.1}]
    factory.assert_called_once_with(str(tmp_path.resolve()), device="cpu", compute_type="int8", cpu_threads=4,
                                    num_workers=1, local_files_only=True)
    assert model.transcribe.call_args.kwargs["language"] == language
    assert model.transcribe.call_args.kwargs["word_timestamps"] is True


def test_native_inference_deadline_is_bounded_and_failed_worker_is_reapable(tmp_path, monkeypatch):
    script = tmp_path / "timeout_worker.py"
    script.write_text("import sys,time\nprint('{\"type\":\"ready\"}',flush=True)\nsys.stdin.buffer.read(4)\ntime.sleep(60)\n")
    monkeypatch.setattr("app.infrastructure.faster_whisper.WORKER", script)
    monkeypatch.setattr("app.infrastructure.faster_whisper.INFERENCE_TIMEOUT_SECONDS", 0.05)
    provider = FasterWhisperProvider(Path(sys.executable), tmp_path)
    monkeypatch.setattr(provider, "availability", lambda: {"available": True})

    async def run():
        session = await provider.open("en-US")
        process = session.process
        with pytest.raises(SpeechFailure, match="worker_timeout_or_exit"):
            await session.feed(VOICE)
        await session.close()
        assert process.returncode is not None
    asyncio.run(run())
