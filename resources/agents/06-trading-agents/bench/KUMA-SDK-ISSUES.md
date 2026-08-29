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

---

## 五、自定义 Judge Provider 实测（`kuma_judge.py` / `judge_contract_probe.py` / `envelope_probe.py`）

用类式 `RubricJudge` 重跑了官方 Judge 那次的**同样 3 条 case**（pos-01 / neg-06 / neg-09），
构成严格对照。判定 1/3 通过，与本地基线一致；同样 3 条走官方 Judge 是 3/3
`insufficient_evidence`。差别只在证据通道。

### SDK 做对的地方

- `adapt_judge_provider` 对任何带 `.judge()` 的对象原样透传（`providers/base.py:129`），
  不套 `CallableJudgeProvider`。类式 Provider 是一等公民。
- **rubric 完整穿过 Case → Run → JudgeContext**。这一轮故意不用模块全局变量，
  改从 `context.case.rubric` 读回评分标准（报告 `extensions.rubric_source = "case.rubric"`），
  三条 input_id 齐全。`rubric` 是 `normalize_case` 唯一豁免私有数据扫描的子树，
  它是自定义 Judge 传递判分标准的正确通道，且确实可用。
- `normalize_report` 这道门很扎实：30 条探针 20 条正确拒绝，覆盖私有数据扫描、
  JSON 可序列化、run_id 绑定、confidence 值域、status 枚举。

### 缺陷 5：SDK 冻结 Mapping，`isinstance(x, dict)` 静默失效

`Submission.output` 的实际类型是 **`mappingproxy`**，`extensions` 同理。
按直觉写 `isinstance(value, dict)` 的消费者会静默拿到空结果——**不抛异常、不告警**。
本文件第一版探针就踩了两次：`output_text_chars` 报 0、信封报 `present: False`，
而实际数据是满的。改用 `collections.abc.Mapping` 后立刻正常。

这与第二节的阻断级缺陷是**同一个根因**：jsonschema 的 `"object"` 类型检查只认 `dict`，
所以每一份冻结后的 input schema 都被拒。区别在于那次是 SDK 内部撞上，
这次是 Provider 作者从外部撞上——**它不只是内部 bug，是 SDK 强加给每个
Provider 实现者的契约陷阱**，而文档未声明返回的是 mappingproxy。

### 缺陷 6：Judge 返回值的 issue 结构完全不校验

`issues=[{"detail": "x"}]` 直接通过。官方 Judge 的 issue 带
`issue_id`/`severity`/`message`，自定义 Judge 可返回任意字典。
消费 `TestReport.issues` 的代码拿不到稳定形状。

### 缺陷 7：七种不同错误塌成同一句话

`status='banana'`、`status=42`、`confidence='banana'`、`confidence=1.5`、
`issues=[bare string]`、`issues=[42]`、`status='passed'` —— 全部报
`Judge Provider returned an invalid TestReport`，不指出是哪个字段。
与第二节 "invalid input_schema" 指错方向属同一类 DX 问题。

附带一处不一致：`_official_judgment.py:71` 的白名单收 `"passed"`，
而 `TestReport.__post_init__` 只收 `"pass"`。官方路径能过的拼写，自定义路径过不了。

### 缺陷 4 的最小复现（`envelope_probe.py`，一秒，无 agent、无网络）

`build_runtime_evidence` 是纯函数。喂给它一个**携带真实正文**的 log 段
（`content` 字段，与 SDK 自己放进 `Submission.logs` 的形状相同）：

```
输入 log 段:  content 2,000 字符
输入 output:  final_trade_decision 2,000 字符
信封总大小:   693 字符
  component 0  kind=artifact_snapshot     字段: [artifact_id, kind, media_type, sha256, size_bytes]
  component 1  kind=agent_response_claim  字段: [claim, claim_id, kind, text_sha256]
信封中能否找回正文片段 'FINAL TRANSACTION PROPOSAL': False
信封中是否含 sha256 摘要: True
```

**4,000 字符正文进，693 字符纯元数据出。**

### 正文确实握在 SDK 手里——被信封丢掉，不是从未采集

`Submission.logs[i]` 的字段是
`[binary, complete, content, encoding, end_offset, path, segment_no, sha256, start_offset]`
—— **`content` 在提交侧是有的**。三条 case 的实测对照：

| case | 本地 Judge 可读正文 | `submission.logs` 正文 | 官方信封 | 带正文的组件 |
|---|---:|---:|---:|---|
| pos-01-us-largecap | 20,633 | 413,728 | **779** | 无 |
| neg-06-invalid-ticker | 1,024 | 17,048 | **785** | 无 |
| neg-09-empty-ticker | 24,991 | 387,897 | **782** | 无 |

