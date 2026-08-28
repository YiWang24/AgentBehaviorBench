"""Retain completed model calls so a run can be summarized after it finishes.

``LLMActivity`` renders a self-erasing live panel and clears its state at every
stage boundary, so nothing survives for a final report. This sink keeps one small
record per call instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentbench.runtime.interception import TraceEvent

from .LLMactivity import PREVIEW_CHAR_LIMIT, event_preview


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One matched model request/response pair."""

    number: int
    provider: str
    request_preview: str
    response_preview: str
    status: object | None = None
    latency_ms: object | None = None

    @property
    def latency_text(self) -> str:
        if isinstance(self.latency_ms, (int, float)):
            return f"{float(self.latency_ms):.1f}ms"
        return "-"

    @property
    def status_text(self) -> str:
        return "-" if self.status is None else str(self.status)


@dataclass(slots=True)
class CallRecorder:
    """Collect completed calls in the order their responses arrived."""

    preview_chars: int = PREVIEW_CHAR_LIMIT
    records: list[CallRecord] = field(default_factory=list)
    _pending: dict[str, tuple[str, str]] = field(default_factory=dict)

    def emit(self, event: TraceEvent) -> None:
        call_id = event.data.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            return
        if event.event == "llm_request":
            self._pending[call_id] = (
                _provider(event.data),
                event_preview(event, self.preview_chars),
            )
            return
        if event.event != "llm_response":
            return
        provider, request_preview = self._pending.pop(
            call_id, ("model", "-")
        )
        self.records.append(
            CallRecord(
                number=len(self.records) + 1,
                provider=provider,
                request_preview=request_preview,
                response_preview=event_preview(event, self.preview_chars),
                status=event.data.get("status"),
                latency_ms=event.data.get("latency_ms"),
            )
        )


def _provider(data: object) -> str:
    if not isinstance(data, dict):
        return "model"
    provider = data.get("provider")
    return provider if isinstance(provider, str) and provider else "model"


__all__ = ["CallRecord", "CallRecorder"]
