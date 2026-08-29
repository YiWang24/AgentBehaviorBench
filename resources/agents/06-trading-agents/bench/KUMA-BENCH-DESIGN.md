# `kuma_bench.py` 设计分析

目标：一个 Python 文件，尽量复用 AgentBehaviorBench（下称 ABB）现有函数，把
06-trading-agents 连同 KUMA SDK 一起在 Docker 里启动，跑 `bench/cases.json` 里
每一条 case，并采集 KUMA 判定所需的全部数据（含 OTel evidence）。

本文所有结论要么来自源码位置，要么来自本机实测；实测项标注了测得的数字。

---

## 一、核心架构冲突：SDK 必须在容器内，而 ABB 的 runtime 把 SDK 放在容器外

这是决定整个脚本形态的唯一硬约束。

ABB 现有的 Docker 拓扑（`agentbench/runtime/docker/runtime.py:165`）是：

```
宿主机                                 容器
─────────────────────────────────      ──────────────────────
BenchmarkRunner._run_with_running  ──►  worker.py 读 stdin
  sdk_run.get_input()                     JSONL: {"input": ...}
  running.invoke(payload)          ◄──    JSONL: {"ok": true, "output": ...}
  sdk_run.submit(output)
```

SDK Run 活在宿主机进程里，agent 活在容器里，中间是 `DockerSession` 的 JSONL 管道。

KUMA 不允许这样。`resolve_runtime_mode`（`kuma/runtime.py:41`）在 `is_running_in_docker()`
为假且未开 `allow_local` 时直接抛 `DockerRequiredError`，措辞是
"KUMA runs must start inside the same Docker container as the Agent"。

后果连锁：

- `EvidenceCollector` 的 `tracking_root` 在 docker 模式下是 `Path("/")`
  （`kuma/api.py:233`），即证据路径是**容器相对**的。SDK 在宿主机跑，采到的
  文件证据就指向宿主机路径，语义错误。
- `TraceEvidenceCapture` 是**进程内**的 OTel SpanProcessor（`kuma/otel.py:110`）。
  agent 的 span 产生在容器进程里，宿主机的 capture 一条都收不到。
- `ContainerRunLock` 落在 `/tmp/kuma-active-run.lock`（`kuma/runtime.py:59`），
  语义是"每容器一个活跃 Run"。

**结论：Run 循环必须整体搬进容器。** 因此 `BenchmarkRunner.run_defuzex()` 无法直接调用，
`DockerSession` 的 invoke 管道在这条链路上也失去作用——它们服务的是另一种拓扑。

顺带一处失修：`benchmark_runner.py:385` 仍 `from defuzex import create_run`，
而 SDK 早已更名为 `kuma`（`KUMA-DefuzeX/src/defuzex` 只剩无 `__init__.py` 的
`__pycache__` 残留）。这条路径当前必然 `ModuleNotFoundError`。

### 采用的拓扑

```
宿主机  kuma_bench.py（orchestrator）
  │  复用 ABB：registry / AgentContainerConfig / DockerImageBuilder / DockerPolicy
  │  每条 case 起一个容器
  ▼
容器  kuma_bench.py --in-container（同一个文件，第二种角色）
        kuma.create_run(自定义 Case + 自定义 Judge + trace_evidence=capture)
        while get_input(): 驱动 TradingAgentsGraph → submit(output, logs=[...])
        run.judge() → /out/<case_id>/report.json
```

同一个文件承担两种角色，宿主机侧只 import `agentbench`，容器侧只 import `kuma`，
两边的 import 都做成惰性的，互不污染。

---

## 二、KUMA 能接收的证据通道，以及每条通道装得下什么

实测方式：`ta-kuma-otel:v1` 容器内跑一个无 LLM 调用的探针，喂进 3 个
gen_ai 语义 span，检查 SDK 究竟留下了什么。

