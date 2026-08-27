# GPT Researcher (AgentBench adaptation)

AgentBench adaptation of [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher),
pinned at `6f998577d547b1e54ec662dac63583aa11e3b84b`, Apache-2.0.

Upstream's `multi_agents` workflow is a research team: an initial browsing pass,
an editor that plans the outline, a plan review step, parallel per-section
research, a writer, a fact checker, a diagram generator, and a publisher.

## Gate status

> **This adapter has not passed `agentbench verify`.** Its non-LLM boundary is
> fully exercised offline, but the pipeline cannot complete against the offline
> model mock. See [Offline gate limitation](#offline-gate-limitation) below.
> The registry entry is therefore `status = "adapting"`; only `certify` against
> a real model can promote it.

## What was adapted

The workflow is untouched. Only the boundaries the benchmark owns were changed.

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Tavily / Exa / DuckDuckGo / Serper / … | `benchmark_mocks`, deterministic corpus |
| Scraping | BeautifulSoup, Selenium, Firecrawl, browser | never reached — the benchmark retriever declares `requires_scraping = False` |
| Embeddings | `openai:text-embedding-3-small` | deterministic local vectors |
| Writable state | `./outputs` relative to CWD | `/tmp/gpt-researcher/workspace` |
| Export formats | markdown + pdf + docx | markdown only |
| Entry point | `main.py` / FastAPI backend | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

Declaring the retriever with `requires_scraping = False` is what removes the
entire scraper surface: results already carry their content, so no browser,
Selenium, or HTTP fetch layer ever runs.

### Why embeddings are mocked rather than intercepted

Upstream uses embeddings only to rank and compress retrieved context; the
vectors never reach the agent's visible output. The Model Interceptor has no
embeddings protocol plugin and OpenRouter exposes no embeddings endpoint, so
that traffic can be neither captured nor forwarded. Letting it escape to a live
provider would break the benchmark's network rule, so it is computed locally
from a hash of the text. This is a deliberate deviation from "the model
provider is the only real dependency" and is recorded here rather than hidden.

### Retriever name validation

`Config.parse_retrievers` validates the configured retriever against
`get_all_retriever_names()`, which eagerly imports every retriever module —
arxiv, exa_py, tavily, ddgs, firecrawl and the rest. All of them are mocked, so
the benchmark patches that validation instead of installing a dozen unused API
clients purely to satisfy a name check.

### Dependencies

Upstream declares roughly 173 dependencies covering every retriever, scraper,
embedding provider, and export format. The selected graph reaches 19 of them.
Provider-specific integrations are imported lazily and never selected, and
disabling pdf/docx export keeps the native rendering stack (`md2pdf`,
`weasyprint`, `htmldocx`) out of the image.

`backend/`, `frontend/`, `docs/`, `evals/`, `terraform/`, `mcp-server/`, and
`deep_agents/` are not vendored.

## Input and output

The official Case provider emits text and gpt-researcher's native input is a
research question, so the mapping is close to the identity: whitespace is
collapsed and the query is capped at 500 characters. A structured payload with
a `query` field is also accepted.

Public output:

```json
{
  "query": "What is retrieval-augmented generation?",
  "report": {"title": "...", "introduction": "...", "conclusion": "...", "report": "..."},
  "sources": ["https://benchmark.invalid/..."]
}
```

`raw_output` adds section and source counts, per-section report sizes, the
diagram count, and the mock trace. Neither contains credentials.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- The process changes directory to `/tmp/gpt-researcher/workspace` before any
  upstream import, because `ChiefEditorAgent` creates `./outputs/<run>`
  relative to the current directory as soon as it is constructed.
- The research agents print progress banners to stdout, so each request runs
  with stdout redirected to stderr and the JSONL reply is written to the
  original stream.
- Bounded for one Case: `MAX_ITERATIONS=1`, `MAX_SEARCH_RESULTS_PER_QUERY=3`,
  `MAX_SUBTOPICS=1`, one section, one plan revision, one fact-check revision.

## Offline gate limitation

`agentbench verify` serves a canned text reply for every model call. Five call
sites in `multi_agents` request JSON:

```python
plan = await call_model(prompt=prompt, model=..., response_format="json")
```

`call_model` does not forward `response_format` to the provider. It only
prompts for JSON and parses the reply with `json_repair`. Given the mock's
`"offline verification reply"`, `parse_json_markdown` returns a string, and the
planner fails on `plan.get("title")` with
`AttributeError: 'str' object has no attribute 'get'`.

Everything before that point works offline. A probe run reaches the planner
after 23 model calls on `/v1/chat/completions`, having served three searches
from the offline corpus and two embedding batches locally, with no network
access at all.

This is not repairable from the benchmark side without either fabricating agent
behaviour or teaching the offline mock a per-call-site JSON schema it cannot
know. It is unblocked by:

- running `agentbench certify gpt-researcher` against a real model, which
  returns JSON as the prompts request; or
- upstream forwarding `response_format` to the provider, which would let the
  existing offline mock answer with schema-shaped JSON.

## Run it

```bash
python -m agentbench certify gpt-researcher   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
python -m agentbench verify gpt-researcher    # currently fails at the planner, see above
```

## Known limitations

- Every source document is a deterministic benchmark fixture served from
  `benchmark.invalid`. Reports must not be presented as real research.
- Embeddings are local hashes, so semantic ranking quality is not
  representative of production behaviour.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
- pdf and docx export are disabled.
