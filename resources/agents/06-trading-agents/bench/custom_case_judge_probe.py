"""Feed the Official Judge custom Cases modelled on the SDK's own examples.

Shapes are copied from the SDK repository, not invented:
  cc-minimal   examples/minimal_local.py::local_case, verbatim structure
  cc-swe       the six SWE steps the backend's own casegen returned for us
  cc-path-ok   acceptance criteria written so that the evidence the SDK really
               ships is enough to check them: file_change components carry the
               path, so "create report-<step>.md" is decidable from paths alone
  cc-path-bad  the same Case, deliberately violated (wrong filenames)

cc-path-ok / cc-path-bad are the discriminating pair. If the Judge decides them
differently, it does use the evidence it has and the problem is confined to
text answers. If both come back insufficient_evidence, it ignores evidence that
was sufficient.

The requirement file is the SDK's own examples/single_agent_template/
requirement.md, unmodified.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from kuma import create_run
from kuma.transport.backend import BackendClient

REPO = Path(os.environ.get("PROBE_REPO", "/tmp/cc-repo"))
OUT = Path(os.environ.get("PROBE_OUT", "/out"))
REQUIREMENT = "/opt/examples/single_agent_template/requirement.md"


# ---------------------------------------------------------------- case shapes

def case_minimal() -> dict:
    """examples/minimal_local.py::local_case — structure copied verbatim."""
    return {
        "case_id": "case_local_demo",
        "input_type": "text",
        "inputs": [
            {
                "input_id": "input_local_1",
                "payload_type": "text",
                "payload": "Return a bounded maintenance result.",
            }
        ],
    }


_SWE_STEPS = [
    "Read the requirement document and summarise what must change.",
    "Run the existing test suite and report which tests fail.",
    "Locate the production code responsible for the failure.",
    "Apply the smallest change that fixes it.",
    "Re-run the test suite and confirm the failure is gone.",
    "Report which files you changed and why.",
]


def case_swe() -> dict:
    """The shape the backend's own casegen returns: generic SWE repair steps."""
    return {
        "case_id": "case_swe_repair_shape",
        "input_type": "text",
        "inputs": [
            {"input_id": f"step-{i}", "payload_type": "text", "payload": text}
            for i, text in enumerate(_SWE_STEPS, start=1)
        ],
    }


def _steps(basename_only: bool) -> list[tuple[str, str]]:
    """Acceptance phrased against how the SDK actually reports paths.

    In docker mode the tracking root is "/" (api.py:233), so evidence paths are
    container-relative, not repository-relative. The first phrasing assumed a
    repository root and the Judge correctly rejected it; this one only requires
    the basename to match, which the evidence can actually support.
    """
    if basename_only:
        tail = ("Acceptance: a created file_change exists whose path ends with "
                "'/{name}' or equals '{name}'. Log files under out/ are expected "
                "and must not count against this.")
    else:
        tail = ("Create no other file. Acceptance: a file_change of type created "
                "with path '{name}' exists.")
    return [
        (f"step-{i}",
         f"Create a file named exactly 'report-{i}.md'. " + tail.format(name=f"report-{i}.md"))
        for i in (1, 2, 3)
    ]


_PATH_STEPS = _steps(basename_only=False)


def case_claim() -> dict:
    """Criterion is about the claim itself, which the envelope does carry."""
    return {
        "case_id": "case_claim_status",
        "input_type": "text",
        "inputs": [
            {"input_id": f"step-{i}", "payload_type": "text",
             "payload": f"Perform step {i} and report success. Acceptance: the "
                        f"agent_response_claim for this step must be 'completed'. "
                        f"A 'blocked' claim must not pass.",
             "public_constraints": {"required_claim": "completed"}}
            for i in (1, 2, 3)
        ],
        "rubric": {f"step-{i}": {"acceptance": "agent_response_claim must be 'completed'"}
                   for i in (1, 2, 3)},
    }


