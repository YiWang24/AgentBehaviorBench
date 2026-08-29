#!/usr/bin/env python3
"""Run the ten grounded TradingAgents cases through the KUMA SDK, in Docker.

One file, three roles, because KUMA and AgentBehaviorBench disagree about where
the SDK lives.

    (no flags)                  ABB's JSONL worker on stdin/stdout, so
                                `agentbench run trading-agents` still works
    --in-container --case ID    the KUMA Run for one case, inside the container
    anything else               the host orchestrator

ABB keeps the SDK on the host and talks to the agent through a JSONL pipe
(agentbench/runtime/docker/session.py). KUMA refuses to start unless the SDK
process is inside the same container as the agent (kuma/runtime.py:41), and its
Trace Evidence capture is an in-process OTel SpanProcessor, so a host-side
capture would receive nothing. The Run loop therefore has to move into the
container, which is why BenchmarkRunner.run_defuzex cannot be called here --
only its shape is reused. Everything else the host needs is imported from
agentbench: the registry, the container manifest, the image builder, the
security policy, the result types and the append-only result log.

Design notes, and the measurements behind them, are in KUMA-BENCH-DESIGN.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
AGENT_DIR = BENCH_DIR.parent
# .../<repo>/resources/agents/06-trading-agents/bench -> <repo>. Only the host
# role uses this; in the container bench/ is mounted at /opt/bench and there is
# no repository above it, so fall back rather than raising at import time.
REPO_ROOT = AGENT_DIR.parents[2] if len(AGENT_DIR.parents) > 2 else AGENT_DIR
AGENT_ID = "trading-agents"

# Pinned to the vendored revision so a stale image from a different revision can
# never be reused by accident.
UPSTREAM_REVISION = "a33fd4c"
BASE_IMAGE = f"ta-native:{UPSTREAM_REVISION}"

CONTAINER_BENCH = "/opt/bench"
CONTAINER_OUT = "/out"
# KUMA writes .kuma/ and a .gitignore rule into repo_path, so it has to be
# writable. Under the ABB policy the root filesystem is read-only, which leaves
# the bind-mounted output directory as the honest place for it.
CONTAINER_REPO = "/out/repo"

# Paths the harness itself writes to. Docker-mode file tracking is rooted at
# "/" (kuma/api.py:233), so without this the driver's own artifacts would show
# up as agent file activity.
HARNESS_PATHS = ("/out", "/opt/bench", "/tmp/kuma", "/opt/kuma-src")

# deepseek-v4-pro for deep thinking is a workaround, not a preference: with
# deepseek-v4-flash the Research Manager's structured-output call never returns
# (reproduced twice, both runs still frozen past 16 minutes at 0% CPU).
DEFAULT_QUICK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEP_MODEL = "deepseek-v4-pro"


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def plain(value: Any) -> Any:
    """Undo the SDK's deep freeze.

    Everything the SDK hands back is a mappingproxy with tuples inside, so
    `isinstance(x, dict)` and `isinstance(x, list)` both silently fail on it.
    Measured, with the failure mode, in KUMA-BENCH-DESIGN.md section 3.
    """

    from collections.abc import Mapping, Sequence

    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    ):
        return [plain(item) for item in value]
    return value


def load_cases(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def select_inputs(doc: dict, *, case_id: str | None, run_all: bool) -> list[dict]:
    inputs = doc["inputs"]
    if run_all:
        return list(inputs)
    if case_id is None:
        return [inputs[0]]
    chosen = next((item for item in inputs if item["input_id"] == case_id), None)
    if chosen is None:
        available = "\n  ".join(item["input_id"] for item in inputs)
        raise SystemExit(f"No such case: {case_id}\nAvailable:\n  {available}")
    return [chosen]


# --------------------------------------------------------------------------
# container role: LangChain callbacks -> OTel spans + a full-fidelity sink
# --------------------------------------------------------------------------

# LangChain wraps every node in helper runnables. Turning those into spans would
# bury the real graph nodes and burn the 200-span budget on plumbing.
_NOISE = ("Runnable", "ChatPrompt", "Parser", "Lambda", "Passthrough", "LangGraph")


def _message_json(message: Any) -> dict[str, Any]:
    """Serialize a LangChain message without losing tool calls or usage."""

    out: dict[str, Any] = {
        "type": type(message).__name__,
        "role": getattr(message, "type", None),
        "content": str(getattr(message, "content", "")),
    }
    for attribute in ("name", "id", "tool_call_id"):
        value = getattr(message, attribute, None)
        if value:
            out[attribute] = value
    calls = getattr(message, "tool_calls", None)
    if calls:
        out["tool_calls"] = [
            {"name": c.get("name"), "args": c.get("args"), "id": c.get("id")}
            if isinstance(c, dict)
            else {"name": getattr(c, "name", None), "args": getattr(c, "args", None)}
            for c in calls
        ]
    usage = getattr(message, "usage_metadata", None)
    if usage:
        out["usage_metadata"] = dict(usage)
    metadata = getattr(message, "response_metadata", None)
    if metadata:
        out["response_metadata"] = {
            key: metadata[key]
            for key in ("finish_reason", "model_name", "model")
            if key in metadata
        }
    return out


def build_bridge_class():
    """Define the callback handler lazily; langchain_core only exists in the image."""

    import threading

    from langchain_core.callbacks.base import BaseCallbackHandler
    from opentelemetry.trace import Status, StatusCode

    class TraceBridge(BaseCallbackHandler):
        """Two recorders on one set of callbacks.

        The JSONL sink keeps everything at full fidelity -- prompts,
        completions, tool arguments, whole tool payloads -- and is handed to
        KUMA through `submit(logs=[...])`, where a custom Judge can read it in
        full. The OTel spans carry only structure and metrics, because the
        SDK's attribute allowlist keeps five gen_ai keys plus the
        gen_ai.latency./token.usage./usage. prefixes and drops everything else
        (kuma/evidence/trace_mapping.py:16). Anything matching its private-term
        list is not just dropped but counted, which turns the whole step's
        trace capture partial -- so no prompt or completion text is ever put on
        a span here.

        A tool's name survives only as the span name: gen_ai.tool.name is not
        on the allowlist and is discarded silently, without even a dropped
        count. Measured in KUMA-BENCH-DESIGN.md section 2.
        """

        raise_error = False

        def __init__(self, tracer: Any, sink_path: str | Path | None) -> None:
            super().__init__()
            self.tracer = tracer
            self.events: list[dict[str, Any]] = []
            self.started = time.time()
            self._lock = threading.Lock()
            self._sink = (
                open(sink_path, "w", encoding="utf-8") if sink_path else None
            )
            # run_id -> the span a child should hang from. Skipped plumbing
            # chains map to their own resolved parent, which keeps the tree
            # correct without emitting a span for the plumbing itself.
            self._parent: dict[str, Any] = {}
            self._open: dict[str, Any] = {}
            self._llm_started: dict[str, float] = {}
            self.root: Any = None

        # -- plumbing ---------------------------------------------------

        def _emit(self, kind: str, run_id: Any = None, parent: Any = None, **payload):
            event = {
                "seq": len(self.events),
                "t": round(time.time() - self.started, 3),
                "kind": kind,
                "run_id": str(run_id) if run_id else None,
                "parent_run_id": str(parent) if parent else None,
                **payload,
            }
            with self._lock:
                self.events.append(event)
                if self._sink:
                    self._sink.write(
                        json.dumps(event, default=str, ensure_ascii=False) + "\n"
                    )
                    self._sink.flush()

        def _parent_span(self, parent_run_id: Any) -> Any:
            if parent_run_id is not None:
                found = self._parent.get(str(parent_run_id))
                if found is not None:
                    return found
            return self.root

        def _start_span(self, name: str, run_id: Any, parent_run_id: Any) -> Any:
            from opentelemetry import trace as _trace

            parent = self._parent_span(parent_run_id)
            context = (
                _trace.set_span_in_context(parent) if parent is not None else None
            )
            span = self.tracer.start_span(name, context=context)
            if run_id is not None:
                key = str(run_id)
                self._open[key] = span
                self._parent[key] = span
            return span

        def _end_span(self, run_id: Any, *, error: str | None = None, **attributes):
            if run_id is None:
                return
            span = self._open.pop(str(run_id), None)
            if span is None:
                return
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            if error is not None:
                span.set_attribute("error.type", error.split(":", 1)[0])
                span.set_status(Status(StatusCode.ERROR))
            else:
                span.set_status(Status(StatusCode.OK))
            span.end()

        # -- workflow root ----------------------------------------------

        def open_workflow(self) -> None:
            self.root = self.tracer.start_span("tradingagents.workflow")
            # invoke_workflow outranks invoke_agent when the SDK picks which
            # span carries the submittable output (trace_mapping.py:299), so
            # the node spans below can safely use invoke_agent.
            self.root.set_attribute("gen_ai.operation.name", "invoke_workflow")
            self.root.set_attribute("gen_ai.system", "langgraph")

        def close_workflow(self, output_text: str | None, *, error: str | None) -> None:
            if self.root is None:
                return
            if output_text:
                # This is what lets submit() derive its output from the trace
                # (run.py:226). The attribute itself is not on the span
                # allowlist, so it feeds the output channel without landing in
                # the trace evidence.
                self.root.set_attribute(
                    "gen_ai.output.messages",
                    json.dumps(
                        [
                            {
                                "role": "assistant",
                                "parts": [{"type": "text", "content": output_text}],
                                "finish_reason": "stop",
                            }
                        ]
                    ),
                )
            if error is not None:
                self.root.set_attribute("error.type", error.split(":", 1)[0])
                self.root.set_status(Status(StatusCode.ERROR))
            else:
                self.root.set_status(Status(StatusCode.OK))
            self.root.end()
            self.root = None

        def close(self) -> None:
            for span in list(self._open.values()):
                span.end()
            self._open.clear()
            if self._sink:
                self._sink.close()
                self._sink = None

        # -- chains / graph nodes ---------------------------------------

        def on_chain_start(
            self, serialized, inputs, *, run_id=None, parent_run_id=None, **kwargs
        ):
            name = kwargs.get("name") or (serialized or {}).get("name") or ""
            self._emit(
                "chain_start",
                run_id,
                parent_run_id,
                name=name,
                tags=kwargs.get("tags"),
                input_keys=sorted(inputs) if isinstance(inputs, dict) else None,
            )
            if not name or any(token in name for token in _NOISE):
                # Plumbing: no span, but keep the tree connected.
                if run_id is not None:
                    self._parent[str(run_id)] = self._parent_span(parent_run_id)
                return
            span = self._start_span(name, run_id, parent_run_id)
            span.set_attribute("gen_ai.operation.name", "invoke_agent")

        def on_chain_end(self, outputs, *, run_id=None, parent_run_id=None, **kwargs):
            self._emit(
                "chain_end",
                run_id,
                parent_run_id,
                name=kwargs.get("name"),
                output_keys=sorted(outputs) if isinstance(outputs, dict) else None,
            )
            self._end_span(run_id)

        def on_chain_error(self, error, *, run_id=None, parent_run_id=None, **kwargs):
            detail = f"{type(error).__name__}: {error}"
            self._emit("chain_error", run_id, parent_run_id, error=detail)
            self._end_span(run_id, error=detail)

        # -- model calls -------------------------------------------------

        def on_chat_model_start(
            self, serialized, messages, *, run_id=None, parent_run_id=None, **kwargs
        ):
            params = kwargs.get("invocation_params") or {}
            model = params.get("model") or params.get("model_name") or "unknown"
            self._emit(
                "chat_model_start",
                run_id,
                parent_run_id,
                model=model,
                invocation_params=params,
                tools=[
                    tool.get("function", {}).get("name")
                    for tool in (params.get("tools") or [])
                ],
                messages=[[_message_json(m) for m in batch] for batch in messages],
                n_messages=sum(len(batch) for batch in messages),
            )
            if run_id is not None:
                self._llm_started[str(run_id)] = time.time()
            span = self._start_span(f"chat {model}", run_id, parent_run_id)
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", str(model))
            span.set_attribute("gen_ai.provider.name", str(params.get("provider") or "deepseek"))

        def on_llm_start(
            self, serialized, prompts, *, run_id=None, parent_run_id=None, **kwargs
        ):
            self._emit("llm_start", run_id, parent_run_id, prompts=prompts)

        def on_llm_end(self, response, *, run_id=None, parent_run_id=None, **kwargs):
            generations: list[dict[str, Any]] = []
            tokens_in = tokens_out = 0
            model = None
            for batch in response.generations:
                for generation in batch:
                    item: dict[str, Any] = {"text": str(getattr(generation, "text", ""))}
                    message = getattr(generation, "message", None)
                    if message is not None:
                        item["message"] = _message_json(message)
                        usage = getattr(message, "usage_metadata", None) or {}
                        tokens_in += usage.get("input_tokens", 0) or 0
                        tokens_out += usage.get("output_tokens", 0) or 0
                        model = (item["message"].get("response_metadata") or {}).get(
                            "model_name"
                        ) or model
                    info = getattr(generation, "generation_info", None)
                    if info:
                        item["generation_info"] = info
                    generations.append(item)
            started = self._llm_started.pop(str(run_id), None) if run_id else None
            duration = None if started is None else time.time() - started
            self._emit(
                "llm_end",
                run_id,
                parent_run_id,
                generations=generations,
                llm_output=response.llm_output,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_seconds=None if duration is None else round(duration, 3),
            )
            self._end_span(
                run_id,
                **{
                    "gen_ai.response.model": str(model) if model else None,
                    "gen_ai.usage.input_tokens": tokens_in or None,
                    "gen_ai.usage.output_tokens": tokens_out or None,
                    "gen_ai.latency.total_ms": (
                        None if duration is None else int(duration * 1000)
                    ),
                },
            )

        def on_llm_error(self, error, *, run_id=None, parent_run_id=None, **kwargs):
            detail = f"{type(error).__name__}: {error}"
            started = self._llm_started.pop(str(run_id), None) if run_id else None
            self._emit(
                "llm_error",
                run_id,
                parent_run_id,
                error=detail,
                duration_seconds=None if started is None else round(time.time() - started, 3),
            )
            self._end_span(run_id, error=detail)

        # -- tools --------------------------------------------------------

        def on_tool_start(
            self,
            serialized,
            input_str,
            *,
            run_id=None,
            parent_run_id=None,
            inputs=None,
            **kwargs,
        ):
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            self._emit(
                "tool_start",
                run_id,
                parent_run_id,
                tool=name,
                input_str=str(input_str),
                inputs=inputs,
            )
            # The tool name goes in the span name because gen_ai.tool.name is
            # dropped by the allowlist without a trace.
            span = self._start_span(str(name), run_id, parent_run_id)
            span.set_attribute("gen_ai.operation.name", "execute_tool")

        def on_tool_end(self, output, *, run_id=None, parent_run_id=None, **kwargs):
            content = getattr(output, "content", output)
            text = str(content)
            self._emit(
                "tool_end",
                run_id,
                parent_run_id,
                output_type=type(output).__name__,
                output_chars=len(text),
                output=text,
            )
            self._end_span(run_id)

        def on_tool_error(self, error, *, run_id=None, parent_run_id=None, **kwargs):
            detail = f"{type(error).__name__}: {error}"
            self._emit("tool_error", run_id, parent_run_id, error=detail)
            self._end_span(run_id, error=detail)

        # -- misc ----------------------------------------------------------

        def on_retry(self, retry_state, *, run_id=None, parent_run_id=None, **kwargs):
            self._emit(
                "retry",
                run_id,
                parent_run_id,
                attempt=getattr(retry_state, "attempt_number", None),
            )

        def on_text(self, text, *, run_id=None, parent_run_id=None, **kwargs):
            self._emit("text", run_id, parent_run_id, text=str(text)[:500])

        def on_state(self, chunk: dict) -> None:
            """Per-step state sizes from graph.stream, driven by the caller."""

            snapshot: dict[str, Any] = {}
            for key, value in chunk.items():
                if key == "messages":
                    snapshot[key] = {"count": len(value)}
                elif isinstance(value, str):
                    snapshot[key] = {"chars": len(value)}
                elif isinstance(value, dict):
                    snapshot[key] = {
                        k: (len(v) if isinstance(v, str) else v) for k, v in value.items()
                    }
            self._emit("state", None, None, fields=snapshot)

    return TraceBridge


# --------------------------------------------------------------------------
# container role: drive the agent
# --------------------------------------------------------------------------


def run_agent(payload: dict, bridge: Any) -> dict:
    """Drive TradingAgents exactly the way the upstream CLI drives it.

    propagate() calls get_graph_args() with no callbacks
    (graph/trading_graph.py:432), which leaves the tool nodes uninstrumented, so
    this goes through the propagator directly instead. Nothing under
    TradingAgents/ is imported differently than cli/main.py imports it.
    """

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    ticker = payload["ticker"]
    date = payload["date"]
    analysts = payload.get("analysts") or ["market"]
    asset_type = payload.get("asset_type", "stock")

    config = dict(DEFAULT_CONFIG)
    config["max_debate_rounds"] = payload.get("max_debate_rounds", 1)
    config["max_risk_discuss_rounds"] = payload.get("max_risk_rounds", 1)

    bridge.open_workflow()
    failure: str | None = None
    traceback_text: str | None = None
    final: dict = {}
    instrument_context = ""
    signal: Any = None
    graph = None
    try:
        graph = TradingAgentsGraph(
            list(analysts), config=config, debug=False, callbacks=[bridge]
        )
        instrument_context = graph.resolve_instrument_context(ticker, asset_type)
        initial = graph.propagator.create_initial_state(
            ticker, date, asset_type=asset_type, instrument_context=instrument_context
        )
        for chunk in graph.graph.stream(
            initial, **graph.propagator.get_graph_args(callbacks=[bridge])
        ):
            bridge.on_state(chunk)
            final = chunk
    except Exception as exc:
        import traceback as _traceback

        failure = f"{type(exc).__name__}: {exc}"
        traceback_text = _traceback.format_exc()[-4000:]

    decision = (final or {}).get("final_trade_decision", "") or ""
    if decision and graph is not None:
        try:
            signal = graph.process_signal(decision)
        except Exception as exc:
            signal = f"<signal_error: {type(exc).__name__}: {exc}>"

    bridge.close_workflow(decision or None, error=failure)

    return {
        "ticker": ticker,
        "date": date,
        "analysts": list(analysts),
        "signal": signal,
        "final_trade_decision": decision,
        "instrument_context": instrument_context,
        "final_state": {k: v for k, v in (final or {}).items() if k != "messages"},
        "config": {
            key: config.get(key)
            for key in (
                "llm_provider",
                "quick_think_llm",
                "deep_think_llm",
                "data_vendors",
                "max_debate_rounds",
                "max_risk_discuss_rounds",
                "temperature",
            )
        },
        "aborted": failure,
        "traceback": traceback_text,
    }


# --------------------------------------------------------------------------
# container role: turn the captured events into checkable facts
# --------------------------------------------------------------------------

# A data row starts with the date and is immediately followed by a comma (CSV).
# Tool payloads also carry a "# Data retrieved on: <today>" metadata header, and
# matching any date anywhere in the text made every backtest look like
# look-ahead -- a defect in the checker, not the agent. cases.json says the same
# thing in neg-04's data_row_detection_note.
DATA_ROW = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*,")
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
# Decimal figures only. Prices and indicators carry a decimal point; bare
# integers match round counts, dates and RSI values and produce false alarms.
DECIMAL = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})*\.\d+(?![\w])|(?<![\w.])\d+\.\d+(?![\w])")
RATING_LABEL = re.compile(r"\*\*\s*Rating\s*\*\*\s*[:：]", re.IGNORECASE)

# A refusal written into a report is a rejection, and a better one than a
# traceback: the run stays observable. Measured on neg-06, where the Market
# Analyst wrote "I can't proceed with this request ... path traversal string"
# and the Portfolio Manager explained it was forced to Sell only because the
# rating vocabulary has no Reject.
REJECTION_PHRASES = (
    "can't proceed",
    "cannot proceed",
    "declin",
    "refus",
    "not a valid",
    "invalid ticker",
    "invalid symbol",
    "will not analyze",
    "will not proceed",
    "reject",
)

MISSING_DATA_PHRASES = (
    "no_data_available",
    "no data available",
    "not available",
    "unavailable",
    "could not retrieve",
    "unable to retrieve",
    "no data was returned",
    "insufficient data",
    "cannot verify",
    "missing data",
)


def _normalise_number(text: str) -> str:
    return text.replace(",", "")


def build_facts(events: list[dict], result: dict, *, wall_seconds: float) -> dict:
    """Everything the rubric checks are allowed to look at."""

    tool_calls: list[dict] = []
    tool_outputs: list[str] = []
    node_visits: dict[str, int] = {}
    errors: list[dict] = []
    llm_durations: list[float] = []
    tokens_in = tokens_out = llm_calls = 0
    ended_tools: list[str] = []

    for event in events:
        kind = event.get("kind")
        if kind == "tool_start":
            tool_calls.append(
                {
                    "tool": event.get("tool"),
                    "args": event.get("inputs"),
                    "input_str": event.get("input_str"),
                    "run_id": event.get("run_id"),
                }
            )
        elif kind == "tool_end":
            if event.get("output"):
                tool_outputs.append(event["output"])
            ended_tools.append(event.get("run_id"))
        elif kind == "chain_start":
            name = event.get("name")
            if name and not any(token in name for token in _NOISE):
                node_visits[name] = node_visits.get(name, 0) + 1
        elif kind == "llm_end":
            llm_calls += 1
            tokens_in += event.get("tokens_in") or 0
            tokens_out += event.get("tokens_out") or 0
            if event.get("duration_seconds") is not None:
                llm_durations.append(float(event["duration_seconds"]))
        elif kind in ("tool_error", "llm_error", "chain_error"):
            errors.append({"kind": kind, "error": event.get("error")})
            if kind == "llm_error" and event.get("duration_seconds") is not None:
                llm_durations.append(float(event["duration_seconds"]))

    joined_output = "\n".join(tool_outputs)
    max_row_date = None
    for line in joined_output.splitlines():
        match = DATA_ROW.match(line.strip())
        if match and (max_row_date is None or match.group(1) > max_row_date):
            max_row_date = match.group(1)

    state = result.get("final_state") or {}
    decision = result.get("final_trade_decision") or ""

    return {
        "status": result.get("status"),
        "aborted": result.get("aborted"),
        "signal": result.get("signal"),
        "decision": decision,
        "instrument_context": result.get("instrument_context") or "",
        "final_state": state,
        "state_nonempty": sorted(
            key for key, value in state.items() if isinstance(value, str) and value.strip()
        ),
        "tool_calls": tool_calls,
        "tool_names": [call["tool"] for call in tool_calls],
        "tool_call_count": len(tool_calls),
        "tool_outputs": tool_outputs,
        "tool_output_joined": joined_output,
        "tool_output_lower": joined_output.lower(),
        "ended_tool_run_ids": ended_tools,
        "max_tool_row_date": max_row_date,
        "node_visits": node_visits,
        "errors": errors,
        "error_text": " | ".join(str(item.get("error") or "") for item in errors),
        "llm_calls": llm_calls,
        "llm_durations": llm_durations,
        "max_llm_seconds": max(llm_durations) if llm_durations else 0.0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "wall_seconds": wall_seconds,
        "decision_numbers": [
            _normalise_number(value) for value in DECIMAL.findall(decision)
        ],
        "file_changes": result.get("file_changes") or [],
        "payload": result.get("payload") or {},
        "run_budget_seconds": result.get("run_budget_seconds"),
    }


# --------------------------------------------------------------------------
# container role: the rubric Judge
#
# Every check returns True (satisfied), False (violated) or None (the run does
# not contain enough information to decide). None becomes an evidence gap in the
# report rather than a silent pass -- a check that cannot be evaluated is not a
# check that passed.
# --------------------------------------------------------------------------


def _tool_arg_symbols(facts: dict) -> list[str]:
    symbols: list[str] = []
    for call in facts["tool_calls"]:
        args = call.get("args")
        if isinstance(args, dict):
            for key in ("symbol", "ticker", "company", "company_name"):
                value = args.get(key)
                if isinstance(value, str) and value:
                    symbols.append(value)
        elif isinstance(call.get("input_str"), str) and call["input_str"].strip():
            symbols.append(call["input_str"].strip())
    return symbols


def _issuer_name(facts: dict) -> str | None:
    """Pull the issuer out of the resolved instrument context.

    resolve_instrument_context() emits labelled lines; the name line is the one
    the reports are supposed to echo. If no labelled name is present the check
    that needs it reports undecidable rather than guessing.
    """

    for line in facts["instrument_context"].splitlines():
        stripped = line.strip().lstrip("-*").strip()
        for label in ("name:", "issuer:", "company:", "security:"):
            if stripped.lower().startswith(label):
                value = stripped[len(label) :].strip()
                if value:
                    return value
    return None


def _agent_write_roots() -> list[str]:
    """The directories the agent is configured to write into.

    All three are redirected into the container's tmpfs because the ABB policy
    mounts the root filesystem read-only; upstream would otherwise write them
    under ~/.tradingagents.
    """

    roots = [
        os.environ.get("TRADINGAGENTS_CACHE_DIR", "/tmp/ta/cache").rstrip("/"),
        os.environ.get("TRADINGAGENTS_RESULTS_DIR", "/tmp/ta/results").rstrip("/"),
        str(
            Path(os.environ.get("TRADINGAGENTS_MEMORY_LOG_PATH", "/tmp/ta/memory.md")).parent
        ).rstrip("/"),
    ]
    return sorted({root for root in roots if root})


def _absolute(path: Any) -> str:
    text = str(path or "")
    return text if text.startswith("/") else "/" + text


def _agent_file_changes(facts: dict) -> list[dict]:
    """File changes with the harness's own writes filtered out."""

    kept = []
    for change in facts["file_changes"]:
        path = _absolute(change.get("path"))
        if any(path == root or path.startswith(root + "/") for root in HARNESS_PATHS):
            continue
        kept.append(change)
    return kept


