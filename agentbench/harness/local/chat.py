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

from kuma import ProviderError

from agentbench.runtime.interception import (
    DEEPSEEK_API_KEY_ENV,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DeepSeekProvider,
    InterceptionConfigurationError,
)

DEFAULT_TIMEOUT = 180.0
DEFAULT_MAX_TOKENS = 8192
RETRY_DELAYS = (2.0, 6.0)


class LocalProviderError(ProviderError):
    """A local Provider could not produce a usable Case or Judgment.

    Deriving from the SDK's own error is what keeps the message: ``create_run``
    and ``Run.judge`` re-raise ``DefuzeError`` untouched but collapse every other
    exception into a bare "The custom Provider failed", which would hide exactly
    the detail needed to fix a bad requirement or a rejected model request.
    """


class TransientProviderError(LocalProviderError):
    """A local Provider call failed in a way a fresh attempt can fix.

    A truncated or malformed reply is this roll of the model misbehaving, not a
    rejected request: generation runs at a non-zero temperature, so the next
    attempt re-rolls. Keeping these apart from an HTTP rejection is what lets the
    retry loop re-raise permanent failures immediately while still retrying the
    transient ones.
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
        """Resolve the same DeepSeek target the Agent's own traffic would reach.

        The endpoint is resolved through ``DeepSeekProvider`` rather than re-read
        here, so the host-side Providers and the intercepted Agent cannot end up
        pointing at different models or base URLs, and both get the same
        whitespace and HTTPS validation.
        """

        api_key = environ.get(DEEPSEEK_API_KEY_ENV, "").strip()
        if not api_key:
            raise LocalProviderError(
                f"Local Case generation and judging need {DEEPSEEK_API_KEY_ENV}. "
                "Set it in the environment or .env."
            )
        try:
            target = DeepSeekProvider(model).resolve(environ)
        except InterceptionConfigurationError as exc:
            raise LocalProviderError(str(exc)) from exc
        return cls(api_key=api_key, model=target.model, base_url=target.base_url)

    def json_object(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Return the model's reply parsed as a JSON object.

        Case generation and judging each happen once per Run, so a transient
        failure would waste the whole Run; the call is retried rather than
        surfaced as an Agent failure. That covers the network, and equally a
        reply that arrives truncated or unparseable — re-rolling costs one call,
        while giving up costs the Run and reads as if the Agent were at fault.
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
                return _decode(self._post(body, max_tokens=max_tokens))
            except TransientProviderError as exc:
                last_error = exc
            except LocalProviderError:
                # A rejected request will be rejected identically on every retry.
                raise
            except Exception as exc:  # noqa: BLE001 - retried and re-raised below
                last_error = exc
        raise LocalProviderError(
            f"The local Provider model call failed: {last_error}"
        ) from last_error

    def _post(self, body: bytes, *, max_tokens: int) -> str:
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
            raise TransientProviderError(
                "The local Provider model returned no choices"
            )
        choice = choices[0]
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise TransientProviderError(
                "The local Provider model returned empty content"
            )
        if choice.get("finish_reason") == "length":
            # Reported here rather than left to the JSON parser, which would
            # otherwise blame the shape of a reply that is merely unfinished.
            raise TransientProviderError(
                f"The local Provider model reached its {max_tokens}-token ceiling "
                "before finishing its JSON"
            )
        return content


def _decode(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        # Some models fence JSON even in object mode.
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TransientProviderError(
            f"The local Provider model did not return JSON: {text[:200]}"
        ) from exc
    if not isinstance(value, dict):
        raise TransientProviderError(
            "The local Provider model returned a non-object"
        )
    return value


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT",
    "ChatModel",
    "LocalProviderError",
    "TransientProviderError",
]
