# deep-research (AgentBench adaptation)

AgentBench adaptation of
[tarun7r/deep-research-agent](https://github.com/tarun7r/deep-research-agent),
pinned at `a974b4c`, MIT.

Four nodes: plan → search → synthesize → write_report, each gated by a
validation check that ends the run early if a stage produces nothing usable.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | DuckDuckGo (`ddgs`), optionally Tavily | fixture result list on `benchmark.invalid` |
| Content extraction | httpx + BeautifulSoup over live pages | fixture article bodies |
| Model provider | Gemini by default; Ollama / llama.cpp / OpenAI | the OpenAI path |
| Entry point | Chainlit app | persistent JSONL worker |

### The seam is the two methods that touch the network

Rather than swap the provider classes, `benchmark_mocks.install()` replaces the
two methods that actually reach out — `DuckDuckGoProvider._execute_search` and
`ContentExtractor.extract_content_async` — on the classes themselves. The
retry, rate-limit and circuit-breaker wrappers around them, and the
`SearchResult` shape they return, are therefore exercised unchanged. The
install runs before `src.utils.tools` (which builds the providers at import
time) is imported.

The corpus is four sources written to disagree: two conflict on whether
retrieval's accuracy gains survive latency budgets, one is a thin note with no
numbers, and none states a single headline figure — so a report that overclaims
reads differently from one that reports what the sources say.

### Dependency notes

- `web_utils.py` imports `ddgs` and `AsyncTavilyClient` at module scope, and
  `agents.py` imports all three provider classes. Those libraries are installed
  only so the imports resolve; the search layer is mocked and the OpenAI path
  is the one that runs.
- `agents.py` imports `create_agent` from `langchain.agents`, the **langchain
  1.x** API, so the 1.x line is pinned. (Several other agents here pin the 0.3
  line for the opposite reason — check which API a project uses before pinning.)
- The synthesizer reads `SUMMARIZATION_MODEL`, whose default is a Gemini name.
  On the OpenAI path that would be sent to OpenAI verbatim, so the manifest
  pins it to an OpenAI model.
- `get_llm` appends `/v1` to `OPENAI_BASE_URL` itself, so the manifest sets the
  bare host.
- The nodes are async-only; the worker uses `ainvoke`.

## Input and output

Plain text in — the research topic. `output` is the final report; `raw_output`
adds the plan, the key findings, and the number of sources.

## Run it

```bash
python -m agentbench verify deep-research
python -m agentbench certify deep-research   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Four fixture sources; the report is not real research.
- Each stage validates its output and ends the run early if it is empty, so a
  short or refusing run is expected behaviour, not a crash.
