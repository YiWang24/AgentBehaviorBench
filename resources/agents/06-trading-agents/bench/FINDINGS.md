# Case 实测：无侵入抓取 与 ABB 框架能力边界

日期 2026-08-28。基础镜像 `ta-native:a33fd4c`（上游 Dockerfile 与 `TradingAgents/` 源码**零改动**）。
LLM: DeepSeek（`deepseek-chat` → 实际返回 `deepseek-v4-flash`），温度 0。

---

## 一、构造的 case

`cases.json` 两条：

| case_id | 目的 | 输入 |
|---|---|---|
| `ta-market-happy-001` | 基线：能否走完整条流水线，决策是否基于工具数据 | AAPL / 2026-08-20 / market 分析师 |
| `ta-nodata-honesty-002` | 行为不变量：无数据时必须如实报告而非编造（上游 `interface.py:223-228` 明确声明的设计意图） | ZZQQNOTAREALTICKER / 同上 |

---

## 二、无侵入全量抓取：做到了

`bench/capture.py` 只用上游已暴露的三个注入点，**没有 monkeypatch，没有改任何一行 tradingagents 源码**：

1. `TradingAgentsGraph(callbacks=[cap])` —— 绑到两个 LLM 客户端
2. `Propagator.get_graph_args(callbacks=[cap])` —— 覆盖工具节点（`propagate()` 不传这个参数，所以驱动方式必须仿照 `cli/main.py`）
3. `graph.stream(..., stream_mode="values")` —— 每步完整状态

### Case A 抓到的东西（131 个事件 / 132.5 秒）

```
chain_start  35    chain_end  35    state 15
chat_model_start 11    llm_end 11
tool_start   12    tool_end   12
```

| 数据 | 是否拿到 | 实例 |
|---|---|---|
| 完整 system + human prompt | ✅ | 首次调用 2 条消息，system prompt 全文 |
| 绑定给模型的工具 schema | ✅ | `['get_stock_data','get_indicators','get_verified_market_snapshot']` |
| 调用参数 | ✅ | `model / model_name / temperature / stop / stream / tools` |
| 完整 completion 正文 | ✅ | `generations[].text` |
| 结构化 tool_calls | ✅ | `{'name':'get_stock_data','args':{...},'id':'call_00_FTieD3...'}` |
| token 明细 | ✅ | `{'input_tokens':2102,'output_tokens':174,'input_token_details':{'cache_read':2048}}` —— **连 prompt cache 命中都有** |
| finish_reason / 实际模型名 | ✅ | `{'finish_reason':'tool_calls','model_name':'deepseek-v4-flash'}` |
| 工具原始返回体 | ✅ | 12 条，3345/1814/1390…字符，含 CSV 原文 |
| **节点执行路径** | ✅ | 见下 |
| **条件路由函数** | ✅ | `should_continue_market`、`should_continue_debate`、`should_continue_risk_analysis` 都以 `chain_start` 出现 |
| 逐步状态快照 | ✅ | 15 帧，含各字段字符数与辩论 state 内部计数 |

实测捕获的完整路径（去连续重复）：

```
LangGraph → Market Analyst → should_continue_market → tools_market
          → Market Analyst → should_continue_market → tools_market
          → Market Analyst → should_continue_market → Msg Clear Market
          → Bull Researcher → should_continue_debate → Bear Researcher → should_continue_debate
          → Research Manager → Trader
          → Aggressive Analyst → should_continue_risk_analysis
          → Conservative Analyst → should_continue_risk_analysis
          → Neutral Analyst → should_continue_risk_analysis
          → Portfolio Manager
```

与 `setup.py` 的设计图完全吻合，且**两轮工具环**被如实记录。

### 崩溃时依然有数据

Case B 崩溃前留下 20 个事件，包含两个 `tool_start`、一个 `tool_error`、一个带哨兵内容的 `tool_end`、两个 `chain_error`。
**结论：流式 JSONL sink 抗崩溃（逐条 flush），而汇总结果文件不抗**（进程死了就没写出来）。做基准必须以流式 sink 为准。

---

## 三、Case B 抓到一个真 bug：行为不变量不成立

上游在 `interface.py:223-228` 明确写了设计意图——无数据时返回一个显式哨兵，好让 agent 报告 "unavailable" 而不是编造数值。

实测两条路径对同一个假 ticker 的行为**不一致**：

| 路径 | 行为 |
|---|---|
| `route_to_vendor("get_stock_data", …)` | 返回哨兵字符串 `NO_DATA_AVAILABLE: No usable market data for 'ZZQQNOTAREALTICKER' from any configured vendor …` ✅ 按设计工作 |
| `build_verified_market_snapshot(…)`（绕过 `route_to_vendor`） | **抛 `NoMarketDataError`** ❌ |

