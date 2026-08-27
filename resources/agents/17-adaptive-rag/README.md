# adaptive-rag (AgentBench adaptation)

AgentBench adaptation of
[dhruvsinghal09/Adaptive-Rag](https://github.com/dhruvsinghal09/Adaptive-Rag),
pinned at `6f6401e`.

The graph routes a question three ways — indexed documents, web search, or
straight to the model — then grades what it retrieved and rewrites the query
when the documents miss.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Embeddings | `OpenAIEmbeddings` | deterministic local vectors |
| Vector store | FAISS, seeded from user uploads | FAISS, seeded from four fixture documents |
| Web search | `TavilySearchResults` | `BenchmarkSearchResults`, fixed results on `benchmark.invalid` |
| Entry point | FastAPI upload + query endpoints | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

Upstream expects a user to upload a document before querying; with no upload
the retriever falls back to a dummy "no documents" record and the graph cannot
demonstrate routing. `benchmark_mocks` therefore seeds the index with four
short documents on distinguishable retrieval topics, so a Case can tell
document routing from web routing.

The ReAct agent in `src/rag/reAct_agent.py` is imported by the package but not
reached by the selected graph.

### Licence

Upstream declares MIT in its README and ships no `LICENSE` file. `NOTICE`
records the declaration rather than inventing a licence text.

### Pinned dependencies

`reAct_agent.py` imports `create_react_agent` and `AgentExecutor` from
`langchain.agents`; both moved in langchain 1.x, so `pyproject.toml` pins the
0.3 line the project targets. Pinning is preferred over editing the vendored
import.

`src/config/prompts.yaml` is loaded by path relative to the installed module,
so it is declared as package data — otherwise the import raises
`FileNotFoundError` after `pip install .`.

## Input and output

The official Case provider emits text, which becomes the question.

```json
{"messages": [{"role": "user", "content": "..."}], "latest_query": "..."}
```

`raw_output` carries the route the classifier chose and the documents it
retrieved, so a judge can check that routing and grounding agree.

## Run it

```bash
python -m agentbench verify adaptive-rag
python -m agentbench certify adaptive-rag   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Embeddings are hashed bags of words, not model output, so ranking quality is
  not representative of production retrieval.
- The corpus is four fixture documents and search results are fixtures. Answers
  are not real research.
