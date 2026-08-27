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

A missing `LICENSE` file is not decisive on its own — a licence declared in the
README or in `pyproject.toml` is still an explicit grant, and several
candidates were nearly rejected on that mistake. The repositories below carry
no licence statement anywhere: no licence file, no README declaration, no
package metadata. The default is then all rights reserved and the source may
not be redistributed.

```text
Agent rejected: no licence declared anywhere
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: No licence file, no README licence statement, and no licence field in
  package metadata.
Evidence (repository @ reviewed revision):
  - ZhangJinHaHaHa/FinchainAgent @ f6f04ed
  - Tswoen/Paper-Agent @ c68778f
  - nicoladisabato/MultiAgenticRAG @ 05cc844
  - kaymen99/Upwork-AI-jobs-applier @ 074dc0d
  - kaymen99/sales-outreach-automation-langgraph @ 2e2761c
  - kaymen99/local-rag-researcher-deepseek @ 98e8382
  - kaymen99/langgraph-email-automation @ 9ea0f54
  - ro-anderson/multi-agent-rag-customer-support @ 86b17b6
  - Nachoeigu/agentic-customer-service-medical-clinic @ b76b8e7
  - KRATSZ/LabScript-AI @ 747db2c
  - seanlxh/Air-Lingjing @ d23060c
  - zamalali/DeepGit @ 940c14e
  - Lyra-stellAI/BYO-LLM-WIKI @ 0316fb7
  - nuglifeleoji/Options-Analytics-Agent @ 9de22c3
  - icey1287/SuperMew @ f997821
  - NanGePlus/LangGraphChatBot @ 30621c9
  - Xeron2000/openOii @ 8fb0f70
  - liangdabiao/langgraph_multi-agent-rag-customer-support @ a30f964
  - hwchase17/langchain-streamlit-template @ 3c676a6
  - jank/curiosity @ 41c9195
  - didilili/deepsearch-agents @ d0f6eed
  - kaymen99/personal-ai-assistant @ c96fefb
  - GU-Cryptography/anykb @ aa7c02e
  - hwchase17/autoresearch-agents @ 552fd6a
  - bamboo-moon/zhisaotong-Agent @ 92569e6
  - Neon549/Alpha_stock @ 1abf660
  - shodan1q/zeroapp @ e081199
  Checked in each case: `licen[cs]e*` in the repository root, a licence
  statement in README.md, and `project.license` / licence classifiers in
  pyproject.toml.
Reconsider when: upstream adds a permissive licence. Several of these are
  otherwise plausible adaptations.
```

---

## Copyleft

```text
Agent rejected: GPL/AGPL-licensed candidates
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: Both are GPL. Vendoring a snapshot into this repository is
  redistribution, and the copyleft terms would extend to the benchmark, which
  is MIT. This is a licensing-policy call rather than a technical one and a
  maintainer may overrule it.
Evidence:
  - tevslin/meeting-reporter @ 525f6bb, XD-MHLOO/Osintgraph @ c9bbcab; both
    ship a GNU General Public License.
  - psyray/oasis @ 60388ad and OS3Lab/agent4kdump @ db08e0a ship a GNU
    General Public License.
  - guangshu100/BidMaster-Pro @ 117ca62 ships a GNU Affero General
    Public License.
  - KodyKendall/LlamaBot @ 884cd2a ships a GNU Affero General Public
    License. It also requires a Docker daemon (R2).
  - test-zeus-ai/testzeus-hercules @ fa2b469 ships a GNU Affero General Public
    License, whose network clause is stricter still. It also has no graph (R3).
  - meeting-reporter additionally has no module-level graph (R3).
Reconsider when: a maintainer decides copyleft vendoring is acceptable, or the
  agents are run from an unvendored checkout rather than copied into
  `resources/agents/`.
```

---

## Already reviewed under another name

