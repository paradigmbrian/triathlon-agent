from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.graph import after_targets
from tri_planning.graph.nodes.targets import make_targets_node, weekly_targets_from_workouts
from tri_planning.planning.models import TrainingGoal
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def stored_goal(conn, **over):
    return repo.insert_goal(conn, TrainingGoal(**{**GOAL_ARGS, **over}))


async def test_generated_goal_builds_plan_and_summarizes(nocommit, make_deps):
    gid = stored_goal(nocommit)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[])))
    out = await node({"goal_id": gid, "phase": "planning"}, CFG)
    plan = repo.get_plan(nocommit, out["plan_id"])
    assert plan.source == "generated" and len(plan.targets) == 14 and plan.start_date == MONDAY
    assert isinstance(out["messages"][0], AIMessage) and "14 weeks" in out["messages"][0].content
    assert len(repo.list_weeks(nocommit, plan.id)) == 14


async def test_existing_plan_is_not_rebuilt(nocommit, make_deps):
    gid = stored_goal(nocommit)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[])))
    first = await node({"goal_id": gid, "phase": "planning"}, CFG)
    again = await node({"goal_id": gid, "phase": "planning", "plan_id": first["plan_id"]}, CFG)
    assert again == {}


async def test_bought_plan_proposes_apply_plan(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1", create_tp_event=True)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    out = await node({"goal_id": gid, "phase": "planning"}, CFG)
    ops = [c.op for c in out["pending_changes"]]
    assert ops == ["create_event", "apply_plan"] and out["changes_from"] == "targets"
    assert out["pending_changes"][1].payload == {
        "plan_id": "p1",
        "start_date": MONDAY.isoformat(),
        "calendar_before": [],
    }
    assert out["pending_violations"] == {}


async def test_bought_plan_after_apply_derives_targets_and_ownership(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    workouts = [
        {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0},
        {
            "id": "w2",
            "date": (MONDAY + timedelta(days=3)).isoformat(),
            "tss_planned": 80,
            "duration_planned": 1.5,
        },
        {
            "id": "w3",
            "date": (MONDAY + timedelta(weeks=1)).isoformat(),
            "tss_planned": 100,
            "duration_planned": 2.0,
        },
        {
            "id": "w4",
            "date": (MONDAY + timedelta(weeks=2)).isoformat(),
            "tss_planned": 40,
            "duration_planned": 1.0,
        },
    ]
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 4}})
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node({"goal_id": gid, "phase": "planning", "tp_plan_applied": True}, CFG)
    assert out["phase"] == "active" and out["tp_plan_applied"] is False
    plan = repo.get_plan(nocommit, out["plan_id"])
    assert plan.source == "tp_plan" and [t.target_tss for t in plan.targets] == [140, 100, 40]
    assert [t.phase for t in plan.targets] == ["peak", "taper", "race"]
    assert all(w.written_to_tp for w in repo.list_weeks(nocommit, plan.id))
    assert repo.owned_workout_ids(nocommit, plan.id) == {"w1", "w2", "w3", "w4"}
    assert tp.calls[0][0] == "tp_get_workouts"


async def test_empty_adoption_ends_the_run_and_is_not_proposed_again(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    tp = FakeTp()  # its tp_get_workouts answers with no workouts
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    state = {"goal_id": gid, "phase": "planning", "tp_plan_applied": True}
    out = await node(state, CFG)
    assert "plan_id" not in out and "p1" in out["messages"][0].content
    assert after_targets({**state, **out}) == END
    assert repo.get_goal(nocommit, gid).tp_plan_applied_at is not None
    # a later run starts from the tables: the plan is on TrainingPeaks, so it is adopted
    # again, never proposed again
    again = await node({"goal_id": gid, "phase": "planning"}, CFG)
    assert "pending_changes" not in again and "plan_id" not in again
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_get_workouts"]


async def test_adoption_owns_only_the_workouts_the_plan_added(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    mine = {
        "id": "a1",
        "date": (MONDAY + timedelta(days=1)).isoformat(),
        "tss_planned": 30,
        "duration_planned": 0.5,
    }
    added = {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0}
    tp = FakeTp(listings=[[mine], [mine, added]])
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    proposed = await node({"goal_id": gid, "phase": "planning"}, CFG)
    apply_plan = proposed["pending_changes"][-1]
    assert apply_plan.payload["calendar_before"] == ["a1"]
    assert tp.calls[0][1]["workout_filter"] == "planned"
    # the apply node records the change as sent; the adoption reads the listing back from it
    repo.insert_change(
        nocommit, None, "t", apply_plan, tp_workout_id=None, result={"success": True}
    )
    out = await node({"goal_id": gid, "phase": "planning", "tp_plan_applied": True}, CFG)
    assert repo.owned_workout_ids(nocommit, out["plan_id"]) == {"w1"}
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_get_workouts"]


def test_weekly_targets_from_workouts_groups_by_monday():
    ws = [
        {
            "id": "a",
            "date": (MONDAY + timedelta(days=2)).isoformat(),
            "tss_planned": 50,
            "duration_planned": 1.0,
        },
        {
            "id": "b",
            "date": (MONDAY + timedelta(days=6)).isoformat(),
            "tss_planned": 50,
            "duration_planned": None,
        },
        {
            "id": "c",
            "date": (MONDAY + timedelta(days=8)).isoformat(),
            "tss_planned": None,
            "duration_planned": 2.0,
        },
    ]
    targets = weekly_targets_from_workouts(ws, MONDAY)
    assert [(t.week_start, t.target_tss, t.target_hours) for t in targets] == [
        (MONDAY, 100, 1.0),
        (MONDAY + timedelta(weeks=1), 0, 2.0),
    ]
