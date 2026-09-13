from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_coach.graph.graph import build_graph
from tri_coach.testing import CFG, consult, move_call, propose, seed_active_plan
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS, FakeGarmin
from tri_nutrition.testing import FakeTp as NutritionFakeTp
from tri_planning import repo
from tri_planning.planning.models import TrainingGoal
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db


def graph_for(make_deps, mem_store, *, tp=None, garmin=None, **scripts):
    models = {
        k: ScriptedChatModel(script=scripts.get(k, []))
        for k in ("coach", "planning", "nutrition", "analyst")
    }
    deps = make_deps(tp=tp, garmin=garmin, **models)
    return build_graph(deps, InMemorySaver(), mem_store), models


async def test_reject_returns_to_the_coach_with_the_note(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    tp = FakeTp()
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[
            consult("planning", "Move w1."),
            propose("Move it.", ["p1"]),
            AIMessage(content="Understood, Wednesday stays."),
        ],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    out = await graph.ainvoke(
        Command(resume={"action": "reject", "note": "I like Wednesdays"}), CFG
    )
    assert "__interrupt__" not in out and tp.calls == []
    assert out["pending"] is None and out["review_decision"].action == "reject"
    assert any(
        isinstance(m, HumanMessage) and "Review rejected: I like Wednesdays" in m.content
        for m in out["messages"]
    )
    assert (
        out["messages"][-1].content == "Understood, Wednesday stays." and models["coach"].calls == 3
    )
    assert (await graph.aget_state(CFG)).next == ()


async def test_edit_replaces_the_change_set_before_apply(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    tp = FakeTp()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    edited = out["__interrupt__"][0].value["proposals"]
    edited[0]["changes"][0]["new_date"] = (MONDAY + timedelta(days=5)).isoformat()
    out = await graph.ainvoke(Command(resume={"action": "edit", "proposals": edited}), CFG)
    assert tp.calls == [
        (
            "tp_update_workout",
            {"workout_id": "w1", "date": (MONDAY + timedelta(days=5)).isoformat()},
        )
    ]
    assert out["pending"] is None


async def test_nutrition_handoff_proposes_and_apply_persists_overrides(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    garmin = FakeGarmin()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        garmin=garmin,
        tp=NutritionFakeTp(),
        coach=[
            consult(
                "nutrition",
                "Race block starts Monday; raise activity_factor to 1.45; keep the goal.",
            ),
            propose("Higher activity factor for the race block.", ["p1"]),
        ],
        nutrition=[
            tool_call(
                "propose_target_changes",
                {"overrides": {"activity_factor": 1.45}, "reason": "race block"},
            ),
            AIMessage(content="Proposed."),
        ],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("race block starts")]}, CFG)
    p = out["__interrupt__"][0].value["proposals"][0]
    assert p["domain"] == "nutrition" and p["changes"][0]["op"] == "set_day_targets"
    assert p["overrides"] == {"activity_factor": 1.45} and garmin.calls == []
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in garmin.calls] == ["set_nutrition_daily_settings"]
    assert (await S.get_profile(mem_store)).activity_factor == 1.45
    rows = ndb.execute("select thread_id from nutrition_changes").fetchall()
    assert [r["thread_id"] for r in rows] == ["coach"]
    assert out["reports"][0].domain == "nutrition" and out["reports"][0].applied == 1
    assert out["messages"][-1].content == "nutrition: applied 1"


async def test_bought_plan_is_adopted_after_apply(nocommit, make_deps, mem_store):
    repo.insert_goal(nocommit, TrainingGoal(**{**GOAL_ARGS, "tp_plan_id": "p1"}))
    workouts = [
        {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0}
    ]
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 1}})
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[
            consult("planning", "Activate the bought plan p1 from next Monday."),
            propose("Apply the bought plan.", ["p1"]),
        ],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("use my bought plan")]}, CFG)
    assert out["__interrupt__"][0].value["proposals"][0]["changes"][0]["op"] == "apply_plan"
    assert models["planning"].calls == 0  # targets proposes the apply_plan change without a model
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert repo.derive_phase(nocommit)[0] == "active" and out["pending"] is None


