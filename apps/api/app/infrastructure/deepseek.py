"""Fixed-origin DeepSeek chat adapter behind the existing GenerationProvider port.

AI-002 Stage 1: the adapter exists for deterministic tests but is not imported
by bootstrap, settings, Live transport or the renderer. It sends only the
detected question, the fixed instructions and the selected-language fixed
examples. The caller injects the key; it is never logged, echoed or stored.
"""
from __future__ import annotations

import asyncio
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

# The endpoint is a module constant: callers cannot change scheme, host or path.
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELS = frozenset({"deepseek-flash", "deepseek-v4-pro"})
MAX_RESPONSE_BYTES = 64 * 1024
MAX_OUTPUT_TOKENS = 256
_KEY = re.compile(r"[A-Za-z0-9._-]{16,200}")


def _status_error(status: int) -> GenerationError:
    """Map upstream statuses to existing allowlisted codes, never to bodies."""
    if status == 429 or status >= 500:
        return GenerationError("unavailable")
    # 401/403 (rejected key), redirects and other client errors are not retried.
    return GenerationError("provider_error")


def _answer_from(data: object, model: str) -> str:
    """Accept one complete assistant message; reject truncation and tool output."""
    if not isinstance(data, dict) or "error" in data or data.get("model") != model:
        raise GenerationError("invalid_response")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise GenerationError("invalid_response")
    choice = choices[0]
    index = choice.get("index")
    if choice.get("finish_reason") != "stop":
        raise GenerationError("invalid_response")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool) or index != 0):
        raise GenerationError("invalid_response")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise GenerationError("invalid_response")
    if (message.get("tool_calls") not in (None, [])
            or message.get("function_call") is not None):
        raise GenerationError("invalid_response")
    # Only final assistant text is used; reasoning or other fields are ignored.
    content = message.get("content")
    if (not isinstance(content, str) or not content.strip()
            or len(content) > MAX_ANSWER_CHARS):
        raise GenerationError("invalid_response")
    return content.strip()


class DeepSeekProvider:
    """Call the fixed DeepSeek chat endpoint in explicit non-thinking mode.

    The key is injectable for composition and tests and is validated before any
    request. There are no retries, redirects, proxies, streams, tools or web
    search. The caller still owns the overall generation deadline.
    """

    name = "deepseek"

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (not isinstance(model, str) or model not in DEEPSEEK_MODELS
                or not isinstance(api_key, str) or not _KEY.fullmatch(api_key)
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60):
            raise GenerationError("not_configured")
        self.model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def generate(self, question: str, language: GenerationLanguage) -> str:
        """Return completed assistant text or raise a controlled generation error."""
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
            "thinking": {"type": "disabled"},
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.2,
        }
        try:
            # The internal deadline bounds the whole exchange, including a
            # slow-drip body that stays inside each httpx read timeout.
            async with asyncio.timeout(self._timeout_seconds):
                data = await self._post(payload)
        except TimeoutError:
            raise GenerationError("timeout") from None
        except httpx.TimeoutException:
            raise GenerationError("timeout") from None
        except httpx.DecodingError:
            raise GenerationError("invalid_response") from None
        except httpx.RequestError:
            raise GenerationError("unavailable") from None
        except (ValueError, UnicodeError, RecursionError):
            raise GenerationError("invalid_response") from None
        return _answer_from(data, self.model)

    async def _post(self, payload: dict[str, object]) -> object:
        # No environment proxy/auth/netrc, redirects, cookies or transport
        # retries. Only the bearer header carries the injected key.
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds, trust_env=False, follow_redirects=False,
            transport=self._transport,
        ) as client:
            async with client.stream(
                "POST", DEEPSEEK_CHAT_URL, json=payload,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Accept": "application/json",
                         # Refuse transparent decompression: a small body must
                         # not expand before the byte cap is checked.
                         "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise _status_error(response.status_code)
                encoding = response.headers.get("content-encoding", "identity").strip().casefold()
                if encoding != "identity":
                    raise GenerationError("invalid_response")
                body = bytearray()
                if response.is_stream_consumed:
                    # Injected buffered transports (tests) already hold bytes.
                    body.extend(response.content)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise GenerationError("invalid_response")
                else:
                    # Raw bytes are capped before any decoding could allocate.
                    async for chunk in response.aiter_raw(chunk_size=4096):
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise GenerationError("invalid_response")
        return json.loads(body)