自定义 Judge 能读到 41 万字符；官方路径拿到 779 字符,全是摘要。
这坐实了第四节的判断：**不是判得不准，是根本看不到内容**。

---

## 六、合成数据直打官方 API：官方 SDK 能否正常使用（`official_sdk_probe.py`）

**agent 完全剥离。** 每一条 submission 都是脚本里写死的合成文本，极性刻意做得毫不含糊：
正例是一份完整的分析结论，反例是一句明确的拒绝。Judge 只要能看到任何一点内容，
区分二者都是平凡的。所以这里出现 `insufficient_evidence` 只能是证据通道的性质，
与被测 agent 无关。六个变体各用独立容器（避开 Run 锁）。

| 变体 | 官方 Case | track_files | 改文件 | logs | 提交内容 | 提交状态 | 判定 |
|---|---|---|---|---|---|---|---|
| custom-nofiles | 否 | 否 | 否 | 是 | 正常 | completed | `insufficient_evidence` |
| custom-files | 否 | 是 + upload_diff | **是** | 是 | 正常 | completed | `insufficient_evidence` |
| no-logs | 否 | 否 | 否 | 否 | 正常 | completed | `insufficient_evidence` |
| official-full | **是** | 是 + upload_diff | 是 | 是 | 正常 | completed | **`pass`** |
| official-refuse | **是** | 是 + upload_diff | 是 | 是 | **公开声明未执行** | completed | **`pass`** |
| official-failed | **是** | 是 + upload_diff | 是 | 是 | **公开声明未执行** | **failed** | **`pass`** |

**判定只由一个变量决定：Case 是否来自后端。** 提交的内容、是否改文件、是否带日志、
甚至 submission 状态是 completed 还是 failed，都不改变结果。

### 混合路径（自定义 Case + 官方 Judge）：结构性不可用，但失败得很诚实

三个变体全部 `insufficient_evidence`，后端的措辞逐次更明确：

> contains only artifact metadata (paths, sha256 hashes, sizes) but **no log content**.
> The only response claims are completion statuses, **which are not proof of response text**.

`custom-files` 是关键对照：`track_files=True` + `upload_diff=True` + 真实改了两个文件，
后端仍然说 "the actual text content of pos-answer.md, neg-refuse.md ... is not provided"。
**这推翻了"KUMA 至少对改文件的 agent 可用"的假设** —— file_change 组件同样只有
`path + operation + before/after_sha256`。

`upload_diff=True` 名不副实：`diff.py:139` 产出的 `text_diff` 进的是
`local_diffs`，而 `tracking/evidence.py:262` 只把它写进**本地** record 文件并做敏感扫描，
`PreparedEvidence` 根本不带它。**这个开关不上传任何东西。**

### 完全官方路径：看起来能用，实际是空判——这更危险

`official-refuse` 的每一步提交都是：

> I refused to perform this step. I did not read the requirement, did not run any
> test, and changed nothing on purpose. There is no result here.

判定 `pass`，confidence high，4/4 step `passed`，0 issues。

`official-failed` 更进一步：四步全部 `status="failed"` + `error="step not performed"`。
`official_judge.py:385` 的 `_submission_status` 确实把聚合状态 `"failed"` 发了上去
（它是 metadata 里少数真实传输的字段之一），后端**依然**返回 `pass`。

**在官方 Case 路径上，Judge 的判定与 SDK 送出的任何 submission 信息都无关。**

### 为什么两条路径行为不同

`api.py:64-73`：

```python
can_negotiate = bool(official_case and official_judge and evidence_capabilities)
...
if not can_negotiate:
    evidence_capabilities = ()
```

证据能力协商**要求同时是官方 Case 和官方 Judge**。混合路径下 `official_case=False`，
协商被整个跳过，Case 不声明任何可观测证据种类，后端 Judge 于是回退到要正文——
而 SDK 永远不送正文，死锁。走完全官方路径时协商成立，后端按声明的能力生成 Case，
但它能拿到的仍只有哈希，于是"验证"退化成放行。

**一条失败得很响，一条失败得无声。都不可用。**

### 证据词表里有四种类型无人能声明

`runtime_contract.py:14` 的 `CASEGEN_EVIDENCE_CAPABILITY_ORDER` 有七种：

```
file_change, tool_call, command_result, test_result, state_transition,
artifact_snapshot, agent_response_claim
```

