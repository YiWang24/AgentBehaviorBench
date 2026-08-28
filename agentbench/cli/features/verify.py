"""Verify one Agent through the DefuzeX SDK, without any DefuzeX credentials.

Two questions can be asked, and they need different machinery. ``startup`` asks
whether the Agent runs at all and is cheap enough to repeat while adapting one.
``benchmark`` asks whether it behaves, by running the same flow ``certify`` runs
with locally generated Cases and local judging in place of the official services.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from agentbench.harness import BenchmarkSuiteResult, SuiteAgentResult
from agentbench.harness.offline import DEFAULT_PROBE_TEXT, STATUS_PASS
from agentbench.harness.registry import AgentRegistration, load_registry
from agentbench.runtime.agentcontainer import runtime_type
from agentbench.runtime.interception import (
    DEFAULT_TRACE_MAX_BYTES,
    InterceptionConfig,
)

from agentbench.cli.environment import load_project_environment
from agentbench.cli.execution import BenchmarkExecution, run_benchmark_once
from agentbench.cli.verify_runtime import (
    BENCHMARK_MODE,
    LIVE_SOURCE,
    MODEL_SOURCES,
    OFFLINE_SOURCE,
    STARTUP_MODE,
    VERIFY_MODES,
    ModelSource,
    VerifyOptions,
    VerifyRuntime,
    build_verify_runtime,
)
from agentbench.cli.TerminalUI import LLMActivity
from agentbench.cli.verify_report import (
    ERROR,
    FAIL,
    PASS,
    VerifyProgress,
    VerifyReport,
    print_header,
    print_report,
)

from .base import CommandFeature
from .run import DEFAULT_REGISTRY_PATH

DEFAULT_INPUT_COUNT = 1
# One probe answers the startup question; one generated Case does not answer the
# behavior question, because a single Input cannot cover a requirement.
DEFAULT_BENCHMARK_INPUT_COUNT = 3
ARTIFACT_PREFIX = "agentbench-verify-"
INPUT_FILE_MARKER = "@"


def configure_parser(parser: ArgumentParser) -> None:
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
            "Probe text sent to the Agent, or @PATH to read it from a file. "
            "Defaults to a short generic prompt."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=VERIFY_MODES,
        default=STARTUP_MODE,
        help=(
            "'startup' (default) checks that the Agent runs and its model traffic "
            "is observable, using no credentials. 'benchmark' runs the same flow "
            "as certify with locally generated Cases and local judging, which "
            "needs DEEPSEEK_API_KEY and a live model source."
        ),
    )
    parser.add_argument(
        "--inputs",
        type=int,
        metavar="N",
        help=(
            "Startup probes to send, or Inputs to generate in benchmark mode. "
            f"Defaults to {DEFAULT_INPUT_COUNT} and "
            f"{DEFAULT_BENCHMARK_INPUT_COUNT} respectively."
        ),
    )
    parser.add_argument(
        "--provider-model",
        metavar="MODEL",
        help=(
            "Model that generates the Case and judges the Run in benchmark mode; "
            "defaults to DEEPSEEK_MODEL. Independent of the model the Agent uses."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Where to write the benchmark result log. Defaults to "
            "results/verify-<agent_id>.jsonl; ignored in startup mode, which "
            "uses a temporary file."
        ),
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary result log instead of deleting it on exit.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print one JSON summary instead of the human report.",
    )
    parser.add_argument(
        "--model-source",
        choices=MODEL_SOURCES,
        default=OFFLINE_SOURCE,
        help=(
            "Where model replies come from. 'offline' (default) synthesizes them "
            "inside the interceptor with network egress blocked and needs no "
            "credential. 'deepseek' calls the real provider, which opens egress "
            "and requires DEEPSEEK_API_KEY."
        ),
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help=(
            "Model slug for the selected source; defaults to DEEPSEEK_MODEL or "
            "deepseek-chat when --model-source is deepseek."
        ),
    )
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
    benchmark = args.mode == BENCHMARK_MODE
    return verify(
        args.agent_id,
        options=VerifyOptions(
            input_count=(
                args.inputs
                if args.inputs is not None
                else (
                    DEFAULT_BENCHMARK_INPUT_COUNT if benchmark else DEFAULT_INPUT_COUNT
                )
            ),
            probe_text=(
                _probe_text(args.input)
                if args.input is not None
                else DEFAULT_PROBE_TEXT
            ),
            mode=args.mode,
            # Grading synthetic replies is meaningless, so benchmark mode implies
            # a live model unless the caller named a different one.
            model_source=(
                LIVE_SOURCE
                if benchmark and args.model_source == OFFLINE_SOURCE
                else args.model_source
            ),
            model=args.model,
            provider_model=args.provider_model,
            llm_trace=args.llm_trace,
            llm_trace_max_bytes=args.llm_trace_max_bytes,
        ),
        keep_artifacts=args.keep_artifacts,
        output_path=args.output,
        as_json=args.as_json,
    )


def verify(
    agent_id: str,
    *,
    options: VerifyOptions | None = None,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    keep_artifacts: bool = False,
    output_fn: Callable[[str], None] = print,
    offline: VerifyRuntime | None = None,
    output_path: str | Path | None = None,
    as_json: bool = False,
) -> int:
    """Run one Agent through a real SDK Run without any DefuzeX credentials.

    The SDK owns the Run in both modes, exactly as it does for ``run`` and
    ``certify``; only the Case and Judge Provider ports are local, which is what
    selects the SDK's local mode and leaves it with no Backend to call.
    ``DEFUZEX_API_KEY`` is never read and the Registry is never written.

    In ``startup`` mode the Case is a fixed probe and the Judge only asks whether
    every Input came back answered. That is the only defensible verdict when
    replies come from the offline mock, and it is cheap enough to repeat.

    In ``benchmark`` mode the flow is ``certify``'s: a Case is generated from the
    Agent's requirement, the Agent answers it with a real model, and the Run is
    graded against the behaviors the requirement declared. What differs from
    ``certify`` is only who writes the Case and who grades it.
    """

    options = options or VerifyOptions()
    # In JSON mode nothing may reach stdout before the document itself.
    stage_output = _discard if as_json else output_fn

    agent, rejection = _select_agent(agent_id, registry_path, options.input_count)
    if agent is None:
        return _fail_early(agent_id, rejection, output_fn, as_json=as_json)

    # The live panel is wanted on a terminal, but its non-interactive fallback would
    # duplicate what the sectioned report already prints, so that path is silenced.
    llm_activity = LLMActivity(
        _discard,
        live_updates=not as_json and sys.stdout.isatty(),
    )
    if offline is None:
        try:
            offline = build_verify_runtime(
                options,
                output_fn=stage_output,
                activity_sink=llm_activity,
            )
        except Exception as exc:
            # Assembly only reads configuration: an unsupported mode, a plaintext
            # base URL, a missing provider credential. All of those are the
            # caller's mistake rather than a verdict about the Agent, so they are
            # reported as errors before an image is built. Catching broadly keeps
            # the SDK's own error types out of this module's imports.
            return _fail_early(agent_id, str(exc), output_fn, as_json=as_json)

    print_header(agent_id, stage_output, runtime=offline)
    report = _run_verification(
        agent=agent,
        offline=offline,
        llm_activity=llm_activity,
        stage_output=stage_output,
        keep_artifacts=keep_artifacts,
        output_path=output_path,
    )

    if as_json:
        output_fn(report.to_json())
    else:
        output_fn("")
        print_report(report, output_fn)
    return report.exit_code


def _select_agent(
    agent_id: str, registry_path: str | Path, input_count: int
) -> tuple[AgentRegistration | None, str]:
    """Resolve the Agent, or explain why verification cannot run at all."""

    if input_count < 1:
        return None, "--inputs must be at least 1"
    try:
        # Disabled Agents are verifiable on purpose: this is the check you run while
        # adapting, before an Agent is ever enabled for a batch.
        agent = load_registry(registry_path).find(agent_id, enabled_only=False)
    except (KeyError, ValueError) as exc:
        # str(KeyError) re-quotes its argument, which would leak into the report.
        return None, str(exc.args[0] if exc.args else exc)

    rejection = _preflight_error(agent)
    return (None, rejection) if rejection else (agent, "")


def _run_verification(
    *,
    agent: AgentRegistration,
    offline: VerifyRuntime,
    llm_activity: LLMActivity,
    stage_output: Callable[[str], None],
    keep_artifacts: bool,
    output_path: str | Path | None = None,
) -> VerifyReport:
    """Run the Case and summarize it, cleaning up unless the log is worth keeping."""

    benchmark = offline.mode == BENCHMARK_MODE
    # A graded Run is worth archiving, so benchmark mode writes where certify
    # writes. A startup probe is not, so it stays in a directory that is removed.
    artifact_dir = None if benchmark else Path(tempfile.mkdtemp(prefix=ARTIFACT_PREFIX))
    keep = keep_artifacts or benchmark
    try:
        execution = run_benchmark_once(
            # Startup asks about the Agent, not about coverage, so it always runs
            # one Case. A benchmark honors the count the Registry declared, the
            # same way certify does.
            (agent if benchmark else replace(agent, case_count=1),),
            runner=offline.runner,
            output_path=_artifact_path(agent.agent_id, artifact_dir, output_path),
            output_fn=_discard,  # the sectioned report owns all verify output
            viewer_starter=None,
            llm_activity=llm_activity,
            progress=VerifyProgress(
                stage_output,
                llm_activity=llm_activity,
                call_count=lambda: offline.captured_pair_count,
            ),
        )
        return _build_report(
            agent_id=agent.agent_id,
            execution=execution,
            offline=offline,
            keep_artifacts=keep,
        )
    finally:
        if artifact_dir is not None and not keep:
            shutil.rmtree(artifact_dir, ignore_errors=True)


def _artifact_path(
    agent_id: str,
    artifact_dir: Path | None,
    output_path: str | Path | None,
) -> Path:
    if output_path is not None:
        return Path(output_path)
    name = f"verify-{_safe_name(agent_id)}.jsonl"
    if artifact_dir is not None:
        return artifact_dir / name
    return _results_dir() / name


def _results_dir() -> Path:
    """The repository's results directory, matching where certify writes."""

    return Path(DEFAULT_REGISTRY_PATH).resolve().parent.parent / "results"


