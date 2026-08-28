"""A local stand-in for the official DefuzeX Judge service."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kuma.providers import JudgeContext
from ..submission import COMPLETED, answered, failure_reason
from .chat import ChatModel, LocalProviderError
from .prompts import JUDGE_SYSTEM, judge_prompt

REPORT_ID = "report_local_behavior_v1"

PASS = "pass"
ISSUE = "issue"
INSUFFICIENT = "insufficient_evidence"
STATUSES = frozenset({PASS, ISSUE, INSUFFICIENT})

MAX_OUTPUT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class LocalJudgeProvider:
    """Grade a finished Run against the behavior spec its Case published.

    This mirrors ``OfficialJudgeProvider``: a completed history goes in and a
    normalized Judgment comes out. The official service uploads Evidence and
    judges server-side against a private rubric; here the rubric arrived in the
    Case and the reasoning happens locally, but the SDK still validates and
    normalizes the result into the same ``TestReport``.
    """

    model: ChatModel

    def judge(self, context: JudgeContext) -> dict[str, Any]:
        history = tuple(context.history)
        if not history:
            return _report(
                INSUFFICIENT,
                confidence=1.0,
                summary="The Run produced no submissions to judge.",
                stop_reason="empty_history",
            )
        if not any(answered(item) for item in history):
            # Every step failed, so there is nothing for a model to weigh. Saying
            # so directly is both cheaper and more honest than asking it to.
            return _report(
                INSUFFICIENT,
                confidence=1.0,
                summary="The Agent answered none of its Inputs.",
                stop_reason="no_agent_output",
                issues=[
                    {
                        "code": "no_agent_output",
                        "message": _failure_text(item),
                        "step_id": item.test_input.input_id,
                    }
                    for item in history
                ],
            )

        rubric = _rubric(context)
        reply = self.model.json_object(
            system=JUDGE_SYSTEM,
            user=judge_prompt(
                behaviors_to_test=rubric["behaviors_to_test"],
                prohibited_behaviors=rubric["prohibited_behaviors"],
                transcript=_transcript(history),
            ),
        )
        return _report(
            _status(reply),
            confidence=_confidence(reply.get("confidence")),
            summary=str(reply.get("summary") or "").strip(),
            stop_reason="behavior_review_complete",
            issues=_issues(reply.get("issues")),
            step_results=_step_results(reply.get("step_results")),
        )


def _rubric(context: JudgeContext) -> dict[str, str]:
    """Read the behavior spec the Case published, or say it is missing."""

    rubric = getattr(context.case, "rubric", None)
    if not isinstance(rubric, Mapping):
        raise LocalProviderError(
            "The Case published no rubric, so there is nothing to judge against"
        )
    spec = {
        name: str(rubric.get(name) or "").strip()
        for name in ("behaviors_to_test", "prohibited_behaviors")
    }
    if not spec["behaviors_to_test"]:
        raise LocalProviderError(
            "The Case rubric declares no behaviors to test"
        )
    return spec


def _failure_text(item: Any) -> str:
    return f"Step {failure_reason(item)}"


def _transcript(history: Sequence[Any]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(history, start=1):
        submission = item.submission
        blocks.append(
            f"### Step {index} (step_id: {item.test_input.input_id})\n"
            f"USER: {_text(item.test_input.payload)}\n"
            f"AGENT: {_text(submission.output) if submission.status == COMPLETED else _failure_text(item)}"
        )
    return "\n\n".join(blocks)


def _text(value: Any) -> str:
    """Render an Agent output for review without letting one step flood the prompt."""

    if value is None:
        return "<no output>"
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered = str(value)
    rendered = rendered.strip()
    if len(rendered) <= MAX_OUTPUT_CHARS:
        return rendered or "<empty>"
    return f"{rendered[:MAX_OUTPUT_CHARS]}… [truncated, {len(rendered)} chars total]"


def _status(reply: Mapping[str, Any]) -> str:
    value = str(reply.get("status") or "").strip().lower()
    if value not in STATUSES:
        raise LocalProviderError(
            f"The local Judge returned an unusable status: {value!r}"
        )
    return value


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.5
    return min(max(float(value), 0.0), 1.0)


def _issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    issues: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        issue = {"code": str(item.get("code") or "behavior_issue").strip(), "message": message}
        step_id = str(item.get("step_id") or "").strip()
        if step_id:
            issue["step_id"] = step_id
        issues.append(issue)
    return issues


def _step_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        results.append(
            {
                "step_id": str(item.get("step_id") or "").strip(),
                "passed": bool(item.get("passed")),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return results


def _report(
    status: str,
    *,
    confidence: float,
    summary: str,
    stop_reason: str,
    issues: list[dict[str, str]] | None = None,
    step_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "report_id": REPORT_ID,
        "status": status,
        "confidence": confidence,
        "stop_reason": stop_reason,
        "issues": issues or [],
        "extensions": {
            "summary": summary,
            "step_results": step_results or [],
        },
    }


__all__ = ["INSUFFICIENT", "ISSUE", "PASS", "REPORT_ID", "LocalJudgeProvider"]
