"""Sectioned terminal report and machine-readable summary for `verify`.

Four sections, in the order a reader needs them: what is being checked, which
stages passed, what the model actually exchanged, and the verdict. No boxes, so
nothing can break on a long path, and every line stays greppable.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agentbench.cli.constants import (
    ANSI_BOLD,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
)
from agentbench.cli.TerminalUI.call_log import CallRecord

PASS = "pass"
FAIL = "fail"
ERROR = "error"

EXIT_CODES = {PASS: 0, FAIL: 1, ERROR: 2}

MARK_OK = "✓"
MARK_FAIL = "✗"
ARROW_IN = "▸"
ARROW_OUT = "◂"
SEPARATOR = "·"

LABEL_WIDTH = 16
PREVIEW_WIDTH = 54
DETAIL_WIDTH = 70
RUN_ID_WIDTH = 20
MAX_DISPLAYED_CALLS = 10


def truncate(text: str, width: int) -> str:
    """Cut the tail of a preview.

    Previews read left to right, so the opening words matter most; only paths get
    shortened from the middle.
    """

    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[: max(width - 1, 0)].rstrip() + "…"


@dataclass(frozen=True)
class VerifyReport:
    """Everything `verify` learned about one Agent."""

    agent_id: str
    verdict: str
    completed_cases: int = 0
    requested_cases: int = 0
    captured_pairs: int = 0
    substituted_secrets: tuple[str, ...] = ()
    result_log: Path | None = None
    reason: str | None = None
    calls: tuple[CallRecord, ...] = ()

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def exit_code(self) -> int:
        """The shell status this verdict maps to.

        Derived rather than stored so the two can never disagree, and left out of
        the JSON: the process already returns it, and ``verdict`` says the same
        thing in a form that does not need a lookup table.
        """

        return EXIT_CODES[self.verdict]

    def to_json(self) -> str:
        return json.dumps(
            {
                "command": "verify",
                "agent_id": self.agent_id,
                "verdict": self.verdict,
                "cases": {
                    "completed": self.completed_cases,
                    "requested": self.requested_cases,
                },
                "model_calls": {
                    "captured_pairs": self.captured_pairs,
                    "calls": [
                        {
                            "number": call.number,
                            "provider": call.provider,
                            "status": call.status,
                            "latency_ms": call.latency_ms,
                            "request_preview": call.request_preview,
                            "response_preview": call.response_preview,
                        }
                        for call in self.calls
                    ],
                },
                "substituted_secrets": list(self.substituted_secrets),
                "result_log": None if self.result_log is None else str(self.result_log),
                "reason": self.reason,
            },
            ensure_ascii=False,
            indent=2,
        )


def print_header(agent_id: str, output_fn: Callable[[str], None]) -> None:
    output_fn("")
    output_fn(f"{ANSI_BOLD}verify{ANSI_RESET} {SEPARATOR} {ANSI_BOLD}{agent_id}{ANSI_RESET}")
    output_fn(
        f"       offline {SEPARATOR} no credentials {SEPARATOR} egress blocked "
        f"{SEPARATOR} registry untouched"
    )
    output_fn("")


def print_report(report: VerifyReport, output_fn: Callable[[str], None]) -> None:
    """Render the model-call and verdict sections."""

    if report.calls:
        _print_calls(report.calls, output_fn)
    if report.substituted_secrets:
        output_fn(
            f"  {ANSI_YELLOW}!{ANSI_RESET}  {'stubbed secrets':<{LABEL_WIDTH}}"
            + ", ".join(report.substituted_secrets)
        )
        output_fn("")
    _print_verdict(report, output_fn)


def _print_calls(
    calls: Sequence[CallRecord], output_fn: Callable[[str], None]
) -> None:
    shown = _visible_calls(calls)
    for call in shown:
        if call is None:
            output_fn(f"     {'':>2}  {SEPARATOR * 3} {len(calls) - MAX_DISPLAYED_CALLS} more calls")
            continue
        meta = f"{call.status_text} {SEPARATOR} {call.latency_text}"
        output_fn(
            f"     {call.number:02d}  {ARROW_IN} "
            f"{truncate(call.request_preview, PREVIEW_WIDTH)}"
        )
        output_fn(
            f"         {ARROW_OUT} "
            f"{truncate(call.response_preview, PREVIEW_WIDTH):<{PREVIEW_WIDTH}}  {meta}"
        )
    output_fn("")


def _visible_calls(
    calls: Sequence[CallRecord],
) -> list[CallRecord | None]:
    """Keep the report short by eliding the middle of a long call list."""

    if len(calls) <= MAX_DISPLAYED_CALLS:
        return list(calls)
    head = MAX_DISPLAYED_CALLS // 2
    tail = MAX_DISPLAYED_CALLS - head
    return [*calls[:head], None, *calls[len(calls) - tail :]]


def _print_verdict(report: VerifyReport, output_fn: Callable[[str], None]) -> None:
    if report.passed:
        badge = f"{ANSI_GREEN}{ANSI_BOLD}PASS{ANSI_RESET}"
        pairs = report.captured_pairs
        detail = (
            f"{report.completed_cases}/{report.requested_cases} cases {SEPARATOR} "
            f"{pairs} model request/response pair{'' if pairs == 1 else 's'} captured"
        )
    else:
        badge = f"{ANSI_RED}{ANSI_BOLD}FAIL{ANSI_RESET}"
        detail = report.reason or "verification did not complete"

    # A failure reason now names its underlying cause, which can outrun the rest
    # of the report. Wrapping keeps it whole and aligned instead of letting the
    # terminal break it at an arbitrary column.
    head, *rest = textwrap.wrap(detail, DETAIL_WIDTH) or [""]
    output_fn(f"  {badge}   {head}")
    for line in rest:
        output_fn(f"{'':<9}{line}")
    if report.result_log is not None:
        output_fn(f"         log  {report.result_log}")


def _print_stage(
    label: str,
    detail: str,
    output_fn: Callable[[str], None],
    *,
    ok: bool,
) -> None:
    mark = f"{ANSI_GREEN}{MARK_OK}{ANSI_RESET}" if ok else f"{ANSI_RED}{MARK_FAIL}{ANSI_RESET}"
    # These lines form a scannable column, so a failure detail is cut here rather
    # than allowed to wrap; the verdict below carries the same reason in full.
    output_fn(
        f"  {mark}  {label:<{LABEL_WIDTH}}{truncate(detail, DETAIL_WIDTH - LABEL_WIDTH)}"
    )


STAGE_LABELS = {
    "sdk_check": "configuration",
    "agent_start": "agent start",
    "case_generation": "case",
    "benchmark_execution": "agent run",
}


class VerifyProgress:
    """Render one compact line per stage, with a live panel while it runs.

    The live panel is owned by ``LLMActivity`` and erases itself, so only the
    finished line survives in a log. Its own stage line is suppressed via
    ``close()`` so this renderer controls the final format.
    """

    def __init__(
        self,
        output_fn: Callable[[str], None],
        *,
        llm_activity: object | None = None,
        call_count: Callable[[], int] | None = None,
    ) -> None:
        self._output_fn = output_fn
        self._llm_activity = llm_activity
        self._call_count = call_count
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed

    def __call__(self, event: object) -> None:
        stage = getattr(event, "stage", "")
        status = getattr(event, "status", "")
        label = STAGE_LABELS.get(stage, stage)

        if status == "started":
            self._start_live(f"{label}...")
            return

        self._stop_live()
        ok = status == "succeeded"
        self._failed = self._failed or not ok
        _print_stage(
            label,
            self._detail(stage, getattr(event, "detail", None), ok=ok),
            self._output_fn,
            ok=ok,
        )

    def close(self) -> None:
        self._stop_live()

    def _detail(self, stage: str, detail: object, *, ok: bool) -> str:
        text = "" if detail is None else str(detail)
        if not ok:
            return text or "failed"
        if stage == "sdk_check":
            return text.replace("Provider mode: ", "") + " providers"
        if stage == "case_generation":
            return truncate(text.replace("run=", ""), RUN_ID_WIDTH)
        if stage == "benchmark_execution":
            if self._call_count is None:
                return text
            count = self._call_count()
            return f"{count} model call{'' if count == 1 else 's'}"
        return text

    def _start_live(self, label: str) -> None:
        starter = getattr(self._llm_activity, "start_stage", None)
        if callable(starter):
            starter(label)

    def _stop_live(self) -> None:
        closer = getattr(self._llm_activity, "close", None)
        if callable(closer):
            closer()


__all__ = [
    "ERROR",
    "FAIL",
    "PASS",
    "VerifyProgress",
    "VerifyReport",
    "print_header",
    "print_report",
]
