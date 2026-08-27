# Event Deep Research (AgentBench adaptation)

AgentBench adaptation of [bernatsampera/event-deep-research](https://github.com/bernatsampera/event-deep-research),
pinned at `b5b82fcbddb874d9beee1bca29aea362589efbf2`, MIT.

Upstream builds a chronology for a named person. A supervisor loop chooses
between researching a question, reflecting, and finishing; the research subgraph
searches, picks the best URLs, crawls them, chunks the text, checks each chunk
for biographical events, and merges what it finds into four categories. A final
node structures the result into dated events.

Upstream declares five graphs; the benchmark selects `supervisor`, the
top-level pipeline that drives the rest.

## Gate status

> **This adapter has not passed `agentbench verify`.** It runs 19 model calls and
> the whole research loop offline, then stops in the final structuring node. See
> [Offline gate limitation](#offline-gate-limitation). The registry entry is
> `status = "adapting"`; only certification against a real model can promote it.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Tavily | `benchmark_mocks`, deterministic corpus |
| Page crawl | Firecrawl API over aiohttp | deterministic markdown per corpus URL |
| Tracing | Langfuse, hosted | inert callback handler |
| Model provider | `google_genai:gemini-2.5-flash` | `anthropic:claude-sonnet-4-5`, by configuration |
| Entry point | LangGraph dev server | persistent JSONL worker |

### Choosing a provider was configuration, not a source edit

`Configuration.from_runnable_config` reads every field from an upper-cased
environment variable, so the model is selected without touching source. Three
details made that harder than it looks:

- Upstream defaults to Gemini, which the Model Interceptor cannot capture.
- The OpenAI path is broken upstream: `llm_service` pins `reasoning: "False"` as
  a **string**, and `ChatOpenAI` requires a dict, so construction fails
  validation. Anthropic accepts the field at construction but rejects it at call
  time with `AsyncMessages.create() got an unexpected keyword argument
  'reasoning'`. The benchmark drops that key when it is not a real dict — the
  value is `"False"`, so reasoning is off either way and no model behaviour
  changes. A genuine reasoning config is left alone.
- The four model roles do **not** all fall back to `LLM_MODEL`.
  `get_chunk_model()` falls back to a hardcoded `ollama:gemma3:4b`, which dials
  `localhost:11434` and is refused. All four roles are pinned explicitly.

## Input and output

The official Case provider emits text and the agent's native input is a person's
name, so the mapping is close to the identity.

```json
{"subject": "Ada Lovelace", "events": [...], "events_summary": "..."}
```

`raw_output` adds the event count, which categories were populated, the
supervisor iteration count, and the mock trace.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem, writes under `/tmp`.
- tiktoken's BPE tables are fetched at build time; the chunker needs them and
  the runtime has no egress.
- `MAX_TOOL_ITERATIONS` is 2 and `recursion_limit` is 40 so one Case stays
  bounded.

## Offline gate limitation

The canned offline reply extracts no real biographical events. The merge
subgraph then takes its "nothing new" early exit at
`merge_events_graph.py:209`, which returns `existing_events` as a
`CategoriesWithEvents` model. The final node in `src/graph.py` subscripts that
value as a mapping:

```python
early_prompt = structure_events_prompt.format(existing_events=existing_events["early"])
```

so the run ends with `TypeError: 'CategoriesWithEvents' object is not
subscriptable`. The merge path that runs when events *are* found builds a plain
dict, so a real model does not reach this branch.

Everything before it works offline: 19 model calls, search and crawl served from
the corpus, no network access.

Repairing it would mean editing the agent's own logic rather than the benchmark
boundary, so it is recorded instead. It is unblocked by
`agentbench certify event-deep-research` against a real model, or by upstream
normalising that early-exit return value.

## Known limitations

- Every source is a deterministic fixture from `benchmark.invalid`; the
  chronology is not real biography.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
