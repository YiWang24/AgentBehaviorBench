"""Register a plain OpenAI provider through upstream's own extension point.

`data_agent.llm.base.get_llm` registers only `AzureOpenAIProvider`. Azure OpenAI
authenticates with an `api-key` header, which the Model Interceptor's auth
plugins (`bearer-token`, `anthropic-api-key`) do not cover, so its traffic
cannot be captured.

Upstream anticipates this: `LLMFactory.register_provider` is a documented
extension point and `BaseProvider` is a two-line interface. Registering an
OpenAI provider therefore changes the transport, not the agent — the same
prompts, the same model calls, the same graph.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from data_agent.llm.base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    def create_llm(self, **kwargs: Any) -> BaseChatModel:
        return ChatOpenAI(
            model=kwargs.get("deployment_name") or os.environ.get("NL2SQL_MODEL", "gpt-4o"),
            temperature=kwargs.get("temperature", 0),
            max_tokens=kwargs.get("max_tokens"),
        )


def register() -> None:
    from data_agent.llm import base

    if base._default_factory is None:
        base._default_factory = base.LLMFactory()
    base._default_factory.register_provider(OpenAIProvider())
