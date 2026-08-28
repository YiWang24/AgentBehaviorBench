"""Built-in upstream target provider adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import Route, Target


class TargetRoutingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedTargetRequest:
    provider_id: str
    source_model: object
    target_model: str
    host: str
    path: str
    payload: object


@dataclass(frozen=True, slots=True)
class OpenAICompatibleTarget:
    """Rewrite an intercepted request onto an OpenAI-compatible endpoint.

    Only the host, path, and model are replaced, so every provider that speaks the
    OpenAI wire format shares this adapter. It is registered once per provider name
    so an Agent manifest names the provider it is actually reaching.
    """

    name: str

    _ENDPOINTS = {
        "openai-chat": "/chat/completions",
        "openai-responses": "/responses",
        "anthropic-messages": "/messages",
    }

    def prepare_request(
        self,
        request: object,
        *,
        route: Route,
        target: Target,
    ) -> PreparedTargetRequest:
        try:
            endpoint = self._ENDPOINTS[route.protocol_plugin]
        except KeyError as exc:
            raise TargetRoutingError(
                f"{self.name} does not support source protocol "
                f"{route.protocol_plugin!r}"
            ) from exc

        content = getattr(request, "content", b"") or b""
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TargetRoutingError("Model request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise TargetRoutingError("Model request body must be a JSON object")

        source_model = payload.get("model")
        payload["model"] = target.model
        parsed = urlsplit(target.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise TargetRoutingError(f"{self.name} target base URL must use HTTPS")
        base_path = parsed.path.rstrip("/")
        target_path = f"{base_path}{endpoint}"

        setattr(request, "scheme", "https")
        setattr(request, "host", parsed.hostname)
        setattr(request, "port", parsed.port or 443)
        setattr(request, "path", target_path)
        setattr(
            request,
            "content",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
        )
        headers = getattr(request, "headers")
        headers["host"] = parsed.netloc
        for key, value in target.headers.items():
            headers[key] = value

        return PreparedTargetRequest(
            provider_id=target.provider_id,
            source_model=source_model,
            target_model=target.model,
            host=parsed.hostname,
            path=target_path,
            payload=payload,
        )


OPENROUTER_TARGET = OpenAICompatibleTarget("openrouter")
DEEPSEEK_TARGET = OpenAICompatibleTarget("deepseek")
