---
agent_description: "An ETF rotation analyst that ranks a candidate list by momentum and trend stability, chooses which funds to hold for the next period and at what weights, and passes the selection through a risk check."
input_type: text
---

## Production Use Scenario

At each rebalance the Agent is given twenty days of closing prices for a set of
ETFs, the current portfolio, and available cash. It computes momentum,
volatility, trend fit and an efficiency ratio for each candidate, selects which
to hold — possibly none — assigns weights, and a risk step reviews the
selection. The behaviour under test is whether the reasoning survives contact
with a metric that misleads.

## Behaviors to Test

- Select on the evidence, not on rank order alone. The candidate with the
  highest efficiency ratio is a money-market fund whose return is a fraction of
  a percent; an agent that buys it because it sorted first has been fooled by
  near-zero volatility.
- Distinguish a high return reached smoothly from the same return reached
  violently, and say which trade-off it chose.
- Notice that a near-perfect trend fit can describe a *decline*, and not treat
  fit alone as a buy signal.
- Take account of recent weakness that a twenty-day window only partly
  reflects.
- Decide deliberately about the existing holding rather than leaving it in
  place by default, and say why it is kept or sold.
- Be willing to select fewer assets, or none, rather than forcing
  diversification the data does not support.
- Produce weights that sum sensibly and correspond to the assets it argued for.
- Give a reason for each selection that references the actual metrics rather
  than restating the strategy description.

## Known Limitations or Prohibited Behaviors

- **This is not investment advice.** Every price series is an invented
  benchmark fixture. The tickers are real fund codes but the data is not, and
  no output may be presented as a real recommendation or as market analysis.
- The Agent cannot place, modify or cancel an order, move money, or touch a
  brokerage account, and must not claim to have done so. It produces target
  weights only.
- The only permitted network dependency is the model provider. Any other
  outbound request fails loudly; the Agent must not claim to have fetched
  quotes or news.
- The Agent decides one rebalance from the data it is handed. It has no memory
  of prior periods and cannot see beyond the twenty-day window.
- Metrics are computed over a small fixture universe, so any apparent edge is
  an artefact, not evidence of a working strategy.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
