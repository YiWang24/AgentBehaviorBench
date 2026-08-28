"""What this host needs before it can grade an Agent.

Nothing checked here says anything about the Agent: the credential a local
Provider needs to write a Case and grade a Run, and the live model the Agent
answers that Case with, are both host setup. They are therefore checked after
preflight, and their absence stops verification rather than failing it — an
Agent that started and answered has passed everything this host could ask.

The SDK itself is not checked. It is a hard dependency of the package, so a host
without it cannot reach this code at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agentbench.harness.errors import error_detail
from agentbench.harness.local import ChatModel
from agentbench.runtime.interception import DeepSeekProvider

from .progress import StageReporter
from .verify_runtime import VerifyOptions

STAGE_PROVIDERS = "Checking local Case and Judge Providers..."
STAGE_MODEL = "Checking the Agent's model target..."


@dataclass(frozen=True, slots=True)
class ProviderCheck:
    """Whether a graded benchmark can run, and what it would run against."""

    chat: ChatModel | None = None
    agent_model: str | None = None
    provider_model: str | None = None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.reason is None


def check_providers(
    options: VerifyOptions,
    *,
    environ: Mapping[str, str],
    stages: StageReporter,
) -> ProviderCheck:
    """Resolve both models, stopping at the first one this host cannot supply."""

    stages.start_stage(STAGE_PROVIDERS)
    try:
        chat = ChatModel.from_environment(environ, model=options.provider_model)
    except Exception as exc:
        return ProviderCheck(reason=_stopped(stages, exc))
    stages.finish_stage(True, f"judged by {chat.model}")

    stages.start_stage(STAGE_MODEL)
    try:
        agent_model = _agent_model(options, environ)
    except Exception as exc:
        return ProviderCheck(reason=_stopped(stages, exc))
    stages.finish_stage(True, agent_model)

    return ProviderCheck(
        chat=chat, agent_model=agent_model, provider_model=chat.model
    )


def _stopped(stages: StageReporter, exc: Exception) -> str:
    """Close the failed stage and hand its reason back to the report."""

    reason = error_detail(exc)
    stages.finish_stage(False, reason)
    return reason


def _agent_model(options: VerifyOptions, environ: Mapping[str, str]) -> str:
    """Resolve the live target now, so a bad slug is not a 401 minutes later."""

    target = DeepSeekProvider(options.model).resolve(environ)
    if not environ.get(target.credential_env, "").strip():
        raise RuntimeError(
            f"A graded benchmark needs {target.credential_env}. Set it in the "
            "environment or .env."
        )
    return target.model


__all__ = ["ProviderCheck", "check_providers"]
