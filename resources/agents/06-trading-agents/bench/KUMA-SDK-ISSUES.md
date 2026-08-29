# KUMA SDK 实测缺陷（用 06 TradingAgents 的 10 条自定义 case 触发）

SDK 版本：`/home/wy/projects/DefuzeX/KUMA-DefuzeX` 本地源码（`kuma-defuzex`，pip 安装进容器）。
运行方式：完全本地（自定义 Case Provider + 自定义 Judge Provider），不使用 API key、不上传任何数据。

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
