"""The chat agent: a tool-calling loop with in-process conversation memory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools. The stable prefix (system prompt
    and tool schemas) is served from Anthropic's prompt cache."""
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        checkpointer=checkpointer or InMemorySaver(),
    )
