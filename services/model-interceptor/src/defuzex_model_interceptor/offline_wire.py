"""Render one offline reply in each supported provider's wire format.

The decision of *what* to say is made once — a tool call when the Agent declared
tools and none has run yet, otherwise whatever contract it stated — and then
written three ways. The streaming forms carry exactly the same content as the
non-streaming ones, so a client reconstructs an identical reply either way.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .offline_schema import OFFLINE_TEXT, arguments_for
from .offline_prompt import reply_text

_TOOL_CALL_PREFIX = "call_offline_verify"


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
            return name, arguments_for(schema)
    return None


def openai_chat(payload: Mapping[str, Any], model: str, token: str) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("messages")) else _first_tool(payload)
    structured = reply_text(payload) if tool is None else None

    if tool is None:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": structured or OFFLINE_TEXT,
        }
        finish_reason = "stop"
    else:
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

    return {
        "id": f"chatcmpl-defuzex-offline-{token}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def openai_responses(
    payload: Mapping[str, Any], model: str, token: str
) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("input")) else _first_tool(payload)
    output: list[dict[str, Any]]
    if tool is None:
        output = [
            {
                "type": "message",
                "id": f"msg_defuzex_offline_{token}",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": reply_text(payload) or OFFLINE_TEXT,
                    }
                ],
            }
        ]
    else:
        name, arguments = tool
        call_id = f"{_TOOL_CALL_PREFIX}_{token}"
        output = [
            {
                "type": "function_call",
                "id": call_id,
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
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


def anthropic_messages(
    payload: Mapping[str, Any], model: str, token: str
) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("messages")) else _first_tool(payload)
    content: list[dict[str, Any]]
    if tool is None:
        content = [{"type": "text", "text": reply_text(payload) or OFFLINE_TEXT}]
        stop_reason = "end_turn"
    else:
        name, arguments = tool
        content = [
            {
                "type": "tool_use",
                "id": f"{_TOOL_CALL_PREFIX}_{token}",
                "name": name,
                "input": arguments,
            }
        ]
        stop_reason = "tool_use"
    return {
        "id": f"msg-defuzex-offline-{token}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def encode_sse(events: list[tuple[str | None, Any]]) -> bytes:
    """Render `(event_name, data)` pairs as one complete SSE body.

    The reply is canned, so the whole stream is emitted at once. Clients parse
    it incrementally either way, and the interceptor's `text/event-stream`
    decoder reads the same `data:` lines it reads from a real provider.
    """

    lines: list[str] = []
    for name, data in events:
        if name is not None:
            lines.append(f"event: {name}")
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        lines.append(f"data: {payload}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _event(name: str, **payload: Any) -> tuple[str, dict[str, Any]]:
    """One named SSE frame.

    Every frame in these protocols repeats its own event name inside the JSON as
    ``type``, so naming it once here keeps the two from drifting apart.
    """

    return name, {"type": name, **payload}


def _tool_call_delta(index: int, call: Mapping[str, Any]) -> dict[str, Any]:
    function = call.get("function", {})
    return {
        "tool_calls": [
            {
                "index": index,
                "id": call.get("id"),
                "type": "function",
                "function": {
                    "name": function.get("name"),
                    "arguments": function.get("arguments", ""),
                },
            }
        ]
    }


def openai_chat_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Chat-completions SSE frames equivalent to one non-streaming reply."""

    choice = body["choices"][0]
    message = choice["message"]
    base = {
        "id": body["id"],
        "object": "chat.completion.chunk",
        "created": body.get("created", 0),
        "model": body.get("model"),
    }

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> tuple[None, Any]:
        return None, {
            **base,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    events: list[tuple[str | None, Any]] = [chunk({"role": "assistant"})]

    tool_calls = message.get("tool_calls")
    if tool_calls:
        events.extend(
            chunk(_tool_call_delta(index, call))
            for index, call in enumerate(tool_calls)
        )
    elif message.get("content"):
        events.append(chunk({"content": message["content"]}))

    events.append(chunk({}, choice.get("finish_reason", "stop")))
    events.append((None, "[DONE]"))
    return events


def anthropic_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Anthropic messages SSE frames equivalent to one non-streaming reply."""

    opening = {key: value for key, value in body.items() if key != "content"}
    opening["content"] = []

    events: list[tuple[str | None, Any]] = [_event("message_start", message=opening)]
    for index, block in enumerate(body.get("content", [])):
        events.extend(_anthropic_block_events(index, block))
    events.append(
        _event(
            "message_delta",
            delta={"stop_reason": body.get("stop_reason"), "stop_sequence": None},
            usage=body.get("usage", {}),
        )
    )
    events.append(_event("message_stop"))
    return events


def _anthropic_block_events(
    index: int, block: Mapping[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """The start/delta/stop trio one content block streams as."""

    if block.get("type") == "tool_use":
        content_block = {
            "type": "tool_use",
            "id": block.get("id"),
            "name": block.get("name"),
            "input": {},
        }
        delta = {
            "type": "input_json_delta",
            "partial_json": json.dumps(block.get("input", {}), ensure_ascii=False),
        }
    else:
        content_block = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": block.get("text", "")}

    return [
        _event("content_block_start", index=index, content_block=content_block),
        _event("content_block_delta", index=index, delta=delta),
        _event("content_block_stop", index=index),
    ]


def openai_responses_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Responses-API SSE frames equivalent to one non-streaming reply.

    Clients that stream this protocol reconstruct the reply from the terminal
    `response.completed` event, so the whole response object is carried there;
    the per-item events before it mirror the shape a real provider sends.
    """

    creating = {key: value for key, value in body.items() if key != "output"}
    creating["output"] = []
    creating["status"] = "in_progress"

    events: list[tuple[str | None, Any]] = [
        _event("response.created", response=creating)
    ]
    for index, item in enumerate(body.get("output", [])):
        events.append(
            _event("response.output_item.added", output_index=index, item=item)
        )
        events.append(
            _event("response.output_item.done", output_index=index, item=item)
        )
    events.append(_event("response.completed", response=dict(body)))
    return events


__all__ = [
    "anthropic_events",
    "anthropic_messages",
    "encode_sse",
    "openai_chat",
    "openai_chat_events",
    "openai_responses",
    "openai_responses_events",
]
