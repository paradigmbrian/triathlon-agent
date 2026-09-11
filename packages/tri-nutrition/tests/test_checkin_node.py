import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.checkin import make_checkin_node, proposal_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def tm(content, name="propose_target_changes"):
    return ToolMessage(content=json.dumps(content), name=name, tool_call_id="c1")


def test_proposal_from_messages():
    ok = tm({"proposed": True, "overrides": {"activity_factor": 1.4}, "reason": "r"})
    assert proposal_from_messages([ok]) == {"activity_factor": 1.4}
    assert proposal_from_messages([tm({"proposed": True, "overrides": {}, "reason": "e"})]) == {}
    assert proposal_from_messages([tm({"error": "unknown profile fields: x"})]) is None
    assert proposal_from_messages([tm({"recorded": True}, name="record_fuel_feedback")]) is None
    assert proposal_from_messages([AIMessage(content="hi")]) is None
    # the last proposal wins
    assert proposal_from_messages([ok, tm({"error": "x"})]) is None


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("checkin", node)
    g.add_edge(START, "checkin")
    g.add_edge("checkin", END)
    return g.compile(store=store)


def propose(overrides, reason):
    return tool_call("propose_target_changes", {"overrides": overrides, "reason": reason})


async def test_proposal_sets_overrides_and_flags(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[
            propose({"activity_factor": 1.5}, "on my feet all day"),
            AIMessage(content="Proposed a higher activity factor."),
        ]
    )
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert out["targets_requested"] is True and out["regenerate_from"] == "checkin"
    assert out["profile_overrides"] == {"activity_factor": 1.5}
    assert "profile_saved" not in out or out["profile_saved"] is False
    assert (await S.get_profile(mem_store)).activity_factor == 1.35


async def test_extend_horizon_requests_targets_without_overrides(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[propose({}, "extend horizon"), AIMessage(content="Extending.")]
    )
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert out["targets_requested"] is True and out["profile_overrides"] is None


async def test_question_turn_sets_nothing(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[AIMessage(content="Rest days are 2400 kcal.")])
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("what do I eat on rest days?")]}, CFG)
    assert "targets_requested" not in out and "profile_overrides" not in out
    assert [type(m).__name__ for m in out["messages"]] == ["HumanMessage", "AIMessage"]


async def test_fuel_feedback_turn_writes_log_and_sets_nothing(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    feedback = {
        "day": "2026-09-12",
        "sport": "bike",
        "duration_min": 150,
        "carbs_g_per_h": 70,
        "outcome": "ok",
        "products": ["Gel"],
    }
    model = ScriptedChatModel(
        script=[tool_call("record_fuel_feedback", feedback), AIMessage(content="Logged.")]
    )
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("the long ride was fine at 70")]}, CFG)
    assert "targets_requested" not in out
    assert [e.carbs_g_per_h for e in await S.get_fuel_log(mem_store)] == [70]
