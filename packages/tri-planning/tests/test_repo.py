from datetime import date, timedelta

import pytest

from tri_core.db import repo as core_repo
from tri_core.db.models import DailyMetricsRow
from tri_planning import repo
from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    TrainingGoal,
    WeekTarget,
)

pytestmark = pytest.mark.db

MON = date(2026, 9, 14)


@pytest.fixture
def pdb(db):
    if db.execute("select to_regclass('training_goals') as t").fetchone()["t"] is None:
        pytest.skip("migrations/002_planning.sql not applied to the test database")
    return db


def goal(**over) -> TrainingGoal:
    base = dict(
        goal_type="olympic",
        event_name="City Tri",
        event_date=date(2026, 12, 13),
        priority="A",
        weekly_hours_min=6,
        weekly_hours_max=10,
        available_days={"mon": [], "sat": "any"},
        constraints=["pool closed Fridays"],
    )
    base.update(over)
    return TrainingGoal(**base)


def targets(n=3):
    return [
        WeekTarget(
            week_start=MON + timedelta(weeks=i),
            phase="base",
            target_tss=300 + i,
            target_hours=6,
            sport_hint="h",
        )
        for i in range(n)
    ]


def test_goal_roundtrip(pdb):
    gid = repo.insert_goal(pdb, goal())
    stored = repo.get_goal(pdb, gid)
    assert stored is not None and stored.id == gid and stored.status == "active"
    assert stored.goal.available_days["mon"] == [] and stored.goal.available_days["sat"] == "any"
    assert stored.goal.constraints == ["pool closed Fridays"]
    assert repo.get_active_goal(pdb).id == gid
    repo.set_goal_event(pdb, gid, "evt-1")
    assert repo.get_goal(pdb, gid).tp_event_id == "evt-1"


def test_plan_and_weeks(pdb):
    gid = repo.insert_goal(pdb, goal())
    pid = repo.insert_plan(pdb, gid, "generated", None, targets())
    plan = repo.get_plan(pdb, pid)
    assert plan.start_date == MON and plan.end_date == MON + timedelta(weeks=2, days=6)
    assert [t.target_tss for t in plan.skeleton] == [300, 301, 302]
    assert repo.get_active_plan(pdb, gid).id == pid
    weeks = repo.list_weeks(pdb, pid)
    assert [w.week_start for w in weeks] == [
        MON,
        MON + timedelta(weeks=1),
        MON + timedelta(weeks=2),
    ]
    assert all(w.designed is None and not w.written_to_tp for w in weeks)

    designed = PlannedWeek(
        week_start=MON,
        sessions=[
            PlannedSession(
                date=MON,
                sport="swim",
                title="Swim",
                description="",
                duration_minutes=45,
                tss_planned=40,
                intensity="endurance",
            )
        ],
        coach_note="easy start",
    )
    repo.set_week_designed(pdb, pid, MON, designed)
    repo.mark_weeks_written(pdb, pid, [MON])
    first = repo.list_weeks(pdb, pid)[0]
    assert first.designed == designed and first.written_to_tp is True


def test_changes_and_ownership(pdb):
    gid = repo.insert_goal(pdb, goal())
    pid = repo.insert_plan(pdb, gid, "generated", None, targets(1))
    create = CalendarChange(op="create", workout_date=MON, reason="plan")
    repo.insert_change(pdb, pid, "planning", create, tp_workout_id="w1", result={"success": True})
    repo.insert_change(pdb, pid, "planning", create, tp_workout_id="w2", result={"success": True})
    assert repo.owned_workout_ids(pdb, pid) == {"w1", "w2"}
    delete = CalendarChange(op="delete", tp_workout_id="w2", reason="dropped")
    repo.insert_change(pdb, pid, "planning", delete, tp_workout_id="w2", result={"success": True})
    assert repo.owned_workout_ids(pdb, pid) == {"w1"}
    row = pdb.execute("select * from plan_changes where tp_workout_id = 'w1'").fetchone()
    assert row["operation"] == "create" and row["payload"]["op"] == "create"
    assert row["workout_date"] == MON and row["reason"] == "plan"


def test_abandon_active(pdb):
    gid = repo.insert_goal(pdb, goal())
    repo.insert_plan(pdb, gid, "generated", None, targets(1))
    assert repo.abandon_active(pdb) == (1, 1)
    assert repo.get_active_goal(pdb) is None
    assert repo.get_active_plan(pdb, gid) is None
    assert repo.get_goal(pdb, gid).status == "abandoned"


def test_fitness_snapshot(pdb):
    as_of = date(2026, 9, 14)
    rows = [
        DailyMetricsRow(metric_date=as_of - timedelta(days=d), tss_day=70.0, ctl=40.0 + d)
        for d in range(1, 29)
    ]
    core_repo.upsert_daily_metrics(pdb, rows)
    snap = repo.fitness_snapshot(pdb, as_of)
    assert snap.ctl == 41  # the latest row, one day before as_of
    assert snap.recent_weekly_tss == pytest.approx(70 * 28 / 4)


def test_fitness_snapshot_empty(pdb):
    snap = repo.fitness_snapshot(pdb, date(1999, 1, 1))
    assert snap.ctl is None and snap.recent_weekly_tss is None
