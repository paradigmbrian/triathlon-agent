from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.nodes.design import make_design_node, window_weeks
from tri_planning.planning.models import (
    FitnessSnapshot,
    PlannedWeek,
    PlanWeekRow,
    ReviewDecision,
    TrainingGoal,
)
from tri_planning.planning.targets import build
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt
from tri_planning.testing import GOAL_ARGS, MONDAY, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid, targets


def structured(week: dict) -> AIMessage:
    return tool_call("PlannedWeek", week)


async def node_out(deps, gid, pid):
    return await make_design_node(deps)({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)


async def test_designs_window_weeks_and_proposes_creates(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            structured(week_json(MONDAY, targets[0].target_tss)),
            structured(week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)),
        ]
    )
    node = make_design_node(make_deps(model, horizon=2))
    out = await node({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)
    assert model.calls == 2
    assert len(out["pending_changes"]) == 6
    assert {c.op for c in out["pending_changes"]} == {"create"}
    assert out["changes_from"] == "design" and str(MONDAY) in out["pending_summary"]
    weeks = repo.list_weeks(nocommit, pid)
    assert weeks[0].designed is not None and weeks[1].designed is not None
    assert weeks[2].designed is None


async def test_retries_once_on_violation_and_reports_if_still_bad(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    bad = week_json(MONDAY, targets[0].target_tss, hard_on_consecutive_days=True)
    good = week_json(MONDAY, targets[0].target_tss)
    model = ScriptedChatModel(script=[structured(bad), structured(good)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" not in out["pending_summary"]

    model = ScriptedChatModel(script=[structured(bad), structured(bad)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" in out["pending_summary"]
    assert "consecutive" in out["pending_summary"]


async def test_reject_note_reaches_prompt_and_unwritten_weeks_are_redesigned(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    captured = []

    class Spy(ScriptedChatModel):
        def _generate(self, messages, *a, **k):
            captured.append(messages[-1].content)
            return super()._generate(messages, *a, **k)

    model = Spy(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    node = make_design_node(make_deps(model))
    state = {
        "goal_id": gid,
        "plan_id": pid,
        "messages": [HumanMessage("Plan review rejected: no running on Wednesdays")],
        "review_decision": ReviewDecision(action="reject", note="no running on Wednesdays"),
    }
    await node(state, CFG)
    assert "no running on Wednesdays" in captured[-1]


async def test_event_change_first_when_requested(nocommit, make_deps):
    gid, pid, targets = seed(nocommit, create_tp_event=True)
    model = ScriptedChatModel(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    out = await node_out(make_deps(model), gid, pid)
    assert out["pending_changes"][0].op == "create_event"


def test_window_weeks_respects_horizon_and_written_flag():
    rows = [
        PlanWeekRow(
            plan_id=1,
            week_start=MONDAY + timedelta(weeks=i),
            phase="base",
            target_tss=1,
            target_hours=1,
            designed=None,
            written_to_tp=(i == 0),
        )
        for i in range(5)
    ]
    picked = window_weeks(rows, MONDAY + timedelta(days=2), 3)
    assert [w.week_start for w in picked] == [
        MONDAY + timedelta(weeks=1),
        MONDAY + timedelta(weeks=2),
    ]


def test_prompt_mentions_target_availability_and_rules():
    goal = TrainingGoal(**GOAL_ARGS)
    targets = build(goal, FitnessSnapshot(ctl=45), MONDAY)
    text = render_design_prompt(goal, targets[0], {"ftp_watts": 250}, None, None, None, None)
    assert f"{targets[0].target_tss:.0f}" in text and "pool closed Fridays" in text
    assert "250" in text
    assert "consecutive" in DESIGN_SYSTEM and "percentOfFtp" in DESIGN_SYSTEM
    assert isinstance(PlannedWeek.model_validate(week_json(MONDAY, 300)), PlannedWeek)
