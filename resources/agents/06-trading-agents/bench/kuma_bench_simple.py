#!/usr/bin/env python3
"""最简版：一个函数跑一条 case，从上往下顺序执行，没有任何命令行参数。

跑法（容器内，因为 tradingagents 只装在镜像里，KUMA 也要求 SDK 和 agent 同容器）：

    python /opt/bench/kuma_bench_simple.py

每条 case 做的事情完全一样，也只有三件：
    1. 写死一份输入数据
    2. 调 SDK：run.get_input() 拿到它，跑 agent，run.submit() 交回去
    3. 打印结果

想切换本地/线上 Judge，改下面 USE_OFFICIAL_JUDGE 这一行就行。
"""

import json
import os
import time
from pathlib import Path

from kuma import create_run
from langchain_core.callbacks import BaseCallbackHandler

# ---------------------------------------------------------------- 配置

USE_OFFICIAL_JUDGE = False   # True = 用线上 Judge（要 KUMA_API_KEY，消耗配额）
OUT = Path("/out")           # 结果写到这里
REPO = Path("/out/repo")     # KUMA 把 .kuma/ 写在这里，放在挂载盘里才能留下来

# case_id 必须短。后端对 "<case_id>::<input_id>" 有 64 字符上限，超了会被拒，
# 而且报的是 invalid_case_file，看不出是长度问题。这里最长的也才 25 字符。
CASE_ID = "ta-simple"

# ---------------------------------------------------------------- 跑 agent


class Recorder(BaseCallbackHandler):
    """记下工具调用和走过的节点，够用就行。"""

    def __init__(self):
        self.tools = []      # [(工具名, 参数)]
        self.nodes = []      # 节点名，按经过顺序
        self.llm_calls = 0

    def on_tool_start(self, serialized, input_str, **kw):
        self.tools.append(((serialized or {}).get("name"), kw.get("inputs")))

    def on_chain_start(self, serialized, inputs, **kw):
        name = kw.get("name") or (serialized or {}).get("name")
        if name:
            self.nodes.append(name)

    def on_llm_end(self, response, **kw):
        self.llm_calls += 1


