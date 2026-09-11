import json
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.nodes.adjust import changes_from_messages, make_adjust_node
from tri_planning.planning.models import (
    CalendarChange,
    FitnessSnapshot,
    PlannedSession,
    TrainingGoal,
)
from tri_planning.planning.targets import build
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
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
    repo.mark_weeks_written(conn, pid, [MONDAY])
    return gid, pid, targets


def test_changes_from_messages_merges_tool_results():
    proposal = {
        "summary": "lighter",
        "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "sick"}],
    }
    designed = {
        "week_start": "2026-09-21",
        "coach_note": "n",
        "violations": [],
        "changes": [
            {
                "op": "create",
                "workout_date": "2026-09-21",
                "reason": "next week",
                "workout": {
                    "date": "2026-09-21",
                    "sport": "swim",
                    "title": "S",
                    "description": "",
                    "duration_minutes": 45,
                    "tss_planned": 40,
                    "intensity": "endurance",
                },
            }
        ],
    }
    msgs = [
        ToolMessage(content=json.dumps(designed), name="design_next_week", tool_call_id="1"),
        ToolMessage(
            content=json.dumps(proposal), name="propose_calendar_changes", tool_call_id="2"
        ),
        AIMessage(content="done"),
    ]
    changes, summary = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"] and summary == "lighter"
    assert changes_from_messages([AIMessage(content="no changes")]) == ([], None)


async def test_turn_without_proposal_clears_pending_changes(nocommit, make_deps):
    gid, pid, _ = seed(nocommit)
    model = ScriptedChatModel(script=[AIMessage(content="All on track. No changes.")])
    node = make_adjust_node(make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3)))
    out = await node(
        {
            "goal_id": gid,
            "plan_id": pid,
            "phase": "active",
            "messages": [HumanMessage("how am I doing?")],
        },
        CFG,
    )
    assert out["pending_changes"] == [] and out["changes_from"] is None
    assert out["pending_summary"] is None and out["review_decision"] is None
    assert out["messages"][-1].content.startswith("All on track")


async def test_proposal_becomes_pending_changes(nocommit, make_deps):
    gid, pid, _ = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            tool_call(
                "propose_calendar_changes",
                {
                    "summary": "drop tempo",
                    "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "sick"}],
                },
            ),
            AIMessage(content="Proposed."),
        ]
    )
    node = make_adjust_node(make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3)))
    out = await node(
        {
            "goal_id": gid,
            "plan_id": pid,
            "phase": "active",
            "messages": [HumanMessage("I'm sick, drop Wednesday")],
        },
        CFG,
    )
    assert out["changes_from"] == "adjust" and out["pending_summary"] == "drop tempo"
    assert [c.op for c in out["pending_changes"]] == ["delete"]


async def test_design_next_week_extends_window(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            tool_call("design_next_week", {}),
            tool_call("PlannedWeek", week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)),
            AIMessage(content="Next week designed; nothing else to change."),
        ]
    )
    node = make_adjust_node(
        make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3), horizon=3)
    )
    out = await node(
        {"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage("check in")]},
        CFG,
    )
    assert len(out["pending_changes"]) == 3 and all(
        c.op == "create" for c in out["pending_changes"]
    )
    assert repo.list_weeks(nocommit, pid)[1].designed is not None
    assert "2026-09-21" in out["pending_summary"]
