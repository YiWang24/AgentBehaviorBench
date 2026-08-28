from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.cli.features.verify import verify
from agentbench.cli.main import cli
from agentbench.cli.verify_runtime import (
    OFFLINE_TARGET_PLUGIN,
    OFFLINE_UPSTREAM_KEY_ENV,
    VerifyRuntime,
    build_verify_runtime,
)
from agentbench.harness import (
    AgentRegistration,
    BenchmarkSuiteResult,
    SuiteAgentResult,
    SuiteConfigurationError,
)
from agentbench.harness.offline import (
    OfflineSecretResolver,
    StartupCaseProvider,
    StartupJudgeProvider,
)
from agentbench.cli.presentation import ANSI_PATTERN
from agentbench.cli.TerminalUI.call_log import CallRecorder
from agentbench.harness.runner.benchmark_runner import BenchmarkRunner
from agentbench.cli.TerminalUI import LLMActivity
from agentbench.runtime.interception import (
    InterceptionTraceState,
    TerminalTraceSink,
    TraceEvent,
)
from tests.test_cli import FakeSuiteRunner

DOCKER_AGENT_ID = "langgraph-customer-support-agent"
IN_PROCESS_AGENT_ID = "langgraph-new-project"


def _trace_state(pairs: int) -> InterceptionTraceState:
    state = InterceptionTraceState()
    for index in range(pairs):
        call_id = f"call_{index}"
        state.emit(TraceEvent("llm_request", {"call_id": call_id}))
        state.emit(TraceEvent("llm_response", {"call_id": call_id}))
    return state


def _offline(
    *,
    pairs: int = 1,
    runner: object | None = None,
    resolver: OfflineSecretResolver | None = None,
) -> VerifyRuntime:
    return VerifyRuntime(
        runner=runner or FakeSuiteRunner(),  # type: ignore[arg-type]
        trace_state=_trace_state(pairs),
        secret_resolver=resolver or OfflineSecretResolver({}),
        call_recorder=CallRecorder(),
    )


def _registry_path(repo_root: Path) -> Path:
    return repo_root / "resources" / "registry.toml"


def _plain(text: str) -> str:
    return ANSI_PATTERN.sub("", text).strip()


def _verdict_line(output: list[str]) -> str:
    """The PASS/FAIL verdict, rejoined when a long reason wrapped across lines."""

    collected: list[str] = []
    for line in output:
        text = _plain(line)
        if not collected:
            if text.startswith(("PASS", "FAIL")):
                collected.append(text)
            continue
        if not text or text.startswith("log "):
            break
        collected.append(text)
    if not collected:
        raise AssertionError(f"no verdict line in {[_plain(line) for line in output]}")
    return " ".join(collected)


def _json_report(output: list[str]) -> dict:
    return json.loads("\n".join(output))


# --- argument dispatch -------------------------------------------------------


def test_cli_dispatches_verify_with_defaults(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_verify(agent_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((agent_id, kwargs))
        return 0

    monkeypatch.setattr("agentbench.cli.features.verify.verify", fake_verify)

    assert cli(["verify", "test-agent"]) == 0
    assert calls == [("test-agent", {"input_count": 1, "keep_artifacts": False})]


def test_cli_dispatches_verify_options(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_verify(agent_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((agent_id, kwargs))
        return 3

    monkeypatch.setattr("agentbench.cli.features.verify.verify", fake_verify)

    exit_code = cli(
        [
            "verify",
            "test-agent",
            "--input",
            "ping",
            "--inputs",
            "2",
            "--keep-artifacts",
            "--llm-trace",
            "terminal",
            "--llm-trace-max-bytes",
            "4096",
        ]
    )

    assert exit_code == 3
    assert calls == [
        (
            "test-agent",
            {
                "input_count": 2,
                "keep_artifacts": True,
                "probe_text": "ping",
                "llm_trace": "terminal",
                "llm_trace_max_bytes": 4096,
            },
        )
    ]


def test_cli_dispatches_a_live_model_source(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "agentbench.cli.features.verify.verify",
        lambda agent_id, **kwargs: calls.append(kwargs) or 0,  # type: ignore[func-returns-value]
    )

    cli(
        [
            "verify",
            "test-agent",
            "--model-source",
            "deepseek",
            "--model",
            "deepseek-reasoner",
        ]
    )

    assert calls[0]["model_source"] == "deepseek"
    assert calls[0]["model"] == "deepseek-reasoner"


def test_cli_omits_the_model_source_when_it_is_the_offline_default(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "agentbench.cli.features.verify.verify",
        lambda agent_id, **kwargs: calls.append(kwargs) or 0,  # type: ignore[func-returns-value]
    )

    cli(["verify", "test-agent"])

    assert "model_source" not in calls[0]


def test_a_misconfigured_model_source_is_reported_as_an_error(
    monkeypatch, repo_root: Path
) -> None:
    """A missing provider key is the caller's mistake, not a verdict on the Agent."""

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        model_source="deepseek",
    )

    assert exit_code == 2
    assert "DEEPSEEK_API_KEY" in output[-1]


def test_cli_reads_probe_text_from_a_file(monkeypatch, tmp_path: Path) -> None:
    probe = tmp_path / "probe.txt"
    probe.write_text("from a file", encoding="utf-8")
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "agentbench.cli.features.verify.verify",
        lambda agent_id, **kwargs: calls.append(kwargs) or 0,  # type: ignore[func-returns-value]
    )

    cli(["verify", "test-agent", "--input", f"@{probe}"])

    assert calls[0]["probe_text"] == "from a file"


# --- preflight rejections ----------------------------------------------------


def test_unregistered_agent_is_rejected(repo_root: Path) -> None:
    output: list[str] = []

    exit_code = verify(
        "not-a-real-agent",
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(),
    )

    assert exit_code == 2
    assert "not registered" in output[-1]


def test_in_process_agent_is_rejected(repo_root: Path) -> None:
    """Without the Docker runtime there is no interceptor to observe."""

    output: list[str] = []

    exit_code = verify(
        IN_PROCESS_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(),
    )

    assert exit_code == 2
    assert "Docker runtime" in output[-1]


def test_zero_inputs_is_rejected(repo_root: Path) -> None:
    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        input_count=0,
        output_fn=output.append,
        offline=_offline(),
    )

    assert exit_code == 2
    assert "--inputs" in output[-1]


# --- verdicts ----------------------------------------------------------------


def test_verification_passes_when_the_agent_runs_and_traffic_is_captured(
    repo_root: Path,
) -> None:
    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=2),
    )

    assert exit_code == 0
    verdict = _verdict_line(output)
    assert verdict.startswith("PASS")
    assert "1/1 cases" in verdict
    assert "2 model request/response pairs captured" in verdict


