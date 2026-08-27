from __future__ import annotations

import json
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERCEPTOR_SRC = REPO_ROOT / "services" / "model-interceptor" / "src"
sys.path.insert(0, str(INTERCEPTOR_SRC))

from defuzex_model_interceptor.config import Route, Target  # noqa: E402
from defuzex_model_interceptor.offline import (  # noqa: E402
    OFFLINE_TARGET_PLUGIN,
    OFFLINE_MOCK_TARGET,
    OFFLINE_TEXT,
    OfflineResponseError,
)
from defuzex_model_interceptor.registry import load_targets  # noqa: E402


def _route(protocol_plugin: str = "openai-chat") -> Route:
    return Route(
        route_id="offline",
        host_patterns=("api.openai.com",),
        ports=(443,),
        methods=("POST",),
        path_patterns=("/v1/chat/completions",),
        protocol_plugin=protocol_plugin,
        credential_id="primary",
    )


def _target() -> Target:
    return Target(
        provider_id="offline",
        target_plugin=OFFLINE_TARGET_PLUGIN,
        base_url="offline://local",
        model="offline-verify-model",
        headers=MappingProxyType({}),
    )


def _reply(payload: dict[str, object], protocol_plugin: str = "openai-chat") -> dict:
    response = OFFLINE_MOCK_TARGET.build_response(
        json.dumps(payload).encode("utf-8"),
        route=_route(protocol_plugin),
        target=_target(),
    )
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/json"
    return json.loads(response.content)


def test_offline_target_is_discoverable_through_the_plugin_registry() -> None:
    assert load_targets()[OFFLINE_TARGET_PLUGIN] is OFFLINE_MOCK_TARGET


def test_plain_chat_request_returns_finished_text() -> None:
    body = _reply({"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "hi"}]})

    choice = body["choices"][0]
    assert body["model"] == "offline-verify-model"
    assert choice["message"]["content"] == OFFLINE_TEXT
    assert choice["finish_reason"] == "stop"


def test_declared_tool_is_called_with_schema_satisfying_arguments() -> None:
    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "write_email",
                        "parameters": {
                            "type": "object",
                            "required": ["to", "retries", "urgent", "tone"],
                            "properties": {
                                "to": {"type": "string"},
                                "retries": {"type": "integer"},
                                "urgent": {"type": "boolean"},
                                "tone": {"type": "string", "enum": ["formal", "casual"]},
                                "ignored": {"type": "string"},
                            },
                        },
                    },
                }
            ],
        }
    )

    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]["function"]
    assert call["name"] == "write_email"
    assert json.loads(call["arguments"]) == {
        "to": OFFLINE_TEXT,
        "retries": 0,
        "urgent": True,
        "tone": "formal",
    }


def test_reply_stops_calling_tools_once_a_tool_result_is_present() -> None:
    """Without this the Agent would loop on tool calls until its step limit."""

    body = _reply(
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": None},
                {"role": "tool", "content": "tool output"},
            ],
            "tools": [
                {"type": "function", "function": {"name": "search", "parameters": {}}}
            ],
        }
    )

    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == OFFLINE_TEXT


def test_structured_output_request_returns_schema_shaped_json() -> None:
    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "schema": {
                        "type": "object",
                        "required": ["classification"],
                        "properties": {
                            "classification": {
                                "type": "string",
                                "enum": ["respond", "ignore"],
                            }
                        },
                    }
                },
            },
        }
    )

    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert json.loads(choice["message"]["content"]) == {"classification": "respond"}


def test_every_protocol_ranks_a_declared_tool_above_a_requested_schema() -> None:
    """An Agent that bound tools is waiting for a tool call.

    A schema describes the answer it wants afterwards, so a request carrying both
    must resolve the same way on every protocol; ranking them differently made one
    protocol answer in text while the others called the tool.
    """

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "schema": {
                "type": "object",
                "required": ["verdict"],
                "properties": {"verdict": {"type": "string"}},
            }
        },
    }
    chat_tool = {
        "type": "function",
        "function": {"name": "search", "parameters": {"type": "object"}},
    }
    flat_tool = {"name": "search", "input_schema": {"type": "object"}}

    chat = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [chat_tool],
            "response_format": response_format,
        }
    )
    responses = _reply(
        {
            "input": [{"role": "user", "content": "hi"}],
            "tools": [flat_tool],
            "response_format": response_format,
        },
        protocol_plugin="openai-responses",
    )
    anthropic = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [flat_tool],
            "response_format": response_format,
        },
        protocol_plugin="anthropic-messages",
    )

    assert chat["choices"][0]["finish_reason"] == "tool_calls"
    assert chat["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "search"
    assert responses["output"][0]["type"] == "function_call"
    assert anthropic["stop_reason"] == "tool_use"


def test_a_requested_schema_is_still_answered_when_no_tool_is_declared() -> None:
    """Ranking tools first must not stop a plain schema request being honoured."""

    for plugin, key in (
        ("openai-chat", "messages"),
        ("openai-responses", "input"),
        ("anthropic-messages", "messages"),
    ):
        body = _reply(
            {
                key: [{"role": "user", "content": "hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "required": ["verdict"],
                            "properties": {
                                "verdict": {"type": "string", "enum": ["yes", "no"]}
                            },
                        }
                    },
                },
            },
            protocol_plugin=plugin,
        )
        if plugin == "openai-chat":
            text = body["choices"][0]["message"]["content"]
        elif plugin == "openai-responses":
            text = body["output"][0]["content"][0]["text"]
        else:
            text = body["content"][0]["text"]
        assert json.loads(text) == {"verdict": "yes"}, plugin