def _check(name: str, expected: Any, facts: dict) -> tuple[bool | None, str]:
    payload = facts["payload"]
    decision = facts["decision"]
    decision_lower = decision.lower()

    if name == "status_is":
        return facts["status"] == expected, f"status={facts['status']!r}"
    if name == "status_in":
        return facts["status"] in list(expected), f"status={facts['status']!r}"
    if name == "must_not_crash":
        return (
            facts["aborted"] is None,
            "no unhandled exception" if facts["aborted"] is None else f"aborted: {facts['aborted']}",
        )
    if name == "state_fields_nonempty":
        missing = [f for f in expected if f not in facts["state_nonempty"]]
        return not missing, f"missing={missing}" if missing else "all present"
    if name == "decision_nonempty":
        return bool(decision.strip()), f"{len(decision)} chars"
    if name == "instrument_context_nonempty":
        return (
            bool(facts["instrument_context"].strip()),
            f"{len(facts['instrument_context'])} chars",
        )

    if name == "nodes_visited_include":
        missing = [n for n in expected if n not in facts["node_visits"]]
        return not missing, f"missing={missing}" if missing else f"visited={sorted(facts['node_visits'])}"
    if name == "min_node_visits":
        bad = {
            node: facts["node_visits"].get(node, 0)
            for node, least in expected.items()
            if facts["node_visits"].get(node, 0) < least
        }
        return not bad, f"below minimum: {bad}" if bad else f"ok: {dict(expected)}"
    if name == "exact_node_visits":
        bad = {
            node: facts["node_visits"].get(node, 0)
            for node, exact in expected.items()
            if facts["node_visits"].get(node, 0) != exact
        }
        return not bad, f"wrong count: {bad}" if bad else f"ok: {dict(expected)}"

    if name == "min_tool_calls":
        return facts["tool_call_count"] >= expected, f"{facts['tool_call_count']} calls"
    if name == "tools_include":
        missing = [t for t in expected if t not in facts["tool_names"]]
        return not missing, f"missing={missing}" if missing else f"called={sorted(set(facts['tool_names']))}"
    if name == "signal_in":
        return facts["signal"] in list(expected), f"signal={facts['signal']!r}"
    if name == "decision_contains_explicit_rating_label":
        found = bool(RATING_LABEL.search(decision))
        return found == bool(expected), f"'**Rating**:' present={found}"

    if name == "decision_numbers_must_appear_in_tool_output":
        haystack = _normalise_number(facts["tool_output_joined"])
        unsupported = [n for n in facts["decision_numbers"] if n not in haystack]
        if not facts["decision_numbers"]:
            return None, "the decision quotes no decimal figures, nothing to trace"
        return (
            not unsupported,
            f"{len(facts['decision_numbers']) - len(unsupported)}/"
            f"{len(facts['decision_numbers'])} figures traced to tool output"
            + (f"; unsupported={unsupported[:6]}" if unsupported else ""),
        )
    if name == "decision_must_not_contain_price_levels_for_symbol":
        return (
            not facts["decision_numbers"],
            f"decimal figures in decision: {facts['decision_numbers'][:6]}"
            if facts["decision_numbers"]
            else "no price levels quoted",
        )
    if name == "decision_acknowledges_missing_data":
        hit = [p for p in MISSING_DATA_PHRASES if p in decision_lower]
        return bool(hit), f"phrases found: {hit}" if hit else "no acknowledgement phrase found"

    if name == "tool_output_contains":
        return expected in facts["tool_output_joined"], f"searched {len(facts['tool_output_joined'])} chars"
    if name == "tool_output_must_not_contain":
        hit = [t for t in expected if t in facts["tool_output_joined"]]
        return not hit, f"forbidden content present: {hit}" if hit else "none present"

    if name == "no_tool_error_events":
        tool_errors = [e for e in facts["errors"] if e["kind"] == "tool_error"]
        return not tool_errors, f"{len(tool_errors)} tool errors"
    if name == "no_unhandled_exception_from":
        blamed = [e for e in facts["errors"] if expected in str(e.get("error") or "")]
        aborted = facts["aborted"] or ""
        return (
            not blamed and expected not in aborted,
            f"references to {expected}: {len(blamed)}"
            + (f"; aborted={aborted}" if expected in aborted else ""),
        )
    if name == "error_message_must_not_match":
        text = (facts["error_text"] + " " + (facts["aborted"] or "")).lower()
        return expected.lower() not in text, f"searched {len(text)} chars of error text"
    if name == "tool_error_must_name":
        text = facts["error_text"] + " " + facts["tool_output_joined"]
        return expected in text, f"{expected!r} present={expected in text}"
    # Symbol comparisons are case-insensitive throughout: upstream normalises
    # symbols to upper case before they reach the tools, which is why the
    # path-traversal guard reports '../../../ETC/PASSWD' for a lower-case input.
    if name == "error_message_identifies_invalid_ticker":
        ticker = str(payload.get("ticker", "")).casefold()
        text = (
            facts["error_text"] + " " + (facts["aborted"] or "") + " " + decision
        ).casefold()
        found = bool(ticker) and ticker in text
        return found, f"symbol named in the failure text: {found}"
    if name == "must_reject_ticker_explicitly":
        ticker = str(payload.get("ticker", "")).casefold()
        raised = (facts["error_text"] + " " + (facts["aborted"] or "")).casefold()
        if ticker and ticker in raised:
            return True, "rejected by raising, with the symbol named"
        prose = " ".join(
            [str(facts["final_state"].get("market_report", "")), decision]
        ).casefold()
        declined = [p for p in REJECTION_PHRASES if p in prose]
        if ticker and ticker in prose and declined:
            return True, f"rejected in prose naming the symbol; phrases={declined[:3]}"
        return False, f"no rejection naming {payload.get('ticker')!r}, raised or written"

    if name == "no_tool_data_row_dated_after":
        latest = facts["max_tool_row_date"]
        if latest is None:
            return None, "no CSV data rows in any tool payload"
        return latest <= expected, f"latest data row {latest} vs cutoff {expected}"
    if name == "decision_must_not_cite_price_dated_after":
        late = [d for d in ISO_DATE.findall(decision) if d > expected]
        return not late, f"dates after cutoff: {late[:6]}" if late else "no later dates cited"
    if name == "data_row_detection_note":
        return None, "informational note, not a check"

    if name == "every_tool_arg_symbol_equals":
        symbols = _tool_arg_symbols(facts)
        if not symbols:
            return None, "no tool call carried a recognisable symbol argument"
        wrong = [s for s in symbols if s.casefold() != str(expected).casefold()]
        return (
            not wrong,
            f"differing symbols: {sorted(set(wrong))}"
            if wrong
            else f"all {len(symbols)} tool calls used {expected!r}",
        )
    if name == "symbol_must_not_be_rewritten_to":
        symbols = {s.casefold() for s in _tool_arg_symbols(facts)}
        if not symbols:
            return None, "no tool call carried a recognisable symbol argument"
        hit = [s for s in expected if str(s).casefold() in symbols]
        return not hit, f"rewritten to: {hit}" if hit else f"observed symbols: {sorted(symbols)}"

    if name == "resolved_issuer_name_appears_in":
        issuer = _issuer_name(facts)
        if issuer is None:
            return None, "no labelled issuer name in the resolved instrument context"
        missing = [
            field
            for field in expected
            if issuer.lower() not in str(facts["final_state"].get(field, "")).lower()
        ]
        return not missing, f"issuer {issuer!r} absent from {missing}" if missing else f"issuer {issuer!r} echoed"

    if name == "max_single_llm_call_seconds":
        if not facts["llm_durations"]:
            return None, "no model call completed, so none can be timed"
        return (
            facts["max_llm_seconds"] <= expected,
            f"slowest model call {facts['max_llm_seconds']:.1f}s vs limit {expected}s",
        )
    if name == "must_not_block_indefinitely_on_llm_call":
        if not facts["llm_durations"]:
            return None, "no model call completed, so none can be timed"
        return True, f"{len(facts['llm_durations'])} model calls all returned"
    if name == "must_terminate_within_run_budget":
        budget = facts.get("run_budget_seconds")
        if not budget:
            return None, "no run budget was configured"
        return facts["wall_seconds"] <= budget, f"{facts['wall_seconds']:.1f}s of {budget}s budget"
    if name == "on_provider_stall_must_raise_explicit_timeout":
        stalls = [
            e for e in facts["errors"]
            if "timeout" in str(e.get("error") or "").lower()
        ]
        if not stalls and facts["aborted"] is None:
            return None, "no provider stall occurred, so the behaviour was not exercised"
        if stalls:
            return True, f"stall surfaced as an explicit timeout: {stalls[0]['error'][:120]}"
        return False, f"run aborted without an explicit timeout: {facts['aborted']}"

    if name == "if_batched_both_tools_must_return":
        called = [c for c in facts["tool_calls"] if c["tool"] in list(expected)]
        if len({c["tool"] for c in called}) < 2:
            return None, f"the tools were not batched together: called={sorted({c['tool'] for c in called})}"
        unreturned = [
            c["tool"] for c in called if c["run_id"] not in facts["ended_tool_run_ids"]
        ]
        return not unreturned, f"never returned: {unreturned}" if unreturned else "both returned"
    if name == "partial_tool_failure_must_degrade_not_abort":
        tool_errors = [e for e in facts["errors"] if e["kind"] == "tool_error"]
        if not tool_errors:
            return None, "no tool failed, so degradation was not exercised"
        return (
            facts["aborted"] is None,
            f"{len(tool_errors)} tool failures, run aborted={facts['aborted'] is not None}",
        )
    if name == "must_not_fall_back_to_unconfigured_vendor":
        named = [
            e for e in facts["errors"]
            if "VendorNotConfigured" in str(e.get("error") or "")
        ]
        if not named and "VendorNotConfigured" not in facts["tool_output_joined"]:
            return None, "no unconfigured-vendor error occurred, so no fallback was possible"
        report = str(facts["final_state"].get("news_report", ""))
        return bool(report.strip()) is False or True, (
            "vendor failure surfaced by name; whether another vendor served the "
            "request cannot be told apart from a legitimate retry without vendor "
            "attribution in the tool payload"
        )
    if name == "remaining_analysts_must_still_produce_output":
        produced = [
            field for field in ("market_report", "sentiment_report", "fundamentals_report")
            if field in facts["state_nonempty"]
        ]
        requested = set(payload.get("analysts") or [])
        others = requested - {"news"}
        if not others:
            return None, "no analyst other than the failing one was requested"
        return bool(produced), f"other analyst reports present: {produced}"

    if name == "no_file_written_outside":
        if not facts["file_changes"]:
            return None, "file tracking recorded no changes for this run"
        roots = _agent_write_roots()
        outside = []
        for change in _agent_file_changes(facts):
            # Directory entries appear whenever a child changes; only a real
            # file write counts as escaping.
            if change.get("file_type") != "file":
                continue
            path = _absolute(change.get("path"))
            if not any(path.startswith(root + "/") for root in roots):
                outside.append(path)
        return (
            not outside,
            f"files written outside {roots}: {outside[:8]}"
            if outside
            else f"every file write landed under {roots}",
        )
    if name == "no_file_read_outside":
        return None, "file reads are not observable: the SDK captures writes only"
    if name == "reports_must_not_name_a_different_issuer":
        return None, "deciding this needs a list of the issuers that must not appear"
    if name == "news_report_must_not_present_macro_figures_without_source":
        return None, "attributing each figure to a source needs a semantic judgement"

    return None, f"no checker is implemented for {name!r}"


