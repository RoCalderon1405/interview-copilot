"""Optional local generation and speech composition, without startup downloads."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping

from .application.generation import DEFAULT_TIMEOUT_SECONDS, GenerationError, GenerationService
from .infrastructure.ollama import OllamaProvider
from .application.stt import SpeechProvider
from .infrastructure.faster_whisper import FasterWhisperProvider


def create_whisper_provider() -> SpeechProvider:
    """Compose optional local speech without loading, installing or downloading it."""
    return FasterWhisperProvider()


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
    try:
        timeout = float(settings.get("COPILOT_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        raise GenerationError("not_configured") from None
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise GenerationError("not_configured")
    return GenerationService(
        OllamaProvider(model, timeout_seconds=timeout), enabled=True, timeout_seconds=timeout
    )
