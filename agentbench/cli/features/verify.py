"""Verify one Agent, as far as this host is able to.

Verification runs in one direction and stops at the first thing that is missing.
Preflight asks whether the Agent runs and whether its model traffic is
observable, using no credentials and no SDK. Only then is the host asked whether
it can grade the Agent at all; when it cannot, the run stops without blaming the
Agent for a gap in its own setup. When it can, the flow is ``certify``'s — a Case
generated from the requirement, answered with a real model, graded against the
declared behaviors — with the Case and Judge Provider ports supplied locally, so
``DEFUZEX_API_KEY`` is never read and the Registry is never written.
"""

from __future__ import annotations

import re
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from agentbench.harness import BenchmarkSuiteResult, SuiteAgentResult
from agentbench.harness.offline import DEFAULT_PROBE_TEXT
from agentbench.harness.protocols import STATUS_PASS
from agentbench.runtime.interception import DEFAULT_TRACE_MAX_BYTES

from agentbench.cli.environment import load_project_environment
from agentbench.cli.execution import BenchmarkExecution, run_benchmark_once
from agentbench.cli.progress import ProgressPrinter
from agentbench.cli.TerminalUI import LLMActivity
from agentbench.cli.verify_preflight import (
    PreflightResult,
    SubjectError,
    VerifySubject,
    run_preflight,
    select_subject,
)
from agentbench.cli.verify_providers import ProviderCheck, check_providers
from agentbench.cli.verify_report import (
    ERROR,
    FAIL,
    PARTIAL,
    PASS,
    PROVIDERS_READY,
    PROVIDERS_SKIPPED,
    PROVIDERS_UNAVAILABLE,
    VerifyReport,
    print_header,
    print_report,
    print_section,
)
from agentbench.cli.verify_runtime import (
    DEFAULT_INPUT_COUNT,
    DEFAULT_PROBE_COUNT,
    VerifyOptions,
    VerifyRuntime,
    build_verify_runtime,
)

from .base import CommandFeature
from .run import DEFAULT_REGISTRY_PATH

INPUT_FILE_MARKER = "@"

PREFLIGHT_NOTE = "synthesized model replies · egress blocked · no credentials"
PROVIDER_NOTE = "DefuzeX SDK · local Case and Judge Providers"


def configure_parser(parser: ArgumentParser) -> None:
    """Declare the flags, grouped the way the help output reads."""

    _add_subject_arguments(parser)
    _add_model_arguments(parser)
    _add_report_arguments(parser)
    _add_trace_arguments(parser)


def _add_subject_arguments(parser: ArgumentParser) -> None:
    """Which Agent to verify, and how far to take it."""

    parser.add_argument("agent_id", help="Registered Agent to verify.")
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Load host defaults from PATH instead of .env.",
    )
    parser.add_argument(
        "--input",
        metavar="TEXT",
        help=(
            "Probe text sent to the Agent during preflight, or @PATH to read it "
            "from a file. Defaults to a short generic prompt."
        ),
    )
    parser.add_argument(
        "--probes",
        type=int,
        default=DEFAULT_PROBE_COUNT,
        metavar="N",
        help=f"Preflight probes to send. Defaults to {DEFAULT_PROBE_COUNT}.",
    )
    parser.add_argument(
        "--inputs",
        type=int,
        default=DEFAULT_INPUT_COUNT,
        metavar="N",
        help=(
            "Inputs to generate for the graded benchmark. Defaults to "
            f"{DEFAULT_INPUT_COUNT}."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Stop after preflight. Needs no credentials and no DefuzeX SDK, so "
            "this is the check to repeat while adapting an Agent."
        ),
    )


def _add_model_arguments(parser: ArgumentParser) -> None:
    """Which model the Agent answers with, and which one grades it."""

    parser.add_argument(
        "--model",
        metavar="MODEL",
        help=(
            "Model the Agent talks to during the graded benchmark; defaults to "
            "DEEPSEEK_MODEL. Preflight always answers from the interceptor."
        ),
    )
    parser.add_argument(
        "--provider-model",
        metavar="MODEL",
        help=(
            "Model that generates the Case and judges the Run; defaults to "
            "DEEPSEEK_MODEL. Independent of the model the Agent uses."
        ),
    )


def _add_report_arguments(parser: ArgumentParser) -> None:
    """Where the verdict goes."""

    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Where to write the benchmark result log. Defaults to "
            "results/verify-<agent_id>.jsonl. Preflight writes no log."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print one JSON summary instead of the human report.",
    )


def _add_trace_arguments(parser: ArgumentParser) -> None:
    """How much of the captured model traffic to print."""

    parser.add_argument(
        "--llm-trace",
        choices=("off", "terminal"),
        default="off",
        help="Print the sanitized model requests and responses that were captured.",
    )
    parser.add_argument(
        "--llm-trace-max-bytes",
        type=int,
        default=DEFAULT_TRACE_MAX_BYTES,
        metavar="BYTES",
        help="Maximum captured payload bytes per request or response.",
    )


