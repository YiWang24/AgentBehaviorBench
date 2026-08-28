# mcube-patent-draft (AgentBench adaptation)

AgentBench adaptation of [yycyyv/M-Cube](https://github.com/yycyyv/M-Cube),
pinned at `75ab640`, MIT.

An eleven-node patent-drafting workflow: extract technical substance → draft
claims → analyse drawings → traceability check → (human review) → write
specification → logic and spec review, with retry loops on each generative
stage.

## What was adapted

Nothing upstream's logic is substituted. The drafting graph calls the model and
reaches nothing else — Chroma lives in `tools/`, off the graph path — so
`benchmark_mocks` installs the egress guard only.

| Concern | Upstream | Here |
| --- | --- | --- |
| Agent bundle | wired in `api/routers._build_draft_graph_for_runtime` | the same factory, reproduced in the wrapper |
| Model transport | raw httpx to an OpenAI-compatible endpoint | unchanged; captured by the Model Interceptor |
| Human review | attorney approves/edits claims via the API | auto-accepts the drafted claims (see below) |
| Entry point | FastAPI service | persistent JSONL worker |
| Vector search | Chroma-backed `RAGSearchService` | not on the drafting path; not vendored |

### Why the factory is reproduced, not imported

`api/routers.py` builds the bundle, but it imports FastAPI at module scope, so
it cannot be imported here. `_build_draft_graph_for_runtime` is self-contained
(`build_llm_callable`, `DraftAgentBundle`, the seven `BaseStructuredAgent`s,
`build_draft_workflow`), so it is reproduced in `graph.py` with the same retry
policies. The three stub helpers it falls back to — `_make_stub_llm_callable`,
`_DRAFT_STUBS`, `_minimal_specification_stub` — are copied *verbatim* into
`stubs.py` (that file carries a note saying so).

### The human-review gate

The graph interrupts once for an attorney to approve or edit the drafted claims.
The benchmark has no attorney, so the worker resumes with the claims the graph
itself produced — upstream's "approved" path. `raw_output.claims_auto_approved`
records this, so nothing is mistaken for a real review.

### Interception and structured output

`build_llm_callable` routes the `openai` provider (and `qwen`/`kimi`/`deepseek`/
`minimax`/`glm`) through an OpenAI-compatible endpoint via a raw httpx client;
the interceptor captures it by host. Every node uses
`response_format: {"type": "json_object"}` and, on retry, embeds the target
Pydantic schema as `[OUTPUT_SCHEMA]` in the prompt — both of which the offline
mock answers, so the structured stages produce parseable JSON under the gate.

When no key is supplied `build_llm_callable` returns None and the bundle falls
back to the deterministic stubs, which is upstream's own no-model behaviour.

## Input and output

Plain text in — the technical disclosure. `output` is the drafted claims and
specification; `raw_output` adds the technical summary, the traceability report,
and the review issues.

## Run it

```bash
python -m agentbench verify mcube-patent-draft
python -m agentbench certify mcube-patent-draft   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not legal advice.** The draft is a starting point for a patent attorney,
  not a filing-ready document, and no prior-art search is performed.
- No human attorney: the review gate is auto-accepted.
