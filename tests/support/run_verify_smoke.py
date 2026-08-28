"""Manual Docker smoke test for verify's preflight.

Unit tests stub the runtime, so this script is what proves the real thing: a real
image build, a real interceptor, real TLS interception, locally generated model
replies, and an isolated network. Run it by hand when the runtime changes.

    python tests/support/run_verify_smoke.py [agent_id]

It intentionally requires no credentials and not even the DefuzeX SDK. If it
needs either, that is the bug: preflight exists precisely to answer for an Agent
on a host where nothing else is set up yet.
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
from agentbench.cli.verify_runtime import VerifyOptions  # noqa: E402

DEFAULT_AGENT_ID = "langgraph-customer-support-agent"
PROBE_COUNT = 2
# Stripped so the run stays free and deterministic: without a provider
# credential it cannot reach the graded benchmark, which is the half this smoke
# test is not about.
FORBIDDEN_KEYS = ("DEFUZEX_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY")


def main() -> int:
    agent_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AGENT_ID
    for key in FORBIDDEN_KEYS:
        # Preflight must not merely avoid using these; it must run without them.
        os.environ.pop(key, None)

    lines: list[str] = []
    # The JSON summary is the contract worth asserting on; the human report is
    # free to change layout without breaking this check.
    exit_code = verify(
        agent_id,
        options=VerifyOptions(probe_count=PROBE_COUNT),
        output_fn=lines.append,
        as_json=True,
    )
    report = json.loads("\n".join(lines))
    preflight = report["preflight"]
    captured = report["model_calls"]["captured_pairs"]

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print(f"exit code                  : {exit_code}")
    print(f"probes answered            : {preflight['probes_answered']}")
    print(f"captured request/response  : {captured}")
    print(f"substituted secrets        : {report['substituted_secrets'] or 'none'}")

    # With every credential stripped the run cannot reach the graded benchmark,
    # so `partial` is the expected verdict — preflight held, the host could not
    # take it further. Anything else means preflight itself failed.
    if exit_code != 0 or report["verdict"] != "partial":
        print(f"preflight smoke test FAILED: {report.get('reason')}")
        return 1
    if preflight["probes_answered"] != PROBE_COUNT:
        print(
            f"preflight smoke test FAILED: expected {PROBE_COUNT} answered probes, "
            f"saw {preflight['probes_answered']}"
        )
        return 1
    if captured < PROBE_COUNT:
        print(
            f"preflight smoke test FAILED: expected at least {PROBE_COUNT} captured "
            f"pairs, saw {captured}"
        )
        return 1

    print("preflight smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