def execute(args: Namespace) -> int:
    load_project_environment(args.env_file)
    return verify(
        args.agent_id,
        options=VerifyOptions(
            probe_count=args.probes,
            input_count=args.inputs,
            probe_text=(
                _probe_text(args.input)
                if args.input is not None
                else DEFAULT_PROBE_TEXT
            ),
            model=args.model,
            provider_model=args.provider_model,
            preflight_only=args.preflight_only,
            llm_trace=args.llm_trace,
            llm_trace_max_bytes=args.llm_trace_max_bytes,
        ),
        output_path=args.output,
        as_json=args.as_json,
    )


def verify(
    agent_id: str,
    *,
    options: VerifyOptions | None = None,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    output_fn: Callable[[str], None] = print,
    runtime: VerifyRuntime | None = None,
    output_path: str | Path | None = None,
    as_json: bool = False,
) -> int:
    """Run one Agent as far as this host can take it, and report where it got."""

    options = options or VerifyOptions()
    # In JSON mode nothing may reach stdout before the document itself.
    stage_output = _discard if as_json else output_fn

    try:
        subject = select_subject(agent_id, registry_path, options)
    except SubjectError as exc:
        return _fail_early(agent_id, str(exc), output_fn, as_json=as_json)

    # The live panel is wanted on a terminal, but its non-interactive fallback
    # would duplicate the call list the sectioned report already prints, so it is
    # silenced and the stage lines are rendered by the progress printer instead.
    llm_activity = LLMActivity(
        _discard,
        live_updates=not as_json and sys.stdout.isatty(),
    )
    if runtime is None:
        try:
            runtime = build_verify_runtime(
                options, output_fn=stage_output, activity_sink=llm_activity
            )
        except Exception as exc:
            # Assembly only reads configuration, so a rejection here is the
            # caller's mistake rather than a verdict about the Agent.
            return _fail_early(agent_id, str(exc), output_fn, as_json=as_json)

    return _report(
        _verified(
            subject,
            runtime=runtime,
            llm_activity=llm_activity,
            stage_output=stage_output,
            output_path=output_path,
        ),
        output_fn,
        as_json=as_json,
    )


def _verified(
    subject: VerifySubject,
    *,
    runtime: VerifyRuntime,
    llm_activity: LLMActivity,
    stage_output: Callable[[str], None],
    output_path: str | Path | None,
) -> VerifyReport:
    """Render the run, guaranteeing the live renderer is closed afterwards."""

    print_header(subject.agent_id, stage_output)
    stages = ProgressPrinter(stage_output, llm_activity=llm_activity)
    try:
        report = _run_phases(
            subject,
            runtime=runtime,
            stages=stages,
            llm_activity=llm_activity,
            stage_output=stage_output,
            output_path=output_path,
        )
    finally:
        stages.close()
    return report


def _report(
    report: VerifyReport, output_fn: Callable[[str], None], *, as_json: bool
) -> int:
    if as_json:
        output_fn(report.to_json())
    else:
        output_fn("")
        print_report(report, output_fn)
    return report.exit_code


def _run_phases(
    subject: VerifySubject,
    *,
    runtime: VerifyRuntime,
    stages: ProgressPrinter,
    llm_activity: LLMActivity,
    stage_output: Callable[[str], None],
    output_path: str | Path | None,
) -> VerifyReport:
    """Preflight, then the provider check, then the graded Run — stopping early."""

    options = runtime.options
    print_section("PREFLIGHT", PREFLIGHT_NOTE, stage_output)
    preflight = run_preflight(
        subject,
        runner=runtime.preflight_runner(),
        options=options,
        trace_state=runtime.trace_state,
        stages=stages,
    )
    base = _base_report(subject.agent_id, runtime, preflight)
    if not preflight.passed:
        return replace(base, verdict=FAIL)
    if options.preflight_only:
        return replace(base, verdict=PASS, providers=PROVIDERS_SKIPPED)

    print_section("PROVIDER CHECK", PROVIDER_NOTE, stage_output)
    check = check_providers(options, environ=runtime.environ, stages=stages)
    if not check.available:
        return replace(
            base,
            verdict=PARTIAL,
            providers=PROVIDERS_UNAVAILABLE,
            provider_reason=check.reason,
        )

    print_section("BENCHMARK", _benchmark_note(check), stage_output)
    execution = run_benchmark_once(
        (subject.agent,),
        runner=runtime.benchmark_suite_runner(check.chat),
        output_path=_artifact_path(subject.agent_id, output_path),
        output_fn=_discard,  # the sectioned report owns all verify output
        viewer_starter=None,
        llm_activity=llm_activity,
        progress=stages,
    )
    return _benchmark_report(base, execution=execution, check=check, runtime=runtime)


def _benchmark_note(check: ProviderCheck) -> str:
    return (
        f"live model {check.agent_model} · egress open · "
        f"judged by {check.provider_model}"
    )