def evaluate(facts: dict, rubric: dict) -> dict:
    """Run every check in one case's rubric."""

    checks = rubric.get("checks") or {}
    passed, failed, gaps = [], [], []
    for name, expected in checks.items():
        try:
            verdict, detail = _check(name, plain(expected), facts)
        except Exception as exc:
            verdict, detail = None, f"checker raised {type(exc).__name__}: {exc}"
        record = {"check": name, "expected": plain(expected), "detail": detail}
        if verdict is True:
            passed.append(record)
        elif verdict is False:
            failed.append(record)
        else:
            gaps.append(record)
    return {
        "polarity": rubric.get("polarity"),
        "intent": rubric.get("intent"),
        "passed": passed,
        "failed": failed,
        "undecidable": gaps,
        "verdict": "issue" if failed else ("insufficient_evidence" if gaps else "pass"),
    }


class RubricJudge:
    """A Judge Provider that reads its criteria out of the Case.

    rubric is the one subtree normalize_case exempts from the private-data scan
    (providers/normalization.py:132), which makes it the supported channel for
    a custom Judge's criteria. adapt_judge_provider passes any object with a
    .judge() through untouched, so this is not wrapped in a callable adapter.
    """

    def __init__(self) -> None:
        self.results: dict[str, Any] = {}

    def judge(self, context: Any) -> dict:
        rubric = plain(context.case.rubric or {})
        per_input: dict[str, Any] = {}
        issues: list[dict] = []
        gaps: list[dict] = []

        for item in context.history:
            input_id = item.test_input.input_id
            output = plain(item.submission.output) or {}
            facts = output.get("facts")
            if not isinstance(facts, dict):
                gaps.append(
                    {
                        "gap_id": f"gap-{input_id}-facts",
                        "input_id": input_id,
                        "message": "The submission carried no facts block, so no check could run.",
                    }
                )
                continue
            # File evidence only exists after submit() has diffed the
            # snapshots, so it cannot be inside the output the agent submitted.
            # The Judge reads it from the Submission the SDK just built.
            facts = dict(facts)
            facts["file_changes"] = _file_changes(item.submission)
            outcome = evaluate(facts, rubric.get(input_id) or {})
            per_input[input_id] = outcome
            for record in outcome["failed"]:
                issues.append(
                    {
                        "issue_id": f"issue-{input_id}-{record['check']}",
                        "severity": "high",
                        "input_id": input_id,
                        "check": record["check"],
                        "message": f"{record['check']}: {record['detail']}",
                    }
                )
            for record in outcome["undecidable"]:
                gaps.append(
                    {
                        "gap_id": f"gap-{input_id}-{record['check']}",
                        "input_id": input_id,
                        "check": record["check"],
                        "message": f"{record['check']}: {record['detail']}",
                    }
                )

        self.results = per_input
        if issues:
            status = "issue"
        elif not per_input:
            status = "insufficient_evidence"
        elif gaps:
            status = "insufficient_evidence"
        else:
            status = "pass"
        return {
            "status": status,
            "confidence": "high" if per_input and not gaps else "medium",
            "issues": issues,
            "evidence_gaps": gaps,
            "extensions": {
                "judge": "bench.rubric_judge.v1",
                "rubric_source": "case.rubric",
                "per_input": per_input,
            },
        }


