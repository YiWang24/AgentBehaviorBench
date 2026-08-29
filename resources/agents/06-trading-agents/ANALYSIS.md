# 06 TradingAgents — 编排 / 工具 / 依赖 / 启动 / 数据抓取 → KUMA 接入方案

结论先行：**这个 agent 的数据抓取不需要改上游源码**，因为它自己就留了三个一等公民的注入点（LangChain callbacks、`openai_compatible` backend_url、vendor 路由单一出口）。真正的落差在两处：一是它的 CLI 无法非交互启动，二是 **KUMA 的 Evidence 契约在设计上就不搬运 prompt/completion**，而这恰恰是你要拿来优化 KUMA 内部逻辑的那部分数据。

代码依据：`tradingagents/` 16,663 行 / 137 个 py 文件，HEAD `a33fd4c`。

---

## 一、编排逻辑

`tradingagents/graph/setup.py` 用 LangGraph `StateGraph(AgentState)` 构图。三段流水线：

```
START → [Market → Sentiment → News → Fundamentals]   四个分析师串行，各自带工具环
      → Bull ⇄ Bear → Research Manager               研究辩论
      → Trader
      → Aggressive ⇄ Conservative ⇄ Neutral → Portfolio Manager → END
```

**节点构成**（4 分析师全开时共 20 个节点）：每个分析师是 3 个节点 —— `Market Analyst` / `tools_market` / `Msg Clear Market`（`analyst_execution.py:ANALYST_NODE_SPECS`），加上 8 个固定节点（Bull / Bear / Research Manager / Trader / Aggressive / Conservative / Neutral / Portfolio Manager）。

**条件边**（`graph/conditional_logic.py`）共 3 类：

| 路由函数 | 判据 | 出口 |
|---|---|---|
| `should_continue_{market,social,news,fundamentals}` | `messages[-1].tool_calls` 非空 | `tools_X` 否则 `Msg Clear X` |
| `should_continue_debate` | `investment_debate_state.count >= 2 × max_debate_rounds` | Bull / Bear / Research Manager |
| `should_continue_risk_analysis` | `risk_debate_state.count >= 3 × max_risk_rounds` | Aggressive / Conservative / Neutral / Portfolio Manager |

注意 `setup.py:32-42` 的 `DEBATE_PATH_MAP` / `RISK_ANALYSIS_PATH_MAP` —— 每条条件边都映射了全部目标，是为了防止路由函数 fall-through 导致 LangGraph 崩溃（上游 #1088）。**这是个天然的行为测试点**：如果 KUMA 要测「路由鲁棒性」，这里就是注入畸形 speaker label 的地方。

**状态结构**（`agents/utils/agent_states.py`）：`AgentState` 继承 `MessagesState`，除 `messages` 外有 15 个字段，其中 `investment_debate_state`（6 字段）和 `risk_debate_state`（10 字段）是嵌套 TypedDict。全量字段是抓取的目标集合。

**双 LLM 分层**：`quick_thinking_llm` 跑分析师+辩手，`deep_thinking_llm` 跑 Research Manager 和 Portfolio Manager（`setup.py:83-92`）。默认 `gpt-5.4-mini` / `gpt-5.5`。

**单次运行的 LLM 调用量**：默认 `max_debate_rounds=1` / `max_risk_rounds=1` 时，分析师段每人至少 2 次（出 tool_call + 读结果出报告）= 8 次，辩论 2 次 + Manager 1 次，Trader 1 次，风险 3 次 + PM 1 次 —— **下限约 16 次，实测多轮工具时到 24 次**。这直接决定了超时预算。

---

## 二、工具

12 个 `@tool`，装进 4 个 `ToolNode`（`trading_graph.py:_create_tool_nodes`）：

| ToolNode | 工具 |
|---|---|
| `market` | `get_stock_data`、`get_indicators`、`get_verified_market_snapshot` |
| `social` | `get_news` |
| `news` | `get_news`、`get_global_news`、`get_insider_transactions`、`get_macro_indicators`、`get_prediction_markets` |
| `fundamentals` | `get_fundamentals`、`get_balance_sheet`、`get_cashflow`、`get_income_statement` |