而 `derive_casegen_evidence_capabilities`（同文件 95 行）只可能声明其中三种：
`file_change`（需 track_files）、`artifact_snapshot`（需 trace_evidence）、
`agent_response_claim`。**`tool_call`、`command_result`、`test_result`、
`state_transition` 定义在词表里，但没有任何代码路径能声明或产出它们。**

`tool_call` 恰恰是本项目 trace 抓得最全的一类（10 条 case 共 98 次工具调用，
参数与完整输出俱在）。SDK 有词汇，没有采集与传输的实现。

### 本轮消耗

6 次 Run：casegen 9→12，judge 7→13，credits 99,984→99,975（9 credits）。
上传到 `defuzex.ai` 的全部是本文件内写死的合成文本，不含任何真实数据。

---

## 七、用官方自己的样例测试（`examples/single_agent_template`）

SDK 仓库自带三个示例，其中 `single_agent_template` 是官方的标准模板，
README 有专门一节 "Official Case and Judge"，说明如何用 `KUMA_USE_OFFICIAL=1`
接官方 Case 与官方 Judge。它自带的 `call_your_agent` 是个空桩，只回显输入。

### 本地 quickstart：正常

按 README 跑默认路径，输出与文档逐字一致：

```
run_state=completed
history_items=1
last_submission_status=completed
report=None
result_link=None
```

模板本身没问题。（`report=None` 也不是缺陷：`submit()` 在最后一条输入时会自动触发
judge，而本地路径 `judge=False`。）

### 官方模式：开箱即 `insufficient_evidence`

```
KUMA_USE_OFFICIAL=1  KUMA_API_KEY=…  KUMA_REPO_PATH=/tmp/official-repo
```

```
run_state=report_ready
history_items=4
last_submission_status=completed
status='insufficient_evidence'  confidence='low'
step_results: step-1..4 全部 insufficient_evidence
flags: {'runtime_evidence': False}
```

**官方自己的模板，按官方 README 跑官方模式，用官方 Case 和官方 Judge，
四步全部判不出来。** 这不需要任何自定义代码就能复现。

### 判定的真正决定因素：`submit(logs=...)` 传没传

`flags: {'runtime_evidence': False}` 是新线索。模板与第六节 `official-full` 的
差异有四处，逐一隔离后只剩一个变量：

| 变体 | logs= | 改文件 | 提交内容 | 提交状态 | 判定 |
|---|---|---|---|---|---|
| official-full | **是** | 是 | 正常 | completed | `pass` |
| official-refuse | **是** | 是 | 公开声明未执行 | completed | `pass` |
| official-failed | **是** | 是 | 公开声明未执行 | failed | `pass` |
| official-nofiles | **是** | 否 | 正常 | completed | `pass` |
| official-nologs | **否** | 否 | 正常 | completed | `insufficient_evidence` |
| 官方模板 | **否** | 否 | 空桩回显 | completed | `insufficient_evidence` |

`official-nofiles` 与 `official-nologs` 是严格单变量对照——配置完全相同，
只差 `submit()` 有没有传 `logs=`。前者 pass，后者 insufficient_evidence。

而 `_log_components`（`evidence/runtime.py:137`）只把日志变成
`artifact_snapshot` 的 `sha256 + size_bytes + path`，**内容从不上传**。

**所以官方路径的判定规则实际是：`submit()` 传了任意一个文件给 `logs=` 就 `pass`，
不传就 `insufficient_evidence`。文件里写什么、agent 做了什么、状态是
completed 还是 failed，全都不参与判定。**

我先猜决定因素是"有没有文件改动"，被 `official-nofiles` 证伪；
再隔离到 `logs=`，被 `official-nologs` 证实。两次都是单变量对照。

### 这对第六节结论的修正

第六节说"官方 Case 路径永远 pass"是不准确的——它的四个变体恰好都传了 `logs=`。
准确的说法是：**官方路径的判定与 agent 行为无关，只与是否附带了一个
日志文件有关**。一个什么都不做的 agent，只要 `submit(logs=[任意文件])`，
就能拿到 `pass` + confidence high + 4/4 step passed。

两种失败模式因此是同一个缺陷的两面：
证据信封里除了 `agent_response_claim` 之外一个组件都没有时，后端置
`runtime_evidence: False` 并拒判；有任意一个 `artifact_snapshot` 时就放行，
而它看不到那个 snapshot 的内容。

### 本节消耗

官方模板 1 次 + 隔离实验 2 次。累计 credits 99,984 → 99,969。

---

## 八、自造 Case 直测 Judge —— 这一节推翻了第六、七节的主要结论

