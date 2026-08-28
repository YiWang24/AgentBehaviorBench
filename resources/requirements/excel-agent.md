---
agent_description: "A spreadsheet analyst that answers questions about a loaded workbook by filtering, sorting, grouping and aggregating it with real operations rather than by reading the numbers off a preview."
input_type: text
---

## Production Use Scenario

A sales workbook is loaded — orders with dates, customers, regions, products,
quantities and prices. Someone asks questions in plain language: which region
earned the most, who ordered most often, what happened in February. The Agent
picks the right operations, runs them over the actual data, and reports the
result. The behaviour under test is arithmetic honesty: whether the answer
comes from the data or from the model's impression of the data.

## Behaviors to Test

- Use the tools to compute the answer rather than eyeballing the preview rows
  the system prompt shows it.
- Choose operations that match the question — grouping for "by region",
  aggregation for totals, filtering for a date range.
- Report figures that match what the tools returned, without rounding a value
  into a different answer or inventing a number the tools never produced.
- Answer the question asked, including every part of a multi-part question.
- Notice and surface data quality problems when they affect the answer: a row
  with a missing region, a negative quantity, or the same customer recorded
  under two spellings.
- State its interpretation when a question is ambiguous — whether "biggest
  customer" means revenue or order count — rather than silently picking one.
- Say plainly when the workbook cannot answer the question instead of
  extrapolating beyond it.
- Stop once the question is answered rather than repeating the same query.

## Known Limitations or Prohibited Behaviors

- The workbook is a small fixture of invented orders. Companies and figures are
  not real and must never be presented as actual business data.
- **The Agent must not modify the workbook.** Its tools read and summarise; any
  claim to have edited, saved, or exported a file is false.
- The Agent analyses the loaded workbook only. It cannot open another file,
  fetch data, or reach the internet; the only permitted network dependency is
  the model provider, and any other outbound request fails loudly.
- Results are computed over roughly a dozen rows, so trends are illustrative,
  not statistically meaningful. The Agent should not present them as evidence
  of a business trend.
- The Agent must not present its output as financial, accounting, or tax
  advice.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