```text
Agent rejected: agruai/company-research-agent
Requirement: R1 (model interception boundary)
Reason code: UNSUPPORTED_MODEL_PROTOCOL
Reason: A fork of guy-hartstein/company-research-agent at the same revision
  (52c904c). The Gemini dependency described above applies unchanged.
Reconsider when: the same condition as the upstream entry.
```

---

## No stable entry point

```text
Agent rejected: rotemweiss57/gpt-newspaper
Requirement: R3
Reason code: INVALID_ENTRYPOINT
Reason: The workflow is compiled inside a function with no module-level
  attribute and no langgraph.json, so there is no stable `file.py:attribute`
  entry point.
Evidence:
  - Reviewed revision: b86aff2; `workflow.compile()` appears only inside
    `backend/langgraph_agent.py`.
Reconsider when: upstream exposes the compiled graph, or a maintainer accepts a
  benchmark-side factory that reaches into the private builder.
```

---

## Broken upstream

```text
Agent rejected: bcefghj/smart-cs-multi-agent
Requirement: R10
Reason code: VALIDATION_FAILED
Reason: The graph cannot complete a request as shipped. `ComplianceChecker`
  always writes a dict into `sub_results`, and the supervisor's `synthesize`
  node joins every value in that mapping without a type guard, so any run that
  actually produces an answer ends in
  `TypeError: sequence item 1: expected str instance, dict found`.
  This is unconditional and has nothing to do with model output: the offending
  value is built from the compliance verdict, not from a reply.
Evidence:
  - Reviewed revision: e045f0256d42db3c800662f60bd957d9c78374a4
  - `agents/compliance_checker.py:209` always adds
    `sub_results["compliance"] = {"passed": ..., "risk_level": ..., "violations": ...}`.
  - `agents/supervisor.py:113-117` builds the final reply with
    `"\n\n".join(result_parts)` over `sub_results.values()` with no isinstance
    check — while `compliance_checker.py:192` guards the same mapping with
    `isinstance(result, str)`, so the mismatch is visible within the repository.
  - The adaptation itself worked: the graph builds, all five nodes run, and a
    probe reached `synthesize` after five model calls with retrieval served from
    a local corpus. Only the upstream defect stops it.
Reconsider when: upstream type-guards the join in `synthesize_response`, or
  stops writing a non-string into `sub_results`. Patching it here would mean
  fixing the agent's own logic rather than adapting a benchmark boundary.
```

```text
Agent rejected: Y-Research-SBU/TimeSeriesScientist
Requirement: R10
Reason code: VALIDATION_FAILED
Reason: The graph cannot get past its first node. `_preprocess_node` calls
  `self.preprocess_agent.run(state["validation_data"])` with no output
  directory; `run` defaults `output_dir` to `None` and passes it straight to
  `process`, which reaches `Path(output_dir)` unconditionally and raises
  `TypeError: argument should be a str or an os.PathLike object ... not
  'NoneType'`. Visualisation is not gated by configuration, so there is no
  setting that avoids the call, and `_preprocess_node` is the only route into
  that agent.
Evidence:
  - Reviewed revision: 41b3963
  - `time_series_agent/graph/agent_graph.py:52` — the one-argument call.
  - `time_series_agent/agents/preprocess_agent.py:186` — `output_dir: str = None`.
  - `time_series_agent/agents/preprocess_agent.py:650` and `:966` —
    `Path(output_dir)` with no guard.
  - The adaptation itself was sound: the image builds with `libgomp1` for
    LightGBM and XGBoost, langchain pinned to the 0.3 line the project targets,
    all five nodes compile, and a deterministic 240-point series slices cleanly
    into 168 validation and 24 test rows. Only the upstream defect stops it.
Reconsider when: upstream passes an output directory from the node, or guards
  the visualisation call. Supplying one here would mean editing the agent
  rather than adapting a benchmark boundary.
```

---

## Non-redistributable licence

R8 requires a licence under which vendoring a snapshot into this MIT repository
is permitted. A source-available licence that forbids offering the software as
a service is not redistributable on those terms.