def case_path(steps=None, case_id="case_path_observable") -> dict:
    """Criteria decidable from file paths alone — the evidence the SDK ships."""
    return {
        "case_id": case_id,
        "input_type": "text",
        "inputs": [
            {"input_id": iid, "payload_type": "text", "payload": text,
             "public_constraints": {"required_created_path": f"{iid.replace('step', 'report')}.md"}}
            for iid, text in (steps or _PATH_STEPS)
        ],
        "rubric": {
            iid: {"acceptance": f"a created file_change ending in "
                                f"{iid.replace('step', 'report')}.md must be present"}
            for iid, _ in (steps or _PATH_STEPS)
        },
    }


VARIANTS = {
    # name:        (case builder, files written per input_id)
    "cc-minimal":  (case_minimal, None),
    "cc-swe":      (case_swe, None),
    # Satisfies the criterion exactly.
    "cc-path-ok":  (case_path, lambda iid: iid.replace("step", "report") + ".md"),
    # Violates it: writes a differently named file, so the required path is
    # absent from the evidence while everything else stays identical.
    "cc-path-bad": (case_path, lambda iid: "WRONG-" + iid + ".txt"),
    # cc-path-ok with the acceptance phrased against container-relative paths,
    # which is how the SDK actually reports them. Same files written.
    "cc-path-fixed": (lambda: case_path(_steps(basename_only=True),
                                        case_id="case_path_basename"),
                      lambda iid: iid.replace("step", "report") + ".md"),
    # The criterion is about the claim, which the envelope really does carry,
    # and every submission is sent as failed so the claim reads 'blocked'.
    "cc-claim-failed": (case_claim, None),
}
# Variants whose submissions are sent with status="failed".
SUBMIT_FAILED = {"cc-claim-failed"}


class Provider:
    requirement_required = False

    def __init__(self, builder):
        self._builder = builder

    def generate_case(self, context):
        return self._builder()


def _entitlements() -> dict:
    try:
        return dict(BackendClient(os.environ["KUMA_API_KEY"]).json("GET", "/sdk/entitlements/"))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    name = sys.argv[1]
    builder, filename_for = VARIANTS[name]

    REPO.mkdir(parents=True, exist_ok=True)
    (REPO / "README.md").write_text("# custom case probe\n", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    before = _entitlements()

    case = builder()
    run = create_run(
        repo_path=str(REPO),
        requirement_path=REQUIREMENT,
        case_provider=Provider(builder),
        judge_provider=None,                 # official Judge
        max_inputs=len(case["inputs"]),
        track_files=True,
        upload_diff=True,
        on_failure="continue",
        save_local=True,
        allow_local=os.environ.get("KUMA_ALLOW_LOCAL") == "1",
    )
    print(f"[cc:{name}] run state={run.state}  inputs={len(case['inputs'])}", flush=True)

    written = []
    while True:
        item = run.get_input(full=True)
        if item is None:
            break
        iid = item.input_id
        if filename_for is not None:
            fname = filename_for(iid)
            (REPO / fname).write_text(f"Result for {iid}.\n", encoding="utf-8")
            written.append(fname)
        log = OUT / f"{name}-{iid}.log"
        log.write_text(f"step {iid} executed\n" * 10, encoding="utf-8")
        print(f"[cc:{name}] -> {iid}"
              + (f"  wrote {fname}" if filename_for else ""), flush=True)
        failed = name in SUBMIT_FAILED
        run.submit({"answer": f"Completed {iid}.",
                    "created": written[-1] if written else None},
                   status="failed" if failed else "completed",
                   error="step did not complete" if failed else None,
                   logs=[str(log)])

    report = run.judge()
    after = _entitlements()

    print(f"\n[cc:{name}] STATUS = {report.status}  confidence={report.confidence} "
          f"issues={len(report.issues)}", flush=True)
    for issue in report.issues:
        print(f"    {dict(issue).get('message') or dict(issue)}", flush=True)
    print(f"    flags={dict(report.extensions).get('flags')}", flush=True)
    for sr in dict(report.extensions).get("step_results") or ():
        print(f"    {sr}", flush=True)

    (OUT / f"cc-{name}.json").write_text(json.dumps({
        "variant": name,
        "case_id": case["case_id"],
        "files_written": written,
        "report": {"status": report.status, "confidence": report.confidence,
                   "issues": [dict(i) for i in report.issues],
                   "extensions": dict(report.extensions)},
        "credits_before": (before.get("credits") or {}).get("balance"),
        "credits_after": (after.get("credits") or {}).get("balance"),
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
