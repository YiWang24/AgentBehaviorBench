# AgentBench CLI

This document is the complete usage guide for the AgentBench command-line
interface. The CLI installation entry point is defined in `pyproject.toml`, and
the implementation lives in `agentbench/cli/`.

## 1. Prerequisites

Run commands from the repository root:

```powershell
cd <path-to>\defuzeX_AgentBench
```

AgentBench supports two equivalent invocation forms:

```powershell
python -m agentbench <command> [arguments]
agentbench <command> [arguments]
```

The second form requires this project to be installed in the active Python
environment. Before running a benchmark, make sure that:

- Python 3.10 or later is available.
- `DEFUZEX_API_KEY` is configured in the current terminal environment.
- Docker Desktop is running when the target Agent uses the Docker runtime.
- `OPENROUTER_API_KEY` is configured for intercepted Docker Agents.
- A model is supplied with `--model` or `OPENROUTER_MODEL`.
- Other required environment variables declared by the target Agent's
  `agent.toml` are configured.
- The Agent is registered in `resources/registry.toml`, and its directory,
  `agent.toml`, and requirement file exist.

### One Run at a Time

The DefuzeX SDK enforces a single active Run per host with an operating-system
file lock. A second `run`, `certify`, or `verify` started while another is still
going fails with `RunAlreadyActiveError`, so batch these commands sequentially
rather than in parallel. The lock file is resolved from `XDG_RUNTIME_DIR`, which
is also how a test suite isolates itself from a Run happening on the same machine.

Show root help with:

```powershell
python -m agentbench --help
```

Current subcommands:

| Command | Purpose |
| --- | --- |
| `run` | Run all enabled Agents whose status is `ready`. |
| `view` | Open an existing JSONL result in the local web viewer. |
| `verify` | Check one Agent as far as this host can: a credential-free preflight, then a graded benchmark with local Providers. |
| `certify` | Verify one `adapting` Agent can complete its requested Cases and promote it to `ready`. |

`verify` is the only command that runs without `DEFUZEX_API_KEY`: it supplies its
own Case and Judge Providers instead of calling the DefuzeX Backend. Its first
phase needs no credential and no network at all; only the graded benchmark that
follows needs `DEEPSEEK_API_KEY`, and a host without one stops after preflight
instead of failing. Use `verify` while adapting an Agent, before `certify`.

## 2. Default Command and Compatibility

`run` is the default command. These commands are equivalent:

```powershell
python -m agentbench
python -m agentbench run
```

The old no-subcommand argument form remains supported:

```powershell
python -m agentbench --output results\result.json
```

It is equivalent to:

```powershell
python -m agentbench run --output results\result.json
```

Root-level `-h` or `--help` shows all subcommands and is not rewritten to
`run --help`.

## 3. `run`

### 3.1 Syntax

```text
agentbench run [-h] [--env-file PATH] [--output PATH]
               [--model OPENROUTER_MODEL]
               [--llm-trace {off,terminal}]
               [--llm-trace-max-bytes BYTES]
```

```powershell
python -m agentbench run
python -m agentbench run --model openai/gpt-4.1-mini
python -m agentbench run --output results\result.json
python -m agentbench run --llm-trace terminal
```

### 3.2 Arguments

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `-h`, `--help` | No | - | Show `run` help and exit. |
| `--env-file PATH` | No | Repository `.env` | Load host-only secrets and defaults from another dotenv file. |
| `--output PATH` | No | Do not save | Save a unique append-only JSONL result and start the local viewer. |
| `--model OPENROUTER_MODEL` | No | `OPENROUTER_MODEL` | Force every intercepted Agent request to use this OpenRouter model slug. |
| `--llm-trace {off,terminal}` | No | `off` | Print sanitized model requests and responses captured by the transparent Interceptor. |
| `--llm-trace-max-bytes BYTES` | No | `262144` | Maximum payload bytes displayed for each request or response. |

`PATH` is the naming base for the result file, not the final file name.
AgentBench adds a timestamp and always writes `.jsonl`:

```text
--output results\result.json
-> results\result-20260820-162500.jsonl
```

If a file name collides within the same second, AgentBench appends `-2`, `-3`,
and so on. Existing files are never overwritten. Each event is appended as soon
as it is produced, so data already written before an interruption is preserved.

When `--output` is omitted:

- the benchmark still runs normally;
- no JSONL trace/result artifact is generated;
- the local viewer is not started;
- the terminal still shows each Agent result and the final suite result.

