"""LangGraph entry point for the benchmark adaptation of DeepFund.

The upstream workflow is preserved: the selected analysts fan out from START,
each writing a signal, and the portfolio manager decides on the ticker. The
benchmark runs a single-ticker configuration so one Case stays bounded.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must patch Router before analysts import it)

benchmark_mocks.install()

from graph.workflow import AgentWorkflow  # noqa: E402
from util.db_helper import db_initialize, get_db  # noqa: E402

EXPERIMENT = "agentbench"
ANALYSTS = ("fundamental", "technical")

_database_ready = False


def _config(ticker: str, trading_date: str) -> dict[str, Any]:
    return {
        "exp_name": EXPERIMENT,
        "cashflow": 100000,
        "tickers": [ticker],
        "workflow_analysts": list(ANALYSTS),
        "planner_mode": False,
        "trading_date": datetime.strptime(trading_date, "%Y-%m-%d"),
        "llm": {"provider": "OpenAI", "model": "gpt-4o-mini"},
    }


def _database():
    """Create the SQLite schema and open it, once per process.

    Upstream creates the schema from `python database/sqlite_setup.py`, a step
    its README documents separately from running the agent. The benchmark starts
    from an empty tmpfs every run, so the setup is invoked here instead.
    """
    global _database_ready
    if not _database_ready:
        from database.sqlite_setup import init_database

        init_database()
        db_initialize(use_local_db=True)
        _database_ready = True
    return get_db()


def graph():
    """Zero-argument factory returning the compiled trading workflow.

    `build()` reads `current_analysts`, which `load_analysts()` sets per ticker;
    upstream's `run()` calls them in that order, so the factory does too.
    """
    config = _config(runtime.DEFAULT_TICKER, runtime.DEFAULT_TRADING_DATE)
    database = _database()
    config_id = database.get_config_id_by_name(EXPERIMENT) or database.create_config(config)
    workflow = AgentWorkflow(config, config_id)
    workflow.load_analysts(runtime.DEFAULT_TICKER)
    return workflow.build()


def run_analysis(ticker: str, trading_date: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run the workflow for one ticker and normalize the public result."""
    config = _config(ticker, trading_date)
    database = _database()
    config_id = database.get_config_id_by_name(EXPERIMENT) or database.create_config(config)

    workflow = AgentWorkflow(config, config_id)
    workflow.run(config_id)

    decisions = database.get_decision_memory(EXPERIMENT, ticker, limit=5) or []
    normalised = []
    for decision in decisions:
        dump = getattr(decision, "model_dump", None)
        normalised.append(dump() if callable(dump) else dict(decision))

    portfolio = database.get_latest_portfolio(config_id) or {}
    return {
        "ticker": ticker,
        "trading_date": trading_date,
        "analysts": list(ANALYSTS),
        "decisions": normalised,
        "cashflow": portfolio.get("cashflow"),
    }


_TICKER = re.compile(r"\b([A-Z][A-Z.\-]{1,5})\b")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Words that look like tickers but are not, so shouty prose cannot redirect the
# analysis to a different instrument.
_NOT_TICKERS = frozenset(
    {"AI", "AND", "ANY", "BUY", "CEO", "EPS", "ETF", "FED", "FOR", "GDP",
     "HOLD", "IPO", "NOT", "NOW", "ROI", "SELL", "THE", "USD", "WHY", "YOY"}
)


def parse_request(text: str) -> tuple[str, str]:
    """Map free text onto a (ticker, trading date) pair.

    The official Case provider emits text, but the workflow needs an explicit
    ticker and date. An unrecognised request analyses the default instrument
    rather than inventing one.
    """
    text = " ".join(str(text or "").split())
    ticker = runtime.DEFAULT_TICKER
    for candidate in _TICKER.findall(text):
        if candidate.upper() not in _NOT_TICKERS:
            ticker = candidate.upper()
            break

    match = _DATE.search(text)
    trading_date = runtime.DEFAULT_TRADING_DATE
    if match:
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
        else:
            trading_date = match.group(1)
    return ticker, trading_date
