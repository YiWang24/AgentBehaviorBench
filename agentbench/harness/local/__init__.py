"""Local stand-ins for the official KUMA Case and Judge services.

Supplying both Provider ports is what selects the SDK's local mode, so a Run
driven from here never resolves a DefuzeX credential and never opens a Backend
connection. Everything else about the Run — the state machine, the handshake,
the report — stays the SDK's.
"""

from .case import BEHAVIOR_SECTIONS, LocalCaseProvider
from .chat import ChatModel, LocalProviderError
from .judge import INSUFFICIENT, ISSUE, PASS, LocalJudgeProvider
from .suite import DEFAULT_MAX_INPUTS, LocalBenchmarkSuiteRunner

__all__ = [
    "BEHAVIOR_SECTIONS",
    "DEFAULT_MAX_INPUTS",
    "INSUFFICIENT",
    "ISSUE",
    "PASS",
    "ChatModel",
    "LocalBenchmarkSuiteRunner",
    "LocalCaseProvider",
    "LocalJudgeProvider",
    "LocalProviderError",
]
