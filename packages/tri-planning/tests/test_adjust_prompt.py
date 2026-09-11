from datetime import date, timedelta

import pytest

from tri_core.db import repo as core_repo
from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_planning import repo
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal, WeekTarget
from tri_planning.prompts.adjust import AdjustContext, load_adjust_context, render_adjust_prompt
from tri_planning.testing import GOAL_ARGS, MONDAY

pytestmark = pytest.mark.db


def workout(day, **over):
    base = dict(
        tp_workout_id=f"tp{day}",
        workout_date=MONDAY + timedelta(days=day),
        sport="run",
        sport_raw=None,
        title="Run",
        description=None,
        completed=True,
        planned_duration_sec=3600,
        planned_distance_m=None,
        planned_tss=50,
        planned_if=None,
        actual_duration_sec=3500,
        actual_distance_m=None,
        actual_tss=48,
        actual_if=None,
        normalized_power=None,
        avg_power=None,
        avg_hr=None,
        avg_cadence=None,
        elevation_gain_m=None,
        calories=None,
        feeling=None,
        rpe=None,
        comments=None,
        structure=None,
        raw={},
    )
    base.update(over)
    return WorkoutRow(**base)


def seed(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=300, target_hours=6
        )
        for i in range(4)
    ]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(
        date=MONDAY + timedelta(weeks=1),
        sport="bike",
        title="Long ride",
        description="",
        duration_minutes=120,
        tss_planned=90,
        intensity="endurance",
    )
    repo.insert_change(
        conn,
        pid,
        "planning",
        CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"),
        tp_workout_id="w9",
        result={},
    )
    repo.mark_weeks_written(conn, pid, [MONDAY, MONDAY + timedelta(weeks=1)])
    return pid


def test_owned_workouts_carry_title_and_sport(nocommit):
    pid = seed(nocommit)
    owned = repo.owned_workouts(nocommit, pid)
    assert owned == [
        {
            "tp_workout_id": "w9",
            "workout_date": MONDAY + timedelta(weeks=1),
            "sport": "bike",
            "title": "Long ride",
        }
    ]


def test_recovery_baseline_and_sessions(nocommit):
    today = MONDAY + timedelta(days=7)
    rows = [
        DailyMetricsRow(
            metric_date=today - timedelta(days=d),
            training_readiness=60 if d > 3 else 40,
            hrv_overnight_avg=50 if d > 3 else 45,
            tsb=-5,
        )
        for d in range(1, 31)
    ]
    core_repo.upsert_daily_metrics(nocommit, rows)
    core_repo.upsert_workouts(nocommit, [workout(1, rpe=9), workout(3, feeling=2), workout(5)])
    b = repo.recovery_baseline(nocommit, today)
    assert b["readiness_3d"] == 40 and b["readiness_30d"] == pytest.approx((3 * 40 + 27 * 60) / 30)
    assert b["hrv_3d"] == 45 and b["tsb"] == -5
    sessions = repo.recent_sessions(nocommit, today - timedelta(days=7), today)
    assert [s["rpe"] for s in sessions] == [9, None, None] and sessions[1]["feeling"] == 2


def test_load_context_counts_designed_weeks_and_extension(nocommit):
    pid = seed(nocommit)
    ctx = load_adjust_context(nocommit, MONDAY + timedelta(days=2), pid, horizon=3)
    assert ctx.this_week.week_start == MONDAY and ctx.next_week.week_start == MONDAY + timedelta(
        weeks=1
    )
    assert ctx.designed_remaining == 2 and ctx.extension_needed is False
    ctx2 = load_adjust_context(nocommit, MONDAY + timedelta(weeks=1, days=1), pid, horizon=3)
    assert ctx2.designed_remaining == 1 and ctx2.extension_needed is True


def test_render_flags_rpe_and_feeling_and_lists_owned_ids():
    goal = TrainingGoal(**GOAL_ARGS)
    ctx = AdjustContext(
        today=date(2026, 9, 21),
        goal=goal,
        this_week=None,
        next_week=None,
        actual_tss_this_week=0,
        sessions=[
            {
                "workout_date": date(2026, 9, 15),
                "sport": "run",
                "title": "Tempo",
                "completed": True,
                "planned_tss": 60,
                "actual_tss": 70,
                "planned_duration_sec": 3600,
                "actual_duration_sec": 3900,
                "rpe": 9,
                "feeling": 2,
            }
        ],
        baseline={
            "readiness_3d": 40.0,
            "readiness_30d": 60.0,
            "hrv_3d": 45.0,
            "hrv_30d": 50.0,
            "tsb": -12.0,
        },
        owned=[
            {
                "tp_workout_id": "w9",
                "workout_date": date(2026, 9, 22),
                "sport": "bike",
                "title": "Long ride",
            }
        ],
        designed_remaining=1,
        horizon=3,
        extension_needed=True,
        checkin=False,
    )
    text = render_adjust_prompt(ctx)
    assert "FLAG" in text and "rpe 9" in text and "feeling 2" in text
    assert "w9" in text and "Long ride" in text
    assert "swap days" in text and "re-plan the week" in text
    assert "Window extension needed: yes" in text and "design_next_week" in text
    assert text.index("Lever order") < text.index("Today is")  # stable rules first, data after
