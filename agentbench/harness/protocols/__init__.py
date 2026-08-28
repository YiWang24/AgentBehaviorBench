"""Structural interfaces used by the benchmark harness."""

from .providers import (
    CaseGenerationContext,
    CaseLike,
    HistoryItemLike,
    JudgeContext,
    SubmissionLike,
)
from .sdk import STATUS_PASS, SDKReport, SDKRun, SDKRunFactory, SDKTestInput

__all__ = [
    "STATUS_PASS",
    "CaseGenerationContext",
    "CaseLike",
    "HistoryItemLike",
    "JudgeContext",
    "SDKReport",
    "SDKRun",
    "SDKRunFactory",
    "SDKTestInput",
    "SubmissionLike",
]
