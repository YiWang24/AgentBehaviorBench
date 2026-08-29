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

**关键结构**：除 `get_verified_market_snapshot` 外，所有工具体都是一行 —— `return route_to_vendor("<method>", *args)`（见 `agents/utils/core_stock_tools.py` 等）。也就是说：

> **所有外部数据出口收敛到 `tradingagents/dataflows/interface.py:route_to_vendor()` 这一个函数。**

这是整个方案里最有价值的一点：屏蔽付费 vendor、注入确定性 mock、录制/回放，全都只需要在这一个点上做，而且不用碰工具定义 —— agent 的**原生工具调用行为完全保留**（LLM 照样自己决定调哪个工具、传什么参数）。

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

**这就是你感觉到的落差**。展开说：

> 你要「抓到所有中间数据来优化 KUMA 内部逻辑」，但 KUMA 的 Evidence 通道按契约只会拿到**骨架**（走了哪些节点、什么模型、耗时、token 数）。四份分析师报告、多空辩论全文、12 个工具的原始返回体 —— 这些是判断 agent 行为对错的核心，却**进不了 Trace Evidence**。

能进 KUMA 的内容通道只有三个，都有代价：
- `submit(output=...)`：JSON-compatible，是唯一能塞全量内容的地方，但上传前会过敏感信息扫描（`repository/privacy.py`）。
- `submit(logs=[...])`：从显式指定的文件读增量，同样过扫描。
- `upload_diff=True`：文件文本 diff。

**所以架构上必须双平面**，不能指望 KUMA 一条通道解决：

- **平面 1（KUMA 契约面）**：`submit(output)` 提交结构化结论 + OTel trace 提交骨架 → 这是 KUMA 官方评判的输入。
- **平面 2（本地全保真面）**：callback handler 写 JSONL 到挂载卷 → 这是你分析、回归、优化 KUMA 内部逻辑的语料。
- 两面用 KUMA `run_id` + input index 关联。

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

## 九、需要先验证的未知项

以下是本次静态分析没能确认、建议实跑一次小规模 case 验证的：

1. `langchain/langgraph` 版本对 `on_tool_end` 是否给出原始字符串返回体（版本敏感）。
2. yfinance 在本机网络下的可达性与限流（历史上出现过 Yahoo 侧 429）。
3. `openai_compatible` 客户端是否把 `callbacks` 正确透传（`openai_client.py:168` 的 kwargs 白名单里有 `callbacks`，看起来可以，但没实跑）。
4. KUMA `submit(output)` 的实际体积上限 —— 源码里没有找到显式常量，可能在服务端。
5. 敏感信息扫描器对金融文本的误报率（ticker、数字串是否会被判定为敏感）。
