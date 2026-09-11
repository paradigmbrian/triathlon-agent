from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import plan_loader, repo
from tri_nutrition import store as S
from tri_nutrition.graph.graph import after_checkin, after_review, build_graph, route_start
from tri_nutrition.nutrition.models import NutritionProfile, ReviewDecision
from tri_nutrition.nutrition.targets import build
from tri_nutrition.repl import checkin_run
from tri_nutrition.testing import (
    MONDAY,
    PROFILE_ARGS,
    FakeGarmin,
    FakeTp,
    race_plan_json,
    seed_goal_and_plan,
    seed_workouts,
    session_fuel_json,
    session_json,
)

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "nutrition"}}
APPROVE = Command(resume={"action": "approve"})


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def intake_script():
    return [
        tool_call("save_nutrition_profile", PROFILE_ARGS),
        AIMessage(content="Profile saved. Building your targets."),
    ]


def make_graph(make_deps, mem_store, model, garmin, horizon=7):
    deps = make_deps(model, garmin=garmin, horizon=horizon)
    return build_graph(deps, InMemorySaver(), mem_store)


async def test_intake_to_review_pauses_before_any_write(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert len(payload["changes"]) == 1 and "kcal" in payload["summary"]
    assert payload["changes"][0]["day"] == MONDAY.isoformat()
    assert g.calls == []
    snap = await graph.aget_state(CFG)
    assert snap.next == ("review",) and snap.values["regenerate_from"] == "intake"
    assert (await S.get_profile(mem_store)) is not None


async def test_approve_applies_and_writes_garmin(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and len(g.calls) == 1
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6))
    assert [s.written_to_garmin for s in stored] == [True] + [False] * 6
    assert "Applied 1 of 1" in out["messages"][-1].content


async def test_reject_routes_back_to_intake_with_note(ndb, make_deps, mem_store):
    model = ScriptedChatModel(
        script=[*intake_script(), AIMessage(content="What would you like to change?")]
    )
    graph = make_graph(make_deps, mem_store, model, FakeGarmin())
    await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "too few carbs"}), CFG)
    assert "__interrupt__" not in out and model.calls == 3
    msgs = out["messages"]
    assert any(isinstance(m, HumanMessage) and "too few carbs" in m.content for m in msgs)
    assert isinstance(msgs[-1], AIMessage) and "change" in msgs[-1].content


async def test_new_thread_with_profile_routes_to_checkin(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[AIMessage(content="Your profile is set; ask me anything.")])
    graph = make_graph(make_deps, mem_store, model, FakeGarmin())
    out = await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert out["has_profile"] is True and "__interrupt__" not in out
    assert out["messages"][-1].content.startswith("Your profile")


