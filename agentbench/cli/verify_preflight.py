"""Preflight: everything `verify` can check without the DefuzeX SDK.

Preflight answers two questions about the Agent and nothing else — does it run,
and is its model traffic observable. It invokes the adapter directly instead of
driving an SDK Run, because an Agent has to stay checkable while the host is
still being set up. A missing SDK or provider key is a gap in the host, and
folding it in here would report it as an Agent failure, which it is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentbench.harness import AgentRunner, RunningAgent
from agentbench.harness.registry import AgentRegistration, load_registry
from agentbench.harness.submission import is_blank
from agentbench.runtime.agentcontainer import runtime_type
from agentbench.runtime.interception import (
    InterceptionConfig,
    InterceptionTraceState,
)

from .progress import StageReporter
from .verify_runtime import VerifyOptions

PROBE_THREAD_PREFIX = "verify_preflight"

STAGE_START = "Starting Agent..."
STAGE_PROBE = "Probing Agent..."
STAGE_CAPTURE = "Capturing model traffic..."

UNOBSERVABLE = (
    "Agent ran but no model call was captured, so its LLM traffic is not observable"
)


class SubjectError(Exception):
    """The caller pointed verify at something it cannot answer for.

    Distinct from a failed verification: nothing was learned about the Agent, so
    the outcome is the caller's to fix rather than a verdict to act on.
    """


@dataclass(frozen=True, slots=True)
class VerifySubject:
    """One Agent that verification is able to run at all."""

    agent: AgentRegistration
    interception: InterceptionConfig

    @property
    def agent_id(self) -> str:
        return self.agent.agent_id


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """What preflight learned, and why it stopped when it did."""

    probes_sent: int = 0
    probes_answered: int = 0
    captured_pairs: int = 0
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.reason is None


def select_subject(
    agent_id: str, registry_path: str | Path, options: VerifyOptions
) -> VerifySubject:
    """Resolve the Agent, or explain why verification cannot run at all."""

    if options.probe_count < 1:
        raise SubjectError("--probes must be at least 1")
    if options.input_count < 1:
        raise SubjectError("--inputs must be at least 1")

    try:
        # Disabled Agents are verifiable on purpose: this is the check you run
        # while adapting an Agent, before it is ever enabled for a batch.
        agent = load_registry(registry_path).find(agent_id, enabled_only=False)
    except (KeyError, ValueError) as exc:
        # str(KeyError) re-quotes its argument, which would leak into the report.
        raise SubjectError(str(exc.args[0] if exc.args else exc)) from exc

    selected = runtime_type(agent.path)
    if selected != "docker":
        raise SubjectError(
            f"Agent '{agent_id}' uses the {selected!r} runtime. Verification "
            "requires the Docker runtime so model traffic can be intercepted."
        )
    interception = InterceptionConfig.from_agent_dir(agent.path)
    if interception is None:
        raise SubjectError(
            f"Agent '{agent_id}' declares no [llm_interception] section, so its "
            "model calls cannot be captured or served offline."
        )
    return VerifySubject(agent=agent, interception=interception)


def run_preflight(
    subject: VerifySubject,
    *,
    runner: AgentRunner,
    options: VerifyOptions,
    trace_state: InterceptionTraceState,
    stages: StageReporter,
) -> PreflightResult:
    """Start the Agent, probe it, and confirm its model traffic was captured."""

    stages.start_stage(STAGE_START)
    try:
        running = runner.start(subject.agent)
    except Exception as exc:
        detail = error_detail(exc)
        stages.finish_stage(False, detail)
        return PreflightResult(reason=detail)

    routes = len(subject.interception.routes)
    stages.finish_stage(
        True, f"{running.adapter_name} | {routes} route{'' if routes == 1 else 's'}"
    )
    with running:
        answered, reason = _probe(running, options, stages)

    # Read the pair count only after the container is closed, so the interceptor's
    # last response event has been consumed by the trace follower.
    pairs = trace_state.checkpoint()
    if reason is not None:
        return PreflightResult(
            probes_sent=options.probe_count,
            probes_answered=answered,
            captured_pairs=pairs,
            reason=reason,
        )

    stages.start_stage(STAGE_CAPTURE)
    stages.finish_stage(
        pairs >= 1, f"{pairs} request/response pair{'' if pairs == 1 else 's'}"
    )
    return PreflightResult(
        probes_sent=options.probe_count,
        probes_answered=answered,
        captured_pairs=pairs,
        reason=None if pairs >= 1 else UNOBSERVABLE,
    )


def _probe(
    running: RunningAgent, options: VerifyOptions, stages: StageReporter
) -> tuple[int, str | None]:
    """Send every probe, stopping at the first one the Agent did not answer."""

    stages.start_stage(STAGE_PROBE)
    answered = 0
    for index in range(1, options.probe_count + 1):
        try:
            invocation = running.invoke(
                options.probe_text,
                run_config={
                    "configurable": {"thread_id": f"{PROBE_THREAD_PREFIX}_{index}"}
                },
            )
        except Exception as exc:
            reason = f"Probe {index} failed: {error_detail(exc)}"
            stages.finish_stage(False, error_detail(exc))
            return answered, reason
        if is_blank(invocation.output):
            reason = f"Probe {index} completed but returned no usable output"
            stages.finish_stage(False, reason)
            return answered, reason
        answered += 1

    stages.finish_stage(True, f"{answered}/{options.probe_count} answered")
    return answered, None


def error_detail(exc: Exception) -> str:
    """Name the exception, and its message when it carries one."""

    message = str(exc).strip()
    return type(exc).__name__ if not message else f"{type(exc).__name__}: {message}"


__all__ = [
    "PreflightResult",
    "SubjectError",
    "VerifySubject",
    "error_detail",
    "run_preflight",
    "select_subject",
]