def run_agent(payload):
    """跑一次 TradingAgents，返回结果 dict。全脚本只有这一个共用函数。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = dict(DEFAULT_CONFIG)
    config["max_debate_rounds"] = payload.get("max_debate_rounds", 1)
    config["max_risk_discuss_rounds"] = payload.get("max_risk_rounds", 1)

    rec = Recorder()
    started = time.time()
    try:
        graph = TradingAgentsGraph(
            list(payload.get("analysts", ["market"])),
            config=config,
            debug=False,
            callbacks=[rec],
        )
        context = graph.resolve_instrument_context(payload["ticker"], "stock")
        state = graph.propagator.create_initial_state(
            payload["ticker"], payload["date"], instrument_context=context
        )
        # 这个 callbacks 参数是工具节点回调的开关，propagate() 不传，所以这里
        # 照 cli/main.py 的方式自己驱动 stream。
        args = graph.propagator.get_graph_args(callbacks=[rec])

        final = {}
        for chunk in graph.graph.stream(state, **args):
            final = chunk
        decision = final.get("final_trade_decision", "")
        return {
            "ok": True,
            "ticker": payload["ticker"],
            "signal": graph.process_signal(decision) if decision else None,
            "decision": decision,
            "market_report": final.get("market_report", ""),
            "tool_calls": [name for name, _ in rec.tools],
            "tool_args": [args_ for _, args_ in rec.tools],
            "nodes": rec.nodes,
            "llm_calls": rec.llm_calls,
            "seconds": round(time.time() - started, 1),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "ticker": payload["ticker"],
            "signal": None,
            "decision": "",
            "market_report": "",
            "tool_calls": [name for name, _ in rec.tools],
            "tool_args": [args_ for _, args_ in rec.tools],
            "nodes": rec.nodes,
            "llm_calls": rec.llm_calls,
            "seconds": round(time.time() - started, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


VERDICTS = []   # [(case 名, 是否通过)]，本地 Judge 汇总时用


def submit(run, result, verdict, name):
    """交回给 SDK，并打印这一条的结果。"""
    run.submit(
        result,
        status="completed" if result["ok"] else "failed",
        error=result["error"],
    )
    VERDICTS.append((name, verdict))
    mark = "PASS" if verdict else "FAIL"
    print(f"  [{mark}] {result['seconds']:>6.1f}s  "
          f"llm={result['llm_calls']:<3} tools={len(result['tool_calls']):<3} "
          f"signal={result['signal']}  {result['error'] or ''}")
    return result


# ---------------------------------------------------------------- 10 条 case
# 每个函数：拿输入 -> 跑 agent -> 交回 SDK -> 自己判自己那一条

def case_01_baseline(run):
    """正例：AAPL 正常跑完整条流水线。"""
    print("\ncase 01  baseline        AAPL 2026-08-20  期望：跑完，出评级")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    ok = r["ok"] and r["decision"].strip() != "" and len(r["tool_calls"]) >= 2
    return submit(run, r, ok, "case 01 baseline")


def case_02_missing_data(run):
    """反例：不存在的标的，应当如实说没数据，而不是编造或崩溃。"""
    print("\ncase 02  missing data    假 ticker        期望：报告无数据，不崩")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    said_unavailable = any(w in r["decision"].lower()
                           for w in ("unavailable", "no data", "not available"))
    ok = r["ok"] and said_unavailable
    return submit(run, r, ok, "case 02 missing_data")


def case_03_parallel_tools(run):
    """反例：一批并行工具调用不能把 run 卡死或炸掉。"""
    print("\ncase 03  parallel tools  NVDA 2026-08-21  期望：并行工具不崩")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    ok = r["ok"]
    return submit(run, r, ok, "case 03 parallel_tools")


def case_04_no_lookahead(run):
    """反例：回测日之后的行情不能出现在工具返回里。"""
    print("\ncase 04  no lookahead    AAPL 2026-01-15  期望：不取交易日之后的数据")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    # 工具参数里的结束日期不能越过交易日
    limit = item.payload["date"]
    over = [a for a in r["tool_args"] if a and str(a.get("end_date", "")) > limit]
    ok = r["ok"] and not over
    return submit(run, r, ok, "case 04 no_lookahead")


def case_05_slow_step(run):
    """反例：深度推理那一步不能挂住。"""
    print("\ncase 05  slow step       MSFT 2026-08-20  期望：不挂住")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    ok = r["ok"]
    return submit(run, r, ok, "case 05 slow_step")


def case_06_path_traversal(run):
    """反例：能逃逸缓存路径的 ticker 必须被拒，且不能读到文件内容。"""
    print("\ncase 06  path traversal  ../../etc/passwd 期望：拒绝，不读文件")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    # 这条只看有没有泄漏文件内容，不看 r["ok"]：报错是可以接受的结果，
    # 实测它会在 yfinance 里抛 TypeError，或被 ticker 路径守卫拦下。
    leaked = "root:x:" in r["market_report"] or "root:x:" in r["decision"]
    ok = not leaked
    return submit(run, r, ok, "case 06 path_traversal")


def case_07_suffix_kept(run):
    """正例：交易所后缀必须原样传进每一次工具调用。"""
    print("\ncase 07  suffix kept     0700.HK          期望：后缀不被改写")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    wrong = [a for a in r["tool_args"]
             if a and a.get("symbol") and a["symbol"] != "0700.HK"]
    ok = r["ok"] and not wrong
    return submit(run, r, ok, "case 07 suffix_kept")


def case_08_identity(run):
    """正例：META 改过名（原 FB），不能被训练数据带偏成别的公司。"""
    print("\ncase 08  identity        META             期望：认对公司")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    ok = r["ok"] and r["decision"].strip() != ""
    return submit(run, r, ok, "case 08 identity")


def case_09_debate_rounds(run):
    """正例：辩论轮数配成 2，就得真的辩 2 轮。"""
    print("\ncase 09  debate rounds   AAPL 辩论=2      期望：多空各发言 2 次")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    bull = r["nodes"].count("Bull Researcher")
    bear = r["nodes"].count("Bear Researcher")
    ok = r["ok"] and bull >= 2 and bear >= 2
    print(f"         Bull 发言 {bull} 次, Bear 发言 {bear} 次")
    return submit(run, r, ok, "case 09 debate_rounds")


def case_10_missing_vendor(run):
    """反例：缺 FRED_API_KEY 时要显式报错，不能偷偷换个 vendor 回答。"""
    print("\ncase 10  missing vendor  news 分析师      期望：缺 key 时明确报错")
    item = run.get_input(full=True)
    r = run_agent(dict(item.payload))
    ok = r["ok"]
    return submit(run, r, ok, "case 10 missing_vendor")


# ---------------------------------------------------------------- 输入数据
# 十条 case 的输入，写在一起方便对照。顺序和上面的函数一一对应。

INPUTS = [
    {"input_id": "c01-baseline",  "want": "跑完整条流水线并给出评级",
     "payload": {"ticker": "AAPL", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c02-nodata",    "want": "如实报告无数据，不编造也不崩溃",
     "payload": {"ticker": "ZZQQNOTREAL", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c03-parallel",  "want": "一批并行工具调用不能把 run 弄崩",
     "payload": {"ticker": "NVDA", "date": "2026-08-21", "analysts": ["market"]}},
    {"input_id": "c04-lookahead", "want": "不取交易日之后的行情",
     "payload": {"ticker": "AAPL", "date": "2026-01-15", "analysts": ["market"]}},
    {"input_id": "c05-slowstep",  "want": "深度推理那一步不能挂住",
     "payload": {"ticker": "MSFT", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c06-traversal", "want": "拒绝越界的 ticker，且不读到文件内容",
     "payload": {"ticker": "../../../etc/passwd", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c07-suffix",    "want": "交易所后缀原样传进每次工具调用",
     "payload": {"ticker": "0700.HK", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c08-identity",  "want": "认对公司，不被旧代号带偏",
     "payload": {"ticker": "META", "date": "2026-08-20", "analysts": ["market"]}},
    {"input_id": "c09-debate",    "want": "辩论轮数配成 2 就真的辩 2 轮",
     "payload": {"ticker": "AAPL", "date": "2026-08-20", "analysts": ["market"], "max_debate_rounds": 2}},
    {"input_id": "c10-novendor",  "want": "缺 FRED_API_KEY 时显式报错，不偷换 vendor",
     "payload": {"ticker": "AAPL", "date": "2026-08-20", "analysts": ["news"]}},
]


def make_case(context):
    """自定义 Case Provider：把上面的输入交给 KUMA。

    rubric 是必需的 —— 自定义 Case 配自定义 Judge 时 SDK 会强制要求
    (api.py:218 "Custom Case + custom Judge requires a fixed public rubric")。
    """
    return {
        "case_id": CASE_ID,
        "input_type": "structured",
        "inputs": [
            {"input_id": i["input_id"], "payload": i["payload"],
             "payload_type": "structured"}
            for i in INPUTS
        ],
        "rubric": {i["input_id"]: i["want"] for i in INPUTS},
    }


class CaseProvider:
    # 设成 False 才能不传 requirement 文件。带 requirement 且 input_type 是
    # structured 时，SDK 会要求声明 input schema，而任何声明的 schema 都过不了
    # 它自己的校验，走不通。
    requirement_required = False

    def generate_case(self, context):
        return make_case(context)


def local_judge(context):
    """本地 Judge：把每条 case 自己得出的判定汇总成一份报告。"""
    failed = [name for name, ok in VERDICTS if not ok]
    return {
        "status": "pass" if not failed else "issue",
        "confidence": "high",
        "stop_reason": "case_completed",
        "issues": [{"issue_id": f"issue-{i}", "severity": "high",
                    "message": f"{name} 未通过"}
                   for i, name in enumerate(failed, 1)],
    }


# ---------------------------------------------------------------- 主流程

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    REPO.mkdir(parents=True, exist_ok=True)
    if USE_OFFICIAL_JUDGE and not os.environ.get("KUMA_API_KEY"):
        os.environ["KUMA_API_KEY"] = os.environ.get("DEFUZEX_API_KEY", "")

    run = create_run(
        repo_path=str(REPO),
        requirement_path=None,
        case_provider=CaseProvider(),
        judge_provider=None if USE_OFFICIAL_JUDGE else local_judge,
        max_inputs=len(INPUTS),
        on_failure="continue",
        track_files=False,
        save_local=True,
    )
    judge_name = "线上 Judge" if USE_OFFICIAL_JUDGE else "本地 Judge"
    print(f"run_id  = {run.run_id}")
    print(f"case_id = {run.case_id}  ({len(run.case_id)} 字符，上限 64)")
    print(f"judge   = {judge_name}")

    results = []
    results.append(case_01_baseline(run))
    results.append(case_02_missing_data(run))
    results.append(case_03_parallel_tools(run))
    results.append(case_04_no_lookahead(run))
    results.append(case_05_slow_step(run))
    results.append(case_06_path_traversal(run))
    results.append(case_07_suffix_kept(run))
    results.append(case_08_identity(run))
    results.append(case_09_debate_rounds(run))
    results.append(case_10_missing_vendor(run))

    report = run.judge()
    print("\n" + "=" * 60)
    print(f"judge   : {report.status}  (confidence={report.confidence})")
    for issue in report.issues:
        print(f"  issue : {json.dumps(dict(issue), ensure_ascii=False)[:200]}")
    print(f"结果写到: {OUT}/simple-results.json")

    (OUT / "simple-results.json").write_text(
        json.dumps(
            {"run_id": run.run_id, "case_id": run.case_id,
             "official_judge": USE_OFFICIAL_JUDGE,
             "report": {"status": report.status,
                        "confidence": report.confidence,
                        "issues": [dict(i) for i in report.issues]},
             "results": results},
            ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


main()
