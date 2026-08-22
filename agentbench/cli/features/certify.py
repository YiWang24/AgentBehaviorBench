"""Certify one adapting Agent and promote it to ready."""

from __future__ import annotations

import re
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from agentbench.harness import BenchmarkSuiteResult, SuiteRunner
from agentbench.harness.registry import load_registry
from agentbench.runtime.interception import DEFAULT_TRACE_MAX_BYTES

from agentbench.cli.execution import run_benchmark_once
from agentbench.cli.environment import load_project_environment
from agentbench.cli.registry_status import RegistryStatusError, update_agent_status
from agentbench.cli.TerminalUI import LLMActivity
from agentbench.cli.trace_runtime import build_trace_suite_runner

from .base import CommandFeature
from .run import DEFAULT_REGISTRY_PATH


def configure_parser(parser: ArgumentParser) -> None:
    parser.add_argument("agent_id", help="Registered adapting Agent to certify.")
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Load host secrets and defaults from PATH instead of .env.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Optional base path for the append-only certification result.",
    )
    parser.add_argument(
        "--model",
        metavar="OPENROUTER_MODEL",
        help="OpenRouter model slug; defaults to OPENROUTER_MODEL.",
    )
    parser.add_argument(
        "--llm-trace",
        choices=("off", "terminal"),
        default="off",
        help="Print sanitized intercepted model requests and responses.",
    )
    parser.add_argument(
        "--llm-trace-max-bytes",
        type=int,
        default=DEFAULT_TRACE_MAX_BYTES,
        metavar="BYTES",
    )


def execute(args: Namespace) -> int:
    load_project_environment(args.env_file)
    kwargs: dict[str, object] = {"output_path": args.output}
    if args.model is not None:
        kwargs["model"] = args.model
    if args.llm_trace != "off":
        kwargs["llm_trace"] = args.llm_trace
    if args.llm_trace_max_bytes != DEFAULT_TRACE_MAX_BYTES:
        kwargs["llm_trace_max_bytes"] = args.llm_trace_max_bytes
    return certify(args.agent_id, **kwargs)


def certify(
    agent_id: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    output_path: str | Path | None = None,
    output_fn: Callable[[str], None] = print,
    suite_runner: SuiteRunner | None = None,
    llm_trace: str = "off",
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES,
    model: str | None = None,
) -> int:
    """Run one adapting Agent and promote it after adapter execution succeeds."""

    registry = load_registry(registry_path)
    try:
        agent = registry.find(agent_id)
    except (KeyError, ValueError) as exc:
        output_fn(f"Certification error: {exc}")
        return 2

    if agent.status == "ready":
        output_fn(f"Agent '{agent_id}' is already ready.")
        return 0
    if agent.status != "adapting":
        output_fn(
            f"Certification error: Agent '{agent_id}' has status "
            f"'{agent.status}', expected 'adapting'."
        )
        return 2

    artifact_base = output_path or _default_output_path(registry_path, agent_id)
    output_fn(f"Certifying adapting Agent: {agent_id}")
    output_fn(
        "The registry will change to ready if the Agent completes its Cases "
        "without invocation errors."
    )
    llm_activity = LLMActivity(output_fn)
    execution = run_benchmark_once(
        (agent,),
        runner=suite_runner
        or build_trace_suite_runner(
            mode=llm_trace,
            max_bytes=llm_trace_max_bytes,
            output_fn=output_fn,
            model=model,
            activity_sink=llm_activity,
        ),
        output_path=artifact_base,
        output_fn=output_fn,
        viewer_starter=None,
        llm_activity=llm_activity,
    )
    if execution.result is None or not _agent_completed_certification(
        execution.result, agent_id
    ):
        output_fn(f"Certification failed. Agent '{agent_id}' remains adapting.")
        return execution.exit_code

    try:
        update_agent_status(
            registry_path,
            agent_id,
            expected_status="adapting",
            new_status="ready",
        )
    except RegistryStatusError as exc:
        output_fn(f"Certification passed, but registry update failed: {exc}")
        return 2

    if execution.result.passed:
        output_fn(f"Certification passed. Agent '{agent_id}' is now ready.")
    else:
        output_fn(
            f"Certification completed with benchmark failures. Agent '{agent_id}' is now ready."
        )
    return 0


def _agent_completed_certification(
    result: BenchmarkSuiteResult, agent_id: str
) -> bool:
    if result.skipped_count != 0:
        return False
    if len(result.items) != 1:
        return False
    item = result.items[0]
    return (
        item.agent_id == agent_id
        and item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def _default_output_path(registry_path: str | Path, agent_id: str) -> Path:
    repo_root = Path(registry_path).resolve().parent.parent
    safe_agent_id = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_id).strip("-")
    return repo_root / "results" / f"certify-{safe_agent_id or 'agent'}.jsonl"


FEATURE = CommandFeature(
    name="certify",
    help="Run one adapting Agent and promote it to ready after execution succeeds.",
    description=(
        "Execute the full benchmark flow for one adapting Agent and update "
        "its registry status after it completes all requested Cases without "
        "invocation errors."
    ),
    configure=configure_parser,
    execute=execute,
)