### 3.3 Agent Selection Rules

Default runs select only registrations that satisfy both conditions:

```toml
enabled = true
status = "ready"
```

Enabled Agents that are still `adapting` are excluded from normal batches. The
CLI displays the number of excluded Agents and suggests using
`agentbench certify <agent_id>`.

Registry order determines execution order. Each Agent's `case` field determines
how many independent Cases are run.

### 3.4 Confirmation Prompt

After displaying the selected Agents, the CLI asks:

```text
Continue? [yes/no]:
```

Accepted inputs:

| Result | Inputs |
| --- | --- |
| Continue | `yes`, `y`, `confirm`, `c` |
| Cancel | `no`, `n`, `cancel`, or an empty response |

Cancellation is not a benchmark failure and exits with code `0`.

### 3.5 Result Viewer Lifecycle

`run` starts the viewer before the benchmark only when `--output` is provided.
The terminal prints the suite URL, and after each Agent completes it also prints
a direct link with `#agent=<agent_id>`.

You can open the URL while the benchmark is running. The viewer does not refresh
automatically by default. Use the Refresh button to load the latest events
without interrupting dropdowns or the current selection.

After the run finishes, the CLI keeps the viewer alive and asks:

```text
Viewer action? [r rerun/q quit]:
```

| Action | Inputs | Behavior |
| --- | --- | --- |
| Rerun | `r`, `rerun`, `retry`, `again` | Stop the current viewer, create a new suite and result file, and run again. |
| Quit | `q`, `quit`, `exit`, or an empty response | Stop the viewer and return the benchmark exit code. |

`Ctrl+C` or end-of-input also stops the viewer.

## 4. `verify`

### 4.1 What It Answers

`verify` runs in one direction and stops at the first thing that is missing. It
never changes the Registry, and it never reads `DEFUZEX_API_KEY`.

| Phase | Question | Needs | Model replies | Egress | If it fails |
| --- | --- | --- | --- | --- | --- |
| 1. Preflight | Does this Agent run, and is its model traffic observable? | Docker only | Synthesized in the interceptor | Blocked | `FAIL` (exit `1`) |
| 2. Provider check | Can this host grade the Agent at all? | `DEEPSEEK_API_KEY` | - | - | `PARTIAL` (exit `0`) |
| 3. Benchmark | Does this Agent behave as its requirement says? | A live model | Real DeepSeek API | Open | `FAIL` (exit `1`) |

The ordering is the point. Preflight needs no credential and starts the Agent's
container itself, invoking the adapter directly rather than through an SDK Run —
so an Agent stays checkable on a host where nothing else is configured. Only once
the Agent has proven itself is the host asked whether it can grade it, and a host
that cannot is not an Agent that failed.

The benchmark phase then runs **the same flow as `certify`** — the Registry's
Case count, a real model, an archived result log — with local Case and Judge
Providers in place of the official services. Supplying both Provider ports is
what selects the SDK's local mode, in which the SDK builds no Backend client at
all. Everything else about the Run stays the SDK's: the same `create_run`, the
same strict `get_input`/`submit` handshake, the same `TestReport`.

The Case is generated from the Agent's requirement — its production scenario,
the behaviors to test, and the prohibited ones — so the quality of a graded Run
is bounded by how specific that file is. A requirement written from a template
produces generic Cases.

Preflight always sends `--probes` probes regardless of the Agent's `case` field,
because it checks startup rather than coverage. The benchmark honors the declared
count, the same way `run` and `certify` do.

Because the two phases make opposite guarantees about the network, the Agent's
container is started twice rather than shared.

### 4.2 Syntax

```text
agentbench verify [-h] [--env-file PATH] [--input TEXT] [--probes N]
                  [--inputs N] [--preflight-only] [--model MODEL]
                  [--provider-model MODEL] [--output PATH] [--json]
                  [--llm-trace {off,terminal}]
                  [--llm-trace-max-bytes BYTES] agent_id
```

```powershell
python -m agentbench verify langgraph-customer-support-agent
python -m agentbench verify swe-agent --preflight-only --probes 3
python -m agentbench verify langgraph-chat-agent --inputs 5
python -m agentbench verify swe-agent --model deepseek-reasoner --llm-trace terminal
```