| 通道 | 怎么传 | 自定义 Judge 能看到 | 官方 Judge 能看到 |
|---|---|---|---|
| **A. OTel trace** | `create_run(trace_evidence=capture)` | `extensions["trace_evidence"]` 全量 span 树 | 1 个 `artifact_snapshot`，**仅 sha256 + size** |
| **B. submission output** | `submit(output=...)` 或由 span 自动派生 | `Submission.output` 全文 | `agent_response_claim.text_sha256` |
| **C. 日志文件** | `submit(logs=[path])` | `Submission.logs[i]["content"]` 全文 | `artifact_snapshot`，仅 sha256 |
| **D. 文件变更** | `track_files=True` | 路径 + 前后 sha256 | 同左 |
| **E. ABB 模型拦截器** | 不属于 KUMA，可作为 C 的一个文件挂进去 | 取决于挂法 | 同 C |

### A：OTel 通道实测

探针输出（3 span，2,139 字节 trace evidence）：

```
tradingagents.workflow  attrs={"gen_ai.operation.name":"invoke_agent",
                               "gen_ai.provider.name":"deepseek",
                               "gen_ai.system":"langgraph"}
Market Analyst          attrs={"gen_ai.operation.name":"chat",
                               "gen_ai.request.model":"deepseek-v4-flash",
                               "gen_ai.response.model":"deepseek-v4-flash",
                               "gen_ai.usage.input_tokens":8123,
                               "gen_ai.usage.output_tokens":940}
get_stock_data          attrs={"gen_ai.operation.name":"execute_tool"}
```

三条必须知道的规则（`kuma/evidence/trace_mapping.py:16-52`）：

1. **属性白名单极窄**。只留 `gen_ai.operation.name` / `gen_ai.provider.name` /
   `gen_ai.request.model` / `gen_ai.response.model` / `gen_ai.system`，
   外加前缀 `gen_ai.latency.` / `gen_ai.token.usage.` / `gen_ai.usage.`。
   Resource 侧另有 6 个允许键（`service.name` 等）。
2. **命中私有词表的属性会被计入 dropped 并把 traces 状态打成 partial**。
   探针故意设了 `gen_ai.prompt`，结果：`dropped=1`，
   `reasons=('trace_attribute_filtered',)`，`capture_status.traces=partial`，
   并在 `run.runtime_warnings` 留下 `trace_evidence:trace_attribute_filtered`。
   正文确实没泄漏（探针验证 `"SECRET PROMPT TEXT" in envelope` 为 `False`）。
   → **不要设这类属性**，否则每条 case 的 trace 状态都是 partial。
3. **不在白名单又不含私有词的属性被静默丢弃**。`gen_ai.tool.name` 就是这样没的，
   连 dropped 计数都不加。→ **工具名只能放进 span name**，
   span name 完整保留（上限 `max_text_length=256`）。

`submit()` 不传 output 时会自动从 span 派生（`kuma/run.py:226-236` →
`extract_agent_output`，`trace_mapping.py:267`）：要求某个 span 的
`gen_ai.operation.name ∈ {invoke_agent, invoke_workflow}` 且带
`gen_ai.output.messages`。探针验证该路径可用。注意
`gen_ai.output.messages` 本身**不进** span 属性白名单——它只喂 output 通道，
不落进 trace 证据，这是有意设计。

配额（`kuma/evidence/trace.py:59-67`）：`max_spans=200`（每步）、
`max_attributes=32`、`max_events_per_span=20`、`max_text_length=256`、
`max_total_bytes=512_000`（按 `(run_id, case_id)` 累计，**跨步共享**）。

按探针测得的 ~700 字节/span 外推：单条 case 约 30 span（1 workflow + 8 节点 +
11 LLM + 10 工具，取自 pos-01 的实测计数）≈ 21KB，宽裕；但 10 条 case 塞进
**同一个 Run** 会累到 ~210KB…上限虽未破，节点更多的 case（4 analysts / 2 轮辩论）
很容易把 200 span 和 512KB 一起顶穿，后面的 case 会拿到 `trace_budget_exhausted`。

> **→ 每条 case 独立一个 Run、独立一个容器。** 这同时避开了
> `ContainerRunLock` 的每容器单 Run 限制，也让一条 case 卡死不牵连其余九条
> （TradingAgents 单条 6–8 分钟，pos-01 实测 392.3s）。

### D：本项目基本不可用

