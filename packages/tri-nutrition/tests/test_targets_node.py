from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.targets import make_targets_node
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, seed_ftp, seed_goal_and_plan, session_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    if nocommit.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    return nocommit


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("targets", node)
    g.add_edge(START, "targets")
    g.add_edge("targets", END)
    return g.compile(store=store)


def node_graph(make_deps, mem_store, horizon):
    return one_node_graph(
        make_targets_node(make_deps(ScriptedChatModel(script=[]), horizon=horizon)), mem_store
    )


async def test_builds_upserts_and_proposes_today(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    seed_ftp(ndb, 250)
    hard_run = session_json(MONDAY + timedelta(days=2), "run", 50, "threshold", 60)
    seed_goal_and_plan(ndb, MONDAY, [("build", [hard_run]), ("build", None)])
    graph = node_graph(make_deps, mem_store, 7)
    out = await graph.ainvoke({"profile_saved": True, "regenerate_from": "intake"}, CFG)
    assert [c.day for c in out["pending_changes"]] == [MONDAY] and out["profile_saved"] is False
    assert out["pending_changes"][0].op == "set_day_targets"
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6))
    assert len(stored) == 7 and stored[2].target.day_type == "hard"
    assert stored[0].target.plan_phase == "build" and stored[0].target.source == "plan"
    assert "hard" in out["pending_summary"] and "2026-09-16" in out["pending_summary"]
    assert out["last_error"] is None


async def test_unchanged_written_days_are_not_reproposed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    graph = node_graph(make_deps, mem_store, 3)
    first = await graph.ainvoke({"profile_saved": True}, CFG)
    assert [c.day for c in first["pending_changes"]] == [MONDAY]
    repo.mark_targets_written(ndb, [MONDAY])
    out = await graph.ainvoke({"profile_saved": True}, CFG)
    assert out["pending_changes"] == [] and "already on Garmin" in out["pending_summary"]


async def test_overrides_apply_on_top_of_store_profile(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    graph = node_graph(make_deps, mem_store, 1)
    base = await graph.ainvoke({"profile_saved": True}, CFG)
    more = await graph.ainvoke(
        {"profile_saved": True, "profile_overrides": {"activity_factor": 1.5}}, CFG
    )
    base_kcal = base["pending_changes"][0].payload["calorie_goal"]
    assert more["pending_changes"][0].payload["calorie_goal"] > base_kcal


async def test_bounds_violation_writes_nothing(ndb, make_deps, mem_store):
    # a 45 kg athlete with the max deficit lands below 30 kcal/kg FFM
    small = {
        **PROFILE_ARGS,
        "weight_kg": 45,
        "height_cm": 150,
        "body_fat_pct": 10,
        "goal": "lose",
        "target_weight_kg": 40,
        "max_weekly_change_pct": 1.0,
        "activity_factor": 1.2,
    }
    await S.put_profile(mem_store, NutritionProfile(**small))
    graph = node_graph(make_deps, mem_store, 7)
    out = await graph.ainvoke({"profile_saved": True}, CFG)
    assert out["pending_changes"] == [] and "energy availability" in out["last_error"]
    last = out["messages"][-1]
    assert isinstance(last, AIMessage) and "energy availability" in last.content
    assert repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6)) == []


async def test_without_profile_sets_error(ndb, make_deps, mem_store):
    graph = node_graph(make_deps, mem_store, 14)
    out = await graph.ainvoke({}, CFG)
    assert out["pending_changes"] == [] and "no nutrition profile" in out["last_error"]
