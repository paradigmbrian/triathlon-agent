import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.nodes.intake import goal_id_from_messages, make_intake_node
from tri_planning.testing import GOAL_ARGS

pytestmark = pytest.mark.db

CFG = {"configurable": {"thread_id": "t"}}


def test_goal_id_from_messages():
    msgs = [
        ToolMessage(
            content=json.dumps({"goal_id": 7, "weeks": 14}),
            name="set_training_goal",
            tool_call_id="c1",
        )
    ]
    assert goal_id_from_messages(msgs) == 7
    err = ToolMessage(
        content=json.dumps({"error": "x"}), name="set_training_goal", tool_call_id="c2"
    )
    assert goal_id_from_messages([err]) is None
    assert goal_id_from_messages([AIMessage(content="hi")]) is None


async def test_intake_turn_without_goal_returns_only_messages(make_deps):
    model = ScriptedChatModel(script=[AIMessage(content="What race are you targeting?")])
    node = make_intake_node(make_deps(model))
    out = await node({"messages": [HumanMessage("I want to plan my season")]}, CFG)
    assert [type(m).__name__ for m in out["messages"]] == ["AIMessage"]
    assert "goal_id" not in out


async def test_intake_sets_goal_and_phase(make_deps):
    model = ScriptedChatModel(
        script=[tool_call("set_training_goal", GOAL_ARGS), AIMessage(content="Goal saved.")]
    )
    node = make_intake_node(make_deps(model))
    out = await node({"messages": [HumanMessage("Olympic on Dec 13, 4-12 h, any day")]}, CFG)
    assert out["phase"] == "planning" and isinstance(out["goal_id"], int)
    assert [type(m).__name__ for m in out["messages"]] == ["AIMessage", "ToolMessage", "AIMessage"]
