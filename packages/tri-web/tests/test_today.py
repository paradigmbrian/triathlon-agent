"""TodayView with and without a plan, targets, metrics and labs; the pending badge."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from tri_coach.models import ChangeSet, Proposal
from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_core.db import repo as crepo
from tri_nutrition import repo as nrepo
from tri_nutrition.nutrition.models import DayTarget
from tri_nutrition.testing import seed_workouts
from tri_planning.testing import MONDAY, FakeTp
from tri_web.today import TodayView, build_today

pytestmark = pytest.mark.db

TODAY = MONDAY + timedelta(days=2)  # Wednesday 2026-09-16


def seed_day(conn, day: date) -> None:
    seed_workouts(
        conn,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": day,
                "sport": "run",
                "title": "Tempo",
                "planned_duration_sec": 3600,
                "planned_tss": 60,
            },
            {
                "tp_workout_id": "w0",
                "workout_date": day - timedelta(days=1),
                "sport": "bike",
                "planned_duration_sec": 5400,
                "planned_tss": 80,
                "completed": True,
            },
        ],
    )
    conn.execute(
        "insert into daily_metrics (metric_date, sleep_seconds, sleep_score, "
        "hrv_overnight_avg, resting_hr, body_battery_high, training_readiness, "
        "ctl, atl, tsb) values (%s, 27000, 81, 62, 48, 92, 77, 45.2, 50.1, -4.9)",
        (day,),
    )
    nrepo.upsert_targets(
        conn,
        [
            DayTarget(
                day=day,
                day_type="moderate",
                session_kcal=600,
                total_kcal=2900,
                carbs_g=380,
                protein_g=150,
                fat_g=80,
                fluid_baseline_ml=2500,
                source="plan",
            )
        ],
    )
    nrepo.upsert_fuel_plan(conn, "session", day, "w1", {"carbs_g_per_h": 60, "pre": "toast"}, [])
    crepo.set_sync_state(conn, "garmin", day, "ok", None)


async def test_today_with_everything(nocommit, runtime):
    seed_active_plan(nocommit)
    seed_day(nocommit, TODAY)
    rt = runtime(today=TODAY)
    view = await build_today(rt)
    assert isinstance(view, TodayView)
    h = view.header
    assert h.today == TODAY and h.phase == "active"
    assert (
        h.goal is not None
        and h.goal.event_date is not None
        and h.goal.days_to_go == (h.goal.event_date - TODAY).days
    )
    assert h.week.start == MONDAY and h.week.number == 1 and h.week.of == 3
    assert [s.source for s in h.last_sync] == ["garmin"] and h.last_sync[0].status == "ok"
    assert view.session is not None
    assert [w.tp_workout_id for w in view.session.workouts] == ["w1"]
    assert (
        view.session.workouts[0].planned_tss == 60 and view.session.workouts[0].completed is False
    )
    assert view.session.fuel is not None and view.session.fuel.payload["carbs_g_per_h"] == 60
    r = view.readiness
    assert r is not None and r.is_today and r.date == TODAY
    assert r.sleep_hours == 7.5 and r.sleep_score == 81 and r.hrv == 62 and r.resting_hr == 48
    assert r.body_battery == 92 and r.training_readiness == 77
    assert (r.ctl, r.atl, r.tsb) == (45.2, 50.1, -4.9)
    assert (
        view.fuel.target is not None
        and view.fuel.target.total_kcal == 2900
        and view.fuel.target.day_type == "moderate"
    )
    assert view.fuel.targets_through == TODAY
    w = view.week
    assert w is not None and w.phase == "build" and w.target_tss == 300 and w.target_hours == 6
    assert (
        w.actual_hours == 0 and w.actual_tss == 0
    )  # w0 has no actual_duration_sec; no tss_day rows
    assert {(s.sport, s.planned, s.completed) for s in w.sessions} == {
        ("run", 1, 0),
        ("bike", 1, 1),
    }
    assert view.labs is None and view.labs_enabled is False and view.labs_missing is False
    assert view.pending is None


async def test_today_with_nothing(nocommit, runtime):
    view = await build_today(runtime(today=TODAY))
    assert view.header.phase == "intake" and view.header.goal is None
    assert view.header.week.number is None and view.header.last_sync == []
    assert view.session is None and view.readiness is None
    assert view.fuel.target is None and view.fuel.targets_through is None
    assert view.week is None and view.pending is None


async def test_readiness_falls_back_to_the_latest_earlier_row(nocommit, runtime):
    nocommit.execute(
        "insert into daily_metrics (metric_date, sleep_score, ctl) values (%s, 70, 40)",
        (TODAY - timedelta(days=2),),
    )
    view = await build_today(runtime(today=TODAY))
    r = view.readiness
    assert r is not None and r.is_today is False and r.date == TODAY - timedelta(days=2)
    assert r.sleep_score == 70 and r.ctl == 40 and r.sleep_hours is None


async def test_pending_shows_a_paused_review(nocommit, runtime):
    seed_active_plan(nocommit)
    rt = runtime(
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
        today=TODAY,
    )
    from langchain_core.messages import HumanMessage

    from tri_web.runtime import cfg

    await rt.graph.ainvoke(
        {"messages": [HumanMessage("my knee hurts")]}, {**cfg(rt), "recursion_limit": 60}
    )
    view = await build_today(rt)
    assert view.pending is not None and view.pending.narration == "Move it."
    assert view.pending.proposals[0]["id"] == "p1"


async def test_pending_shows_a_held_change_set(nocommit, runtime):
    rt = runtime(today=TODAY)
    held = ChangeSet(
        narration="Held.",
        proposals=[Proposal(id="p1", domain="planning", summary="s", changes=[])],
    )
    from tri_web.runtime import cfg

    await rt.graph.aupdate_state(cfg(rt), {"pending": held}, as_node="start")
    view = await build_today(rt)
    assert view.pending is not None and view.pending.narration == "Held."


def test_decimals_become_floats():
    from tri_web.today import _f

    assert _f(Decimal("45.20")) == 45.2 and _f(None) is None and _f(3) == 3.0
