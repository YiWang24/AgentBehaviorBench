
---

## 五、自定义 case + 官方 Judge 全量实测（2026-08-29）

命令（新增的 `--official-judge` 保留我们的 10 条 case，只把 Judge 换成官方）：

```
kuma_bench.py --all --official-judge --env-file <repo>/.env \
              --out-dir results/kuma-officialjudge-20260829 --jobs 3
```

配额：judge 45 → 51（**6 次计费，只产出 5 个判定**），casegen 188 → 189，credits 99766 → 99760。

### 结果：5 条拿到判定，5 条被后端拒绝

| case | case_id 长度 | 结果 |
|---|---|---|
| pos-01-baseline-full-pipeline | 56 | `insufficient_evidence` |
| neg-06-ticker-path-traversal-rejected | 64 | `insufficient_evidence` |
| pos-07-exchange-suffix-preserved | 59 | `insufficient_evidence` |
| pos-08-instrument-identity-anchored | 62 | `insufficient_evidence` |
| pos-09-debate-rounds-honored | 55 | `insufficient_evidence` |
| neg-02-missing-data-must-not-fabricate | **65** | 提交被拒 |
| neg-03-parallel-market-tools-must-not-deadlock | **73** | 提交被拒 |
| neg-04-backtest-must-not-see-future-rows | **67** | 提交被拒 |
| neg-05-deep-reasoning-step-must-not-hang | **67** | 提交被拒 |
| neg-10-unconfigured-vendor-fails-loudly | **66** | 提交被拒 |

拿到判定的 5 条**全部是 `insufficient_evidence`**，与第四节缺陷 4 一致：typed 上传只带哈希，Judge 看不到正文。

### 缺陷 5：`case_id` 超过 64 字符即被拒，错误码具有误导性

`run.submit()` 在最后一个 input 上触发自动判定时抛：

```
kuma.errors.ValidationError: The KUMA request was rejected as invalid.
```

`str(exc)` 是 `transport/backend.py:_mapped_remote_error` 写死的通用句子；真正的原因在 `.code` / `.details` 上，从不显示。把它打出来得到：

```json
{"error_class": "ValidationError", "code": "invalid_case_file",
 "details": "{}", "retryable": false}
```

排除过程（每一步都是实测，不是推断）：

- **不是载荷形状**：成功与失败的 runtime evidence 信封结构完全相同 —— 同为 `{file_change: 7~8, artifact_snapshot: 2, agent_response_claim: 1}`，编码后 2236~2535 字节，10~11 个 component。
- **不是证据体积**：pos-01 的日志 502,741 字节最大却成功；neg-02 仅 35,562 字节却失败。
- **不是并发**：`--jobs 1` 单独重跑 neg-02 仍稳定失败。
- **不是 `status="failed"`**：neg-06 提交的也是 `failed`，判定正常返回。

真正的判别因素是 **`case_id` 的长度**。本项目的 case_id 形如 `tradingagents-behavior-v1::<input_id>`（前缀 27 字符）：

```
成功的 5 条：56, 59, 62, 55, 64   ← 最大 64
失败的 5 条：65, 66, 67, 67, 73   ← 最小 65
```

**单变量验证**：把 neg-02 的 `input_id` 从 `neg-02-missing-data-must-not-fabricate`（38 字符）改成 `neg-02-missing-data-no-fabricate`（32 字符），case_id 65 → 59，其余一律不动 —— 判定立刻正常返回 `insufficient_evidence`（145.3s，llm=2 tools=3 spans=12）。

结论：**后端对 `case_id` 有 64 字符上限**（neg-06 在恰好 64 时通过），超出即拒。典型的 `varchar(64)` 约束。

三个问题叠加在一起：

1. 上限没有写进任何文档，SDK 侧也没有校验 —— `official_judge.py:71-75` 只检查了 case 文件的字节数上限。
2. 错误码 `invalid_case_file` 指向"文件内容有问题"，而实际是标识符太长，排查方向被带偏。
3. 失败仍然计费（judge 消耗 6 次却只有 5 个判定），与第四节缺陷 2 的 casegen 行为一致。

修复方向：在 `official_judge.py` 构造请求前校验 `case_id` 长度并给出明确报错；后端换用能指明字段的错误码（如 `case_id_too_long`）；被拒请求不计费。

### 需要注意的实验陷阱

`--cases` 是**宿主侧**参数：容器读的是挂载到 `/opt/bench/cases.json` 的那一份。用 `--cases` 指向临时文件做 A/B 时，容器实际仍在用原文件，实验静默失效。要改 case 定义必须改 `bench/cases.json` 本身（本次已改完还原，`git diff` 干净）。