def test_anthropic_messages_reply_uses_tool_use_blocks() -> None:
    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "name": "lookup_order",
                    "input_schema": {
                        "type": "object",
                        "required": ["order_id"],
                        "properties": {"order_id": {"type": "string"}},
                    },
                }
            ],
        },
        protocol_plugin="anthropic-messages",
    )

    assert body["stop_reason"] == "tool_use"
    assert body["content"][0]["type"] == "tool_use"
    assert body["content"][0]["name"] == "lookup_order"
    assert body["content"][0]["input"] == {"order_id": OFFLINE_TEXT}


def test_anthropic_reply_ends_the_turn_after_a_tool_result_block() -> None:
    body = _reply(
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "done"}],
                },
            ],
            "tools": [{"name": "lookup_order", "input_schema": {}}],
        },
        protocol_plugin="anthropic-messages",
    )

    assert body["stop_reason"] == "end_turn"
    assert body["content"][0]["text"] == OFFLINE_TEXT


def test_openai_responses_reply_uses_function_call_output() -> None:
    body = _reply(
        {
            "input": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "name": "search",
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        },
        protocol_plugin="openai-responses",
    )

    assert body["status"] == "completed"
    assert body["output"][0]["type"] == "function_call"
    assert body["output"][0]["name"] == "search"
    assert json.loads(body["output"][0]["arguments"]) == {"query": OFFLINE_TEXT}


def test_responses_reply_stops_calling_tools_once_a_tool_result_is_present() -> None:
    """A Responses-API tool result is a typed item, not a message with a role.

    Matching only on ``role == "tool"`` never fires here, so the reply kept
    requesting the same tool and any tool-using Agent on this protocol looped
    until its recursion limit.
    """

    body = _reply(
        {
            "input": [
                {"role": "user", "content": "hi"},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "tool output",
                },
            ],
            "tools": [{"name": "search", "parameters": {}}],
        },
        protocol_plugin="openai-responses",
    )

    assert [item["type"] for item in body["output"]] == ["message"]
    assert body["output"][0]["content"][0]["text"] == OFFLINE_TEXT


@pytest.mark.parametrize(
    ("protocol_plugin", "payload_key"),
    [
        ("openai-chat", "messages"),
        ("openai-responses", "input"),
        ("anthropic-messages", "messages"),
    ],
)
def test_reply_identifiers_differ_between_turns(
    protocol_plugin: str, payload_key: str
) -> None:
    """LangGraph's ``add_messages`` reducer deduplicates by message id.

    Constant identifiers made the second reply overwrite the first instead of
    appending, which left a tool message last in the list and broke Agent
    routing that reads ``tool_calls`` off the final message.
    """

    first = _reply(
        {payload_key: [{"role": "user", "content": "first turn"}]},
        protocol_plugin=protocol_plugin,
    )
    second = _reply(
        {payload_key: [{"role": "user", "content": "second turn"}]},
        protocol_plugin=protocol_plugin,
    )

    assert first["id"] != second["id"]


def test_reply_identifiers_are_reproducible_for_an_identical_request() -> None:
    payload = {"messages": [{"role": "user", "content": "same"}]}

    assert _reply(payload)["id"] == _reply(payload)["id"]


def _sse(payload: dict[str, object], protocol_plugin: str = "openai-chat") -> list[dict]:
    response = OFFLINE_MOCK_TARGET.build_response(
        json.dumps({**payload, "stream": True}).encode("utf-8"),
        route=_route(protocol_plugin),
        target=_target(),
    )
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/event-stream"

    frames = []
    for line in response.content.decode("utf-8").splitlines():
        if line.startswith("data:"):
            value = line[5:].strip()
            frames.append(value if value == "[DONE]" else json.loads(value))
    return frames


