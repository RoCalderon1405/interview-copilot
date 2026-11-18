"""Bounded local-only Ollama chat adapter without tools, credentials or retries."""
from __future__ import annotations

import json
import math
import re

import httpx

from ..application.generation import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    GenerationError,
    GenerationLanguage,
    few_shot_examples,
    system_instructions,
)

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_OUTPUT_TOKENS = 256
_MODEL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?")


class OllamaProvider:
    """Call a preinstalled local model; never pull models or follow redirects."""

    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (not isinstance(model, str) or len(model) > 200 or not _MODEL_NAME.fullmatch(model)
                or model.casefold().endswith((":cloud", "-cloud"))
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60):
            raise GenerationError("not_configured")
        self.model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def generate(self, question: str, language: GenerationLanguage) -> str:
        """Return a completed assistant answer, rejecting tool calls and truncation."""
        if (not isinstance(question, str) or len(question) > MAX_QUESTION_CHARS
                or len(question.strip()) < 3):
            raise GenerationError("invalid_input")
        messages = [{"role": "system", "content": system_instructions(language)}]
        for example_question, example_answer in few_shot_examples(language):
            messages.extend((
                {"role": "user", "content": example_question},
                {"role": "assistant", "content": example_answer},
            ))
        messages.append({"role": "user", "content": question})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": MAX_OUTPUT_TOKENS, "temperature": 0.2},
        }
        try:
            # No environment proxy/auth/netrc, redirects, cookies from earlier
            # requests or SDK retries. The caller enforces the total deadline.
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, trust_env=False, follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream("POST", OLLAMA_CHAT_URL, json=payload) as response:
                    if response.status_code != 200:
                        raise GenerationError("unavailable" if response.status_code == 503 else "provider_error")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise GenerationError("invalid_response")
            data = json.loads(body)
        except httpx.TimeoutException:
            raise GenerationError("timeout") from None
        except httpx.DecodingError:
            raise GenerationError("invalid_response") from None
        except httpx.RequestError:
            raise GenerationError("unavailable") from None
        except (ValueError, UnicodeError):
            raise GenerationError("invalid_response") from None

        if not isinstance(data, dict) or data.get("done") is not True or "error" in data:
            raise GenerationError("invalid_response")
        accepted_models = (self.model,) if ":" in self.model else (self.model, self.model + ":latest")
        if data.get("model") not in accepted_models or data.get("done_reason") == "length":
            raise GenerationError("invalid_response")
        message = data.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise GenerationError("invalid_response")
        answer = message.get("content")
        if (message.get("tool_calls") not in (None, []) or not isinstance(answer, str)
                or not answer.strip() or len(answer) > MAX_ANSWER_CHARS):
            raise GenerationError("invalid_response")
        return answer.strip()