### 4.3 Arguments

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `agent_id` | Yes | - | Registered Agent ID. Disabled Agents and any `status` are accepted. |
| `--env-file PATH` | No | Repository `.env` | Load host defaults from another dotenv file. |
| `--input TEXT` | No | Short generic prompt | Preflight probe text, or `@PATH` to read it from a file. |
| `--probes N` | No | `1` | Preflight probes to send. |
| `--inputs N` | No | `3` | Inputs to generate for the graded benchmark. |
| `--preflight-only` | No | Run all phases | Stop after preflight. Needs no credential. |
| `--model MODEL` | No | `DEEPSEEK_MODEL` | Model the Agent talks to during the benchmark. Preflight always answers from the interceptor. |
| `--provider-model MODEL` | No | `DEEPSEEK_MODEL` | Model that writes the Case and grades the Run. Independent of `--model`. |
| `--output PATH` | No | `results/verify-<agent_id>.jsonl` | Where to write the benchmark result log. Preflight writes no log. |
| `--json` | No | Human report | Print one JSON summary and nothing else. |
| `--llm-trace {off,terminal}` | No | `off` | Also dump every captured payload. Debugging only. |
| `--llm-trace-max-bytes BYTES` | No | `262144` | Maximum captured bytes per request or response. |
| `-h`, `--help` | No | - | Show `verify` help and exit. |

`--preflight-only` is the check to repeat while adapting an Agent: it is the
cheapest phase and answers the only question that matters before the Agent runs
at all.

### 4.4 Agent Requirements

| Condition | Behavior |
| --- | --- |
| `runtime.type = "docker"` and an `[llm_interception]` section | Verification runs. |
| Any other runtime type | Refuse and exit `2`; no interceptor can observe an in-process Agent. |
| No `[llm_interception]` section | Refuse and exit `2`; model calls could be neither captured nor served offline. |
| Not registered | Refuse and exit `2`. |

Secrets declared in `runtime.secret_env_keys` do not need real values. Missing
ones are replaced with deterministic placeholders — shaped like the credential
they replace, so an Agent that validates its key still starts — and the
substituted names are printed, so a stub never passes silently.

### 4.5 Verdict

| Verdict | Exit | Means |
| --- | --- | --- |
| `PASS` | `0` | Every phase that ran held. |
| `PARTIAL` | `0` | Preflight held; this host could not grade the Agent. |
| `FAIL` | `1` | Preflight or the graded Run failed. |
| `ERROR` | `2` | The caller pointed `verify` at something it cannot answer for. |

`PARTIAL` shares an exit code with `PASS` on purpose: a missing provider key is a
gap in the host's own setup, not a defect in the Agent, and a CI job without a
credential must not go red for it. The report still names what was missing.

Preflight passes when the image builds, the container starts, every probe returns
non-empty output, and at least one complete `llm_request`/`llm_response` pair is
captured. It never grades quality — the replies come from a local mock, so the
Agent's wording carries no signal. An Agent whose reply is poor still passes
preflight; one that returns nothing does not.

The benchmark's verdict is the Judge's. Every Case must pass: an Agent that
failed its first Case and passed its second has not passed. The SDK's own status
is reported separately, as `judge:` in the report and
`benchmark.sdk_judge_status` in the JSON, because the two answer different
questions — the Judge grades the Run, while the verdict also required preflight
to have held first.

### 4.6 Report Layout

One column of stages, split by the three questions the run asks in order, then
the model traffic, the judgment, and the verdict. These are the same stage lines
`certify` prints; on a terminal the running stage is a self-erasing live line.

```text
verify · langgraph-customer-support-agent
       SDK local providers · no DefuzeX credentials · registry untouched

+ PREFLIGHT ------------------------------------------------------------+
  synthesized model replies · egress blocked · no credentials
  Starting Agent... OK | ContainerAgentAdapter | 2 routes
  Probing Agent... OK | 1/1 answered
  Capturing model traffic... OK | 2 request/response pairs

+ PROVIDER CHECK -------------------------------------------------------+
  Checking local Case and Judge Providers... OK | judged by deepseek-chat
  Checking the Agent's model target... OK | deepseek-chat

+ BENCHMARK ------------------------------------------------------------+
  Generating Case with local Provider... OK | run=run_d9075725a90b41c
  Running Agent inputs... OK | Judge: pass

     01  ▸ Reply with a short confirmation that you received thi…
         ◂ Tool: list_available_functions                  200 · 1.4ms

  ✓  step_1          Answered within its declared scope.

  PASS   1/1 cases · 2 model request/response pairs captured · judge: pass
         log  results/verify-langgraph-customer-support-agent-20260828.jsonl
```

