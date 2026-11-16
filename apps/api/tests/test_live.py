"""Live audio transport, token, question-detection and real-Vosk integration tests.

All knowledge entries and audio fixtures are synthetic. Transport tests use a
fake recognizer only to drive the WebSocket protocol; the real pipeline test at
the bottom loads the locally installed Vosk models against synthetic WAV files.
"""
from __future__ import annotations

import json
import sqlite3
import time
import wave
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.live import (
    DEDUPE_CAPACITY,
    DEDUPE_TTL_SECONDS,
    MAX_CONTROL_CHARS,
    MAX_QUESTION_CANDIDATES,
    MAX_TRANSCRIPT_CHARS,
    PARTIAL_STABILITY_FRAMES,
    StablePartialQuestion,
    FeedResult,
    LiveRuntime,
    LiveTokenManager,
    RecentFinalDedupe,
    SpeechUnavailable,
    VoskModelCache,
    detect_questions,
)
from app.main import create_app
from app.parsers import ParsedEntry
from app.textnorm import normalize

ALLOWED_HEADERS = {"origin": "http://localhost:5173"}
WAV_DIR = Path(__file__).resolve().parent / "fixtures" / "live_audio"


class CountingStore:
    """Delegating store that counts exact-lookup calls (proves partials never search)."""

    def __init__(self, store):
        self._store = store
        self.exact_calls = 0

    def __getattr__(self, name):
        return getattr(self._store, name)

    def find_exact_qa(self, question):
        self.exact_calls += 1
        return self._store.find_exact_qa(question)


class FakeRecognizer:
    pass


class FakeModelCache:
    def __init__(self, feed_results=None, finish_result=None):
        self.feed_results = list(feed_results or [])
        self.finish_result = finish_result or FeedResult()
        self.languages = []

    def create_recognizer(self, language):
        self.languages.append(language)
        return FakeRecognizer()

    def feed(self, recognizer, audio):
        return self.feed_results.pop(0) if self.feed_results else FeedResult()

    def finish(self, recognizer):
        return self.finish_result


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        yield c


def add_qa(store, document, question, answer):
    store.import_document(
        document,
        (document + question).encode(),
        [ParsedEntry("qa", question, answer, "", "Línea 1")],
    )


def create_live(client, language="en-US"):
    session_id = client.post("/sessions", json={"mode": "live"}).json()["id"]
    response = client.post(
        f"/sessions/{session_id}/live-token",
        json={"language": language, "consent": True},
    )
    assert response.status_code == 200, response.text
    return session_id, response.json()["token"]


def test_local_diagnostics_first_pcm_once_and_no_private_payload(client, monkeypatch, capsys):
    monkeypatch.setenv("COPILOT_LIVE_DIAGNOSTICS", "1")
    client.app.state.live.models = FakeModelCache()
    _, token = create_live(client)
    with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as ws:
        ws.send_json({"type": "start", "token": token})
        assert ws.receive_json()["type"] == "ready"
        for _ in range(100):
            ws.send_bytes(b"\x00\x00" * 3200)
        ws.send_text("stop")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    output = capsys.readouterr().out
    assert output.count('"stage": "pcm.first-receipt"') == 1
    assert token not in output
    assert len(output.splitlines()) <= 8
    assert '"stage": "cleanup.complete"' in output


def test_local_diagnostics_opt_in_and_sink_failure_are_safe(monkeypatch, capsys):
    from app.live import _diagnostic

    monkeypatch.delenv("COPILOT_LIVE_DIAGNOSTICS", raising=False)
    _diagnostic("pcm.first-receipt")
    assert not capsys.readouterr().out
    monkeypatch.setenv("COPILOT_LIVE_DIAGNOSTICS", "1")
    _diagnostic("private token transcript")
    assert not capsys.readouterr().out
    monkeypatch.setattr("builtins.print", lambda *a, **k: (_ for _ in ()).throw(OSError("sink")))
    _diagnostic("cleanup.complete")


def fake_client(tmp_path, feed_results=None, finish_result=None, clock=None):
    app = create_app(tmp_path)
    fake = FakeModelCache(feed_results, finish_result)
    app.state.live = LiveRuntime(models=fake, clock=clock or time.monotonic)
    return app, fake


def start(websocket, token):
    websocket.send_json({"type": "start", "token": token})
    return websocket.receive_json()


def pcm_frame(milliseconds=100):
    return b"\x00\x00" * (16 * milliseconds)


# --- Heuristic question detection -------------------------------------------


def test_detects_english_questions_with_and_without_punctuation():
    cases = [
        "What is authentication?",
        "what is authentication",
        "How do you handle conflict",
        "Can you tell me about a time you failed?",
        "Tell me about yourself.",
        "Describe a difficult project.",
        "Walk me through your last role.",
    ]
    for text in cases:
        assert detect_questions(text), text


