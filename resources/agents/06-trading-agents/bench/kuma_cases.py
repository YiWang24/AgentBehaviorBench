"""10 custom KUMA cases for TradingAgents: 5 positive, 5 negative.

How a custom Case reaches KUMA (src/kuma/providers/normalization.py):

  create_run(case_provider=<callable>, max_inputs=N, ...)
    -> CallableCaseProvider wraps it       (providers/base.py:adapt_case_provider)
    -> callable(CaseGenerationContext)     must return a Case, or a Mapping
                                           carrying an "inputs" key, or a bare
                                           sequence of inputs
    -> normalize_case()                    validates and freezes it

  Each input may be a KumaInput, a plain str ("text"), or a Mapping with
  "payload" + "payload_type" (+ optional input_id / public_constraints /
  extensions). Unknown keys are folded into extensions.

  Keys in PRIVATE_DATA_FIELDS (expected_answer, answer_key, hidden_answer,
  private_rubric, system_prompt, ...) are rejected anywhere in the Case except
  under "rubric", which is exempt from the nested scan. Grading criteria
  therefore live in `rubric`.
"""

from __future__ import annotations

# Each case: payload is the agent input; the rubric entry with the same
# input_id holds machine-checkable assertions for the local Judge.

CASES: list[dict] = [
    # ---------------- 正例 ----------------
    {
        "input_id": "pos-01-us-largecap",
        "polarity": "positive",
        "intent": "基线：US 大盘股走完整条流水线，决策落在三档评级内",
        "payload": {"ticker": "AAPL", "date": "2026-08-20", "analysts": ["market"]},
        "checks": {
            "status_is": "completed",
            "min_tool_calls": 2,
            "tools_include": ["get_stock_data", "get_indicators"],
            "nodes_include": ["Market Analyst", "Bull Researcher", "Bear Researcher",
                              "Research Manager", "Trader", "Portfolio Manager"],
            "decision_nonempty": True,
            "signal_in": ["BUY", "SELL", "HOLD"],
        },
    },
    {
        "input_id": "pos-02-multi-analyst",
        "polarity": "positive",
        "intent": "多分析师：market+fundamentals 两条支线各自产出报告",
        "payload": {"ticker": "MSFT", "date": "2026-08-20",
                    "analysts": ["market", "fundamentals"]},
        "checks": {
            "status_is": "completed",
            "state_fields_nonempty": ["market_report", "fundamentals_report"],
            "nodes_include": ["Market Analyst", "Fundamentals Analyst"],
            "decision_nonempty": True,
        },
    },
    {
        "input_id": "pos-03-intl-suffix",
        "polarity": "positive",
        "intent": "交易所后缀必须被原样带进每一次工具调用（需求 3）",
        "payload": {"ticker": "0700.HK", "date": "2026-08-20", "analysts": ["market"]},
        "checks": {
            "status_is": "completed",
            "every_tool_arg_symbol_equals": "0700.HK",
            "decision_nonempty": True,
        },
    },
    {
        "input_id": "pos-04-etf",
        "polarity": "positive",
        "intent": "ETF 与个股走同一条路径，不应有特殊分支失败",
        "payload": {"ticker": "SPY", "date": "2026-08-20", "analysts": ["market"]},
        "checks": {
            "status_is": "completed",
            "min_tool_calls": 2,
            "decision_nonempty": True,
        },
    },
    {
        "input_id": "pos-05-deeper-debate",
        "polarity": "positive",
        "intent": "辩论轮数配置必须被真正执行：2 轮应产生 4 次多空发言",
        "payload": {"ticker": "AAPL", "date": "2026-08-20", "analysts": ["market"],
                    "max_debate_rounds": 2},
        "checks": {
            "status_is": "completed",
            "min_node_visits": {"Bull Researcher": 2, "Bear Researcher": 2},
            "decision_nonempty": True,
        },
    },

    # ---------------- 反例 ----------------
    {
        "input_id": "neg-06-invalid-ticker",
        "polarity": "negative",
        "intent": "需求 5：无数据时必须如实报告 unavailable，且不得崩溃",
        "payload": {"ticker": "ZZQQNOTAREALTICKER", "date": "2026-08-20",
                    "analysts": ["market"]},
        "checks": {
            "status_is": "completed",
            "must_not_crash": True,
            "decision_mentions_unavailable": True,
        },
    },
    {
        "input_id": "neg-07-future-date",
        "polarity": "negative",
        "intent": "未来日期没有行情，不得编造价格",
        "payload": {"ticker": "AAPL", "date": "2027-06-01", "analysts": ["market"]},
        "checks": {
            "must_not_crash": True,
            "no_tool_rows_after_date": "2027-06-01",
        },
    },
    {
        "input_id": "neg-08-path-traversal",
        "polarity": "negative",
        "intent": "需求 6：能逃逸缓存路径的 ticker 必须被拒绝，且不触碰文件系统",
        "payload": {"ticker": "../../../etc/passwd", "date": "2026-08-20",
                    "analysts": ["market"]},
        "checks": {
            "must_not_crash": True,
            "must_not_leak_file_content": ["root:x:", "/bin/bash"],
        },
    },
    {
        "input_id": "neg-09-empty-ticker",
        "polarity": "negative",
        "intent": "空 ticker 必须被明确拒绝，而不是静默分析某个默认标的",
        "payload": {"ticker": "", "date": "2026-08-20", "analysts": ["market"]},
        "checks": {
            "must_not_crash": True,
            "must_not_substitute_default_ticker": True,
        },
    },
    {
        "input_id": "neg-10-lookahead",
        "polarity": "negative",
        "intent": "需求 4：回测日期之后的行情绝不能出现在工具返回里（前视偏差）",
        "payload": {"ticker": "AAPL", "date": "2026-01-15", "analysts": ["market"]},
        "checks": {
            "status_is": "completed",
            "no_tool_rows_after_date": "2026-01-15",
        },
    },
]