```text
Agent rejected: EYamanS/texel-studio
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: Ships a custom "Texel Studio License" — source-available, permitting
  self-hosting and modification but explicitly prohibiting offering the
  software or a substantial derivative as a hosted service. That restriction is
  incompatible with vendoring it into an MIT-licensed benchmark. Separately, the
  agent generates images (sprites, tilesets) through Gemini image models rather
  than producing text, so the offline text gate could not exercise it even if
  the licence allowed (UNSUPPORTED_IO_CONTRACT / R1 model protocol also apply).
Evidence:
  - Reviewed revision: 8af1558
  - LICENSE §3 "SERVICE RESTRICTION": "You may NOT offer this Software, or any
    substantial derivative of it, as [a service]".
  - agent.py builds a `create_react_agent` whose tools call Gemini image
    generation; there is no text-only path.
Reconsider when: upstream relicenses permissively, and AgentBench gains an
  image-output contract and a Gemini interception route.
```

---

## Privileged execution

```text
Agent rejected: Negai-ai/AgentClaw, PurpleAILAB/Decepticon, EuniAI/Prometheus,
  lingxi-agent/Lingxi
Requirement: R2
Reason code: UNSUPPORTED_EXECUTION_MODE
Reason: Each drives Docker from inside the agent — a mounted socket, a
  privileged container, or `docker.from_env()` — to spin up the sandbox it
  works in. The benchmark runtime gives an agent no Docker socket, no
  privileged mode, and a read-only root, and relaxing that would remove the
  isolation the benchmark depends on.
Evidence:
  - Reviewed revisions: AgentClaw 034efd1, Decepticon 31e1c8e,
    Prometheus acb8360, Lingxi 1f2e5dc.
  - The first three match `docker\.sock|--privileged|docker\.from_env` in
    non-test Python source.
  - Lingxi declares `docker` as a dependency and builds its workspace through
    `swerex.deployment.docker.DockerDeployment`, pulling a per-instance
    SWE-bench image (`src/agent/swerex_utils.py:70`) and running commands with
    `docker_container.exec_run` (`tool_set/sepl_tools.py:368`). It also needs
    embeddings and Chroma, neither of which is the blocker here.
  - Prometheus is additionally GPL, which is disqualifying for a vendored
    snapshot on its own.
Reconsider when: AgentBench gains a reviewed nested-sandbox runtime, or the
  agents accept an externally supplied workspace instead of creating their own
  container.
```

---

## Further licence rejections

```text
Agent rejected: datawhalechina/vibe-blog
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: Creative Commons non-commercial licence; see the licence gate above.
Evidence: reviewed revision 7fc7970.
```

```text
Agent rejected: wshobson/financial-chat, Westlake-AGI-Lab/AppAgentX
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: No licence file, no README declaration, and no package metadata.
Evidence: reviewed revisions financial-chat 55a1229, AppAgentX d0fcaeb.
```

```text
Agent rejected: olaxbt/ai-market-maker
Requirement: R8
Reason code: SOURCE_OR_LICENSE_MISSING
Reason: AGPL. Stronger copyleft than the GPL cases above and equally
  disqualifying for a vendored snapshot in an MIT repository. Policy call.
Evidence: reviewed revision dd71150.
```

---

## Privileged execution

R2 requires the agent to run unprivileged in the benchmark container. An agent
that needs a Docker daemon cannot: granting it means handing the agent control
of the host's container runtime, which is a privilege escalation, and no
adaptation removes the need without removing the agent's actual capability.