def test_verification_fails_when_no_model_call_is_captured(repo_root: Path) -> None:
    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=0),
    )

    assert exit_code == 1
    assert "not observable" in _verdict_line(output)


class _FailingSuiteRunner:
    """Report an Agent that raised before completing its Case."""

    def __init__(self, error_type: str = "AgentStartError") -> None:
        self.error_type = error_type

    @staticmethod
    def new_suite_id() -> str:
        return "suite_verify_failure"

    def run_defuzex(self, agents, **kwargs):  # type: ignore[no-untyped-def]
        selected = tuple(agents)
        return BenchmarkSuiteResult(
            suite_id=str(kwargs["suite_id"]),
            selected_agent_ids=tuple(agent.agent_id for agent in selected),
            items=tuple(
                SuiteAgentResult(
                    agent_id=agent.agent_id,
                    requested_case_count=agent.case_count,
                    error_type=self.error_type,
                    error_message="container exited during startup",
                )
                for agent in selected
            ),
        )


def test_verification_fails_when_the_agent_cannot_start(repo_root: Path) -> None:
    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=1, runner=_FailingSuiteRunner()),
    )

    assert exit_code == 1
    verdict = _verdict_line(output)
    assert verdict.startswith("FAIL")
    assert "AgentStartError" in verdict


def test_a_non_passing_sdk_judgment_fails_verification(repo_root: Path) -> None:
    """The SDK Judge owns the verdict now that a real local Judge produces it.

    The local Judge only ever reports an issue when an Input went unanswered, so
    its rejection is a startup failure rather than an opinion about quality.
    """

    output: list[str] = []

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=1, runner=FakeSuiteRunner(result_status="issue")),
    )

    assert exit_code == 1
    verdict = _verdict_line(output)
    assert verdict.startswith("FAIL")
    assert "issue" in verdict


def test_a_passing_run_reports_the_sdk_judge_status(repo_root: Path) -> None:
    output: list[str] = []

    verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=1),
        as_json=True,
    )

    assert _json_report(output)["sdk_judge_status"] == "pass"


def test_shared_configuration_failure_fails_verification(repo_root: Path) -> None:
    output: list[str] = []
    runner = FakeSuiteRunner(error=SuiteConfigurationError("docker unavailable"))

    exit_code = verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(pairs=0, runner=runner),
    )

    assert exit_code == 1
    assert _verdict_line(output).startswith("FAIL")


def test_substituted_secrets_are_reported(repo_root: Path) -> None:
    resolver = OfflineSecretResolver({})
    resolver.require("SOME_AGENT_SECRET")
    output: list[str] = []

    verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(resolver=resolver),
    )

    assert any("SOME_AGENT_SECRET" in line for line in output)


def test_verification_never_writes_the_registry(repo_root: Path) -> None:
    registry_path = _registry_path(repo_root)
    before = registry_path.read_bytes()

    verify(
        DOCKER_AGENT_ID,
        registry_path=registry_path,
        output_fn=lambda _: None,
        offline=_offline(),
    )

    assert registry_path.read_bytes() == before


