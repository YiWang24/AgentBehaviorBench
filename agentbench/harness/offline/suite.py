"""Suite runner that forces local Providers for offline startup verification."""

from __future__ import annotations

from typing import Any

from ..result import BenchmarkSuiteResult
from ..runner.suite_runner import SuiteRunner
from .providers import DEFAULT_PROBE_TEXT, StartupCaseProvider, StartupJudgeProvider


class OfflineSuiteRunner(SuiteRunner):
    """Pin every run to the local Provider pair.

    ``run_benchmark_once`` deliberately does not forward Provider arguments, so they
    are injected here instead of widening the shared CLI execution path. Passing
    both Providers is what selects the SDK's local mode, which never reads
    ``DEFUZEX_API_KEY`` and never opens a Backend connection.
    """

    def __init__(
        self,
        *,
        max_inputs: int,
        probe_text: str = DEFAULT_PROBE_TEXT,
        **kwargs: Any,
    ) -> None:
        if max_inputs < 1:
            raise ValueError("Offline verification requires at least one input")
        super().__init__(**kwargs)
        self._max_inputs = max_inputs
        self._probe_text = probe_text

    def run_defuzex(self, registrations: Any, **kwargs: Any) -> BenchmarkSuiteResult:
        kwargs.update(
            case_provider=StartupCaseProvider(probe_text=self._probe_text),
            judge_provider=StartupJudgeProvider(),
            max_inputs=self._max_inputs,
            api_key=None,
            track_files=False,
            save_local=False,
        )
        return super().run_defuzex(registrations, **kwargs)
