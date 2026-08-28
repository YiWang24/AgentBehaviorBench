"""Deterministic offline model replies served from inside the interceptor.

Startup verification only needs the Agent to receive a well-formed model reply so
its framework keeps running; it does not need a real model. Replies are therefore
synthesized from what the request itself declares, which keeps this target
Agent-agnostic instead of hard-coding tool names per Agent.

The work is split three ways: :mod:`offline_schema` turns a declared schema into
a value, :mod:`offline_prompt` recovers a contract the Agent stated in prose
instead, and :mod:`offline_wire` writes the result in each provider's format.
This module is only the target that ties them together.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .config import Route, Target
from .offline_schema import OFFLINE_TEXT
from .offline_wire import (
    anthropic_events,
    anthropic_messages,
    encode_sse,
    openai_chat,
    openai_chat_events,
    openai_responses,
    openai_responses_events,
)

OFFLINE_TARGET_PLUGIN = "offline-mock"


_JSON_HEADERS = {"Content-Type": "application/json"}


_SSE_HEADERS = {"Content-Type": "text/event-stream", "Cache-Control": "no-store"}


class OfflineResponseError(ValueError):
    """Raised when a request cannot be answered without a real provider."""


@dataclass(frozen=True, slots=True)
class OfflineResponse:
    status: int
    headers: Mapping[str, str]
    content: bytes


class OfflineMockTarget:
    """Answer matched model calls locally instead of routing them upstream."""

    name = OFFLINE_TARGET_PLUGIN

    _SUPPORTED = ("openai-chat", "openai-responses", "anthropic-messages")

    def prepare_request(
        self,
        request: object,
        *,
        route: Route,
        target: Target,
    ) -> Any:
        """Validate and label the call without rewriting it to an upstream host.

        The request never leaves the interceptor, so the original host and path are
        kept: they are what the trace should report as the Agent's own destination.
        """

        from .targets import PreparedTargetRequest, TargetRoutingError

        if route.protocol_plugin not in self._SUPPORTED:
            raise TargetRoutingError(
                f"Offline mock does not support source protocol {route.protocol_plugin!r}"
            )
        payload = _decode(getattr(request, "content", b"") or b"", TargetRoutingError)
        source_model = payload.get("model")
        payload["model"] = target.model

        return PreparedTargetRequest(
            provider_id=target.provider_id,
            source_model=source_model,
            target_model=target.model,
            host=getattr(request, "pretty_host", None) or getattr(request, "host", ""),
            path=getattr(request, "path", ""),
            payload=payload,
        )

    def build_response(
        self,
        content: bytes,
        *,
        route: Route,
        target: Target,
    ) -> OfflineResponse:
        """Build the canned reply for one matched request body."""

        payload = _decode(content, OfflineResponseError)
        model = target.model
        token = _fingerprint(content)
        if route.protocol_plugin == "anthropic-messages":
            body = anthropic_messages(payload, model, token)
            to_events = anthropic_events
        elif route.protocol_plugin == "openai-responses":
            body = openai_responses(payload, model, token)
            to_events = openai_responses_events
        else:
            body = openai_chat(payload, model, token)
            to_events = openai_chat_events

        if payload.get("stream"):
            return OfflineResponse(
                status=200,
                headers=dict(_SSE_HEADERS),
                content=encode_sse(to_events(body)),
            )
        return OfflineResponse(
            status=200,
            headers=dict(_JSON_HEADERS),
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )


OFFLINE_MOCK_TARGET = OfflineMockTarget()


def _decode(content: bytes, error: type[Exception]) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error("Model request body must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise error("Model request body must be a JSON object")
    return payload


def _fingerprint(content: bytes) -> str:
    """Short, deterministic tag for one request body.

    Reply identifiers must differ between successive turns. LangGraph's
    ``add_messages`` reducer deduplicates by message id, so a constant id makes
    the second assistant reply overwrite the first instead of appending: the
    tool result stays last in the list and the agent's own routing then reads
    ``tool_calls`` off a tool message. Hashing the request body keeps replies
    reproducible for identical input while still separating distinct turns.
    """

    return hashlib.sha256(content).hexdigest()[:12]


__all__ = [
    "OFFLINE_MOCK_TARGET",
    "OFFLINE_TARGET_PLUGIN",
    "OFFLINE_TEXT",
    "OfflineMockTarget",
    "OfflineResponse",
    "OfflineResponseError",
]
