#!/usr/bin/env bash
#
# Run one case from cases.json against the real TradingAgents agent, in Docker,
# and narrate what it does while it does it.
#
#   ./run-demo.sh --list                             # show the 10 cases
#   ./run-demo.sh                                    # run the baseline case
#   ./run-demo.sh --case neg-02-missing-data-must-not-fabricate
#
# Needs: docker, and a DeepSeek API key in DEEPSEEK_API_KEY.
#
# The image is built straight from TradingAgents/ with its own unmodified
# Dockerfile, so what runs is the upstream agent, not a fork of it. bench/ is
# mounted read-only at /opt/bench rather than baked in, which keeps the image
# free of anything we wrote.
#
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$BENCH_DIR")"
SOURCE_DIR="$AGENT_DIR/TradingAgents"

# Pinned in agent-side docs and matched to the vendored revision, so a stale
# image from a different revision can never be reused by accident.
REVISION="a33fd4c"
IMAGE="tradingagents:$REVISION"

# deepseek-v4-pro for deep thinking is not a preference, it is a workaround.
# With deepseek-v4-flash the Research Manager's structured-output call never
# returns: reproduced twice, both runs frozen at the same point with the
# container at 0% CPU and no network progress, still hanging past 16 minutes.
# The same model handles every other node fine, and upstream's own
# scripts/smoke_structured_output.py passes on it with a small prompt.
QUICK_MODEL="${TRADINGAGENTS_QUICK_THINK_LLM:-deepseek-v4-flash}"
DEEP_MODEL="${TRADINGAGENTS_DEEP_THINK_LLM:-deepseek-v4-pro}"

CASE_ID=""
LIST_ONLY=0
OUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --list)     LIST_ONLY=1; shift ;;
    --case)     CASE_ID="${2:?--case needs an input_id}"; shift 2 ;;
    --out-dir)  OUT_DIR="${2:?--out-dir needs a path}"; shift 2 ;;
    -h|--help)  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "docker is not on PATH." >&2; exit 1; }
[ -f "$SOURCE_DIR/Dockerfile" ] || {
  echo "Agent source is missing: $SOURCE_DIR" >&2
  echo "Expected the vendored TradingAgents checkout next to bench/." >&2
  exit 1
}

# --- build the agent image once -------------------------------------------
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE from $SOURCE_DIR (first run only, a few minutes)..."
  docker build -t "$IMAGE" "$SOURCE_DIR"
fi

# --list needs no credentials and no network.
if [ "$LIST_ONLY" = 1 ]; then
  exec docker run --rm --entrypoint python \
    -v "$BENCH_DIR":/opt/bench:ro \
    "$IMAGE" /opt/bench/demo_driver.py --cases /opt/bench/cases.json --list
fi

# --- credentials -----------------------------------------------------------
# CLAUDE_SWITCH_DEEPSEEK_AUTH_TOKEN is accepted as a fallback because that is
# where this machine already keeps a DeepSeek key.
API_KEY="${DEEPSEEK_API_KEY:-${CLAUDE_SWITCH_DEEPSEEK_AUTH_TOKEN:-}}"
if [ -z "$API_KEY" ]; then
  cat >&2 <<'MSG'
No API key found. Set one and re-run:

    export DEEPSEEK_API_KEY=sk-...
    ./run-demo.sh

A DeepSeek key is enough for the whole run. The data side (yfinance for
prices and indicators) needs no key at all.
MSG
  exit 1
fi

# --- output ----------------------------------------------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="${OUT_DIR:-/tmp/tradingagents-demo/$STAMP}"
mkdir -p "$OUT_DIR"
chmod 777 "$OUT_DIR"

echo "Image      : $IMAGE"
echo "Case       : ${CASE_ID:-<first input in cases.json>}"
echo "Models     : quick=$QUICK_MODEL  deep=$DEEP_MODEL"
echo "Output     : $OUT_DIR"
echo

DRIVER_ARGS=(--cases /opt/bench/cases.json --out /out/result.json)
[ -n "$CASE_ID" ] && DRIVER_ARGS+=(--input-id "$CASE_ID")

# The key is exported and passed by name so its value never lands in argv,
# where `ps` and shell history would pick it up.
export DEEPSEEK_API_KEY="$API_KEY"

status=0
docker run --rm -i \
  --entrypoint python \
  -e DEEPSEEK_API_KEY \
  -e TRADINGAGENTS_LLM_PROVIDER=deepseek \
  -e TRADINGAGENTS_QUICK_THINK_LLM="$QUICK_MODEL" \
  -e TRADINGAGENTS_DEEP_THINK_LLM="$DEEP_MODEL" \
  -e TRADINGAGENTS_TEMPERATURE=0 \
  -e PYTHONUNBUFFERED=1 \
  -e TRADINGAGENTS_CACHE_DIR=/tmp/ta/cache \
  -e TRADINGAGENTS_RESULTS_DIR=/tmp/ta/results \
  -e TRADINGAGENTS_MEMORY_LOG_PATH=/tmp/ta/memory.md \
  -v "$BENCH_DIR":/opt/bench:ro \
  -v "$OUT_DIR":/out \
  "$IMAGE" /opt/bench/demo_driver.py "${DRIVER_ARGS[@]}" || status=$?

# The driver only knows the container path, so translate it for the caller.
echo
echo "Full result (host path): $OUT_DIR/result.json"
exit "$status"
