"""Ollama transport used by local-LLM policy analysis."""

from __future__ import annotations

import json
import socket
from typing import Any, Protocol
from urllib import error, request

from .llm_models import LLMConnectionError, LLMResponseError, LLMTimeoutError


DEFAULT_MODEL = "qwen3:4b-instruct"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_RETRIES = 2

SYSTEM_PROMPT = """You extract facts from privacy policies.
Use only the supplied text; never use outside knowledge or make assumptions.
For every field, value must be yes, no, or unclear.
- sharing_condition: yes when sharing conditions or recipients are disclosed;
  no only when sharing is explicitly denied; otherwise unclear.
- retention_policy: yes when a retention period or deletion criterion is
  disclosed; no only when the policy explicitly says data is not retained;
  otherwise unclear.
- cross_border_transfer: yes when international transfer, processing, or
  storage is disclosed; no when explicitly denied; otherwise unclear.
- child_data_involved: yes when children's data is collected or processed; no
  when the service excludes children or explicitly does not collect their data;
  otherwise unclear.
Evidence must be copied exactly and contiguously from the supplied text.
Return an empty evidence list for unclear fields.  Do not add extra fields.
"""


class ChatClient(Protocol):
    """Small interface that makes the LLM transport replaceable in tests."""

    def chat(self, *, model: str, prompt: str, schema: dict[str, Any], timeout: float) -> str:
        """Return only the model's JSON message content."""


class OllamaChatClient:
    """Minimal Ollama HTTP client using only Python's standard library."""

    def __init__(self, url: str = OLLAMA_CHAT_URL) -> None:
        self.url = url

    def chat(self, *, model: str, prompt: str, schema: dict[str, Any], timeout: float) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1024},
        }
        http_request = request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise LLMTimeoutError(f"Ollama timed out after {timeout:g} seconds") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"Ollama returned HTTP {exc.code}: {detail[:300]}"
            if exc.code in {408, 429} or exc.code >= 500:
                raise LLMConnectionError(message) from exc
            raise LLMResponseError(message) from exc
        except (error.URLError, ConnectionError, OSError) as exc:
            raise LLMConnectionError(
                "Cannot connect to Ollama at 127.0.0.1:11434; start Ollama and pull the configured model"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseError("Ollama returned a non-JSON HTTP response") from exc

        try:
            content = body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMResponseError("Ollama response is missing message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("Ollama returned empty model content")
        return content