docker 模式下 `tracking_root` 是 `/`，`Snapshotter` 会遍历整个 rootfs。
实测 `ta-kuma:v1` 的 `find / -xdev -type f | wc -l` = **31,681**，
每步要做两次（baseline + after）全量哈希。且它只产出路径 + 哈希，
对"决策文本是否是 Buy"这类判据毫无帮助。**保持 `track_files=False`。**

---

## 三、上一轮已经证伪的路径（不要重走）

来自 `git show d1604fa:.../bench/KUMA-SDK-ISSUES.md`（534 行，已实测）：

1. **requirement 的 `## Input Schema` 一律过不了校验**。`parse_requirement` 用
   `_freeze_json` 把 schema 冻成 `MappingProxyType` / `tuple`，随后
   `_resolved_input_schema` 交给 jsonschema 的 `check_schema`，而 jsonschema 的
   `"object"` 只认 `dict`、`"array"` 只认 `list` → 必然失败。
   而 `requirements.py:282` 又规定 `input_type: structured` 必须声明 schema，
   形成死锁。
   **绕法（已验证）**：类式 Provider 声明 `requirement_required = False`，
   `create_run(requirement_path=None)`。`api.py:404` 的
   `getattr(provider, "requirement_required", True)` 会读到 False。
2. **官方 Case 生成对领域 agent 不可用**：`defuzex.casegen.ita.v1` 返回的是
   通用 SWE 修复六步流程，与交易语义无关。→ 必须自带 Case Provider。
3. **官方 Judge 结构性看不到正文**。`_official_evidence_upload.py:206-217` 里
   typed 路径（hash-only）只要 `runtime_parts` 非空就无条件胜出，而 runtime
   evidence 信封**总会**至少发一个 `agent_response_claim` → legacy 的带正文
   路径永远发不出去。实测三条 case 全判 `insufficient_evidence`。
   但同一份文档第八节做了修正：**官方 Judge 本身是好的**——只要验收标准能用
   它真正收到的证据（文件路径、文件操作、claim 状态）表达，它会给出精确、
   可追溯到 `component_id` 的判定。问题在于 TradingAgents 的判据是**文本**。
4. `upload_diff=True` 名不副实：`diff.py` 产出的 `text_diff` 只写进本地 record，
   `PreparedEvidence` 不带它，不上传任何东西。
5. **SDK 返回的是 `mappingproxy` 不是 `dict`**。`isinstance(x, dict)` 会静默
   拿到空结果，不抛异常不告警。消费侧一律用 `collections.abc.Mapping`。
6. 同一 `case_id` 换内容会在**judge 阶段**才抛 `CaseIntegrityError`，
   此时算力已经花完。→ case_id 要随选中的 case 集合派生。

一处修正：该文档说 payload 里的 list 会变成 tuple。本轮探针测得
`get_input()` 返回的 `analysts` 是 **`list`**——因为 `get_input()` 走
`_plain_json`（`run.py:46`）把冻结结构还原了；只有 `get_input(full=True)`
才拿到冻结的 `KumaInput`。上一轮的 driver 用的是 `full=True`，所以看到 tuple。
两种都对，取决于怎么取。

---

## 四、能复用的 ABB 组件（宿主机侧）

| 组件 | 位置 | 用途 | 可用性 |
|---|---|---|---|
| `load_registry` / `AgentRegistration` | `harness/registry.py` | 按 agent_id 找路径 | 直接用 |
| `AgentContainerConfig.from_agent_dir` | `runtime/agentcontainer/config.py:34` | 解析 agent.toml → 构建上下文 / argv / workdir / env / timeout | 直接用 |
| `DockerImageBuilder.build` | `runtime/docker/image_builder.py:29` | 内容寻址构建，同内容不重复 build | 直接用 |
| `DockerPolicy.run_arguments` | `runtime/docker/policy.py:14` | `--read-only --cap-drop=ALL` 等安全参数 | 用，但需两处偏离（见下） |
| `BenchmarkResult` / `BenchmarkStepResult` / `SuiteAgentResult` | `harness/result.py` | 结果数据结构 | 直接用 |
| `ResultLogWriter` / `append_result_event` | `cli/result_export.py` | 追加式 JSONL 结果件，与 `results/*.jsonl` 同格式 | 直接用 |
| `emit_progress` / `BenchmarkProgress` | `harness/progress.py` | 阶段事件 | 直接用 |
| `LLMActivity` | `cli/TerminalUI/LLMactivity.py` | 终端活动显示 | 可选 |
| `DockerSession` | `runtime/docker/session.py` | JSONL invoke 管道 | **不用**（拓扑不符） |
| `BenchmarkRunner.run_defuzex` | `harness/runner/benchmark_runner.py:36` | SDK 握手循环 | **不能直接用**（SDK 在宿主机 + import 已失修），但容器侧的循环照抄它的形状 |
| `runtime/interception/*` | mitmproxy 模型拦截 | 网络层 LLM 收发全文 | 可选加挂，见第六节 |

