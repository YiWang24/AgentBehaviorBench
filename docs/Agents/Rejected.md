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
