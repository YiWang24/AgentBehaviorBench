"""Does the runtime-evidence envelope keep log text, or only its digest?

`build_runtime_evidence` is a pure function, so this needs no agent and no
network. It is handed a log segment that carries real text in `content` — the
same shape the SDK itself puts in `Submission.logs` — and reports which fields
survive into the envelope that the Official Judge upload path ships.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kuma.evidence.runtime import build_runtime_evidence, runtime_submission_id

RUN = "run_0123456789abcdef0123456789abcdef"
INPUT = "probe-input"

TEXT = (
    "FINAL TRANSACTION PROPOSAL: **BUY**\n"
    "The market analyst report shows a clear uptrend with RSI at 58.\n"
) * 20


def main() -> None:
    segment = {
        "path": "probe.jsonl",
        "segment_no": 0,
        "start_offset": 0,
        "end_offset": len(TEXT.encode()),
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "content": TEXT,          # the submission side carries the real text
        "encoding": "utf-8",
        "binary": False,
        "complete": True,
    }

    built = build_runtime_evidence(
        run_id=RUN,
        input_id=INPUT,
        step_id=INPUT,
        submission_id=runtime_submission_id(RUN, INPUT),
        root=Path("/tmp"),
        status="completed",
        output={"final_trade_decision": TEXT, "signal": "BUY"},
        error=None,
        file_evidence=None,
        logs=[segment],
        trace_evidence=None,
    )
    env = built.evidence
    blob = json.dumps(env, default=str)

    print(f"输入 log 段:  content {len(TEXT):,} 字符, sha256 {segment['sha256'][:16]}...")
    print(f"输入 output:  final_trade_decision {len(TEXT):,} 字符")
    print()
    print(f"信封 schema:  {env.get('schema_version')}")
    print(f"信封总大小:   {len(blob):,} 字符")
    print(f"missing:      {built.missing}   dropped={built.dropped_count}")
    print()
    for comp in env.get("components", ()):
        keys = sorted(k for k in comp if k not in ("component_id", "sequence"))
        print(f"  component {comp.get('sequence')}  kind={comp.get('kind')}")
        print(f"    字段: {keys}")

    print()
    # The decisive question: is any of the original text recoverable?
    probe_line = "FINAL TRANSACTION PROPOSAL"
    print(f"信封中能否找回正文片段 {probe_line!r}: {probe_line in blob}")
    print(f"信封中是否含 sha256 摘要: {segment['sha256'] in blob}")


if __name__ == "__main__":
    main()
