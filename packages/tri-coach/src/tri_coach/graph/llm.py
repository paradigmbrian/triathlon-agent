"""Model construction and the create_agent sub-agent used inside conversational nodes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
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


@wrap_model_call
async def one_tool_call_at_a_time(request: Any, handler: Any) -> Any:
    """Bind every model call with parallel tool use off.

    A handoff tool unwinds the sub-agent through Command(graph=PARENT) as soon as it runs, so a
    sibling call made in the same step can never return its result. Asking for one call per step
    keeps the persisted history free of tool_use blocks with no tool_result. langchain-anthropic
    turns `parallel_tool_calls=False` into the API's `disable_parallel_tool_use`. The coach
    graph only ever runs the sub-agent asynchronously, so the async hook is the one needed.
    """
    settings = {**request.model_settings, "parallel_tool_calls": False}
    return await handler(request.override(model_settings=settings))


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
        middleware=[
            one_tool_call_at_a_time,
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        ],
        checkpointer=False,
    )
