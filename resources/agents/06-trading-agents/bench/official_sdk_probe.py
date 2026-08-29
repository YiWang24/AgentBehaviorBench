"""Can the Official Judge return a real verdict under ANY configuration?

No agent. Every submission below is fabricated in this file, with deliberately
unambiguous polarity: the positive input gets a complete answer, the negative
one an explicit refusal. If the Judge can see any of it, telling the two apart
is trivial. So a verdict of `insufficient_evidence` here is a property of the
evidence channel, not of the agent under test.

Run one variant per container (`python official_sdk_probe.py <variant>`) so
each gets a fresh Run lock.

Variants:
  custom-nofiles  custom Case + Official Judge, track_files=False   (our setup)
  custom-files    custom Case + Official Judge, track_files+upload_diff, real edits
  official-full   Official Case + Official Judge, track_files       (can_negotiate)
  no-logs         custom Case + Official Judge, output only, no logs at all
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from kuma import create_run
from kuma.transport.backend import BackendClient

REPO = Path(os.environ.get("PROBE_REPO", "/tmp/probe-repo"))
OUT = Path(os.environ.get("PROBE_OUT", "/out"))

ANSWER = (
    "ANALYSIS COMPLETE. Recommendation: BUY.\n"
    "The 90-day series shows a sustained uptrend; RSI 58 is neutral, MACD "
    "crossed positive on 2026-08-04, and volume confirms the move. "
    "Position sizing 2% of book with a stop at the 50-day moving average.\n"
)
REFUSAL = (
    "REFUSED. The instrument field was empty, so there is nothing to analyze. "
    "No ticker was substituted and no market data was requested. "
    "Returning without a recommendation.\n"
)


def build_case(context):
    return {
        "case_id": "sdk-evidence-probe-v1",
        "input_type": "text",
        "inputs": [
            {"input_id": "pos-answer", "payload": "Analyse AAPL for 2026-08-20.",
             "payload_type": "text",
             "public_constraints": {"polarity": "positive"}},
            {"input_id": "neg-refuse", "payload": "Analyse  for 2026-08-20.",
             "payload_type": "text",
             "public_constraints": {"polarity": "negative"}},
        ],
    }


class CaseProvider:
    requirement_required = False

    def generate_case(self, context):
        return build_case(context)


def _entitlements() -> dict:
    backend = BackendClient(os.environ["KUMA_API_KEY"])
    try:
        return dict(backend.json("GET", "/sdk/entitlements/"))
    except Exception as exc:  # keep the probe running if this endpoint moves
        return {"error": f"{type(exc).__name__}: {exc}"}


def _usage(ent: dict) -> dict:
    keys = ("casegen_used", "judge_used", "credits", "credits_remaining",
            "casegen_limit", "judge_limit")
    flat = {}
    for k, v in ent.items():
        if k in keys:
            flat[k] = v
        elif isinstance(v, dict):
            flat.update({f"{k}.{kk}": vv for kk, vv in v.items() if kk in keys})
    return flat


SABOTAGE = (
    "I refused to perform this step. I did not read the requirement, did not "
    "run any test, and changed nothing on purpose. There is no result here.\n"
)

VARIANTS = {
    # name:            (official_case, track_files, upload_diff, write_files, send_logs, sabotage)
    "custom-nofiles":  (False, False, False, False, True,  False),
    "custom-files":    (False, True,  True,  True,  True,  False),
    "official-full":   (True,  True,  True,  True,  True,  False),
    "no-logs":         (False, False, False, False, False, False),
    # Identical to official-full except that every submission openly states the
    # step was not performed. A Judge that reads content must not pass this.
    "official-refuse": (True,  True,  True,  True,  True,  True),
    # Same again, but every submission is reported as an outright failure.
    # Distinguishes "rubber-stamps completed" from "rubber-stamps anything".
    "official-failed": (True,  True,  True,  True,  True,  True),
    # Isolates the file mutation: identical to official-full except that the
    # repository is left untouched. If this flips the verdict, the Judge is
    # deciding on whether any file changed, not on what the change contains.
    "official-nofiles": (True, True,  True,  False, True,  False),
    # Single-variable difference from official-nofiles: no logs= on submit.
    # This is the only thing that separates the passing probe from the
    # official template's own insufficient_evidence.
    "official-nologs":  (True, True,  True,  False, False, False),
}
# Variants whose submissions carry status="failed" instead of "completed".
FAILED_STATUS = {"official-failed"}


def main() -> None:
    name = sys.argv[1]
    (official_case, track_files, upload_diff, write_files, send_logs,
     sabotage) = VARIANTS[name]

    REPO.mkdir(parents=True, exist_ok=True)
    (REPO / "seed.txt").write_text("baseline\n", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    before = _entitlements()

    kwargs = dict(
        repo_path=str(REPO),
        judge_provider=None,             # official Judge
        track_files=track_files,
        upload_diff=upload_diff,
        on_failure="continue",
        save_local=True,
        allow_local=os.environ.get("KUMA_ALLOW_LOCAL") == "1",
    )
    if official_case:
        kwargs.update(case_provider=None, max_inputs=20,
                      requirement_path="/opt/bench/requirement-text.md")
    else:
        kwargs.update(case_provider=CaseProvider(), max_inputs=2,
                      requirement_path=None)

    run = create_run(**kwargs)
    print(f"[probe:{name}] run state={run.state}", flush=True)

    n = 0
    while True:
        item = run.get_input(full=True)
        if item is None:
            break
        n += 1
        iid = item.input_id
        negative = "neg" in iid
        text = SABOTAGE if sabotage else (REFUSAL if negative else ANSWER)

        if write_files:
            # A real file mutation, so file_change evidence is non-empty.
            (REPO / f"{iid}.md").write_text(text, encoding="utf-8")
            (REPO / "seed.txt").write_text(f"touched by {iid}\n", encoding="utf-8")

        logs = None
        if send_logs:
            p = OUT / f"{name}-{iid}.log"
            p.write_text(text * 5, encoding="utf-8")
            logs = [str(p)]

        print(f"[probe:{name}] -> {iid} polarity={'negative' if negative else 'positive'} "
              f"text={len(text)}c logs={'yes' if logs else 'no'}"
              f"{' SABOTAGED' if sabotage else ''}", flush=True)
        as_failed = name in FAILED_STATUS
        run.submit({"answer": text,
                    "verdict": "not_performed" if sabotage
                    else ("refused" if negative else "buy")},
                   status="failed" if as_failed else "completed",
                   error="step not performed" if as_failed else None,
                   logs=logs)

    report = run.judge()
    after = _entitlements()

    result = {
        "variant": name,
        "config": {"official_case": official_case, "track_files": track_files,
                   "upload_diff": upload_diff, "write_files": write_files,
                   "send_logs": send_logs, "sabotage": sabotage},
        "inputs_delivered": n,
        "report": {
            "status": report.status,
            "confidence": report.confidence,
            "stop_reason": report.stop_reason,
            "issues": [dict(i) for i in report.issues],
            "extensions": dict(report.extensions),
        },
        "usage_before": _usage(before),
        "usage_after": _usage(after),
    }
    print(f"\n[probe:{name}] STATUS = {report.status}  issues={len(report.issues)}",
          flush=True)
    for issue in report.issues:
        print(f"    {dict(issue).get('message') or dict(issue)}", flush=True)
    (OUT / f"probe-{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
