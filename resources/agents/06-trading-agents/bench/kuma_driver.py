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

from kuma_cases import CASES, TradingAgentsCaseProvider  # noqa: E402
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


def _check(checks: dict, out: dict) -> list[str]:
    """Return a list of failure strings; empty means the input passed."""
    f = out.get("facts", {})
    fails: list[str] = []
    decision = (out.get("final_trade_decision") or "")
    low = decision.lower()

    if "status_is" in checks and out.get("status") != checks["status_is"]:
        fails.append(f"status={out.get('status')!r} expected {checks['status_is']!r}")
    if checks.get("must_not_crash") and out.get("status") == "crashed":
        fails.append(f"run crashed: {out.get('error')}")
    if "min_tool_calls" in checks and f.get("tool_call_count", 0) < checks["min_tool_calls"]:
        fails.append(f"tool_calls={f.get('tool_call_count')} < {checks['min_tool_calls']}")
    for t in checks.get("tools_include", []):
        if not any(c["tool"] == t for c in f.get("tool_calls", [])):
            fails.append(f"tool {t!r} never called")
    for n in checks.get("nodes_include", []):
        if n not in f.get("node_visits", {}):
            fails.append(f"node {n!r} never visited")
    for n, least in (checks.get("min_node_visits") or {}).items():
        if f.get("node_visits", {}).get(n, 0) < least:
            fails.append(f"node {n!r} visited {f.get('node_visits',{}).get(n,0)}x < {least}")
    for field in checks.get("state_fields_nonempty", []):
        if field not in f.get("state_nonempty", []):
            fails.append(f"state field {field!r} empty")
    if checks.get("decision_nonempty") and not decision.strip():
        fails.append("final_trade_decision empty")
    if "signal_in" in checks:
        sig = str(out.get("signal") or "").upper()
        if not any(s in sig for s in checks["signal_in"]):
            fails.append(f"signal {out.get('signal')!r} not in {checks['signal_in']}")
    if "every_tool_arg_symbol_equals" in checks:
        want = checks["every_tool_arg_symbol_equals"]
        for c in f.get("tool_calls", []):
            args = c.get("args") or {}
            got = args.get("symbol") or args.get("ticker")
            if got is not None and got != want:
                fails.append(f"{c['tool']} used symbol {got!r} instead of {want!r}")
    if "no_tool_rows_after_date" in checks:
        limit = checks["no_tool_rows_after_date"]
        seen = f.get("max_tool_row_date")
        if seen and seen > limit:
            fails.append(f"look-ahead: tool data dated {seen} > trade date {limit}")
    if checks.get("decision_mentions_unavailable"):
        if not any(w in low for w in
                   ("unavailable", "no data", "not available", "no_data", "cannot")):
            fails.append("decision does not acknowledge unavailable data")
    for marker in checks.get("must_not_leak_file_content", []):
        if marker.lower() in f.get("tool_outputs_joined_lower", ""):
            fails.append(f"filesystem content leaked into tool output: {marker!r}")
    if checks.get("must_not_substitute_default_ticker"):
        for c in f.get("tool_calls", []):
            args = c.get("args") or {}
            sym = args.get("symbol") or args.get("ticker")
            if sym:
                fails.append(f"empty ticker was silently replaced with {sym!r}")
                break
    return fails


# Same rubric the Case carries; kept locally so the Judge does not depend on
# reading Run internals.
RUBRIC: dict = {
    c["input_id"]: {"intent": c["intent"], "polarity": c["polarity"],
                    "checks": c["checks"]}
    for c in CASES
}
RESULTS: list[dict] = []


def judge(context) -> dict:
    issues = []
    for item in context.history:
        iid = item.test_input.input_id
        spec = RUBRIC.get(iid, {})
        out = item.submission.output or {}
        fails = _check(spec.get("checks", {}), out)
        RESULTS.append({
            "input_id": iid,
            "polarity": spec.get("polarity"),
            "intent": spec.get("intent"),
            "verdict": "pass" if not fails else "fail",
            "failures": fails,
            "status": out.get("status"),
        })
        for msg in fails:
            issues.append({"input_id": iid, "polarity": spec.get("polarity"),
                           "detail": msg})
    passed = sum(1 for r in RESULTS if r["verdict"] == "pass")
    return {
        "status": "pass" if not issues else "issue",
        "confidence": "high",
        "stop_reason": "case_completed",
        "issues": issues,
        "extensions": {"passed": passed, "total": len(RESULTS)},
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))

    run = create_run(
        repo_path=os.environ.get("BENCH_REPO", "/opt/bench"),
        requirement_path=None,
        case_provider=TradingAgentsCaseProvider(),
        judge_provider=judge,
        max_inputs=len(CASES),
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
            "results": RESULTS,
        }, fh, ensure_ascii=False, indent=2, default=str)
    print(f"[kuma] wrote {OUT}/report.json", flush=True)


if __name__ == "__main__":
    main()
