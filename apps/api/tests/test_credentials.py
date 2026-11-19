"""Dummy-only credential precedence, Windows persistence, exclusion and safe helper results."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from app.infrastructure import deepgram_credentials_helper as helper
from app.infrastructure.windows_credentials import (KEY_ENV, CredentialBusy, CredentialError,
    CredentialGate, WindowsCredentialStore, resolve_key)
from app.infrastructure.deepgram import DeepgramProvider


class Store:
    def __init__(self, key=None):
        self.key = key
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.key

    def write(self, key):
        self.key = key

    def delete(self):
        self.key = None


@pytest.mark.parametrize("invalid", ["", " ", "a\nb", "a\rb", "a\tb", "a" * 257])
def test_invalid_environment_never_falls_back(invalid):
    store = Store("fictitious-stored-key")
    with pytest.raises(CredentialError, match="invalid_environment"):
        resolve_key({KEY_ENV: invalid}, store)
    assert store.reads == 0


def test_environment_precedence_and_safe_availability(monkeypatch):
    monkeypatch.setattr("app.infrastructure.deepgram._websockets_installed", lambda: True)
    store = Store("fictitious-stored-key")
    provider = DeepgramProvider({KEY_ENV: "fictitious-environment-key"}, credential_store=store)
    status = provider.availability()
    assert status["configured"] and status["credential_source"] == "environment"
    assert store.reads == 0 and "fictitious" not in json.dumps(status)
    status = DeepgramProvider({KEY_ENV: "bad\nvalue"}, credential_store=store).availability()
    assert not status["available"] and status["configuration_error"] == "invalid_environment"


@pytest.mark.skipif(os.name != "nt", reason="Windows credential resolution")
def test_new_sessions_reread_store_without_replacing_existing_session(monkeypatch):
    import websockets.asyncio.client as client
    monkeypatch.setattr("app.infrastructure.deepgram._websockets_installed", lambda: True)
    authorizations = []
    class Connection:
        async def close(self):
            pass
    async def connect(_url, **kwargs):
        authorizations.append(kwargs["additional_headers"]["Authorization"])
        return Connection()
    monkeypatch.setattr(client, "connect", connect)
    store = Store("fictitious-first")
    provider = DeepgramProvider({}, credential_store=store)
    async def run():
        first = await provider.open("en-US")
        store.key = "fictitious-second"
        second = await provider.open("en-US")
        assert first is not second
        await first.close()
        await second.close()
    asyncio.run(run())
    assert authorizations == ["Token fictitious-first", "Token fictitious-second"]


@pytest.mark.skipif(os.name != "nt", reason="Real Windows APIs, isolated dummy target")
def test_windows_store_restart_persistence_and_cleanup():
    target = "InterviewCopilot-CLOUD001-Test-" + str(uuid.uuid4())
    store = WindowsCredentialStore(target)
    assert store.read() is None  # Never overwrite an existing target, even with a unique name.
    try:
        store.write("fictitious-first")
        assert store.read() == "fictitious-first"
        store.write("fictitious-second")
        code = """import sys;sys.path.insert(0,sys.argv[1])
from app.infrastructure.windows_credentials import WindowsCredentialStore
assert sys.argv[2].startswith('InterviewCopilot-CLOUD001-Test-')
assert WindowsCredentialStore(sys.argv[2]).read() == 'fictitious-second'
print('status-only-ok')
"""
        result = subprocess.run([sys.executable, "-I", "-c", code, str(Path.cwd()), target], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and result.stdout.strip() == "status-only-ok" and not result.stderr
    finally:
        store.delete()
    assert store.read() is None
    store.delete()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows shared/exclusive handles")
def test_capture_and_mutation_gate_conflicts_and_crash_release(tmp_path):
    path = tmp_path / "guard.lock"
    with CredentialGate(exclusive=False, path=path), CredentialGate(exclusive=False, path=path):
        with pytest.raises(CredentialBusy):
            CredentialGate(exclusive=True, path=path)
    with CredentialGate(exclusive=True, path=path):
        with pytest.raises(CredentialBusy):
            CredentialGate(exclusive=False, path=path)
        with pytest.raises(CredentialBusy):
            CredentialGate(exclusive=True, path=path)
    code = """import sys;sys.path.insert(0,sys.argv[1])