**关键结构**：12 个工具里有 **11 个**的函数体就是一行 —— `return route_to_vendor("<method>", *args)`（`get_indicators` 是在循环里对每个指标各调一次，本质相同）。也就是说：

> **绝大部分外部数据出口收敛到 `tradingagents/dataflows/interface.py:route_to_vendor()` 这一个函数。**

这是整个方案里最有价值的一点：屏蔽付费 vendor、注入确定性 mock、录制/回放，主要只需要在这一个点上做，而且不用碰工具定义 —— agent 的**原生工具调用行为完全保留**（LLM 照样自己决定调哪个工具、传什么参数）。

**但有一个例外，务必注意**：`get_verified_market_snapshot` **绕过了 vendor 路由**。它的调用链是

```
get_verified_market_snapshot                       (market_data_validation_tools.py:23)
  → build_verified_market_snapshot                 (dataflows/market_data_validator.py:62)
    → _verified_rows                               (market_data_validator.py:28)
      → load_ohlcv                                 (dataflows/stockstats_utils.py:148)
        → yf.download(...)                         (stockstats_utils.py:195)  ← 直连 yfinance
```

它**硬编码走 yfinance**，不看 `data_vendors` 配置，并且自带一套「5 年窗口、按 symbol 一个文件」的独立缓存。这是有意为之 —— 它是给分析师提示词用的「地面真值校验快照」，设计上就不该被 vendor 配置左右（`trading_graph.py:197-200` 的注释说明它必须可执行，否则模型会报告数据"unavailable"）。

**对方案的影响**：做确定性 mock 或离线回放时，**只拦 `route_to_vendor` 是不够的**，`get_verified_market_snapshot` 仍会打 Yahoo。需要两个拦截点：`route_to_vendor` 和 `load_ohlcv`（或更底层的 yfinance 层）。屏蔽付费 key 这件事不受影响，因为 yfinance 本来就无 key。

---

## 三、外部依赖

### 数据 vendor 矩阵（`interface.py:VENDOR_METHODS` + `default_config.py:data_vendors`）

| 方法 | alpha_vantage | yfinance | 其他 | 默认 | 需要 key |
|---|---|---|---|---|---|
| `get_stock_data` | ✓ | ✓ | | yfinance | 否 |
| `get_indicators` | ✓ | ✓ | | yfinance | 否 |
| `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` | ✓ | ✓ | | yfinance | 否 |
| `get_news` / `get_global_news` / `get_insider_transactions` | ✓ | ✓ | | yfinance | 否 |
| `get_macro_indicators` | | | fred | fred | **是**（`FRED_API_KEY`，免费注册） |
| `get_prediction_markets` | | | polymarket | polymarket | 否（公开 API） |

**开箱默认就是无付费 key 的**：11 个方法里 10 个走 yfinance/polymarket，唯一要 key 的是 `get_macro_indicators`(FRED)。`ALPHA_VANTAGE_API_KEY` 是可选替代 vendor，默认不启用。

`route_to_vendor` 的 fallback 语义要注意（`interface.py:179-193`）：配置的 vendor 列表**就是**完整链条，不会静默回落到未选择的 vendor（上游 #988/#289 修的就是这个）。所以屏蔽 alpha_vantage 只要不把它写进 `data_vendors` 即可，不会被偷偷用上。

### LLM 依赖

`llm_clients/api_key_env.py` 注册了 18 个 provider。其中三个不需要 key：`bedrock`（走 AWS 凭证链）、`ollama`（本地）、**`openai_compatible`（key 可选，专为本地/中继设计）**。

`openai_compatible` + `TRADINGAGENTS_LLM_BACKEND_URL` 是上游明确支持的通用 OpenAI 兼容端点入口 —— **这是把 LLM 流量导向 KUMA 侧的官方通道，不需要 TLS MITM**。

### 运行期落盘（容器内必须挂出来）

`~/.tradingagents/`（`TRADINGAGENTS_HOME`）下三个子目录，均可用环境变量重定向：

| 路径 | 环境变量 | 内容 |
|---|---|---|
| `logs/` | `TRADINGAGENTS_RESULTS_DIR` | 最终状态 JSON、报告树 |
| `cache/` | `TRADINGAGENTS_CACHE_DIR` | 数据缓存 + LangGraph checkpoint sqlite |
| `memory/trading_memory.md` | `TRADINGAGENTS_MEMORY_LOG_PATH` | **跨运行记忆** |

