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