def test_streaming_chat_request_gets_an_event_stream() -> None:
    """A non-streaming body for a streaming request yields no generations.

    langchain-openai reads chat completions through its stream parser whenever
    the request sets `stream`, and a plain JSON reply leaves that parser with
    nothing, failing the run with "No generations found in stream".
    """

    frames = _sse({"messages": [{"role": "user", "content": "hi"}]})

    assert frames[-1] == "[DONE]"
    assert frames[0]["object"] == "chat.completion.chunk"
    assert frames[0]["choices"][0]["delta"]["role"] == "assistant"
    assert any(
        frame != "[DONE]" and frame["choices"][0]["delta"].get("content") == OFFLINE_TEXT
        for frame in frames
    )
    assert frames[-2]["choices"][0]["finish_reason"] == "stop"


def test_streaming_chat_tool_call_is_delivered_as_a_delta() -> None:
    frames = _sse(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {"type": "function", "function": {"name": "search", "parameters": {}}}
            ],
        }
    )

    deltas = [
        frame["choices"][0]["delta"]
        for frame in frames
        if frame != "[DONE]" and frame["choices"][0]["delta"].get("tool_calls")
    ]

    assert len(deltas) == 1
    call = deltas[0]["tool_calls"][0]
    assert call["index"] == 0
    assert call["function"]["name"] == "search"
    assert frames[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_streaming_anthropic_request_gets_message_events() -> None:
    frames = _sse(
        {"messages": [{"role": "user", "content": "hi"}]},
        protocol_plugin="anthropic-messages",
    )
    kinds = [frame["type"] for frame in frames]

    assert kinds[0] == "message_start"
    assert kinds[-1] == "message_stop"
    assert "content_block_delta" in kinds
    assert any(
        frame.get("delta", {}).get("text") == OFFLINE_TEXT
        for frame in frames
        if frame["type"] == "content_block_delta"
    )


def test_streaming_responses_request_ends_with_the_complete_response() -> None:
    frames = _sse(
        {"input": [{"role": "user", "content": "hi"}]},
        protocol_plugin="openai-responses",
    )

    assert frames[0]["type"] == "response.created"
    assert frames[0]["response"]["output"] == []
    assert frames[-1]["type"] == "response.completed"
    assert frames[-1]["response"]["output"][0]["type"] == "message"


_FORMAT_INSTRUCTIONS = """The output should be formatted as a JSON instance that conforms to the JSON schema below.

As an example, for the schema {"properties": {"foo": {"title": "Foo", "type": "array"}}, "required": ["foo"]} the object {"foo": ["bar"]} is well-formatted.

Here is the output schema:
```
{"properties": {"title": {"type": "string"}, "steps": {"items": {"type": "string"}, "type": "array"}}, "required": ["title", "steps"]}
```"""


def test_prompt_embedded_schema_is_answered_with_shaped_json() -> None:
    """LangChain output parsers state the contract in the prompt, not the request.

    ``JsonOutputParser`` tells the model to emit JSON and parses the reply
    afterwards, so nothing in the request body declares it. Against canned text
    those agents fail with OutputParserException.
    """

    body = _reply(
        {
            "messages": [
                {"role": "system", "content": _FORMAT_INSTRUCTIONS},
                {"role": "user", "content": "plan the change"},
            ]
        }
    )

    content = json.loads(body["choices"][0]["message"]["content"])

    assert content == {"title": OFFLINE_TEXT, "steps": [OFFLINE_TEXT]}


def test_prompt_embedded_schema_ignores_the_illustrative_example() -> None:
    """The instructions also contain an inline example schema, unfenced.

    Picking the first `{"properties"` in the text would answer with the
    example's shape instead of the real one.
    """

    body = _reply({"messages": [{"role": "user", "content": _FORMAT_INSTRUCTIONS}]})

    assert "foo" not in json.loads(body["choices"][0]["message"]["content"])


def test_prompt_without_the_sentinel_is_left_alone() -> None:
    body = _reply(
        {
            "messages": [
                {
                    "role": "user",
                    "content": 'Return JSON like {"properties": {"a": {"type": "string"}}}',
                }
            ]
        }
    )

    assert body["choices"][0]["message"]["content"] == OFFLINE_TEXT


def test_a_declared_tool_still_wins_over_a_prompt_schema() -> None:
    body = _reply(
        {
            "messages": [{"role": "user", "content": _FORMAT_INSTRUCTIONS}],
            "tools": [
                {"type": "function", "function": {"name": "search", "parameters": {}}}
            ],
        }
    )

    assert body["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.parametrize(
    ("protocol_plugin", "payload_key"),
    [("openai-responses", "input"), ("anthropic-messages", "messages")],
)
def test_prompt_embedded_schema_is_honoured_on_every_protocol(
    protocol_plugin: str, payload_key: str
) -> None:
    body = _reply(
        {payload_key: [{"role": "user", "content": _FORMAT_INSTRUCTIONS}]},
        protocol_plugin=protocol_plugin,
    )

    text = (
        body["output"][0]["content"][0]["text"]
        if protocol_plugin == "openai-responses"
        else body["content"][0]["text"]
    )

    assert json.loads(text) == {"title": OFFLINE_TEXT, "steps": [OFFLINE_TEXT]}


def test_array_placeholders_carry_one_element() -> None:
    """An empty list satisfies the schema but breaks agents that read items[0]."""

    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "plan",
                        "parameters": {
                            "type": "object",
                            "required": ["steps"],
                            "properties": {
                                "steps": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["action"],
                                        "properties": {"action": {"type": "string"}},
                                    },
                                }
                            },
                        },
                    },
                }
            ],
        }
    )

    call = body["choices"][0]["message"]["tool_calls"][0]["function"]
    arguments = json.loads(call["arguments"])

    assert arguments["steps"] == [{"action": OFFLINE_TEXT}]


