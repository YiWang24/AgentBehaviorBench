from __future__ import annotations

import json
from pathlib import Path

from agentbench.cli.presentation import ANSI_PATTERN, render_panel, visible_width
from agentbench.cli.TerminalUI.call_log import CallRecord, CallRecorder
from agentbench.cli.verify_report import (
    ERROR,
    FAIL,
    MAX_DISPLAYED_CALLS,
    PASS,
    VerifyProgress,
    VerifyReport,
    print_report,
    truncate,
)
from agentbench.harness import BenchmarkProgress
from agentbench.runtime.interception import TerminalTraceSink, TraceEvent
from agentbench.cli.constants import ANSI_CYAN


def _plain(line: str) -> str:
    return ANSI_PATTERN.sub("", line)


def _call(number: int, request: str = "ask", response: str = "reply") -> CallRecord:
    return CallRecord(
        number=number,
        provider="offline",
        request_preview=request,
        response_preview=response,
        status=200,
        latency_ms=1.25,
    )


# --- panel geometry ----------------------------------------------------------


def test_panel_border_stays_aligned_when_content_is_longer_than_the_default() -> None:
    long_path = "/tmp/" + "a" * 120 + ".jsonl"

    lines = render_panel("RESULT VIEWER", [f"Result saved: {long_path}"], ANSI_CYAN)
    widths = {visible_width(line) for line in lines}

    assert len(widths) == 1, f"panel borders misaligned: {widths}"


def test_panel_keeps_long_values_intact_so_they_stay_copyable() -> None:
    long_path = "/tmp/" + "b" * 120 + ".jsonl"

    lines = render_panel("RESULT VIEWER", [f"Open later: {long_path}"], ANSI_CYAN)

    assert any(long_path in _plain(line) for line in lines)


def test_short_content_keeps_the_default_panel_width() -> None:
    short = render_panel("RUN QUEUED", ["ok"], ANSI_CYAN)

    assert visible_width(short[0]) == 78


# --- preview truncation ------------------------------------------------------


def test_preview_truncation_cuts_the_tail_not_the_middle() -> None:
    """Previews read left to right, so the opening words must survive."""

    result = truncate("Reply with a short confirmation that you received this", 20)

    assert result.startswith("Reply with a short")
    assert result.endswith("…")
    assert len(result) <= 20


def test_preview_truncation_collapses_whitespace_and_keeps_short_text() -> None:
    assert truncate("  keep   this  ", 40) == "keep this"


# --- call recording ----------------------------------------------------------


def test_recorder_pairs_requests_with_responses_in_completion_order() -> None:
    recorder = CallRecorder()
    for call_id in ("a", "b"):
        recorder.emit(
            TraceEvent(
                "llm_request",
                {
                    "call_id": call_id,
                    "provider": "offline",
                    "payload": {"messages": [{"role": "user", "content": call_id}]},
                },
            )
        )
    recorder.emit(
        TraceEvent(
            "llm_response",
            {
                "call_id": "b",
                "status": 200,
                "latency_ms": 2.5,
                "payload": {"choices": [{"message": {"content": "second"}}]},
            },
        )
    )

    assert [record.number for record in recorder.records] == [1]
    assert recorder.records[0].request_preview == "b"
    assert recorder.records[0].response_preview == "second"
    assert recorder.records[0].latency_text == "2.5ms"


def test_recorder_ignores_events_without_a_call_id() -> None:
    recorder = CallRecorder()

    recorder.emit(TraceEvent("interceptor_ready", {"agent_id": "x"}))
    recorder.emit(TraceEvent("llm_response", {"status": 200}))

    assert recorder.records == []


# --- report rendering --------------------------------------------------------


def test_passing_report_states_cases_and_captured_pairs() -> None:
    output: list[str] = []
    report = VerifyReport(
        agent_id="demo",
        verdict=PASS,
        completed_cases=1,
        requested_cases=1,
        captured_pairs=2,
        calls=(_call(1), _call(2)),
    )

    print_report(report, output.append)
    verdict = next(line for line in map(_plain, output) if line.strip().startswith("PASS"))

    assert "1/1 cases" in verdict
    assert "2 model request/response pairs captured" in verdict


def test_a_single_captured_pair_is_not_pluralized() -> None:
    output: list[str] = []
    report = VerifyReport(
        agent_id="demo",
        verdict=PASS,
        completed_cases=1,
        requested_cases=1,
        captured_pairs=1,
    )

    print_report(report, output.append)
    verdict = next(line for line in map(_plain, output) if line.strip().startswith("PASS"))

    assert "1 model request/response pair captured" in verdict


def test_failing_report_leads_with_the_reason() -> None:
    output: list[str] = []
    report = VerifyReport(
        agent_id="demo",
        verdict=FAIL,
        reason="AgentStartError: container exited",
    )

    print_report(report, output.append)
    verdict = next(line for line in map(_plain, output) if line.strip().startswith("FAIL"))

    assert "AgentStartError: container exited" in verdict