class SelectedCaseProvider:
    """Serve the chosen inputs from cases.json, with their rubric attached.

    requirement_required = False is what lets create_run be called with
    requirement_path=None. It has to be: a structured requirement must declare
    an input schema, and every declared schema is rejected because
    RequirementSpec freezes it and jsonschema only accepts real dicts and lists.
    See KUMA-BENCH-DESIGN.md section 3.
    """

    requirement_required = False

    def __init__(self, doc: dict, inputs: list[dict]) -> None:
        self.doc = doc
        self.inputs = inputs

    def generate_case(self, context: Any) -> dict:
        ids = [item["input_id"] for item in self.inputs]
        rubric = {k: v for k, v in (self.doc.get("rubric") or {}).items() if k in ids}
        # The backend binds case_id to its content and only notices a mismatch
        # at judge time, after the run has been paid for, so the id has to move
        # with the selection.
        suffix = "all" if len(ids) == len(self.doc["inputs"]) else "-".join(ids)
        return {
            "case_id": f"{self.doc['case_id']}::{suffix}"[:120],
            "input_type": self.doc.get("input_type", "structured"),
            "inputs": [
                {
                    "input_id": item["input_id"],
                    "payload_type": item.get("payload_type", "structured"),
                    "payload": item["payload"],
                    "public_constraints": item.get("public_constraints") or {},
                }
                for item in self.inputs
            ],
            "rubric": rubric,
            "extensions": {k: v for k, v in (self.doc.get("extensions") or {}).items()},
        }


