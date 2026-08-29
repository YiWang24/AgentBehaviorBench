"""Run one case from cases.json and narrate what the agent does, live.

The point of this file is visibility. TradingAgents takes 6-8 minutes for a
single-analyst run and prints nothing on its own, so without narration the
terminal looks hung. Every node entry, tool call, and model reply is echoed
as it happens.

Nothing under TradingAgents/ is imported differently than the upstream CLI
does it. In particular the graph is driven the way cli/main.py drives it --
`propagator.get_graph_args(callbacks=[...])` then `graph.stream(...)` --
because `TradingAgentsGraph.propagate()` calls get_graph_args() with no
callbacks (trading_graph.py:432), which leaves the tool nodes uninstrumented.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from langchain_core.callbacks.base import BaseCallbackHandler

# LangChain wraps every node in helper runnables; showing them would bury the
# actual graph nodes in noise.
_NOISE = ("Runnable", "ChatPrompt", "Parser", "Lambda", "Passthrough", "LangGraph")

BOLD, DIM, GREEN, YELLOW, CYAN, RESET = (
    ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[36m", "\033[0m")
    if sys.stdout.isatty()
    else ("", "", "", "", "", "")
)


# A ToolNode runs its calls in parallel, so several callback threads print at
# once; without this the lines interleave mid-word.
_PRINT_LOCK = threading.Lock()


def _say(text: str = "") -> None:
    with _PRINT_LOCK:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


class Narrator(BaseCallbackHandler):
    """Echo graph progress to the terminal and keep counters for the summary."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.llm_calls = 0
        self.tool_calls: list[dict] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.nodes: list[str] = []
        self.errors: list[str] = []

    @property
    def elapsed(self) -> str:
        return f"{time.time() - self.t0:6.1f}s"

    def on_chain_start(self, serialized, inputs, **kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name") or ""
        if not name or any(token in name for token in _NOISE):
            return
        if name.startswith("should_continue"):
            _say(f"{DIM}[{self.elapsed}]   ? router {name}{RESET}")
            return
        if self.nodes and self.nodes[-1] == name:
            return
        self.nodes.append(name)
        _say(f"{DIM}[{self.elapsed}]{RESET} {BOLD}{CYAN}-> {name}{RESET}")

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        args = kwargs.get("inputs")
        shown = json.dumps(args, ensure_ascii=False) if args else str(input_str)[:160]
        self.tool_calls.append({"tool": name, "args": args})
        _say(f"{DIM}[{self.elapsed}]{RESET}    {YELLOW}tool {name}{RESET} {shown}")

    def on_tool_end(self, output, **kwargs):
        # LangGraph hands back a ToolMessage; str() on it would print the repr
        # rather than what the model actually reads.
        text = str(getattr(output, "content", output))
        head = text.strip().splitlines()[0][:90] if text.strip() else "(empty)"
        _say(f"{DIM}[{self.elapsed}]{RESET}      {GREEN}<- {len(text):,} chars{RESET}  {DIM}{head}{RESET}")

    def on_tool_error(self, error, **kwargs):
        self.errors.append(f"tool: {type(error).__name__}: {error}")
        _say(f"{DIM}[{self.elapsed}]{RESET}      {YELLOW}!! tool error: {type(error).__name__}: {error}{RESET}")

    def on_chat_model_start(self, serialized, messages, **kwargs):
        model = (kwargs.get("invocation_params") or {}).get("model", "?")
        _say(f"{DIM}[{self.elapsed}]{RESET}    {DIM}thinking... ({model}){RESET}")

    def on_llm_end(self, response, **kwargs):
        self.llm_calls += 1
        try:
            usage = response.generations[0][0].message.usage_metadata or {}
            self.tokens_in += usage.get("input_tokens", 0)
            self.tokens_out += usage.get("output_tokens", 0)
        except Exception:
            pass

    def on_llm_error(self, error, **kwargs):
        self.errors.append(f"llm: {type(error).__name__}: {error}")
        _say(f"{DIM}[{self.elapsed}]{RESET}    {YELLOW}!! llm error: {type(error).__name__}: {error}{RESET}")


def _load_case(cases_path: str, input_id: str | None) -> tuple[dict, dict]:
    with open(cases_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    inputs = doc["inputs"]
    if input_id:
        chosen = next((i for i in inputs if i["input_id"] == input_id), None)
        if chosen is None:
            ids = "\n  ".join(i["input_id"] for i in inputs)
            raise SystemExit(f"No such input_id: {input_id}\nAvailable:\n  {ids}")
    else:
        chosen = inputs[0]
    return chosen, (doc.get("rubric") or {}).get(chosen["input_id"], {})


def _section(title: str) -> None:
    _say()
    _say(f"{BOLD}{'=' * 72}{RESET}")
    _say(f"{BOLD}{title}{RESET}")
    _say(f"{BOLD}{'=' * 72}{RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", default="/opt/bench/cases.json")
    ap.add_argument("--input-id", default=None, help="Which input to run; default is the first")
    ap.add_argument("--list", action="store_true", help="List available inputs and exit")
    ap.add_argument("--out", default=None, help="Write the full result JSON here")
    args = ap.parse_args()

    if args.list:
        with open(args.cases, encoding="utf-8") as fh:
            doc = json.load(fh)
        for item in doc["inputs"]:
            intent = (doc.get("rubric") or {}).get(item["input_id"], {}).get("intent", "")
            _say(f"{BOLD}{item['input_id']}{RESET}")
            _say(f"    payload: {json.dumps(item['payload'], ensure_ascii=False)}")
            _say(f"    {DIM}{intent}{RESET}\n")
        return 0

    chosen, rubric = _load_case(args.cases, args.input_id)
    payload = chosen["payload"]

    # Imported here so --list works even outside the image.
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    cfg = dict(DEFAULT_CONFIG)
    cfg["max_debate_rounds"] = payload.get("max_debate_rounds", 1)
    cfg["max_risk_discuss_rounds"] = payload.get("max_risk_rounds", 1)

    ticker = payload["ticker"]
    date = payload["date"]
    analysts = payload.get("analysts") or ["market"]
    asset_type = payload.get("asset_type", "stock")

    _section(f"CASE  {chosen['input_id']}")
    if rubric.get("intent"):
        _say(f"{DIM}{rubric['intent']}{RESET}\n")
    _say(f"  ticker            {ticker}")
    _say(f"  date              {date}")
    _say(f"  analysts          {', '.join(analysts)}")
    _say(f"  debate rounds     {cfg['max_debate_rounds']}  (risk: {cfg['max_risk_discuss_rounds']})")
    _say(f"  quick-think LLM   {cfg['llm_provider']} / {cfg['quick_think_llm']}")
    _say(f"  deep-think LLM    {cfg['llm_provider']} / {cfg['deep_think_llm']}")
    _say(f"\n{DIM}A single-analyst run is roughly 11 model calls and 6-8 minutes.{RESET}")

    _section("LIVE  what the agent is doing")

    narrator = Narrator()
    graph = TradingAgentsGraph(analysts, config=cfg, debug=False, callbacks=[narrator])
    instrument_context = graph.resolve_instrument_context(ticker, asset_type)
    init = graph.propagator.create_initial_state(
        ticker, date, asset_type=asset_type, instrument_context=instrument_context
    )
    graph_args = graph.propagator.get_graph_args(callbacks=[narrator])

    final: dict = {}
    failure: str | None = None
    try:
        for chunk in graph.graph.stream(init, **graph_args):
            final = chunk
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        _say(f"\n{YELLOW}RUN ABORTED: {failure}{RESET}")

    decision = final.get("final_trade_decision", "") if final else ""
    signal = None
    if decision:
        try:
            signal = graph.process_signal(decision)
        except Exception as exc:
            signal = f"<unparseable: {type(exc).__name__}: {exc}>"

    _section("RESOLVED INSTRUMENT  (anchors every agent to the real issuer)")
    _say(instrument_context.strip() or "(empty)")

    for key, label in (
        ("market_report", "MARKET ANALYST REPORT"),
        ("sentiment_report", "SOCIAL / SENTIMENT REPORT"),
        ("news_report", "NEWS REPORT"),
        ("fundamentals_report", "FUNDAMENTALS REPORT"),
        ("investment_plan", "RESEARCH MANAGER  (verdict of the bull/bear debate)"),
        ("trader_investment_plan", "TRADER PLAN"),
    ):
        text = (final or {}).get(key) or ""
        if not text.strip():
            continue
        _section(label)
        body = text.strip()
        _say(body if len(body) <= 2500 else body[:2500] + f"\n{DIM}... [{len(body):,} chars total, full text in the saved JSON]{RESET}")

    _section("PORTFOLIO MANAGER  final decision")
    _say(decision.strip() or "(none - the run did not reach the Portfolio Manager)")

    _section("RESULT")
    _say(f"  rating           {BOLD}{signal or '(none)'}{RESET}   {DIM}(5-tier: Buy / Overweight / Hold / Underweight / Sell){RESET}")
    _say(f"  wall time        {time.time() - narrator.t0:.1f}s")
    _say(f"  model calls      {narrator.llm_calls}")
    _say(f"  tool calls       {len(narrator.tool_calls)}")
    _say(f"  tokens           {narrator.tokens_in:,} in / {narrator.tokens_out:,} out")
    _say(f"  nodes visited    {len(narrator.nodes)}")
    if narrator.errors or failure:
        _say(f"  {YELLOW}errors           {len(narrator.errors) + (1 if failure else 0)}{RESET}")
        for err in narrator.errors:
            _say(f"    {YELLOW}- {err}{RESET}")
        if failure:
            _say(f"    {YELLOW}- run aborted: {failure}{RESET}")
    else:
        _say(f"  errors           none")

    _say(f"\n{DIM}Tools the model chose to call, in order:{RESET}")
    for call in narrator.tool_calls:
        _say(f"  {call['tool']}  {json.dumps(call['args'], ensure_ascii=False)}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "input_id": chosen["input_id"],
                    "payload": payload,
                    "config": {
                        "llm_provider": cfg["llm_provider"],
                        "quick_think_llm": cfg["quick_think_llm"],
                        "deep_think_llm": cfg["deep_think_llm"],
                        "data_vendors": cfg["data_vendors"],
                        "max_debate_rounds": cfg["max_debate_rounds"],
                        "max_risk_discuss_rounds": cfg["max_risk_discuss_rounds"],
                    },
                    "instrument_context": instrument_context,
                    "signal": signal,
                    "final_state": {k: v for k, v in (final or {}).items() if k != "messages"},
                    "stats": {
                        "wall_seconds": round(time.time() - narrator.t0, 1),
                        "llm_calls": narrator.llm_calls,
                        "tool_calls": narrator.tool_calls,
                        "tokens_in": narrator.tokens_in,
                        "tokens_out": narrator.tokens_out,
                        "nodes": narrator.nodes,
                        "errors": narrator.errors,
                        "aborted": failure,
                    },
                },
                fh,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        _say(f"\n{DIM}Full result written to {args.out}{RESET}")

    return 1 if (failure or narrator.errors) else 0


if __name__ == "__main__":
    sys.exit(main())
