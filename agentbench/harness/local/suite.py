"""Suite runner that swaps only the two Provider ports for local ones."""

from __future__ import annotations

from typing import Any

from ..result import BenchmarkSuiteResult
from ..runner.suite_runner import SuiteRunner
from .case import LocalCaseProvider
from .chat import ChatModel
from .judge import LocalJudgeProvider

DEFAULT_MAX_INPUTS = 3


class LocalBenchmarkSuiteRunner(SuiteRunner):
    """Run the full benchmark with locally generated Cases and local judging.

    Everything the shared execution path already sets — ``allow_local``,
    ``track_files``, the progress and step callbacks — is left alone, so a local
    Run differs from an official one only in who writes the Case and who grades
    it. That is the whole point: it exercises the SDK exactly as ``certify`` does.
    """

    def __init__(
        self,
        *,
        model: ChatModel,
        max_inputs: int = DEFAULT_MAX_INPUTS,
        **kwargs: Any,
    ) -> None:
        if max_inputs < 1:
            raise ValueError("A local benchmark requires at least one input")
        super().__init__(**kwargs)
        self._model = model
        self._max_inputs = max_inputs

    @property
    def model(self) -> ChatModel:
        return self._model

    def run_defuzex(self, registrations: Any, **kwargs: Any) -> BenchmarkSuiteResult:
        kwargs.update(
            case_provider=LocalCaseProvider(model=self._model),
            judge_provider=LocalJudgeProvider(model=self._model),
            max_inputs=self._max_inputs,
            api_key=None,
        )
        return super().run_defuzex(registrations, **kwargs)


__all__ = ["DEFAULT_MAX_INPUTS", "LocalBenchmarkSuiteRunner"]