from pathlib import Path
from app.infrastructure.windows_credentials import CredentialGate
gate=CredentialGate(exclusive=False,path=Path(sys.argv[2]))
print('leased',flush=True)
sys.stdin.buffer.read(1)
"""
    child = subprocess.Popen([sys._base_executable, "-I", "-c", code, str(Path.cwd()), str(path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "leased"
        with pytest.raises(CredentialBusy):
            CredentialGate(exclusive=True, path=path)
    finally:
        child.kill()
        child.wait(timeout=5)
    with CredentialGate(exclusive=True, path=path):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows-only helper")
def test_helper_cancellation_conflicts_failures_and_status_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(helper, "_watch_parent", lambda *_: None)
    monkeypatch.setattr(helper, "_watch_cancel", lambda: None)
    store = Store("fictitious-preserved")
    monkeypatch.setattr(helper, "prompt", lambda *_: None)
    def invoke(action):
        helper.run([action, "1", "en", str(os.getpid())], store=store, gate_path=tmp_path / "helper.lock")
        return json.loads(capsys.readouterr().out)
    assert invoke("replace") == {"result":"cancelled", "stored":True}
    assert store.key == "fictitious-preserved"
    assert invoke("configure")["result"] == "conflict"
    with CredentialGate(exclusive=False, path=tmp_path / "helper.lock"):
        assert invoke("delete") == {"result":"busy", "stored":None}
    monkeypatch.setattr(helper, "prompt", lambda *_: "fictitious-replacement")
    assert invoke("replace") == {"result":"configured", "stored":True}
    assert invoke("status") == {"result":"status", "stored":True}
    def failure(*_):
        raise RuntimeError("fictitious-secret-must-not-escape")
    monkeypatch.setattr(store, "write", failure)
    assert invoke("replace") == {"result":"error", "stored":None}
    assert invoke("delete") == {"result":"deleted", "stored":False}
    assert store.key is None


def test_backend_rejects_mutation_conflict_without_opening_provider(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import create_app
    def blocked(**_):
        raise CredentialBusy("busy")
    monkeypatch.setattr("app.live.CredentialGate", blocked)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect('/live/transcribe', headers={'origin':'http://localhost:5173'}) as ws:
            packet = ws.receive_json()
            assert packet['code'] == 'credentials_busy'
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert app.state.live.acquire_connection()
        app.state.live.release_connection()


@pytest.mark.skipif(os.name != "nt", reason="Windows backend capture lease")
def test_backend_holds_shared_guard_through_session_and_releases_after_stop(tmp_path):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import create_app
    from app.application.stt import FeedResult
    from app.infrastructure.windows_credentials import credential_gate_path
    class Session:
        async def feed(self, _):
            return FeedResult()
        async def finish(self):
            return FeedResult()
        async def close(self):
            pass
    class Provider:
        def availability(self):
            return {"provider":"vosk", "available":True, "languages":{"en-US":{"available":True}}}
        async def open(self, _):
            return Session()
    app = create_app(tmp_path)
    app.state.live.models = Provider()
    with TestClient(app) as client:
        sid = client.post('/sessions', json={'mode':'live'}).json()['id']
        token = client.post(f'/sessions/{sid}/live-token', json={'consent':True,'language':'en-US'}).json()['token']
        with client.websocket_connect('/live/transcribe', headers={'origin':'http://localhost:5173'}) as ws:
            ws.send_json({'type':'start','token':token})
            assert ws.receive_json()['type'] == 'ready'
            with pytest.raises(CredentialBusy):
                CredentialGate(exclusive=True, path=credential_gate_path())
            # A native capture-window lease may coexist with its backend session.
            with CredentialGate(exclusive=False, path=credential_gate_path()):
                pass
            ws.send_text('stop')
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    with CredentialGate(exclusive=True, path=credential_gate_path()):
        pass
