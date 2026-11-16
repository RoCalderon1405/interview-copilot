"""Generation contracts with fake providers and no local model execution."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.application.generation import GenerationError, GenerationService, system_instructions
from app.bootstrap import create_generation_service


class FakeProvider:
    name = "fake"
    model = "explicit-model"

    def __init__(self, output="A practical answer."):
        self.output = output
        self.calls = []

    async def generate(self, question, language):
        self.calls.append((question, language))
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


def test_provenance_and_only_question_language_reach_provider():
    provider = FakeProvider()
    result = asyncio.run(GenerationService(provider, enabled=True).generate("  Explain caching?  ", "en-US"))
    assert provider.calls == [("Explain caching?", "en-US")]
    assert asdict(result) == dict(answer="A practical answer.", provider="fake", model="explicit-model",
                                  kind="ai_generated", source=None)
    with pytest.raises(FrozenInstanceError):
        result.source = "invented"


@pytest.mark.parametrize("language,phrase", [("en-US", "B2 English"), ("es-MX", "español natural")])
def test_fixed_natural_answer_instruction_contract(language, phrase):
    prompt = system_instructions(language)
    for required in (phrase, "3-5 concise sentences", "natural, conversational and professional",
                     "short example", "unnecessary jargon", "employment history", "personal experience",
                     "Acknowledge uncertainty", "untrusted"):
        assert required in prompt
    assert "not verified facts" in prompt
    assert "external operations" in prompt


@pytest.mark.parametrize("settings", [{}, {"COPILOT_LLM_ENABLED": "false"}, {"COPILOT_LLM_ENABLED": "0"},
    {"COPILOT_OLLAMA_MODEL": "explicit", "COPILOT_LLM_TIMEOUT_SECONDS": "invalid"}])
def test_disabled_by_default(settings):
    with pytest.raises(GenerationError, match="disabled"):
        asyncio.run(create_generation_service(settings).generate("Question?", "en-US"))


@pytest.mark.parametrize("settings", [
    {"COPILOT_LLM_ENABLED": "yes"},
    {"COPILOT_LLM_ENABLED": "true"},
    *[{"COPILOT_LLM_ENABLED": "true", "COPILOT_OLLAMA_MODEL": "local",
       "COPILOT_LLM_TIMEOUT_SECONDS": value} for value in ("nan", "inf", "0", "-1", "61", "bad")],
])
def test_invalid_or_missing_configuration(settings):
    with pytest.raises(GenerationError) as error:
        asyncio.run(create_generation_service(settings).generate("Question?", "en-US"))
    assert error.value.code == "not_configured"


def test_composition_has_no_network_and_explicit_timeout(monkeypatch):
    import httpx

    def forbidden(*args, **kwargs):
        pytest.fail("Composition must not create a network client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    service = create_generation_service({"COPILOT_LLM_ENABLED": "1", "COPILOT_OLLAMA_MODEL": "local"})
    assert service._timeout_seconds == 8
    assert service._provider.model == "local"
    custom = create_generation_service({"COPILOT_LLM_ENABLED": "true", "COPILOT_OLLAMA_MODEL": "local",
                                        "COPILOT_LLM_TIMEOUT_SECONDS": "2.5"})
    assert custom._timeout_seconds == custom._provider._timeout_seconds == 2.5


@pytest.mark.parametrize("question,language", [(None, "en-US"), ("ab", "en-US"), ("   ", "en-US"),
    ("x" * 3001, "en-US"), ("Question?", "fr-FR"), ("Question?", None)])
def test_invalid_input_never_calls_provider(question, language):
    provider = FakeProvider()
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider, enabled=True).generate(question, language))
    assert error.value.code == "invalid_input"
    assert provider.calls == []


@pytest.mark.parametrize("output", [None, {}, 123, "", "  ", "x" * 2001])
def test_invalid_output_is_not_a_suggestion(output):
    provider = FakeProvider(output)
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider, enabled=True).generate("Question?", "es-MX"))
    assert error.value.code == "invalid_response"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("failure,code", [(RuntimeError("PRIVATE TEXT"), "provider_error"),
    (GenerationError("unavailable"), "unavailable"), (TimeoutError("PRIVATE TEXT"), "timeout")])
def test_errors_are_sanitized_without_retry(failure, code, caplog):
    provider = FakeProvider(failure)
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider, enabled=True).generate("PRIVATE QUESTION", "en-US"))
    assert error.value.code == code
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert len(provider.calls) == 1


def test_total_timeout_cancels_provider_once():
    class WaitingProvider(FakeProvider):
        cancelled = False

        async def generate(self, question, language):
            self.calls.append((question, language))
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    provider = WaitingProvider()
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider, enabled=True, timeout_seconds=0.01).generate("Question?", "en-US"))
    assert error.value.code == "timeout"
    assert provider.cancelled and len(provider.calls) == 1


def test_caller_cancellation_propagates():
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(GenerationService(FakeProvider(asyncio.CancelledError()), enabled=True)
                    .generate("Question?", "en-US"))


def test_disabled_service_never_calls_even_a_configured_provider():
    provider = FakeProvider()
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider).generate("Question?", "en-US"))
    assert error.value.code == "disabled"
    assert provider.calls == []


def test_inclusive_question_and_answer_limits():
    provider = FakeProvider("a" * 2000)
    result = asyncio.run(GenerationService(provider, enabled=True).generate("q" * 3000, "es-MX"))
    assert len(result.answer) == 2000
    assert provider.calls == [("q" * 3000, "es-MX")]


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), float("inf"), True, "8"])
def test_invalid_service_timeout(timeout):
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(FakeProvider(), enabled=True, timeout_seconds=timeout)
                    .generate("Question?", "en-US"))
    assert error.value.code == "not_configured"


@pytest.mark.parametrize("name,model", [(None, "local"), ("", "local"), ("fake", ""),
    ("fake", None), ("x" * 81, "local"), ("fake", "x" * 201)])
def test_invalid_provider_metadata_never_calls_provider(name, model):
    provider = FakeProvider()
    provider.name, provider.model = name, model
    with pytest.raises(GenerationError) as error:
        asyncio.run(GenerationService(provider, enabled=True).generate("Question?", "en-US"))
    assert error.value.code == "not_configured"
    assert provider.calls == []


def test_application_import_is_independent_of_http_and_infrastructure():
    script = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
class RejectAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('httpx', 'fastapi', 'sqlite3', 'app.live', 'app.store') or fullname.startswith('app.infrastructure'):
            raise AssertionError('Unexpected dependency: ' + fullname)
sys.meta_path.insert(0, RejectAdapters())
from app.application.generation import GenerationService
assert GenerationService is not None
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script,
                             str(Path(__file__).resolve().parents[1])],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_enabled_environment_composes_without_network_or_new_public_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_OLLAMA_MODEL", "local")
    monkeypatch.setenv("COPILOT_DATA_DIR", str(tmp_path))
    import httpx
    from app.main import create_app

    def forbidden(*args, **kwargs):
        pytest.fail("Composition must not create a network client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    app = create_app(tmp_path)
    assert app.state.generation.available
    assert not any('generat' in path or 'ollama' in path for path in app.openapi()['paths'])
