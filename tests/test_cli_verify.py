"""`verify` end to end: the three phases, and where each one stops."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from agentbench.adapter import AdapterInvocation
from agentbench.cli.features.verify import verify
from agentbench.cli.main import cli
from agentbench.cli.presentation import ANSI_PATTERN
from agentbench.cli.TerminalUI.call_log import CallRecord, CallRecorder
from agentbench.cli.verify_report import (
    PROVIDERS_READY,
    PROVIDERS_SKIPPED,
    PROVIDERS_UNAVAILABLE,
)
from agentbench.cli.verify_runtime import VerifyOptions
from agentbench.harness import (
    AgentRegistration,
    BenchmarkSuiteResult,
    RunningAgent,
    SuiteAgentResult,
    SuiteConfigurationError,
)
from agentbench.runtime.contracts import OfflineSecretResolver
from agentbench.runtime.interception import InterceptionTraceState, TraceEvent
from tests.test_cli import FakeSuiteRunner

DOCKER_AGENT_ID = "langgraph-customer-support-agent"
IN_PROCESS_AGENT_ID = "langgraph-new-project"

LIVE_ENV = {"DEEPSEEK_API_KEY": "sk-not-a-real-key"}


# --- test doubles ------------------------------------------------------------


class _FakeAdapter:
    """An Agent that answers every probe, unless told to misbehave."""

    def __init__(
        self, *, outputs: list[object] | None = None, error: Exception | None = None
    ) -> None:
        self._outputs = outputs
        self._error = error
        self.is_loaded = True
        self.invocations: list[object] = []

    def load(self) -> "_FakeAdapter":
        return self

    def invoke(self, value: object, *, run_config: object | None = None):
        self.invocations.append(value)
        if self._error is not None:
            raise self._error
        output = self._outputs.pop(0) if self._outputs else "a reply"
        return AdapterInvocation(output=output, raw_output=output)

    def close(self) -> None:
        self.is_loaded = False


class _FakeAgentRunner:
    def __init__(
        self, adapter: _FakeAdapter | None = None, error: Exception | None = None
    ) -> None:
        self.adapter = adapter or _FakeAdapter()
        self.error = error
        self.starts = 0

    def start(self, agent: AgentRegistration) -> RunningAgent:
        self.starts += 1
        if self.error is not None:
            raise self.error
        return RunningAgent(registration=agent, adapter=self.adapter)  # type: ignore[arg-type]


@dataclass
class _FakeRuntime:
    """The two stacks and the shared observation handles, without Docker."""

    options: VerifyOptions
    environ: Mapping[str, str]
    trace_state: InterceptionTraceState
    agent_runner: _FakeAgentRunner
    secret_resolver: OfflineSecretResolver
    call_recorder: CallRecorder = field(default_factory=CallRecorder)
    suite: object | None = None
    suites_built: int = 0

    @property
    def captured_pair_count(self) -> int:
        return self.trace_state.checkpoint()

    @property
    def calls(self) -> tuple[CallRecord, ...]:
        return tuple(self.call_recorder.records)

    @property
    def substituted_secrets(self) -> tuple[str, ...]:
        return self.secret_resolver.substituted

    def preflight_runner(self) -> _FakeAgentRunner:
        return self.agent_runner

    def benchmark_suite_runner(self, chat: object) -> object:
        self.suites_built += 1
        return self.suite or FakeSuiteRunner()


def _trace_state(pairs: int) -> InterceptionTraceState:
    state = InterceptionTraceState()
    for index in range(pairs):
        call_id = f"call_{index}"
        state.emit(TraceEvent("llm_request", {"call_id": call_id}))
        state.emit(TraceEvent("llm_response", {"call_id": call_id}))
    return state


def _runtime(
    *,
    options: VerifyOptions | None = None,
    pairs: int = 1,
    adapter: _FakeAdapter | None = None,
    start_error: Exception | None = None,
    environ: Mapping[str, str] | None = None,
    suite: object | None = None,
    resolver: OfflineSecretResolver | None = None,
) -> _FakeRuntime:
    return _FakeRuntime(
        options=options or VerifyOptions(),
        environ=LIVE_ENV if environ is None else environ,
        trace_state=_trace_state(pairs),
        agent_runner=_FakeAgentRunner(adapter, start_error),
        secret_resolver=resolver or OfflineSecretResolver({}),
        suite=suite,
    )


def _registry_path(repo_root: Path) -> Path:
    return repo_root / "resources" / "registry.toml"


def _plain(text: str) -> str:
    return ANSI_PATTERN.sub("", text).strip()


VERDICT_BADGES = {"PASS", "PARTIAL", "FAIL"}


def _verdict_line(output: list[str]) -> str:
    """The verdict, rejoined when a long reason wrapped across lines.

    Matched on the whole badge, not a prefix: a failed stage line reads
    ``FAILED | ...`` and would otherwise be mistaken for the verdict.
    """

    collected: list[str] = []
    for line in output:
        text = _plain(line)
        if not collected:
            if text.split(" ")[0] in VERDICT_BADGES:
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


def _run(repo_root: Path, runtime: _FakeRuntime, **kwargs):  # type: ignore[no-untyped-def]
    output: list[str] = []
    exit_code = verify(
        DOCKER_AGENT_ID,
        options=runtime.options,
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        runtime=runtime,  # type: ignore[arg-type]
        **kwargs,
    )
    return exit_code, output


# --- argument dispatch -------------------------------------------------------


def _dispatched(monkeypatch) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    """Replace `verify` with a recorder, and return the calls it collects."""

    calls: list[dict[str, object]] = []

    def record(agent_id: str, **kwargs: object) -> int:
        calls.append({"agent_id": agent_id, **kwargs})
        return 0

    monkeypatch.setattr("agentbench.cli.features.verify.verify", record)
    return calls


def test_cli_dispatches_verify_with_defaults(monkeypatch) -> None:
    calls = _dispatched(monkeypatch)

    assert cli(["verify", "test-agent"]) == 0
    assert calls[0]["agent_id"] == "test-agent"
    assert calls[0]["options"] == VerifyOptions(probe_count=1, input_count=3)
    assert calls[0]["output_path"] is None
    assert calls[0]["as_json"] is False


def test_cli_separates_preflight_probes_from_benchmark_inputs(monkeypatch) -> None:
    """The two counts answer different questions and must not share a flag."""

    calls = _dispatched(monkeypatch)

    cli(["verify", "test-agent", "--probes", "4", "--inputs", "7"])

    options = calls[0]["options"]
    assert (options.probe_count, options.input_count) == (4, 7)


def test_cli_dispatches_the_remaining_options(monkeypatch) -> None:
    calls = _dispatched(monkeypatch)

    cli(
        [
            "verify",
            "test-agent",
            "--input",
            "ping",
            "--preflight-only",
            "--model",
            "deepseek-reasoner",
            "--provider-model",
            "deepseek-chat",
            "--llm-trace",
            "terminal",
            "--llm-trace-max-bytes",
            "4096",
        ]
    )

    assert calls[0]["options"] == VerifyOptions(
        probe_count=1,
        input_count=3,
        probe_text="ping",
        model="deepseek-reasoner",
        provider_model="deepseek-chat",
        preflight_only=True,
        llm_trace="terminal",
        llm_trace_max_bytes=4096,
    )


def test_cli_reads_probe_text_from_a_file(monkeypatch, tmp_path: Path) -> None:
    probe = tmp_path / "probe.txt"
    probe.write_text("from a file", encoding="utf-8")
    calls = _dispatched(monkeypatch)

    cli(["verify", "test-agent", "--input", f"@{probe}"])

    assert calls[0]["options"].probe_text == "from a file"


# --- selection errors --------------------------------------------------------


def test_unregistered_agent_is_rejected(repo_root: Path) -> None:
    output: list[str] = []

    exit_code = verify(
        "not-a-real-agent",
        registry_path=_registry_path(repo_root),
        output_fn=output.append,
        runtime=_runtime(),  # type: ignore[arg-type]
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
        runtime=_runtime(),  # type: ignore[arg-type]
    )

    assert exit_code == 2
    assert "Docker runtime" in output[-1]


def test_zero_probes_is_rejected(repo_root: Path) -> None:
    exit_code, output = _run(repo_root, _runtime(options=VerifyOptions(probe_count=0)))

    assert exit_code == 2
    assert "--probes" in output[-1]


def test_zero_inputs_is_rejected(repo_root: Path) -> None:
    exit_code, output = _run(repo_root, _runtime(options=VerifyOptions(input_count=0)))

    assert exit_code == 2
    assert "--inputs" in output[-1]


# --- preflight ---------------------------------------------------------------


def test_preflight_probes_the_agent_the_requested_number_of_times(
    repo_root: Path,
) -> None:
    adapter = _FakeAdapter()
    runtime = _runtime(
        options=VerifyOptions(probe_count=3, probe_text="ping", preflight_only=True),
        adapter=adapter,
    )

    _run(repo_root, runtime)

    assert adapter.invocations == ["ping", "ping", "ping"]


def test_preflight_never_touches_the_sdk_or_the_benchmark_stack(
    repo_root: Path,
) -> None:
    """A missing SDK must not stop an Agent from being checked."""

    runtime = _runtime(options=VerifyOptions(preflight_only=True))

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 0
    assert runtime.suites_built == 0
    assert not any("PROVIDER CHECK" in _plain(line) for line in output)


def test_a_preflight_only_pass_reports_probes_rather_than_cases(
    repo_root: Path,
) -> None:
    options = VerifyOptions(probe_count=2, preflight_only=True)
    runtime = _runtime(options=options, pairs=2)

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 0
    verdict = _verdict_line(output)
    assert "preflight only" in verdict
    assert "2/2 probes answered" in verdict


def test_an_agent_that_cannot_start_fails_preflight(repo_root: Path) -> None:
    runtime = _runtime(start_error=RuntimeError("container exited during startup"))

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 1
    verdict = _verdict_line(output)
    assert verdict.startswith("FAIL")
    assert "container exited during startup" in verdict


def test_an_agent_that_raises_on_a_probe_fails_preflight(repo_root: Path) -> None:
    runtime = _runtime(adapter=_FakeAdapter(error=RuntimeError("worker died")))

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 1
    assert "worker died" in _verdict_line(output)


def test_an_empty_answer_fails_preflight(repo_root: Path) -> None:
    """Only genuinely absent output counts as unanswered."""

    runtime = _runtime(adapter=_FakeAdapter(outputs=["   "]))

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 1
    assert "no usable output" in _verdict_line(output)


def test_a_falsy_but_present_answer_still_counts(repo_root: Path) -> None:
    runtime = _runtime(
        options=VerifyOptions(preflight_only=True), adapter=_FakeAdapter(outputs=[0])
    )

    exit_code, _ = _run(repo_root, runtime)

    assert exit_code == 0


def test_uncaptured_model_traffic_fails_preflight(repo_root: Path) -> None:
    runtime = _runtime(pairs=0)

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 1
    assert "not observable" in _verdict_line(output)


def test_substituted_secrets_are_reported(repo_root: Path) -> None:
    resolver = OfflineSecretResolver({})
    resolver.require("SOME_AGENT_SECRET")
    runtime = _runtime(options=VerifyOptions(preflight_only=True), resolver=resolver)

    _, output = _run(repo_root, runtime)

    assert any("SOME_AGENT_SECRET" in line for line in output)


# --- provider check ----------------------------------------------------------


def test_a_missing_provider_credential_stops_without_failing(repo_root: Path) -> None:
    """Preflight passed; the gap is in the host, so the Agent is not blamed."""

    runtime = _runtime(environ={})

    exit_code, output = _run(repo_root, runtime)

    assert exit_code == 0
    assert runtime.suites_built == 0
    verdict = _verdict_line(output)
    assert verdict.startswith("PARTIAL")
    assert "DEEPSEEK_API_KEY" in verdict


def test_a_partial_run_records_why_it_stopped(repo_root: Path) -> None:
    runtime = _runtime(environ={})

    _, output = _run(repo_root, runtime, as_json=True)

    providers = _json_report(output)["providers"]
    assert providers["state"] == PROVIDERS_UNAVAILABLE
    assert "DEEPSEEK_API_KEY" in providers["reason"]


def test_a_preflight_only_run_marks_the_provider_check_skipped(
    repo_root: Path,
) -> None:
    runtime = _runtime(options=VerifyOptions(preflight_only=True))

    _, output = _run(repo_root, runtime, as_json=True)

    assert _json_report(output)["providers"]["state"] == PROVIDERS_SKIPPED


# --- benchmark ---------------------------------------------------------------


def test_a_graded_run_passes_and_names_both_models(
    repo_root: Path, tmp_path: Path
) -> None:
    runtime = _runtime()

    exit_code, output = _run(
        repo_root, runtime, output_path=tmp_path / "verify.jsonl", as_json=True
    )

    assert exit_code == 0
    report = _json_report(output)
    assert report["verdict"] == "pass"
    assert report["providers"]["state"] == PROVIDERS_READY
    assert report["providers"]["agent_model"]
    assert report["providers"]["provider_model"]
    assert report["benchmark"]["ran"] is True
    assert report["benchmark"]["sdk_judge_status"] == "pass"


def test_a_non_passing_judgment_fails_verification(
    repo_root: Path, tmp_path: Path
) -> None:
    """The SDK Judge owns the verdict once a real Case has been graded."""

    runtime = _runtime(suite=FakeSuiteRunner(result_status="issue"))

    exit_code, output = _run(repo_root, runtime, output_path=tmp_path / "verify.jsonl")

    assert exit_code == 1
    verdict = _verdict_line(output)
    assert verdict.startswith("FAIL")
    assert "issue" in verdict


def test_a_run_that_never_started_fails_verification(
    repo_root: Path, tmp_path: Path
) -> None:
    runtime = _runtime(suite=_FailingSuiteRunner())

    exit_code, output = _run(repo_root, runtime, output_path=tmp_path / "verify.jsonl")

    assert exit_code == 1
    assert "AgentStartError" in _verdict_line(output)


def test_shared_configuration_failure_fails_verification(
    repo_root: Path, tmp_path: Path
) -> None:
    runtime = _runtime(
        suite=FakeSuiteRunner(error=SuiteConfigurationError("docker unavailable"))
    )

    exit_code, output = _run(repo_root, runtime, output_path=tmp_path / "verify.jsonl")

    assert exit_code == 1
    assert _verdict_line(output).startswith("FAIL")


def test_a_graded_run_writes_and_reports_its_result_log(
    repo_root: Path, tmp_path: Path
) -> None:
    """The archived Run is worth keeping, so its path has to reach the reader."""

    _, output = _run(repo_root, _runtime(), output_path=tmp_path / "verify.jsonl")

    logged = [_plain(line) for line in output if _plain(line).startswith("log ")]
    assert len(logged) == 1
    # The writer suffixes the base path so a rerun never overwrites an archive.
    path = Path(logged[0].removeprefix("log").strip())
    assert path.parent == tmp_path
    lines = path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert events[-1]["event"] == "suite_completed"


def test_the_benchmark_honours_the_registry_case_count(
    repo_root: Path, tmp_path: Path
) -> None:
    """A graded Run covers what the Registry declared, exactly as certify does."""

    suite = FakeSuiteRunner()
    _run(repo_root, _runtime(suite=suite), output_path=tmp_path / "verify.jsonl")

    selected, _ = suite.calls[0]
    registered = selected[0]
    assert registered.agent_id == DOCKER_AGENT_ID
    assert registered.case_count >= 1


class _FailingSuiteRunner:
    """Report an Agent that raised before completing its Case."""

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
                    error_type="AgentStartError",
                    error_message="container exited during startup",
                )
                for agent in selected
            ),
        )


# --- invariants --------------------------------------------------------------


def test_verification_never_writes_the_registry(
    repo_root: Path, tmp_path: Path
) -> None:
    registry_path = _registry_path(repo_root)
    before = registry_path.read_bytes()

    verify(
        DOCKER_AGENT_ID,
        registry_path=registry_path,
        output_fn=lambda _: None,
        runtime=_runtime(),  # type: ignore[arg-type]
        output_path=tmp_path / "verify.jsonl",
    )

    assert registry_path.read_bytes() == before


def test_json_mode_emits_one_document_and_nothing_else(
    repo_root: Path, tmp_path: Path
) -> None:
    """Stage chatter before the document would make the output unparseable."""

    _, output = _run(
        repo_root, _runtime(), output_path=tmp_path / "verify.jsonl", as_json=True
    )

    assert _json_report(output)["command"] == "verify"
