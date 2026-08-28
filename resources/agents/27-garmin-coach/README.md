# garmin-coach (AgentBench adaptation)

AgentBench adaptation of
[leonzzz435/garmin-ai-coach](https://github.com/leonzzz435/garmin-ai-coach),
pinned at `54a6494`.

Three summarisers feed three experts (metrics, physiology, activity); an
orchestrator routes; synthesis, formatting, season planning and weekly planning
follow.

## What was adapted

Nothing upstream is substituted. The workflow reads its data from graph state,
so the Garmin client is never reached on this path; `benchmark_mocks` installs
the egress guard only.

| Concern | Upstream | Here |
| --- | --- | --- |
| Athlete data | Garmin Connect, athlete's own account | one fixture four-week block |
| Model roles | `gpt-5` / `gpt-5-search` (STANDARD) | `AI_MODE=cost_effective`, plain Anthropic |
| Entry point | CLI | persistent JSONL worker |
| Plotting / HITL | enabled | both off |

### Why `cost_effective`, and why not the analysis workflow

The STANDARD and PRO modes assign `gpt-5-search` / `gpt-5.2-pro-search` to the
expert roles, which attach a server-side `{"type": "web_search"}` tool on the
Responses API. That needs real OpenAI egress the benchmark does not have.
`cost_effective` assigns a plain Anthropic model to every role, captured by the
`anthropic-messages` plugin.

More importantly, the graph selected is
`create_integrated_analysis_and_planning_workflow`, **not**
`create_analysis_workflow`. The latter keeps unconditional edges from
`master_orchestrator` back to the three experts while the orchestrator also
routes with `Command(goto=...)`, so every orchestrator turn re-fans out and the
run never terminates — it hit the recursion limit at 40 steps with 41 captured
model calls. Its no-questions branch also routes to `season_planner`, a node
that workflow does not contain. The integrated workflow is upstream's corrected
version; its own comment reads "Master orchestrator uses ONLY `Command(goto=...)`
for dynamic routing / NO unconditional edges from orchestrator".

### The fixture athlete

Four weeks of load, six days of metrics, four sessions, physiology markers, and
an A-race five weeks out. The block contains a real coaching decision rather
than a uniformly good or bad history: load ramps steeply in week three, resting
heart rate rises and HRV falls across the same week, sleep drops, the athlete
reports one-sided calf soreness, and the ACWR sits at 1.42. An answer that says
"keep ramping" is distinguishable from one that reads the signals.

### Licence

Upstream declares MIT in its README (badge plus a `[LICENSE](LICENSE)` link)
but ships no LICENSE file and no licence field in `pyproject.toml`. `NOTICE`
records the declaration rather than inventing a licence text.

### Details worth knowing

- The nodes are async-only — `compiled.invoke()` raises; the worker uses
  `ainvoke`.
- The workflow compiles with a `MemorySaver`, so each request needs its own
  `thread_id`.
- `core/config.py` rejects any `OPENAI_API_KEY` not starting with `sk-` and any
  `ANTHROPIC_API_KEY` not starting with `sk-ant-`. This is why the harness now
  shapes its stand-in credentials to match the family they replace; before
  that, the agent failed at configuration time without making a single call.

## Input and output

Plain text in — the athlete's question, which becomes `analysis_context`.
`output` is the formatted analysis; `raw_output` also carries the synthesis and
each expert summary.

## Run it

```bash
python -m agentbench verify garmin-coach
python -m agentbench certify garmin-coach   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- **Not medical advice.** The athlete and every reading are fixtures.
- Plotting is disabled and there is no human in the loop.
