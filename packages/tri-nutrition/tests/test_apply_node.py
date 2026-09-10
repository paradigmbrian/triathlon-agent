from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.apply import make_apply_node
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import day_target_change
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def target(day=MONDAY, **over) -> DayTarget:
    base = dict(
        day=day,
        day_type="easy",
        session_kcal=0,
        total_kcal=2800,
        carbs_g=280,
        protein_g=150,
        fat_g=120,
        fluid_baseline_ml=2800,
        source="plan",
    )
    base.update(over)
    return DayTarget(**base)


def apply_graph(make_deps, mem_store, garmin):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("apply", make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=garmin)))
    g.add_edge(START, "apply")
    g.add_edge("apply", END)
    return g.compile(store=mem_store)


def state(changes, **over):
    return {"pending_changes": changes, "pending_summary": "s", **over}


async def test_applies_today_records_row_and_marks_written(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target(), target(MONDAY + timedelta(days=1))])
    g = FakeGarmin()
    out = await apply_graph(make_deps, mem_store, g).ainvoke(
        state([day_target_change(target())]), CFG
    )
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert [c[0] for c in g.calls] == ["set_nutrition_daily_settings"]
    assert g.calls[0][1]["date"] == "2026-09-14" and g.calls[0][1]["calorie_goal"] == 2800
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=1))
    assert [s.written_to_garmin for s in stored] == [True, False]
    rows = ndb.execute(
        "select operation, target_key, result from nutrition_changes order by id"
    ).fetchall()
    assert [r["target_key"] for r in rows] == ["2026-09-14"]
    assert rows[0]["result"]["status"] == "updated"
    assert "applied 1 of 1" in out["messages"][-1].content


async def test_future_day_is_refused_and_batch_stops(ndb, make_deps, mem_store):
    ts = [target(), target(MONDAY + timedelta(days=1)), target(MONDAY + timedelta(days=2))]
    repo.upsert_targets(ndb, ts)
    g = FakeGarmin()
    out = await apply_graph(make_deps, mem_store, g).ainvoke(
        state([day_target_change(t) for t in ts]), CFG
    )
    assert [c.day for c in out["pending_changes"]] == [
        MONDAY + timedelta(days=1),
        MONDAY + timedelta(days=2),
    ]
    assert "only hold today" in out["last_error"] and "2026-09-15" in out["last_error"]
    assert len(g.calls) == 1  # today went through, the future day never reached Garmin
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=2))
    assert [s.written_to_garmin for s in stored] == [True, False, False]
    assert ndb.execute("select count(*) as n from nutrition_changes").fetchone()["n"] == 1


async def test_garmin_failure_keeps_change_pending(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target()])
    g = FakeGarmin(fail_on_call=1)
    out = await apply_graph(make_deps, mem_store, g).ainvoke(
        state([day_target_change(target())]), CFG
    )
    assert [c.day for c in out["pending_changes"]] == [MONDAY]
    assert "boom" in out["last_error"]
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is False
    assert ndb.execute("select count(*) as n from nutrition_changes").fetchone()["n"] == 0


async def test_refuses_without_garmin(ndb, make_deps, mem_store):
    out = await apply_graph(make_deps, mem_store, None).ainvoke(
        state([day_target_change(target())]), CFG
    )
    assert len(out["pending_changes"]) == 1 and "unavailable" in out["last_error"]


async def test_overrides_persist_to_store_on_full_success(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    out = await apply_graph(make_deps, mem_store, FakeGarmin()).ainvoke(
        state([day_target_change(target())], profile_overrides={"activity_factor": 1.5}), CFG
    )
    assert out["profile_overrides"] is None
    assert (await S.get_profile(mem_store)).activity_factor == 1.5


async def test_non_garmin_ops_are_skipped_with_reason(ndb, make_deps, mem_store):
    note = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="r")
    g = FakeGarmin()
    out = await apply_graph(make_deps, mem_store, g).ainvoke(state([note]), CFG)
    assert g.calls == [] and out["pending_changes"] == []
    assert "skipped" in out["messages"][-1].content
