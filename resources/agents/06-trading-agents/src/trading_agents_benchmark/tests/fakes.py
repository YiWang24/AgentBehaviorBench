"""A minimal fake chat model for exercising the real TradingAgents graph
end-to-end without a real model API key.

Every LLM call in TradingAgents goes through one of three shapes:

1. Tool-bound (the four analysts): call each bound tool exactly once (across
   successive turns of the same ReAct loop), then close with free text.
2. Structured output (Research Manager, Trader, Portfolio Manager, Sentiment
   Analyst): `with_structured_output` raises `NotImplementedError`, which is
   a real path -- `tradingagents.agents.utils.structured.bind_structured`
   already catches exactly this and falls back to free-text generation, and
   `signal_processing.parse_rating` still recovers a valid 5-tier rating
   from free text (defaulting to "Hold" if no tier keyword appears), so
   nothing needs to be hand-faked here.
3. Plain free text (bull/bear researchers, risk debators): closes with free
   text directly.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_CLOSING_TEXT = (
    "Based on the available analyst reports and debate, the evidence is "
    "reasonably balanced with a modest tilt toward caution.\n\n"
    "**Rating**: Hold\n"
    "**Executive Summary**: Hold the position and reassess after the next "
    "data point.\n"
    "**Investment Thesis**: Benchmark smoke-test placeholder reasoning.\n\n"
    "FINAL TRANSACTION PROPOSAL: **HOLD**"
)


def _sample_args(tool: Any, ticker: str, curr_date: str) -> dict[str, Any]:
    schema = getattr(tool, "args_schema", None)
    fields = getattr(schema, "model_fields", None) if schema is not None else None
    if not fields:
        return {}

    args: dict[str, Any] = {}
    for name, field in fields.items():
        if not field.is_required():
            continue
        lname = name.lower()
        if "date" in lname:
            args[name] = curr_date
        elif "symbol" in lname or "ticker" in lname:
            args[name] = ticker
        elif "indicator" in lname:
            args[name] = "close_50_sma"
        elif "topic" in lname or "quer" in lname:
            args[name] = "market outlook"
        elif "freq" in lname:
            args[name] = "quarterly"
        elif "look_back" in lname or lname.endswith("_days"):
            args[name] = 5
        elif "limit" in lname or "count" in lname:
            args[name] = 3
        else:
            annotation = field.annotation
            if annotation in (int,):
                args[name] = 1
            elif annotation in (float,):
                args[name] = 1.0
            else:
                args[name] = ticker
    return args


class FakeAnalystChatModel(BaseChatModel):
    """Deterministic stand-in for the deep/quick thinking LLMs."""

    bound_tools: list = []
    ticker: str = "NVDA"
    curr_date: str = "2024-05-10"

    @property
    def _llm_type(self) -> str:
        return "fake-tradingagents-benchmark-model"

    def bind_tools(self, tools: list, **_kwargs: Any) -> "FakeAnalystChatModel":
        return self.__class__(bound_tools=list(tools), ticker=self.ticker, curr_date=self.curr_date)

    def with_structured_output(self, schema: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("fake model does not support structured output")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tool_messages_seen = sum(1 for m in messages if isinstance(m, ToolMessage))
        if self.bound_tools and tool_messages_seen < len(self.bound_tools):
            tool = self.bound_tools[tool_messages_seen]
            tool_name = getattr(tool, "name", getattr(tool, "__name__", "unknown_tool"))
            args = _sample_args(tool, self.ticker, self.curr_date)
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": tool_name, "args": args, "id": f"fake-call-{tool_messages_seen}"}
                ],
            )
        else:
            message = AIMessage(content=_CLOSING_TEXT)
        return ChatResult(generations=[ChatGeneration(message=message)])


def install_fake_llms(trading_graph: Any, ticker: str, curr_date: str) -> None:
    """Rebuild a constructed TradingAgentsGraph against FakeAnalystChatModel.

    Sub-components close over the LLM reference at construction time
    (GraphSetup, Reflector, SignalProcessor all take it as a constructor
    arg), so the graph itself must be rebuilt against the fake model rather
    than only swapping the two top-level attributes.
    """
    from tradingagents.graph.reflection import Reflector
    from tradingagents.graph.setup import GraphSetup
    from tradingagents.graph.signal_processing import SignalProcessor

    fake = FakeAnalystChatModel(ticker=ticker, curr_date=curr_date)
    trading_graph.deep_thinking_llm = fake
    trading_graph.quick_thinking_llm = fake
    trading_graph.reflector = Reflector(fake)
    trading_graph.signal_processor = SignalProcessor(fake)
    trading_graph.graph_setup = GraphSetup(
        fake, fake, trading_graph.tool_nodes, trading_graph.conditional_logic
    )
    trading_graph.workflow = trading_graph.graph_setup.setup_graph(trading_graph.selected_analysts)
    trading_graph.graph = trading_graph.workflow.compile()