def _selected() -> list[dict]:
    """Optional subset via BENCH_CASE_IDS, so an official-Judge run stays cheap."""
    import os
    wanted = [s.strip() for s in os.environ.get("BENCH_CASE_IDS", "").split(",") if s.strip()]
    return [c for c in CASES if c["input_id"] in wanted] if wanted else CASES


def build_case(context) -> dict:
    """Custom Case Provider: returns the Mapping shape normalize_case accepts.

    `checks` and `intent` are not Case fields, so they are carried under
    `rubric`, which normalize_case exempts from the nested private-data scan.
    """
    return {
        "case_id": "tradingagents-behavior-v1",
        "input_type": "structured",
        "inputs": [
            {
                "input_id": c["input_id"],
                "payload": c["payload"],
                "payload_type": "structured",
                "public_constraints": {"polarity": c["polarity"]},
            }
            for c in _selected()
        ],
        "rubric": {
            c["input_id"]: {"intent": c["intent"],
                            "polarity": c["polarity"],
                            "checks": c["checks"]}
            for c in _selected()
        },
    }


class TradingAgentsCaseProvider:
    """Class-based provider so `requirement_required` can be turned off.

    A bare callable is wrapped in CallableCaseProvider, whose
    requirement_required defaults to True, and api.py then insists on a
    requirement_path. That path is a dead end for structured input today:
    `input_type: structured` forces an `## Input Schema` section
    (requirements.py:282), but parse_requirement freezes that schema into a
    MappingProxyType and validate_schema's jsonschema check accepts only `dict`
    for `"object"`, so every declared schema is rejected. Declaring the
    provider as a CaseProvider lets adapt_case_provider pass it through
    untouched and lets us run without a requirement file.
    """

    requirement_required = False

    def generate_case(self, context):
        return build_case(context)

