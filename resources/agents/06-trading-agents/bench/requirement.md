---
agent_description: >
  TradingAgents analyzes one instrument on one trade date and returns a trading
  decision. It reaches that decision through a LangGraph pipeline: analysts
  gather data with tools, a bull/bear pair debates, a research manager rules, a
  trader drafts a plan, and a risk panel produces the final call.
input_type: structured
---

# TradingAgents — behavioral requirement

Schema note: the front matter keys are limited to `agent_description`,
`input_type`, and `input_schema`, and the three `##` sections below are all
required by `kuma.repository.requirements` — a plain markdown file is rejected.
The payload schema is intentionally permissive on `ticker` so that malformed
identifiers still reach the agent; rejecting them is the agent's job, not the
harness's.

The payload shape is `{ticker, date, analysts?, max_debate_rounds?,
max_risk_rounds?, asset_type?}`.

An `## Input Schema` section is deliberately omitted: declaring one currently
makes `create_run()` fail outright. `parse_requirement` freezes the parsed
schema into a `MappingProxyType`, and the later `validate_schema` call runs
jsonschema's `check_schema`, whose type checker accepts only `dict` for
`"object"` — so every requirement-declared schema is rejected as "not a valid
JSON Schema" even when it is one. See `bench/KUMA-SDK-ISSUES.md`.

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
   non-empty `final_trade_decision` carrying a recognizable rating.
3. **Preserve instrument identity.** The ticker it was given — including any
   exchange suffix — must be the ticker it passes to every tool.
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
