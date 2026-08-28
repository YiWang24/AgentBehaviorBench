"""Local Case and Judge Providers that ask only whether an Agent starts.

These are real DefuzeX Providers: the SDK owns the Case, the Run state machine,
and the Judgment, exactly as it does for an official run. Only the two Provider
ports are supplied locally, which is what removes the need for
``DEFUZEX_API_KEY`` — the SDK never builds a Backend client when both Providers
are custom.

The verdict is deliberately about health, not quality. Startup verification
serves replies from a local mock model, so the Agent's wording carries no signal
worth grading; what it does prove is that the adapter ran, the handshake held,
and every Input came back answered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocols.providers import CaseGenerationContext, JudgeContext
from ..submission import COMPLETED, answered, failure_reason

DEFAULT_PROBE_TEXT = "Reply with a short confirmation that you received this message."

CASE_ID = "case_startup_probe_v1"
REPORT_ID = "report_startup_probe_v1"
INPUT_PREFIX = "input_startup_probe"

STATUS_PASS = "pass"
STATUS_ISSUE = "issue"


@dataclass(frozen=True, slots=True)
class StartupCaseProvider:
    """Emit one text probe per requested Input.

    ``requirement_required`` is False because verification has to work while an
    Agent is still being adapted, before it has a requirement file. When one does
    exist the SDK still parses it and enforces its declared ``input_type``, so the
    Case stays consistent with what the official Providers would demand.
    """

    probe_text: str = DEFAULT_PROBE_TEXT
    requirement_required: bool = False

    def generate_case(self, context: CaseGenerationContext) -> dict[str, Any]:
        return {
            "case_id": CASE_ID,
            "input_type": "text",
            "rubric": {"rule": "agent_started", "expects": "a non-empty reply"},
            "inputs": [
                {
                    "input_id": f"{INPUT_PREFIX}_{index}",
                    "payload_type": "text",
                    "payload": self.probe_text,
                }
                for index in range(1, context.max_inputs + 1)
            ],
        }


@dataclass(frozen=True, slots=True)
class StartupJudgeProvider:
    """Pass only when every Input was answered with usable output."""

    def judge(self, context: JudgeContext) -> dict[str, Any]:
        issues = [
            issue
            for item in context.history
            if (issue := _submission_issue(item)) is not None
        ]
        answered = len(context.history) - len(issues)
        return {
            "report_id": REPORT_ID,
            "status": STATUS_ISSUE if issues else STATUS_PASS,
            "confidence": 1.0,
            "stop_reason": "startup_probe_complete",
            "issues": issues,
            "extensions": {
                "answered_inputs": answered,
                "total_inputs": len(context.history),
            },
        }


def _submission_issue(item: Any) -> dict[str, str] | None:
    """Describe why one step failed startup, or None when it succeeded."""

    if answered(item):
        return None
    incomplete = item.submission.status != COMPLETED
    return {
        "code": "input_not_completed" if incomplete else "empty_output",
        "message": f"Input {item.test_input.input_id} {failure_reason(item)}",
    }


__all__ = [
    "CASE_ID",
    "DEFAULT_PROBE_TEXT",
    "INPUT_PREFIX",
    "REPORT_ID",
    "STATUS_ISSUE",
    "STATUS_PASS",
    "StartupCaseProvider",
    "StartupJudgeProvider",
]
