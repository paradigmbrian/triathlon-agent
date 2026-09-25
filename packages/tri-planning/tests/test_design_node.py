import contextlib
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import tri_planning.graph.nodes.design as design_node
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.config import PlanningSettings
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.deps import make_deps as real_make_deps
from tri_planning.graph.nodes.design import design_week, make_design_node, window_weeks
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


def seed(conn, start=MONDAY, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), start)
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


async def test_design_node_clears_pending_violations(nocommit, make_deps):
    # A later review on the persistent planning thread must not show stale violations from an
    # earlier adjust run; the design node always starts the set clean.
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    out = await node_out(make_deps(model, horizon=1), gid, pid)
    assert out["pending_violations"] == {}


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


def test_window_starts_at_the_first_plan_week_when_today_is_before_it():
    rows = [
        PlanWeekRow(
            plan_id=1,
            week_start=MONDAY + timedelta(weeks=i),
            phase="base",
            target_tss=1,
            target_hours=1,
            designed=None,
            written_to_tp=False,
        )
        for i in range(1, 6)
    ]
    # a Wednesday; the plan starts the Monday after it
    picked = window_weeks(rows, MONDAY + timedelta(days=2), 3)
    assert [w.week_start for w in picked] == [MONDAY + timedelta(weeks=i) for i in (1, 2, 3)]
    assert window_weeks([], MONDAY, 3) == []


async def test_horizon_three_on_a_wednesday_designs_three_weeks(nocommit, make_deps):
    gid, pid, targets = seed(nocommit, start=MONDAY + timedelta(weeks=1))
    model = ScriptedChatModel(
        script=[structured(week_json(t.week_start, t.target_tss)) for t in targets[:3]]
    )
    node = make_design_node(make_deps(model, today=MONDAY + timedelta(days=2), horizon=3))
    out = await node({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)
    assert model.calls == 3 and len(out["pending_changes"]) == 9


def test_prompt_mentions_target_availability_and_rules():
    goal = TrainingGoal(**GOAL_ARGS)
    targets = build(goal, FitnessSnapshot(ctl=45), MONDAY)
    text = render_design_prompt(goal, targets[0], {"ftp_watts": 250}, None, None, None, None)
    assert f"{targets[0].target_tss:.0f}" in text and "pool closed Fridays" in text
    assert "250" in text
    assert "consecutive" in DESIGN_SYSTEM and "percentOfFtp" in DESIGN_SYSTEM
    assert isinstance(PlannedWeek.model_validate(week_json(MONDAY, 300)), PlannedWeek)


class _Stop(Exception):
    pass


async def test_design_week_uses_the_design_model_when_one_is_set(monkeypatch):
    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        raise _Stop

    monkeypatch.setattr(design_node, "structured", spy)
    agent, designer = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    deps = GraphDeps(model=agent, connect=lambda: contextlib.nullcontext(None), db_url="unused")
    with pytest.raises(_Stop):
        await design_week(deps, None, None, None, None, None, {})
    deps.design_model = designer
    with pytest.raises(_Stop):
        await design_week(deps, None, None, None, None, None, {})
    assert seen == [(agent, PlannedWeek), (designer, PlannedWeek)]


def test_make_deps_takes_an_optional_design_model():
    agent, designer = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    settings = PlanningSettings(_env_file=None)
    assert real_make_deps(settings, agent, None).design_model is None
    assert real_make_deps(settings, agent, None, design_model=designer).design_model is designer


async def test_a_reply_without_a_week_is_retried_once_then_reported(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            AIMessage(content="I need more information."),
            structured(week_json(MONDAY, targets[0].target_tss)),
        ]
    )
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" not in out["pending_summary"]
    assert len(out["pending_changes"]) == 3

    model = ScriptedChatModel(script=[AIMessage(content="no"), AIMessage(content="still no")])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and out["pending_changes"] == []
    assert "VIOLATIONS" in out["pending_summary"] and "no week" in out["pending_summary"]
