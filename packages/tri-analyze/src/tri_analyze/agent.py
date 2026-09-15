"""The analyst agent: a model-and-tools loop whose system prompt is rendered before each model
call from the athlete context passed as runtime context and the names of the bound tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from tri_analyze.prompts.analyst import PROMPT_VERSION, render_system_prompt
from tri_analyze.repo import AthleteContext
from tri_core.harness.agents import build_chat_agent


@dynamic_prompt
def analyst_prompt(request: ModelRequest[AthleteContext]) -> str:
    """Render the system prompt from the run's context and the tools bound to this request."""
    names = [t.name if isinstance(t, BaseTool) else str(t["name"]) for t in request.tools]
    return render_system_prompt(request.runtime.context, names)


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools. Every run must pass
    `context=<AthleteContext>`. The prompt middleware runs first so the caching middleware marks
    the rendered system prompt; tool order is the order given, which keeps the cached prefix
    stable. Runs carry the `analyst` tag and the prompt version as metadata."""
    agent = build_chat_agent(
        model,
        tools,
        middleware=[analyst_prompt],
        context_schema=AthleteContext,
        checkpointer=checkpointer,
    )
    return agent.with_config(
        {"tags": ["analyst"], "metadata": {"analyst_prompt_version": PROMPT_VERSION}}
    )
