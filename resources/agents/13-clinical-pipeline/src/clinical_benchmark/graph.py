"""LangGraph entry point for the benchmark adaptation of the clinical pipeline.

The upstream graph is imported unchanged: intake, diagnosis with a loop back to
intake when more information is needed, then treatment, coding, and audit.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from clinical_agent.graph.clinical_pipeline import build_clinical_pipeline  # noqa: E402

RECURSION_LIMIT = 30

_pipeline = None


def graph():
    """Zero-argument factory returning the compiled clinical pipeline."""
    global _pipeline
    if _pipeline is None:
        _pipeline = build_clinical_pipeline()
    return _pipeline


def _plain(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


async def run_case(description: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run one clinical case and normalize the public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)
    config.setdefault("configurable", {}).setdefault("thread_id", "benchmark")

    state = await graph().ainvoke({"raw_input": description}, config=config)
    plain = _plain(state) if isinstance(state, dict) else _plain(getattr(state, "__dict__", {}))

    return {
        "presentation": description,
        "diagnosis": plain.get("diagnosis"),
        "treatment": plain.get("treatment_plan") or plain.get("treatment"),
        "codes": plain.get("icd10_codes") or plain.get("codes"),
        "audit": plain.get("audit_report") or plain.get("audit"),
        "needs_more_info": bool(plain.get("needs_more_info")),
    }
