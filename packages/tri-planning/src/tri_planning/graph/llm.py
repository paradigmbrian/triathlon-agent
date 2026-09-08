"""Model construction and the create_agent sub-agent used inside conversational nodes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )


def make_subagent(model: BaseChatModel, tools: Sequence[BaseTool], system_prompt: str) -> Any:
    """A tool-calling loop with no checkpointer of its own: the parent graph owns the messages.

    A compiled graph invoked inside a node is a subgraph. `checkpointer=False`
    stops it from writing its own checkpoints under the parent's namespace; the parent state
    already carries the conversation.
    """
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        checkpointer=False,
    )