A run that stopped early prints only the sections it reached and leads with the
reason. Call lists longer than ten are elided in the middle. Note that
`captured_pairs` counts both phases, so a graded run includes its preflight
probes.

`--llm-trace terminal` adds a dump of every captured payload on top of the
report. It is a debugging aid, not a verbosity level: an Agent that resends a
long system prompt each turn produces hundreds of extra lines. Each printed
payload is capped, but the capture itself is not — lowering
`--llm-trace-max-bytes` far enough truncates request bodies mid-JSON, and the
previews and result log degrade with it.

### 4.7 Machine-Readable Output

`--json` prints one document and suppresses every other line, grouped by the
phase each fact came from, so how far the run got is readable without inferring
it from nulls:

```json
{
  "command": "verify",
  "agent_id": "langgraph-customer-support-agent",
  "verdict": "pass",
  "preflight": {"probes_sent": 1, "probes_answered": 1},
  "providers": {
    "state": "ready",
    "reason": null,
    "provider_model": "deepseek-chat",
    "agent_model": "deepseek-chat"
  },
  "benchmark": {
    "ran": true,
    "cases": {"completed": 1, "requested": 1},
    "sdk_judge_status": "pass",
    "summary": "Answered every prompt within its declared scope.",
    "issues": [],
    "step_results": [{"step_id": "step_1", "passed": true, "reason": "…"}]
  },
  "model_calls": {"captured_pairs": 2, "calls": [{"number": 1, "…": "…"}]},
  "substituted_secrets": [],
  "result_log": "results/verify-langgraph-customer-support-agent-20260828.jsonl",
  "reason": null
}
```

`providers.state` is `ready`, `unavailable`, or `skipped` — `unavailable` carries
its reason, `skipped` means `--preflight-only`. `benchmark.ran` is `false` in
both cases, and `result_log` is `null`, because only a graded Run is archived.

### 4.8 Model Notes

Neither phase's model source is selectable: preflight is always offline, which is
what makes it free and hermetic, and the benchmark always uses a real provider,
because grading synthesized replies would say nothing about the Agent.

That has one consequence worth knowing. An Agent that cannot cope with the mock's
constant replies — a graph that routes on reply content, or a framework that
rejects a synthesized tool call — fails preflight and never reaches the
benchmark, even though it would work against a live model. Preflight is a gate:
for such an Agent the fix is on the Agent's side, or in the `[llm_interception]`
routes describing a shape the mock can satisfy.

DeepSeek serves only the OpenAI **chat** wire format. An Agent whose manifest
routes `openai-responses` or `anthropic-messages` traffic cannot be graded
against it, and an Agent requesting JSON-schema `response_format` currently gets
`400 This response_format type is unavailable now`. Those are provider limits,
not adapter defects: `--preflight-only` still verifies such an Agent.

## 5. `certify`

### 5.1 Syntax

```text
agentbench certify [-h] [--env-file PATH] [--output PATH]
                   [--model OPENROUTER_MODEL]
                   [--llm-trace {off,terminal}]
                   [--llm-trace-max-bytes BYTES] agent_id
```

Most common invocation:

```powershell
python -m agentbench certify swe-agent
```

### 5.2 Arguments

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `agent_id` | Yes | - | Stable Agent ID from `resources/registry.toml`. |
| `--env-file PATH` | No | Repository `.env` | Load host-only secrets and defaults from another dotenv file. |
| `--output PATH` | No | `results\certify-<agent_id>.jsonl` | Custom naming base for the certification result. |
| `--model OPENROUTER_MODEL` | No | `OPENROUTER_MODEL` | Force intercepted calls to use this OpenRouter model slug. |
| `--llm-trace {off,terminal}` | No | `off` | Print sanitized intercepted model traffic during certification. |
| `--llm-trace-max-bytes BYTES` | No | `262144` | Maximum displayed bytes per model request or response. |
| `-h`, `--help` | No | - | Show `certify` help and exit. |

Unlike normal `run`, `certify` always saves a unique JSONL result whether or not
`--output` is passed. Default example:

```text
results\certify-swe-agent-20260820-162500.jsonl
```

Custom naming base:

```powershell
python -m agentbench certify swe-agent `
  --output results\manual-swe-certification.json
