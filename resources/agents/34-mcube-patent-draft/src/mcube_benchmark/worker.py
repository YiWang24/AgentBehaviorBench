"""JSONL worker for the M-Cube patent-drafting workflow.

The graph interrupts once for human review of the drafted claims. The benchmark
has no human, so it resumes with the claims the graph itself produced — the
"accept the draft as written" path. `raw_output` records that the review was
auto-accepted so nothing is mistaken for a real approval.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import uuid


def _disclosure(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("disclosure_text", "disclosure", "question", "query", "prompt", "input", "text", "content"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    from langgraph.types import Command

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("MCUBE_RECURSION_LIMIT", "60"))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"JSONDecodeError: {exc}"}), flush=True)
            continue

        try:
            disclosure = _disclosure(payload)
            config = {
                "recursion_limit": limit,
                "configurable": {"thread_id": str(uuid.uuid4())},
            }
            initial = {
                "session_id": "benchmark",
                "trace_id": str(uuid.uuid4()),
                "status": "running",
                "disclosure_text": disclosure,
                "disclosure_images": [],
            }
            auto_approved = False
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke(initial, config=config)
                snapshot = compiled.get_state(config)
                # If it stopped at the human-review interrupt, accept the
                # claims it drafted and resume — upstream's "approved" path.
                if snapshot.next:
                    claims = state.get("claims")
                    state = compiled.invoke(
                        Command(resume={"approved_claims": claims}), config=config
                    )
                    auto_approved = True

            reply = {
                "ok": True,
                "output": json.dumps(
                    {
                        "claims": state.get("claims"),
                        "specification": state.get("specification"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                "raw_output": {
                    "disclosure_text": disclosure,
                    "tech_summary": state.get("tech_summary"),
                    "claims": state.get("claims"),
                    "claim_traceability": state.get("claim_traceability"),
                    "specification": state.get("specification"),
                    "review_issues": state.get("review_issues"),
                    "status": state.get("status"),
                    "claims_auto_approved": auto_approved,
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
