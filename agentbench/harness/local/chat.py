"""Host-side chat client used by the local Case and Judge Providers.

This is deliberately not the Model Interceptor. The Interceptor exists to observe
and re-route the *Agent's* traffic from inside an isolated container; these calls
are the harness reasoning about the Agent from outside it, exactly as the official
Providers reason about it from inside the DefuzeX Backend.

Only the OpenAI chat wire format and JSON-object mode are used, because that is
the intersection every candidate provider supports.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

from defuzex.errors import ProviderError

from agentbench.runtime.interception import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL_ENV,
    DEEPSEEK_MODEL_ENV,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
)

DEFAULT_TIMEOUT = 180.0
DEFAULT_MAX_TOKENS = 4096
RETRY_DELAYS = (2.0, 6.0)


class LocalProviderError(ProviderError):
    """A local Provider could not produce a usable Case or Judgment.

    Deriving from the SDK's own error is what keeps the message: ``create_run``
    and ``Run.judge`` re-raise ``DefuzeError`` untouched but collapse every other
    exception into a bare "The custom Provider failed", which would hide exactly
    the detail needed to fix a bad requirement or a rejected model request.
    """


@dataclass(frozen=True, slots=True)
class ChatModel:
    """One JSON-answering chat endpoint.

    ``response_format`` is pinned to ``json_object`` rather than ``json_schema``:
    DeepSeek rejects the latter outright, and the object mode is enough once the
    prompt states the shape.
    """

    api_key: str
    model: str = DEFAULT_DEEPSEEK_MODEL
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str], *, model: str | None = None
    ) -> "ChatModel":
        api_key = environ.get(DEEPSEEK_API_KEY_ENV, "").strip()
        if not api_key:
            raise LocalProviderError(
                f"Local Case generation and judging need {DEEPSEEK_API_KEY_ENV}. "
                "Set it in the environment or .env."
            )
        return cls(
            api_key=api_key,
            model=(
                model or environ.get(DEEPSEEK_MODEL_ENV, "") or DEFAULT_DEEPSEEK_MODEL
            ).strip(),
            base_url=(
                environ.get(DEEPSEEK_BASE_URL_ENV, "").strip()
                or DEFAULT_DEEPSEEK_BASE_URL
            ).rstrip("/"),
        )

    def json_object(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Return the model's reply parsed as a JSON object.

        Case generation and judging each happen once per Run, so a transient
        network failure would waste the whole Run; the call is retried rather
        than surfaced as an Agent failure.
        """

        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                # Case generation should vary between runs; judging should not.
                # One temperature cannot serve both, so callers that need
                # determinism pin it through the prompt instead.
                "temperature": 0.3,
            }
        ).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            if attempt:
                time.sleep(RETRY_DELAYS[attempt - 1])
            try:
                return _decode(self._post(body))
            except LocalProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 - retried and re-raised below
                last_error = exc
        raise LocalProviderError(
            f"The local Provider model call failed: {last_error}"
        ) from last_error

    def _post(self, body: bytes) -> str:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            # A rejected request will be rejected identically on every retry.
            raise LocalProviderError(
                f"The local Provider model returned HTTP {exc.code}: {detail}"
            ) from exc
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LocalProviderError("The local Provider model returned no choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LocalProviderError("The local Provider model returned empty content")
        return content


def _decode(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        # Some models fence JSON even in object mode.
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalProviderError(
            f"The local Provider model did not return JSON: {text[:200]}"
        ) from exc
    if not isinstance(value, dict):
        raise LocalProviderError("The local Provider model returned a non-object")
    return value


__all__ = [
    "ChatModel",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT",
    "LocalProviderError",
]
