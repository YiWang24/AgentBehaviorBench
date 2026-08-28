"""Structural interfaces used by the benchmark harness."""

from .providers import (
    CaseGenerationContext,
    HistoryItemLike,
    JudgeContext,
    SubmissionLike,
)
from .sdk import SDKReport, SDKRun, SDKRunFactory, SDKTestInput

__all__ = [
    "CaseGenerationContext",
    "HistoryItemLike",
    "JudgeContext",
    "SDKReport",
    "SDKRun",
    "SDKRunFactory",
    "SDKTestInput",
    "SubmissionLike",
]
