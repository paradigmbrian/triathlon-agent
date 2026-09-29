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
from tri_web.metrics import BASELINE_DAYS
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


async def test_week_number_is_none_before_the_plan_starts(nocommit, runtime):
    seed_active_plan(nocommit)
    before = MONDAY - timedelta(days=7)  # a week before the plan's first week
    view = await build_today(runtime(today=before))
    assert view.header.week.number is None and view.header.week.of is None


def test_decimals_become_floats():
    from tri_web.today import _f

    assert _f(Decimal("45.20")) == 45.2 and _f(None) is None and _f(3) == 3.0


def seed_metrics(conn, end: date, *, gap: date | None = None) -> None:
    """28 days ending on `end`: HRV 60 and RHR 48 every day, then 50 and 55 on `end`; CTL rising
    0.5 a day from 40; ATL 60 and TSB -6.5 on `end`; no training readiness or sleep time."""
    for i in range(BASELINE_DAYS):
        d = end - timedelta(days=BASELINE_DAYS - 1 - i)
        if d == gap:
            continue
        last = d == end
        conn.execute(
            "insert into daily_metrics (metric_date, sleep_score, hrv_overnight_avg, resting_hr, "
            "ctl, atl, tsb) values (%s, 80, %s, %s, %s, %s, %s)",
            (
                d,
                50 if last else 60,
                55 if last else 48,
                40 + 0.5 * i,
                60 if last else 50,
                -6.5 if last else 0,
            ),
        )


async def test_trends_from_28_days_of_metrics(nocommit, runtime):
    seed_metrics(nocommit, TODAY, gap=TODAY - timedelta(days=3))
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None
    assert set(r.trends) == {"hrv", "resting_hr", "sleep_score"}
    hrv = r.trends["hrv"]
    assert hrv.now == 50 and hrv.band == "below" and hrv.better is False
    rhr = r.trends["resting_hr"]
    assert rhr.band == "above" and rhr.better is False
    assert len(hrv.spark) == 14 and hrv.spark[10] is None
    assert r.tsb_zone == "neutral"
    assert r.ramp_7d == 3.5 and r.ramp_caution is False
    assert r.acwr == 1.12 and r.acwr_flag is None


async def test_trends_anchor_on_the_readiness_row(nocommit, runtime):
    seed_metrics(nocommit, TODAY - timedelta(days=2))
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None and r.is_today is False
    assert r.trends["hrv"].now == 50 and r.trends["hrv"].band == "below"


async def test_one_row_of_metrics_gives_no_ramp_and_no_band(nocommit, runtime):
    nocommit.execute(
        "insert into daily_metrics (metric_date, hrv_overnight_avg, ctl, atl, tsb) "
        "values (%s, 60, 0, 10, 30)",
        (TODAY,),
    )
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None
    assert r.trends["hrv"].band is None
    assert r.ramp_7d is None and r.acwr is None and r.acwr_flag is None
    assert r.tsb_zone == "detraining"


async def test_workout_detail_and_per_sport_week(nocommit, runtime):
    seed_active_plan(nocommit)
    seed_day(nocommit, TODAY)
    nocommit.execute(
        "update workouts set completed = true, actual_duration_sec = 3780, actual_tss = 57, "
        "actual_if = 0.82, avg_hr = 148, avg_power = 212, normalized_power = 225 "
        "where tp_workout_id = 'w1'"
    )
    view = await build_today(runtime(today=TODAY))
    assert view.session is not None
    w1 = view.session.workouts[0]
    assert (w1.actual_if, w1.avg_hr, w1.avg_power, w1.normalized_power) == (0.82, 148, 212, 225)
    week = view.week
    assert week is not None
    by = {s.sport: s for s in week.sessions}
    assert (by["run"].planned_tss, by["run"].actual_tss) == (60, 57)
    assert (by["run"].planned_hours, by["run"].actual_hours) == (1.0, 1.05)
    assert (by["bike"].planned_tss, by["bike"].actual_tss, by["bike"].planned_hours) == (80, 0, 1.5)
    assert (week.planned_to_date, week.completed_to_date) == (2, 2)
