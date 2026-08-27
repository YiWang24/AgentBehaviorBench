# crypto-hedge-fund (AgentBench adaptation)

AgentBench adaptation of
[51bitquant/ai-hedge-fund-crypto](https://github.com/51bitquant/ai-hedge-fund-crypto),
pinned at `c6750e0`, MIT.

A multi-timeframe crypto trading graph: fetch candles per interval → run
technical strategies (MACD) → risk management → portfolio management.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Market data | Binance REST (spot + futures) | deterministic fixture klines |
| Model provider | OpenAI/Groq/Gemini/Anthropic/Ollama, config-selected | the OpenAI path |
| Entry point | backtester / live loop | persistent JSONL worker, one rebalance |

Only the exchange data is mocked. The strategies, indicators, risk step, and
portfolio manager all run unchanged; `raw_output` carries the per-asset signals
and the final decisions so a judge can check they agree.

### The dual-path trap, paid twice

Everything imports under two names — `utils.x` and `src.utils.x` — because both
`src/` and its parent are on `sys.path`, and Python treats them as **different
module objects**. `data_node` constructs `src.utils.BinanceDataProvider`, whose
`__init__` builds `src.gateway...Client` (which pings Binance) — so the mock has
to patch *those* module names, not the `utils.`/`gateway.` aliases. Patching the
alias silently misses and the live fetch fires. Both the constructor ping and
the data methods are patched under the `src.` names.

### Fixture design

Each `(symbol, timeframe)` gets a reproducible seeded random walk. BTCUSDT
trends up over the window and ETHUSDT trends down, so a strategy reading both
has a real choice rather than one uniform signal; the per-step volatility is
enough that momentum and mean-reversion would disagree.

### Runtime and dependency notes

- The provider writes a `./cache` directory and `config.yaml` is read relative
  to the working directory, both of which fail on the read-only image root. The
  wrapper copies the config into `/tmp/crypto` and runs from there.
- `util_func.py` imports `CompiledGraph` from `langgraph.graph.state`, an alias
  dropped after the 0.2 line, so langgraph is pinned to `>=0.2.20,<0.3`.
- `llm/__init__.py` imports all five provider classes at module scope; they are
  installed so the imports resolve, but the OpenAI path is the one that runs.
- `config.yaml`'s `model.base_url` is `https://api.openai.com/v1`; the
  interceptor captures that host.

## Input and output

The graph decides from the fixture candles, not free text, so the Case's text
is recorded in `raw_output.note`. A JSON payload may override `tickers` or
`end_date`. `output` is the position decisions; `raw_output` adds the analyst
signals.

## Run it

```bash
python -m agentbench verify crypto-hedge-fund
python -m agentbench certify crypto-hedge-fund   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not investment advice.** Tickers are real; prices are invented fixtures.
- One rebalance, no memory across periods; nothing is ever traded.
