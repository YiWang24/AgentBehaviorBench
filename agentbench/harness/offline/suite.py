"""Suite runner that forces local providers for offline startup verification."""

from __future__ import annotations

from typing import Any

from ..result import BenchmarkSuiteResult
from ..runner.suite_runner import SuiteRunner
from .run import OfflineCaseProvider, OfflineJudgeProvider


class OfflineSuiteRunner(SuiteRunner):
    """Pin every run to the local provider pair.

    ``run_benchmark_once`` deliberately does not forward provider arguments, so they
    are injected here instead of widening the shared CLI execution path.
    """

    def __init__(self, *, max_inputs: int, **kwargs: Any) -> None:
        if max_inputs < 1:
            raise ValueError("Offline verification requires at least one input")
        super().__init__(**kwargs)
        self._max_inputs = max_inputs

    def run_defuzex(self, registrations: Any, **kwargs: Any) -> BenchmarkSuiteResult:
        kwargs.update(
            case_provider=OfflineCaseProvider(),
            judge_provider=OfflineJudgeProvider(),
            max_inputs=self._max_inputs,
            api_key=None,
            track_files=False,
            save_local=False,
        )
        return super().run_defuzex(registrations, **kwargs)