def _build_report(
    *,
    agent_id: str,
    execution: BenchmarkExecution,
    offline: VerifyRuntime,
    keep_artifacts: bool,
) -> VerifyReport:
    """Turn the suite outcome into a startup verdict."""

    result = execution.result
    item = _agent_item(result, agent_id)
    # Built once as a passing report and narrowed with `replace` below. A dict of
    # shared keyword arguments would be untyped at every construction site, which
    # is exactly where a missing or misspelled field should be caught.
    report = VerifyReport(
        agent_id=agent_id,
        verdict=PASS,
        captured_pairs=offline.captured_pair_count,
        substituted_secrets=offline.substituted_secrets,
        result_log=(
            execution.result_log.path
            if keep_artifacts and execution.result_log is not None
            else None
        ),
        calls=offline.calls,
        model_source=offline.model_source,
        model=offline.model,
        mode=offline.mode,
        provider_model=offline.provider_model,
    )
    if item is not None:
        report = replace(
            report,
            completed_cases=item.completed_case_count,
            requested_cases=item.requested_case_count,
            judge_status=_judge_status(item),
            **_judgment_detail(item),
        )

    if item is None or not _started(item):
        reason = "Agent did not complete startup"
        if item is not None and item.error_type is not None:
            reason = f"{item.error_type}: {item.error_message}"
        return replace(report, verdict=FAIL, reason=reason)

    # The SDK, not this command, decides whether the Run satisfied its Case. A
    # local Judge still answers only the startup question, but it answers it
    # through the same report contract an official Judge would use.
    judgment = _judge_rejection(item)
    if judgment is not None:
        return replace(report, verdict=FAIL, reason=judgment)

    if offline.captured_pair_count < 1:
        return replace(
            report,
            verdict=FAIL,
            reason=(
                "Agent ran but no model call was captured, so its LLM traffic "
                "is not observable"
            ),
        )

    return report


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
    return next(
        (status for status in statuses if status != STATUS_PASS), STATUS_PASS
    )


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


