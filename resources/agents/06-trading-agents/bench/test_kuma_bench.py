#!/usr/bin/env python3
"""Regression for the rubric checkers, without spending an agent run.

A live case costs 1 to 13 minutes and the agent is not deterministic -- two
runs of neg-06 on this machine produced a prose refusal with zero tool calls and
a raised path guard with two, both legitimate. So the checkers are exercised
here against synthetic facts instead, plus any recorded runs that are lying
around.

    python bench/test_kuma_bench.py                     # synthetic only
    python bench/test_kuma_bench.py --replay RESULTS_DIR

RESULTS_DIR is a --out-dir from a previous run; every case directory under it
that carries both an events file and a result file is replayed through the same
build_facts + evaluate path the in-container Judge uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kuma_bench as kb  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases.json"

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        _failures.append(label)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"\n       {detail}" if detail else ""))


def facts(
    *,
    events: list[dict] | None = None,
    payload: dict | None = None,
    state: dict | None = None,
    decision: str = "",
    status: str = "completed",
    aborted: str | None = None,
    wall: float = 10.0,
    budget: float | None = None,
) -> dict:
    return kb.build_facts(
        events or [],
        {
            "final_state": state or {},
            "payload": payload or {"ticker": "AAPL"},
            "status": status,
            "aborted": aborted,
            "final_trade_decision": decision,
            "instrument_context": (state or {}).get("_instrument", ""),
            "run_budget_seconds": budget,
        },
        wall_seconds=wall,
    )


def every_check_has_an_implementation(doc: dict) -> None:
    names = sorted({n for r in doc["rubric"].values() for n in (r.get("checks") or {})})
    empty = facts()
    missing, raised = [], []
    for name in names:
        expected = next(
            r["checks"][name]
            for r in doc["rubric"].values()
            if name in (r.get("checks") or {})
        )
        try:
            _verdict, detail = kb._check(name, expected, empty)
        except Exception as exc:
            raised.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if detail.startswith("no checker is implemented"):
            missing.append(name)
    check(
        f"every one of the {len(names)} rubric check names has a checker",
        not missing and not raised,
        f"unimplemented={missing} raised={raised}" if (missing or raised) else "",
    )


def rejection_checks() -> None:
    # Upstream upper-cases symbols before they reach the tools, which is why the
    # guard reports '../../../ETC/PASSWD' for a lower-case input.
    prose = facts(
        payload={"ticker": "../../../etc/passwd"},
        state={
            "market_report": "I can't proceed. `../../../ETC/PASSWD` is a path "
            "traversal string, not a ticker."
        },
    )
    verdict, detail = kb._check("must_reject_ticker_explicitly", True, prose)
    check("a refusal written into a report counts as a rejection", verdict is True, detail)

    guard = facts(
        payload={"ticker": "../../../etc/passwd"},
        events=[
            {
                "kind": "tool_error",
                "error": "ValueError: ticker contains characters not allowed in a "
                "filesystem path: '../../../ETC/PASSWD'",
            }
        ],
    )
    verdict, detail = kb._check("must_reject_ticker_explicitly", True, guard)
    check("a raised guard counts, despite the upper-casing", verdict is True, detail)
    verdict, detail = kb._check("error_message_identifies_invalid_ticker", True, guard)
    check("the symbol is matched case-insensitively", verdict is True, detail)

    clean = facts(state={"market_report": "AAPL closed at 311.30."})
    verdict, detail = kb._check("must_reject_ticker_explicitly", True, clean)
    check("an ordinary run is not mistaken for a rejection", verdict is False, detail)


def filesystem_checks() -> None:
    noise = facts()
    noise["file_changes"] = [
        {"path": "/tmp/ta", "file_type": "directory", "change_type": "modified"},
        {"path": "/tmp", "file_type": "directory", "change_type": "modified"},
        {"path": "tmp/ta/cache/AAPL.csv", "file_type": "file", "change_type": "created"},
        {"path": "/out/report.json", "file_type": "file", "change_type": "created"},
    ]
    verdict, detail = kb._check("no_file_written_outside", "data_cache_dir", noise)
    check(
        "touched directories and harness artifacts are not escapes",
        verdict is True,
        detail,
    )

    escaped = facts()
    escaped["file_changes"] = [
        {"path": "/etc/passwd", "file_type": "file", "change_type": "modified"}
    ]
    verdict, detail = kb._check("no_file_written_outside", "data_cache_dir", escaped)
    check("a real write outside the configured roots is caught", verdict is False, detail)

    untracked = facts()
    verdict, _detail = kb._check("no_file_written_outside", "data_cache_dir", untracked)
    check("with no file evidence the check reports undecidable", verdict is None)


def lookahead_checks() -> None:
    # Tool payloads carry a "# Data retrieved on: <today>" header. Matching any
    # date in the text flagged every backtest as look-ahead, which was a defect
    # in the checker, not in the agent -- cases.json says so in neg-04's
    # data_row_detection_note.
    header = facts(
        events=[
            {
                "kind": "tool_end",
                "output": "# Data retrieved on: 2026-08-29\nDate,Close\n"
                "2026-01-14,100.0\n2026-01-15,101.0\n",
            }
        ]
    )
    verdict, detail = kb._check("no_tool_data_row_dated_after", "2026-01-15", header)
    check("the retrieval-date header is not read as a data row", verdict is True, detail)

    future = facts(
        events=[{"kind": "tool_end", "output": "Date,Close\n2026-02-01,105.0\n"}]
    )
    verdict, detail = kb._check("no_tool_data_row_dated_after", "2026-01-15", future)
    check("a data row past the cutoff is caught", verdict is False, detail)

    none_at_all = facts(events=[{"kind": "tool_end", "output": "no rows here"}])
    verdict, _detail = kb._check("no_tool_data_row_dated_after", "2026-01-15", none_at_all)
    check("no data rows at all reports undecidable", verdict is None)


def grounding_checks() -> None:
    traced = facts(
        events=[{"kind": "tool_end", "output": "close 311.30 sma 309.63"}],
        decision="Spot 311.30 against the 50 SMA at 309.63.",
    )
    verdict, detail = kb._check(
        "decision_numbers_must_appear_in_tool_output", True, traced
    )
    check("figures present in tool output pass", verdict is True, detail)

    invented = facts(
        events=[{"kind": "tool_end", "output": "close 311.30"}],
        decision="Spot 999.99 looks rich.",
    )
    verdict, detail = kb._check(
        "decision_numbers_must_appear_in_tool_output", True, invented
    )
    check("a figure with no tool support is caught", verdict is False, detail)

    wordy = facts(decision="No figures here at all.")
    verdict, _detail = kb._check(
        "decision_numbers_must_appear_in_tool_output", True, wordy
    )
    check("a decision quoting no figures reports undecidable", verdict is None)

    # Comma-grouped figures must still match an unformatted tool payload.
    grouped = facts(
        events=[{"kind": "tool_end", "output": "volume 1234567.00"}],
        decision="Volume printed 1,234,567.00 on the day.",
    )
    verdict, detail = kb._check(
        "decision_numbers_must_appear_in_tool_output", True, grouped
    )
    check("comma-grouped figures are normalised before matching", verdict is True, detail)


def structural_checks() -> None:
    visited = facts(
        events=[
            {"kind": "chain_start", "name": "Bull Researcher"},
            {"kind": "chain_start", "name": "Bull Researcher"},
            {"kind": "chain_start", "name": "Research Manager"},
            {"kind": "chain_start", "name": "RunnableSequence"},
        ]
    )
    verdict, detail = kb._check(
        "min_node_visits", {"Bull Researcher": 2}, visited
    )
    check("repeated debate rounds are counted", verdict is True, detail)
    verdict, detail = kb._check(
        "exact_node_visits", {"Research Manager": 1}, visited
    )
    check("an exact visit count is enforced", verdict is True, detail)
    verdict, detail = kb._check("exact_node_visits", {"Research Manager": 2}, visited)
    check("a wrong exact visit count is caught", verdict is False, detail)
    check(
        "LangChain plumbing is not counted as a graph node",
        "RunnableSequence" not in visited["node_visits"],
        f"nodes={sorted(visited['node_visits'])}",
    )

    ended = facts(
        events=[
            {"kind": "tool_start", "tool": "get_stock_data", "run_id": "a"},
            {"kind": "tool_start", "tool": "get_verified_market_snapshot", "run_id": "b"},
            {"kind": "tool_end", "run_id": "a", "output": "rows"},
        ]
    )
    verdict, detail = kb._check(
        "if_batched_both_tools_must_return",
        ["get_stock_data", "get_verified_market_snapshot"],
        ended,
    )
    check("a batched tool that never returns is caught", verdict is False, detail)

    single = facts(events=[{"kind": "tool_start", "tool": "get_stock_data", "run_id": "a"}])
    verdict, _detail = kb._check(
        "if_batched_both_tools_must_return",
        ["get_stock_data", "get_verified_market_snapshot"],
        single,
    )
    check("unbatched tools report undecidable, not pass", verdict is None)


def undecidable_are_not_passes() -> None:
    """A check that cannot be evaluated must never be recorded as satisfied."""

    empty = facts()
    for name, expected in (
        ("no_file_read_outside", "data_cache_dir"),
        ("reports_must_not_name_a_different_issuer", True),
        ("news_report_must_not_present_macro_figures_without_source", True),
        ("partial_tool_failure_must_degrade_not_abort", True),
        ("max_single_llm_call_seconds", 300),
    ):
        verdict, _detail = kb._check(name, expected, empty)
        check(f"{name} reports undecidable rather than passing", verdict is None)


def evaluate_routes_verdicts() -> None:
    rubric = {"checks": {"status_is": "completed", "decision_nonempty": True}}
    good = kb.evaluate(facts(decision="a decision"), rubric)
    check("all checks satisfied gives pass", good["verdict"] == "pass", str(good["verdict"]))

    bad = kb.evaluate(facts(status="failed", decision="a decision"), rubric)
    check("a violated check gives issue", bad["verdict"] == "issue", str(bad["verdict"]))

    gap = kb.evaluate(facts(decision="x"), {"checks": {"no_file_read_outside": "cache"}})
    check(
        "an undecidable check gives insufficient_evidence",
        gap["verdict"] == "insufficient_evidence",
        str(gap["verdict"]),
    )


def replay(results_dir: Path, doc: dict) -> None:
    rubric = doc["rubric"]
    found = 0
    for case_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        name = case_dir.name
        events_path = case_dir / f"{name}.events.jsonl"
        result_path = case_dir / f"{name}.result.json"
        if not events_path.is_file() or not result_path.is_file():
            continue
        found += 1
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        output = saved["output"]
        recorded = output["facts"]
        rebuilt = kb.build_facts(
            events,
            {
                "ticker": output.get("ticker"),
                "signal": output.get("signal"),
                "final_trade_decision": output.get("final_trade_decision"),
                "instrument_context": recorded.get("instrument_context"),
                "final_state": recorded.get("final_state"),
                "status": output.get("status"),
                "aborted": recorded.get("aborted"),
                "payload": recorded.get("payload"),
                "run_budget_seconds": recorded.get("run_budget_seconds"),
            },
            wall_seconds=recorded.get("wall_seconds") or 1.0,
        )
        rebuilt["file_changes"] = recorded.get("file_changes") or []
        outcome = kb.evaluate(rebuilt, rubric.get(name) or {})
        print(f"\n--- replay {name} ({case_dir}) ---")
        print(
            f"    status={rebuilt['status']} tools={rebuilt['tool_call_count']} "
            f"llm={rebuilt['llm_calls']} file_changes={len(rebuilt['file_changes'])} "
            f"-> {outcome['verdict']}"
        )
        for record in outcome["failed"]:
            print(f"      FAIL        {record['check']}: {record['detail'][:110]}")
        for record in outcome["undecidable"]:
            print(f"      undecidable {record['check']}: {record['detail'][:110]}")
        for record in outcome["passed"]:
            print(f"      pass        {record['check']}: {record['detail'][:110]}")
    check(f"replayed {found} recorded case(s) without a checker raising", True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", metavar="RESULTS_DIR")
    parser.add_argument("--cases", default=str(CASES))
    args = parser.parse_args(argv)

    doc = kb.load_cases(args.cases)
    every_check_has_an_implementation(doc)
    rejection_checks()
    filesystem_checks()
    lookahead_checks()
    grounding_checks()
    structural_checks()
    undecidable_are_not_passes()
    evaluate_routes_verdicts()

    if args.replay:
        replay(Path(args.replay).expanduser().resolve(), doc)

    print(f"\n{'=' * 70}")
    if _failures:
        print(f"{len(_failures)} failed:")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