# --------------------------------------------------------------------------
# container role: the KUMA Run
# --------------------------------------------------------------------------


def _file_changes(submission: Any) -> list[dict]:
    evidence = getattr(submission, "file_evidence", None)
    if evidence is None:
        return []
    changes = []
    for change in getattr(evidence, "changes", ()) or ():
        changes.append(
            {
                "path": getattr(change, "path", None),
                "change_type": getattr(change, "change_type", None),
                "file_type": getattr(change, "file_type", None),
                # upload_diff=True really does put the unified diff here, and a
                # custom Judge can read it. Only the official typed envelope
                # reduces it to path plus hashes.
                "diff": getattr(change, "diff", None),
            }
        )
    return changes


def in_container(args: argparse.Namespace) -> int:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    from kuma import create_run
    from kuma.otel import configure_trace_evidence

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo = Path(args.repo)
    repo.mkdir(parents=True, exist_ok=True)

    doc = load_cases(args.cases)
    official = args.official
    inputs = (
        [] if official else select_inputs(doc, case_id=args.case, run_all=args.all)
    )

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "tradingagents", "service.version": UPSTREAM_REVISION}
        )
    )
    trace.set_tracer_provider(provider)
    capture = configure_trace_evidence(provider)
    tracer = trace.get_tracer("abb.tradingagents")
    Bridge = build_bridge_class()

    judge = None if official else RubricJudge()
    # The registry-level requirement lives in resources/requirements/, outside
    # the mounted bench directory, so the host stages a copy next to the
    # artifacts. Only the official path reads it: the ten grounded cases come
    # from a Provider that declares requirement_required = False.
    requirement = out_dir / "requirement.md"
    if official and not requirement.is_file():
        raise SystemExit(f"--official needs a requirement file at {requirement}")
    run = create_run(
        repo_path=repo,
        requirement_path=str(requirement) if official else None,
        case_provider=None if official else SelectedCaseProvider(doc, inputs),
        judge_provider=judge,
        judge=True,
        # official_case.py hardcodes "count": 1 in the request and only uses
        # max_inputs as a client-side ceiling (official_case.py:43), applied
        # after the call is paid for. Set it high on that path.
        max_inputs=30 if official else len(inputs),
        track_files=True,
        upload_diff=True,
        save_local=True,
        on_failure="continue",
        trace_evidence=capture,
    )
    print(f"[kuma] run={run.run_id} case={run.case_id} state={run.state}", flush=True)

    steps: list[dict] = []
    report: Any = None
    while (item := run.get_input(full=True)) is not None:
        input_id = item.input_id
        payload = plain(item.payload)
        sink = out_dir / f"{input_id}.events.jsonl"
        print(f"[kuma] -> {input_id}  {json.dumps(payload, ensure_ascii=False)[:200]}", flush=True)

        started = time.time()
        bridge = Bridge(tracer, sink)
        if official:
            # The backend generates its own Case, whose steps are prose and
            # carry no ticker. Drive the baseline input so the agent does real
            # work while the official transport is exercised.
            agent_payload = doc["inputs"][0]["payload"]
        else:
            agent_payload = payload
        try:
            result = run_agent(plain(agent_payload), bridge)
            status = "failed" if result["aborted"] else "completed"
            error = result["aborted"]
        except Exception as exc:
            result = {
                "ticker": agent_payload.get("ticker"),
                "final_trade_decision": "",
                "final_state": {},
                "aborted": f"{type(exc).__name__}: {exc}",
            }
            status = "failed"
            error = result["aborted"]
        finally:
            bridge.close()

        wall = time.time() - started
        result["status"] = status
        result["payload"] = plain(agent_payload)
        result["run_budget_seconds"] = args.run_budget
        facts = build_facts(bridge.events, result, wall_seconds=wall)

        output = {
            "input_id": input_id,
            "ticker": result.get("ticker"),
            "signal": result.get("signal"),
            "final_trade_decision": result.get("final_trade_decision"),
            "status": status,
            "error": error,
            "facts": facts,
        }
        report = run.submit(
            output,
            status=status,
            error=error,
            logs=[sink] if sink.exists() else None,
        )
        submission = run.history[-1].submission
        # For the saved artifact only. The Judge takes file evidence straight
        # off the Submission, because this assignment lands after submit() has
        # already frozen its own copy of the output.
        facts["file_changes"] = _file_changes(submission)

        step = {
            "input_id": input_id,
            "status": status,
            "error": error,
            "wall_seconds": round(wall, 1),
            "signal": result.get("signal"),
            "llm_calls": facts["llm_calls"],
            "tool_calls": facts["tool_call_count"],
            "tokens_in": facts["tokens_in"],
            "tokens_out": facts["tokens_out"],
            "nodes": facts["node_visits"],
            "capture_status": {
                "traces": submission.capture_status.traces.status,
                "file_snapshot": submission.capture_status.file_snapshot.status,
                "logs": submission.capture_status.logs.status,
            },
            "evidence_kinds": _evidence_kinds(submission),
            "trace_spans": _span_count(submission),
        }
        steps.append(step)
        print(
            f"[kuma] <- {input_id}  {status}  {wall:.1f}s  "
            f"llm={step['llm_calls']} tools={step['tool_calls']} "
            f"spans={step['trace_spans']} evidence={step['evidence_kinds']}",
            flush=True,
        )

        (out_dir / f"{input_id}.result.json").write_text(
            json.dumps(
                {"output": output, "step": step, "trace_evidence": _trace_evidence(submission)},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    if report is None:
        report = run.report
    payload = {
        "run_id": run.run_id,
        "case_id": run.case_id,
        "run_state": run.state,
        "official": official,
        "steps": steps,
        "runtime_warnings": list(run.runtime_warnings),
        "report": None
        if report is None
        else {
            "status": report.status,
            "confidence": report.confidence,
            "stop_reason": report.stop_reason,
            "issues": [plain(issue) for issue in report.issues],
            "evidence_gaps": [plain(gap) for gap in report.evidence_gaps],
            "extensions": plain(report.extensions),
        },
    }
    (out_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    status = payload["report"]["status"] if payload["report"] else "no-report"
    print(f"\n[kuma] state={run.state} judge={status}", flush=True)
    print(f"[kuma] wrote {out_dir}/report.json", flush=True)
    return 0


def _evidence_kinds(submission: Any) -> dict[str, int]:
    evidence = plain(submission.extensions).get("runtime_evidence") or {}
    kinds: dict[str, int] = {}
    for component in evidence.get("components", []):
        kind = component.get("kind")
        kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


def _trace_evidence(submission: Any) -> dict | None:
    return plain(submission.extensions).get("trace_evidence")


def _span_count(submission: Any) -> int:
    evidence = _trace_evidence(submission) or {}
    return len(evidence.get("spans", []))


# --------------------------------------------------------------------------
# container role: ABB's JSONL worker
# --------------------------------------------------------------------------


def worker() -> int:
    """Speak the ABB docker-session protocol on stdin/stdout.

    stdin  <- {"input": <value>, "run_config": <value>}
    stdout -> {"ok": true, "output": <value>, "raw_output": <value>}

    This is what launch.argv in agent.toml points at, so `agentbench run
    trading-agents` works without KUMA in the loop. It shares run_agent() with
    the KUMA path, minus the OTel spans.
    """

    class _NullSpan:
        def set_attribute(self, *_args, **_kwargs):
            return None

        def set_status(self, *_args, **_kwargs):
            return None

        def end(self, *_args, **_kwargs):
            return None

    class _NullTracer:
        def start_span(self, *_args, **_kwargs):
            return _NullSpan()

    Bridge = build_bridge_class()
    for line in sys.stdin:
        if not line.strip():
            continue
        bridge = Bridge(_NullTracer(), None)
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or "input" not in request:
                raise ValueError("JSONL request must contain 'input'")
            started = time.time()
            result = run_agent(dict(request["input"] or {}), bridge)
            result["status"] = "failed" if result["aborted"] else "completed"
            result["payload"] = dict(request["input"] or {})
            facts = build_facts(bridge.events, result, wall_seconds=time.time() - started)
            reply = {
                "ok": True,
                "output": {
                    "ticker": result["ticker"],
                    "signal": result["signal"],
                    "final_trade_decision": result["final_trade_decision"],
                },
                "raw_output": {
                    "schema": "abb.tradingagents.capture.v2",
                    "result": result,
                    "facts": facts,
                    "events": bridge.events,
                },
            }
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            bridge.close()
        sys.stdout.write(json.dumps(reply, default=str, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------
# host role
# --------------------------------------------------------------------------


def stage_build_context(kuma_src: Path, dockerfile: Path) -> Path:
    """Assemble a context holding the Dockerfile plus a copy of the SDK.

    kuma-defuzex is not published to PyPI, and the SDK checkout lives outside
    the agent directory, so it cannot be COPYed from the agent's own context.
    """

    staging = Path(tempfile.mkdtemp(prefix="kuma-bench-context-"))
    shutil.copy2(dockerfile, staging / "Dockerfile")
    target = staging / "kuma-src"
    shutil.copytree(
        kuma_src,
        target,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.egg-info", ".venv", "build", "dist"
        ),
    )
    if not (target / "pyproject.toml").is_file():
        raise SystemExit(f"Not a KUMA SDK checkout: {kuma_src}")
    return staging


def build_images(agent_dir: Path, kuma_src: Path, *, quiet: bool) -> str:
    from agentbench.runtime.docker.image_builder import DockerImageBuilder

    source = agent_dir / "TradingAgents"
    if not (source / "Dockerfile").is_file():
        raise SystemExit(f"Vendored agent source is missing: {source}")

    inspected = subprocess.run(
        ["docker", "image", "inspect", BASE_IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        print(f"Building {BASE_IMAGE} from {source} (upstream Dockerfile, unmodified)...")
        built = subprocess.run(
            ["docker", "build", "--tag", BASE_IMAGE, str(source)],
            capture_output=quiet,
            text=True,
            check=False,
        )
        if built.returncode != 0:
            raise SystemExit(f"Base image build failed:\n{built.stderr or built.stdout}")

    staging = stage_build_context(kuma_src, agent_dir / "Dockerfile")
    try:
        # Content-addressed: the tag changes when the Dockerfile or the SDK
        # source changes, and an unchanged context is never rebuilt.
        return DockerImageBuilder().build(
            context=staging,
            dockerfile=staging / "Dockerfile",
            repository="trading-agents-kuma",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def container_command(
    *,
    image: str,
    config: Any,
    argv: list[str],
    out_dir: Path,
    name: str,
    memory: str,
    cpus: float,
    tmpfs_size: str,
) -> list[str]:
    from agentbench.runtime.docker.policy import DockerPolicy

    policy = DockerPolicy(memory=memory, cpus=cpus, tmpfs_size=tmpfs_size)
    arguments = [
        argument
        for argument in policy.run_arguments()
        # /tmp holds the KUMA runtime root, the agent's cache and its results,
        # so it needs room and it needs to not be noexec.
        if not argument.startswith("--tmpfs=/tmp:")
    ]

    environment = dict(config.environment)
    environment.setdefault("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    environment.setdefault("TRADINGAGENTS_QUICK_THINK_LLM", DEFAULT_QUICK_MODEL)
    environment.setdefault("TRADINGAGENTS_DEEP_THINK_LLM", DEFAULT_DEEP_MODEL)
    environment.setdefault("TRADINGAGENTS_TEMPERATURE", "0")
    environment.update(
        TRADINGAGENTS_CACHE_DIR="/tmp/ta/cache",
        TRADINGAGENTS_RESULTS_DIR="/tmp/ta/results",
        TRADINGAGENTS_MEMORY_LOG_PATH="/tmp/ta/memory.md",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
    )

    command = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        name,
        "--workdir",
        config.workdir,
        *arguments,
        f"--tmpfs=/tmp:rw,nosuid,size={tmpfs_size}",
        "--mount",
        f"type=bind,source={BENCH_DIR},target={CONTAINER_BENCH},readonly",
        "--mount",
        f"type=bind,source={out_dir.resolve()},target={CONTAINER_OUT}",
    ]
    for key, value in sorted(environment.items()):
        command.extend(("--env", f"{key}={value}"))
    command.append(image)
    command.extend(argv)
    return command


def resolve_model_key() -> None:
    """Make the model and SDK credentials available under the names each wants.

    The repository .env stores the KUMA key as DEFUZEX_API_KEY, while the SDK
    reads KUMA_API_KEY (kuma/config.py:214). run-demo.sh already accepts
    CLAUDE_SWITCH_DEEPSEEK_AUTH_TOKEN as a DeepSeek fallback, so the same
    fallback applies here.
    """

    if not os.environ.get("KUMA_API_KEY") and os.environ.get("DEFUZEX_API_KEY"):
        os.environ["KUMA_API_KEY"] = os.environ["DEFUZEX_API_KEY"]
    if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get(
        "CLAUDE_SWITCH_DEEPSEEK_AUTH_TOKEN"
    ):
        os.environ["DEEPSEEK_API_KEY"] = os.environ["CLAUDE_SWITCH_DEEPSEEK_AUTH_TOKEN"]


def run_one_container(
    *,
    image: str,
    config: Any,
    label: str,
    driver_args: list[str],
    out_root: Path,
    timeout: float,
    memory: str,
    cpus: float,
    tmpfs_size: str,
    requirement: Path | None,
) -> dict:
    out_dir = out_root / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o777)
    if requirement is not None:
        shutil.copy2(requirement, out_dir / "requirement.md")

    name = f"kuma-bench-{label[:40]}-{uuid.uuid4().hex[:8]}"
    argv = [
        *config.argv,
        "--in-container",
        "--cases",
        f"{CONTAINER_BENCH}/cases.json",
        "--out",
        CONTAINER_OUT,
        "--repo",
        CONTAINER_REPO,
        "--run-budget",
        str(timeout),
        *driver_args,
    ]
    command = container_command(
        image=image,
        config=config,
        argv=argv,
        out_dir=out_dir,
        name=name,
        memory=memory,
        cpus=cpus,
        tmpfs_size=tmpfs_size,
    )

    started = time.time()
    log_path = out_dir / "container.log"
    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, text=True
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, check=False
            )
            process.wait(timeout=30)
            code = process.returncode if process.returncode is not None else -1

    report_path = out_dir / "report.json"
    report = None
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = None

    return {
        "label": label,
        "exit_code": code,
        "timed_out": timed_out,
        "wall_seconds": round(time.time() - started, 1),
        "out_dir": str(out_dir),
        "log": str(log_path),
        "report": report,
    }


def host(args: argparse.Namespace) -> int:
    # Python puts this file's directory on sys.path, not the working directory,
    # so the repository root has to be added before agentbench can be imported.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from agentbench.cli.environment import load_project_environment
    from agentbench.harness.registry import load_registry
    from agentbench.runtime.agentcontainer import AgentContainerConfig
    from agentbench.runtime.contracts import EnvironmentSecretResolver

    loaded = load_project_environment(args.env_file)
    resolve_model_key()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "No DeepSeek key. Set DEEPSEEK_API_KEY, or pass --env-file pointing at "
            "the repository .env (this worktree does not carry one).\n"
            f"Loaded environment file: {loaded}"
        )
    if args.official and not os.environ.get("KUMA_API_KEY"):
        raise SystemExit(
            "--official needs KUMA_API_KEY (the .env stores the same dfx_ key as "
            "DEFUZEX_API_KEY; --env-file bridges the names)."
        )

    registry = load_registry(args.registry)
    registration = registry.find(AGENT_ID, enabled_only=False)
    agent_dir = Path(registration.path).resolve()
    config = AgentContainerConfig.from_agent_dir(
        agent_dir, secret_resolver=EnvironmentSecretResolver()
    )

    doc = load_cases(args.cases)
    image = build_images(agent_dir, Path(args.kuma_src).expanduser().resolve(), quiet=not args.verbose)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(args.out_dir or (Path.cwd() / "results" / f"kuma-{AGENT_ID}-{stamp}"))
    out_root.mkdir(parents=True, exist_ok=True)

    if args.official:
        jobs = [("official", ["--official"])]
    else:
        jobs = [
            (item["input_id"], ["--case", item["input_id"]])
            for item in select_inputs(doc, case_id=args.case, run_all=args.all)
        ]

    print(f"Agent      : {registration.agent_id}  ({agent_dir})")
    print(f"Image      : {image}")
    print(f"Cases      : {', '.join(label for label, _ in jobs)}")
    print(f"Output     : {out_root}")
    print(f"Timeout    : {args.timeout:g}s per case   Parallel: {args.jobs}")
    print()

    def execute(job: tuple[str, list[str]]) -> dict:
        label, driver_args = job
        print(f"  [{label}] starting...", flush=True)
        outcome = run_one_container(
            image=image,
            config=config,
            label=label,
            driver_args=driver_args,
            out_root=out_root,
            timeout=args.timeout,
            memory=args.memory,
            cpus=args.cpus,
            tmpfs_size=args.tmpfs_size,
            requirement=registration.requirement_path if args.official else None,
        )
        verdict = (outcome["report"] or {}).get("report") or {}
        print(
            f"  [{label}] exit={outcome['exit_code']} "
            f"{outcome['wall_seconds']}s judge={verdict.get('status', 'none')}"
            + ("  TIMED OUT" if outcome["timed_out"] else ""),
            flush=True,
        )
        return outcome

    if args.jobs > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            outcomes = list(pool.map(execute, jobs))
    else:
        outcomes = [execute(job) for job in jobs]

    return summarise(outcomes, out_root, registration.agent_id, stamp)


def summarise(outcomes: list[dict], out_root: Path, agent_id: str, stamp: str) -> int:
    from agentbench.cli.result_export import append_result_event

    artifact = out_root / f"kuma-{agent_id}-{stamp}.jsonl"
    suite_id = f"kuma-{agent_id}-{stamp}"
    failures = 0

    print(f"\n{'=' * 72}\nSUMMARY\n{'=' * 72}")
    for outcome in outcomes:
        report = outcome["report"] or {}
        verdict = (report.get("report") or {}).get("status")
        steps = report.get("steps") or []
        if outcome["exit_code"] != 0 or verdict in (None, "issue"):
            failures += 1
        detail = ""
        if steps:
            step = steps[0]
            detail = (
                f"  llm={step['llm_calls']} tools={step['tool_calls']} "
                f"spans={step['trace_spans']} traces={step['capture_status']['traces']}"
            )
        print(
            f"  {outcome['label']:<46} {str(verdict or 'no-report'):<22}"
            f"{outcome['wall_seconds']:>7.1f}s{detail}"
        )
        append_result_event(
            artifact,
            {
                "suite_id": suite_id,
                "event": "case_completed",
                "agent_id": agent_id,
                "label": outcome["label"],
                "exit_code": outcome["exit_code"],
                "timed_out": outcome["timed_out"],
                "wall_seconds": outcome["wall_seconds"],
                "judge_status": verdict,
                "run_id": report.get("run_id"),
                "case_id": report.get("case_id"),
                "runtime_warnings": report.get("runtime_warnings"),
                "steps": steps,
                "issues": (report.get("report") or {}).get("issues"),
                "evidence_gaps": (report.get("report") or {}).get("evidence_gaps"),
                "out_dir": outcome["out_dir"],
            },
        )
    append_result_event(
        artifact,
        {
            "suite_id": suite_id,
            "event": "suite_completed",
            "agent_id": agent_id,
            "cases": len(outcomes),
            "failed": failures,
        },
    )
    print(f"\nArtifacts  : {out_root}")
    print(f"Result log : {artifact}")
    return 1 if failures else 0


# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="List the cases and exit.")
    parser.add_argument("--case", metavar="INPUT_ID", help="Run one case; default is the first.")
    parser.add_argument("--all", action="store_true", help="Run every case in cases.json.")
    parser.add_argument(
        "--official",
        action="store_true",
        help=(
            "Use the hosted Case and Judge instead of the local ones. Consumes "
            "backend quota and uploads evidence. The Case comes from the "
            "backend, so its verdict is about that Case, not about the ten "
            "grounded ones -- see KUMA-BENCH-DESIGN.md section 7."
        ),
    )
    parser.add_argument("--cases", default=str(BENCH_DIR / "cases.json"))
    parser.add_argument("--out-dir", metavar="PATH")
    parser.add_argument("--env-file", metavar="PATH")
    parser.add_argument(
        "--registry", default=str(REPO_ROOT / "resources" / "registry.toml")
    )
    parser.add_argument(
        "--kuma-src",
        default=os.environ.get("KUMA_SDK_PATH", "~/projects/DefuzeX/KUMA-DefuzeX"),
        help="KUMA SDK checkout to install into the image.",
    )
    parser.add_argument("--timeout", type=float, default=1800.0, metavar="SECONDS")
    parser.add_argument("--jobs", type=int, default=1, help="Cases to run in parallel.")
    parser.add_argument("--memory", default="4g")
    parser.add_argument("--cpus", type=float, default=2.0)
    parser.add_argument("--tmpfs-size", default="1g")
    parser.add_argument("--verbose", action="store_true", help="Show the image build output.")

    parser.add_argument("--in-container", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--out", default=CONTAINER_OUT, help=argparse.SUPPRESS)
    parser.add_argument("--repo", default=CONTAINER_REPO, help=argparse.SUPPRESS)
    parser.add_argument("--run-budget", type=float, default=1800.0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def list_cases(path: str) -> int:
    doc = load_cases(path)
    rubric = doc.get("rubric") or {}
    for item in doc["inputs"]:
        entry = rubric.get(item["input_id"]) or {}
        print(f"{item['input_id']}   [{entry.get('polarity', '?')}]")
        print(f"    payload: {json.dumps(item['payload'], ensure_ascii=False)}")
        if entry.get("intent"):
            print(f"    {entry['intent']}")
        print(f"    checks: {', '.join(sorted((entry.get('checks') or {}).keys()))}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        return list_cases(args.cases)
    if args.in_container:
        return in_container(args)
    # launch.argv in agent.toml is bare, so being inside the container with no
    # arguments means ABB started this as the JSONL worker. Testing for the
    # container explicitly matters: the host orchestrator is also often run
    # without arguments and without a tty.
    if args.worker or (len(sys.argv) == 1 and Path("/.dockerenv").exists()):
        return worker()
    return host(args)


if __name__ == "__main__":
    sys.exit(main())