def test_detects_spanish_questions_with_and_without_punctuation():
    cases = [
        "¿Cómo resuelves un conflicto en el equipo?",
        "como resuelves un conflicto en el equipo",
        "¿Puedes contarme sobre ti?",
        "Cuéntame sobre un proyecto difícil.",
        "Háblame de tu experiencia.",
    ]
    for text in cases:
        assert detect_questions(text), text


def test_ignores_statements_and_extracts_candidate_from_mixed_speech():
    assert detect_questions("I worked at Acme for five years.") == []
    assert detect_questions("Me gusta trabajar en equipo.") == []
    assert detect_questions("Okay. What is authentication?") == ["What is authentication"]


@pytest.mark.parametrize(
    ("spoken_final", "expected"),
    [
        ("ah got it the question is what is authentication", ["what is authentication"]),
        ("sure what is authentication", ["what is authentication"]),
        ("the question is what is authentication", ["what is authentication"]),
        ("la pregunta es qué es la autenticación", ["qué es la autenticación"]),
        ("the question is authentication verifies identity", []),
        ("I already answered what is authentication", []),
        (
            "sure thanks again for coming i'm looking for someone who can build reliable "
            "eighty eyes and explain their choices clearly to teammates so here's the question "
            "when designing a rest a p i how do you choose between get post put and patch",
            ["when designing a rest a p i how do you choose between get post put and patch"],
        ),
        ("okay so here's the question how do you select a database", ["how do you select a database"]),
        ("well here is the question why would you use redis", ["why would you use redis"]),
        ("pues ahora la pregunta es cómo manejarías el error", ["cómo manejarías el error"]),
        ("thanks for joining here's the question about my background", []),
        ("we discussed why we chose the database", []),
        ("authentication means proving who you are", []),
    ],
)
def test_question_detection_handles_spoken_introductions_without_false_embedded_matches(spoken_final, expected):
    """Regression corpus based on actual Windows Vosk transcript fragments."""
    assert detect_questions(spoken_final) == expected


def test_detector_is_documented_heuristic_not_semantic():
    """Cue-prefix matching is lexical; a statement that starts with a cue is accepted."""
    assert detect_questions("How I learned Python was through projects.") == [
        "How I learned Python was through projects"
    ]


def test_detector_caps_candidates_per_final():
    text = " ".join(f"What is question {index}?" for index in range(MAX_QUESTION_CANDIDATES + 5))
    candidates = detect_questions(text)
    assert len(candidates) == MAX_QUESTION_CANDIDATES
    assert candidates[0] == "What is question 0"
    assert candidates[-1] == f"What is question {MAX_QUESTION_CANDIDATES - 1}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("thanks for joining so how do you handle authentication", ["how do you handle authentication"]),
        ("we build APIs next question what is authentication", ["what is authentication"]),
        ("one what is authentication two why use dependency injection",
         ["what is authentication", "why use dependency injection"]),
        ("we have a few questions one what is authentication and two why would you use redis",
         ["what is authentication", "why would you use redis"]),
        ("first what is authentication second how do you test code",
         ["what is authentication", "how do you test code"]),
        ("1 what is authentication 2 why use redis",
         ["what is authentication", "why use redis"]),
        ("what is authentication and what is authorization",
         ["what is authentication", "what is authorization"]),
        ("thanks here is the question what is authentication and here is the question what is authorization",
         ["what is authentication", "what is authorization"]),
        ("what is authentication so how do you handle expired tokens",
         ["what is authentication", "how do you handle expired tokens"]),
        ("one when designing an API how do you choose between get and post two what is authorization",
         ["when designing an API how do you choose between get and post", "what is authorization"]),
        ("gracias por venir entonces cómo manejas los errores", ["cómo manejas los errores"]),
        ("trabajamos con APIs ahora qué es la autenticación", ["qué es la autenticación"]),
        ("uno qué es la autenticación dos por qué usar redis",
         ["qué es la autenticación", "por qué usar redis"]),
        ("primero qué es la autenticación segundo cómo eliges una base de datos",
         ["qué es la autenticación", "cómo eliges una base de datos"]),
        ("qué es la autenticación y cuál es la diferencia con autorización",
         ["qué es la autenticación", "cuál es la diferencia con autorización"]),
        ("por qué usar redis y cuál es la alternativa",
         ["por qué usar redis", "cuál es la alternativa"]),
        ("gracias la pregunta es qué es la autenticación y la siguiente pregunta cómo resuelves un conflicto",
         ["qué es la autenticación", "cómo resuelves un conflicto"]),
        ("la siguiente pregunta cuando diseñas una API cómo manejas los errores",
         ["cuando diseñas una API cómo manejas los errores"]),
        ("THANKS SO WHAT IS C++ AND WHAT IS C#", ["WHAT IS C++", "WHAT IS C#"]),
        ("so how do you handle auth orization", ["how do you handle auth orization"]),
    ],
)
def test_final_detects_marked_conversational_questions(text, expected):
    """Synthetic finals exercise only explicit transitions and enumerations."""
    assert detect_questions(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "thanks for joining today we build APIs how do you handle authentication",
        "we discussed how do you handle authentication yesterday",
        "we discussed so how do you handle authentication yesterday",
        "I already answered one what is authentication two why use redis",
        "the document contains the question what is authentication",
        "the example says one what is authentication two why use redis",
        'the interviewer wrote "so what is authentication and what is authorization"',
        'the sample contains "one what is authentication? two why use redis?"',
        "a sample 'here is the question what is authentication' is printed",
        "el documento dice la pregunta es qué es la autenticación",
        "discutimos entonces cómo manejas los errores",
        "el ejemplo contiene «uno qué es la autenticación dos por qué usar redis»",
        "gracias trabajamos con APIs como manejas los errores",
        "we have one database and two replicas",
        "we use tokens and what we store is encrypted",
        "thanks so how we handle errors depends on the service",
        "thanks so his authentication",
    ],
)
def test_final_does_not_scan_arbitrary_or_reported_interrogatives(text):
    assert detect_questions(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "how do you determine which database fits and why it matters",
        "explain how it works and why do we need a cache",
        "can you explain what is authentication and what is authorization",
        "explica cómo funciona y por qué necesitamos una caché",
        "cómo eliges una base de datos y qué factores consideras",
        'how do you parse "and what is authorization" safely',
        "what is authentication we use tokens in our services",
        "how do you apply what we discussed yesterday",
    ],
)
def test_final_preserves_subordinates_quotes_and_unmarked_trailing_context(text):
    assert detect_questions(text) == [text]