def test_a_long_failure_reason_wraps_instead_of_running_off_the_report() -> None:
    """The reason names its underlying cause, so it can outrun the other lines."""

    output: list[str] = []
    report = VerifyReport(
        agent_id="demo",
        verdict=FAIL,
        reason=(
            "AgentInvocationError: Agent 'gpt-researcher' failed for SDK Input "
            "'offline-probe-1': DockerSessionError: AttributeError: 'str' object "
            "has no attribute 'get'"
        ),
    )

    print_report(report, output.append)
    plain = [_plain(line) for line in output if _plain(line).strip()]
    rejoined = " ".join(line.strip() for line in plain)

    assert plain[0].strip().startswith("FAIL")
    assert all(len(line) <= 80 for line in plain), [len(line) for line in plain]
    assert "AttributeError: 'str' object has no attribute 'get'" in rejoined


def test_long_call_lists_are_elided_in_the_middle() -> None:
    output: list[str] = []
    calls = tuple(_call(index) for index in range(1, MAX_DISPLAYED_CALLS + 6))
    report = VerifyReport(
        agent_id="demo",
        verdict=PASS,
        completed_cases=1,
        requested_cases=1,
        captured_pairs=len(calls),
        calls=calls,
    )

    print_report(report, output.append)
    plain = [_plain(line) for line in output]

    assert any("5 more calls" in line for line in plain)
    assert sum(1 for line in plain if "▸" in line) == MAX_DISPLAYED_CALLS


def test_stubbed_secrets_are_surfaced() -> None:
    output: list[str] = []
    report = VerifyReport(
        agent_id="demo",
        verdict=PASS,
        completed_cases=1,
        requested_cases=1,
        captured_pairs=1,
        substituted_secrets=("OPENAI_API_KEY",),
    )

    print_report(report, output.append)

    assert any("OPENAI_API_KEY" in _plain(line) for line in output)


def test_kept_result_log_is_printed_and_omitted_otherwise() -> None:
    base = {
        "agent_id": "demo",
        "verdict": PASS,
        "completed_cases": 1,
        "requested_cases": 1,
        "captured_pairs": 1,
    }
    with_log: list[str] = []
    without_log: list[str] = []

    print_report(
        VerifyReport(result_log=Path("/tmp/demo.jsonl"), **base), with_log.append
    )
    print_report(VerifyReport(**base), without_log.append)

    assert any("/tmp/demo.jsonl" in _plain(line) for line in with_log)
    assert not any("log " in _plain(line) for line in without_log)


# --- machine-readable summary ------------------------------------------------


def test_json_summary_carries_the_verdict_and_every_call() -> None:
    report = VerifyReport(
        agent_id="demo",
        verdict=PASS,
        completed_cases=1,
        requested_cases=2,
        captured_pairs=1,
        calls=(_call(1, request="ask something", response="answered"),),
        result_log=Path("/tmp/demo.jsonl"),
    )

    payload = json.loads(report.to_json())

    assert payload["command"] == "verify"
    assert payload["verdict"] == PASS
    assert payload["cases"] == {"completed": 1, "requested": 2}
    assert payload["model_calls"]["captured_pairs"] == 1
    assert payload["model_calls"]["calls"][0]["request_preview"] == "ask something"
    assert payload["result_log"] == "/tmp/demo.jsonl"


def test_json_summary_of_a_preflight_error_has_no_counts() -> None:
    payload = json.loads(
        VerifyReport(
            agent_id="demo", verdict=ERROR, reason="not registered"
        ).to_json()
    )

    assert payload["verdict"] == ERROR
    assert payload["reason"] == "not registered"
    assert payload["model_calls"]["calls"] == []


def test_the_shell_status_is_derived_from_the_verdict_and_left_out_of_the_json() -> None:
    """The process already returns the status, and `verdict` says the same thing."""

    codes = {
        verdict: VerifyReport(agent_id="demo", verdict=verdict).exit_code
        for verdict in (PASS, FAIL, ERROR)
    }

    assert codes == {PASS: 0, FAIL: 1, ERROR: 2}
    assert "exit_code" not in json.loads(
        VerifyReport(agent_id="demo", verdict=PASS).to_json()
    )


# --- stage lines -------------------------------------------------------------


def test_stage_lines_report_each_boundary_once() -> None:
    output: list[str] = []
    progress = VerifyProgress(output.append, call_count=lambda: 3)

    for stage, detail in (
        ("sdk_check", "Provider mode: local"),
        ("agent_start", "ContainerAgentAdapter"),
        ("case_generation", "run=offline_abcdef0123456789extra"),
        ("benchmark_execution", "Judge: pass"),
    ):
        progress(BenchmarkProgress(stage, "started"))  # type: ignore[arg-type]
        progress(BenchmarkProgress(stage, "succeeded", detail=detail))  # type: ignore[arg-type]
    progress.close()

    plain = [_plain(line).strip() for line in output]
    assert len(plain) == 4, plain
    assert plain[0].startswith("✓  configuration")
    assert plain[0].endswith("local providers")
    assert plain[1].endswith("ContainerAgentAdapter")
    assert "offline_abcdef" in plain[2]
    assert plain[3].endswith("3 model calls")
    assert not progress.failed


