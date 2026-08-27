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

Show root help with:

```powershell
python -m agentbench --help
```

Current subcommands:

| Command | Purpose |
| --- | --- |
| `run` | Run all enabled Agents whose status is `ready`. |
| `view` | Open an existing JSONL result in the local web viewer. |
| `verify` | Check offline that one Agent starts and its model traffic is captured. Uses no credentials and no network. |
| `certify` | Verify one `adapting` Agent can complete its requested Cases and promote it to `ready`. |

`verify` is the only command that runs without `DEFUZEX_API_KEY`, without
`OPENROUTER_API_KEY`, and without network access. Use it while adapting an Agent,
before `certify`.

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

`verify` answers one question: **does this Agent start, respond, and is its model
traffic observable?** It does not measure benchmark quality and it does not change
the Registry.

The whole run is hermetic:

- no `DEFUZEX_API_KEY` and no `OPENROUTER_API_KEY` are read;
- the DefuzeX SDK is never imported;
- the container network is created with `--internal`, so nothing reaches the
  internet;
- model replies are generated inside the Model Interceptor by the `offline-mock`
  target, synthesized from whatever tools or response format the request declares;
- results go to a temporary file that is deleted unless `--keep-artifacts` is given.

### 4.2 Syntax

```text
agentbench verify [-h] [--env-file PATH] [--input TEXT] [--inputs N]
                  [--keep-artifacts] [--json] [--llm-trace {off,terminal}]
                  [--llm-trace-max-bytes BYTES] agent_id
```

```powershell
python -m agentbench verify langgraph-customer-support-agent
python -m agentbench verify swe-agent --inputs 3 --llm-trace terminal
python -m agentbench verify swe-agent --input "@prompts\probe.txt" --keep-artifacts
```

### 4.3 Arguments

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `agent_id` | Yes | - | Registered Agent ID. Disabled Agents and any `status` are accepted. |
| `--env-file PATH` | No | Repository `.env` | Load host defaults from another dotenv file. |
| `--input TEXT` | No | Short generic prompt | Probe text, or `@PATH` to read it from a file. |
| `--inputs N` | No | `1` | Number of probe inputs sent in the single Case. |
| `--keep-artifacts` | No | Delete | Keep the temporary result log and print its path. |
| `--json` | No | Human report | Print one JSON summary and nothing else. |
| `--llm-trace {off,terminal}` | No | `off` | Also dump every captured payload in full. Debugging only. |
| `--llm-trace-max-bytes BYTES` | No | `2048` | Maximum displayed bytes per request or response. |
| `-h`, `--help` | No | - | Show `verify` help and exit. |

Unlike `run` and `certify`, `verify` always runs exactly **one** Case regardless of
the Agent's `case` field, because it checks startup rather than coverage.

### 4.4 Agent Requirements

| Condition | Behavior |
| --- | --- |
| `runtime.type = "docker"` and an `[llm_interception]` section | Verification runs. |
| Any other runtime type | Refuse and exit `2`; no interceptor can observe an in-process Agent. |
| No `[llm_interception]` section | Refuse and exit `2`; model calls could be neither captured nor served offline. |
| Not registered | Refuse and exit `2`. |

Secrets declared in `runtime.secret_env_keys` do not need real values. Missing ones
are replaced with deterministic placeholders and the substituted names are printed,
so a stubbed secret never passes silently.

### 4.5 Verdict

Verification passes when all of the following hold:

- the Agent image builds and the container starts;
- every probe input is invoked without a startup, runtime, or invocation error;
- at least one complete `llm_request`/`llm_response` pair is captured.

A Judge-style report status is irrelevant here. An Agent whose reply is poor still
passes verification, because the adapter and runtime are what is under test.

### 4.6 Report Layout

The report has four sections: what is being checked, which stages passed, what the
model exchanged, and the verdict.