def test_marked_final_order_deduplication_and_limits():
    text = "one what is authentication two what is authentication three what is authorization"
    assert detect_questions(text) == ["what is authentication", "what is authorization"]
    assert detect_questions(text, limit=1) == ["what is authentication"]
    assert detect_questions(text, limit=0) == []
    many = " and ".join(f"what is concept {index}" for index in range(12))
    assert detect_questions(many) == [f"what is concept {index}" for index in range(MAX_QUESTION_CANDIDATES)]


@pytest.mark.parametrize(
    "partial",
    [
        "thanks for joining so how do you handle authentication",
        "one what is authentication two why use redis",
        "gracias entonces cómo manejas los errores",
    ],
)
def test_marked_final_segmentation_does_not_expand_partial_detection(partial):
    tracker = StablePartialQuestion()
    for _ in range(PARTIAL_STABILITY_FRAMES + 2):
        assert tracker.observe(partial) is None


def test_consecutive_questions_still_form_one_partial_candidate():
    partial = "what is authentication and what is authorization"
    tracker = StablePartialQuestion()
    for _ in range(PARTIAL_STABILITY_FRAMES - 1):
        assert tracker.observe(partial) is None
    assert tracker.observe(partial) == partial


def test_final_result_reads_vosk_word_end_timing():
    from app.live import _final_result

    result = _final_result(json.dumps({
        "text": "what is authentication",
        "result": [
            {"word": "what", "start": 0.1, "end": 0.3},
            {"word": "authentication", "start": 1.6, "end": 2.09},
        ],
    }))
    assert result.final == "what is authentication"
    assert result.last_word_end_seconds == 2.09
    assert _final_result('{"text": "hello"}').last_word_end_seconds is None
    assert _final_result('{"text": ""}').final is None


# --- Bounded dedupe ----------------------------------------------------------


def test_dedupe_normalizes_and_releases_after_ttl():
    now = [0.0]
    dedupe = RecentFinalDedupe(clock=lambda: now[0])
    assert dedupe.seen("What is authentication?") is False
    assert dedupe.seen("what is authentication") is True
    now[0] = DEDUPE_TTL_SECONDS - 0.01
    assert dedupe.seen("What is authentication?") is True
    now[0] = DEDUPE_TTL_SECONDS
    assert dedupe.seen("What is authentication?") is False
    assert dedupe.seen("How do you test code?") is False


def test_dedupe_capacity_evicts_oldest_bound():
    now = [0.0]
    dedupe = RecentFinalDedupe(clock=lambda: now[0])
    for index in range(DEDUPE_CAPACITY):
        assert dedupe.seen(f"question {index}") is False
    assert dedupe.seen("question 32") is False  # evicts the oldest entry at the cap
    assert dedupe.seen("question 1") is True
    assert len(dedupe._seen) <= DEDUPE_CAPACITY
    assert dedupe.seen("question 0") is False


# --- Ephemeral tokens --------------------------------------------------------


def test_token_single_use_and_new_token_revokes_old_session_token():
    manager = LiveTokenManager(clock=lambda: 0.0)
    first = manager.issue("session-1", "en-US")
    second = manager.issue("session-1", "es-MX")
    assert manager.consume(first) is None
    grant = manager.consume(second)
    assert grant is not None
    assert (grant.session_id, grant.language) == ("session-1", "es-MX")
    assert manager.consume(second) is None