**跨运行记忆是可复现性的最大威胁**：`_run_graph` 起手就 `self.memory_log.get_past_context(company_name)` 把历史决策注入初始状态，收尾又 `store_decision()`。同一 ticker 跑第二次，输入已经不同了。做基准必须**每次运行给一个全新的 memory 路径**，否则 case 之间互相污染。

网络出口需求：`query*.finance.yahoo.com`（yfinance）、`gamma-api.polymarket.com`、`api.stlouisfed.org`（若启用 FRED）、以及 LLM 端点。

---

## 四、启动方式与阻塞点

上游镜像：`ENTRYPOINT ["tradingagents"]`，`python:3.12-slim` 两段构建，venv 在 `/opt/venv`，非 root 用户 `appuser`，工作目录 `/home/appuser/app`，卷 `/home/appuser/.tradingagents`。compose 里 `tty: true` + `stdin_open: true`。

**阻塞点：原生 CLI 无法非交互启动。**

`cli/main.py:get_user_selections()` 有 8 步交互。其中 5 步能被环境变量跳过（`TRADINGAGENTS_OUTPUT_LANGUAGE`、`_MAX_DEBATE_ROUNDS`+`_MAX_RISK_ROUNDS`、`_LLM_PROVIDER`、`_QUICK_THINK_LLM`/`_DEEP_THINK_LLM`、各 thinking 档位），但 **ticker、分析日期、分析师选择这三步没有任何环境变量出口**，必然要 questionary 交互。`analyze` 命令只有 `--checkpoint` / `--clear-checkpoints` 两个 flag。

所以自动化只能走**编程入口**：

```python
graph = TradingAgentsGraph(["market","social","news","fundamentals"],
                           config=cfg, debug=True, callbacks=[handler])
final_state, signal = graph.propagate("AAPL", "2026-08-27")
```

或者像 CLI 那样自己驱动 `graph.graph.stream(init_state, **args)`（见下一节，**必须走这条**）。

两条路的差别很关键：

- `propagate()` 内部调 `get_graph_args()` **不传 callbacks**（`trading_graph.py:432`）→ 只有绑在 LLM 构造器上的回调生效，**工具节点的 callback 收不到**。
- CLI 走 `get_graph_args(callbacks=[stats_handler])`（`cli/main.py:1128`）→ LLM + 工具全覆盖。

**要抓全数据必须复刻 CLI 的驱动方式，而不是调 `propagate()`。**

---

## 五、数据抓取：三个平面

### 平面 A — LangChain callbacks（保真度最高，上游一等公民）

`TradingAgentsGraph.__init__(callbacks=[...])` 把 handler 绑到两个 LLM 客户端上（`trading_graph.py:98-99`），`get_graph_args(callbacks=[...])` 把它注入 graph config 覆盖工具节点。上游自己的 `cli/stats_handler.py:StatsCallbackHandler` 就是这么用的（只数了个数）。

我们换成一个全量 handler，可拿到：

| 钩子 | 数据 |
|---|---|
| `on_chat_model_start` | 完整 prompt messages（含 system prompt、工具 schema） |
| `on_llm_end` | 完整 completion + `usage_metadata` token 数 |
| `on_tool_start` / `on_tool_end` | 工具名、入参、**原始返回体** |
| `on_chain_start` / `on_chain_end` | 节点边界，可还原实际走过的路径 |
| `on_llm_error` / `on_tool_error` | 失败点 |

**零源码改动**，因为这是上游已声明的参数。

### 平面 B — LangGraph stream（状态快照）

`stream_mode: "values"`（`propagation.py:82`）每步吐出**完整 state**。逐 chunk diff 就得到「哪个节点改了哪个字段」，覆盖 4 份报告、2 组辩论历史、investment_plan、trader_investment_plan、final_trade_decision 的逐步演化。

### 平面 C — 落盘产物

`_log_state()` 写最终状态 JSON，`save_reports()` 写 markdown 报告树。**注意 `_log_state` 丢掉了 `messages`**（`trading_graph.py:486-500` 只挑了 reports 和 debate state），所以落盘产物**不含 LLM 原始消息和工具调用**，不能作为唯一数据源。

