from __future__ import annotations

import pytest

from agentbench.harness import AgentRegistration
from agentbench.harness.offline import (
    DEFAULT_PROBE_TEXT,
    OfflineCaseProvider,
    OfflineJudgeProvider,
    OfflineRunFactory,
    OfflineSdkRun,
    OfflineSecretResolver,
    OfflineSuiteRunner,
    probe_inputs,
)
from agentbench.harness.offline.secrets import PLACEHOLDER_PREFIX
from agentbench.harness.protocols import SDKRun
from tests.support.results import benchmark_result
from tests.test_suite_runner import FakeBenchmarkRunner


def _drain(run: OfflineSdkRun) -> list[str]:
    """Consume every probe the way BenchmarkRunner does."""

    ids: list[str] = []
    while (test_input := run.get_input(full=True)) is not None:
        ids.append(test_input.input_id)
        run.submit({"reply": "ok"})
    return ids


def test_offline_run_satisfies_the_sdk_run_protocol() -> None:
    run: SDKRun = OfflineSdkRun()  # type: ignore[assignment]

    assert run.run_id.startswith("offline_")
    assert callable(run.get_input)
    assert callable(run.submit)


def test_offline_run_yields_every_probe_then_stops() -> None:
    run = OfflineSdkRun(probes=probe_inputs("ping", count=3))

    assert _drain(run) == [
        "offline-probe-1",
        "offline-probe-2",
        "offline-probe-3",
    ]
    assert run.get_input(full=True) is None
    assert len(run.history) == 3


def test_completed_run_reports_pass_and_completed_state() -> None:
    run = OfflineSdkRun(probes=probe_inputs(count=2))
    _drain(run)

    assert run.state == "completed"
    assert run.report.status == "pass"
    assert run.report.issues == ()


def test_run_is_still_running_before_every_probe_is_submitted() -> None:
    run = OfflineSdkRun(probes=probe_inputs(count=2))
    run.get_input(full=True)
    run.submit({"reply": "ok"})

    assert run.state == "running"
    assert run.report.status == "fail"
    assert "1 of 2" in str(run.report.issues[0])


def test_failed_submission_marks_the_run_failed() -> None:
    run = OfflineSdkRun()
    run.get_input(full=True)
    run.submit(status="failed", error="Agent invocation failed: DockerSessionError")

    assert run.state == "failed"
    assert run.report.status == "fail"
    assert run.report.issues == ("Agent invocation failed: DockerSessionError",)


def test_probe_payload_defaults_to_the_shared_prompt() -> None:
    run = OfflineSdkRun()
    test_input = run.get_input(full=True)

    assert test_input is not None
    assert test_input.payload == DEFAULT_PROBE_TEXT


def test_empty_probe_sets_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one probe"):
        OfflineSdkRun(probes=())
    with pytest.raises(ValueError, match="at least one probe"):
        probe_inputs(count=0)


def test_run_factory_creates_one_run_per_case_and_ignores_sdk_arguments() -> None:
    factory = OfflineRunFactory(probes=probe_inputs("ping", count=2))

    first = factory(repo_path="/tmp/agent", allow_local=True, max_inputs=2)
    second = factory(repo_path="/tmp/agent", allow_local=True, max_inputs=2)

    assert first is not second
    assert factory.created == [first, second]
    assert first.get_input(full=True).payload == "ping"  # type: ignore[union-attr]


def test_offline_secret_resolver_prefers_real_values() -> None:
    resolver = OfflineSecretResolver({"REAL_KEY": "actual-value"})

    assert resolver.require("REAL_KEY") == "actual-value"
    assert resolver.substituted == ()


def test_offline_secret_resolver_substitutes_and_records_missing_values() -> None:
    resolver = OfflineSecretResolver({"BLANK": "   "})

    # The marker is embedded rather than leading: placeholders carry the
    # prefix of the credential family they replace, so agents that validate
    # key shape accept them.
    assert PLACEHOLDER_PREFIX in resolver.require("MISSING")
    assert PLACEHOLDER_PREFIX in resolver.require("BLANK")
    assert PLACEHOLDER_PREFIX in resolver.require("MISSING")
    assert resolver.substituted == ("MISSING", "BLANK")


def test_offline_placeholders_are_shaped_like_the_credential_they_replace() -> None:
    """Agents guard on key shape; a placeholder that fails the guard reports a
    configuration error the deployment does not have."""

    resolver = OfflineSecretResolver({})

    openai_key = resolver.require("OPENAI_API_KEY")
    assert openai_key.startswith("sk-")
    assert PLACEHOLDER_PREFIX in openai_key

    anthropic_key = resolver.require("ANTHROPIC_API_KEY")
    assert anthropic_key.startswith("sk-ant-api03-")
    # sk-ant- keys also satisfy the looser sk- guard.
    assert anthropic_key.startswith("sk-")

    # A non-key secret still gets an identifiable placeholder.
    other = resolver.require("SOME_ENDPOINT")
    assert PLACEHOLDER_PREFIX in other
    assert "some_endpoint" in other


def test_offline_suite_runner_forces_local_providers_and_drops_the_api_key(
    enabled_agents: tuple[AgentRegistration, ...],
) -> None:
    agents = enabled_agents[:1]
    fake = FakeBenchmarkRunner(
        {agent.agent_id: benchmark_result(agent.agent_id) for agent in agents}
    )

    OfflineSuiteRunner(benchmark_runner=fake, max_inputs=3).run_defuzex(  # type: ignore[arg-type]
        agents,
        api_key="dfx_should_be_ignored",
        allow_local=True,
    )

    _, kwargs = fake.calls[0]
    assert kwargs["api_key"] is None
    assert kwargs["max_inputs"] == 3
    assert isinstance(kwargs["case_provider"], OfflineCaseProvider)
    assert isinstance(kwargs["judge_provider"], OfflineJudgeProvider)
    assert kwargs["track_files"] is False
    assert kwargs["save_local"] is False


def test_offline_suite_runner_rejects_an_empty_input_budget() -> None:
    with pytest.raises(ValueError, match="at least one input"):
        OfflineSuiteRunner(max_inputs=0)