### `DockerPolicy` 需要的两处偏离

1. `--memory=1g` / `--cpus=1.0` 对 TradingAgents 偏紧（`run-demo.sh` 当前不限）。
   参数化，默认放宽到 4g / 2.0。
2. `--read-only` 与 KUMA 冲突：`ensure_repo_runtime_directory`（`runtime.py:171`）
   要在 `repo_path` 下 `mkdir .kuma` 并改写 `.gitignore`。
   → 给 `repo_path` 挂一个可写的 tmpfs 或宿主机目录；`/tmp` 已有 tmpfs 但
   默认 `size=64m` 且 `noexec`，需调大。

---

## 五、镜像分层

```
ta-native:a33fd4c          ← TradingAgents/Dockerfile 原样构建，不改上游一行
      │
      ├─ + pip install /opt/kuma-src         （KUMA SDK 源码，见下）
      ├─ + pip install opentelemetry-api/sdk （kuma-defuzex[otel] 的实际内容）
      └─ + ENTRYPOINT []                     （上游是 ["tradingagents"]，
                                               不清掉会把 argv 当 CLI 参数吞掉）
bench/ 与 out/ 用挂载而非 COPY，镜像里不含我们写的东西。
```

`kuma-defuzex` **不在 PyPI 上**（`pip index versions kuma-defuzex` → no matching
distribution）。已存在的 `ta-kuma:v1` 是把 SDK 源码 `COPY kuma-src /opt/kuma-src`
再 `pip install` 进去的。脚本需要把 `/home/wy/projects/DefuzeX/KUMA-DefuzeX`
暂存进构建上下文——用临时目录 stage，交给 `DockerImageBuilder` 内容寻址。

现有镜像盘点：`ta-native:a33fd4c`(559MB) / `ta-kuma:v1`(564MB，含 kuma 0.1.0 +
tradingagents 0.3.1 + langchain-core 1.6.1，**无 otel**) /
`ta-kuma-otel:v1`(本轮探针所建，已补 otel)。

---

## 六、LangChain → OTel 的桥

TradingAgents 是 LangGraph 应用，镜像里没有任何 OTel 自动埋点。两种做法：

- **(选用) 自写 `BaseCallbackHandler` → OTel span 桥**。上一轮的
  `capture.py::FullCapture` 已经把所有回调抓全了（`d1604fa` 可取回），
  在它基础上加开/关 span 即可，注入点是上游自己暴露的
  `TradingAgentsGraph(callbacks=[...])` 和 `Propagator.get_graph_args(callbacks=[...])`，
  不 monkeypatch、不改上游。
  span 形状：
  - 根 span `tradingagents.workflow`，`gen_ai.operation.name=invoke_agent`，
    收尾时 set `gen_ai.output.messages`（供 output 自动派生）
  - 每个图节点一个 span，span name = 节点名
  - 每次 LLM 调用一个 span，`operation.name=chat` + `request.model` /
    `response.model` / `gen_ai.usage.*`
  - 每次工具调用一个 span，**span name = 工具名**（属性放不下），
    `operation.name=execute_tool`
- (不选) `openinference-instrumentation-langchain` 之类第三方 instrumentor：
  会喷出大量白名单外属性，其中 `*.prompt` / `*.content` 命中私有词表，
  每条 case 都会被打成 partial + 高 dropped_count。

