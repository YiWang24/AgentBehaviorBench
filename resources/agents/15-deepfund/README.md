# DeepFund (AgentBench adaptation)

AgentBench adaptation of [HKUSTDial/DeepFund](https://github.com/HKUSTDial/DeepFund),
pinned at `e31f1c2eae845b8627fe65621ba4febaf55c2385`, MIT.

Upstream runs a configurable set of analysts in parallel over one ticker — each
writing a signal — then a portfolio manager weighs them against the current
holdings and records a decision. The benchmark selects a single-ticker,
two-analyst configuration (fundamental and technical) so one Case stays bounded.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Market data | Alpha Vantage / yfinance via `apis.router.Router` | `benchmark_mocks`, deterministic fixtures |
| Database | Supabase, or SQLite with `--local-db` | SQLite inside the container tmpfs |
| Log directory | `<package>/../logs` | explicit `DEEPFUND_LOG_DIR` |
| Entry point | `main.py` with argparse and a YAML config | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

Every analyst builds its own `Router` and calls through it, so replacing that
one class before the analyst modules are imported covers the whole market-data
surface — prices, fundamentals, news, insider trades, and macro indicators.

The fixtures are constructed from **DeepFund's own Pydantic models**
(`OHLCVCandle`, `MediaNews`, `InsiderTrade`, `Fundamentals`, `MacroEconomic`)
rather than hand-rolled dicts, so a change in their shape fails loudly at
construction instead of silently producing something the analysts cannot read.

### The one source change

`util/logger.py` derived its log directory from `__file__`:

```python
self.log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
```

After `pip install .` that resolves inside `site-packages`, whose parent is
read-only at runtime, so the logger raised `PermissionError` at import. Per
`docs/Agents/Reference.md` §15 the fix is to make the path explicit, so the line
now honours `DEEPFUND_LOG_DIR` and falls back to the original expression when it
is unset. Nothing else in the vendored source is modified.

### Database

Upstream documents schema creation as a separate step
(`python database/sqlite_setup.py`). The benchmark starts from an empty tmpfs
every run, so the adapter invokes that setup before opening the database. The
SQLite file lives under `/tmp`, so a run leaves nothing behind and cannot reach
a shared instance.

### Dependencies

`llm/provider.py` imports every provider SDK at module load and
`util/db_helper.py` imports the Supabase backend even in local mode, so both are
installed although only OpenAI and SQLite are ever used.

## Input and output

The official Case provider emits text, so the worker maps free text onto an
explicit `(ticker, trading date)` pair: a bare uppercase token that is not a
common English word becomes the ticker, a `YYYY-MM-DD` string becomes the date,
and anything unrecognised falls back to `NVDA` on `2024-05-10` rather than
inventing an instrument.

```json
{"ticker": "NVDA", "trading_date": "2024-05-10", "decisions": [...]}
```

`raw_output` adds the analysts used, the decision count, remaining cash, and the
mock trace.

## Run it

```bash
python -m agentbench verify deepfund
python -m agentbench certify deepfund   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not investment advice.** Every figure is a deterministic fixture.
- Decisions are written to a throwaway SQLite database; no order is ever placed.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
