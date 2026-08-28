"""Sectioned terminal report and machine-readable summary for `verify`.

The run reads top to bottom as one column of stages, split by the three
questions it asks in order: can the Agent run, can this host grade it, and did it
behave. Stage lines are rendered by the shared :class:`ProgressPrinter`, so a
verification looks like a `certify` run rather than a dialect of one. What is
left here is the framing around them — the section rules, the model-call log, the
judgment, and the verdict.

No boxes around the verdict, so nothing can break on a long path, and every line
stays greppable.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agentbench.cli.constants import (
    ANSI_BOLD,
    ANSI_CYAN,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
)
from agentbench.cli.execution import completed_every_case, sole_agent_result
from agentbench.cli.presentation import panel_rule, visible_width
from agentbench.cli.TerminalUI.call_log import CallRecord
from agentbench.harness import BenchmarkSuiteResult, SuiteAgentResult
from agentbench.harness.protocols import STATUS_PASS

PASS = "pass"
# Preflight held, but this host could not grade the Agent. Nothing about the
# Agent failed, so this shares an exit code with a pass: a CI job without a
# provider credential must not go red for a gap in its own setup.
PARTIAL = "partial"
FAIL = "fail"
ERROR = "error"

EXIT_CODES = {PASS: 0, PARTIAL: 0, FAIL: 1, ERROR: 2}

PROVIDERS_READY = "ready"
PROVIDERS_UNAVAILABLE = "unavailable"
PROVIDERS_SKIPPED = "skipped"

MARK_OK = "✓"
MARK_FAIL = "✗"
ARROW_IN = "▸"
ARROW_OUT = "◂"
SEPARATOR = "·"

LABEL_WIDTH = 16
PREVIEW_WIDTH = 54
DETAIL_WIDTH = 70
MAX_DISPLAYED_CALLS = 10


def truncate(text: str, width: int) -> str:
    """Cut the tail of a preview.

    Previews read left to right, so the opening words matter most; only paths get
    shortened from the middle.
    """

    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[: max(width - 1, 0)].rstrip() + "…"


@dataclass(frozen=True)
class VerifyReport:
    """Everything `verify` learned about one Agent."""

    agent_id: str
    verdict: str
    # Preflight: did the Agent run, and was its traffic observable.
    probes_sent: int = 0
    probes_answered: int = 0
    captured_pairs: int = 0
    substituted_secrets: tuple[str, ...] = ()
    # Provider check: could this host grade the Agent at all.
    providers: str = PROVIDERS_SKIPPED
    provider_reason: str | None = None
    # The model that wrote the Case and graded the Run, when one did.
    provider_model: str | None = None
    # The model the Agent itself answered with, when a graded Run happened.
    agent_model: str | None = None
    # Benchmark: how the graded Run went.
    benchmark_ran: bool = False
    completed_cases: int = 0
    requested_cases: int = 0
    # The DefuzeX SDK's own report status for the Run, distinct from this
    # command's verdict: the Judge can pass a Run whose model traffic verify
    # still rejects as unobservable.
    judge_status: str | None = None
    judge_summary: str | None = None
    judge_issues: tuple[str, ...] = ()
    # (step_id, passed, reason) per generated Input.
    step_results: tuple[tuple[str, bool, str], ...] = ()
    calls: tuple[CallRecord, ...] = ()
    result_log: Path | None = None
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def exit_code(self) -> int:
        """The shell status this verdict maps to.

        Derived rather than stored so the two can never disagree, and left out of
        the JSON: the process already returns it, and ``verdict`` says the same
        thing in a form that does not need a lookup table.
        """

        return EXIT_CODES[self.verdict]

    def to_json(self) -> str:
        """One document per run, grouped by the phase each fact came from."""

        return json.dumps(
            {
                "command": "verify",
                "agent_id": self.agent_id,
                "verdict": self.verdict,
                "preflight": {
                    "probes_sent": self.probes_sent,
                    "probes_answered": self.probes_answered,
                },
                "providers": {
                    "state": self.providers,
                    "reason": self.provider_reason,
                    "provider_model": self.provider_model,
                    "agent_model": self.agent_model,
                },
                "benchmark": self._benchmark_json(),
                "model_calls": {
                    "captured_pairs": self.captured_pairs,
                    "calls": [_call_json(call) for call in self.calls],
                },
                "substituted_secrets": list(self.substituted_secrets),
                "result_log": None if self.result_log is None else str(self.result_log),
                "reason": self.reason,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _benchmark_json(self) -> dict[str, object]:
        return {
            "ran": self.benchmark_ran,
            "cases": {
                "completed": self.completed_cases,
                "requested": self.requested_cases,
            },
            "sdk_judge_status": self.judge_status,
            "summary": self.judge_summary,
            "issues": list(self.judge_issues),
            "step_results": [
                {"step_id": step, "passed": passed, "reason": reason}
                for step, passed, reason in self.step_results
            ],
        }


def _call_json(call: CallRecord) -> dict[str, object]:
    return {
        "number": call.number,
        "provider": call.provider,
        "status": call.status,
        "latency_ms": call.latency_ms,
        "request_preview": call.request_preview,
        "response_preview": call.response_preview,
    }


@dataclass(frozen=True, slots=True)
class Judgment:
    """What the SDK's Judge said about one Agent, flattened for the report.

    Reading it is a single pass over the suite result, because every field it
    carries answers the same question — did this Agent satisfy the Cases it was
    given, and if not, what was the first thing that went wrong.
    """

    completed_cases: int = 0
    requested_cases: int = 0
    status: str | None = None
    summary: str | None = None
    issues: tuple[str, ...] = ()
    # (step_id, passed, reason) per generated Input.
    step_results: tuple[tuple[str, bool, str], ...] = ()
    # None when every Case passed.
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.reason is None


def read_judgment(
    result: BenchmarkSuiteResult | None, agent_id: str
) -> Judgment:
    """Lift the Judge's own words out of every Case the Agent ran.

    A verdict is only actionable with the reasoning behind it, and the SDK
    carries anything beyond the standard report fields in ``extensions``. All
    Cases are read, not just the last: an Agent that failed its first Case and
    passed its second has not passed.
    """

    item = sole_agent_result(result, agent_id)
    if item is None or not completed_every_case(item):
        reason = (
            f"{item.error_type}: {item.error_message}"
            if item is not None and item.error_type is not None
            else "The graded Run did not complete"
        )
        return Judgment(reason=reason)

    summaries: list[str] = []
    issues: list[str] = []
    steps: list[tuple[str, bool, str]] = []
    multiple = len(item.benchmarks) > 1
    for index, benchmark in enumerate(item.benchmarks, start=1):
        report = benchmark.report
        if report is None:
            continue
        prefix = f"case {index} " if multiple else ""
        extensions = _extensions(report)
        summary = str(extensions.get("summary") or "").strip()
        if summary:
            summaries.append(f"{prefix}{summary}" if prefix else summary)
        issues.extend(f"{prefix}{_issue_text(issue)}" for issue in report.issues)
        raw = extensions.get("step_results")
        steps.extend(
            (
                f"{prefix}{entry.get('step_id') or '?'}".strip(),
                bool(entry.get("passed")),
                str(entry.get("reason") or "").strip(),
            )
            for entry in (raw if isinstance(raw, (list, tuple)) else ())
            if isinstance(entry, Mapping)
        )

    return Judgment(
        completed_cases=item.completed_case_count,
        requested_cases=item.requested_case_count,
        status=_judge_status(item),
        summary=" ".join(summaries) or None,
        issues=tuple(issues),
        step_results=tuple(steps),
        # The SDK, not this command, decides whether the Run satisfied its Case.
        reason=_judge_rejection(item),
    )



def _judge_status(item: SuiteAgentResult) -> str | None:
    """The Agent's overall SDK status: the first Case that did not pass."""

    statuses = [
        benchmark.report.status
        for benchmark in item.benchmarks
        if benchmark.report is not None
    ]
    if not statuses:
        return None
    return next((status for status in statuses if status != STATUS_PASS), STATUS_PASS)


