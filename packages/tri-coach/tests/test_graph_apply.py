from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_coach.graph.checkpointer import make_serde
from tri_coach.graph.graph import build_graph
from tri_coach.graph.nodes.apply import _regeneration_due, merge_held
from tri_coach.models import ApplyReport, ChangeSet, Proposal
from tri_coach.testing import CFG, consult, move_call, propose, seed_active_plan
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import repo as nrepo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import DayTarget, NutritionProfile
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
    return build_graph(deps, InMemorySaver(serde=make_serde()), mem_store), models


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


def held_set() -> ChangeSet:
    return ChangeSet(
        narration="Held from the last apply.",
        proposals=[
            Proposal.model_validate(
                {
                    "id": "held-planning",
                    "domain": "planning",
                    "summary": "1 planning changes held from the last apply",
                    "changes": [
                        {
                            "op": "move",
                            "tp_workout_id": "w1",
                            "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                            "reason": "rest day",
                        }
                    ],
                }
            ),
            Proposal.model_validate(
                {
                    "id": "held-nutrition",
                    "domain": "nutrition",
                    "summary": "1 nutrition changes held from the last apply",
                    "changes": [
                        {
                            "op": "set_day_targets",
                            "target_key": MONDAY.isoformat(),
                            "day": MONDAY.isoformat(),
                            "payload": {"calorie_goal": 2800},
                            "reason": "extend horizon",
                        }
                    ],
                }
            ),
        ],
    )


async def test_re_proposing_one_held_proposal_keeps_the_other_held(ndb, make_deps, mem_store):
    seed_active_plan(ndb)
    tp = FakeTp()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[propose("Retry the plan part.", ["held-planning"])],
    )
    await graph.aupdate_state(CFG, {"pending": held_set()}, as_node="start")
    out = await graph.ainvoke({"messages": [HumanMessage("retry the plan part")]}, CFG)
    assert [p["id"] for p in out["__interrupt__"][0].value["proposals"]] == ["held-planning"]
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    assert [p.id for p in out["pending"].proposals] == ["held-nutrition"]
    assert out["carried"] == []


async def test_rejecting_a_held_proposal_keeps_the_ones_it_did_not_name(ndb, make_deps, mem_store):
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            propose("Retry the plan part.", ["held-planning"]),
            AIMessage(content="Dropped the plan part."),
        ],
    )
    await graph.aupdate_state(CFG, {"pending": held_set()}, as_node="start")
    await graph.ainvoke({"messages": [HumanMessage("retry the plan part")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "not now"}), CFG)
    assert [p.id for p in out["pending"].proposals] == ["held-nutrition"]
    assert out["pending"].narration == "Held from the last apply."


async def test_a_proposal_without_changes_is_refused_at_review(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Lighten the week."),
            propose("Lighter week.", ["p1"]),
            AIMessage(content="Planning asked which session hurt; I will ask you."),
        ],
        planning=[AIMessage(content="Which session hurt: the run or the ride?")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]}, CFG)
    assert "__interrupt__" not in out and models["coach"].calls == 3
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("[review] p1 carry no changes")
        for m in out["messages"]
    )
    assert out["proposal_request"] is None and out["pending"] is None


async def test_an_exception_inside_apply_is_reported_and_the_changes_held(
    nocommit, make_deps, mem_store, monkeypatch
):
    from tri_coach.graph import nodes

    async def boom(*args, **kwargs):
        raise RuntimeError("psycopg went away")

    monkeypatch.setattr(nodes.apply, "apply_planning", boom)
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    report = out["reports"][0]
    assert report.domain == "planning" and report.applied == 0 and report.remaining == 1
    assert "RuntimeError: psycopg went away" in out["last_error"]
    held = out["pending"].proposals[0]
    assert held.id == "held-planning" and len(held.changes) == 1 and "unverified" in held.summary
    assert (await graph.aget_state(CFG)).next == ()


def test_merge_held_joins_a_shared_stable_id():
    plan = held_set().proposals[0]
    nut = held_set().proposals[1]
    merged = merge_held([plan, nut], [plan.model_copy(update={"summary": "new"})])
    assert [p.id for p in merged] == ["held-planning", "held-nutrition"]
    assert len(merged[0].changes) == 2 and merged[0].summary.startswith("2 planning changes")
    assert "unverified" not in merged[0].summary
    assert merge_held([], [nut]) == [nut] and merge_held([nut], []) == [nut]


def test_merge_held_keeps_the_unverified_warning_from_either_side():
    plan = held_set().proposals[0]
    unverified = plan.model_copy(
        update={"summary": "1 planning changes held unverified: apply raised"}
    )
    expected = "2 planning changes held from earlier applies, some unverified: apply raised"
    assert merge_held([plan], [unverified])[0].summary == expected
    assert merge_held([unverified], [plan])[0].summary == expected
    again = merge_held(merge_held([unverified], [plan]), [plan])[0]
    assert again.summary.startswith("3 planning changes") and "unverified" in again.summary


