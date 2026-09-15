"""Generated per docs/How To Add Agent.md step 3: invoke the declared public graph."""
import asyncio


class Generated:
    def __init__(self):
        self._graph = None

    def _load(self):
        if self._graph is None:
            from src.react_agent.graph import graph as g
            self._graph = g
        return self._graph

    async def ainvoke(self, value, config=None, *, context=None):
        if isinstance(value, str):
            value = {"messages": [("user", value)]}
        return await self._load().ainvoke(value, config=config)

    def invoke(self, value, config=None, *, context=None):
        return asyncio.run(self.ainvoke(value, config, context=context))

    def close(self):
        self._graph = None


def create_graph():
    return Generated()