def _judge_rejection(item: SuiteAgentResult) -> str | None:
    """Explain the first non-passing Judgment, or None when every Case passed."""

    if not item.benchmarks:
        return "The SDK Run finished without producing a report"
    for index, benchmark in enumerate(item.benchmarks, start=1):
        report = benchmark.report
        if report is None:
            return f"Case {index} finished without producing a report"
        if report.status == STATUS_PASS:
            continue
        where = f"Case {index}: " if len(item.benchmarks) > 1 else ""
        headline = f"{where}SDK Judge reported {report.status!r}"
        # The Judge's own summary reads better than a concatenation of issues,
        # and the issues are printed in full just above the verdict anyway.
        detail = str(_extensions(report).get("summary") or "").strip()
        if not detail:
            detail = "; ".join(_issue_text(issue) for issue in report.issues)
        return f"{headline}: {detail}" if detail else headline
    return None


def _extensions(report: object) -> Mapping[str, object]:
    extensions = getattr(report, "extensions", None)
    return extensions if isinstance(extensions, Mapping) else {}


def _issue_text(issue: object) -> str:
    if isinstance(issue, Mapping):
        return str(issue.get("message") or issue.get("code") or issue)
    return str(issue)


def print_header(agent_id: str, output_fn: Callable[[str], None]) -> None:
    """Name the subject and the two guarantees that hold for the whole run."""

    output_fn("")
    output_fn(
        f"{ANSI_BOLD}verify{ANSI_RESET} {SEPARATOR} {ANSI_BOLD}{agent_id}{ANSI_RESET}"
    )
    output_fn(
        f"       SDK local providers {SEPARATOR} no DefuzeX credentials "
        f"{SEPARATOR} registry untouched"
    )


