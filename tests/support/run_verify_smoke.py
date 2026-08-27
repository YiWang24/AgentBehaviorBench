"""Manual Docker smoke test for the offline verification path.

Unit tests stub the runtime, so this script is what proves the real thing: a real
image build, a real interceptor, real TLS interception, locally generated model
replies, and an isolated network. Run it by hand when the runtime changes.

    python tests/support/run_verify_smoke.py [agent_id]

It intentionally requires no credentials. If it needs one, that is the bug.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentbench.cli.features.verify import verify  # noqa: E402
from agentbench.cli.offline_runtime import build_offline_runtime  # noqa: E402
from agentbench.harness.offline import probe_inputs  # noqa: E402

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
        print(line, flush=True)

    offline = build_offline_runtime(
        max_inputs=PROBE_COUNT,
        probes=probe_inputs(count=PROBE_COUNT),
        output_fn=emit,
    )
    exit_code = verify(
        agent_id,
        input_count=PROBE_COUNT,
        output_fn=emit,
        offline=offline,
    )

    pairs = offline.captured_pair_count
    print()
    print(f"exit code                  : {exit_code}")
    print(f"captured request/response  : {pairs}")
    print(f"substituted secrets        : {offline.substituted_secrets or 'none'}")

    if exit_code != 0:
        print("offline verification smoke test FAILED")
        return 1
    if pairs < PROBE_COUNT:
        print(
            f"offline verification smoke test FAILED: expected at least "
            f"{PROBE_COUNT} captured pairs, saw {pairs}"
        )
        return 1
    if not any(line.startswith("Verification PASSED.") for line in lines):
        print("offline verification smoke test FAILED: missing pass verdict")
        return 1

    print("offline verification smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
