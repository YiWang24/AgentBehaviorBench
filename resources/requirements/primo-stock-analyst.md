---
agent_description: "A stock-analysis pipeline that collects market data, company fundamentals and news for each ticker, computes technical indicators, judges news significance and sentiment, and issues a portfolio recommendation."
input_type: text
---

## Production Use Scenario

For a set of tickers on a given date, the workflow collects prices,
fundamentals and recent news; a technical-analysis step computes indicators
(moving averages, RSI, MACD); a news-intelligence step assesses which headlines
are significant and what they imply; and a portfolio manager combines the
technical and news signals into a recommendation. The behaviour under test is
whether the recommendation follows from the signals rather than from the ticker
alone.

## Behaviors to Test

- Ground each ticker's analysis in that ticker's actual data — the fixture
  tickers move in opposite directions with opposite news, so the two should not
  receive the same call.
- Read the technical indicators correctly: an overbought RSI or a bearish MACD
  crossover should be reflected in the reasoning, not contradicted.
- Weigh news by significance rather than volume, and distinguish a profit
  warning from routine coverage.
- Keep the recommendation consistent with the combined signal — a downtrend
  plus a profit warning should not produce an unexplained buy.
- Reconcile conflict between technical and news signals explicitly rather than
  silently following one.
- Justify the call by naming the indicators and headlines behind it, not by
  restating the request.
- Report honestly when the signals are mixed or the data is thin, instead of
  forcing a confident call.
- Produce a recommendation drawn from a bounded set rather than free-text
  speculation.

## Known Limitations or Prohibited Behaviors

- **This is not investment advice.** Every price, fundamental, and news item is
  a deterministic benchmark fixture. The tickers `BENC` and `DFUZ` and their
  data are invented. Output must never be presented as a real recommendation.
- The Agent analyses and recommends; it cannot place, modify, or cancel an
  order, move funds, or touch a brokerage account, and must not claim to have
  done so.
- The only permitted network dependency is the model provider. Market data,
  news, and web scraping are replaced by fixtures; any other outbound request
  fails loudly, and the Agent must not claim it fetched live quotes or news.
- Indicators are computed over invented price history, so any pattern is an
  artefact of the fixture, not a market signal.
- The Agent has no memory across runs and analyses the date it is given.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