```

### 5.3 Allowed Registry States

`certify` operates on one specified Agent only and does not run other Agents.

| Current state | Behavior |
| --- | --- |
| `adapting` | Run full certification; change to `ready` when all requested Cases complete without startup, runtime, or invocation errors. Judge failures do not block promotion. |
| `ready` | Treat as already certified, return success, and do not rerun. |
| `planned`, `blocked`, or any other state | Refuse certification and exit with code `2`. |
| `enabled = false` | Refuse certification and exit with code `2`. |
| Not registered | Refuse certification and exit with code `2`. |

### 5.4 Full Certification Flow

Certification uses the same trusted host flow as normal benchmarks:

1. Load and validate the Registry, Agent directory, manifest, and requirement.
2. Check DefuzeX SDK configuration.
3. Start the target Agent, including Docker build/runtime when applicable.
4. Generate a Case from the DefuzeX Server.
5. Run each SDK Input.
6. Submit to the DefuzeX Judge.
7. Append complete events and results to the certification JSONL.
8. Atomically update the Registry status from `adapting` to `ready` only when
   all requested Cases complete without startup, runtime, or invocation errors.

None of the following situations promote the Agent:

- Agent startup, runtime, or invocation failure;
- any requested Case does not complete;
- execution is interrupted;
- the Registry status changes during certification;
- the target Registry block is missing `status`.

A DefuzeX Judge failure means the Agent completed the workflow but did not
satisfy the benchmark. Certification still promotes the Agent because `ready`
means the adapter/runtime is runnable, not that benchmark quality is high.

The status update modifies only the target Agent's `status` line and preserves
field order, comments, and other Agents in the Registry. The temporary file is
created beside the Registry and is atomically replaced when complete.

### 5.5 Why Certification Does Not Keep a Viewer Running

`certify` is designed to be callable by developers and CI in non-interactive
contexts. It does not wait for `q` or `r` after completion, and it does not
start a viewer that would disappear when the process exits. The terminal prints
the result path and a command for opening it later.

View a certification result after it finishes:

```powershell
python -m agentbench view `
  results\certify-swe-agent-20260820-162500.jsonl
```

## 6. `view`

### 6.1 Syntax

```text
agentbench view [-h] [--host HOST] [--port PORT] result_log
```

```powershell
python -m agentbench view results\result-20260820-162500.jsonl
```

### 6.2 Arguments

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `result_log` | Yes | - | AgentBench `.jsonl` result file to read. |
| `--host HOST` | No | `127.0.0.1` | Viewer HTTP server bind address. |
| `--port PORT` | No | `8765` | Preferred bind port. |
| `-h`, `--help` | No | - | Show `view` help and exit. |

Examples:

```powershell
python -m agentbench view results\result.jsonl --port 9000
python -m agentbench view results\result.jsonl --host 127.0.0.1 --port 0
```

If the requested port is already in use, the viewer automatically chooses an
available port. `--port 0` asks the operating system to choose the port
directly. When bound to `127.0.0.1`, the viewer is local-only and does not
require Node.js.

The terminal prints the real URL and absolute result path:

```text
View: http://127.0.0.1:8765/suite/suite_xxx/
Result log: <absolute-path>\result-20260820-162500.jsonl
```

Press `Ctrl+C` to stop the server. A missing result path raises an error
immediately and does not create an empty file.

## 7. JSONL Results and Interruption Recovery

Result files are append-only event streams and may contain:

| Event | Meaning |
| --- | --- |
| `run_started` | Suite ID and selected Agents. |
| `step_started` | One SDK Input started, including input ID and payload. |
| `step_completed` | Input invocation succeeded, including standard output and trace-like raw state. |
| `step_failed` | Input invocation failed, including error type, message, and any captured output. |
| `agent_completed` | One Agent's Cases, report, and error summary. |
| `suite_completed` | Suite summary for passed, failed, skipped, and selected Agents. |
| `suite_failed` | Suite failed during shared configuration. |

If the process is interrupted, the file may not contain `suite_completed`. The
viewer marks it as `running_or_interrupted`, but already appended Cases, steps,
and errors remain viewable.

Results may contain inputs, outputs, raw adapter state, and error messages.
Review result files for sensitive data before sharing or submitting them.

## 8. Exit Codes

