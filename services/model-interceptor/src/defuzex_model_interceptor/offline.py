"""Deterministic offline model replies served from inside the interceptor.

Startup verification only needs the Agent to receive a well-formed model reply so
its framework keeps running; it does not need a real model. Replies are therefore
synthesized from what the request itself declares, which keeps this target
Agent-agnostic instead of hard-coding tool names per Agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .config import Route, Target


OFFLINE_TARGET_PLUGIN = "offline-mock"
OFFLINE_TEXT = "offline verification reply"
_JSON_HEADERS = {"Content-Type": "application/json"}
_SSE_HEADERS = {"Content-Type": "text/event-stream", "Cache-Control": "no-store"}
_TOOL_CALL_PREFIX = "call_offline_verify"
# Fixed text emitted by LangChain output parsers ahead of the schema block.
_SCHEMA_SENTINEL = "Here is the output schema"
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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
            to_events = _anthropic_events
        elif route.protocol_plugin == "openai-responses":
            body = _openai_responses(payload, model, token)
            to_events = _openai_responses_events
        else:
            body = _openai_chat(payload, model, token)
            to_events = _openai_chat_events

        if payload.get("stream"):
            return OfflineResponse(
                status=200,
                headers=dict(_SSE_HEADERS),
                content=_encode_sse(to_events(body)),
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


_MAX_SCHEMA_DEPTH = 4


def _resolve(field: object, root: Mapping[str, Any] | None) -> object:
    """Follow local `$ref` pointers so nested models get their real shape.

    Pydantic emits nested models as `$ref` into `$defs`, so a field that looks
    untyped is often a whole object. Only in-document pointers are followed;
    the mock never fetches a schema.
    """

    for _ in range(_MAX_SCHEMA_DEPTH + 1):
        if not isinstance(field, dict):
            return field
        reference = field.get("$ref")
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return field
        if root is None:
            return field
        node: object = root
        for part in reference[2:].split("/"):
            if not isinstance(node, dict):
                return field
            node = node.get(part)
        if node is None:
            return field
        field = node
    return field


def _arguments_for(
    schema: object, depth: int = 0, root: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Fill a JSON Schema's required properties with type-appropriate placeholders."""

    if root is None and isinstance(schema, dict):
        root = schema
    schema = _resolve(schema, root)
    if not isinstance(schema, dict) or depth > _MAX_SCHEMA_DEPTH:
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
        name: _placeholder(properties.get(name), depth + 1, root)
        for name in names
        if name in properties
    }


def _placeholder(
    field: object, depth: int = 0, root: Mapping[str, Any] | None = None
) -> Any:
    field = _resolve(field, root)
    if not isinstance(field, dict):
        return OFFLINE_TEXT
    choices = field.get("enum")
    if isinstance(choices, list) and choices:
        return choices[0]

    # Optional fields arrive as anyOf[..., {"type": "null"}]; answer the first
    # branch that is not null rather than treating the field as untyped.
    for key in ("anyOf", "oneOf", "allOf"):
        branches = field.get(key)
        if isinstance(branches, list):
            for branch in branches:
                resolved = _resolve(branch, root)
                if isinstance(resolved, dict) and resolved.get("type") != "null":
                    return _placeholder(resolved, depth, root)

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
        # One element rather than none. An empty list satisfies the schema but
        # is not what a model would return, and agents that go straight to
        # `items[0]` fail on it — a startup check should not turn into an
        # IndexError. Nesting is bounded so a recursive schema cannot spin.
        if depth > _MAX_SCHEMA_DEPTH:
            return []
        return [_placeholder(field.get("items"), depth + 1, root)]
    if kind == "object" or isinstance(field.get("properties"), dict):
        return _arguments_for(field, depth, root)
    return OFFLINE_TEXT


def _prompt_text(payload: Mapping[str, Any]) -> str:
    """Concatenate the text the Agent put in front of the model."""

    parts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key in ("content", "text", "input", "messages", "system"):
                if key in value:
                    walk(value[key])

    for key in ("messages", "input", "system", "prompt"):
        if key in payload:
            walk(payload[key])
    return "\n".join(parts)


