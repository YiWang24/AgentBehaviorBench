# excel-agent (AgentBench adaptation)

AgentBench adaptation of [Gen-Future/ExcelMind](https://github.com/Gen-Future/ExcelMind),
pinned at `d8bc5c8`.

A tool-calling loop over a loaded spreadsheet: ten pandas-backed tools for
filtering, sorting, grouping, aggregating, column statistics and previews.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Workbook | uploaded through the HTTP API | one fixture workbook loaded at startup |
| Provider | self-hosted vLLM/Ollama endpoints in `config.example.yaml` | the plain OpenAI path |
| Entry point | FastAPI app + web frontend | persistent JSONL worker |
| Knowledge base | ChromaDB-backed retrieval in `stream.py` | not vendored; it is not on the graph path |

Nothing upstream is substituted. Every tool reads the workbook through pandas
and reaches nothing over the network, so `benchmark_mocks` installs the egress
guard only.

### The fixture workbook is built, not committed

`src/excel_benchmark/make_workbook.py` holds the rows as Python literals and
writes the `.xlsx` at image build time. The repository therefore carries
reviewable text rather than an opaque binary, and the data is visible in a
diff.

The twelve rows are shaped so questions have checkable answers: one customer
appears under two spellings (`Northwind Ltd` and `northwind ltd`), one row has
no region, one quantity is negative, and the region with the most orders is not
the region with the highest revenue. A judge can tell a computed answer from a
plausible-sounding one.

### Configuration

`config.load_config()` looks for `config.yaml` relative to the working
directory, which is `/opt/agent`. The shipped file selects an `openai` provider
whose model, key and base URL are `${...}` references expanded from the
environment by upstream's own `_expand_env_vars`, so no credential is written
into the image.

`get_loader()` returns the *multi-table* loader, whose registration method is
`add_table`, not `load`.

### Licence

Upstream declares MIT in its README (badge and a `[MIT License](LICENSE)` link)
but ships no LICENSE file and no licence field in `pyproject.toml`. `NOTICE`
records the declaration rather than inventing a licence text.

## Input and output

Plain text in. `output` is the Agent's answer; `raw_output` adds every tool
call with its arguments, so a judge can check the answer was computed rather
than guessed.

## Run it

```bash
python -m agentbench verify excel-agent
python -m agentbench certify excel-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Twelve fixture rows; trends are illustrative only.
- The tools are read-only, so the workbook is never modified.
