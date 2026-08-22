from pathlib import Path

import pytest

from agentbench.runtime.interception import (
    InterceptionConfig,
    InterceptionConfigurationError,
    InterceptionTraceState,
    OpenRouterProvider,
    TraceEvent,
    get_trust_plugin,
)


def _write_manifest(root: Path, body: str) -> Path:
    root.mkdir()
    root.joinpath("agent.toml").write_text(body, encoding="utf-8")
    return root


def test_manifest_v2_loads_provider_neutral_interception_contract(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path / "agent",
        '''
schema_version = "defuzex-bench.agent.v2"

[llm_interception]
required = true
trust_plugin = "pem-env"

[llm_interception.environment]
MODEL_ENDPOINT = "https://models.example/v1"
MODEL_NAME = "example-model"

[[llm_interception.credentials]]
id = "primary"
agent_env = "AGENT_MODEL_TOKEN"
auth_plugin = "bearer-token"

[[llm_interception.routes]]
id = "primary-model"
host_patterns = ["models.example", "*.models.example"]
ports = [443]
methods = ["post"]
path_patterns = ["/v1/chat/*", "/v1/responses"]
protocol_plugin = "json-http"
credential = "primary"
''',
    )

    config = InterceptionConfig.from_agent_dir(root)

    assert config is not None
    assert config.environment["MODEL_NAME"] == "example-model"
    assert config.credentials[0].agent_env == "AGENT_MODEL_TOKEN"
    assert config.routes[0].matches(
        host="edge.models.example",
        port=443,
        method="POST",
        path="/v1/chat/completions",
    )


def test_interception_requires_manifest_v2(tmp_path: Path) -> None:
    root = _write_manifest(
        tmp_path / "agent",
        '''
schema_version = "defuzex-bench.agent.v1"
[llm_interception]
trust_plugin = "pem-env"
''',
    )

    with pytest.raises(InterceptionConfigurationError, match="agent.v2"):
        InterceptionConfig.from_agent_dir(root)


@pytest.mark.parametrize("pattern", ["*", "api.*.example", "api?.example", "[a].example"])
def test_interception_rejects_unsafe_host_patterns(
    tmp_path: Path, pattern: str
) -> None:
    root = _write_manifest(
        tmp_path / "agent",
        f'''
schema_version = "defuzex-bench.agent.v2"
[llm_interception]
trust_plugin = "pem-env"
[[llm_interception.credentials]]
id = "primary"
agent_env = "AGENT_TOKEN"
auth_plugin = "bearer-token"
[[llm_interception.routes]]
id = "route"
host_patterns = ["{pattern}"]
methods = ["POST"]
path_patterns = ["/v1/*"]
protocol_plugin = "json-http"
credential = "primary"
''',
    )

    with pytest.raises(InterceptionConfigurationError, match="pattern|wildcard"):
        InterceptionConfig.from_agent_dir(root)


def test_pem_trust_plugin_declares_common_ca_environment() -> None:
    environment = get_trust_plugin("pem-env").agent_environment("/run/ca.pem")

    assert environment["SSL_CERT_FILE"] == "/run/ca.pem"
    assert environment["REQUESTS_CA_BUNDLE"] == "/run/ca.pem"
    assert environment["NODE_EXTRA_CA_CERTS"] == "/run/ca.pem"


def test_openrouter_provider_resolves_run_model_and_environment() -> None:
    target = OpenRouterProvider(model="openai/gpt-4.1-mini").resolve(
        {
            "OPENROUTER_API_KEY": "not-read-by-provider",
            "OPENROUTER_MODEL": "ignored/model",
            "OPENROUTER_APP_TITLE": "AgentBench",
        }
    )

    assert target.provider_id == "openrouter"
    assert target.target_plugin == "openrouter"
    assert target.model == "openai/gpt-4.1-mini"
    assert target.credential_env == "OPENROUTER_API_KEY"
    assert target.headers["X-OpenRouter-Title"] == "AgentBench"


def test_openrouter_provider_requires_a_model() -> None:
    with pytest.raises(InterceptionConfigurationError, match="--model"):
        OpenRouterProvider().resolve({"OPENROUTER_API_KEY": "secret"})


def test_trace_event_parser_ignores_non_trace_logs_and_bad_json() -> None:
    assert TraceEvent.from_log_line("mitmproxy started") is None
    assert TraceEvent.from_log_line("DEFUZEX_TRACE nope") is None

    event = TraceEvent.from_log_line(
        'DEFUZEX_TRACE {"event":"llm_request","call_id":"call-1"}'
    )

    assert event is not None
    assert event.event == "llm_request"
    assert event.data["call_id"] == "call-1"


def test_trace_state_requires_a_matching_request_and_response() -> None:
    state = InterceptionTraceState()
    checkpoint = state.checkpoint()

    state.emit(TraceEvent("llm_request", {"call_id": "call-1"}))
    assert not state.wait_for_completion_after(checkpoint, timeout=0)

    state.emit(TraceEvent("llm_response", {"call_id": "call-1"}))
    assert state.wait_for_completion_after(checkpoint, timeout=0)