def _prompt_schema(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recover a JSON schema that the Agent embedded in its prompt.

    LangChain's ``JsonOutputParser`` and ``PydanticOutputParser`` state the
    contract in the prompt rather than in the request: the model is told to emit
    JSON and the reply is parsed afterwards, so nothing in the request body
    declares it. Against a canned text reply those agents fail with
    ``OutputParserException``.

    The instructions those parsers generate are fixed text ending in a fenced
    block that holds the schema, so the schema can be recovered exactly rather
    than guessed. Anything that does not carry both the sentinel and a parsable
    schema object is left alone.
    """

    text = _prompt_text(payload)
    marker = text.rfind(_SCHEMA_SENTINEL)
    if marker == -1:
        return None
    fenced = _FENCED_JSON.search(text, marker)
    if fenced is None:
        return None
    try:
        schema = json.loads(fenced.group(1))
    except json.JSONDecodeError:
        return None
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema
    return None


def _structured_content(payload: Mapping[str, Any]) -> str | None:
    """Honour a requested JSON response format so parsing on the Agent side works."""

    response_format = payload.get("response_format")
    if not isinstance(response_format, dict):
        return None
    schema = response_format.get("json_schema")
    if isinstance(schema, dict):
        schema = schema.get("schema", schema)
    return json.dumps(_arguments_for(schema), ensure_ascii=False)


def _json_objects(text: str) -> list[dict[str, Any]]:
    """Every balanced `{...}` region in `text` that parses as a JSON object."""

    found: list[dict[str, Any]] = []
    depth = 0
    start = -1
    for index, character in enumerate(text):
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, dict):
                        found.append(parsed)
                start = -1
    return found


def _prompt_example(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recover a reply template the Agent wrote into its own prompt.

    Many agents state their contract by example rather than by schema — "return
    JSON in this shape", followed by a literal object — and then parse the reply
    themselves. Nothing in the request declares it, so a canned sentence makes
    the agent's own parser fail, often on a path that loops or aborts.

    Three conditions must all hold, so this cannot shadow a real contract: the
    prompt asks for JSON, it contains a parseable object with more than one key,
    and the request declares neither tools nor a response format. The example is
    returned as written — it is exactly what the Agent said a good reply looks
    like, including any flags it set to keep a loop from running again.
    """

    text = _prompt_text(payload)
    if "json" not in text.lower():
        return None
    candidates = [obj for obj in _json_objects(text) if len(obj) > 1]
    return candidates[-1] if candidates else None


def _prompt_schema_content(payload: Mapping[str, Any]) -> str | None:
    """Answer a contract the Agent stated in its prompt rather than its request.

    Ranked below a declared tool: an Agent that bound tools is waiting for a
    tool call, and a parser contract only applies to a free-text turn.
    """

    schema = _prompt_schema(payload)
    if schema is not None:
        return json.dumps(_arguments_for(schema), ensure_ascii=False)

    example = _prompt_example(payload)
    if example is not None:
        return json.dumps(example, ensure_ascii=False)
    return None


def _reply_text(payload: Mapping[str, Any]) -> str | None:
    """Content for a turn that answers in text rather than by calling a tool.

    Only reached once a tool call has been ruled out. Every protocol ranks the
    two the same way: an Agent that bound tools is waiting for a tool call, and a
    schema — declared in the request or stated in the prompt — describes the
    answer it wants after that.
    """

    return _structured_content(payload) or _prompt_schema_content(payload)


def _openai_chat(payload: Mapping[str, Any], model: str, token: str) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("messages")) else _first_tool(payload)
    structured = _reply_text(payload) if tool is None else None

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


def _openai_responses(
    payload: Mapping[str, Any], model: str, token: str
) -> dict[str, Any]:
    tool = None if _has_tool_result(payload.get("input")) else _first_tool(payload)
    structured = _reply_text(payload) if tool is None else None
    if structured is not None:
        output: list[dict[str, Any]] = [
            {
                "type": "message",
                "id": f"msg_defuzex_offline_{token}",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": structured}],
            }
        ]
    elif tool is not None:
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
    content: list[dict[str, Any]]
    if tool is None:
        content = [{"type": "text", "text": _reply_text(payload) or OFFLINE_TEXT}]
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


def _encode_sse(events: list[tuple[str | None, Any]]) -> bytes:
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


def _openai_chat_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Chat-completions SSE frames equivalent to one non-streaming reply."""

    choice = body["choices"][0]
    message = choice["message"]
    base = {
        "id": body["id"],
        "object": "chat.completion.chunk",
        "created": body.get("created", 0),
        "model": body.get("model"),
    }

    def chunk(delta: dict[str, Any], finish_reason: str | None) -> dict[str, Any]:
        return {
            **base,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    events: list[tuple[str | None, Any]] = [(None, chunk({"role": "assistant"}, None))]

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for index, call in enumerate(tool_calls):
            function = call.get("function", {})
            events.append(
                (
                    None,
                    chunk(
                        {
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
                        },
                        None,
                    ),
                )
            )
    elif message.get("content"):
        events.append((None, chunk({"content": message["content"]}, None)))

    events.append((None, chunk({}, choice.get("finish_reason", "stop"))))
    events.append((None, "[DONE]"))
    return events


def _anthropic_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Anthropic messages SSE frames equivalent to one non-streaming reply."""

    opening = {key: value for key, value in body.items() if key != "content"}
    opening["content"] = []
    events: list[tuple[str | None, Any]] = [
        ("message_start", {"type": "message_start", "message": opening})
    ]

    for index, block in enumerate(body.get("content", [])):
        if block.get("type") == "tool_use":
            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {
                            "type": "tool_use",
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": {},
                        },
                    },
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(
                                block.get("input", {}), ensure_ascii=False
                            ),
                        },
                    },
                )
            )
        else:
            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": block.get("text", "")},
                    },
                )
            )
        events.append(
            ("content_block_stop", {"type": "content_block_stop", "index": index})
        )

    events.append(
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": body.get("stop_reason"),
                    "stop_sequence": None,
                },
                "usage": body.get("usage", {}),
            },
        )
    )
    events.append(("message_stop", {"type": "message_stop"}))
    return events


def _openai_responses_events(body: Mapping[str, Any]) -> list[tuple[str | None, Any]]:
    """Responses-API SSE frames equivalent to one non-streaming reply.

    Clients that stream this protocol reconstruct the reply from the terminal
    `response.completed` event, so the whole response object is carried there;
    the per-item events before it mirror the shape a real provider sends.
    """

    creating = {key: value for key, value in body.items() if key != "output"}
    creating["output"] = []
    creating["status"] = "in_progress"

    events: list[tuple[str | None, Any]] = [
        ("response.created", {"type": "response.created", "response": creating})
    ]

    for index, item in enumerate(body.get("output", [])):
        events.append(
            (
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": index,
                    "item": item,
                },
            )
        )
        events.append(
            (
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "item": item,
                },
            )
        )

    events.append(
        ("response.completed", {"type": "response.completed", "response": dict(body)})
    )
    return events
