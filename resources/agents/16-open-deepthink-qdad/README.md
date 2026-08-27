# open-deepthink QDAD (AgentBench adaptation)

AgentBench adaptation of the QDAD graph from
[iblameandrew/open-deepthink](https://github.com/iblameandrew/open-deepthink),
pinned at `b440af1`, MIT.

QDAD treats language as a latent. It derives a noun/verb basis from the prompt,
builds an N x N grid of agents over that basis, adds qualitative "noise",
denoises the grid over several rounds with critic agents, and synthesises a
final answer.

Upstream also ships a QNN pipeline, an evolutionary distillation graph, and a
Flask UI. The benchmark selects `qdad`, the graph that reaches nothing but the
model.

## What was adapted

Almost nothing needed replacing, which is unusual and worth stating: the five
nodes reason over a language grid and touch no search, no retrieval, no vector
store, and no filesystem. `benchmark_mocks` therefore substitutes nothing and
only installs the egress guard, so that a future revision reaching for the
network fails loudly rather than silently.

| Concern | Upstream | Here |
| --- | --- | --- |
| External services | none on this graph | none |
| Entry point | Flask app / `deepthink.cli` | persistent JSONL worker |
| Grid size and rounds | user-selected in the UI | pinned small, see below |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

The FAISS retrieval layer and the code sandbox live in `app.py` and
`deepthink/utils.py`, outside the selected graph's import path — only
`deepthink/__main__.py` reaches them, and the worker never imports it.

### Bounding one Case

The noise and denoise nodes fan out over every grid cell in parallel, so model
calls grow with N squared times the denoising steps. The benchmark pins a 2x2
grid and one denoising step, which is ten model calls; `QDAD_GRID_SIZE` and
`QDAD_DENOISING_STEPS` raise it.

## Input and output

The official Case provider emits text and the graph's native input is a prompt,
so the mapping is close to the identity.

```json
{"prompt": "...", "solution": {...}, "build_prompt": "..."}
```

`raw_output` adds the derived noun and verb bases, the grid size, and the
denoising step count — enough to check that the exploration actually varied.

## Run it

```bash
python -m agentbench verify open-deepthink-qdad
python -m agentbench certify open-deepthink-qdad   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- The Agent has no tools and no retrieval; it reasons only from the prompt.
  Output is ideation, not sourced fact.
- The benchmark grid is deliberately small, so breadth is bounded.