# --- artifacts ---------------------------------------------------------------


def test_result_log_is_deleted_unless_kept(repo_root: Path) -> None:
    output: list[str] = []

    verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        offline=_offline(),
        as_json=True,
    )

    report = _json_report(output)
    assert report["result_log"] is None
    assert not any("agentbench-verify-" in _plain(line) for line in output)


def test_kept_result_log_survives_and_holds_the_suite_summary(repo_root: Path) -> None:
    output: list[str] = []

    verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        keep_artifacts=True,
        output_fn=output.append,
        offline=_offline(),
        as_json=True,
    )

    path = Path(_json_report(output)["result_log"])
    try:
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert events[-1]["event"] == "suite_completed"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_kept_result_log_path_is_shown_in_the_human_report(repo_root: Path) -> None:
    output: list[str] = []

    verify(
        DOCKER_AGENT_ID,
        registry_path=_registry_path(repo_root),
        keep_artifacts=True,
        output_fn=output.append,
        offline=_offline(),
    )

    logged = [_plain(line) for line in output if _plain(line).startswith("log ")]
    assert len(logged) == 1
    path = Path(logged[0].removeprefix("log").strip())
    try:
        assert path.is_file()
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


# --- credential isolation ----------------------------------------------------


class _PoisonedEnviron(dict):
    """Fail loudly if provider credentials are consulted."""

    FORBIDDEN = ("DEFUZEX_API_KEY", "OPENROUTER_API_KEY")

    def get(self, key, default=None):  # type: ignore[no-untyped-def]
        if key in self.FORBIDDEN:
            raise AssertionError(f"Offline verification read {key}")
        return super().get(key, default)


def test_local_provider_mode_never_consults_provider_credentials(
    starter_agent: AgentRegistration,
) -> None:
    runner = BenchmarkRunner(
        environ=_PoisonedEnviron(),
        sdk_run_factory=lambda **kwargs: None,  # type: ignore[arg-type, return-value]
    )

    mode = runner.validate_defuzex(
        starter_agent,
        case_provider=StartupCaseProvider(),
        judge_provider=StartupJudgeProvider(),
        max_inputs=1,
        allow_local=True,
        track_files=False,
    )

    assert mode == "local"


def test_official_mode_would_have_tripped_the_poisoned_environment(
    starter_agent: AgentRegistration,
) -> None:
    """Guards the test above: the tripwire really does fire without local providers."""

    runner = BenchmarkRunner(
        environ=_PoisonedEnviron(),
        sdk_run_factory=lambda **kwargs: None,  # type: ignore[arg-type, return-value]
    )

    with pytest.raises(AssertionError, match="read DEFUZEX_API_KEY"):
        runner.validate_defuzex(starter_agent, allow_local=True, track_files=False)


def test_requested_llm_trace_reaches_output_when_no_live_panel_owns_the_terminal() -> None:
    """A silenced live panel must not swallow a trace the caller asked for."""

    written: list[str] = []
    silent_panel = LLMActivity(lambda _: None, live_updates=False)

    build_verify_runtime(
        max_inputs=1,
        probe_text="ping",
        output_fn=written.append,
        llm_trace="terminal",
        activity_sink=silent_panel,
    )
    # The composite sink is what the runtime hands to Docker; drive it directly.
    _emit_trace_event(written)

    assert any("LLM TRACE" in line for line in written)


def _emit_trace_event(written: list[str]) -> None:
    from agentbench.cli.verify_runtime import _trace_output

    silent_panel = LLMActivity(lambda _: None, live_updates=False)
    TerminalTraceSink(_trace_output(silent_panel, written.append)).emit(
        TraceEvent(
            "llm_request",
            {
                "call_id": "call-1",
                "route_id": "openai-chat",
                "provider": "offline",
                "method": "POST",
                "host": "api.openai.com",
                "path": "/v1/chat/completions",
            },
        )
    )


def test_offline_runtime_targets_the_offline_plugin_with_a_synthetic_credential(
    monkeypatch,
) -> None:
    monkeypatch.delenv(OFFLINE_UPSTREAM_KEY_ENV, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    offline = build_verify_runtime(
        max_inputs=1,
        probe_text="ping",
        output_fn=lambda _: None,
    )
    docker_runtime = offline.runner._benchmark_runner._agent_runner._runtime_factory._docker_builder()
    target = docker_runtime._model_provider.resolve({})

    assert target.target_plugin == OFFLINE_TARGET_PLUGIN
    assert target.credential_env == OFFLINE_UPSTREAM_KEY_ENV
    assert docker_runtime._egress == "blocked"
    # The synthetic upstream credential resolves without touching real config.
    assert docker_runtime._secret_resolver.require(OFFLINE_UPSTREAM_KEY_ENV)
    assert offline.substituted_secrets == ()
