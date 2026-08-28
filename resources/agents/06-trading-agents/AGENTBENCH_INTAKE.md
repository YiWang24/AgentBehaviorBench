# AgentBench Intake: trading-agents

## Source

- Repository: https://github.com/TauricResearch/TradingAgents.git
- Commit converted: `a33fd4c0f134485a43553a2c23a63cb14adbd88f`
- License: Apache-2.0 (`LICENSE`, and `pyproject.toml`)
- Selected via AgentRadar's catalog (`data/catalog.json`, sorted by
  `github_stars` descending in `agentradar.py`): rank 1, 100,523 stars,
  `langgraph_status: confirmed`, `project_kind: agent_project`.
- Queue: converted directly (single-agent onboarding), no `AgentFactory/`
  queue directories retained in this repository -- see `.gitignore`.

## Expected task

Text such as:

```text
Should I buy NVDA on 2024-05-10?
```

Expected successful behavior: four analysts (market, social, news,
fundamentals) each call their bound tools, a bull/bear researcher debate
converges to an investment plan, a trader turns that into a transaction
proposal, three risk debators (aggressive/conservative/neutral) discuss it,
and a portfolio manager issues a final 5-tier rating with a plain-English
rationale.

## Stage 1 analysis

Graph entry:

- `main.py` (upstream) constructs `TradingAgentsGraph(debug=True,
  config=DEFAULT_CONFIG.copy())` and calls
  `ta.propagate("NVDA", "2024-05-10")` -- the documented entry point.
- `tradingagents/graph/trading_graph.py:TradingAgentsGraph` builds the LLM
  clients, tool nodes, and a `StateGraph` (via `GraphSetup.setup_graph`),
  compiles it to `self.graph`, and exposes `.propagate(company_name,
  trade_date, asset_type="stock")`, which resolves instrument identity and
  memory-log context, builds the initial state via `Propagator`, and calls
  `self.graph.invoke(...)`.
- State: `tradingagents/agents/utils/agent_states.py:AgentState` (a
  `MessagesState` subclass) plus `InvestDebateState`/`RiskDebateState`.

Original model dependency:

- `tradingagents/llm_clients/factory.py` dispatches by `config["llm_provider"]`
  (default `"openai"`) to `OpenAIClient` (`llm_clients/openai_client.py`),
  which builds a `ChatOpenAI` subclass reading `OPENAI_API_KEY`
  (`llm_clients/api_key_env.py`) and, for native OpenAI with no custom
  `backend_url`, sets `use_responses_api=True` -- i.e. it calls
  `https://api.openai.com/v1/responses`, not `/v1/chat/completions`.
  **No source change needed**: this already matches the "keep the Agent's
  original provider URL and credential variable" contract, so `agent.toml`
  declares both `/v1/chat/completions` and `/v1/responses` routes under
  `agent_env = "OPENAI_API_KEY"`.

Original business/data tools (bound per analyst in
`TradingAgentsGraph._create_tool_nodes`):

- market: `get_stock_data`, `get_indicators`, `get_verified_market_snapshot`
- social: `get_news`
- news: `get_news`, `get_global_news`, `get_insider_transactions`,
  `get_macro_indicators`, `get_prediction_markets`
- fundamentals: `get_fundamentals`, `get_balance_sheet`, `get_cashflow`,
  `get_income_statement`