def test_a_long_stage_detail_is_cut_so_the_stage_column_stays_scannable() -> None:
    output: list[str] = []
    progress = VerifyProgress(output.append)
    reason = (
        "AgentInvocationError: Agent 'gpt-researcher' failed for SDK Input "
        "'offline-probe-1': DockerSessionError: AttributeError: 'str' object "
        "has no attribute 'get'"
    )

    progress(BenchmarkProgress("benchmark_execution", "failed", detail=reason))  # type: ignore[arg-type]

    line = _plain(output[0])
    assert len(line) <= 80, len(line)
    assert line.rstrip().endswith("…")


def test_failed_stage_is_marked_and_remembered() -> None:
    output: list[str] = []
    progress = VerifyProgress(output.append)

    progress(BenchmarkProgress("agent_start", "started"))  # type: ignore[arg-type]
    progress(BenchmarkProgress("agent_start", "failed", detail="DockerRuntimeError"))  # type: ignore[arg-type]

    assert _plain(output[0]).strip().startswith("✗  agent start")
    assert "DockerRuntimeError" in _plain(output[0])
    assert progress.failed


def test_a_long_request_still_yields_a_readable_preview() -> None:
    """Capture must stay full-fidelity.

    Truncating captured bytes to bound terminal verbosity leaves the body invalid
    JSON, and preview extraction then falls back to dumping raw escaped text.
    Bounding belongs in the sink that prints, not in what gets captured.
    """

    recorder = CallRecorder()
    long_prompt = "You are a helpful assistant. " * 200

    recorder.emit(
        TraceEvent(
            "llm_request",
            {
                "call_id": "call-1",
                "provider": "offline",
                "payload": {
                    "messages": [
                        {"role": "system", "content": long_prompt},
                        {"role": "user", "content": "Reply with a confirmation."},
                    ]
                },
            },
        )
    )
    recorder.emit(
        TraceEvent(
            "llm_response",
            {
                "call_id": "call-1",
                "status": 200,
                "payload": {"choices": [{"message": {"content": "done"}}]},
            },
        )
    )

    assert recorder.records[0].request_preview == "Reply with a confirmation."
    assert "\\" not in recorder.records[0].request_preview


def test_terminal_trace_caps_only_what_it_prints() -> None:
    output: list[str] = []
    payload = {"messages": [{"content": "x" * 5000}]}

    TerminalTraceSink(output.append, max_payload_chars=200).emit(
        TraceEvent(
            "llm_request",
            {
                "call_id": "call-1",
                "route_id": "openai-chat",
                "provider": "offline",
                "method": "POST",
                "host": "api.openai.com",
                "path": "/v1/chat/completions",
                "payload": payload,
            },
        )
    )

    rendered = output[-1]
    assert len(rendered) < 400
    assert "more characters" in rendered


def test_terminal_trace_omits_a_source_identical_to_its_destination() -> None:
    """A target that answers the call itself never rewrites the address."""

    output: list[str] = []
    TerminalTraceSink(output.append).emit(
        TraceEvent(
            "llm_request",
            {
                "call_id": "call-1",
                "route_id": "openai-chat",
                "provider": "offline",
                "method": "POST",
                "host": "api.openai.com",
                "path": "/v1/chat/completions",
                "source_host": "api.openai.com",
                "source_path": "/v1/chat/completions",
            },
        )
    )

    assert "source=" not in output[0]
    assert "api.openai.com/v1/chat/completions" in output[0]


def test_terminal_trace_keeps_a_source_that_was_rewritten() -> None:
    output: list[str] = []
    TerminalTraceSink(output.append).emit(
        TraceEvent(
            "llm_request",
            {
                "call_id": "call-1",
                "route_id": "openai-chat",
                "provider": "openrouter",
                "method": "POST",
                "host": "openrouter.ai",
                "path": "/api/v1/chat/completions",
                "source_host": "api.openai.com",
                "source_path": "/v1/chat/completions",
            },
        )
    )

    assert "source=api.openai.com/v1/chat/completions" in output[0]


def test_single_model_call_is_not_pluralized() -> None:
    output: list[str] = []
    progress = VerifyProgress(output.append, call_count=lambda: 1)

    progress(BenchmarkProgress("benchmark_execution", "succeeded", detail="Judge: pass"))  # type: ignore[arg-type]

    assert _plain(output[0]).endswith("1 model call")