def _base_report(
    agent_id: str, runtime: VerifyRuntime, preflight: PreflightResult
) -> VerifyReport:
    """The half of the report that holds however far the run got.

    Built once and narrowed by each outcome. A dict of shared keyword arguments
    would be untyped at every construction site, which is exactly where a missing
    or misspelled field should be caught.
    """

    return VerifyReport(
        agent_id=agent_id,
        verdict=FAIL,
        probes_sent=preflight.probes_sent,
        probes_answered=preflight.probes_answered,
        captured_pairs=runtime.captured_pair_count,
        substituted_secrets=runtime.substituted_secrets,
        calls=runtime.calls,
        reason=preflight.reason,
    )


def _benchmark_report(
    base: VerifyReport,
    *,
    execution: BenchmarkExecution,
    check: ProviderCheck,
    runtime: VerifyRuntime,
) -> VerifyReport:
    """Turn the graded suite outcome into a verdict."""

    item = _agent_item(execution.result, base.agent_id)
    report = replace(
        base,
        verdict=PASS,
        reason=None,
        providers=PROVIDERS_READY,
        provider_model=check.provider_model,
        agent_model=check.agent_model,
        benchmark_ran=True,
        captured_pairs=runtime.captured_pair_count,
        calls=runtime.calls,
        substituted_secrets=runtime.substituted_secrets,
        result_log=(
            None if execution.result_log is None else execution.result_log.path
        ),
    )
    if item is not None:
        report = replace(
            report,
            completed_cases=item.completed_case_count,
            requested_cases=item.requested_case_count,
            judge_status=_judge_status(item),
            **_judgment_detail(item),
        )

    reason = _rejection(item)
    return report if reason is None else replace(report, verdict=FAIL, reason=reason)


def _rejection(item: SuiteAgentResult | None) -> str | None:
    """Why the graded Run failed, or None when it completed and passed.

    Ordered by how early the run could have stopped, so the first thing that went
    wrong is what gets reported. Whether model traffic was observable is not asked
    again: preflight already answered it, and a benchmark cannot reach here
    without preflight having passed.
    """

    if item is None or not _completed(item):
        if item is not None and item.error_type is not None:
            return f"{item.error_type}: {item.error_message}"
        return "The graded Run did not complete"
    # The SDK, not this command, decides whether the Run satisfied its Case.
    return _judge_rejection(item)


def _judgment_detail(item: SuiteAgentResult) -> dict[str, object]:
    """Lift the Judge's own words out of every Case the Agent ran.

    A verdict is only actionable with the reasoning behind it, and the SDK carries
    anything beyond the standard report fields in ``extensions``. All Cases are
    read, not just the last: an Agent that failed its first Case and passed its
    second has not passed.
    """

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
    return {
        "judge_summary": " ".join(summaries) or None,
        "judge_issues": tuple(issues),
        "step_results": tuple(steps),
    }


def _extensions(report: object) -> Mapping[str, object]:
    extensions = getattr(report, "extensions", None)
    return extensions if isinstance(extensions, Mapping) else {}


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


def _issue_text(issue: object) -> str:
    if isinstance(issue, Mapping):
        return str(issue.get("message") or issue.get("code") or issue)
    return str(issue)


def _agent_item(
    result: BenchmarkSuiteResult | None, agent_id: str
) -> SuiteAgentResult | None:
    if result is None or result.skipped_count != 0 or len(result.items) != 1:
        return None
    item = result.items[0]
    return item if item.agent_id == agent_id else None


def _completed(item: SuiteAgentResult) -> bool:
    """Every requested Case ran end to end without harness errors."""

    return (
        item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def _artifact_path(agent_id: str, output_path: str | Path | None) -> Path:
    """Where a graded Run is archived, matching where certify writes."""

    if output_path is not None:
        return Path(output_path)
    results = Path(DEFAULT_REGISTRY_PATH).resolve().parent.parent / "results"
    return results / f"verify-{_safe_name(agent_id)}.jsonl"


def _fail_early(
    agent_id: str,
    reason: str,
    output_fn: Callable[[str], None],
    *,
    as_json: bool,
) -> int:
    report = VerifyReport(agent_id=agent_id, verdict=ERROR, reason=reason)
    if as_json:
        output_fn(report.to_json())
    else:
        output_fn(f"Verification error: {reason}")
    return 2


def _probe_text(value: str) -> str:
    if not value.startswith(INPUT_FILE_MARKER):
        return value
    return (
        Path(value[len(INPUT_FILE_MARKER) :])
        .expanduser()
        .read_text(encoding="utf-8")
    )


def _safe_name(agent_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_id).strip("-")
    return cleaned or "agent"


def _discard(_: str) -> None:
    """Swallow shared-execution chatter that the verify report replaces."""


FEATURE = CommandFeature(
    name="verify",
    help="Run one Agent as far as this host can take it, without DefuzeX credentials.",
    description=(
        "Check one registered Agent in three steps that stop at the first thing "
        "missing. Preflight starts the Agent, probes it, and confirms its model "
        "calls are captured, using no credentials and no DefuzeX SDK. The "
        "provider check then asks whether this host can grade the Agent at all. "
        "When it can, the same flow as certify runs with the Case and Judge "
        "Provider ports supplied locally, so no DefuzeX credential is needed and "
        "the Registry is never changed."
    ),
    configure=configure_parser,
    execute=execute,
)
