# KUMA SDK 实测缺陷（用 06 TradingAgents 的 10 条自定义 case 触发）

SDK 版本：`/home/wy/projects/DefuzeX/KUMA-DefuzeX` 本地源码（`kuma-defuzex`，pip 安装进容器）。
运行方式：第一~三节为完全本地（自定义 Case Provider + 自定义 Judge Provider），不使用 API key、不上传任何数据。
第四节为官方 API 链路实测，会向 `defuzex.ai` 上传运行证据 —— 上传内容见该节。

---

## 一、如何传入自定义 case（先把机制说清）

```
create_run(case_provider=<provider>, max_inputs=N, ...)
  → adapt_case_provider()                  providers/base.py:116
      · 已实现 CaseProvider 协议（有 generate_case）→ 原样透传
      · 只是个 callable → 包成 CallableCaseProvider
  → provider.generate_case(CaseGenerationContext)
  → normalize_case()                       providers/normalization.py:244
```

**Case 可以返回三种形状**（`_case_parts`，normalization.py:115）：

1. 一个 `Case` 对象
2. 一个含 `"inputs"` 键的 Mapping，另可带 `case_id` / `input_type` / `input_schema` / `rubric` / `extensions`；**不认识的键会被折进 extensions**
3. 一个裸序列，直接当作 inputs

**每个 input 可以是三种形状**（`_input_parts`，normalization.py:70）：

1. `KumaInput` 对象
2. 裸字符串 → `payload_type="text"`
3. 含 `"payload"` + `"payload_type"` 的 Mapping，另可带 `input_id` / `public_constraints` / `extensions`

**禁止字段**：`PRIVATE_DATA_FIELDS`（`answer_key`、`expected_answer`、`hidden_answer`、`hidden_inputs`、`internal_labels`、`private_rubric`、`system_prompt`、`model_config`、`provider_key`、`mcp_url` 等）在 Case 里任何位置都会被拒 —— **唯独 `rubric` 子树豁免**（normalization.py:132 把 `rubric` 排除在嵌套扫描之外）。所以评分标准要放进 `rubric`。

本项目的实现见 `kuma_cases.py`。

---

## 二、缺陷 1：requirement 声明的 input schema 一律无法通过校验

**严重度：阻断。** `## Input Schema` 这个特性目前完全不可用。

### 复现

任意一个合法 JSON Schema 写进 requirement 的 `## Input Schema` 章节，然后 `create_run(requirement_path=...)`：

```
kuma.errors.ProviderError: Case Provider returned an invalid input_schema
```

### 根因

`parse_requirement()` 把解析出的 schema 经 `_freeze_json` 冻结 —— Mapping 变成 `MappingProxyType`，数组变成 `tuple`。随后 `normalize_case` → `_resolved_input_schema`（normalization.py:170-189）对这个**冻结后**的对象调 `validate_schema`，其内部走 jsonschema 的 `check_schema`。

jsonschema 的默认类型检查器：`"object"` 只接受 `dict`，`"array"` 只接受 `list`。`mappingproxy` 不是 `dict`，`tuple` 不是 `list`，于是元 schema 校验必然失败。

### 实测定位

```
plain dict, no arrays        OK
mappingproxy, no arrays      REJECTED     ← 冻结 Mapping 单独就足以失败
plain dict + items array     OK
required (list)              OK
required (tuple)             REJECTED     ← 冻结数组是叠加因素
enum (tuple)                 REJECTED
type union (tuple)           REJECTED
```

`mappingproxy` 那条是无条件的：**任何**声明的 schema 都过不去，跟里面有没有数组无关。

### 连带后果：structured 输入走 requirement 路径是死锁

`requirements.py:282` 规定 `input_type: structured` **必须**声明 input schema：

```
kuma.errors.ValidationError: Structured requirements must declare an input schema
```

于是形成闭环：

- 不写 `## Input Schema` → 被 `requirements.py:282` 拒（structured 必须声明）
- 写了 `## Input Schema` → 被 `_resolved_input_schema` 拒（冻结对象过不了 jsonschema）

**结论：`input_type: structured` 配合 requirement 文件的路径当前完全走不通。**

### 报错信息误导

两种情况都抛 `"Case Provider returned an invalid input_schema"`，但 schema 其实来自 **requirement 文件**，不是 Case Provider。按这条信息去查自己的 provider 会查错方向。

### 修复方向

在 `validate_schema` 之前把结构还原成 `dict` / `list` 再交给 jsonschema（校验完再冻结），或给 jsonschema 传一个把 `Mapping`/`Sequence` 也算进 `object`/`array` 的自定义 `TypeChecker`。

### 当前绕法

改用类式 Provider 并声明 `requirement_required = False`，然后 `requirement_path=None`：

```python
class TradingAgentsCaseProvider:
    requirement_required = False
    def generate_case(self, context):
        return {...}
```

`adapt_case_provider` 对已实现 `generate_case` 的对象原样透传，`api.py:404` 的 `getattr(provider, "requirement_required", True)` 就读到 False。代价是拿不到 requirement 文本。

---

## 三、观察：payload 会被深度冻结，agent 侧要有心理准备

`_freeze_json` 同样作用于 input payload。实测投递结果：

```
{'ticker': 'AAPL', 'date': '2026-08-20', 'analysts': ('market',)}
                                                     ^^^^^^^^^^^ 原本是 list
```

不是 bug（契约写明会递归冻结防止 Provider 篡改历史），但**接收侧不能假设拿到的是 `list`**。任何 `isinstance(x, list)` 判断都会在这里失效。

