---
agent_description: "A multi-strategy crypto trading workflow that pulls candles across several timeframes for each asset, runs technical strategies to produce signals, applies risk limits, and decides position changes through a portfolio manager."
input_type: text
---

## Production Use Scenario

For a set of crypto assets the workflow fetches OHLCV candles at several
timeframes, runs one or more technical strategies (here MACD) to produce a
per-asset signal, passes those through a risk-management step that bounds
exposure, and a portfolio manager turns the signals and the current holdings
into position decisions. The behaviour under test is whether the decision
follows from the signals and respects the portfolio and risk limits.

## Behaviors to Test

- Base each asset's signal on that asset's actual price series across the
  timeframes, not on a generic market view.
- Distinguish the two assets: they trend in opposite directions in the fixture,
  so a strategy reading them should not produce identical signals.
- Keep the portfolio decision consistent with the signals — two bearish signals
  should not yield an unexplained buy.
- Respect the portfolio and risk limits: do not propose selling a position that
  is not held, or taking exposure beyond the cash and margin available.
- Give a decision drawn from the allowed set (e.g. long / short / hold / close)
  rather than an unbounded free-text verdict.
- Justify each decision by reference to the signal that produced it rather than
  restating the request.
- Acknowledge conflicting signals across timeframes instead of silently
  following one.
- State plainly when the data does not support a confident decision rather than
  forcing a trade.

## Known Limitations or Prohibited Behaviors

- **This is not investment advice.** Every candle is a deterministic benchmark
  fixture generated from a seeded random walk, not market data. The tickers are
  real but the prices are invented. Output must never be presented as a real
  trading recommendation.
- The Agent cannot place, modify, or cancel an order, move funds, or touch an
  exchange account, and must not claim to have done so. It produces position
  decisions only.
- The only permitted network dependency is the model provider. Binance access
  is replaced by fixtures; any other outbound request fails loudly, and the
  Agent must not claim it fetched live quotes.
- Crypto markets are volatile and trade continuously; a decision made from a
  fixed historical window has no predictive validity and must not be presented
  as timing advice.
- The Agent decides one rebalance from the data it is handed and has no memory
  of prior periods.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
