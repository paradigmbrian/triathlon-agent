"""One real coach turn with both servers up: a question answered through the analyst, no
consultation. Opt-in with --live (see tri_core.testing.fixtures)."""

from contextlib import AsyncExitStack

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from tri_coach.config import CoachSettings
from tri_coach.graph.deps import make_deps
from tri_coach.graph.graph import build_graph
from tri_coach.graph.llm import make_model
from tri_coach.servers import open_servers

pytestmark = pytest.mark.live


async def test_one_turn_answers_through_the_analyst_and_consults_nothing():
    settings = CoachSettings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    async with AsyncExitStack() as stack:
        servers = await open_servers(stack, settings, no_live=False, log=print)
        assert servers.garmin is not None and servers.tp is not None, "both servers must be up"
        graph = build_graph(
            make_deps(settings, make_model(settings), servers), InMemorySaver(), InMemoryStore()
        )
        cfg = {"configurable": {"thread_id": "coach-live"}, "recursion_limit": 60}
        out = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        "In one paragraph: how did my last seven days of training go, "
                        "and what does my readiness look like today? Do not change anything."
                    )
                ]
            },
            cfg,
        )
    tools = [m.name for m in out["messages"] if isinstance(m, ToolMessage)]
    assert "ask_analyst" in tools
    assert not any(n in ("consult_planning", "consult_nutrition", "propose_changes") for n in tools)
    assert "__interrupt__" not in out and out["messages"][-1].content