async def test_an_edit_naming_a_carried_held_proposal_does_not_hold_it_again(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    garmin = FakeGarmin()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=NutritionFakeTp(),
        garmin=garmin,
        coach=[propose("Retry the plan part.", ["held-planning"])],
    )
    await graph.aupdate_state(CFG, {"pending": held_set()}, as_node="start")
    out = await graph.ainvoke({"messages": [HumanMessage("retry the plan part")]}, CFG)
    assert [p["id"] for p in out["__interrupt__"][0].value["proposals"]] == ["held-planning"]
    edited = [held_set().proposals[1].model_dump(mode="json")]  # swapped for the carried one
    full = {"calorie_goal": 2800, "carbs_grams": 350, "protein_grams": 150, "fat_grams": 80}
    edited[0]["changes"][0]["payload"] = full
    out = await graph.ainvoke(Command(resume={"action": "edit", "proposals": edited}), CFG)
    assert [c[0] for c in garmin.calls] == ["set_nutrition_daily_settings"]
    assert out["reports"][0].domain == "nutrition" and out["reports"][0].applied == 1
    assert out["pending"] is None and out["carried"] == []


async def test_a_failing_regeneration_check_is_reported_and_the_apply_committed(
    nocommit, make_deps, mem_store, monkeypatch
):
    from types import SimpleNamespace

    from tri_coach.graph import nodes

    def boom(*args, **kwargs):
        raise RuntimeError("targets table went away")

    # only apply's binding: the coach's context loader reads targets through the real repo
    monkeypatch.setattr(nodes.apply, "nrepo", SimpleNamespace(list_targets=boom))
    seed_active_plan(nocommit)
    tp = FakeTp()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("move it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    skip = "regeneration skipped: RuntimeError: targets table went away"
    assert out["pending"] is None and out["regenerate_after_apply"] is False
    assert skip in out["last_error"] and skip in out["messages"][-1].content
    assert out["reports"][0].applied == 1
    assert (await graph.aget_state(CFG)).next == ()


async def test_a_plan_change_that_moves_sessions_regenerates_nutrition_and_opens_a_second_gate(
    ndb, make_deps, mem_store
):
    seed_active_plan(ndb)
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    nrepo.upsert_targets(
        ndb,
        [
            DayTarget(
                day=MONDAY + timedelta(days=i),
                day_type="easy",
                session_kcal=0,
                total_kcal=2000,
                carbs_g=200,
                protein_g=150,
                fat_g=70,
                fluid_baseline_ml=2500,
                source="plan",
            )
            for i in range(3)
        ],
    )
    tp, garmin = FakeTp(), FakeGarmin()
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        garmin=garmin,
        coach=[
            consult("planning", "Move w1."),
            propose("Move it.", ["p1"]),
            propose("Today's targets follow the moved session.", ["p1"], "c10"),
        ],
        planning=[move_call(), AIMessage(content="ok")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("move it")]}, CFG)
    assert out["__interrupt__"][0].value["proposals"][0]["domain"] == "planning"

    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    second = out["__interrupt__"][0].value
    assert second["narration"].startswith("Today's targets")
    assert [(p["id"], p["domain"]) for p in second["proposals"]] == [("p1", "nutrition")]
    assert second["proposals"][0]["changes"][0]["op"] == "set_day_targets"
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("[follow-on]") for m in out["messages"]
    )
    assert garmin.calls == [] and models["nutrition"].calls == 0 and models["coach"].calls == 3

    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in garmin.calls] == ["set_nutrition_daily_settings"]
    assert [r.domain for r in out["reports"]] == ["nutrition"]
    assert out["regenerate_after_apply"] is False and out["pending"] is None
    assert (await graph.aget_state(CFG)).next == ()


async def test_no_regeneration_without_targets_in_the_horizon(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("move it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert out["reports"][0].sessions_changed is True and out["regenerate_after_apply"] is False
    assert out["proposals"] == [] and models["coach"].calls == 2
    assert (await graph.aget_state(CFG)).next == ()


def test_regeneration_is_due_when_planning_moved_sessions_and_targets_exist(ndb, make_deps):
    deps = make_deps(
        **{k: ScriptedChatModel(script=[]) for k in ("coach", "planning", "nutrition", "analyst")}
    )
    nrepo.upsert_targets(
        ndb,
        [
            DayTarget(
                day=MONDAY,
                day_type="easy",
                session_kcal=0,
                total_kcal=2000,
                carbs_g=200,
                protein_g=150,
                fat_g=70,
                fluid_baseline_ml=2500,
                source="plan",
            )
        ],
    )
    clean_apply = ApplyReport(
        domain="planning", applied=1, skipped=[], remaining=0, error=None, sessions_changed=True
    )
    assert _regeneration_due(deps, [clean_apply]) is True