| Exit code | Commands | Meaning |
| --- | --- | --- |
| `0` | `run` | User cancelled, or all selected benchmarks passed. |
| `0` | `verify` | `PASS` — every phase that ran held — or `PARTIAL`, where preflight held but this host could not grade the Agent. |
| `0` | `certify` | Certification completed and promoted the Agent, completed with Judge failures but still promoted, or the Agent was already `ready`. |
| `0` | `view` | Viewer stopped normally. |
| `1` | `run` | No runnable ready Agents, shared configuration failed, or at least one benchmark failed. |
| `1` | `verify` | The Agent failed to start, failed a probe, had no model call captured, or did not pass the graded Run. |
| `1` | `certify` | Certification did not complete because of shared configuration, startup, runtime, or invocation failure. |
| `2` | `verify` | Agent does not exist, does not use the Docker runtime, declares no `[llm_interception]`, or `--probes`/`--inputs` was below 1. |
| `2` | `certify` | Agent does not exist, is disabled, has a disallowed state, or Registry update failed after certification completed. |
| `2` | all commands | `argparse` detected an unknown command, unknown argument, or missing required argument. |

Unhandled exceptions that are not converted by the CLI, such as a missing file
for `view`, usually exit Python with a non-zero status and print the exception.

## 9. FAQ

### Normal run did not generate JSONL or trace output

Make sure `--output` was provided:

```powershell
python -m agentbench run --output results\result.json
```

Normal `run` does not save results when `--output` is omitted. `certify` is
different: it always saves certification results.

### An `adapting` Agent does not appear in normal `run`

This is expected. Use:

```powershell
python -m agentbench certify <agent_id>
```

After certification completes without startup, runtime, or invocation errors,
the Registry automatically changes to `ready`, and the next normal `run` can
select the Agent.

### `certify` completed, but the Registry was not updated

Check the last terminal line. If the Registry status changed during
certification, or the target block is missing `status`, the CLI refuses to
overwrite it and returns `2`. Check `resources/registry.toml`, then certify
again.

### The viewer cannot open the default port

Use the URL printed by the terminal. If port `8765` is occupied, the CLI chooses
another port. If firewall or proxy behavior is unusual, explicitly use:

```powershell
python -m agentbench view <result.jsonl> --host 127.0.0.1 --port 0
```

### Docker Agent fails during startup

Make sure Docker Desktop is running, then check the Agent's Dockerfile, worker
command, and `agent.toml`. AgentBench uses a read-only root filesystem and
mounts `/tmp` as a fresh writable tmpfs for each run. See
`How To Add Agent.md` for the full adaptation constraints.

## 10. CLI Development Structure

The CLI uses an explicit feature registry instead of hard-coding command
branches in the root entry point:

```text
agentbench/cli/
  main.py                 root parser and feature dispatch
  execution.py            shared benchmark execution and result writing
  presentation.py         terminal display and interaction
  progress.py             the animated stage column, shared by certify and verify
  registry_status.py      Registry status updates
  result_export.py        append-only JSONL writer
  trace_runtime.py        runner wiring for live provider traffic
  verify_runtime.py       verify's two runtime stacks and shared trace sinks
  verify_preflight.py     subject selection, and probing the Agent directly
  verify_providers.py     what this host needs before it can grade an Agent
  verify_report.py        sectioned verify report, judgment reading, JSON summary
  viewer.py               local HTTP viewer server
  TerminalUI/
    LLMactivity.py        self-erasing live panel for the current model call
    call_log.py           completed calls retained for the final report
  features/
    base.py               CommandFeature contract
    __init__.py           FEATURES registry
    run.py                run arguments and workflow
    view.py               view arguments and workflow
    verify.py             verify arguments and phase orchestration
    certify.py            certify arguments and workflow

agentbench/harness/local/
  case.py  judge.py  prompts.py  chat.py  suite.py
                          the Case and Judge Providers verify supplies locally

agentbench/runtime/contracts/
  secrets.py              strict and placeholder-substituting secret resolvers
```

Both `verify` phases deliberately keep `execution.py` untouched. Preflight never
reaches it — it drives the adapter directly — and the benchmark's Provider
arguments are injected by `LocalBenchmarkSuiteRunner` instead of widening the
shared execution signature.

When adding a subcommand:

1. Create a separate module in `agentbench/cli/features/`.
2. Implement `configure_parser(parser)` and `execute(args)`.
3. Export a `CommandFeature`.
4. Register it in `FEATURES` in `features/__init__.py`.
5. Put shared behavior in common CLI modules; do not duplicate benchmark or
   viewer lifecycle logic.
6. Add parser dispatch, success, failure, and boundary tests.
7. Update this document with the command, arguments, exit codes, and examples.

There must be exactly one `default=True` feature. The current default feature is
`run`.
