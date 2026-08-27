"""Deterministic offline model replies served from inside the interceptor.

Startup verification only needs the Agent to receive a well-formed model reply so
its framework keeps running; it does not need a real model. Replies are therefore
synthesized from what the request itself declares, which keeps this target
Agent-agnostic instead of hard-coding tool names per Agent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .config import Route, Target


OFFLINE_TARGET_PLUGIN = "offline-mock"
OFFLINE_TEXT = "offline verification reply"
_JSON_HEADERS = {"Content-Type": "application/json"}
_TOOL_CALL_PREFIX = "call_offline_verify"


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
            body = _anthropic_messages(payload, model, token)
        elif route.protocol_plugin == "openai-responses":
            body = _openai_responses(payload, model, token)
        else:
            body = _openai_chat(payload, model, token)
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


def _has_tool_result(messages: object) -> bool:
    """Detect that a tool already ran, so the reply must end the agent loop."""

    if not isinstance(messages, list):
        return False
    for item in messages:
        if not isinstance(item, dict):
            continue
        # OpenAI chat completions.
        if item.get("role") == "tool":
            return True
        # OpenAI Responses API: tool output is a typed item with no role.
        if item.get("type") in ("function_call_output", "computer_call_output"):
            return True
        # Anthropic messages.
        if item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in content
            ):
                return True
    return False


def _first_tool(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return the first declared tool name and a schema-satisfying argument set."""

    tools = payload.get("tools")
    if not isinstance(tools, list):
        return None
    for item in tools:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if isinstance(function, dict):  # OpenAI chat completions
            name = function.get("name")
            schema = function.get("parameters")
        else:  # Anthropic messages and OpenAI responses
            name = item.get("name")
            schema = item.get("input_schema") or item.get("parameters")
        if isinstance(name, str) and name:
            return name, _arguments_for(schema)
    return None


def _arguments_for(schema: object) -> dict[str, Any]:
    """Fill a JSON Schema's required properties with type-appropriate placeholders."""

    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict):
        return {}
    names = (
        [item for item in required if isinstance(item, str)]
        if isinstance(required, list)
        else list(properties)
    )
    return {
        name: _placeholder(properties.get(name))
        for name in names
        if name in properties
    }


def _placeholder(field: object) -> Any:
    if not isinstance(field, dict):
        return OFFLINE_TEXT
    choices = field.get("enum")
    if isinstance(choices, list) and choices:
        return choices[0]
    kind = field.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "string")
    if kind == "boolean":
        return True
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "array":
        return []
    if kind == "object":
        return _arguments_for(field)
    return OFFLINE_TEXT


def _structured_content(payload: Mapping[str, Any]) -> str | None:
    """Honour a requested JSON response format so parsing on the Agent side works."""

    response_format = payload.get("response_format")
    if not isinstance(response_format, dict):
        return None
    schema = response_format.get("json_schema")
    if isinstance(schema, dict):
        schema = schema.get("schema", schema)
    return json.dumps(_arguments_for(schema), ensure_ascii=False)


def _openai_chat(payload: Mapping[str, Any], model: str, token: str) -> dict[str, Any]:
    structured = _structured_content(payload)
    tool = None if _has_tool_result(payload.get("messages")) else _first_tool(payload)

    if structured is not None:
        message: dict[str, Any] = {"role": "assistant", "content": structured}
        finish_reason = "stop"
    elif tool is not None:
        name, arguments = tool
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"{_TOOL_CALL_PREFIX}_{token}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    else:
        message = {"role": "assistant", "content": OFFLINE_TEXT}
        finish_reason = "stop"

    return {
        "id": f"chatcmpl-defuzex-offline-{token}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _openai_responses(
    payload: Mapping[str, Any], model: str, token: str
) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("input")) else _first_tool(payload)
    if tool is not None:
        name, arguments = tool
        call_id = f"{_TOOL_CALL_PREFIX}_{token}"
        output: list[dict[str, Any]] = [
            {
                "type": "function_call",
                "id": call_id,
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            }
        ]
    else:
        output = [
            {
                "type": "message",
                "id": f"msg_defuzex_offline_{token}",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": OFFLINE_TEXT}],
            }
        ]
    return {
        "id": f"resp-defuzex-offline-{token}",
        "object": "response",
        "created_at": 0,
        "model": model,
        "status": "completed",
        "output": output,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _anthropic_messages(
    payload: Mapping[str, Any], model: str, token: str
) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("messages")) else _first_tool(payload)
    if tool is not None:
        name, arguments = tool
        content: list[dict[str, Any]] = [
            {
                "type": "tool_use",
                "id": f"{_TOOL_CALL_PREFIX}_{token}",
                "name": name,
                "input": arguments,
            }
        ]
        stop_reason = "tool_use"
    else:
        content = [{"type": "text", "text": OFFLINE_TEXT}]
        stop_reason = "end_turn"
    return {
        "id": f"msg-defuzex-offline-{token}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