def _agent_item(
    result: BenchmarkSuiteResult | None, agent_id: str
) -> SuiteAgentResult | None:
    if result is None or result.skipped_count != 0 or len(result.items) != 1:
        return None
    item = result.items[0]
    return item if item.agent_id == agent_id else None


def _started(item: SuiteAgentResult) -> bool:
    """Startup succeeded when the single Case ran end to end without harness errors."""

    return (
        item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def _discard(_: str) -> None:
    """Swallow shared-execution chatter that the verify report replaces."""


def _preflight_error(agent: AgentRegistration) -> str | None:
    """Reject Agents that cannot answer the question verification asks."""

    selected = runtime_type(agent.path)
    if selected != "docker":
        return (
            f"Agent '{agent.agent_id}' uses the {selected!r} runtime. Offline "
            "verification requires the Docker runtime so model traffic can be "
            "intercepted."
        )
    if InterceptionConfig.from_agent_dir(agent.path) is None:
        return (
            f"Agent '{agent.agent_id}' declares no [llm_interception] section, so "
            "its model calls cannot be captured or served offline."
        )
    return None


def _probe_text(value: str) -> str:
    if not value.startswith(INPUT_FILE_MARKER):
        return value
    return Path(value[len(INPUT_FILE_MARKER) :]).expanduser().read_text(
        encoding="utf-8"
    )


def _safe_name(agent_id: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in agent_id
    ).strip("-")
    return cleaned or "agent"


FEATURE = CommandFeature(
    name="verify",
    help="Run one Agent through a real SDK Run using local Case and Judge Providers.",
    description=(
        "Drive one registered Agent through the DefuzeX SDK with the Case and "
        "Judge Provider ports supplied locally, so no DefuzeX credential is "
        "needed and the Registry is never changed. 'startup' mode blocks network "
        "egress, serves locally generated model replies, and checks only that the "
        "Agent responds and its model calls are captured. 'benchmark' mode runs "
        "the same flow as certify: a Case generated from the Agent's requirement, "
        "answered with a real model, graded against the declared behaviors."
    ),
    configure=configure_parser,
    execute=execute,
)
