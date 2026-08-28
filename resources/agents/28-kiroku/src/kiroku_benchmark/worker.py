"""JSONL worker for the Kiroku document writer.

Upstream's UI drives the graph one segment at a time: `step(instruction,
state)` runs to the next `interrupt_before` and waits for the author. The
worker does the same, resuming each break with an *empty* instruction — which
is upstream's own "accept as written" path, taken without a model call. No
review comment is invented on the author's behalf; `raw_output` records how
many breaks were passed so a judge can see the shape of the run.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys


def _instructions(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("instructions", "question", "query", "prompt", "input", "text", "content"):
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
    from . import brief as brief_module
    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        writer = graph_module.writer()

    max_segments = int(os.environ.get("KIROKU_MAX_SEGMENTS", "12"))

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
            instructions = _instructions(payload)
            # get_thread_id() returns a string; each request gets a fresh
            # thread so drafts never leak between runs.
            writer.set_thread_id(int(writer.get_thread_id()) + 1)

            state = brief_module.initial_state(instructions)
            segments = 0
            with contextlib.redirect_stdout(sys.stderr):
                draft = writer.invoke(state, {"instruction": ""})
                segments += 1
                # Resume through each human-review break until the graph ends.
                while segments < max_segments and writer.get_state().next:
                    draft = writer.invoke(None, {"instruction": ""})
                    segments += 1
                final = writer.get_state()

            values = final.values if hasattr(final, "values") else {}
            reply = {
                "ok": True,
                "output": draft,
                "raw_output": {
                    "draft": draft,
                    "instructions": instructions,
                    "title": values.get("title"),
                    "plan": values.get("plan"),
                    "critique": values.get("critique"),
                    "references": values.get("references"),
                    "segments_run": segments,
                    "stopped_before": list(final.next) if final.next else [],
                    "review_instruction_supplied": "",
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