---

## 六、KUMA 侧的契约与落差

读 `KUMA-DefuzeX/src/kuma/` 与 `docs/`：

**Run 协议**：`create_run()` → 循环 `run.get_input()` / `run.submit(output)` → `run.judge()`。同步、单进程。

**三条硬约束**：

1. **必须与 agent 同容器**。`runtime.py:is_running_in_docker()` 检查 `/.dockerenv` 与 `/proc/1/cgroup` 的 `docker|containerd` token，否则抛 `DockerRequiredError`。`allow_local=True` 只是开发开关。
2. **一个容器同时只能有一个活跃 Run**，用 OS 文件锁强制（`runtime.py:95-120`）。→ 并行跑多个 case 必须一个 case 一个容器。
3. **Trace Evidence 在设计上就不搬运 prompt/completion**。`evidence/trace_mapping.py` 的白名单只放行 `gen_ai.operation.name`、`gen_ai.provider.name`、`gen_ai.request.model`、`gen_ai.response.model`、`gen_ai.system`，加前缀 `gen_ai.latency.*` / `gen_ai.token.usage.*` / `gen_ai.usage.*`；黑名单 `_PRIVATE_ATTRIBUTE_TERMS` 明确拦掉 `prompt`、`completion`、`content`、`source`、`system_prompt`、`token`、`api_key`、`log.body`。

上面第 3 条只适用于 **OTel Trace Evidence 这一条通道**，不能推广到整个 Evidence 模型。逐个通道读完源码后的准确版本如下。

### 6.1 完整通道清单

| 通道 | 承载内容 | 上限（SDK 默认值） | 出处 |
|---|---|---|---|
| `submit(output=...)` | **任意嵌套 JSON 全文**（dict/list/str/bool/int/有限 float） | SDK 侧未见显式上限 | `contracts.py:_freeze_json` |
| `submit(logs=[...])` | **文件增量全文**（`"content"` 字段就是 UTF-8 正文，非哈希） | 20 个文件 / 单段 10 MB / 总计 20 MB；后缀限 `.txt .log .json .jsonl .md` | `evidence/tracking/logs.py:58-73, 195-222` |
| `Submission.extensions["runtime_evidence"]` | **仅哈希**，7 种封闭 component | 1–100 个 component，单个 EvidenceItem ≤ 120,000 字符 | `docs/runtime-evidence.md` |
| 文件追踪 `track_files=True` | 路径 / 哈希 / 大小 / mode / 变更类型；`upload_diff=True` 才带文本 diff | 100,000 条目 / 单文件文本 1 MB / 文本总计 32 MB | `evidence/tracking/snapshot.py:83-92` |
| OTel Trace Evidence | 骨架，白名单外全部丢弃 | 200 spans / 32 属性 / 单文本 256 字符 / 总计 512 KB | `evidence/trace.py:60-67` |
| 返回值 `TestReport` | `status`(pass/issue/insufficient_evidence)、`confidence`、`stop_reason`、`issues[]`、**`evidence_gaps[]`** | — | `contracts.py:328` |

**修正**：`logs` 通道装的是完整正文（`logs.py:220` 的 `"content": content`），总计 20 MB —— 对 TradingAgents 一次运行的全量 trace 是够用的。所以「KUMA 只能拿到骨架」这个说法只对 Trace Evidence 成立，**不成立于整个 Evidence 模型**。

因此双平面不是被契约**强制**的，而是一个可选的工程取舍：

- 只用 KUMA 单平面 → `output` 放结构化结论，`logs=[trace.jsonl]` 放全量事件流。够用，且省一套设施。
- 加本地平面 2 → 好处是不受 20 MB 上限约束、不过敏感扫描、可长期留存做回归。**建议保留**，但理由是容量与留存，不是「KUMA 收不下」。

### 6.2 敏感扫描的实际口径（比预想窄）

`repository/privacy.py:29-48` 只匹配 7 类具体凭证特征：PEM 私钥头、`Authorization: Bearer/Basic`、`Cookie:`、GitHub token（`ghp_`/`gho_`/…）、AWS key（`AKIA`/`ASIA`）、KUMA key（`dfx_`）、以及 `api_key|access_token|auth_token|password|secret` 后跟 16 位以上的赋值。