def print_section(title: str, note: str, output_fn: Callable[[str], None]) -> None:
    """Open one phase, stating what it does and does not reach.

    The guarantees differ per phase — preflight blocks egress, the benchmark opens
    it — so they belong here rather than in a header that would have to hedge.
    """

    output_fn("")
    output_fn(panel_rule(title, ANSI_CYAN))
    if note:
        output_fn(f"  {note}")


def print_report(report: VerifyReport, output_fn: Callable[[str], None]) -> None:
    """Render the model-call and verdict sections."""

    if report.calls:
        _print_calls(report.calls, output_fn)
    if report.step_results or report.judge_issues:
        _print_judgment(report, output_fn)
    if report.substituted_secrets:
        output_fn(
            f"  {ANSI_YELLOW}!{ANSI_RESET}  {'stubbed secrets':<{LABEL_WIDTH}}"
            + ", ".join(report.substituted_secrets)
        )
        output_fn("")
    _print_verdict(report, output_fn)


def _print_calls(
    calls: Sequence[CallRecord], output_fn: Callable[[str], None]
) -> None:
    shown = _visible_calls(calls)
    for call in shown:
        if call is None:
            output_fn(
                f"     {'':>2}  {SEPARATOR * 3} "
                f"{len(calls) - MAX_DISPLAYED_CALLS} more calls"
            )
            continue
        meta = f"{call.status_text} {SEPARATOR} {call.latency_text}"
        output_fn(
            f"     {call.number:02d}  {ARROW_IN} "
            f"{truncate(call.request_preview, PREVIEW_WIDTH)}"
        )
        output_fn(
            f"         {ARROW_OUT} "
            f"{truncate(call.response_preview, PREVIEW_WIDTH):<{PREVIEW_WIDTH}}  {meta}"
        )
    output_fn("")


