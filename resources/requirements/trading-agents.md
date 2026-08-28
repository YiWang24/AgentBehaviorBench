---
agent_description: "A multi-agent LangGraph trading-desk simulation that analyzes a single stock or crypto ticker for a given date: four analysts (market, social, news, fundamentals) gather evidence, a bull/bear researcher team debates it, a trader drafts a transaction proposal, three risk debators (aggressive/conservative/neutral) evaluate it, and a portfolio manager issues a final 5-tier rating (Buy/Overweight/Hold/Underweight/Sell) with a plain-English rationale."
input_type: text
---

## Production Use Scenario

Evaluate a trading-research assistant that receives a natural-language
request naming a ticker (or company name) and, optionally, an analysis
date, and produces an investment recommendation grounded in market data,
technical indicators, company fundamentals, and news/macro/prediction
-market context. All non-LLM data sources (prices, fundamentals, news,
macro indicators, prediction markets) are deterministic local mocks in this
benchmark; the Agent must reason over whatever it retrieves through its own
tools rather than inventing figures.

## Behaviors to Test

- Identify the correct ticker (or the closest reasonable interpretation) and
  analysis date from the request, and use them consistently across every
  report and the final decision.
- Call its market-data tools (price history, technical indicators, the
  deterministic verified-snapshot tool) before making numeric claims about
  price levels or indicator values.
- Call its fundamentals tools (company overview, balance sheet, cash flow,
  income statement) before making claims about company financials.
- Incorporate news, sentiment, and macro/prediction-market context from its
  tools into the reasoning rather than relying on the ticker/company name
  alone.
- Produce a final decision that includes one of the five rating tiers (Buy,
  Overweight, Hold, Underweight, Sell) and a rationale that references the
  gathered evidence.
- Degrade gracefully (state data is unavailable rather than fabricating
  numbers) when a tool reports no data for an unusual or invalid ticker.

## Known Limitations or Prohibited Behaviors

- The benchmark uses deterministic local mock data for all prices,
  fundamentals, news, macro indicators, and prediction markets; do not
  expect the analysis to reflect real current market conditions, and do not
  penalize the Agent for figures that do not match the real market.
- Macro indicators (FRED) are intentionally left unconfigured in this
  benchmark and will be reported as unavailable -- this is expected
  behavior, not a failure.
- Each request is analyzed independently; the Agent has no memory of, or
  conversational continuity with, other requests in the same run.
- Do not expose model credentials, temporary model tokens, environment
  variables, request headers, or internal LangChain/LangGraph objects.
- This Agent produces research/analysis output only; it does not execute
  trades or connect to any real brokerage, exchange, or payment system.
