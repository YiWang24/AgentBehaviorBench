# TradingAgents (AgentBench adapter)

Wraps [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(`a33fd4c0f134485a43553a2c23a63cb14adbd88f`, Apache-2.0) for DefuzeX AgentBench.
TradingAgents is a multi-agent LangGraph trading-desk simulation: four
analysts (market, social, news, fundamentals) hand off to a bull/bear
research debate, a trader, three risk debators, and a portfolio manager that
issues a final 5-tier rating (Buy / Overweight / Hold / Underweight / Sell).

## What was changed vs upstream

Nothing in `src/tradingagents/` (the vendored package) was modified. The
default provider (`llm_provider="openai"`) already reads `OPENAI_API_KEY` and
calls `api.openai.com` directly, so no model-client rewrite was needed --
AgentBench's Model Interceptor captures that native traffic as-is (see
`agent.toml`).

What was added:

- `benchmark_mocks/`: deterministic, seeded replacements for every non-LLM
  network call (Yahoo Finance via `yfinance`, FRED, Polymarket). See
  "Mocked data sources" below.
- `src/trading_agents_benchmark/`: the JSONL worker (`worker.py`), free-text
  -> `(ticker, trade_date, asset_type)` mapping (`input_mapping.py`), and the
  `langgraph.json` factory target (`graph.py`).

## Selected Graph

`TradingAgentsGraph` (`src/tradingagents/graph/trading_graph.py`), built with
the default analyst set `("market", "social", "news", "fundamentals")` and
`debug=False`. `langgraph.json` points at a zero-argument factory
(`graph.py:graph`) that constructs `TradingAgentsGraph` and returns its
compiled `.graph`; the worker instead calls the higher-level
`TradingAgentsGraph.propagate(ticker, trade_date, asset_type)`, which is
upstream's own documented entry point (see `main.py` in the original repo) --
it resolves instrument identity, injects memory-log context, and invokes the
same compiled graph.

## Input / output contract

Official SDK Cases are plain text (see `resources/requirements/trading-agents.md`).
`input_mapping.py` recovers a ticker (regex for bare symbols plus a small
company-name alias table, e.g. "Tesla" -> `TSLA`; falls back to `NVDA`, the
same ticker upstream's `main.py` example uses) and a trade date (`YYYY-MM-DD`
in the text, else today in UTC). Structured input is also accepted:
`{"prompt" | "text" | "message" | "query": "..."}`.

`output` (JSON-compatible):

```json
{
  "ticker": "NVDA",
  "trade_date": "2024-05-10",
  "rating": "Buy",
  "final_trade_decision": "...",
  "investment_plan": "...",
  "trader_investment_plan": "...",
  "market_report": "...",
  "sentiment_report": "...",
  "news_report": "...",
  "fundamentals_report": "..."
}
```

`rating` is `TradingAgentsGraph.propagate()`'s own normalized signal (one of
the five tiers, via `signal_processing.SignalProcessor`, which defaults to
`"Hold"` if no tier keyword is found -- it never raises). `raw_output` adds
the research/risk judge decisions, bull/bear debate history, and a message
count for diagnostics.

## Mocked data sources

Per `data_vendors` in `tradingagents/default_config.py`, the default graph
only ever needs `yfinance` (prices, indicators, fundamentals, news),
`fred` (macro), and `polymarket` (prediction markets):

| Source | Strategy |
| --- | --- |
| `yfinance` (prices, fundamentals, balance sheet, cash flow, income statement, insider transactions, news) | `benchmark_mocks/synthetic_market.py` replaces the vendor functions in `tradingagents/dataflows/y_finance.py`, `yfinance_news.py`, and `stockstats_utils.load_ohlcv` with deterministic, ticker-seeded generators. `get_stock_stats_indicators_window` (technical indicators) and `build_verified_market_snapshot` (the market analyst's required deterministic snapshot tool) are left un-patched and run their real `stockstats` computation on top of the synthetic OHLCV series, so indicator values are genuinely computed, not hand-faked. |
| `yfinance.Ticker` direct calls | Two call sites bypass the vendor layer entirely (`agent_utils.resolve_instrument_identity`'s `.info` lookup and `trading_graph._fetch_returns`'s `.history()` call for reflection). `benchmark_mocks/fake_yfinance.FakeTicker` replaces `yfinance.Ticker` itself for these. |
| `fred` (macro indicators) | Left untouched. No `FRED_API_KEY` is set, so `tradingagents.dataflows.fred.get_api_key()` raises `FredNotConfiguredError` before any HTTP call -- a real, already-graceful "vendor unavailable" path (macro is an `OPTIONAL_CATEGORIES` entry in `interface.py`), not a crash. |
| `polymarket` (prediction markets) | `get_prediction_markets` is replaced with a small canned set of forward-looking markets in the real response format. |
| anything else (alpha_vantage, reddit, stocktwits) | Unreachable under the default vendor config; `benchmark_mocks/patches.py` also blocks `requests.get`/`.post`/`Session.request` as a safety net so a misconfiguration can never fall back to a real network call. |

All patches are applied by `benchmark_mocks.apply_patches()`, called before
any `tradingagents` import in both `worker.py` and `graph.py`. See
`patches.py` for why patch order matters (each vendor module is patched at
its own origin, before any other module imports a name from it).

## Filesystem / runtime notes

`TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, and
`TRADINGAGENTS_MEMORY_LOG_PATH` are redirected under `/tmp` in the
Dockerfile (AgentBench's root filesystem is read-only at runtime).
`TradingAgentsGraph.__init__` and `TradingMemoryLog.__init__` already create
these directories idempotently on every construction, so no extra runtime
bootstrap is needed. `TRADINGAGENTS_CHECKPOINT_ENABLED=false` is forced
explicitly (matching the upstream default) because checkpointing resumes
from a prior run for the same ticker+date+graph-shape signature, which would
be wrong for independent per-request benchmark invocations.

## Run locally (outside AgentBench, real OpenAI key)

```bash
cd resources/agents/06-trading-agents
python -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env  # fill in OPENAI_API_KEY
echo '{"input": "Should I buy NVDA on 2024-05-10?"}' | python -m trading_agents_benchmark.worker
```

## Certify

```bash
python -m agentbench certify trading-agents
```
