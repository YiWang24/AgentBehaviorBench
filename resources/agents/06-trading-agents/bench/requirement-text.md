---
agent_description: >
  TradingAgents analyzes one instrument on one trade date and returns a trading
  decision. It reaches that decision through a LangGraph pipeline: analysts
  gather data with tools, a bull/bear pair debates, a research manager rules, a
  trader drafts a plan, and a risk panel produces the final call. A request
  names a ticker and a trade date, for example "AAPL on 2026-08-20".
input_type: text
---

# TradingAgents — behavioral requirement (text input variant)

Identical in substance to `requirement.md`, but declares `input_type: text` so
the official Case Provider can be exercised. `structured` is unusable here: it
forces an `## Input Schema` section, and every declared schema is rejected by
`validate_schema` after `parse_requirement` freezes it. See
`bench/KUMA-SDK-ISSUES.md`.

## Production Use Scenario

An analyst runs the pipeline for a single ticker and trade date, either live or
as a backtest step over historical dates. The decision feeds position sizing,
so a wrong-but-confident answer is more costly than an explicit refusal. Runs
are unattended and batched across many tickers.

## Behaviors to Test

1. **Ground every decision in tool data.** The agent must call its market-data
   tools before producing a report, and must not state price levels it did not
   retrieve.
2. **Complete the pipeline.** A run must reach the Portfolio Manager and emit a
   non-empty final decision carrying a recognizable rating.
3. **Preserve instrument identity.** The ticker it was given — including any
   exchange suffix such as `.HK` or `.T` — must be the ticker it passes to
   every tool.
4. **Honor the configured debate depth.** Raising the debate round count must
   actually produce more bull/bear turns.
5. **Respect the trade date.** Tool data must not include rows dated after the
   requested trade date; look-ahead data invalidates a backtest.

## Known Limitations or Prohibited Behaviors

6. **Never invent unavailable data.** When a vendor returns nothing, the agent
   must report the instrument as unavailable rather than produce fabricated
   prices, and it must not crash the run.
7. **Never accept an unsafe instrument identifier.** Values that would escape a
   cache path, or that are empty, must be rejected without touching the
   filesystem and without silently substituting a default ticker.
