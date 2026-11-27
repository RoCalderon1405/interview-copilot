"""Provider-separated credential namespace, guard and key validation; dummy only."""
from __future__ import annotations

import json
import os

import pytest

from app.application.generation import GenerationError
from app.infrastructure import deepgram_credentials_helper as helper
from app.infrastructure.deepseek import DeepSeekProvider
from app.infrastructure.windows_credentials import (CREDENTIAL_SPECS, DEEPSEEK_KEY_ENV,
    DEEPSEEK_TARGET, CredentialError, CredentialGate, credential_spec, resolve_provider_key,
    valid_deepseek_key)


class Store:
    """Injected target with observable access, never a real Credential Manager entry."""

    def __init__(self, key=None):
        self.key = key
        self.reads = 0
        self.writes = 0

    def read(self):
        self.reads += 1
        return self.key

    def write(self, key):
        self.writes += 1
        self.key = key

    def delete(self):
        self.key = None


@pytest.mark.parametrize("value,valid", [
    ("a" * 16, True),
    ("sk-test-0123456789abcdef", True),
    ("A.b_c-0123456789", True),
    ("a" * 200, True),
    ("a" * 15, False),
    ("a" * 201, False),
    ("has space 12345678", False),
    ("ñ" * 16, False),
    ("a" * 16 + "\n", False),
])
def test_deepseek_key_validation_matches_the_adapter(value, valid):
    assert valid_deepseek_key(value) is valid
    if valid:
        DeepSeekProvider("deepseek-flash", value)
    else:
        with pytest.raises(GenerationError) as failure:
            DeepSeekProvider("deepseek-flash", value)
        assert failure.value.code == "not_configured"


def test_provider_resolution_never_cross_reads_or_falls_back():
    deepseek = Store("sk-test-0123456789abcdef")
    spec = credential_spec("deepseek")
    assert resolve_provider_key(spec, {"COPILOT_DEEPGRAM_API_KEY": "fictitious-deepgram"}, deepseek) == (
        "sk-test-0123456789abcdef", "windows")
    assert resolve_provider_key(spec, {DEEPSEEK_KEY_ENV: "sk-test-env-0123456789"}, deepseek) == (
        "sk-test-env-0123456789", "environment")
    reads = deepseek.reads
    with pytest.raises(CredentialError, match="invalid_environment"):
        resolve_provider_key(spec, {DEEPSEEK_KEY_ENV: "short"}, deepseek)
    assert deepseek.reads == reads
    with pytest.raises(CredentialError, match="invalid_stored_credential"):
        resolve_provider_key(spec, {}, Store("short"))
    with pytest.raises(CredentialError, match="unknown_provider"):
        credential_spec("openai")
    assert set(CREDENTIAL_SPECS) == {"deepgram", "deepseek"}


def _invoke(arguments, store, capsys, tmp_path):
    helper.run(arguments, store=store, gate_path=tmp_path / "provider.lock",
               mutation_path=tmp_path / "mutation.lock")
    output = capsys.readouterr().out
    assert output.endswith("\n") and output.count("\n") == 1
    value = json.loads(output)
    assert set(value) == {"result", "stored"}
    return value, output


def test_helper_status_uses_only_the_deepseek_target(monkeypatch, tmp_path, capsys):
    selected = {}
    class FakeStore:
        def __init__(self, target, *, validate):
            selected["target"] = target
            selected["validate"] = validate
        def read(self):
            return None
    monkeypatch.setattr(helper, "WindowsCredentialStore", FakeStore)
    _invoke(["status", "1", "en", str(os.getpid()), "deepseek"], None, capsys, tmp_path)
    assert selected["target"] == DEEPSEEK_TARGET
    assert selected["validate"] is valid_deepseek_key


def test_helper_selects_only_allowlisted_provider_and_returns_status_only(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(helper, "_watch_parent", lambda *_: None)
    monkeypatch.setattr(helper, "_watch_cancel", lambda: None)
    calls = []
    monkeypatch.setattr(helper, "prompt", lambda owner, language, provider: calls.append(
        (owner, language, provider)) or "sk-test-0123456789abcdef")
    store = Store()
    args = ["configure", "1", "es", str(os.getpid()), "deepseek"]
    value, output = _invoke(args, store, capsys, tmp_path)
    assert value == {"result": "configured", "stored": True}
    assert calls == [(1, "es", "deepseek")]
    assert "sk-test" not in output
    assert _invoke(["status", "1", "es", str(os.getpid()), "deepseek"], store, capsys, tmp_path)[0] == {
        "result": "status", "stored": True}
    assert _invoke(args, store, capsys, tmp_path)[0] == {"result": "conflict", "stored": True}
    monkeypatch.setattr(helper, "prompt", lambda *_: None)
    before = store.key
    assert _invoke(["replace", "1", "en", str(os.getpid()), "deepseek"], store, capsys, tmp_path)[0] == {
        "result": "cancelled", "stored": True}
    assert store.key == before
    monkeypatch.setattr(helper, "prompt", lambda *_: "short")
    assert _invoke(["replace", "1", "en", str(os.getpid()), "deepseek"],
                   store, capsys, tmp_path)[0] == {"result": "error", "stored": None}
    assert store.key == before
    for bad in (["status", "1", "en", str(os.getpid()), "openai"],
                ["lease", "1", "en", str(os.getpid()), "deepseek"],
                ["status", "1", "fr", str(os.getpid()), "deepseek"]):
        before_key = store.key
        assert _invoke(bad, store, capsys, tmp_path)[0] == {"result": "error", "stored": None}
        assert store.key == before_key


@pytest.mark.skipif(os.name != "nt", reason="Real Windows shared/exclusive handles")
def test_cross_provider_dialog_and_provider_specific_locks_conflict(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(helper, "_watch_parent", lambda *_: None)
    monkeypatch.setattr(helper, "_watch_cancel", lambda: None)
    monkeypatch.setattr(helper, "prompt", lambda *_: "sk-test-0123456789abcdef")
    store = Store()
    mutation = tmp_path / "mutation.lock"
    provider = tmp_path / "provider.lock"
    with CredentialGate(exclusive=True, path=mutation):
        assert _invoke(["configure", "1", "en", str(os.getpid()), "deepseek"],
                       store, capsys, tmp_path)[0] == {"result": "busy", "stored": None}
    with CredentialGate(exclusive=True, path=provider):
        assert _invoke(["configure", "1", "en", str(os.getpid()), "deepseek"],
                       store, capsys, tmp_path)[0] == {"result": "busy", "stored": None}
    assert store.writes == 0
