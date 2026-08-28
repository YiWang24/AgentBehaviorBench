# primo-stock-analyst (AgentBench adaptation)

AgentBench adaptation of [ivebotunac/PrimoAgent](https://github.com/ivebotunac/PrimoAgent),
pinned at `878f671`, MIT.

Four nodes: data collection → technical analysis → news intelligence →
portfolio manager.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Prices | yfinance | fixture OHLCV, per-ticker seeded walk |
| Fundamentals & news | Finnhub | fixture financials and one headline per ticker |
| Article scraping | Firecrawl | fixture article bodies |
| Technical indicators | the `ta` library over the price history | unchanged — computed from the fixture data |
| Model provider | OpenAI / Anthropic, config-selected | the OpenAI path |
| Entry point | daily CLI runner | persistent JSONL worker |

Only the external data is mocked. The indicators, the news-significance
scoring, and the portfolio manager all run unchanged; `raw_output` carries the
technical analysis and the news intelligence so a judge can check the
recommendation follows from them.

### Two seams, because the data is read two ways

The tool modules (`src.tools.yfinance_tool`, `finnhub_tool`, `firecrawl_tool`)
are replaced in `sys.modules` before the nodes import them — the named-function
pattern. But the technical node *also* imports `yfinance` directly and calls
`yf.Ticker(symbol).history(...)`, bypassing the tool layer, so the `yfinance`
library itself is stubbed with a `Ticker` whose `.history()` returns the same
fixture series as a DataFrame in yfinance's shape. Both seams draw from one
fixture module, so the two views of a ticker agree.

### The fixture tells a story

`BENC` trends up with improving financials and a positive headline; `DFUZ`
trends down with a profit warning. A recommendation that treats them alike, or
that buys `DFUZ` into its downtrend, is distinguishable from one that reads the
signals. `config.json`'s news source allow-list was extended with the fixture
source (`Benchmark Wire`) so the news node does not filter the fixture article
out.

### Details

- `config.json` is read from beside its module after install, so it ships as
  package data.
- `create_workflow()` returns an *uncompiled* `StateGraph`; the caller compiles
  it separately.
- The nodes are async; the worker uses `ainvoke`.
- yfinance, finnhub-python and firecrawl are not installed (their tools are
  replaced); the `ta`, `langchain`, and provider libraries are.

## Input and output

Plain text in — the tickers are read from the text, or from `symbols` in a JSON
payload (default `BENC`, `DFUZ`). `output` is the portfolio recommendation;
`raw_output` adds the technical and news analysis.

## Run it

```bash
python -m agentbench verify primo-stock-analyst
python -m agentbench certify primo-stock-analyst   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not investment advice.** Tickers and data are invented fixtures.
- Two fixture tickers; indicators are computed over invented history.