---

## 四、官方 API 链路实测（`https://defuzex.ai/api/agentdefuze`）

鉴权正常。`GET /sdk/entitlements/` 返回 scopes `cases:generate` / `sdk:read` / `judge:run`，额度充足，且 `protocol.casegen_frameworks = ["defuzex.casegen.ita.v1"]`。
注意 SDK 读的环境变量是 **`KUMA_API_KEY`**，不是 `DEFUZEX_API_KEY`。

本次消耗：casegen 7 → 9，judge 6 → 7，credits 99,987 → 99,984。

### 缺陷 2：`max_inputs` 是客户端拒绝阈值，不是请求参数 —— 且失败仍扣费

`official_case.py:263` 的请求体里 `"count": 1` 是**硬编码**的，`max_inputs` 从不进入请求。后端自行决定生成几步，SDK 拿到响应后才用 `_official_inputs`（official_case.py:42-47）做区间校验：

```python
if not isinstance(steps, list) or not 1 <= len(steps) <= max_inputs:
    raise ProviderError("The Backend returned an invalid number of Case steps")
```

实测：`max_inputs=3` → 后端返回 6 步 → 报 "The Backend returned an invalid number of Case steps"。
`max_inputs=20` → 同样 6 步 → 通过。

**校验发生在付费调用之后**，实测这次失败仍然使 `casegen_used` +1。调用方无法预知后端会返回几步，只能把 `max_inputs` 猜得足够大，否则白花额度。

修复方向：把期望步数放进请求体，或在步数超限时不计费/可重试。

### 缺陷 3：官方 Case 生成忽略领域 requirement

用 `requirement-text.md`（`input_type: text`，agent_description 明确写了"分析某标的在某交易日并给出交易决策"，Behaviors to Test 五条全是交易语义）调官方 casegen，返回的 6 步是：

```
step-1  Inspect the repository structure and read the requirement documents ...
step-2  Run the existing test suite or checks ... and record the output ...
step-3  Based on the observed test failures ... identify the relevant production code files ...
step-4  Make the smallest necessary change to the production code ...
step-5  Rerun the test suite ... confirm previously failing tests now pass ...
step-6  Report the change made, including the file(s) modified ...
```

这是一套**通用的代码修复 SWE 流程**，与 TradingAgents 毫无关系，agent 根本无法执行。当前 `defuzex.casegen.ita.v1` 策略显然是针对 code-fixing agent 调的，领域型 agent（交易、检索、客服）拿不到可用的 case。

**结论：官方 Case 生成目前不适用于本项目的 agent，必须自带 Case Provider。**

### 缺陷 4（最严重）：官方 Judge 收不到任何文本内容，全部判 `insufficient_evidence`

自定义 Case + **官方 Judge** 跑 3 条（pos-01 / neg-06 / neg-09），agent 侧全部正常执行并 `submit(output=..., logs=[sink])`。官方 Judge 返回：

```
status=insufficient_evidence  confidence=high
step_results: pos-01 → insufficient_evidence
              neg-06 → insufficient_evidence
              neg-09 → insufficient_evidence
```

issue 原文：

> Runtime evidence for pos-01-us-largecap (... artifact_id log-segment-0, sha256 5cd38b0d...) **provides only an artifact snapshot with no text content**; the agent_response_claim 'completed' does not reveal polarity. Cannot verify that the response is positive as required by public_constraints.polarity.

根因在 `_official_evidence_upload.py:206-217`：

```python
runtime_parts, runtime_manifest, findings = _runtime_evidence_parts(...)
if runtime_parts:
    return _typed_upload(runtime_parts, runtime_manifest, findings, config)
return _legacy_upload(context, config, part_prefix)
```

两条上传路径**承载能力完全不同**：

| 路径 | 内容 | 触发条件 |
|---|---|---|
| `_legacy_upload`（`defuzex.run_evidence.v1`） | `history_evidence(context)` —— **含 submission output 正文** | 仅当 `runtime_parts` 为空 |
| `_typed_upload`（`defuzex.runtime_evidence.v1`） | 仅 hash-only 的 component 信封 | 只要 `runtime_parts` 非空 |

而 runtime evidence 信封**总会**至少发出一个 `agent_response_claim`（见 `docs/runtime-evidence.md:64-68`），所以 `runtime_parts` 永远非空 —— **一旦后端在 `evidence_types` 里广告了 `defuzex.runtime_evidence.v1`，typed 路径就无条件胜出，legacy 的正文永远发不出去。**

实测后端 `GET /sdk/judge/config/` 返回：

```
evidence_types: ['raw_log', 'defuzex_file_changes_v1', 'defuzex.runtime_evidence.v1']
max_files: 10 | max_file_bytes: 120000 | max_total_bytes: 1200000
```

`raw_log` 明明也在支持列表里，但 `evidence_upload` 没有任何选择逻辑去用它。

**后果：只要后端支持 runtime_evidence v1，官方 Judge 就结构性地看不到 agent 的任何输出，只能判 `insufficient_evidence`。** 官方评判链路当前不可用。

这也澄清了一个此前反复的判断：`submit(logs=[...])` 在 **SDK 内部**确实持有完整正文（`tracking/logs.py:220`），但**传到官方 Judge 的**是 hash-only 信封。两句都对，但决定评判结果的是后者。

修复方向：typed 与 legacy 并存上传（typed 做完整性锚点，raw_log 提供正文），或让 runtime evidence 支持带正文的 component。
