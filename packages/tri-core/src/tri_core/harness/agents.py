"""The agent builders every package uses. Every agent ends with the same two middlewares: the
Claude fallback, then prompt caching. Caching stays last, so the prompt an earlier
dynamic-prompt middleware renders is what gets marked for the cache, and the marks are applied
to whichever model the fallback picked."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, wrap_model_call
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from tri_core.llm import claude_fallback

Middleware = AgentMiddleware[Any, Any, Any]


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


def _caching() -> Middleware:
    return AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")


def make_subagent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    *,
    middleware: Sequence[Middleware] = (),
) -> Any:
    """A tool-calling loop with no checkpointer of its own: the parent graph owns the messages.

    A compiled graph invoked inside a node is a subgraph. `checkpointer=False`
    stops it from writing its own checkpoints under the parent's namespace; the parent state
    already carries the conversation.
    """
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[*middleware, claude_fallback, _caching()],
        checkpointer=False,
    )


def build_chat_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
    middleware: Sequence[Middleware] = (),
    context_schema: type[Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools, remembering each thread. Without a
    checkpointer the threads live in memory."""
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[*middleware, claude_fallback, _caching()],
        context_schema=context_schema,
        checkpointer=checkpointer or InMemorySaver(),
    )
