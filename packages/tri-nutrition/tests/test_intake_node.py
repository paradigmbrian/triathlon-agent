import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.intake import make_intake_node, profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.testing import PROFILE_ARGS

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def test_profile_saved_from_messages():
    ok = ToolMessage(
        content=json.dumps({"saved": True}), name="save_nutrition_profile", tool_call_id="c1"
    )
    err = ToolMessage(
        content=json.dumps({"error": "x"}), name="save_nutrition_profile", tool_call_id="c2"
    )
    assert profile_saved_from_messages([ok]) is True
    assert profile_saved_from_messages([err]) is False
    assert profile_saved_from_messages([AIMessage(content="hi")]) is False


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("intake", node)
    g.add_edge(START, "intake")
    g.add_edge("intake", END)
    return g.compile(store=store)


async def test_intake_turn_without_save_returns_only_messages(make_deps, mem_store):
    model = ScriptedChatModel(script=[AIMessage(content="What is your goal?")])
    graph = one_node_graph(make_intake_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("help me eat for my race")]}, CFG)
    assert [type(m).__name__ for m in out["messages"]] == ["HumanMessage", "AIMessage"]
    assert "profile_saved" not in out or out["profile_saved"] is False


async def test_intake_saves_profile_and_flags_state(make_deps, mem_store, fake_garmin):
    model = ScriptedChatModel(
        script=[
            tool_call("read_garmin_profile", {}),
            tool_call("save_nutrition_profile", PROFILE_ARGS, "c2"),
            AIMessage(content="Profile saved. Building your targets."),
        ]
    )
    graph = one_node_graph(make_intake_node(make_deps(model, garmin=fake_garmin)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("let's set up my nutrition")]}, CFG)
    assert out["profile_saved"] is True and out["regenerate_from"] == "intake"
    assert (await S.get_profile(mem_store)) is not None
    assert fake_garmin.calls[0][0] == "get_user_profile"
    names = [m.name for m in out["messages"] if isinstance(m, ToolMessage)]
    assert names == ["read_garmin_profile", "save_nutrition_profile"]