**普通金融文本、ticker、价格数字不会触发**。第九节原先列的「敏感扫描误报率」这个未知项可以划掉。

### 6.3 Runtime Evidence 的 7 种 component —— 这就是 KUMA 想知道的「agent 的哪些方面」

`docs/runtime-evidence.md:54-62` 定义了封闭联合类型：

| kind | 字段 |
|---|---|
| `file_change` | `path`、`change_type`(created/modified/deleted/unchanged)、`before_sha256`、`after_sha256`、`size_bytes` |
| `tool_call` | `tool_name`、`outcome`(succeeded/failed/unknown)、**必填 `arguments_sha256`**、`result_sha256` |
| `command_result` | `command_id`、`exit_code`、`stdout_sha256`、`stderr_sha256` |
| `test_result` | `suite_id`、`outcome`(passed/failed/partial)、`passed`、`failed`、`skipped` |
| `state_transition` | `state_id`、`outcome`、`before_sha256`、`after_sha256` |
| `artifact_snapshot` | `artifact_id`、`path`、`sha256`、`size_bytes`、`media_type` |
| `agent_response_claim` | `claim_id`、`claim`(completed/refused/blocked)、`text_sha256` |

**关键一句在 `runtime-evidence.md:70-72`**：

> "The SDK currently has no public instrumentation that proves tool calls, commands, tests, or state transitions, so it does not emit or declare those kinds."

即 `tool_call`、`state_transition`、`command_result`、`test_result` **在 wire schema 里已定义，但 SDK 目前观测不到、不会发出**。当前实现只发 `agent_response_claim`，文件追踪发 `file_change`，日志/OTel 发 hash-only 的 `artifact_snapshot`。

这正是 06 能补上的位置：LangChain callback 拿得到 `on_tool_start/end`（→ `tool_call`，含 `arguments_sha256` / `result_sha256`）和 `on_chain_start/end`（→ `state_transition`，对应 20 个图节点）。**这是「用 06 来优化 KUMA 内部逻辑」最直接的切入点** —— 不是给 KUMA 加新 schema，而是为已有 schema 提供第一个真实的 instrumentation 来源。

### 6.4 输入侧也比预想灵活

`KumaInput.payload_type` 允许 `"text"` 或 `"structured"`，后者接受 Mapping 或 sequence（`contracts.py:85-91`）。所以 `{"ticker": "AAPL", "date": "...", "analysts": [...]}` 这种多字段输入 **KUMA 本身是支持的** —— 第八节第 1 条的单键限制来自 AgentBehaviorBench 的 `input_key`/`output_key` 适配层，不是 KUMA 的约束。

### 6.5 两个平面的关联键

`run_id` + `input_id`（`index`）。`Submission` 三元组 `run_id`/`case_id`/`input_id` 与 runtime evidence envelope 的 `run_id`/`input_id`/`step_id`/`submission_id` 一致，本地 JSONL 用同一组键即可对齐。

---

## 七、端到端流程方案

### 镜像：分层，不动上游

```
Layer 0  上游原生镜像            docker build -t ta-native .        ← Dockerfile 一字不改
Layer 1  FROM ta-native          USER root
                                 pip install kuma-defuzex[otel]
                                 COPY driver.py capture.py
                                 USER appuser
                                 ENTRYPOINT ["python","/opt/bench/driver.py"]
```

上游 Dockerfile 保持原样作为基础层，「原生」得以保留；KUMA SDK 和 agent 同容器，满足 `is_running_in_docker()`。

### 运行时配置（全部环境变量，零源码改动）

```bash
# LLM：走 KUMA 侧 OpenAI 兼容端点，无付费 key
TRADINGAGENTS_LLM_PROVIDER=openai_compatible
TRADINGAGENTS_LLM_BACKEND_URL=http://kuma-model:8080/v1
TRADINGAGENTS_QUICK_THINK_LLM=<model>
TRADINGAGENTS_DEEP_THINK_LLM=<model>
# 确定性
TRADINGAGENTS_TEMPERATURE=0
TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
TRADINGAGENTS_MAX_RISK_ROUNDS=1
# 隔离：每个 case 一份全新记忆，杜绝跨 case 污染
TRADINGAGENTS_MEMORY_LOG_PATH=/run/case/<case_id>/memory.md
TRADINGAGENTS_RESULTS_DIR=/run/case/<case_id>/results
TRADINGAGENTS_CACHE_DIR=/run/case/<case_id>/cache
```