def test_token_expiry_and_capacity_are_bounded():
    now = [0.0]
    manager = LiveTokenManager(clock=lambda: now[0], capacity=3)
    expired = manager.issue("expired", "en-US")
    now[0] = 30.0
    assert manager.consume(expired) is None

    now[0] = 31.0
    tokens = [manager.issue(f"session-{index}", "en-US") for index in range(4)]
    assert manager.consume(tokens[0]) is None  # evicted at the capacity bound
    assert manager.consume(tokens[-1]) is not None


def test_token_is_not_persisted_to_sqlite(client, tmp_path):
    _session_id, token = create_live(client)
    database = tmp_path / "copilot.sqlite3"
    assert database.is_file()
    assert token.encode() not in database.read_bytes()


# --- HTTP validation and status ---------------------------------------------


def test_live_status_reports_availability_without_paths(client):
    response = client.get("/live/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "vosk"
    assert set(payload["languages"]) == {"en-US", "es-MX"}
    assert "detail" in payload and "runtime_installed" in payload
    text = response.text
    assert "local-data" not in text
    assert "C:" not in text and "\\\\" not in text


def test_status_explains_missing_models_without_paths(tmp_path, monkeypatch):
    cache = VoskModelCache(models_root=tmp_path / "missing-models")
    result = cache.availability()
    assert result["available"] is False
    assert all(not entry["available"] for entry in result["languages"].values())
    assert "unavailable" in result["detail"]
    assert "missing-models" not in json.dumps(result)
    with pytest.raises(SpeechUnavailable):
        cache.create_recognizer("en-US")

    monkeypatch.setattr("app.live._vosk_installed", lambda: False)
    assert cache.availability()["runtime_installed"] is False
    assert cache.availability()["available"] is False


def test_live_token_requires_live_unfinished_session_and_consent(client):
    practice = client.post("/sessions", json={"mode": "practice"}).json()["id"]
    assert client.post(
        f"/sessions/{practice}/live-token", json={"language": "en-US", "consent": True}
    ).status_code == 400

    live, _token = create_live(client)
    assert client.post(
        f"/sessions/{live}/live-token", json={"language": "en-US"}
    ).status_code == 422
    assert client.post(
        f"/sessions/{live}/live-token", json={"language": "en-US", "consent": False}
    ).status_code == 422
    assert client.post(
        f"/sessions/{live}/live-token", json={"language": "fr-FR", "consent": True}
    ).status_code == 422

    assert client.post(f"/sessions/{live}/finish").status_code == 200
    assert client.post(
        f"/sessions/{live}/live-token", json={"language": "en-US", "consent": True}
    ).status_code == 409


# --- WebSocket handshake and transport --------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": "null"},
        {"origin": "http://evil.example"},
        {"origin": "https://localhost:5173"},
        {"origin": "http://localhost:5174"},
    ],
)
def test_ws_rejects_missing_null_and_external_origins(client, headers):
    _session_id, token = create_live(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/live/transcribe", headers=headers) as websocket:
            websocket.send_json({"type": "start", "token": token})


def test_ws_rejects_untrusted_host_even_with_allowed_origin(client):
    _session_id, token = create_live(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/live/transcribe",
            headers={"origin": "http://localhost:5173", "host": "evil.example"},
        ) as websocket:
            websocket.send_json({"type": "start", "token": token})


def test_ws_accepts_both_development_origins(tmp_path):
    # This is an origin/transport test, not a Vosk installation check.
    # Use a deterministic fake recognizer so it runs on fresh developer machines.
    app, _fake = fake_client(tmp_path)
    with TestClient(app) as client:
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            _session_id, token = create_live(client)
            with client.websocket_connect("/live/transcribe", headers={"origin": origin}) as websocket:
                ready = start(websocket, token)
                assert ready["type"] == "ready"


def test_ws_rejects_bad_handshake_shapes(client):
    _session_id, token = create_live(client)
    cases = [
        ({"bytes": b"\x00\x00"}, "handshake_required"),
        ({"text": "not json"}, "invalid_handshake"),
        ({"text": json.dumps({"type": "start"})}, "invalid_token"),
        ({"text": json.dumps({"type": "start", "token": "bogus"})}, "invalid_token"),
        ({"text": "x" * 2049}, "handshake_too_large"),
    ]
    for message, expected in cases:
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            if "bytes" in message:
                websocket.send_bytes(message["bytes"])
            else:
                websocket.send_text(message["text"])
            event = websocket.receive_json()
            assert event["type"] == "error", expected
            assert event["code"] == expected
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_ws_token_cannot_be_replayed(tmp_path):
    app, _fake = fake_client(tmp_path)
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            websocket.send_json({"type": "start", "token": token})
            event = websocket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "invalid_token"


def test_ws_token_expiry_is_enforced(tmp_path):
    now = [0.0]
    app = create_app(tmp_path)
    app.state.live = LiveRuntime(clock=lambda: now[0])
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        now[0] = 30.0
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            websocket.send_json({"type": "start", "token": token})
            event = websocket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "invalid_token"


def test_ws_rejects_finished_and_non_live_sessions_after_token_issue(tmp_path):
    app, _fake = fake_client(tmp_path)
    with TestClient(app) as client:
        session_id, token = create_live(client)
        assert client.post(f"/sessions/{session_id}/finish").status_code == 200
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            websocket.send_json({"type": "start", "token": token})
            event = websocket.receive_json()
            assert event["code"] == "session_finished"

        practice = client.post("/sessions", json={"mode": "practice"}).json()["id"]
        # Issue through the internal manager to prove the WS re-checks the session mode.
        token = app.state.live.tokens.issue(practice, "en-US")
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            websocket.send_json({"type": "start", "token": token})
            event = websocket.receive_json()
            assert event["code"] == "not_live"


def test_ws_enforces_one_active_connection_and_releases_cleanly(tmp_path):
    app, _fake = fake_client(tmp_path)
    with TestClient(app) as client:
        first_session, first_token = create_live(client)
        _second_session, second_token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as first:
            assert start(first, first_token)["type"] == "ready"
            with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as second:
                second.send_json({"type": "start", "token": second_token})
                event = second.receive_json()
                assert event["type"] == "error"
                assert event["code"] == "busy"
                with pytest.raises(WebSocketDisconnect):
                    second.receive_json()

        # Closing the first connection releases the process-wide slot.
        _third_session, third_token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as third:
            assert start(third, third_token)["type"] == "ready"


@pytest.mark.parametrize("frame", [b"\x00", b"\x00" * 64002])
def test_ws_rejects_malformed_audio_frames(tmp_path, frame):
    app, fake = fake_client(tmp_path)
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(frame)
            event = websocket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "invalid_audio"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()
        assert fake.feed_results == []


def test_ws_contextual_question_is_detected_without_exact_document_match(tmp_path):
    final = (
        "sure thanks again for coming so here's the question when designing a rest a p i "
        "how do you choose between get post put and patch"
    )
    app, _fake = fake_client(tmp_path, [FeedResult(final=final)])
    with TestClient(app) as client:
        _, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            suggestion = websocket.receive_json()
            assert suggestion["type"] == "suggestion"
            assert suggestion["question"] == (
                "when designing a rest a p i how do you choose between get post put and patch"
            )
            assert suggestion["status"] == "no_evidence"
            assert suggestion["answer"] is None
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_ws_early_exact_question_with_long_spoken_introduction(tmp_path):
    partial = "sure thanks for coming so here's the question what is authentication"
    app, _fake = fake_client(
        tmp_path,
        [FeedResult(partial=partial) for _ in range(PARTIAL_STABILITY_FRAMES)]
        + [FeedResult(final=partial)],
    )
    add_qa(app.state.store, "sample.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            for _ in range(PARTIAL_STABILITY_FRAMES):
                websocket.send_bytes(pcm_frame())
                assert websocket.receive_json()["type"] == "partial"
            early = websocket.receive_json()
            assert early["type"] == "suggestion"
            assert early["from_partial"] is True
            assert early["question"] == "what is authentication"
            assert early["answer"] == "Authentication verifies identity."
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_stable_partial_requires_identical_question_hypotheses():
    tracker = StablePartialQuestion()
    assert tracker.observe("his authentication") is None
    assert tracker.observe("what is authentic") is None
    for _ in range(PARTIAL_STABILITY_FRAMES - 1):
        assert tracker.observe("what is authentication") is None
    assert tracker.observe("what is authentication") == "what is authentication"
    assert tracker.observe("what is authentication") is None  # Single lookup per candidate.
    tracker.reset()
    assert tracker.observe("what is authentication") is None


def test_ws_stable_partial_exact_answer_before_final_and_no_duplicate(tmp_path):
    question = "what is authentication"
    app, _fake = fake_client(
        tmp_path,
        [FeedResult(partial=question) for _ in range(PARTIAL_STABILITY_FRAMES)]
        + [FeedResult(final=question, last_word_end_seconds=2.09)],
    )
    add_qa(app.state.store, "sample.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            for _ in range(PARTIAL_STABILITY_FRAMES):
                websocket.send_bytes(pcm_frame())
                assert websocket.receive_json()["type"] == "partial"
            early = websocket.receive_json()
            assert early["type"] == "suggestion"
            assert early["from_partial"] is True
            assert early["last_word_end_seconds"] is None
            assert early["answer"] == "Authentication verifies identity."
            assert early["source"]["document_name"] == "sample.md"
            websocket.send_bytes(pcm_frame())
            final = websocket.receive_json()
            assert final["type"] == "final"
            assert final["last_word_end_seconds"] == 2.09
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()  # Final must not repeat the early answer.


def test_ws_stable_partial_unknown_question_never_emits_early_suggestion(tmp_path):
    question = "what is not in my documents"
    app, _fake = fake_client(
        tmp_path,
        [FeedResult(partial=question) for _ in range(PARTIAL_STABILITY_FRAMES)]
        + [FeedResult(final=question)],
    )
    store = CountingStore(app.state.store)
    app.state.store = store
    add_qa(store, "sample.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            for _ in range(PARTIAL_STABILITY_FRAMES):
                websocket.send_bytes(pcm_frame())
                assert websocket.receive_json()["type"] == "partial"
            # Receiving the fourth partial can precede its asynchronous lookup.
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            final_suggestion = websocket.receive_json()
            assert final_suggestion["type"] == "suggestion"
            assert final_suggestion["status"] == "no_evidence"
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()
    assert store.exact_calls == 2  # Stable partial once, final once.


def test_partial_transcript_never_triggers_retrieval(tmp_path):
    app, _fake = fake_client(tmp_path, [FeedResult(partial="what is authent")])
    store = CountingStore(app.state.store)
    app.state.store = store
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            partial = websocket.receive_json()
            assert partial == {"type": "partial", "text": "what is authent", "language": "en-US"}
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()
    assert store.exact_calls == 0


def test_final_question_returns_exact_source(tmp_path):
    app, _fake = fake_client(
        tmp_path,
        [FeedResult(final="What is authentication?", last_word_end_seconds=2.09)],
    )
    add_qa(app.state.store, "live-en.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            final = websocket.receive_json()
            assert final == {
                "type": "final",
                "text": "What is authentication?",
                "language": "en-US",
                "last_word_end_seconds": 2.09,
            }
            suggestion = websocket.receive_json()
            assert suggestion["type"] == "suggestion"
            assert suggestion["status"] == "found"
            assert suggestion["answer"] == "Authentication verifies identity."
            assert suggestion["match_type"] == "exact_qa"
            assert suggestion["source"]["document_name"] == "live-en.md"
            assert suggestion["source"]["location"] == "Línea 1"
            assert isinstance(suggestion["retrieval_ms"], float)
            assert suggestion.get("from_partial", False) is False
            assert suggestion["last_word_end_seconds"] == final["last_word_end_seconds"]
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_ws_spoken_intro_finds_exact_answer_early_and_dedupes_repetition(tmp_path):
    # These are the real forms observed before the clean standalone question.
    app, _fake = fake_client(
        tmp_path,
        [
            FeedResult(final="ah got it the question is what is authentication"),
            FeedResult(final="sure what is authentication"),
        ],
    )
    add_qa(app.state.store, "live-en.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            suggestion = websocket.receive_json()
            assert suggestion["question"] == "what is authentication"
            assert suggestion["status"] == "found"
            assert suggestion["answer"] == "Authentication verifies identity."
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()  # No duplicate suggestion.


@pytest.mark.parametrize(
    ("language", "final", "questions"),
    [
        ("en-US", "thanks so what is authentication and what is authorization and what is terraform",
         ["what is authentication", "what is authorization", "what is terraform"]),
        ("es-MX", "gracias uno qué es la autenticación dos qué es la autorización tres qué es terraform",
         ["qué es la autenticación", "qué es la autorización", "qué es terraform"]),
    ],
)
def test_ws_marked_final_preserves_transcript_and_orders_source_backed_suggestions(tmp_path, language, final, questions):
    app, _ = fake_client(tmp_path, [FeedResult(final=final)])
    add_qa(app.state.store, "identity.md", questions[0], "Synthetic identity answer.")
    add_qa(app.state.store, "permissions.md", questions[1], "Synthetic permissions answer.")
    with TestClient(app) as client:
        _, token = create_live(client, language)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as ws:
            assert start(ws, token)["type"] == "ready"
            ws.send_bytes(pcm_frame())
            transcript = ws.receive_json()
            assert transcript["type"] == "final"
            assert transcript["text"] == final
            assert transcript["language"] == language
            suggestions = [ws.receive_json() for _ in questions]
            assert [item["question"] for item in suggestions] == questions
            assert all(item["type"] == "suggestion" for item in suggestions)
            assert [item["match_type"] for item in suggestions] == ["exact_qa", "exact_qa", None]
            assert [item["source"]["document_name"] for item in suggestions[:2]] == ["identity.md", "permissions.md"]
            assert suggestions[0]["answer"] == "Synthetic identity answer."
            assert suggestions[1]["answer"] == "Synthetic permissions answer."
            assert suggestions[2]["status"] == "no_evidence"
            assert suggestions[2]["answer"] is None
            assert suggestions[2]["source"] is None
            ws.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_final_unknown_question_returns_no_evidence(tmp_path):
    app, _fake = fake_client(tmp_path, [FeedResult(final="What is Terraform?")])
    add_qa(app.state.store, "live-en.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            suggestion = websocket.receive_json()
            assert suggestion["status"] == "no_evidence"
            assert suggestion["answer"] is None and suggestion["source"] is None
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_final_statement_does_not_trigger_suggestion(tmp_path):
    app, _fake = fake_client(tmp_path, [FeedResult(final="I worked at Acme for five years.")])
    store = CountingStore(app.state.store)
    app.state.store = store
    add_qa(store, "live-en.md", "What is authentication?", "Authentication verifies identity.")
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            websocket.send_text("stop")
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()
    assert store.exact_calls == 0


def test_repeated_final_is_deduped_per_connection(tmp_path):
    question = "What is authentication?"
    app, _fake = fake_client(tmp_path, [FeedResult(final=question), FeedResult(final=question)])
    add_qa(app.state.store, "live-en.md", question, "Authentication verifies identity.")
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            assert websocket.receive_json()["type"] == "suggestion"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            websocket.send_text("stop")
            # No second suggestion is queued before the close.
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_stop_control_flushes_final_and_unsupported_text_is_rejected(tmp_path):
    app, _fake = fake_client(
        tmp_path,
        finish_result=FeedResult(final="How do you test code?", last_word_end_seconds=1.5),
    )
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_text(json.dumps({"type": "stop"}))
            assert websocket.receive_json()["type"] == "final"
            assert websocket.receive_json()["type"] == "suggestion"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()

        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_text("hello")
            event = websocket.receive_json()
            assert event["code"] == "unsupported_control"


def test_idle_and_session_timeouts_close_with_static_errors(tmp_path):
    for attribute, expected in (
        ("idle_timeout_seconds", "idle_timeout"),
        ("session_limit_seconds", "session_limit"),
    ):
        app, _fake = fake_client(tmp_path)
        setattr(app.state.live, attribute, 0.05)
        with TestClient(app) as client:
            _session_id, token = create_live(client)
            with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
                assert start(websocket, token)["type"] == "ready"
                event = websocket.receive_json()
                assert event["code"] == expected
                with pytest.raises(WebSocketDisconnect):
                    websocket.receive_json()


def test_ws_rejects_oversize_text_control(tmp_path):
    app, _fake = fake_client(tmp_path)
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_text("x" * (MAX_CONTROL_CHARS + 1))
            event = websocket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "control_too_large"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


@pytest.mark.parametrize("field", ["partial", "final"])
def test_ws_rejects_oversize_transcript(tmp_path, field):
    result = FeedResult(**{field: "x" * (MAX_TRANSCRIPT_CHARS + 1)})
    app, _fake = fake_client(tmp_path, [result])
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            event = websocket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "transcript_too_large"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_final_emits_at_most_bounded_question_candidates(tmp_path):
    final_text = " ".join(
        f"What is question {index}?" for index in range(MAX_QUESTION_CANDIDATES + 4)
    )
    app, _fake = fake_client(tmp_path, [FeedResult(final=final_text)])
    with TestClient(app) as client:
        _session_id, token = create_live(client)
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            assert start(websocket, token)["type"] == "ready"
            websocket.send_bytes(pcm_frame())
            assert websocket.receive_json()["type"] == "final"
            suggestions = [websocket.receive_json() for _ in range(MAX_QUESTION_CANDIDATES)]
            assert all(event["type"] == "suggestion" for event in suggestions)
            websocket.send_text("stop")
            # A ninth suggestion would be queued before the close and fail here.
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


# --- Real local Vosk integration (synthetic WAV, no network) ----------------


def _vosk_ready() -> bool:
    cache = VoskModelCache()
    return cache.availability()["languages"]["en-US"]["available"] and cache.availability()["languages"]["es-MX"]["available"]


def _wav_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16000
        return audio.readframes(audio.getnframes()), audio.getnframes() // 16


@pytest.mark.skipif(not _vosk_ready(), reason="Optional Vosk runtime or local EN/ES models are absent")
@pytest.mark.parametrize(
    "language,filename,question,answer,document",
    [
        ("en-US", "en.wav", "What is authentication?", "Authentication verifies identity.", "live-en.md"),
        (
            "es-MX",
            "es.wav",
            "Como resuelves un conflicto en el equipo?",
            "Escucho ambas partes y busco un acuerdo.",
            "live-es.md",
        ),
    ],
)
def test_real_vosk_pipeline_partial_final_source_and_no_audio_persistence(
    tmp_path, language, filename, question, answer, document
):
    app = create_app(tmp_path)
    session_id = app.state.store.create_session("live")["id"]
    add_qa(app.state.store, document, question, answer)
    pcm, _seconds = _wav_pcm(WAV_DIR / filename)
    token = app.state.live.tokens.issue(session_id, language)

    events = []
    with TestClient(app) as client:
        with client.websocket_connect("/live/transcribe", headers=ALLOWED_HEADERS) as websocket:
            ready = start(websocket, token)
            assert ready["type"] == "ready"
            assert ready["language"] == language
            for offset in range(0, len(pcm), 4000):
                websocket.send_bytes(pcm[offset:offset + 4000])
            # One second of silence flushes Vosk's endpointing, then stop flushes any remainder.
            websocket.send_bytes(b"\x00\x00" * 16000)
            websocket.send_text("stop")
            try:
                while True:
                    events.append(websocket.receive_json())
            except WebSocketDisconnect:
                pass

    partials = [event["text"] for event in events if event["type"] == "partial"]
    finals = [event for event in events if event["type"] == "final"]
    suggestions = [event for event in events if event["type"] == "suggestion"]
    assert partials and any(text.strip() for text in partials), events
    assert finals and all(event["text"].strip() for event in finals), events
    assert not [event for event in events if event["type"] == "error"], events
    assert all(event["language"] == language for event in finals)
    # Word timing belongs to finalized speech, including when an early exact
    # suggestion already consumed the dedupe slot and no final suggestion follows.
    for final in finals:
        assert final["last_word_end_seconds"] is not None
        assert 0 < final["last_word_end_seconds"] <= len(pcm) / 32000 + 1
    matching_finals = [
        (index, event) for index, event in enumerate(events)
        if event["type"] == "final" and normalize(event["text"]) == normalize(question)
    ]
    assert matching_finals, events
    assert len(suggestions) == 1, events
    assert suggestions[-1]["status"] == "found", suggestions
    assert suggestions[-1]["answer"] == answer
    assert suggestions[-1]["source"]["document_name"] == document
    assert suggestions[-1]["match_type"] == "exact_qa"
    assert suggestions[-1]["retrieval_ms"] >= 0
    suggestion = suggestions[0]
    assert suggestion["language"] == language
    assert normalize(suggestion["question"]) == normalize(question)
    suggestion_index = events.index(suggestion)
    if suggestion.get("from_partial", False):
        assert suggestion["from_partial"] is True
        assert suggestion["last_word_end_seconds"] is None
        assert suggestion_index < matching_finals[0][0]
        assert sum(event["type"] == "partial" for event in events[:suggestion_index]) >= PARTIAL_STABILITY_FRAMES
    else:
        assert suggestion["last_word_end_seconds"] is not None
        assert suggestion["last_word_end_seconds"] > 0
        assert any(
            index < suggestion_index
            and final["last_word_end_seconds"] == suggestion["last_word_end_seconds"]
            for index, final in matching_finals
        )

    # No raw audio or transcript files were written next to the SQLite store.
    audio_suffixes = {".wav", ".pcm", ".raw", ".webm", ".ogg"}
    assert not [path for path in tmp_path.rglob("*") if path.suffix.casefold() in audio_suffixes]
    with closing(sqlite3.connect(tmp_path / "copilot.sqlite3")) as database:
        session_columns = {row[1] for row in database.execute("PRAGMA table_info(sessions)")}
        assert not {"audio", "transcript", "pcm"} & session_columns


@pytest.mark.parametrize(
    "spoken_final",
    [
        "Could you explain authentication?",
        "thanks so Could you explain authentication",
        "thanks next question Could you explain authentication",
    ],
)
def test_ws_final_returns_labeled_semantic_candidate_only_after_index(tmp_path, spoken_final):
    """Full WebSocket routing uses semantic search on finals, with attribution."""
    from app.semantic import SemanticIndex

    class Embedding:
        def embed(self, texts):
            for text in texts:
                if 'authentication' in text.lower():
                    yield [1.0, 0.0]
                else:
                    yield [0.0, 1.0]

    app, _ = fake_client(
        tmp_path,
        feed_results=[FeedResult(final=spoken_final)],
    )
    add_qa(app.state.store, 'auth.md', 'What is authentication?', 'Verifies identity.')
    app.state.semantic = SemanticIndex(app.state.store, embedder=Embedding())
    app.state.semantic.index()
    with TestClient(app) as client:
        _, token = create_live(client)
        with client.websocket_connect('/live/transcribe', headers=ALLOWED_HEADERS) as ws:
            assert start(ws, token)['type'] == 'ready'
            ws.send_bytes(pcm_frame())
            assert ws.receive_json()['type'] == 'final'
            candidate = ws.receive_json()
            assert candidate['type'] == 'suggestion'
            assert candidate['status'] == 'found'
            assert candidate['match_type'] == 'semantic_qa'
            assert candidate['question'] == 'Could you explain authentication'
            assert candidate['matched_question'] == 'What is authentication?'
            assert candidate['answer'] == 'Verifies identity.'
            assert candidate['source']['document_name'] == 'auth.md'
            ws.send_text('stop')
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