External/network risk inventory (default `data_vendors` in
`tradingagents/default_config.py`: `yfinance` for
core_stock/technical/fundamental/news, `fred` for macro, `polymarket` for
prediction markets -- `alpha_vantage`/reddit/stocktwits are never selected
and are not imported by `dataflows/interface.py`'s dispatch table):

- yfinance: real HTTP calls to Yahoo Finance via the `yfinance` package, from
  `dataflows/y_finance.py`, `dataflows/yfinance_news.py`,
  `dataflows/stockstats_utils.py` (`yf.download`), and two direct call sites
  outside the vendor layer (`agents/utils/agent_utils.py:resolve_instrument_identity`,
  `graph/trading_graph.py:_fetch_returns`).
- FRED: `dataflows/fred.py`, gated by `FRED_API_KEY`; raises
  `FredNotConfiguredError` (a `VendorNotConfiguredError`) before any HTTP
  call when the key is absent, and `interface.py` treats `macro_data` as an
  `OPTIONAL_CATEGORIES` entry -- an unconfigured vendor degrades to a
  sentinel string, not an error.
- Polymarket: `dataflows/polymarket.py`, keyless public API
  (`gamma-api.polymarket.com`); `prediction_markets` is also
  `OPTIONAL_CATEGORIES`, and the function already catches
  `requests.RequestException` into a graceful "unavailable" message.
- Memory log (`agents/utils/memory.py:TradingMemoryLog`): append-only local
  markdown file, no embeddings/vector DB (unlike some LangGraph agents) --
  nothing to mock here beyond redirecting the path under `/tmp`.

Mock plan (implemented in `benchmark_mocks/`):

- `synthetic_market.py`: one seeded PRNG (`hashlib.sha256` of the
  symbol/date) drives a shared deterministic OHLCV price-path generator plus
  fundamentals/balance-sheet/cash-flow/income-statement/news/prediction
  -market generators, each matching the real function's markdown/CSV output
  shape closely enough for the analyst prompts built around it.
- `patches.py`: replaces `tradingagents.dataflows.stockstats_utils.load_ohlcv`,
  every `tradingagents.dataflows.y_finance.get_*` function except
  `get_stock_stats_indicators_window` (left real -- it runs actual
  `stockstats` computation on the synthetic series), every
  `tradingagents.dataflows.yfinance_news.get_*_news*` function, and
  `tradingagents.dataflows.polymarket.get_prediction_markets`, all at their
  origin module (before `dataflows/interface.py` or anything else imports
  them by name). `market_data_validator.build_verified_market_snapshot` is
  also left real for the same reason as the indicator window function.
- `fake_yfinance.FakeTicker` replaces `yfinance.Ticker` globally (module
  attribute) for the two direct, non-dataflows call sites.
- FRED is left unconfigured on purpose (see above) rather than mocked.
- `requests.get`/`.post`/`Session.request` are blocked as a safety net for
  any path not explicitly mocked (alpha_vantage, reddit, stocktwits are
  dead code under the default vendor config, but this guarantees no
  accidental real network call regardless).

Runtime plan:

- No model-client changes (see above). `TRADINGAGENTS_LLM_PROVIDER=openai`
  set explicitly in the Dockerfile for clarity even though it is already the
  default.
- `TRADINGAGENTS_RESULTS_DIR` / `TRADINGAGENTS_CACHE_DIR` /
  `TRADINGAGENTS_MEMORY_LOG_PATH` redirected under `/tmp` (AgentBench's root
  filesystem is read-only at runtime); both `TradingAgentsGraph.__init__`
  and `TradingMemoryLog.__init__` already `mkdir(parents=True,
  exist_ok=True)` idempotently, so no extra bootstrap code was needed.
- `TRADINGAGENTS_CHECKPOINT_ENABLED=false` forced explicitly: it is already
  the default, but checkpointing resumes a prior run keyed on
  ticker+date+graph-shape, which is the wrong behavior for independent
  per-request JSONL invocations sharing one persistent worker process.
- `debug=False` on `TradingAgentsGraph` (upstream's `main.py` example uses
  `debug=True`, which streams and calls `message.pretty_print()` --
  straight to stdout, which would corrupt the JSONL wire protocol). The
  worker additionally wraps graph construction and every `propagate()` call
  in `contextlib.redirect_stdout(sys.stderr)` as defense in depth (one
  exception fallback path in `dataflows/y_finance.py` calls bare `print()`).

## Testing performed

`DEFUZEX_API_KEY`/`OPENROUTER_API_KEY` are not configured in this sandbox and
the `defuzex` SDK package (a private dependency of `defuzex-agentbench`
itself, required to even import `agentbench.harness.*` beyond the leaf
`registry` module, and to run `python -m agentbench certify`) is not
published to public PyPI and is not installed here -- `pip install -e .` on
the repository root fails on that requirement alone, before reaching this
Agent's own code. **`agentbench certify trading-agents` could not be run in
this environment** for that reason; this is an environment limitation, not
specific to this adapter (`05-langgraph-customer-support-agent`, the only
other Docker/interception agent in the registry, is also still `adapting`).
What was verified instead:

- `tests/test_registry.py`: the new `trading-agents` registry entry resolves
  correctly and the `adapting`-set assertion was updated (ran directly via
  `PYTHONPATH=<repo root> pytest tests/test_registry.py`, since
  `agentbench.harness.registry` itself has no `defuzex` dependency). 4
  pre-existing failures for *other* agents (`langgraph-chat-agent`,
  `email-assistant`, `swe-agent` -- their `enabled` values in
  `registry.toml` have drifted from this same test file) were observed and
  are unrelated to this change; confirmed via `git diff` that this change
  only appends a new `[[agents]]` block.
- `src/trading_agents_benchmark/tests/` (32 tests, run with this Agent's own
  dependencies installed in a scratch venv, no `defuzex` needed):
  - `test_input_mapping.py`: ticker/date extraction from free text,
    company-name aliasing, default fallback, structured-object input.
  - `test_mocks.py`: every `benchmark_mocks` replacement function against
    both a curated ticker (`NVDA`) and a synthetic one, the network safety
    net actually blocking `requests`, and FRED's real
    `FredNotConfiguredError` path. Confirms `get_stock_stats_indicators_window`
    and `build_verified_market_snapshot` (left un-patched) run *real*
    `stockstats` computation on top of the synthetic OHLCV series.
  - `test_graph_smoke.py`: a full, real `TradingAgentsGraph` run (real
    default analyst set, real graph/debate/risk structure) against a fake
    `BaseChatModel` (`tests/fakes.py`) standing in for the deep/quick
    thinking LLMs -- exercises every analyst's tool-calling loop against the
    real mocks and produces a valid 5-tier rating end to end (~30s).
  - `test_worker.py`: the same fake-LLM graph through `worker._handle()`
    directly -- JSONL-serializable output/raw_output, safe errors on
    missing/invalid input, and that a real-looking API key value never
    appears in the response.
- Subprocess-level `python -m trading_agents_benchmark.worker` (the exact
  `launch.argv`), piping a JSONL line via stdin with `PYTHONPATH` set to the
  Agent directory (mirrors the Docker image's `WORKDIR`-based import of
  `benchmark_mocks`): confirmed stdout contains exactly one JSON line and
  stderr is empty, both with no `OPENAI_API_KEY` set (clean
  `ValueError: API key ... is not set`) and with a dummy key plus
  `TRADINGAGENTS_LLM_BACKEND_URL=http://127.0.0.1:1/v1` to force a fast,
  network-free connection failure (clean `APIConnectionError`).
- `docker build` on this directory succeeds (`trading-agents-benchmark:test`)
  -- vendored `tradingagents` and `trading_agents_benchmark` both install and
  import correctly from a clean image.
- `docker run --rm -i --read-only --tmpfs /tmp:exec ... python -m
  trading_agents_benchmark.worker` (matching AgentBench's actual runtime
  policy: read-only root, tmpfs `/tmp`) with the same two credential
  scenarios above: both produced the identical clean single-line JSON
  response, confirming graph construction's directory creation
  (`results_dir`/`data_cache_dir`/`memory_log_path`, all redirected to
  `/tmp`) succeeds under a read-only root and the worker never attempts a
  write outside `/tmp`.

Not verified (requires `OPENROUTER_API_KEY`/`DEFUZEX_API_KEY` and the private
`defuzex` package): the Model Interceptor actually capturing and rewriting a
`/v1/responses` request end-to-end, and the DefuzeX Judge's evaluation of a
real (non-fake-LLM) decision.

## Known limitation not fixed

`TradingAgentsGraph.propagate(ticker, trade_date, asset_type)` has no
parameter for an external `run_config`/`thread_id`, and checkpointing is
force-disabled, so per docs/Agents/Reference.md section 10 ("Conversation
State") this Agent has no stateful thread continuation between multiple
SDK Inputs in one Run -- each JSONL request is analyzed independently. This
matches the Agent's real, one-shot "analyze this ticker on this date"
design; it is not a workaround.
