"""Optional local/cloud speech and generation composition, without startup I/O."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping

from .application.generation import DEFAULT_TIMEOUT_SECONDS, GenerationError, GenerationService
from .infrastructure.deepseek import DEEPSEEK_MODELS, DeepSeekProvider
from .infrastructure.ollama import OllamaProvider
from .application.stt import SpeechProvider
from .infrastructure.faster_whisper import FasterWhisperProvider
from .infrastructure.deepgram import DeepgramProvider
from .infrastructure.windows_credentials import (
    CREDENTIAL_SPECS,
    CredentialError,
    WindowsCredentialStore,
    resolve_provider_key,
)

_DEEPSEEK_SPEC = CREDENTIAL_SPECS["deepseek"]
CLOUD_LLM_ENV = "COPILOT_ALLOW_CLOUD_LLM"


def create_whisper_provider() -> SpeechProvider:
    """Compose optional local speech without loading, installing or downloading it."""
    return FasterWhisperProvider()


def create_deepgram_provider() -> DeepgramProvider:
    """Configure cloud STT only from the backend process environment."""
    return DeepgramProvider()


def windows_cloud_llm_supported() -> bool:
    """Cloud LLM selection is limited to the supported Windows development flow."""
    return os.name == "nt"


def cloud_llm_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Require an explicit backend opt-in; installation/startup never enables cloud.

    Only ``true`` or ``1`` (case-insensitive, surrounding whitespace ignored)
    enables the gate. Missing, false or unrecognized values stay off.
    """
    settings = os.environ if environ is None else environ
    return settings.get(CLOUD_LLM_ENV, "false").strip().casefold() in {"true", "1"}


def _generation_timeout(settings: Mapping[str, str]) -> float:
    """Read the existing bounded generation deadline without contacting a provider."""
    try:
        timeout = float(settings.get("COPILOT_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        raise GenerationError("not_configured") from None
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise GenerationError("not_configured")
    return timeout


def create_generation_service(environ: Mapping[str, str] | None = None) -> GenerationService:
    """Build a local service only when explicitly enabled; perform no network I/O."""
    settings = os.environ if environ is None else environ
    enabled = settings.get("COPILOT_LLM_ENABLED", "false").strip().casefold()
    if enabled in {"false", "0"}:
        return GenerationService()
    if enabled not in {"true", "1"}:
        raise GenerationError("not_configured")
    model = settings.get("COPILOT_OLLAMA_MODEL", "").strip()
    if not model:
        return GenerationService(enabled=True)
    timeout = _generation_timeout(settings)
    return GenerationService(
        OllamaProvider(model, timeout_seconds=timeout), enabled=True, timeout_seconds=timeout
    )


def deepseek_availability(
    environ: Mapping[str, str] | None = None,
    *,
    credential_store: WindowsCredentialStore | None = None,
    windows: bool | None = None,
) -> dict[str, object]:
    """Report local DeepSeek readiness without remote verification or secret values.

    The environment override keeps precedence and an invalid value never falls
    back to Windows Credential Manager. This helper only reads local process
    state and the user's credential store; it performs no network request.
    """
    settings = os.environ if environ is None else environ
    supported = os.name == "nt" if windows is None else windows
    gate_enabled = cloud_llm_enabled(settings)
    models = sorted(DEEPSEEK_MODELS)
    if not supported:
        return {
            "provider": "deepseek", "available": False, "configured": False,
            "credential_source": "none", "configuration_error": "windows_required",
            "gate_enabled": gate_enabled, "models": models,
            "detail": "DeepSeek selection is available only in the Windows development flow.",
        }
    store = credential_store or WindowsCredentialStore(
        _DEEPSEEK_SPEC.target, validate=_DEEPSEEK_SPEC.validate
    )
    error = None
    timeout_error = False
    key = None
    try:
        key, source = resolve_provider_key(_DEEPSEEK_SPEC, settings, store)
        configured = key is not None
    except CredentialError as failure:
        configured, source = False, "error"
        error = "invalid_environment" if str(failure) == "invalid_environment" else "credential_unavailable"
    finally:
        key = None
    if configured:
        try:
            _generation_timeout(settings)
        except GenerationError:
            timeout_error = True
            error = error or "invalid_generation_timeout"
    # The backend developer gate is independent of OS support and local key
    # presence. Off is reported as such, never as an unsupported operating system.
    if not gate_enabled:
        error = "cloud_llm_disabled"
    available = gate_enabled and configured and not timeout_error
    if not gate_enabled:
        detail = "Cloud LLM is disabled by the backend developer gate; no remote request is made."
    elif timeout_error:
        detail = "The local generation deadline is invalid; no remote request is performed."
    elif configured:
        detail = "DeepSeek is configured locally; remote authentication and billing are not verified."
    else:
        detail = "DeepSeek requires valid local configuration; no remote check is performed."
    return {
        "provider": "deepseek", "available": available, "configured": configured,
        "credential_source": source, "configuration_error": error,
        "gate_enabled": gate_enabled, "models": models, "detail": detail,
    }


def create_deepseek_generation_service(
    model: str,
    environ: Mapping[str, str] | None = None,
    *,
    credential_store: WindowsCredentialStore | None = None,
    windows: bool | None = None,
) -> GenerationService:
    """Snapshot one key-bound cloud service for a single Live connection.

    Missing, invalid or unsupported configuration raises ``not_configured``
    before any provider call. The caller keeps documentary retrieval available
    and must not substitute Ollama automatically.
    """
    settings = os.environ if environ is None else environ
    supported = os.name == "nt" if windows is None else windows
    if (not supported or not cloud_llm_enabled(settings)
            or not isinstance(model, str) or model not in DEEPSEEK_MODELS):
        raise GenerationError("not_configured")
    store = credential_store or WindowsCredentialStore(
        _DEEPSEEK_SPEC.target, validate=_DEEPSEEK_SPEC.validate
    )
    key = None
    try:
        key, _ = resolve_provider_key(_DEEPSEEK_SPEC, settings, store)
        if key is None:
            raise GenerationError("not_configured")
        timeout = _generation_timeout(settings)
        provider = DeepSeekProvider(model, key, timeout_seconds=timeout)
    except CredentialError:
        raise GenerationError("not_configured") from None
    finally:
        key = None
    return GenerationService(provider, enabled=True, timeout_seconds=timeout)
