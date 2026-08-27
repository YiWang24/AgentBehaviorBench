"""Verify one Agent starts and is observable, without any DefuzeX credentials."""

from __future__ import annotations

import shutil
import tempfile
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agentbench.harness import BenchmarkSuiteResult
from agentbench.harness.offline import DEFAULT_PROBE_TEXT, probe_inputs
from agentbench.harness.registry import AgentRegistration, load_registry
from agentbench.runtime.agentcontainer import runtime_type
from agentbench.runtime.interception import (
    DEFAULT_TRACE_MAX_BYTES,
    InterceptionConfig,
)

from agentbench.cli.environment import load_project_environment
from agentbench.cli.execution import run_benchmark_once
from agentbench.cli.offline_runtime import OfflineRuntime, build_offline_runtime
from agentbench.cli.TerminalUI import LLMActivity

from .base import CommandFeature
from .run import DEFAULT_REGISTRY_PATH

DEFAULT_INPUT_COUNT = 1
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
        "--inputs",
        type=int,
        default=DEFAULT_INPUT_COUNT,
        metavar="N",
        help="Number of probe inputs to send. Defaults to 1.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary result log instead of deleting it on exit.",
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
        help="Maximum captured payload bytes displayed per direction.",
    )


def execute(args: Namespace) -> int:
    load_project_environment(args.env_file)
    kwargs: dict[str, object] = {
        "input_count": args.inputs,
        "keep_artifacts": args.keep_artifacts,
    }
    if args.input is not None:
        kwargs["probe_text"] = _probe_text(args.input)
    if args.llm_trace != "off":
        kwargs["llm_trace"] = args.llm_trace
    if args.llm_trace_max_bytes != DEFAULT_TRACE_MAX_BYTES:
        kwargs["llm_trace_max_bytes"] = args.llm_trace_max_bytes
    return verify(args.agent_id, **kwargs)


def verify(
    agent_id: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    probe_text: str = DEFAULT_PROBE_TEXT,
    input_count: int = DEFAULT_INPUT_COUNT,
    keep_artifacts: bool = False,
    output_fn: Callable[[str], None] = print,
    offline: OfflineRuntime | None = None,
    llm_trace: str = "off",
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES,
) -> int:
    """Start one Agent offline and confirm its model traffic is observable.

    Nothing here reads ``DEFUZEX_API_KEY`` or ``OPENROUTER_API_KEY``, contacts a
    network, or writes the Registry. A pass means the adapter and runtime are
    healthy; it says nothing about benchmark quality.
    """

    if input_count < 1:
        output_fn("Verification error: --inputs must be at least 1.")
        return 2

    registry = load_registry(registry_path)
    try:
        # Disabled Agents are verifiable on purpose: this is the check you run while
        # adapting, before an Agent is ever enabled for a batch.
        agent = registry.find(agent_id, enabled_only=False)
    except (KeyError, ValueError) as exc:
        output_fn(f"Verification error: {exc}")
        return 2

    preflight = _preflight_error(agent)
    if preflight is not None:
        output_fn(f"Verification error: {preflight}")
        return 2

    output_fn(f"Verifying Agent offline: {agent_id}")
    output_fn(
        "No DefuzeX or provider credentials are used, network egress is blocked, "
        "and the Registry is not modified."
    )

    # One Case keeps verification about startup rather than benchmark coverage.
    target = replace(agent, case_count=1)
    llm_activity = LLMActivity(output_fn)
    offline = offline or build_offline_runtime(
        max_inputs=input_count,
        probes=probe_inputs(probe_text, count=input_count),
        output_fn=output_fn,
        llm_trace=llm_trace,
        llm_trace_max_bytes=llm_trace_max_bytes,
        activity_sink=llm_activity,
    )

    artifact_dir = Path(tempfile.mkdtemp(prefix=ARTIFACT_PREFIX))
    try:
        execution = run_benchmark_once(
            (target,),
            runner=offline.runner,
            output_path=artifact_dir / f"verify-{_safe_name(agent_id)}.jsonl",
            output_fn=output_fn,
            viewer_starter=None,
            llm_activity=llm_activity,
        )
        exit_code = _report(
            agent_id=agent_id,
            execution_result=execution.result,
            exit_code=execution.exit_code,
            captured_pairs=offline.captured_pair_count,
            substituted_secrets=offline.substituted_secrets,
            output_fn=output_fn,
        )
        if keep_artifacts and execution.result_log is not None:
            output_fn(f"Result log kept: {execution.result_log.path}")
        return exit_code
    finally:
        if not keep_artifacts:
            shutil.rmtree(artifact_dir, ignore_errors=True)


def _report(
    *,
    agent_id: str,
    execution_result: BenchmarkSuiteResult | None,
    exit_code: int,
    captured_pairs: int,
    substituted_secrets: tuple[str, ...],
    output_fn: Callable[[str], None],
) -> int:
    """Turn the suite outcome into a startup verdict."""

    if substituted_secrets:
        output_fn(
            "Placeholder secrets substituted for offline run: "
            + ", ".join(substituted_secrets)
        )

    if execution_result is None or not _agent_started(execution_result, agent_id):
        output_fn(f"Verification FAILED. Agent '{agent_id}' did not complete startup.")
        return exit_code or 1

    output_fn(f"Captured LLM request/response pairs: {captured_pairs}")
    if captured_pairs < 1:
        output_fn(
            f"Verification FAILED. Agent '{agent_id}' ran but no model call was "
            "captured, so its LLM traffic is not observable."
        )
        return 1

    output_fn(
        f"Verification PASSED. Agent '{agent_id}' starts, responds, and its model "
        "traffic is fully captured."
    )
    return 0


def _agent_started(result: BenchmarkSuiteResult, agent_id: str) -> bool:
    """Startup succeeded when the single Case ran end to end without harness errors."""

    if result.skipped_count != 0 or len(result.items) != 1:
        return False
    item = result.items[0]
    return (
        item.agent_id == agent_id
        and item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


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
    help="Check offline that one Agent starts and its model traffic is captured.",
    description=(
        "Start one registered Agent with network egress blocked and locally "
        "generated model replies, then confirm it responds and that every model "
        "call is captured. Uses no DefuzeX or provider credentials and never "
        "changes the Registry."
    ),
    configure=configure_parser,
    execute=execute,
)