付费 vendor 屏蔽：`config["data_vendors"]` 不写 `alpha_vantage`（默认已如此）。`get_macro_indicators` 若无 `FRED_API_KEY`，`route_to_vendor` 会抛 `VendorNotConfiguredError` 且无其他 vendor 可退 —— 两个选择：给一个免费 FRED key，或干脆不选 `news` 分析师（唯一用到 fred/polymarket 的节点）。

若要做离线/确定性回放，记得同时接管 `dataflows/stockstats_utils.py:load_ohlcv`，否则 `get_verified_market_snapshot` 会绕过 vendor 路由直连 Yahoo（见第二节）。

### driver.py 的形状

```python
run = create_run(repo_path="/run", requirement_path="requirement.md",
                 trace_evidence=configure_trace_evidence(provider))
while (case := run.get_input()) is not None:
    cap = FullCapture(sink=f"/run/case/{case_id}/trace.jsonl")   # 平面 2
    graph = TradingAgentsGraph(analysts, config=cfg, debug=False, callbacks=[cap])
    init  = graph.propagator.create_initial_state(
                case["ticker"], case["date"],
                instrument_context=graph.resolve_instrument_context(case["ticker"]))
    args  = graph.propagator.get_graph_args(callbacks=[cap])      # ← 关键，别用 propagate()
    final = None
    for chunk in graph.graph.stream(init, **args):
        cap.on_state(chunk)                                       # 平面 B
        final = chunk
    run.submit(project(final, cap))                               # 平面 1
```

`project()` 负责把全量状态压成 KUMA 能收的 JSON（保留 final_trade_decision、signal、各报告摘要、工具调用序列的名字与参数），全文留在平面 2。

### 编排：一 case 一容器

KUMA 的单容器单 Run 锁决定了并行度模型 —— 外层调度器为每个 case 起一个容器，挂 `/run/case/<id>`，收集 `trace.jsonl`。超时预算按 16–24 次 LLM 调用估，**不能用现在的 60s**。

---

## 八、现有框架的具体落差

对照 `agent.toml` v2 契约（`resources/agents/02-*/agent.toml`）和 `agentbench/`：

| # | 现状 | 为什么在 06 上不成立 |
|---|---|---|
| 1 | `[adapter] input_key="prompt" / output_key="response"` | 输入是 (ticker, date, asset_type, analysts) 四元组，输出是 15 字段状态。单键映射会丢掉 4 份报告 + 2 组辩论全文 |
| 2 | `[runtime] timeout_sec = 60`（`agentcontainer/config.py:79` 默认值） | 单次运行 16–24 次 LLM 调用，实测十几分钟。差 1–2 个数量级 |
| 3 | `[adapter] mode="in_process"`、`config="langgraph.json"`、`graph_id` | **TradingAgents 没有 langgraph.json**，图由 `GraphSetup.setup_graph(selected_analysts)` 在运行时按配置构建，形状随分析师选择而变。`agentbench/adapter/` 下只有 `langgraph` 一个适配器，无法加载 |
| 4 | `[llm_interception]` 走 `api.openai.com` 的 TLS MITM + PEM 信任插件 | 上游原生支持 `openai_compatible` + `backend_url`，是被支持的重定向，比 MITM 简单且更稳；而且 MITM 只看得到 LLM 流量，看不到工具调用与节点跳转 |
| 5 | `input_mode="jsonl"` / `output_format="jsonl"` 单发单收 | 一次运行产生约 100+ 个中间事件，单行 JSONL 没有承载通道 |
| 6 | 无跨运行状态隔离约定 | `trading_memory.md` 会把上一个 case 的决策注入下一个 case 的初始状态 |
| 7 | 无「一容器一 Run」的并发模型 | KUMA 用 OS 锁强制单 Run，现有 runtime 没有对应约束 |

前四条是**契约层面**的，不是参数调优能解决的：v2 的 `agent.toml` 假设 agent 是「单轮 prompt→response 的 worker」，而 06 是「长时多阶段、状态驱动、工具密集」的形态。要接进来需要一个新的 agent 契约类别（比如 `[adapter] type="stateful-graph"` + 多字段输入输出 + 事件流输出通道），而不是给 v2 加字段。