async def test_checkin_profile_edit_regenerates_targets(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    edited = {**PROFILE_ARGS, "activity_factor": 1.5}
    model = ScriptedChatModel(
        script=[tool_call("save_nutrition_profile", edited), AIMessage(content="Updated.")]
    )
    graph = make_graph(make_deps, mem_store, model, FakeGarmin(), horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("I'm on my feet all day now")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 1
    assert (await graph.aget_state(CFG)).values["regenerate_from"] == "checkin"


async def test_edit_replaces_change_set(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    out = await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    edited = out["__interrupt__"][0].value["changes"]
    edited[0]["payload"] = {**edited[0]["payload"], "carbs_grams": 300, "calorie_goal": 9999}
    out = await graph.ainvoke(Command(resume={"action": "edit", "changes": edited}), CFG)
    assert len(g.calls) == 1 and out["pending_changes"] == []
    sent = g.calls[0][1]
    assert sent["carbs_grams"] == 300 and sent["calorie_goal"] != 9999  # consistency fix applied


async def test_garmin_failure_keeps_today_pending_then_reproposes(ndb, make_deps, mem_store):
    g = FakeGarmin(fail_on_call=1)
    model = ScriptedChatModel(script=[*intake_script(), AIMessage(content="Trying again.")])
    graph = make_graph(make_deps, mem_store, model, g, horizon=4)
    await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(out["pending_changes"]) == 1 and "boom" in out["last_error"]
    g.fail_on_call = None
    out = await graph.ainvoke({"messages": [HumanMessage("try again")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 1
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and len(g.calls) == 2  # 1 failed + 1 retried


def test_route_functions():
    assert route_start({"pending_changes": [1]}) == "review"
    assert route_start({"has_profile": False}) == "intake"
    assert route_start({"has_profile": True}) == "checkin"
    assert after_review({"review_decision": ReviewDecision(action="approve")}) == "apply"
    reject = ReviewDecision(action="reject")
    assert after_review({"review_decision": reject, "regenerate_from": "checkin"}) == "checkin"
    assert after_review({"review_decision": reject, "regenerate_from": "intake"}) == "intake"
    assert after_review({"review_decision": reject}) == "__end__"
    assert after_review({"review_decision": None}) == "__end__"


async def test_intake_to_review_with_fuel_and_approve_writes_both_servers(
    ndb, make_deps, mem_store
):
    if ndb.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    race = MONDAY + timedelta(days=6)
    week = [session_json(MONDAY, "bike", 120, "endurance", 100)]
    seed_goal_and_plan(ndb, MONDAY, [("race", week)], event_date=race)
    seed_workouts(
        ndb,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 7200,
                "title": "bike 120",
            }
        ],
    )
    model = ScriptedChatModel(
        script=[
            *intake_script(),
            tool_call("SessionFuel", session_fuel_json("w1", MONDAY)),
            tool_call("RaceFuelPlan", race_plan_json(race)),
        ]
    )
    g, tp = FakeGarmin(), FakeTp()
    deps = make_deps(model, garmin=g, tp=tp, horizon=7)
    graph = build_graph(deps, InMemorySaver(), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    payload = out["__interrupt__"][0].value
    assert [c["op"] for c in payload["changes"]] == [
        "set_day_targets",
        "set_session_note",
        "set_race_note",
    ]
    assert "Race fuel" in payload["summary"]
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert [c[0] for c in g.calls] == ["set_nutrition_daily_settings"]
    assert [c[0] for c in tp.calls] == [
        "tp_get_workout_note",
        "tp_set_workout_note",
        "tp_create_note",
    ]
    plans = repo.list_fuel_plans(ndb, MONDAY, race)
    assert all(p.written for p in plans)
    assert next(p for p in plans if p.kind == "race").tp_note_id == "n3"


def proposal_script(overrides, reason="evidence"):
    call = tool_call("propose_target_changes", {"overrides": overrides, "reason": reason})
    return [call, AIMessage(content="Proposed.")]


def baseline_kcal(ndb, horizon=3):
    sessions, ctx = plan_loader.load_horizon(ndb, MONDAY, horizon)
    return build(NutritionProfile(**PROFILE_ARGS), sessions, ctx, MONDAY, horizon)[0].total_kcal


async def test_checkin_proposal_regenerates_and_approve_persists_overrides(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    model = ScriptedChatModel(script=proposal_script({"activity_factor": 1.5}, "on my feet"))
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    payload = out["__interrupt__"][0].value
    assert payload["changes"][0]["payload"]["calorie_goal"] > baseline_kcal(ndb)
    snap = await graph.aget_state(CFG)
    assert snap.values["profile_overrides"] == {"activity_factor": 1.5}
    assert snap.values["regenerate_from"] == "checkin"
    assert snap.values["targets_requested"] is False
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(g.calls) == 1 and out["pending_changes"] == []
    assert out["profile_overrides"] is None
    assert (await S.get_profile(mem_store)).activity_factor == 1.5
    assert "profile updated" in out["messages"][-1].content


async def test_checkin_proposal_reject_discards_overrides(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[
            *proposal_script({"activity_factor": 1.5}),
            AIMessage(content="Understood, the targets stand."),
        ]
    )
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    reject = Command(resume={"action": "reject", "note": "I sit most of the day"})
    out = await graph.ainvoke(reject, CFG)
    assert "__interrupt__" not in out and g.calls == [] and model.calls == 3
    assert out["profile_overrides"] is None and out["pending_changes"] == []
    assert (await S.get_profile(mem_store)).activity_factor == 1.35
    assert any(isinstance(m, HumanMessage) and "I sit most" in m.content for m in out["messages"])
    assert out["messages"][-1].content.startswith("Understood")


async def test_checkin_extend_horizon_reproposes_today_only_when_changed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    script = [*proposal_script({}, "extend horizon"), *proposal_script({}, "extend horizon")]
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=script), g, horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert len(out["__interrupt__"][0].value["changes"]) == 1
    await graph.ainvoke(APPROVE, CFG)
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is True
    out = await graph.ainvoke({"messages": [HumanMessage("check in again")]}, CFG)
    assert "__interrupt__" not in out and len(g.calls) == 1  # today already on Garmin
    assert "No nutrition changes to review" in out["messages"][-1].content


def test_after_checkin_routes_on_either_flag():
    assert after_checkin({"profile_saved": True}) == "targets"
    assert after_checkin({"targets_requested": True}) == "targets"
    assert after_checkin({"profile_saved": False, "targets_requested": False}) == END
    assert after_checkin({}) == END


async def test_checkin_run_pauses_then_approves_on_second_run(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    model = ScriptedChatModel(script=proposal_script({}, "extend horizon"))
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=False) == 3
    text = "".join(printed)
    assert "approve / reject" in text and "paused" in text and g.calls == []
    printed.clear()
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=True) == 0
    assert "already waiting at review" in "".join(printed) and len(g.calls) == 1
    assert (await graph.aget_state(CFG)).next == ()


async def test_checkin_run_returns_zero_when_nothing_proposed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[AIMessage(content="Targets stand.")])
    graph = make_graph(make_deps, mem_store, model, FakeGarmin(), horizon=3)
    assert await checkin_run(graph, thread_id="nutrition", out=lambda s: None, approve=True) == 0
