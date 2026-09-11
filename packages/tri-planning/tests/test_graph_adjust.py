from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.graph import after_adjust, build_graph
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal, WeekTarget
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "planning"}}


def seed_active(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=300, target_hours=6
        )
        for i in range(3)
    ]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(
        date=MONDAY + timedelta(days=2),
        sport="run",
        title="Tempo",
        description="",
        duration_minutes=60,
        tss_planned=60,
        intensity="tempo",
    )
    repo.insert_change(
        conn,
        pid,
        "planning",
        CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"),
        tp_workout_id="w1",
        result={},
    )
    return gid, pid


async def test_active_turn_proposes_reviews_and_applies(nocommit, make_deps):
    gid, pid = seed_active(nocommit)
    tp = FakeTp()
    model = ScriptedChatModel(
        script=[
            tool_call(
                "propose_calendar_changes",
                {
                    "summary": "move it",
                    "changes": [
                        {
                            "op": "move",
                            "tp_workout_id": "w1",
                            "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                            "reason": "rest day",
                        }
                    ],
                },
            ),
            AIMessage(content="Proposed a move."),
        ]
    )
    graph = build_graph(
        make_deps(model, tp=tp, today=MONDAY + timedelta(days=1), horizon=3), InMemorySaver()
    )
    await graph.aupdate_state(CFG, {"goal_id": gid, "plan_id": pid, "phase": "active"})
    out = await graph.ainvoke({"messages": [HumanMessage("I need Wednesday off")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][0]["op"] == "move"
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert tp.calls == [
        (
            "tp_update_workout",
            {"workout_id": "w1", "date": (MONDAY + timedelta(days=4)).isoformat()},
        )
    ]
    assert out["phase"] == "active" and out["pending_changes"] == []


async def test_reject_clears_pending_changes_and_returns_to_adjust(nocommit, make_deps):
    gid, pid = seed_active(nocommit)
    tp = FakeTp()
    model = ScriptedChatModel(
        script=[
            tool_call(
                "propose_calendar_changes",
                {
                    "summary": "move it",
                    "changes": [
                        {
                            "op": "move",
                            "tp_workout_id": "w1",
                            "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                            "reason": "rest day",
                        }
                    ],
                },
            ),
            AIMessage(content="Proposed a move."),
            AIMessage(content="Nothing else to change."),
            AIMessage(content="All good this turn."),
        ]
    )
    graph = build_graph(
        make_deps(model, tp=tp, today=MONDAY + timedelta(days=1), horizon=3), InMemorySaver()
    )
    await graph.aupdate_state(CFG, {"goal_id": gid, "plan_id": pid, "phase": "active"})
    out = await graph.ainvoke({"messages": [HumanMessage("I need Wednesday off")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][0]["op"] == "move"

    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "leave it"}), CFG)
    assert "__interrupt__" not in out
    assert out["pending_changes"] == [] and out["changes_from"] is None
    assert any(
        isinstance(m, HumanMessage) and "Plan review rejected: leave it" in m.content
        for m in out["messages"]
    )

    out = await graph.ainvoke({"messages": [HumanMessage("anything else?")]}, CFG)
    assert "__interrupt__" not in out
    assert out["messages"][-1].content == "All good this turn."
    assert tp.calls == []


def test_after_adjust():
    assert after_adjust({"pending_changes": [1]}) == "review"
    assert after_adjust({"pending_changes": []}) == "__end__"