def _print_judgment(report: VerifyReport, output_fn: Callable[[str], None]) -> None:
    """Show what the Judge decided per Input, then anything it objected to.

    A graded verdict is only actionable with the reasoning attached, so this sits
    between the call list and the verdict rather than being folded into either.
    """

    for step_id, passed, reason in report.step_results:
        mark = (
            f"{ANSI_GREEN}{MARK_OK}{ANSI_RESET}"
            if passed
            else f"{ANSI_RED}{MARK_FAIL}{ANSI_RESET}"
        )
        output_fn(
            f"  {mark}  {step_id:<{LABEL_WIDTH}}"
            f"{truncate(reason, DETAIL_WIDTH - LABEL_WIDTH)}"
        )
    for issue in report.judge_issues:
        head, *rest = textwrap.wrap(issue, DETAIL_WIDTH - 6) or [""]
        output_fn(f"  {ANSI_YELLOW}!{ANSI_RESET}  {head}")
        for line in rest:
            output_fn(f"{'':<6}{line}")
    output_fn("")


def _visible_calls(calls: Sequence[CallRecord]) -> list[CallRecord | None]:
    """Keep the report short by eliding the middle of a long call list."""

    if len(calls) <= MAX_DISPLAYED_CALLS:
        return list(calls)
    head = MAX_DISPLAYED_CALLS // 2
    tail = MAX_DISPLAYED_CALLS - head
    return [*calls[:head], None, *calls[len(calls) - tail :]]


def _print_verdict(report: VerifyReport, output_fn: Callable[[str], None]) -> None:
    badge, detail = _verdict_text(report)
    # Derived from the badge rather than fixed: PARTIAL is three characters wider
    # than PASS, and a constant indent would leave its wrapped lines hanging.
    indent = 2 + visible_width(badge) + 3

    # A failure reason names its underlying cause, which can outrun the rest of
    # the report. Wrapping keeps it whole and aligned instead of letting the
    # terminal break it at an arbitrary column.
    head, *rest = textwrap.wrap(detail, DETAIL_WIDTH) or [""]
    output_fn(f"  {badge}   {head}")
    for line in rest:
        output_fn(f"{'':<{indent}}{line}")
    if report.result_log is not None:
        output_fn(f"{'':<{indent}}log  {report.result_log}")


def _verdict_text(report: VerifyReport) -> tuple[str, str]:
    if report.verdict == FAIL:
        return (
            f"{ANSI_RED}{ANSI_BOLD}FAIL{ANSI_RESET}",
            report.reason or "verification did not complete",
        )
    if report.verdict == PARTIAL:
        return (
            f"{ANSI_YELLOW}{ANSI_BOLD}PARTIAL{ANSI_RESET}",
            f"{_preflight_text(report)}. Benchmark skipped: "
            f"{report.provider_reason or 'no local Providers available'}",
        )
    if not report.benchmark_ran:
        return (
            f"{ANSI_GREEN}{ANSI_BOLD}PASS{ANSI_RESET}",
            f"preflight only {SEPARATOR} {_preflight_text(report)}",
        )

    judged = (
        ""
        if report.judge_status is None
        else f" {SEPARATOR} judge: {report.judge_status}"
    )
    detail = (
        f"{report.completed_cases}/{report.requested_cases} cases {SEPARATOR} "
        f"{_pairs_text(report.captured_pairs)}{judged}"
    )
    if report.judge_summary:
        detail = f"{detail}. {report.judge_summary}"
    return f"{ANSI_GREEN}{ANSI_BOLD}PASS{ANSI_RESET}", detail


def _preflight_text(report: VerifyReport) -> str:
    return (
        f"{report.probes_answered}/{report.probes_sent} probes answered "
        f"{SEPARATOR} {_pairs_text(report.captured_pairs)}"
    )


def _pairs_text(pairs: int) -> str:
    return (
        f"{pairs} model request/response pair{'' if pairs == 1 else 's'} captured"
    )


__all__ = [
    "ERROR",
    "FAIL",
    "MAX_DISPLAYED_CALLS",
    "PARTIAL",
    "PASS",
    "PROVIDERS_READY",
    "PROVIDERS_SKIPPED",
    "PROVIDERS_UNAVAILABLE",
    "Judgment",
    "VerifyReport",
    "print_header",
    "print_report",
    "print_section",
    "read_judgment",
    "truncate",
]
