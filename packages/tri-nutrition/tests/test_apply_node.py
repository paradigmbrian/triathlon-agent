from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.apply import ApplyResult, apply_changes, make_apply_node
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import day_target_change
from tri_nutrition.nutrition.models import DayTarget, NutritionProfile, RaceFuelPlan, SessionFuel
from tri_nutrition.nutrition.tp_calls import race_note_change, session_note_change
from tri_nutrition.testing import (
    MONDAY,
    PROFILE_ARGS,
    FakeGarmin,
    FakeTp,
    race_plan_json,
    session_fuel_json,
)

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
    assert "Applied 1 of 1" in out["messages"][-1].content


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


def apply_graph2(make_deps, mem_store, garmin, tp):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    deps = make_deps(ScriptedChatModel(script=[]), garmin=garmin, tp=tp)
    g.add_node("apply", make_apply_node(deps))
    g.add_edge(START, "apply")
    g.add_edge("apply", END)
    return g.compile(store=mem_store)


def session_change(workout_id="w1", day=MONDAY):
    return session_note_change(SessionFuel.model_validate(session_fuel_json(workout_id, day)))


async def test_session_note_written_when_note_empty_then_owned(ndb, make_deps, mem_store):
    repo.upsert_fuel_plan(ndb, "session", MONDAY, "w1", {"note_text": "n"}, [])
    tp = FakeTp()
    graph = apply_graph2(make_deps, mem_store, FakeGarmin(), tp)
    out = await graph.ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note", "tp_set_workout_note"]
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert repo.list_fuel_plans(ndb, MONDAY, MONDAY)[0].written is True
    assert repo.session_note_owned(ndb, "w1")
    # second write: owned, no read needed even if the athlete has since typed a note
    tp2 = FakeTp(responses={"tp_get_workout_note": {"note": "athlete wrote this"}})
    graph = apply_graph2(make_deps, mem_store, FakeGarmin(), tp2)
    out = await graph.ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp2.calls] == ["tp_set_workout_note"] and out["pending_changes"] == []


async def test_session_note_refused_when_athlete_note_exists(ndb, make_deps, mem_store):
    tp = FakeTp(responses={"tp_get_workout_note": {"note": "my own reminder"}})
    graph = apply_graph2(make_deps, mem_store, FakeGarmin(), tp)
    out = await graph.ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note"]
    assert out["pending_changes"] == [] and "not agent-authored" in out["messages"][-1].content


async def test_race_note_create_records_id_then_update_owned(ndb, make_deps, mem_store):
    plan = RaceFuelPlan.model_validate(race_plan_json(MONDAY + timedelta(days=10)))
    repo.upsert_fuel_plan(ndb, "race", plan.event_date, None, plan.model_dump(mode="json"), [])
    tp = FakeTp()
    create = race_note_change(plan, "Race fuel: City Tri", None)
    await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(state([create]), CFG)
    assert tp.calls[0][0] == "tp_create_note"
    plans = repo.list_fuel_plans(ndb, plan.event_date, plan.event_date)
    race = next(p for p in plans if p.kind == "race")
    assert race.written and race.tp_note_id == "n1"
    assert repo.owned_note_ids(ndb) == {"n1"}
    update = race_note_change(plan, "Race fuel: City Tri", "n1")
    tp2 = FakeTp()
    await apply_graph2(make_deps, mem_store, FakeGarmin(), tp2).ainvoke(state([update]), CFG)
    assert tp2.calls[0] == (
        "tp_update_note",
        {"note_id": "n1", "title": "Race fuel: City Tri", "description": plan.note_text},
    )
    foreign = race_note_change(plan, "Race fuel: City Tri", "coach-9")
    tp3 = FakeTp()
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp3).ainvoke(state([foreign]), CFG)
    assert tp3.calls == [] and "not agent-authored" in out["messages"][-1].content


async def test_tp_down_holds_notes_but_garmin_applies(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target()])
    g = FakeGarmin()
    out = await apply_graph2(make_deps, mem_store, g, None).ainvoke(
        state([day_target_change(target()), session_change()]), CFG
    )
    assert len(g.calls) == 1 and [c.op for c in out["pending_changes"]] == ["set_session_note"]
    assert "TrainingPeaks server unavailable" in out["last_error"]


async def test_tp_failure_stops_batch_and_keeps_remainder(ndb, make_deps, mem_store):
    tp = FakeTp(fail_on_call=2)  # get_workout_note ok, set fails
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(
        state([session_change("w1"), session_change("w2", MONDAY + timedelta(days=1))]), CFG
    )
    assert [c.target_key for c in out["pending_changes"]] == ["w1", "w2"]
    assert "boom" in out["last_error"]


async def test_apply_changes_direct_records_thread_and_persists_overrides(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    g = FakeGarmin()
    deps = make_deps(ScriptedChatModel(script=[]), garmin=g)
    r = await apply_changes(
        deps, mem_store, [day_target_change(target())], "coach", overrides={"activity_factor": 1.5}
    )
    assert isinstance(r, ApplyResult)
    assert [c.op for c in r.applied] == ["set_day_targets"]
    assert r.remaining == [] and r.held == [] and r.skipped == [] and r.error is None
    assert r.profile_updated is True
    assert (await S.get_profile(mem_store)).activity_factor == 1.5
    rows = ndb.execute("select thread_id from nutrition_changes").fetchall()
    assert [row["thread_id"] for row in rows] == ["coach"]
    text = r.report(1, {"activity_factor": 1.5})
    assert text.startswith("Applied 1 of 1 changes (Garmin 1, TrainingPeaks 0).")
    assert "profile updated" in text


async def test_apply_changes_direct_holds_when_the_server_is_down(ndb, make_deps, mem_store):
    deps = make_deps(ScriptedChatModel(script=[]), garmin=None)
    r = await apply_changes(deps, mem_store, [day_target_change(target())], "coach", overrides=None)
    assert r.applied == [] and len(r.remaining) == 1 and r.held == r.remaining
    assert r.error is not None and "Garmin server unavailable" in r.error
    assert r.profile_updated is False
    assert "1 change(s) still pending" in r.report(1, None)


async def test_apply_changes_direct_does_not_persist_overrides_on_partial(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    deps = make_deps(ScriptedChatModel(script=[]), garmin=FakeGarmin(fail_on_call=1))
    r = await apply_changes(
        deps, mem_store, [day_target_change(target())], "coach", overrides={"activity_factor": 1.5}
    )
    assert r.error is not None and "boom" in r.error and r.profile_updated is False
    assert (await S.get_profile(mem_store)).activity_factor == 1.35
