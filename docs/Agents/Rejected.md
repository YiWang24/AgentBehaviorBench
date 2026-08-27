# Rejected Agent Candidates

Candidates reviewed against the admission boundary in
[Reference.md](./Reference.md) §2 (R1-R10) and not accepted. A rejection is a
reviewed outcome, not a skipped item: it records what was checked, at which
revision, and what would have to change.

Rejected candidates are **not** added to `resources/registry.toml`, not even as
disabled entries.

Candidates are drawn from the AgentRadar catalog. That catalog is a snapshot, so
a repository may have moved on since it was scanned; where that is the reason
for rejection it is stated explicitly, because a pinned earlier revision may
still qualify.

---

## bytedance/deer-flow

```text
Agent rejected: deer-flow
Requirement: R3
Reason code: INVALID_ENTRYPOINT
Reason: The repository no longer defines an agent graph. At the reviewed
  revision the backend is a chat gateway that hosts and proxies LangGraph
  threads rather than implementing one: it depends on `langgraph-sdk` (the
  client SDK) and imports `langgraph` only for checkpoint plumbing and types.
  There is no module-level compiled graph and no zero-argument factory that
  returns one, so no stable `file.py:attribute` entry point exists.
Evidence:
  - Reviewed revision: bdd68469c156877daa3facb547314b8391cabf73
  - `backend/pyproject.toml` declares `langgraph-sdk>=0.1.51`; plain `langgraph`
    is not a declared dependency.
  - `grep -rn "StateGraph(" backend --include='*.py'` outside `tests/` and
    `scripts/` matches only
    `backend/packages/harness/deerflow/runtime/checkpoint_state.py`, a generic
    checkpoint-state helper.
  - No `build_graph`, `_build_base_graph`, or `get_graph` definition exists
    outside tests.
  - Remaining `langgraph` imports are `checkpoint.base`, `checkpoint.memory`,
    `types.Checkpointer`, `types.Command`, and `channels.binop` — gateway
    plumbing, not graph construction.
  - The AgentRadar catalog records `29+?` nodes and 73 dependencies for this
    repository. That snapshot predates the restructure; the backend now declares
    19 dependencies and contains no agent graph.
Reconsider when: a revision is pinned in which the research graph is defined in
  this repository and exposed as a stable `file.py:attribute`, or when AgentBench
  gains a reviewed adapter for agents that execute behind an HTTP gateway
  (`UNSUPPORTED_EXECUTION_MODE` would otherwise also apply).
```

---

## guy-hartstein/company-research-agent

```text
Agent rejected: company-research-agent
Requirement: R1 (model interception boundary)
Reason code: UNSUPPORTED_MODEL_PROTOCOL
Reason: The pipeline requires two model providers. The four research analysts
  use OpenAI, but the Briefing node constructs ChatGoogleGenerativeAI against
  Google's native Generative Language API and raises without GEMINI_API_KEY —
  there is no fallback. The Model Interceptor registers protocol plugins for
  openai-chat, openai-responses, and anthropic-messages only, and the OpenRouter
  target maps endpoints for those three. Gemini traffic can therefore be neither
  decoded for Trace nor forwarded, so a manifest for this Agent could not
  honestly declare its model traffic.
Evidence:
  - Reviewed revision: 52c904c8169f0a36ee8c1de46d5745aee731a0b4
  - `backend/nodes/briefing.py:29` raises
    `ValueError("GEMINI_API_KEY environment variable is not set")`.
  - `backend/nodes/briefing.py:32` builds `ChatGoogleGenerativeAI(model="gemini-2.5-flash")`.
  - `services/model-interceptor/pyproject.toml` registers exactly three protocol
    plugins under `defuzex.model_interceptor.protocols`.
  - `OpenRouterTarget._ENDPOINTS` has no Gemini entry and raises
    `TargetRoutingError` for any unlisted protocol.
  - The rest of the adaptation is sound: the graph builds, and a single
    substitution of `AsyncTavilyClient` in
    `backend/nodes/researchers/base.py` covers search, crawl, and extract across
    all ten nodes. The work is preserved in the AgentFactory queue.
Reconsider when: a reviewed `google-genai` protocol plugin and a matching target
  endpoint mapping exist in the Model Interceptor. Rewriting the Briefing node
  to call OpenAI is explicitly not an acceptable workaround — it would change
  which model produces the briefings, which is the behaviour under test.
```

---

## License gate

R8 requires a recorded, redistributable license. Vendoring a snapshot into this
repository is redistribution, so a candidate with no license — or one whose
license forbids commercial use or imposes copyleft on the benchmark — cannot be
admitted, however good the adaptation would be.

```text
Agent rejected: stocks-insights-ai-agent
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: Licensed under Creative Commons Attribution-NonCommercial-ShareAlike
  4.0. The NonCommercial term and the ShareAlike obligation both make it
  unsuitable to vendor into this repository.
Evidence:
  - Reviewed revision: 375efb4
  - LICENSE.md declares CC BY-NC-SA 4.0.
Reconsider when: upstream relicenses under a permissive software license. CC
  licenses are not intended for software and no adaptation can work around the
  NonCommercial term.
```

```text
Agent rejected: FinchainAgent, Paper-Agent, MultiAgenticRAG
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: No license file of any kind, so the default is all rights reserved and
  the source may not be redistributed.
Evidence:
  - Reviewed revisions: FinchainAgent f6f04ed, Paper-Agent c68778f,
    MultiAgenticRAG 05cc844.
  - No file matching `licen[cs]e*` in any of the three repositories.
  - Each is otherwise plausible: FinchainAgent compiles a workflow in main.py,
    Paper-Agent and MultiAgenticRAG both build module-level graphs.
Reconsider when: upstream adds a permissive license.
```
