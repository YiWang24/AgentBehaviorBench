"""Selected-agent subset of the upstream `agents` package.

Upstream's ``agents/__init__.py`` re-exports ``agents.agents``, which eagerly
imports every agent in the repository — the MCP agent, the supervisor
hierarchies, the background-task agent, and the RAG assistants. AgentBench
selects exactly one graph (``research_assistant``), so this package exposes no
registry and the sibling agent modules are not vendored. Every module the
selected graph does import is vendored unchanged.
"""