def test_deeply_nested_schema_placeholders_are_bounded() -> None:
    """The array placeholder recurses, so nesting must terminate."""

    node: dict[str, object] = {"type": "string"}
    for _ in range(12):
        node = {"type": "array", "items": node}

    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "deep",
                        "parameters": {
                            "type": "object",
                            "required": ["tree"],
                            "properties": {"tree": node},
                        },
                    },
                }
            ],
        }
    )

    value = json.loads(
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )["tree"]

    depth = 0
    while isinstance(value, list) and value:
        depth += 1
        value = value[0]

    assert depth <= 12


def test_nested_model_refs_are_resolved() -> None:
    """Pydantic emits nested models as $ref into $defs.

    Without resolving them a nested object looks untyped and gets a string
    placeholder, which then fails the agent's own validation.
    """

    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "plan",
                        "parameters": {
                            "$defs": {
                                "Task": {
                                    "type": "object",
                                    "required": ["action"],
                                    "properties": {"action": {"type": "string"}},
                                }
                            },
                            "type": "object",
                            "required": ["tasks"],
                            "properties": {
                                "tasks": {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/Task"},
                                }
                            },
                        },
                    },
                }
            ],
        }
    )

    arguments = json.loads(
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )

    assert arguments["tasks"] == [{"action": OFFLINE_TEXT}]


def test_optional_fields_answer_the_non_null_branch() -> None:
    body = _reply(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "maybe",
                        "parameters": {
                            "type": "object",
                            "required": ["count"],
                            "properties": {
                                "count": {
                                    "anyOf": [{"type": "integer"}, {"type": "null"}]
                                }
                            },
                        },
                    },
                }
            ],
        }
    )

    arguments = json.loads(
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )

    assert arguments == {"count": 0}


def test_non_streaming_request_still_gets_json() -> None:
    body = _reply({"messages": [{"role": "user", "content": "hi"}]})

    assert body["object"] == "chat.completion"


def test_offline_target_rejects_a_non_json_body() -> None:
    with pytest.raises(OfflineResponseError, match="valid UTF-8 JSON"):
        OFFLINE_MOCK_TARGET.build_response(
            b"not json", route=_route(), target=_target()
        )


def test_offline_target_keeps_the_agent_facing_host_and_path_in_the_trace() -> None:
    class FakeRequest:
        content = b'{"model": "gpt-4.1-mini"}'
        pretty_host = "api.openai.com"
        path = "/v1/chat/completions"

    prepared = OFFLINE_MOCK_TARGET.prepare_request(
        FakeRequest(), route=_route(), target=_target()
    )

    assert prepared.host == "api.openai.com"
    assert prepared.path == "/v1/chat/completions"
    assert prepared.source_model == "gpt-4.1-mini"
    assert prepared.target_model == "offline-verify-model"


def test_offline_target_rejects_an_unsupported_source_protocol() -> None:
    from defuzex_model_interceptor.targets import TargetRoutingError

    class FakeRequest:
        content = b"{}"
        pretty_host = "api.openai.com"
        path = "/v1/embeddings"

    with pytest.raises(TargetRoutingError, match="does not support source protocol"):
        OFFLINE_MOCK_TARGET.prepare_request(
            FakeRequest(), route=_route("json-http"), target=_target()
        )
