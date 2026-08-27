# breadfree-rotation (AgentBench adaptation)

AgentBench adaptation of
[FeiCoder/BreadFree-Simu](https://github.com/FeiCoder/BreadFree-Simu),
pinned at `6e5d9dd`, MIT.

Three nodes: `data_prep` computes momentum, volatility, trend fit and an
efficiency ratio over a twenty-day window and ranks the candidates; `analyst`
selects and weights; `risk_manager` reviews.

## What was adapted

Nothing upstream is substituted. The nodes compute from the price series in
graph state and call the model; nothing else is reached, so `benchmark_mocks`
installs the egress guard only.

| Concern | Upstream | Here |
| --- | --- | --- |
| Price history | project database, filled from a market-data provider | six fixture series, twenty-one closes each |
| Entry point | backtest engine looping over history | one rebalance through the JSONL worker |
| Model traffic | Tencent's OpenAI-compatible endpoint | unchanged; captured on its own route |

`breadfree/data` and `breadfree/engine` are not vendored — the decision graph
does not import them, and they carry the market-data and news clients.

### Interception without editing the source

`utils/llm_client.py` hardcodes `https://api.lkeap.cloud.tencent.com/v1` and
uses the plain `openai` client. That is the OpenAI chat wire protocol, so the
route matches that host with the `openai-chat` plugin rather than the vendored
URL being rewritten. The module also raises at import when `HUNYUAN_API_KEY` is
unset; the interceptor supplies it.

### The fixture market is the test

Run through upstream's own `calculate_efficiency_metrics`, the six series rank
like this:

| symbol   | 20d momentum | volatility | r2    | efficiency |
| -------- | ------------ | ---------- | ----- | ---------- |
| `511990` |      +0.19%  |   0.0000   | 1.000 |  1534.2    |
| `510300` |     +17.1%   |   0.0015   | 0.998 |    25.6    |
| `588000` |      +8.5%   |   0.0125   | 0.509 |     0.79   |
| `159915` |     +16.1%   |   0.0751   | 0.727 |     0.36   |
| `512880` |      +0.4%   |   0.0058   | 0.001 |     0.0002 |
| `518880` |     -11.8%   |   0.0009   | 1.000 |   -29.4    |

`511990` is a money-market fund. Its volatility is effectively zero, so the
efficiency ratio explodes and it ranks **first** — on a 0.19% return. An agent
that follows the ranking mechanically buys cash and calls it momentum; the
strategy's own fallback path does exactly that, which is worth knowing when
reading a run. `518880` fits a trend near-perfectly on the way *down*, and
`159915` reaches almost the same return as `510300` by a far worse path.

The portfolio already holds `512880`, which is going nowhere, so the agent also
has to decide about an existing position rather than starting from cash.

## Input and output

Plain text in; the nodes take no free-text input, so the Case's text is
recorded in `raw_output.request` alongside the decision rather than injected
into the prompts. `output` is the selected weights in readable form;
`raw_output` carries the analyst's per-asset reasons, the risk output, and the
computed metrics.

## Run it

```bash
python -m agentbench verify breadfree-rotation
python -m agentbench certify breadfree-rotation   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not investment advice.** Fund codes are real; the price data is invented.
- One rebalance, no memory of prior periods.
- The graph falls back to deterministic equal weights if the model call fails,
  so a run with zero captured calls still produces output — check the call
  count, not just the answer.
