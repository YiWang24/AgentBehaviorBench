"""Execute DefuzeX SDK benchmark runs through registered agents."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from kuma import KumaClient, create_run

from ..errors import AgentInvocationError, ProviderSelectionError, error_detail
from ..progress import ProgressCallback, emit_progress
from ..protocols import SDKReport, SDKRun, SDKRunFactory
from ..registry import AgentRegistration
from ..result import BenchmarkResult, BenchmarkStepFailure, BenchmarkStepResult
from .agent_runner import AgentRunner
from .running_agent import RunningAgent

StepStartCallback = Callable[[str, str, object], None]
StepCompleteCallback = Callable[[str, BenchmarkStepResult], None]
StepFailureCallback = Callable[[str, BenchmarkStepFailure], None]


class BenchmarkRunner:
    """Drive one DefuzeX SDK Run through a registered agent."""

    def __init__(
        self,
        *,
        agent_runner: AgentRunner | None = None,
        sdk_run_factory: SDKRunFactory | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._agent_runner = agent_runner or AgentRunner()
        self._sdk_run_factory = sdk_run_factory or create_run
        self._environ = os.environ if environ is None else environ

    def run_defuzex(
        self,
        registration: AgentRegistration,
        *,
        requirement_path: str | Path | None = None,
        case_provider: object | None = None,
        judge_provider: object | None = None,
        api_key: str | None = None,
        max_inputs: int | None = None,
        allow_local: bool = False,
        track_files: bool = True,
        save_local: bool = False,
        on_progress: ProgressCallback | None = None,
        on_step_start: StepStartCallback | None = None,
        on_step_complete: StepCompleteCallback | None = None,
        on_step_failure: StepFailureCallback | None = None,
    ) -> BenchmarkResult:
        """Start one Agent, create its SDK Run, and execute the handshake."""

        provider_mode, run_kwargs = self._prepare_defuzex(
            registration=registration,
            requirement_path=requirement_path,
            case_provider=case_provider,
            judge_provider=judge_provider,
            api_key=api_key,
            max_inputs=max_inputs,
            allow_local=allow_local,
            track_files=track_files,
            save_local=save_local,
        )

        emit_progress(
            on_progress,
            stage="agent_start",
            status="started",
            agent_id=registration.agent_id,
        )
        try:
            running = self._agent_runner.start(registration)
        except Exception as exc:
            emit_progress(
                on_progress,
                stage="agent_start",
                status="failed",
                agent_id=registration.agent_id,
                detail=error_detail(exc),
            )
            raise

        emit_progress(
            on_progress,
            stage="agent_start",
            status="succeeded",
            agent_id=registration.agent_id,
            detail=running.adapter_name,
        )
        with running:
            emit_progress(
                on_progress,
                stage="case_generation",
                status="started",
                agent_id=registration.agent_id,
                detail=provider_mode,
            )
            try:
                sdk_run = self._sdk_run_factory(**run_kwargs)
            except Exception as exc:
                emit_progress(
                    on_progress,
                    stage="case_generation",
                    status="failed",
                    agent_id=registration.agent_id,
                    detail=error_detail(exc),
                )
                raise

            emit_progress(
                on_progress,
                stage="case_generation",
                status="succeeded",
                agent_id=registration.agent_id,
                detail=f"run={sdk_run.run_id}",
            )
            emit_progress(
                on_progress,
                stage="benchmark_execution",
                status="started",
                agent_id=registration.agent_id,
            )
            try:
                result = self._run_with_running(
                    registration,
                    sdk_run,
                    running,
                    on_step_start=on_step_start,
                    on_step_complete=on_step_complete,
                    on_step_failure=on_step_failure,
                )
            except Exception as exc:
                emit_progress(
                    on_progress,
                    stage="benchmark_execution",
                    status="failed",
                    agent_id=registration.agent_id,
                    detail=error_detail(exc),
                )
                raise

            judge_status = (
                result.report.status if result.report is not None else "no report"
            )
            emit_progress(
                on_progress,
                stage="benchmark_execution",
                status="succeeded",
                agent_id=registration.agent_id,
                detail=f"Judge: {judge_status}",
            )

        return BenchmarkResult(
            agent_id=result.agent_id,
            adapter_name=result.adapter_name,
            run_id=result.run_id,
            run_state=result.run_state,
            report=result.report,
            steps=result.steps,
            history_count=result.history_count,
            provider_mode=provider_mode,
        )

    def run(self, registration: AgentRegistration, sdk_run: SDKRun) -> BenchmarkResult:
        """Execute the SDK get_input/invoke/submit handshake to completion."""

        with self._agent_runner.start(registration) as running:
            return self._run_with_running(registration, sdk_run, running)

    def validate_defuzex(
        self,
        registration: AgentRegistration,
        *,
        requirement_path: str | Path | None = None,
        case_provider: object | None = None,
        judge_provider: object | None = None,
        api_key: str | None = None,
        max_inputs: int | None = None,
        allow_local: bool = False,
        track_files: bool = True,
        save_local: bool = False,
    ) -> str:
        """Validate shared SDK and Provider configuration without networking."""

        provider_mode, _ = self._prepare_defuzex(
            registration=registration,
            requirement_path=requirement_path,
            case_provider=case_provider,
            judge_provider=judge_provider,
            api_key=api_key,
            max_inputs=max_inputs,
            allow_local=allow_local,
            track_files=track_files,
            save_local=save_local,
        )
        return provider_mode

    def _run_with_running(
        self,
        registration: AgentRegistration,
        sdk_run: SDKRun,
        running: RunningAgent,
        *,
        on_step_start: StepStartCallback | None = None,
        on_step_complete: StepCompleteCallback | None = None,
        on_step_failure: StepFailureCallback | None = None,
    ) -> BenchmarkResult:
        """Execute an SDK handshake through an Agent that is already running."""

        steps: list[BenchmarkStepResult] = []
        report: SDKReport | None = None
        run_config = {"configurable": {"thread_id": sdk_run.run_id}}

        adapter_name = running.adapter_name
        while (test_input := sdk_run.get_input(full=True)) is not None:
            if on_step_start is not None:
                on_step_start(
                    registration.agent_id,
                    test_input.input_id,
                    test_input.payload,
                )
            try:
                invocation = running.invoke(
                    test_input.payload,
                    run_config=run_config,
                )
            except Exception as exc:
                if on_step_failure is not None:
                    on_step_failure(
                        registration.agent_id,
                        _step_failure(test_input.input_id, test_input.payload, exc),
                    )
                self._record_failed_submission(sdk_run, exc)
                # The cause has to be in the message, not just __cause__: results
                # carry the error as plain strings, so anything left on the
                # exception object is lost before a report can show it.
                raise AgentInvocationError(
                    f"Agent {registration.agent_id!r} failed for "
                    f"SDK Input {test_input.input_id!r}: {error_detail(exc)}"
                ) from exc

            step = BenchmarkStepResult(
                input_id=test_input.input_id,
                payload=test_input.payload,
                invocation=invocation,
            )
            try:
                report = sdk_run.submit(invocation.output)
            except Exception as exc:
                if on_step_failure is not None:
                    on_step_failure(
                        registration.agent_id,
                        _step_failure(
                            test_input.input_id,
                            test_input.payload,
                            exc,
                            output=invocation.output,
                            raw_output=invocation.raw_output,
                        ),
                    )
                raise

            steps.append(step)
            if on_step_complete is not None:
                on_step_complete(registration.agent_id, step)

        if report is None:
            report = sdk_run.report
        return BenchmarkResult(
            agent_id=registration.agent_id,
            adapter_name=adapter_name,
            run_id=sdk_run.run_id,
            run_state=sdk_run.state,
            report=report,
            steps=tuple(steps),
            history_count=len(sdk_run.history),
        )

    def _prepare_defuzex(
        self,
        *,
        registration: AgentRegistration,
        requirement_path: str | Path | None,
        case_provider: object | None,
        judge_provider: object | None,
        api_key: str | None,
        max_inputs: int | None,
        allow_local: bool,
        track_files: bool,
        save_local: bool,
    ) -> tuple[str, dict[str, object]]:
        provider_mode, run_kwargs = self._sdk_run_configuration(
            registration=registration,
            requirement_path=requirement_path,
            case_provider=case_provider,
            judge_provider=judge_provider,
            api_key=api_key,
            max_inputs=max_inputs,
            allow_local=allow_local,
            track_files=track_files,
            save_local=save_local,
        )
        if self._sdk_run_factory is create_run and provider_mode == "official":
            # Constructing the client validates the credential's shape without
            # making a request, so a bad key fails here rather than mid-Run.
            api_key = run_kwargs.get("api_key")
            KumaClient(api_key=api_key if isinstance(api_key, str) else None)
        return provider_mode, run_kwargs

    @staticmethod
    def _record_failed_submission(sdk_run: SDKRun, exc: Exception) -> None:
        """Best-effort recording keeps SDK history truthful on agent failure."""

        try:
            sdk_run.submit(
                status="failed",
                error=f"Agent invocation failed: {type(exc).__name__}",
            )
        except Exception:
            pass

    def _sdk_run_configuration(
        self,
        *,
        registration: AgentRegistration,
        requirement_path: str | Path | None,
        case_provider: object | None,
        judge_provider: object | None,
        api_key: str | None,
        max_inputs: int | None,
        allow_local: bool,
        track_files: bool,
        save_local: bool,
    ) -> tuple[str, dict[str, object]]:
        has_case_provider = case_provider is not None
        has_judge_provider = judge_provider is not None
        if has_case_provider != has_judge_provider:
            raise ProviderSelectionError(
                "Provide both case_provider and judge_provider for local mode"
            )

        common: dict[str, object] = {
            "repo_path": registration.path,
            "allow_local": allow_local,
            "track_files": track_files,
            "save_local": save_local,
        }
        if has_case_provider and has_judge_provider:
            # Local Providers may still want the Agent's requirement: the SDK parses
            # it and enforces its declared input_type, so a local Case stays
            # consistent with what the official Providers would have demanded. It
            # stays optional because an Agent is verifiable before it has one.
            resolved_requirement = requirement_path or registration.requirement_path
            if resolved_requirement is not None:
                common["requirement_path"] = resolved_requirement
            if max_inputs is None:
                raise ProviderSelectionError(
                    "Local custom Providers require max_inputs"
                )
            common.update(
                case_provider=case_provider,
                judge_provider=judge_provider,
                max_inputs=max_inputs,
            )
            return "local", common

        resolved_key = self._official_api_key(api_key)
        if resolved_key is None:
            raise ProviderSelectionError(
                "No DefuzeX API key or local Provider pair is configured. Set "
                "DEFUZEX_API_KEY or provide both case_provider and "
                "judge_provider."
            )
        resolved_requirement = requirement_path or registration.requirement_path
        if resolved_requirement is None:
            raise ProviderSelectionError(
                "Official DefuzeX Providers require a registered or explicit "
                "requirement_path"
            )
        common["requirement_path"] = resolved_requirement
        common["api_key"] = resolved_key
        return "official", common

    def _official_api_key(self, explicit: str | None) -> str | None:
        """Resolve the API key without logging secrets."""

        return explicit or self._environ.get("DEFUZEX_API_KEY")



def _step_failure(
    input_id: str,
    payload: object,
    exc: Exception,
    *,
    output: object | None = None,
    raw_output: object | None = None,
) -> BenchmarkStepFailure:
    return BenchmarkStepFailure(
        input_id=input_id,
        payload=payload,
        output=output,
        raw_output=raw_output,
        error_type=type(exc).__name__,
        error_message=str(exc),
    )
