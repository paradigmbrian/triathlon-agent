import json
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.planning.models import FitnessSnapshot, PlannedWeek, TrainingGoal
from tri_planning.planning.targets import build
from tri_planning.testing import GOAL_ARGS, MONDAY, week_json
from tri_planning.tools.design_next_week import make_design_next_week_tool

pytestmark = pytest.mark.db


def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid, targets


def structured(week: dict) -> AIMessage:
    return tool_call("PlannedWeek", week)


def design_all(conn, pid, targets):
    for t in targets:
        week = PlannedWeek.model_validate(week_json(t.week_start, t.target_tss))
        repo.set_week_designed(conn, pid, t.week_start, week)
        repo.mark_weeks_written(conn, pid, [t.week_start])


async def test_designs_next_undesigned_week_skipping_written(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    repo.mark_weeks_written(nocommit, pid, [MONDAY])  # week 0: written, not designed
    week1_start = MONDAY + timedelta(weeks=1)
    model = ScriptedChatModel(script=[structured(week_json(week1_start, targets[1].target_tss))])
    deps = make_deps(model, horizon=3)
    tool = make_design_next_week_tool(deps, lambda: pid)

    out = json.loads(await tool.ainvoke({}))

    assert model.calls == 1
    assert out["week_start"] == week1_start.isoformat()
    assert out["violations"] == []
    assert {c["op"] for c in out["changes"]} == {"create"}
    assert len(out["changes"]) == 3  # week_json's three non-rest sessions

    weeks = repo.list_weeks(nocommit, pid)
    assert weeks[0].designed is None
    assert weeks[1].designed is not None
    assert weeks[1].designed.week_start == week1_start


async def test_horizon_exhausted_but_weeks_remain_beyond_it(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    repo.mark_weeks_written(nocommit, pid, [MONDAY])
    deps = make_deps(ScriptedChatModel(script=[]), horizon=1)
    tool = make_design_next_week_tool(deps, lambda: pid)

    out = json.loads(await tool.ainvoke({}))

    assert out == {"error": "every week inside the horizon is already on the calendar"}
    weeks = repo.list_weeks(nocommit, pid)
    assert weeks[1].designed is None


async def test_every_remaining_week_already_designed(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    design_all(nocommit, pid, targets)
    deps = make_deps(ScriptedChatModel(script=[]), horizon=3)
    tool = make_design_next_week_tool(deps, lambda: pid)

    out = json.loads(await tool.ainvoke({}))

    assert out == {"error": "every remaining week is already on the calendar"}


async def test_designed_but_unwritten_week_inside_horizon_is_redesigned(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    repo.set_week_designed(
        nocommit, pid, MONDAY, PlannedWeek.model_validate(week_json(MONDAY, targets[0].target_tss))
    )
    model = ScriptedChatModel(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    deps = make_deps(model, horizon=3)
    tool = make_design_next_week_tool(deps, lambda: pid)

    out = json.loads(await tool.ainvoke({}))

    assert model.calls == 1
    assert out["week_start"] == MONDAY.isoformat()
    weeks = repo.list_weeks(nocommit, pid)
    assert weeks[0].designed is not None and not weeks[0].written_to_tp


async def test_no_active_plan(make_deps):
    deps = make_deps(ScriptedChatModel(script=[]))
    tool = make_design_next_week_tool(deps, lambda: None)

    out = json.loads(await tool.ainvoke({}))

    assert out == {"error": "no active plan"}


async def test_config_not_exposed_in_model_facing_schema(make_deps):
    deps = make_deps(ScriptedChatModel(script=[]))
    tool = make_design_next_week_tool(deps, lambda: None)

    assert tool.args_schema is not None
    assert tool.args_schema.model_json_schema()["properties"] == {}
