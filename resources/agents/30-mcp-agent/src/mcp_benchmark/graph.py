"""Build the MCP-backed ReAct agent.

Upstream constructs the agent inside `initialize_session()` in its Streamlit
app: connect a `MultiServerMCPClient` to the servers named in `config.json`,
take the tools it discovers, and hand them to `create_react_agent` with the
system prompt. The same three calls are made here, with upstream's own config
file, its own server scripts, and its prompt copied verbatim — the Streamlit
module is not imported because it would pull in the whole UI.
"""

from __future__ import annotations

import json
import os
import pathlib

import benchmark_mocks

from .prompt import SYSTEM_PROMPT

_agent = None
_client = None


def config_path() -> str:
    return os.environ.get("MCP_CONFIG", "/opt/agent/config.json")


def mcp_config() -> dict:
    return json.loads(pathlib.Path(config_path()).read_text(encoding="utf-8"))


async def build():
    """Connect to the MCP servers and return the compiled agent."""
    global _agent, _client
    if _agent is not None:
        return _agent

    benchmark_mocks.install_all()

    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent

    _client = MultiServerMCPClient(mcp_config())
    tools = await _client.get_tools()

    model = ChatOpenAI(
        model=os.environ.get("MCP_MODEL", "gpt-4o"),
        temperature=0.1,
    )
    _agent = create_react_agent(
        model,
        tools,
        checkpointer=MemorySaver(),
        prompt=SYSTEM_PROMPT,
    )
    return _agent


def graph():
    """Synchronous entry point for the LangGraph adapter."""
    import asyncio

    return asyncio.run(build())