Case 形状照抄 SDK 仓库自带示例，requirement 直接用官方
`examples/single_agent_template/requirement.md` 未加改动。六个变体全部走
自定义 Case + 官方 Judge。

| 变体 | Case 来源 / 验收标准 | 判定 | Judge 判对了吗 |
|---|---|---|---|
| `cc-minimal` | `examples/minimal_local.py::local_case` 原样结构，标准宽松（"return a bounded maintenance result"） | `pass` | ✅ 合理 |
| `cc-swe` | 后端 casegen 返回过的六步 SWE 流程，要求"报告哪些测试失败" | `insufficient_evidence` | ✅ 诚实——这确实需要正文 |
| `cc-path-ok` | 标准可由文件路径判定，但我写成了"仓库根目录" | `issue` | ✅ 精确指出观察到的是 `tmp/…/report-1.md` |
| `cc-path-bad` | 同上标准，故意写错文件名 | `issue` | ✅ 列出实际路径，并**额外**报出名单外文件 |
| `cc-path-fixed` | 标准按容器相对路径改写，文件写对 | `pass` | ✅ 3/3 |
| `cc-claim-failed` | 标准要求 claim 为 `completed`，提交全部 `status="failed"` | `issue` | ✅ 引用 component_id 与 submission_id |

### 结论：官方 Judge 是好的

`cc-path-fixed` / `cc-path-bad` / `cc-path-ok` 构成三向对照——同一类标准，
行为正确则 `pass`，文件名写错则 `issue`，标准表述与证据约定不符也能被精确指出。
**只要验收标准能用 SDK 真正送出的证据表达，官方 Judge 就做出正确、具体、
可追溯到 component_id 的端到端验证。** 它在缺证据时诚实报 `insufficient_evidence`，
不猜。

### 前面几节错在哪

- **第六节说"官方 Case 路径永远 pass、是空判"——不成立。** `official-refuse` /
  `official-failed` 之所以通过，是因为后端生成的那些 SWE 标准恰好能被可观测证据
  满足（文件确实变了），而破坏只发生在**正文**里，那正是不可见的通道。
  不是盖章，是"能看见的部分确实一致"。
- **第七节说"判定只取决于 `logs=` 传没传"——是过度归纳。** 那个单变量对照本身没错，
  但它成立的前提是那批 case 的标准都需要正文；证据信封里连一个
  `artifact_snapshot` 都没有时后端置 `runtime_evidence: False` 拒判，
  有了就退回到"能看见的部分"判。换一组标准（本节）结论完全不同。
- **`official-failed` 全 `failed` 却 pass，也不是 Judge 忽略状态。**
  `cc-claim-failed` 证明：只要 case 标准提到 claim，Judge 会准确抓出
  `blocked` 并判 issue。前者通过只是因为后端那份 case 的标准没提 claim。

我先猜是"文件改动"，被 `official-nofiles` 证伪；再猜是 `logs=`，
被本节证伪。两次都是我把一组特定 case 的行为当成了通用规则。

### 剩下的、唯一成立的核心缺陷

**SDK 从不送出 response 正文与日志内容。** 因此凡是关于"agent 说了什么"的
验收标准都结构性不可验证。能用文件路径、文件操作、claim 状态表达的标准
全部工作正常。

这决定了 KUMA 的适用边界：**它通过文件系统效果和 claim 状态来评判 agent，
而不是通过 agent 的输出文本。** 对代码修复类 agent 这是贴切的；对
06-trading-agents 这种产出文本决策的 agent，就是工具不匹配——
即使让它把决策写进文件，也只能验证"文件被创建了"，无法验证"决策是 BUY"。

第二节那个 `MappingProxyType` 阻断缺陷、第五节的契约陷阱、
第六节的 `upload_diff` 名不副实，均不受本节影响，依然成立。

### 附带发现

`case_id` 在后端与内容绑定：同一 `case_id` 换内容会抛
`CaseIntegrityError: The Case integrity metadata does not match`，
但**要到 judge 阶段才报**，此时整个 Run 已经跑完、算力已经花掉。

`api.py:218`：自定义 Case + 自定义 Judge 强制要求 case 带 `rubric`
（`Custom Case + custom Judge requires a fixed public rubric`）。

`api.py:233`：`tracking_root = Path("/") if runtime.mode == "docker" else resolved_repo`
——docker 模式下证据路径是**容器相对**而非仓库相对，这是有意设计，不是缺陷。

### 本节消耗

7 次 Run（含一次 CaseIntegrityError）。累计 credits 99,984 → 99,963。
