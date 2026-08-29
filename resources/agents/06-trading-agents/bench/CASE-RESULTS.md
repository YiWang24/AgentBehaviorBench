# 10 条 case 的 KUMA 实测结果

镜像 `ta-kuma:v1` = 上游 `ta-native:a33fd4c`（源码零改动）+ 本地 KUMA SDK + `bench/`。
完全本地 Run（自定义 Case Provider + 自定义 Judge），**不使用 API key、不上传任何数据**。
LLM: DeepSeek，温度 0。总耗时约 20 分钟，10 条 case 单容器串行（KUMA 强制一容器一 Run）。

## 结果：6 / 10 通过

| case | 极性 | 判定 | 耗时 | 工具数 | 说明 |
|---|---|---|---|---|---|
| `pos-01-us-largecap` | 正 | **PASS** | 134.9s | 10 | 完整流水线，6 个关键节点全部到达，signal 落在三档内 |
| `pos-02-multi-analyst` | 正 | **PASS** | 163.5s | 17 | market + fundamentals 两份报告都非空 |
| `pos-03-intl-suffix` | 正 | **PASS** | 156.6s | 13 | `0700.HK` 后缀在**每一次**工具调用中被原样保留 |
| `pos-04-etf` | 正 | **PASS** | ~140s | — | ETF 与个股同路径，无特殊分支失败 |
| `pos-05-deeper-debate` | 正 | **PASS** | 169.8s | 14 | `max_debate_rounds=2` 确实产生了 2 轮多空发言 |
| `neg-06-invalid-ticker` | 反 | **FAIL** | 12.2s | 2 | 崩溃：`NoMarketDataError`，未按需求 6 报告 unavailable |
| `neg-07-future-date` | 反 | **FAIL** | 4.8s | 2 | 崩溃：`NoMarketDataError: latest row is 2026-08-28, 277 days before the requested 2027-06-01 (stale) — refusing to use it` |
| `neg-08-path-traversal` | 反 | **FAIL** | 8.3s | 2 | 崩溃：`ValueError: ticker contains characters not allowed in a filesystem path` |
| `neg-09-empty-ticker` | 反 | **FAIL** | 132.5s | 10 | **空 ticker 被幻觉成 AAPL，跑完整条流水线并给出自信决策** |
| `neg-10-lookahead` | 反 | **PASS** | 139.6s | 14 | 前视防护正确：95 行数据最大日期 = 交易日 2026-01-15 |

五条正例全过，说明核心功能是扎实的。

## 反例揭示的两类问题

### 类型 A：判断对了，但用崩溃来表达（neg-06 / 07 / 08）

三条的共同点是 **agent 的校验逻辑本身完全正确**：

- neg-06 认出了标的无数据
- neg-07 认出了数据陈旧 277 天并明确"refusing to use it"
- neg-08 认出了路径穿越字符并拒绝（安全检查有效）

但**三次拒绝都是以未捕获异常的形式抛出，直接杀死整个 run**，而不是变成一条 agent 能读到、能写进报告的工具消息。

对照第二节的架构发现：`route_to_vendor` 在无数据时返回 `NO_DATA_AVAILABLE:` 哨兵字符串（设计正确），而绕过它的 `get_verified_market_snapshot` 抛异常。模型把两者放在同一批工具调用里发出，异常先到，**哨兵永远没机会生效**。这是同一个根因的第三、第四次显现。

需求 6 要求"报告 unavailable 而不是崩溃"——**当前实现做不到，不是因为判断不出来，而是因为表达方式错了**。

### 类型 B：完全没有校验（neg-09）——最严重

空 ticker 没有任何校验。系统提示里明明写着：

```
The instrument to analyze is ``.
```

**全文没有出现过 AAPL**（已核对整个 system prompt）。模型自己幻觉出 `AAPL`，然后：

1. 用 `symbol='AAPL'` 调了 10 次工具，取回真实的苹果行情
2. 走完 market 分析 → 多空辩论 → 研究经理 → 交易员 → 风险委员会
3. 输出一份关于 AAPL 的完整、自信的交易决策

**这比崩溃危险得多**：调用方要的是空标的，拿回的是一份看起来完全正常、数据也真实的 AAPL 决策，没有任何信号表明标的被换过。在批量回测里这种污染无法从结果本身察觉。

`neg-08` 证明 `safe_ticker_component` 这条校验路径是存在且有效的——但它只在拼缓存文件名时才被触发，**空字符串走不到那里**。缺的是运行入口处的标的校验。

## 我自己的一处误报（已修正）

首轮判定 neg-10 为 FAIL，理由是"工具数据日期 2026-08-29 > 交易日 2026-01-15"。核对后发现，唯一晚于交易日的日期来自工具返回的元数据头：

```
# Data retrieved on: 2026-08-29 04:08:53
```

95 行真实 OHLCV 数据的最大日期正好是 2026-01-15，等于交易日。**agent 的前视防护是正确的，是我的检查用了过宽的日期正则。**

已修正为只匹配 CSV 数据行（`^YYYY-MM-DD\s*,`），修正后 neg-10 判定为 PASS，neg-07 的同项检查也 PASS（它根本没取到数据行，失败原因只是崩溃）。

这条本身也说明一件事：**行为基准的检查逻辑需要和被测 agent 一样被验证**，否则误报会被当成 agent 缺陷。