```text
verify · langgraph-customer-support-agent
       offline · no credentials · egress blocked · registry untouched

  ✓  configuration   local providers
  ✓  agent start     ContainerAgentAdapter
  ✓  case            offline_d9075725a90…
  ✓  agent run       2 model calls

     01  ▸ Reply with a short confirmation that you received thi…
         ◂ Tool: list_available_functions                  200 · 1.4ms
     02  ▸ Available Functions & Actions - search_vector_knowled…
         ◂ offline verification reply                      200 · 0.8ms

  PASS   1/1 cases · 2 model request/response pairs captured
```

On a terminal the stage currently running is shown as a self-erasing live line, so
only finished stages remain. Redirected output skips the live line entirely instead
of writing every animation frame.

A failure leads with the reason rather than a generic message:

```text
  FAIL   AgentStartError: container exited during startup
```

Call lists longer than ten are elided in the middle. Stubbed secrets, when any were
substituted, are listed above the verdict.

The report is the whole output by default. `--llm-trace terminal` adds a full dump
of every captured payload on top of it, which is a debugging firehose rather than a
verbosity level: an Agent that resends a long system prompt each turn produces
hundreds of extra lines. `verify` therefore caps each payload at 2048 bytes instead
of the 256 KiB used elsewhere; raise `--llm-trace-max-bytes` when a truncated
payload is exactly what needs inspecting.

### 4.7 Machine-Readable Output

`--json` prints one JSON document and suppresses every other line, so the exit code
and the document are the whole contract:

```json
{
  "command": "verify",
  "agent_id": "langgraph-customer-support-agent",
  "verdict": "pass",
  "exit_code": 0,
  "cases": {"completed": 1, "requested": 1},
  "model_calls": {
    "captured_pairs": 2,
    "calls": [
      {
        "number": 1,
        "provider": "offline",
        "status": 200,
        "latency_ms": 0.963,
        "request_preview": "Reply with a short confirmation that you received this message.",
        "response_preview": "Tool: list_available_functions"
      }
    ]
  },
  "substituted_secrets": [],
  "result_log": null,
  "reason": null
}
```

`verdict` is `pass`, `fail`, or `error`; `error` covers the preflight rejections in
section 4.4. `result_log` is populated only with `--keep-artifacts`.

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
| `0` | `verify` | The Agent started, answered every probe, and its model traffic was captured. |
| `0` | `certify` | Certification completed and promoted the Agent, completed with Judge failures but still promoted, or the Agent was already `ready`. |
| `0` | `view` | Viewer stopped normally. |
| `1` | `run` | No runnable ready Agents, shared configuration failed, or at least one benchmark failed. |
| `1` | `verify` | The Agent failed to start or complete a probe, or no model call was captured. |
| `1` | `certify` | Certification did not complete because of shared configuration, startup, runtime, or invocation failure. |
| `2` | `verify` | Agent does not exist, does not use the Docker runtime, declares no `[llm_interception]`, or `--inputs` was below 1. |
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
  registry_status.py      Registry status updates
  result_export.py        append-only JSONL writer
  trace_runtime.py        runner wiring for live provider traffic
  offline_runtime.py      runner wiring for credential-free offline runs
  verify_report.py        sectioned verify report and JSON summary
  viewer.py               local HTTP viewer server
  TerminalUI/
    LLMactivity.py        self-erasing live panel for the current model call
    call_log.py           completed calls retained for the final report
  features/
    base.py               CommandFeature contract
    __init__.py           FEATURES registry
    run.py                run arguments and workflow
    view.py               view arguments and workflow
    verify.py             verify arguments and workflow
    certify.py            certify arguments and workflow

agentbench/harness/offline/
  run.py                  local SDK Run, probe inputs, and startup report
  suite.py                suite runner that pins the local provider pair
  secrets.py              placeholder secret resolution for offline runs
```

The offline path deliberately keeps `execution.py` untouched: provider arguments
are injected by `OfflineSuiteRunner` instead of widening the shared execution
signature.

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
