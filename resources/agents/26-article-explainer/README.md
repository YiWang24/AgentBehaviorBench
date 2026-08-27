# article-explainer (AgentBench adaptation)

AgentBench adaptation of
[duartecaldascardoso/article-explainer](https://github.com/duartecaldascardoso/article-explainer),
pinned at `2cf067d`, MIT.

Five ReAct agents — explainer, summariser, developer, analogy creator,
vulnerability expert — wired as a `langgraph-swarm`. Each holds handoff tools
for the other four; the explainer starts.

## Why this one is worth having

It is the first **swarm** in the benchmark. The other multi-agent adaptations
here route through a supervisor that decides and delegates; a swarm has no
centre — whichever agent holds the conversation decides whether to answer or
hand it on. The failure modes differ, so the behaviour worth testing differs:
handing off when it should not, or bouncing control between two agents.

`raw_output` records the `active_agent` at the end plus the full transcript,
where each `transfer_to_*` message marks a handoff, so both are checkable.

## What was adapted

Nothing upstream is substituted. The five agents reach nothing but the model —
no search, no retrieval, no filesystem on the graph path — so `benchmark_mocks`
installs the egress guard only.

| Concern | Upstream | Here |
| --- | --- | --- |
| External services | none on this graph | none |
| Entry point | Streamlit page with a PDF viewer | persistent JSONL worker |
| Content loading | `PyPDFLoader` over an uploaded PDF | the Case's text is the article |

`explainer/graph.py` already exposes the compiled swarm as a module-level
`app`, so the wrapper only installs the guard before importing it.

### The Ollama fallback

`get_chat_model()` returns a `ChatOllama` pointed at `localhost:11434` when
`OPENAI_API_KEY` is unset. The benchmark always injects the key, so the OpenAI
path is taken — and if a future revision took the fallback, the egress guard
fails loudly instead of hanging against a port nothing is listening on.
`langchain-ollama` is still installed because `config.py` imports `ChatOllama`
at module scope.

## Input and output

Plain text in — the article, or a question about it. `output` is the last
non-empty message.

## Run it

```bash
python -m agentbench verify article-explainer
python -m agentbench certify article-explainer   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- No retrieval: everything must come from the text provided.
- Code examples are illustrative and never executed.
