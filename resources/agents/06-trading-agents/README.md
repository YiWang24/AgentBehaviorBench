# TradingAgents (AgentBench adaptation)

AgentBench adaptation of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents),
pinned at `a33fd4c0f134485a43553a2c23a63cb14adbd88f`, Apache-2.0.

Upstream is a multi-agent trading-research pipeline: four analysts each run
their own tool loop, a bull and a bear researcher debate, a research manager
writes the investment plan, a trader turns it into a proposal, three risk
analysts stress it, and a portfolio manager issues a five-tier rating.

## What was adapted

The workflow is untouched. Only the boundaries the benchmark owns were changed.

| Concern | Upstream | Here |
| --- | --- | --- |
| Market/news/fundamental/macro data | yfinance, Alpha Vantage, FRED, Polymarket | `benchmark_mocks`, deterministic fixtures |
| Symbol identity | live yfinance `Ticker.info` | fixture table, generic profile for unknown tickers |
| Writable state | `~/.tradingagents` | `/tmp/trading-agents/{results,cache,memory}` |
| Entry point | `main.py` / Typer CLI | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

The model client is deliberately **not** modified. It still constructs
`ChatOpenAI` against `https://api.openai.com/v1` and reads `OPENAI_API_KEY`.
AgentBench injects a temporary per-run token into that variable and the trusted
Interceptor swaps in the real credential and the run-selected model.

### Selected graph

`langgraph.json` declares one graph, `trading_agents`, resolving to
`src/trading_agents_benchmark/graph.py:graph` — a zero-argument factory that
returns the compiled pipeline. The worker drives it through `run_analysis()`
rather than `graph.invoke()` directly, because the initial state is built by
upstream's `Propagator` and must include the memory-log context and the
resolved instrument identity.

Analysts selected: `market`, `social`, `news`, `fundamentals` (upstream default).
Debate and risk rounds are pinned to 1 so one Case stays bounded.

### Dependencies

Upstream declares 22 dependencies. The CLI and backtesting packages
(`typer`, `questionary`, `rich`, `tqdm`, `backtrader`, `redis`, `parsel`) are
not imported by the selected graph and are omitted. Every remaining package is
reached by a real import from `tradingagents`; `yfinance` and `stockstats` are
installed because `dataflows` imports them at module load even though every
call is mocked.

`cli/`, `tests/`, `assets/`, and `scripts/` from upstream are not vendored.

## Input and output

The official Case provider emits text, so the worker maps free text onto an
explicit `(ticker, trade_date)` request:

- `$NVDA` or a bare uppercase token that is not a common English word becomes
  the ticker; otherwise it falls back to `NVDA`.
- A `YYYY-MM-DD` date becomes the trade date; otherwise it falls back to
  `2024-05-10`.
- A structured payload with `ticker` / `trade_date` is used directly.

The fallback is deliberate: an unrecognised request analyses the default
instrument rather than inventing one. Fixture tickers with a real profile are
`NVDA`, `AAPL`, `MSFT`, `TSLA`, `SPY`; anything else gets a generic profile.

Public output:

```json
{
  "ticker": "NVDA",
  "trade_date": "2024-05-10",
  "rating": "Hold",
  "final_trade_decision": "...",
  "reports": {"market_report": "...", "news_report": "...", "...": "..."}
}
```

`raw_output` adds the resolved request, the selected analysts, report sizes, and
the mock trace (service, operation, safe summary). Neither contains credentials.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- All writes go to `/tmp/trading-agents`, created idempotently at process start
  because `/tmp` is a fresh tmpfs when the container starts.
- No executable tool bundles, so `/run/agentbench-tools` is unused.
- `debug=False` is required: upstream's debug path calls `msg.pretty_print()`,
  which writes to stdout and would corrupt the JSONL protocol.

Environment variables:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | temporary per-run token, injected by AgentBench |
| `OPENAI_BASE_URL` | model endpoint, `https://api.openai.com/v1` |
| `TRADINGAGENTS_DEEP_THINK_LLM` / `_QUICK_THINK_LLM` | model names sent upstream; the Interceptor overrides the effective model |
| `TRADINGAGENTS_RESULTS_DIR` / `_CACHE_DIR` / `_MEMORY_LOG_PATH` | writable paths under `/tmp` |
| `TRADING_AGENTS_STATE_ROOT` | root for the three paths above |

## Run it

```bash
python -m agentbench verify trading-agents
python -m agentbench certify trading-agents   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Every market figure is a deterministic fixture. Ratings are not investment
  advice and carry no relationship to real prices.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading, so a
  gap in mock coverage fails loudly.
- Reflection (`reflect_and_remember`) and report-tree export are not driven by
  the worker; the memory log still records each decision within a run.
