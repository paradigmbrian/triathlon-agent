import contextlib
from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph

import tri_nutrition.graph.nodes.fuel as fuel_node
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.config import NutritionSettings
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.deps import make_deps as real_make_deps
from tri_nutrition.graph.nodes.fuel import make_fuel_node, qualifies, race_due
from tri_nutrition.graph.nodes.targets import build_horizon
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import (
    NutritionProfile,
    PlanContext,
    RaceFuelPlan,
    Session,
    SessionFuel,
)
from tri_nutrition.testing import (
    MONDAY,
    PROFILE_ARGS,
    race_plan_json,
    seed_goal_and_plan,
    seed_workouts,
    session_fuel_json,
    session_json,
)

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}
RACE = MONDAY + timedelta(days=13)
TUE = MONDAY + timedelta(days=2)


@pytest.fixture
def ndb(nocommit):
    for t in ("nutrition_targets", "plan_weeks"):
        if nocommit.execute(f"select to_regclass('{t}') as t").fetchone()["t"] is None:
            pytest.skip(f"{t} missing: migrations not applied")
    return nocommit


def test_qualifies_and_race_due():
    long = Session(day=MONDAY, sport="bike", duration_min=90, intensity="endurance")
    short = Session(day=MONDAY, sport="run", duration_min=40, intensity="endurance")
    hard = Session(day=MONDAY, sport="run", duration_min=40, intensity="threshold")
    assert qualifies(long) and qualifies(hard) and not qualifies(short)
    assert race_due(PlanContext(source="plan", event_date=MONDAY + timedelta(days=21)), MONDAY)
    assert not race_due(PlanContext(source="plan", event_date=MONDAY + timedelta(days=22)), MONDAY)
    assert not race_due(PlanContext(source="plan", event_date=MONDAY - timedelta(days=1)), MONDAY)
    assert not race_due(PlanContext(source="plan"), MONDAY)


def fuel_graph(deps, mem_store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("fuel", make_fuel_node(deps))
    g.add_edge(START, "fuel")
    g.add_edge("fuel", END)
    return g.compile(store=mem_store)


async def seeded(ndb, mem_store, make_deps, model, *, with_race=True, horizon=14):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    week = [
        session_json(MONDAY, "bike", 120, "endurance", 100),  # qualifies (long)
        session_json(TUE, "run", 45, "threshold", 60),  # qualifies (hard)
        session_json(MONDAY + timedelta(days=4), "swim", 45, "endurance", 40),  # does not
    ]
    seed_goal_and_plan(
        ndb, MONDAY, [("build", week), ("peak", None)], event_date=RACE if with_race else None
    )
    seed_workouts(
        ndb,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 7200,
                "title": "bike 120",
            },
            {
                "tp_workout_id": "w2",
                "workout_date": TUE,
                "sport": "run",
                "planned_duration_sec": 2700,
                "title": "run 45",
            },
        ],
    )
    deps = make_deps(model, horizon=horizon)
    h = await build_horizon(deps, mem_store)
    assert not h.violations
    return deps, fuel_graph(deps, mem_store), h


def fuel_call(workout_id, day, **over):
    return tool_call("SessionFuel", session_fuel_json(workout_id, day, **over))


