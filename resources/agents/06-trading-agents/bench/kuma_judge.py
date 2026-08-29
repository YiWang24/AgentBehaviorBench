"""A class-based Judge Provider, written to exercise the SDK's judge contract.

Two things this tests that the previous bare-callable judge did not:

1. The rubric is read back out of ``context.case.rubric`` instead of a module
   global. That is the documented channel (``rubric`` is the one subtree
   ``normalize_case`` exempts from the private-data scan), so reading it here
   proves the SDK carries it intact through Case -> Run -> JudgeContext.

2. Every field the SDK hands a Judge is recorded to a contract dump, next to
   the hash-only ``runtime_evidence`` envelope built for the same submission.
   The two side by side show what a local Judge can see versus what the
   official upload path is able to ship.

``adapt_judge_provider`` passes any object with ``.judge()`` through untouched
(providers/base.py:129), so no callable wrapper is involved.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


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


def _text_chars(value: Any) -> int:
    """Total characters of every string reachable in a submission output.

    Must test against Mapping, not dict: the SDK freezes submission output into
    MappingProxyType, for which `isinstance(x, dict)` is False. Checking dict
    here silently reported 0 characters for outputs that were fully populated —
    the same mismatch that makes jsonschema reject every frozen input schema.
    """
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Mapping):
        return sum(_text_chars(v) for v in value.values())
    if isinstance(value, Sequence):
        return sum(_text_chars(v) for v in value)
    return 0


# Any envelope component field that would carry actual content rather than a
# digest. Kept explicit so a future SDK that adds one shows up in the dump.
_CONTENT_KEYS = frozenset({"text", "content", "data", "body", "output", "snippet"})


def _envelope_facts(runtime_evidence: Any) -> dict:
    """Summarize the hash-only envelope the official upload path would ship."""
    if not isinstance(runtime_evidence, Mapping):
        return {"present": False}
    components = runtime_evidence.get("components") or []
    kinds, content_bearing, digest_only = [], [], []
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        kind = comp.get("kind")
        kinds.append(kind)
        keys = set(comp)
        if keys & _CONTENT_KEYS:
            content_bearing.append({"kind": kind, "keys": sorted(keys & _CONTENT_KEYS)})
        else:
            digest_only.append(kind)
    return {
        "present": True,
        "schema_version": runtime_evidence.get("schema_version"),
        "component_kinds": kinds,
        "components_with_content": content_bearing,
        "components_digest_only": digest_only,
        "envelope_chars": len(json.dumps(runtime_evidence, default=str)),
    }


class RubricJudge:
    """Judge the Run against the rubric the Case carries, and probe the SDK."""

    def __init__(self, dump_path: str | None = None):
        self.dump_path = dump_path
        self.results: list[dict] = []
        self.contract: dict = {}

    # ---------- SDK contract probe ----------

    def _probe(self, context) -> dict:
        case = context.case
        items = []
        for item in context.history:
            sub = item.submission
            ext = dict(sub.extensions or {})
            out = sub.output or {}
            items.append({
                "input_id": sub.input_id,
                "status": sub.status,
                "error": sub.error,
                # what the local Judge can actually read
                "output_keys": sorted(out) if isinstance(out, Mapping) else None,
                "output_type": type(sub.output).__name__,
                "output_text_chars": _text_chars(sub.output),
                "final_decision_chars": len(out.get("final_trade_decision") or "")
                if isinstance(out, Mapping) else 0,
                # Does the submission-side log segment still hold its text?
                "log_content_chars": sum(len(s.get("content") or "")
                                         for s in (sub.logs or ())),
                # what the Input carried in
                "public_constraints": dict(item.test_input.public_constraints or {}),
                "payload_type": item.test_input.payload_type,
                # evidence plumbing
                "logs_segments": len(sub.logs or ()),
                "log_segment_keys": sorted(sub.logs[0]) if sub.logs else [],
                "file_evidence": sub.file_evidence is not None,
                "dropped_count": sub.dropped_count,
                "missing": list(sub.missing or ()),
                "extension_keys": sorted(ext),
                # the envelope the official path would upload for this item
                "runtime_evidence": _envelope_facts(ext.get("runtime_evidence")),
            })
        return {
            "case": {
                "case_id": case.case_id,
                "input_type": case.input_type,
                "n_inputs": len(case.inputs),
                "rubric_present": case.rubric is not None,
                "rubric_input_ids": sorted(case.rubric) if case.rubric else [],
                "rubric_type": type(case.rubric).__name__,
                "input_schema": case.input_schema,
                "extension_keys": sorted(case.extensions or {}),
            },
            "run_status": context.run_status,
            "evidence_summary": dict(context.evidence_summary or {}),
            "history": items,
        }

    # ---------- JudgeProvider port ----------

    def judge(self, context) -> dict:
        self.contract = self._probe(context)

        # The rubric comes from the Case the SDK handed back, not from the
        # module that built it. If the SDK dropped it, this judge cannot grade.
        rubric = context.case.rubric
        if not rubric:
            return {
                "status": "insufficient_evidence",
                "confidence": "high",
                "stop_reason": "case_completed",
                "issues": [{"detail": "Case.rubric did not survive to JudgeContext"}],
            }

        issues = []
        for item in context.history:
            iid = item.test_input.input_id
            spec = rubric.get(iid) or {}
            out = item.submission.output or {}
            fails = _check(dict(spec.get("checks") or {}), out)
            self.results.append({
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

        if self.dump_path:
            with open(self.dump_path, "w", encoding="utf-8") as fh:
                json.dump({"contract": self.contract, "results": self.results},
                          fh, ensure_ascii=False, indent=2, default=str)

        passed = sum(1 for r in self.results if r["verdict"] == "pass")
        return {
            "status": "pass" if not issues else "issue",
            "confidence": "high",
            "stop_reason": "case_completed",
            "issues": issues,
            "extensions": {"passed": passed, "total": len(self.results),
                           "rubric_source": "case.rubric"},
        }
