"""Drive the 10 custom cases through a fully-local KUMA Run.

Fully local = custom Case Provider + custom Judge Provider, so no API key is
used and nothing is uploaded (providers table in docs/sdk-guide.md). The SDK
still enforces its runtime boundary, so this must run inside the same container
as the agent.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kuma import create_run  # noqa: E402
from kuma.contracts import TestReport  # noqa: E402

from kuma_cases import TradingAgentsCaseProvider, _selected  # noqa: E402
from kuma_judge import RubricJudge  # noqa: E402
from worker import run_case  # noqa: E402

OUT = os.environ.get("BENCH_OUT", "/out")
# A data row starts with the date and is immediately followed by a comma
# (CSV), unlike the "# Data retrieved on: ..." metadata header.
_DATA_ROW = re.compile(r"^(20\d{2}-\d{2}-\d{2})\s*,")


def _facts_from_events(events: list[dict], final_state: dict | None) -> dict:
    tool_calls, tool_outputs, node_visits = [], [], {}
    for e in events:
        k = e.get("kind")
        if k == "tool_start":
            tool_calls.append({"tool": e.get("tool"), "args": e.get("inputs")})
        elif k == "tool_end" and e.get("output"):
            tool_outputs.append(e["output"])
        elif k == "chain_start" and e.get("name"):
            node_visits[e["name"]] = node_visits.get(e["name"], 0) + 1

    # Only real OHLCV rows count. Tool payloads carry a "# Data retrieved on:
    # <today>" metadata header, and matching any date in the text made every
    # backtest look like look-ahead — a defect in the check, not the agent.
    max_row_date = None
    for text in tool_outputs:
        for line in text.splitlines():
            m = _DATA_ROW.match(line.strip())
            if not m:
                continue
            d = m.group(1)
            if max_row_date is None or d > max_row_date:
                max_row_date = d

    state = final_state or {}
    return {
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
        "node_visits": node_visits,
        "max_tool_row_date": max_row_date,
        "tool_output_total_chars": sum(len(t) for t in tool_outputs),
        "state_nonempty": sorted(
            k for k, v in state.items() if isinstance(v, str) and v.strip()
        ),
        "tool_outputs_joined_lower": " ".join(tool_outputs).lower()[:200_000],
        "errors": [e for e in events
                   if e.get("kind") in ("tool_error", "llm_error", "chain_error")],
    }


# KUMA_OFFICIAL_JUDGE=1 hands judging to the hosted service instead of the
# local rubric checker. That uploads submission output and the selected log
# files, so it is opt-in.
OFFICIAL_JUDGE = os.environ.get("KUMA_OFFICIAL_JUDGE") == "1"

# Class-based Judge Provider. adapt_judge_provider passes any object with a
# .judge() through untouched, so no callable wrapper is involved, and the
# rubric is read back out of context.case rather than a module global.
JUDGE = RubricJudge(dump_path=os.path.join(OUT, "judge-contract.json"))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))

    run = create_run(
        repo_path=os.environ.get("BENCH_REPO", "/opt/bench"),
        requirement_path=None,
        case_provider=TradingAgentsCaseProvider(),
        judge_provider=None if OFFICIAL_JUDGE else JUDGE,
        max_inputs=len(_selected()),
        on_failure="continue",
        track_files=False,
        save_local=True,
        allow_local=os.environ.get("KUMA_ALLOW_LOCAL") == "1",
    )
    print(f"[kuma] run state={run.state}", flush=True)

    while True:
        item = run.get_input(full=True)
        if item is None:
            break
        iid = item.input_id
        payload = dict(item.payload)
        sink = os.path.join(OUT, f"{iid}.jsonl")
        print(f"[kuma] -> {iid}  {payload}", flush=True)

        t0 = time.time()
        try:
            res = run_case(payload, sink)
            raw = res["raw_output"]
            out = dict(res["output"])
            out["status"] = "completed"
            out["facts"] = _facts_from_events(raw["events"], raw["final_state"])
            status = "completed"
            err = None
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            events = []
            if os.path.exists(sink):
                with open(sink, encoding="utf-8") as fh:
                    events = [json.loads(l) for l in fh if l.strip()]
            out = {
                "ticker": payload.get("ticker"), "date": payload.get("date"),
                "signal": None, "final_trade_decision": "",
                "status": "crashed", "error": err,
                "facts": _facts_from_events(events, None),
            }
            status = "failed"
            traceback.print_exc()

        print(f"[kuma] <- {iid}  {status}  {time.time()-t0:.1f}s  "
              f"tools={out['facts']['tool_call_count']}  err={err}", flush=True)
        run.submit(out, status=status, error=err, logs=[sink] if os.path.exists(sink) else None)

    report: TestReport = run.judge()
    print("\n=== KUMA TestReport ===", flush=True)
    print(f"status={report.status} confidence={report.confidence} "
          f"issues={len(report.issues)} ext={dict(report.extensions)}", flush=True)
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "report": {"status": report.status, "confidence": report.confidence,
                       "stop_reason": report.stop_reason,
                       "issues": [dict(i) for i in report.issues],
                       "extensions": dict(report.extensions)},
            "results": JUDGE.results,
            "sdk_contract": JUDGE.contract,
        }, fh, ensure_ascii=False, indent=2, default=str)
    print(f"[kuma] wrote {OUT}/report.json", flush=True)


if __name__ == "__main__":
    main()