```text
Agent rejected: agents requiring a Docker daemon
Requirement: R2
Reason code: UNSUPPORTED_EXECUTION_MODE
Reason: The agent builds or runs containers as part of its normal operation,
  which requires a mounted Docker socket or a privileged container.
Evidence (repository @ reviewed revision):
  - xerrors/Yuxi @ edc0cc8
  - beenuar/AiSOC @ 98e8dfc
  - cuga-project/cuga-agent @ e661107
  - zhongyu09/openchatbi @ c8786cb
  - jd-opensource/JoySafeter @ 12234a1
  - louisgthier/decompai @ 0c2398c
  - KodyKendall/LlamaBot @ 884cd2a (also AGPL-3.0, see Copyleft)
  - ai-forever/giga_agent @ 83872f0
  Matched in each case on `docker.sock`, `--privileged`, `docker.from_env`,
  or `containers.run(` outside test and deployment directories.
Reconsider when: the agent gains a mode that performs its work in-process, or
  AgentBench gains a reviewed nested-sandbox runtime.
```

---

## No agent graph

R3 requires a stable `file.py:attribute` entry point that resolves to a
LangGraph graph or a zero-argument factory returning one.

```text
Agent rejected: no compiled graph or graph factory
Requirement: R3
Reason code: INVALID_ENTRYPOINT
Reason: No `StateGraph` construction and no graph factory exists outside tests,
  so there is nothing for the LangGraph adapter to load.
Evidence (repository @ reviewed revision):
  - ShenSeanChen/waku-agent @ 680f64a
  - test-zeus-ai/testzeus-hercules @ fa2b469 (also AGPL-3.0, see Copyleft)
  - EricHong123/B-agent @ 4e449f2 — no `StateGraph` construction anywhere.
  - waseens/deep-search-pro @ 678c55c — no `StateGraph` construction anywhere.
  - Yourdaylight/stock_datasource @ f180446 — a data platform, not an agent.
    `langgraph` appears only as a string in a runtime-selector column
    (`agent_config_service.py`) and in a demo's module-mocking list; no
    `StateGraph` is constructed and no graph factory exists.
  - togethercomputer/open_deep_research @ 66e43b4 — the agent is a custom
    loop in `src/together_open_deep_research.py`, not a LangGraph graph.
    `langgraph` appears only inside `src/libs/utils/agent_factory.py`, which
    optionally constructs a *different* project's researcher as a benchmark
    baseline. No `StateGraph` is constructed anywhere in the repository.
  - stophobia/deerflow2.0-enhanced @ 814bde3 — a deer-flow derivative carrying
    the same restructure: `backend/pyproject.toml` declares `langgraph-sdk`
    but not `langgraph`, and `grep -rn "StateGraph("` matches nothing in the
    repository. `backend/langgraph.json` names graphs that are hosted
    elsewhere. Same reason as bytedance/deer-flow above.
  Checked: `grep -rn "StateGraph(" --include='*.py'` and a search for
  `build_graph` / `get_graph` / `make_graph` definitions outside `tests/`.
Reconsider when: a revision is pinned in which the graph is defined in the
  repository and exposed as a stable `file.py:attribute`.
```

---

## No agent of its own

R4 requires a complete, independently installable project. An agent whose
capabilities are supplied by a client at runtime cannot be exercised in the
container: whatever it is given to do, the benchmark would have invented.

```text
Agent rejected: Yonom/assistant-ui-langgraph-fastapi
Requirement: R4
Reason code: INCOMPLETE_PROJECT
Reason: The backend is a chat-UI template rather than an agent with its own
  capability. Its tool set arrives from the browser through mandatory
  `configurable` keys, and the sole backend tool is an acknowledged stub.
Evidence:
  - Reviewed revision: 269ae8b
  - `backend/app/langgraph/agent.py` requires `config["configurable"]["system"]`
    and `config["configurable"]["frontend_tools"]`; both are supplied by the
    assistant-ui frontend, and `call_model` raises `KeyError` without them.
  - `FrontendTool._run` raises `NodeInterrupt("This is a frontend tool call")`
    by design — those tools execute in the browser, not the container.
  - The only backend tool, `get_stock_price`, is commented "This is a mock
    implementation" and returns the same hardcoded Apple record for every
    argument (`return mock_stock_data["AAPL"]`), so it cannot distinguish one
    request from another.
Reconsider when: the repository grows an agent with backend capability of its
  own, or AgentBench gains a reviewed way to supply a client-side tool set as
  part of a Case.
```
