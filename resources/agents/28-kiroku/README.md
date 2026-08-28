# kiroku (AgentBench adaptation)

AgentBench adaptation of [cnunescoelho/kiroku](https://github.com/cnunescoelho/kiroku),
pinned at `4b09df8`, Apache-2.0.

Eleven nodes: research → topic-sentence plan → draft → reflect → revise →
abstract → references → citations, with an author review point between stages.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Literature search | Tavily, expanded via arXiv and PubMed | four fixture sources on `benchmark.invalid` |
| Research tools | Wikipedia, arXiv, PubMed clients | fixture-backed tools with the same names |
| Python REPL | `langchain_experimental` REPL | unchanged; runs inside the sandboxed container |
| Brief | project YAML | one fixture brief; the Case's text becomes the author's instructions |
| Entry point | Gradio web UI | persistent JSONL worker |

### The review points are honoured, not removed

Upstream compiles with `interrupt_before` at each manual-review node — the
human-in-the-loop of a writing tool. The worker resumes each one with an
**empty** instruction, which is upstream's own "accept as written" path:
`TopicSentenceManualReview.run` and its siblings read
`config["configurable"]["instruction"]` and pass straight through when it is
blank, without a model call. Nothing is invented on the author's behalf, and
`raw_output` records `segments_run` and `review_instruction_supplied: ""` so
the shape of the run is visible.

### Three traps

**Replacing a star-imported module means reproducing its namespace.**
`agents/states.py` does `from .search import *`, and upstream's `search.py`
declares no `__all__` — so states.py also inherits the names search.py
imported, including `logging`, which it then calls. Setting `__all__` on the
replacement was "cleaner" and broke the agent with `NameError: name 'logging'`.

**Pin the versions the project declares.** The node methods annotate
`config: dict` rather than `RunnableConfig`. Newer LangGraph reads that
annotation and stops injecting config, so every manual-review node fails with
`run() missing 1 required positional argument: 'config'`. `requirements.txt`
pins `langgraph==0.2.48` and the matching langchain versions; those pins are
used verbatim rather than retyping vendored code.

**`gradio` is stubbed, not installed.** `kiroku_app.py` imports it at module
scope for the UI. The stub raises on *any* attribute access, so if a revision
ever reaches for gradio on the graph path the failure is loud. `IPython` is
imported the same way but is small, so it is installed rather than stubbed.

`nltk.sent_tokenize` downloads the punkt tokenizer on first use; the container
has no egress at run time, so it is cached into the image at build time.

## Input and output

Plain text in — the author's instructions, appended to the fixture brief's
hypothesis. `output` is the finished draft; `raw_output` adds the plan, the
self-critique, the references, and how many segments ran.

## Run it

```bash
python -m agentbench verify kiroku
python -m agentbench certify kiroku   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Four fixture sources; the draft is not a real literature review.
- No human reviewer: every review point is accepted as written.
