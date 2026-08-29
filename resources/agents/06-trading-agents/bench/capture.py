"""Full-fidelity capture for TradingAgents with zero changes to upstream source.

Everything here rides on injection points the upstream already exposes:
  - TradingAgentsGraph(callbacks=[...])            -> binds to both LLM clients
  - Propagator.get_graph_args(callbacks=[...])     -> covers the tool nodes
  - graph.stream(..., stream_mode="values")        -> full state per step

No monkeypatching, no forked files.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _text(value: Any, limit: int | None = None) -> str:
    s = value if isinstance(value, str) else str(value)
    return s if limit is None else s[:limit]


def _msg_to_json(m: Any) -> dict[str, Any]:
    """Serialize a LangChain message without losing tool calls or metadata."""
    out: dict[str, Any] = {
        "type": type(m).__name__,
        "role": getattr(m, "type", None),
        "content": _text(getattr(m, "content", "")),
    }
    for attr in ("name", "id", "tool_call_id"):
        v = getattr(m, attr, None)
        if v:
            out[attr] = v
    tc = getattr(m, "tool_calls", None)
    if tc:
        out["tool_calls"] = [
            {"name": c.get("name"), "args": c.get("args"), "id": c.get("id")}
            if isinstance(c, dict)
            else {"name": getattr(c, "name", None), "args": getattr(c, "args", None)}
            for c in tc
        ]
    usage = getattr(m, "usage_metadata", None)
    if usage:
        out["usage_metadata"] = usage
    rm = getattr(m, "response_metadata", None)
    if rm:
        out["response_metadata"] = {
            k: rm[k] for k in ("finish_reason", "model_name", "model") if k in rm
        }
    return out


class FullCapture(BaseCallbackHandler):
    """Records every callback the LangChain runtime emits, with full payloads."""

    # Without this LangChain omits raw prompt/completion text from the hooks.
    raise_error = False

    def __init__(self, sink_path: str | None = None, *, keep_content: bool = True):
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self.sink_path = sink_path
        self.keep_content = keep_content
        self.t0 = time.time()
        self._sink = open(sink_path, "w", encoding="utf-8") if sink_path else None

    # ---------- plumbing ----------

    def _emit(self, kind: str, run_id: Any = None, parent: Any = None, **payload):
        ev = {
            "seq": len(self.events),
            "t": round(time.time() - self.t0, 3),
            "kind": kind,
            "run_id": str(run_id) if run_id else None,
            "parent_run_id": str(parent) if parent else None,
            **payload,
        }
        self.events.append(ev)
        if self._sink:
            self._sink.write(json.dumps(ev, default=str, ensure_ascii=False) + "\n")
            self._sink.flush()

    def close(self):
        if self._sink:
            self._sink.close()
            self._sink = None

    # ---------- LLM ----------

    def on_chat_model_start(self, serialized, messages, *, run_id=None, parent_run_id=None, **kw):
        self._emit(
            "chat_model_start", run_id, parent_run_id,
            model=(serialized or {}).get("kwargs", {}).get("model_name")
            or (serialized or {}).get("name"),
            invocation_params=kw.get("invocation_params"),
            tools=[t.get("function", {}).get("name")
                   for t in (kw.get("invocation_params", {}) or {}).get("tools", []) or []],
            messages=[[_msg_to_json(m) for m in batch] for batch in messages]
            if self.keep_content else None,
            n_messages=sum(len(b) for b in messages),
        )

    def on_llm_start(self, serialized, prompts, *, run_id=None, parent_run_id=None, **kw):
        self._emit("llm_start", run_id, parent_run_id,
                   prompts=prompts if self.keep_content else None, n_prompts=len(prompts))

    def on_llm_end(self, response, *, run_id=None, parent_run_id=None, **kw):
        gens = []
        for batch in response.generations:
            for g in batch:
                item = {"text": _text(getattr(g, "text", "")) if self.keep_content else None}
                msg = getattr(g, "message", None)
                if msg is not None:
                    item["message"] = _msg_to_json(msg)
                gi = getattr(g, "generation_info", None)
                if gi:
                    item["generation_info"] = gi
                gens.append(item)
        self._emit("llm_end", run_id, parent_run_id,
                   generations=gens, llm_output=response.llm_output)

    def on_llm_error(self, error, *, run_id=None, parent_run_id=None, **kw):
        self._emit("llm_error", run_id, parent_run_id,
                   error=f"{type(error).__name__}: {error}")

    # ---------- chains / graph nodes ----------

    def on_chain_start(self, serialized, inputs, *, run_id=None, parent_run_id=None, **kw):
        self._emit("chain_start", run_id, parent_run_id,
                   name=kw.get("name") or (serialized or {}).get("name"),
                   tags=kw.get("tags"),
                   input_keys=sorted(inputs.keys()) if isinstance(inputs, dict) else None)

    def on_chain_end(self, outputs, *, run_id=None, parent_run_id=None, **kw):
        self._emit("chain_end", run_id, parent_run_id,
                   name=kw.get("name"),
                   output_keys=sorted(outputs.keys()) if isinstance(outputs, dict) else None)

    def on_chain_error(self, error, *, run_id=None, parent_run_id=None, **kw):
        self._emit("chain_error", run_id, parent_run_id,
                   error=f"{type(error).__name__}: {error}")

    # ---------- tools ----------

    def on_tool_start(self, serialized, input_str, *, run_id=None, parent_run_id=None,
                      inputs=None, **kw):
        self._emit("tool_start", run_id, parent_run_id,
                   tool=(serialized or {}).get("name"),
                   input_str=_text(input_str),
                   inputs=inputs)

    def on_tool_end(self, output, *, run_id=None, parent_run_id=None, **kw):
        content = getattr(output, "content", output)
        self._emit("tool_end", run_id, parent_run_id,
                   output_type=type(output).__name__,
                   output_chars=len(_text(content)),
                   output=_text(content) if self.keep_content else None)

    def on_tool_error(self, error, *, run_id=None, parent_run_id=None, **kw):
        self._emit("tool_error", run_id, parent_run_id,
                   error=f"{type(error).__name__}: {error}")

    # ---------- misc ----------

    def on_retry(self, retry_state, *, run_id=None, parent_run_id=None, **kw):
        self._emit("retry", run_id, parent_run_id, attempt=getattr(retry_state, "attempt_number", None))

    def on_text(self, text, *, run_id=None, parent_run_id=None, **kw):
        self._emit("text", run_id, parent_run_id, text=_text(text, 500))

    # ---------- state plane (driven by the caller, not a callback) ----------

    def on_state(self, chunk: dict) -> None:
        """Record the per-step state delta from graph.stream(stream_mode='values')."""
        snap = {}
        for k, v in chunk.items():
            if k == "messages":
                snap[k] = {"count": len(v)}
            elif isinstance(v, str):
                snap[k] = {"chars": len(v)}
            elif isinstance(v, dict):
                snap[k] = {kk: (len(vv) if isinstance(vv, str) else vv) for kk, vv in v.items()}
        self._emit("state", None, None, fields=snap)

    # ---------- derived views ----------

    def summary(self) -> dict[str, Any]:
        import collections
        counts = collections.Counter(e["kind"] for e in self.events)
        tool_calls = [
            {"tool": e["tool"], "args": e.get("inputs") or e.get("input_str")}
            for e in self.events if e["kind"] == "tool_start"
        ]
        tokens_in = tokens_out = 0
        models = set()
        for e in self.events:
            if e["kind"] != "llm_end":
                continue
            for g in e["generations"]:
                u = (g.get("message") or {}).get("usage_metadata") or {}
                tokens_in += u.get("input_tokens", 0)
                tokens_out += u.get("output_tokens", 0)
                rm = (g.get("message") or {}).get("response_metadata") or {}
                if rm.get("model_name"):
                    models.add(rm["model_name"])
        return {
            "event_counts": dict(counts),
            "total_events": len(self.events),
            "llm_calls": counts.get("llm_end", 0),
            "tool_calls": tool_calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "models": sorted(models),
            "wall_seconds": round(time.time() - self.t0, 2),
            "errors": [e for e in self.events
                       if e["kind"] in ("tool_error", "llm_error", "chain_error")],
        }