async def test_plans_qualifying_sessions_and_race(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    out = await graph.ainvoke({"pending_changes": h.changes, "pending_summary": h.summary()}, CFG)
    assert model.calls == 3
    ops = [c.op for c in out["pending_changes"]]
    assert ops == ["set_day_targets", "set_session_note", "set_session_note", "set_race_note"]
    assert out["pending_changes"][-1].target_key == ""  # create
    plans = repo.list_fuel_plans(ndb, MONDAY, RACE)
    assert [(p.kind, p.tp_workout_id) for p in plans] == [
        ("session", "w1"),
        ("session", "w2"),
        ("race", None),
    ]
    assert all(p.violations == [] and not p.written for p in plans)
    assert "60 g/h" in out["pending_summary"] and "Race fuel" in out["pending_summary"]
    assert "2026-09-14" in out["pending_summary"]


async def test_retries_once_and_keeps_violations(ndb, mem_store, make_deps):
    bad = fuel_call("w1", MONDAY, carbs_g_per_h=95)  # needs evidence at 90
    good = fuel_call("w1", MONDAY)
    model = ScriptedChatModel(
        script=[
            bad,
            good,
            fuel_call("w2", TUE, products=["Mystery"]),
            fuel_call("w2", TUE, products=["Mystery"]),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    out = await graph.ainvoke({"pending_changes": h.changes}, CFG)
    assert model.calls == 5
    w2 = next(p for p in repo.list_fuel_plans(ndb, MONDAY, RACE) if p.tp_workout_id == "w2")
    assert any("Mystery" in v for v in w2.violations)
    assert "VIOLATIONS" in out["pending_summary"] and "Mystery" in out["pending_summary"]
    # a session plan with violations is still proposed; the athlete decides at review, and
    # check-in --yes reads pending_violations to skip it
    assert [c.op for c in out["pending_changes"]].count("set_session_note") == 2
    assert list(out["pending_violations"]) == ["w2"]


async def test_unchanged_written_notes_are_not_reproposed(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model, with_race=False)
    await graph.ainvoke({"pending_changes": []}, CFG)
    plans = repo.list_fuel_plans(ndb, MONDAY, MONDAY + timedelta(days=13))
    repo.mark_fuel_written(ndb, plans[0].id, None)
    out = await graph.ainvoke({"pending_changes": []}, CFG)
    assert [c.target_key for c in out["pending_changes"]] == ["w2"]


async def test_race_update_uses_stored_note_id(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    rid = repo.upsert_fuel_plan(ndb, "race", RACE, None, {"note_text": "old"}, [])
    repo.mark_fuel_written(ndb, rid, "note-77")
    out = await graph.ainvoke({"pending_changes": []}, CFG)
    race = next(c for c in out["pending_changes"] if c.op == "set_race_note")
    assert race.target_key == "note-77"


async def test_session_without_workout_id_is_stored_not_written(ndb, mem_store, make_deps):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    seed_goal_and_plan(
        ndb, MONDAY, [("build", [session_json(MONDAY, "bike", 120, "endurance", 100)])]
    )
    model = ScriptedChatModel(script=[fuel_call("unmatched", MONDAY)])
    deps = make_deps(model, horizon=7)
    h = await build_horizon(deps, mem_store)
    out = await fuel_graph(deps, mem_store).ainvoke({"pending_changes": []}, CFG)
    assert out["pending_changes"] == []
    assert "not on the TrainingPeaks calendar" in out["pending_summary"]
    plans = repo.list_fuel_plans(ndb, MONDAY, MONDAY)
    assert len(plans) == 1 and plans[0].tp_workout_id is None and h.targets


async def test_no_profile_is_a_no_op(ndb, mem_store, make_deps):
    graph = fuel_graph(make_deps(ScriptedChatModel(script=[])), mem_store)
    out = await graph.ainvoke({"pending_changes": [], "last_error": "x"}, CFG)
    assert out["pending_changes"] == [] and out["last_error"] == "x"


def test_the_fuel_node_plans_with_the_fuel_model_when_one_is_set(monkeypatch):
    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        return ScriptedChatModel(script=[])

    monkeypatch.setattr(fuel_node, "structured", spy)
    agent, fueler = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    deps = GraphDeps(model=agent, connect=lambda: contextlib.nullcontext(None), db_url="unused")
    make_fuel_node(deps)
    deps.fuel_model = fueler
    make_fuel_node(deps)
    assert seen == [
        (agent, SessionFuel),
        (agent, RaceFuelPlan),
        (fueler, SessionFuel),
        (fueler, RaceFuelPlan),
    ]


def test_make_deps_takes_an_optional_fuel_model():
    agent, fueler = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    settings = NutritionSettings(_env_file=None)
    assert real_make_deps(settings, agent, None).fuel_model is None
    assert real_make_deps(settings, agent, None, None, fuel_model=fueler).fuel_model is fueler