**正文（prompt / completion / 工具参数与完整输出）走通道 C**：
`FullCapture` 已经在写 JSONL sink，`submit(logs=[sink])` 把它整个交给 SDK，
自定义 Judge 侧可读到全文（上一轮实测单条 case 41 万字符）。
OTel 负责**结构与指标**，sink 负责**正文**，两者互补。

---

## 七、判定（Judge）

默认走**自定义 Judge**：`bench/cases.json` 的 `rubric` 已经为 10 条 case 写好了
机器可判的 `checks`（`nodes_visited_include` / `min_tool_calls` / `tools_include` /
`state_fields_nonempty` / `signal_in` / `decision_contains_explicit_rating_label` /
`decision_numbers_must_appear_in_tool_output` 等）。`rubric` 是 `normalize_case`
唯一豁免私有数据扫描的子树（`normalization.py:132`），是传判分标准的正确通道，
上一轮已验证它完整穿过 Case → Run → JudgeContext。

官方 Judge 作为 `--official-judge` 开关保留（默认关）。它会消耗额度并上传数据，
且按第三节第 3 条，对文本型判据只会给 `insufficient_evidence`——但它对
"trace 里有没有出现某个 span / claim 状态是什么"这类判据是准确的，值得留口子。

注：环境变量是 **`KUMA_API_KEY`**，不是 `DEFUZEX_API_KEY`
（`benchmark_runner.py:378` 读的是后者，也是失修的一处）。

---

## 八、脚本骨架

`bench/kuma_bench.py`，单文件双角色：

```
main()
├─ --list                     列出 cases.json 里的 10 条
├─ (宿主机默认角色)
│   ├─ load_registry → AgentRegistration            [复用]
│   ├─ AgentContainerConfig.from_agent_dir          [复用]
│   ├─ stage 构建上下文（+ KUMA 源码）→ DockerImageBuilder.build  [复用]
│   ├─ for case in 选中的 cases:
│   │     docker run --rm  <policy 参数>  <挂载 bench/ 与 out/case_id/>
│   │        python /opt/bench/kuma_bench.py --in-container --case <id>
│   │     收集 /out/<id>/{report.json, trace.jsonl, submission.json}
│   │     ResultLogWriter.append_step_*             [复用]
│   └─ 汇总 → BenchmarkSuiteResult → results/kuma-trading-agents-<ts>.jsonl [复用]
└─ --in-container
    ├─ TracerProvider + configure_trace_evidence()
    ├─ create_run(case_provider=OneCaseProvider(id),
    │             judge_provider=RubricJudge() 或 None,
    │             max_inputs=1, track_files=False,
    │             requirement_path=None, trace_evidence=capture)
    ├─ while (item := run.get_input(full=True)):
    │     驱动 TradingAgentsGraph（callbacks=[OtelBridge(sink)]）
    │     run.submit(output, status=..., logs=[sink])
    └─ run.judge() → 写 /out/<id>/report.json
```

宿主机侧一条 case 失败不影响其余：容器退出码与超时都记进
`BenchmarkStepFailure`，继续下一条。

---

## 九、已知风险

| 风险 | 说明 | 处置 |
|---|---|---|
| 单条 6–8 分钟 | pos-01 实测 392.3s；10 条串行约 1 小时 | 默认只跑 `--case` 指定的一条；`--all` 显式开启，支持并发 |
| `deepseek-v4-flash` 深度推理挂死 | `run-demo.sh` 注释记录：Research Manager 的结构化输出调用复现两次冻结，>16 分钟、容器 0% CPU | 沿用 `run-demo.sh` 的 deep=`deepseek-v4-pro` 组合；容器级超时兜底 |
| neg-05 就是在测这个挂死 | 该 case 的判定依赖超时行为 | 容器超时须映射成 `submit(status="timeout")` 而不是脚本崩溃 |
| KUMA Run 锁 | 每容器单 Run | 每 case 独立容器，天然规避 |
| `--read-only` vs `.kuma` 目录 | 见第四节 | repo_path 指向可写挂载 |
| trace 配额 | 512KB / `(run_id, case_id)`，跨步共享 | 每 case 一个 Run；必要时抬 `TraceEvidenceLimits` |