async def test_a_failing_adopt_is_reported_not_raised(nocommit, make_deps, mem_store):
    repo.insert_goal(nocommit, TrainingGoal(**{**GOAL_ARGS, "tp_plan_id": "p1"}))
    tp = FakeTp(fail_on_call=2)  # tp_apply_training_plan lands; the adopt's read blows up
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[
            consult("planning", "Activate the bought plan p1 from next Monday."),
            propose("Apply the bought plan.", ["p1"]),
        ],
    )
    await graph.ainvoke({"messages": [HumanMessage("use my bought plan")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert "boom" in out["last_error"] and "adopt" in out["last_error"]
    assert out["reports"][0].applied == 1 and out["pending"] is None
    assert (await graph.aget_state(CFG)).next == ()


async def test_partial_apply_keeps_the_remainder_pending_and_shows_it_next_turn(
    nocommit, make_deps, mem_store, monkeypatch
):
    from tri_coach.graph import nodes

    prompts: list[str] = []
    real = nodes.coach.make_subagent

    def record(model, tools, system_prompt):
        prompts.append(system_prompt)
        return real(model, tools, system_prompt)

    monkeypatch.setattr(nodes.coach, "make_subagent", record)
    seed_active_plan(nocommit)
    tp = FakeTp(fail_on_call=1)
    two_moves = tool_call(
        "propose_calendar_changes",
        {
            "summary": "two moves",
            "changes": [
                {
                    "op": "move",
                    "tp_workout_id": "w1",
                    "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                    "reason": "a",
                },
                {"op": "delete", "tp_workout_id": "w1", "reason": "b"},
            ],
        },
    )
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[
            consult("planning", "x"),
            propose("Two changes.", ["p1"]),
            AIMessage(content="Still pending."),
        ],
        planning=[two_moves, AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert out["reports"][0].applied == 0 and out["reports"][0].remaining == 2
    assert out["pending"] is not None and len(out["pending"].proposals[0].changes) == 2
    assert out["pending"].proposals[0].id == "held-planning"
    assert "boom" in out["last_error"] and "stopped:" in out["messages"][-1].content
    await graph.ainvoke({"messages": [HumanMessage("what now?")]}, CFG)
    assert "Pending change set from an earlier turn (2 planning, 0 nutrition)" in prompts[-1]
    assert "held-planning" in prompts[-1]


async def test_a_held_remainder_can_be_re_proposed_by_its_id_next_turn(
    nocommit, make_deps, mem_store
):
    seed_active_plan(nocommit)
    tp = FakeTp(fail_on_call=1)
    two_moves = tool_call(
        "propose_calendar_changes",
        {
            "summary": "two moves",
            "changes": [
                {
                    "op": "move",
                    "tp_workout_id": "w1",
                    "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                    "reason": "a",
                },
                {
                    "op": "move",
                    "tp_workout_id": "w1",
                    "new_date": (MONDAY + timedelta(days=5)).isoformat(),
                    "reason": "b",
                },
            ],
        },
    )
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[
            consult("planning", "x"),
            propose("Two changes.", ["p1"]),
            propose("Let us try the rest again.", ["held-planning"]),
        ],
        planning=[two_moves, AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert out["pending"].proposals[0].id == "held-planning"

    out = await graph.ainvoke({"messages": [HumanMessage("try the rest again")]}, CFG)
    assert "__interrupt__" in out, "the held remainder must reach review, not an unknown-id error"
    payload = out["__interrupt__"][0].value
    assert payload["proposals"][0]["id"] == "held-planning"
    assert len(payload["proposals"][0]["changes"]) == 2
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert out["reports"][0].applied == 2 and out["pending"] is None


async def test_start_clears_last_turns_proposals_but_not_pending(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[consult("planning", "x"), AIMessage(content="one"), AIMessage(content="two")],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("a")]}, CFG)
    assert (await graph.aget_state(CFG)).values["proposals"] != []
    await graph.ainvoke({"messages": [HumanMessage("b")]}, CFG)
    values = (await graph.aget_state(CFG)).values
    assert values["proposals"] == [] and values["brief"] is None and values["pending"] is None