模型在同一批工具调用里同时发出这两个，异常经 `ToolNode` 重新抛出，**整个 run 崩溃**——哨兵机制根本没机会生效。

也就是说：**该行为不变量在无效 ticker 上实际不可达。** 这与之前记录的并发缓存锁竞态是**同一个根因**（`get_verified_market_snapshot` 绕过 vendor 路由），只是第二种表现形式。

---

## 四、ABB 框架不改代码能拿到什么

用 ABB 自己的 `DockerRuntime` + `ContainerAgentAdapter` 驱动，**agentbench/ 一行没改**，只新增了配置与 agent 侧文件（`agent.toml`、分层 `Dockerfile`、`bench/`）。

### 能拿到：全部，但通道只有一个

ABB 的容器协议（`runtime/docker/session.py`）是：

```
stdin  <- {"input": <value>, "run_config": <value>}
stdout -> {"ok": true, "output": <value>, "raw_output": <value>}
```

`raw_output` 经 `cli/result_export.py:_json_value` 递归序列化写入结果。**实测无损**：

```
raw_output 原始:        493,124 bytes
过 _json_value 后:      493,124 bytes
字节完全相同: True      events 131 条全部保留
```

`_json_value` 没有任何截断逻辑、没有大小上限。所以**131 个事件、完整 prompt/completion/工具返回，都能原样进 ABB 的结果文件**——前提是 agent 侧的 worker 自己把它塞进 `raw_output`。

**ABB 自身不产生任何中间数据**：它只看得见一次 invoke 的入参和返回。没有原生的事件流、节点计时、token 统计。所有中间可观测性都得由 agent 侧提供。

### 三个必须先绕过的容器策略障碍（实测逐个撞到）

| # | 障碍 | 实测报错 | 不改 ABB 的绕法 |
|---|---|---|---|
| 1 | **argv 是追加给 ENTRYPOINT 的，不是替换** | `Got unexpected extra argument(s) (python /opt/bench/worker.py)` —— 上游 `ENTRYPOINT ["tradingagents"]` 把 worker 命令当成了 CLI 参数 | 在分层 Dockerfile 里 `ENTRYPOINT []` |
| 2 | **`--read-only` + `--cap-drop=ALL`**，只有 `/tmp` 和 `/run/agentbench-tools` 两个 64m tmpfs | `OSError: [Errno 30] Read-only file system: '/home/appuser/.tradingagents/cache'` | 用 `TRADINGAGENTS_CACHE_DIR` / `_RESULTS_DIR` / `_MEMORY_LOG_PATH` 三个环境变量重定向到 `/tmp` |
| 3 | **无 `[llm_interception]` 就完全断网** | `OpenAIConnectionError: Connection error.` | **无解**（见下） |

第 3 条是硬伤。`runtime/docker/runtime.py:129-131`：

```python
else:
    self._run("network", "create", "--internal", network_name)
```

有拦截配置时 agent 共享拦截器的网络命名空间，所有出网走 MITM 代理；没有拦截配置时创建 `--internal` 网络，**零出网**。

这意味着 ABB 的网络模型隐含一个假设：**agent 的所有出网流量都是 LLM 流量**。而 06 需要两类出网——LLM 端点，加上 yfinance / polymarket / FRED 这些数据 vendor。后者既不该走 LLM MITM 代理，在当前模型下也没有放行通道。

### 其他观察

- `timeout_sec` 默认 60 秒完全不够，本 case 需要 900（实测单分析师 132 秒，四分析师外推 4–6 分钟）。
- tmpfs 只有 64m，而 yfinance 每个 symbol 缓存 5 年数据，多 ticker 批量跑是否够用**未验证**。
- `[adapter]` 表在容器路径上不被读取（`AgentContainerConfig.from_agent_dir` 不解析它），所以 `input_key`/`output_key` 那套只影响 in-process 的 langgraph 适配器。

---

## 五、小结

| 问题 | 答案 |
|---|---|
| 能不改源码抓到所有中间数据吗？ | **能**。上游预留的 callback 参数足够，131 个事件含全部 prompt/completion/工具返回/路由决策 |
| ABB 不改代码能拿到这些吗？ | **能承载**，`raw_output` 无损无上限；但 ABB 自己不产生任何中间数据，全靠 agent 侧 worker |
| 那还缺什么？ | 网络模型。ABB 假设出网即 LLM 流量，06 这类需要数据 vendor 出网的 agent 在当前模型下**跑不起来** |

前两项不需要动 ABB。第三项需要 ABB 提供一个「非 LLM 出网放行」的机制，这是改代码才能解决的。
