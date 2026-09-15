"""Deliver a current excerpt/question to the unchanged native swarm, with session memory."""
import asyncio


def message_from_input(value):
    """Accept text or exactly {message: text}; reject unrepresented attachments."""
    if isinstance(value, dict):
        if set(value) != {'message'}:
            raise ValueError('Article Explainer accepts exactly one current message field')
        value = value['message']
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Supply a non-empty current excerpt and question')
    return value


class ArticleExplainer:
    def __init__(self):
        self._app = None
        self._closed = False

    async def ainvoke(self, value, config=None):
        """Run native handoffs and return the entire native SwarmState.

        Args: value is current text or {message: text}; config is forwarded to
            the native graph, including real framework observation callbacks.
        Returns: Native state containing messages and active_agent, unchanged.
        No PDF is loaded and no transcript is constructed here; prior turns come
        from LangGraph's checkpointer, keyed by the runtime's thread_id.
        """
        message = message_from_input(value)
        if self._closed:
            raise RuntimeError('Article Explainer is closed')
        if self._app is None:
            from langgraph.checkpoint.memory import InMemorySaver
            from explainer.graph import agent_swarm

            # Compile the unchanged native swarm with LangGraph's own session
            # persistence, the same deployment choice react-agent makes. The runtime
            # supplies a stable thread_id, so earlier turns -- and the swarm's
            # active_agent -- survive across Inputs. Upstream's own `agent_swarm.compile()`
            # takes no checkpointer, which restarts the conversation on every Input and
            # makes a multi-step Case behave as unrelated single questions.
            self._app = agent_swarm.compile(checkpointer=InMemorySaver())
        return await self._app.ainvoke({'messages': [('user', message)]}, config=config)

    def invoke(self, value, config=None):
        return asyncio.run(self.ainvoke(value, config))

    def close(self):
        self._closed = True
        self._app = None


def create_graph():
    return ArticleExplainer()