---

## 九之前：实测结果（2026-08-28，Docker 29.7.2）

原生镜像 `docker build -t ta-native:a33fd4c .`（**Dockerfile 未做任何修改**）一次通过，559 MB。

| 验证项 | 结果 |
|---|---|
| `--help` | 正常，确认只有 `--checkpoint` / `--clear-checkpoints` 两个 flag |
| 原生入口无 TTY 启动 | **停在 "Step 1: Ticker Symbol"，报 `Input is not a terminal (fd=0)` 后 Aborted** —— 静态分析结论得到实证 |
| 容器内数据层 | yfinance 直连可用，取到真实 AAPL OHLCV（14 条记录），**全程无需任何付费 key** |
| 端到端运行（编程入口） | **跑通**。1 个分析师、127–149 秒、11 次 LLM 调用、65,859 token（53,826 in / 12,033 out）、10 次工具调用 |
| 产出质量 | `market_report` 10,181 字符、`final_trade_decision` 2,554 字符，含真实的 50SMA/MACD/布林带数值与执行触发条件 |
| callback 注入点 | **验证通过**：`on_tool_start/end` 给出工具名、完整入参、原始返回体；`on_llm_end` 给出 `usage_metadata`。第九节未知项 1、3 到此排除 |
| `past_context` | 冷容器为空，符合预期；compose 挂载 `/home/appuser/.tradingagents` 后会跨 case 累积（第三节的记忆污染风险成立） |

外推：1 个分析师 11 次调用 / 128 秒 → 4 个分析师约 20 次调用 / 4–6 分钟。

### 实测发现的稳定性缺陷：并发 yfinance 缓存锁

4 次完整运行挂了 1 次（挂的是构建后第一次跑）：

```
peewee.OperationalError: database is locked
During task with name 'tools_market'
```

成因：LLM 在**同一个 ToolNode 批次**里同时发出 `get_stock_data` 和 `get_verified_market_snapshot`，LangGraph 并行执行，两条**互相独立的 yfinance 路径**并发初始化 sqlite 时区缓存（`yfinance/cache.py:148 initialise` → `db.connect()`）。`get_verified_market_snapshot` 赢了竞态（返回 1975 字符），`get_stock_data` 失败，随后 `ToolNode._handle_tool_error` 把异常重新抛出，**整个 run 终止**。

这正好落在第二节指出的架构裂缝上：`get_verified_market_snapshot` 绕过 `route_to_vendor`，所以它与 vendor 路由的调用之间**不共享任何串行化**。

隔离复现结果（说明是时序敏感竞态，非必现）：

- 8 路并行 `get_indicators`，冷启动 ×3 → 3/3 全过
- `get_stock_data` ∥ `get_verified_market_snapshot`，冷启动 ×5 → 5/5 全过
- 真实图负载下 ×4 → 1 次失败

**对基准的影响**：约 25% 的运行会因此产生伪失败，且失败表现为 run 整体崩溃而非降级。接入前需要处理 —— 候选做法是在容器启动时单线程预热一次 yfinance 缓存，或在 `load_ohlcv` / `route_to_vendor` 外面加一把进程内锁。两者都不需要改上游源码。

---

## 九、需要先验证的未知项

以下是本次静态分析没能确认、建议实跑一次小规模 case 验证的：

1. `langchain/langgraph` 版本对 `on_tool_end` 是否给出原始字符串返回体（版本敏感）。
2. yfinance 在本机网络下的可达性与限流（历史上出现过 Yahoo 侧 429）。
3. `openai_compatible` 客户端是否把 `callbacks` 正确透传（`openai_client.py:168` 的 kwargs 白名单里有 `callbacks`，看起来可以，但没实跑）。
4. KUMA `submit(output)` 的实际体积上限 —— SDK 侧无显式常量，可能在服务端。`logs` 通道的上限是明确的（总计 20 MB），所以大体量走 logs 更可控。
5. ~~敏感信息扫描器对金融文本的误报率~~ —— **已排除**。`privacy.py:29-48` 只匹配 7 类具体凭证特征，普通金融文本不触发（见 6.2）。
