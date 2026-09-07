"""Model and agent graph construction.

LangChain lesson: `create_agent` builds a LangGraph with two nodes, `model` and `tools`,
and loops until the model stops calling tools. The checkpointer is what turns single calls
into a conversation. Middleware wraps the model call; here it adds Anthropic `cache_control`
markers so the stable prefix (system prompt + tool schemas) is served from cache.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    """Claude via LangChain. No `thinking` kwarg: adaptive thinking is the model default."""
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """A tool-calling agent graph: model <-> tools until the model stops calling tools."""
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        checkpointer=checkpointer or InMemorySaver(),
    )
