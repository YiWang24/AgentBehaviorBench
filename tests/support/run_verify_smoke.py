"""Manual Docker smoke test for the offline verification path.

Unit tests stub the runtime, so this script is what proves the real thing: a real
image build, a real interceptor, real TLS interception, locally generated model
replies, and an isolated network. Run it by hand when the runtime changes.

    python tests/support/run_verify_smoke.py [agent_id]

It intentionally requires no credentials. If it needs one, that is the bug.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentbench.cli.features.verify import verify  # noqa: E402
from agentbench.cli.verify_runtime import (  # noqa: E402
    VerifyOptions,
    build_verify_runtime,
)

DEFAULT_AGENT_ID = "langgraph-customer-support-agent"
PROBE_COUNT = 2
FORBIDDEN_KEYS = ("DEFUZEX_API_KEY", "OPENROUTER_API_KEY")


def main() -> int:
    agent_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AGENT_ID
    for key in FORBIDDEN_KEYS:
        # Verification must not merely avoid using these; it must run without them.
        os.environ.pop(key, None)

    lines: list[str] = []

    def emit(line: str) -> None:
        lines.append(line)

    offline = build_verify_runtime(
        VerifyOptions(input_count=PROBE_COUNT), output_fn=emit
    )
    # The JSON summary is the contract worth asserting on; the human report is
    # free to change layout without breaking this check.
    exit_code = verify(
        agent_id,
        options=VerifyOptions(input_count=PROBE_COUNT),
        output_fn=emit,
        offline=offline,
        as_json=True,
    )
    report = json.loads("\n".join(lines))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print(f"exit code                  : {exit_code}")
    print(f"captured request/response  : {report['model_calls']['captured_pairs']}")
    print(f"substituted secrets        : {report['substituted_secrets'] or 'none'}")
    print(f"SDK judge status           : {report['sdk_judge_status']}")

    if exit_code != 0 or report["verdict"] != "pass":
        print(f"offline verification smoke test FAILED: {report.get('reason')}")
        return 1
    if report["sdk_judge_status"] != "pass":
        # A missing status means the SDK never produced a report, which would mean
        # the Run was not actually driven by the SDK.
        print(
            "offline verification smoke test FAILED: expected the SDK Judge to "
            f"pass, saw {report['sdk_judge_status']!r}"
        )
        return 1
    if report["model_calls"]["captured_pairs"] < PROBE_COUNT:
        print(
            f"offline verification smoke test FAILED: expected at least "
            f"{PROBE_COUNT} captured pairs, saw "
            f"{report['model_calls']['captured_pairs']}"
        )
        return 1

    print("offline verification smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
