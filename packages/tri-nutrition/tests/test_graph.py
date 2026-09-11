from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.graph import after_review, build_graph, route_start
from tri_nutrition.nutrition.models import NutritionProfile, ReviewDecision
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin

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
