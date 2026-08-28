"""The KUMA SDK half of `verify`'s prerequisites.

Nothing checked here says anything about the Agent. The DefuzeX SDK, the
credential a local Provider needs to write a Case and grade a Run, and the live
model the Agent answers that Case with are all host setup. They are therefore
checked after preflight, and their absence stops verification rather than
failing it: an Agent that started and answered has passed everything this host
was able to ask.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agentbench.runtime.interception import DeepSeekProvider

from .progress import StageReporter
from .verify_runtime import VerifyOptions

STAGE_SDK = "Checking DefuzeX SDK..."
STAGE_PROVIDERS = "Checking local Case and Judge Providers..."
STAGE_MODEL = "Checking the Agent's model target..."


@dataclass(frozen=True, slots=True)
class _Resolved:
    """A completed check: what it produced, and what to print for it."""

    value: object
    detail: str


@dataclass(frozen=True, slots=True)
class ProviderCheck:
    """Whether a graded benchmark can run, and what it would run against."""

    chat: object | None = None
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
    """Confirm the SDK, the Provider credential, and the Agent's model target.

    Checked in dependency order, so the first thing actually missing is what gets
    reported rather than whatever failed loudest.
    """

    sdk_detail = _stage(stages, STAGE_SDK, _import_sdk)
    if isinstance(sdk_detail, str):
        return ProviderCheck(reason=sdk_detail)

    chat = _stage(stages, STAGE_PROVIDERS, lambda: _chat_model(options, environ))
    if isinstance(chat, str):
        return ProviderCheck(reason=chat)

    agent_model = _stage(stages, STAGE_MODEL, lambda: _agent_model(options, environ))
    if isinstance(agent_model, str):
        return ProviderCheck(reason=agent_model)

    return ProviderCheck(
        chat=chat.value,
        agent_model=agent_model.value,
        provider_model=getattr(chat.value, "model", None),
    )


def _stage(
    stages: StageReporter, label: str, check: Callable[[], _Resolved]
) -> _Resolved | str:
    """Render one check, returning its result or the reason it stopped the run."""

    stages.start_stage(label)
    try:
        resolved = check()
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        stages.finish_stage(False, reason)
        return reason
    stages.finish_stage(True, resolved.detail)
    return resolved


def _import_sdk() -> _Resolved:
    try:
        import defuzex
    except ImportError as exc:
        # ImportError rather than ModuleNotFoundError: a half-installed SDK
        # fails the same way for the caller, and reads the same in the report.
        raise RuntimeError(
            "The DefuzeX (KUMA) SDK is not importable in the active Python "
            "environment, so no Case can be generated or graded."
        ) from exc
    version = getattr(defuzex, "__version__", None)
    return _Resolved(defuzex, f"defuzex {version}" if version else "defuzex")


def _chat_model(options: VerifyOptions, environ: Mapping[str, str]) -> _Resolved:
    # Imported here because it pulls in the DefuzeX SDK, which preflight and
    # every Agent-only caller must keep out of their import graph.
    from agentbench.harness.local import ChatModel

    chat = ChatModel.from_environment(environ, model=options.provider_model)
    return _Resolved(chat, f"judged by {chat.model}")


def _agent_model(options: VerifyOptions, environ: Mapping[str, str]) -> _Resolved:
    """Resolve the live target now, so a bad slug is not a 401 minutes later."""

    target = DeepSeekProvider(options.model).resolve(environ)
    if not environ.get(target.credential_env, "").strip():
        raise RuntimeError(
            f"A graded benchmark needs {target.credential_env}. Set it in the "
            "environment or .env, or pass --preflight-only."
        )
    return _Resolved(target.model, target.model)


__all__ = ["ProviderCheck", "check_providers"]
