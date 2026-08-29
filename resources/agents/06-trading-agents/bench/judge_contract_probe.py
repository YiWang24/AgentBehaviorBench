"""Probe what the SDK accepts back from a custom Judge Provider.

`normalize_report` (providers/normalization.py:297) is the whole gate between a
custom Judge and a TestReport, and it is a pure function, so every case here
runs in milliseconds without the agent. Each row records what the SDK did, not
what the docs claim it does.
"""

from __future__ import annotations

import datetime as _dt
import json

from kuma.contracts import TestReport
from kuma.providers.normalization import normalize_report

RUN = "run_0123456789abcdef0123456789abcdef"

_VALID = {"status": "pass", "confidence": "high", "stop_reason": "case_completed"}


def _case(name: str, value, *, run_id: str = RUN):
    try:
        report = normalize_report(value, run_id=run_id)
        return {
            "probe": name,
            "outcome": "ACCEPTED",
            "status": report.status,
            "stop_reason": report.stop_reason,
            "n_issues": len(report.issues),
            "extensions": dict(report.extensions),
        }
    except Exception as exc:
        return {
            "probe": name,
            "outcome": "REJECTED",
            "error": f"{type(exc).__name__}: {exc}",
            "code": getattr(exc, "code", None),
        }


def main() -> None:
    probes = [
        # --- shape of the return value ---
        ("mapping, minimal valid", dict(_VALID)),
        ("bare string", "pass"),
        ("None", None),
        ("list", [{"status": "pass"}]),
        ("missing status", {"confidence": "high"}),

        # --- is the status value itself checked? ---
        ("status='banana'", {**_VALID, "status": "banana"}),
        ("status='insufficient_evidence'", {**_VALID, "status": "insufficient_evidence"}),
        ("status=42", {**_VALID, "status": 42}),

        # --- confidence / stop_reason ---
        ("confidence='banana'", {**_VALID, "confidence": "banana"}),
        ("confidence=0.9", {**_VALID, "confidence": 0.9}),
        ("confidence=1.5", {**_VALID, "confidence": 1.5}),
        ("status='passed' (official spelling)", {**_VALID, "status": "passed"}),
        ("stop_reason omitted", {"status": "pass"}),

        # --- issues: is the shape validated at all? ---
        ("issues=[] ", {**_VALID, "issues": []}),
        ("issues=[bare string]", {**_VALID, "status": "issue",
                                  "issues": ["something went wrong"]}),
        ("issues=[dict w/o issue_id/severity]", {**_VALID, "status": "issue",
                                                 "issues": [{"detail": "x"}]}),
        ("issues=[42]", {**_VALID, "status": "issue", "issues": [42]}),

        # --- private-data scan ---
        ("carries expected_answer", {**_VALID, "expected_answer": "BUY"}),
        ("carries system_prompt", {**_VALID, "system_prompt": "you are..."}),
        ("private key nested in extensions",
         {**_VALID, "extensions": {"debug": {"answer_key": "BUY"}}}),
        ("key named 'rubric'", {**_VALID, "rubric": {"a": 1}}),

        # --- JSON-ability ---
        ("non-JSON value (set)", {**_VALID, "extensions": {"s": {1, 2}}}),
        ("non-JSON value (datetime)",
         {**_VALID, "extensions": {"t": _dt.datetime(2026, 1, 1)}}),
        ("nan", {**_VALID, "extensions": {"n": float("nan")}}),

        # --- extensions handling ---
        ("extensions not a mapping", {**_VALID, "extensions": ["a"]}),
        ("unknown top-level key", {**_VALID, "passed": 6, "total": 10}),

        # --- run_id binding ---
        ("run_id mismatch", {**_VALID, "run_id": "run_ffffffffffffffffffffffffffffffff"}),
        ("run_id echoed correctly", {**_VALID, "run_id": RUN}),
    ]

    rows = [_case(name, value) for name, value in probes]

    # A well-formed TestReport must still be refused when it names another Run,
    # and passed straight through when it names this one.
    other = TestReport(report_id="report_deadbeef", status="pass",
                       run_id="run_ffffffffffffffffffffffffffffffff")
    rows.append(_case("TestReport for another run", other))
    mine = TestReport(report_id="report_deadbeef", status="pass", run_id=RUN)
    rows.append(_case("TestReport for this run", mine))

    width = max(len(r["probe"]) for r in rows)
    for r in rows:
        tail = (r.get("error") or
                f"status={r.get('status')!r} issues={r.get('n_issues')} "
                f"ext={r.get('extensions')}")
        print(f"{r['probe']:<{width}}  {r['outcome']:<18} {tail}")

    print()
    acc = sum(1 for r in rows if r["outcome"] == "ACCEPTED")
    print(f"accepted {acc} / {len(rows)}")
    with open("/out/judge-contract-probe.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
