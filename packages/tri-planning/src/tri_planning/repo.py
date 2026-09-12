"""Planning-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_planning.planning.models import (
    CalendarChange,
    FitnessSnapshot,
    GraphPhase,
    PlannedWeek,
    PlanWeekRow,
    StoredGoal,
    StoredPlan,
    TrainingGoal,
    WeekTarget,
)


def insert_goal(conn: Conn, goal: TrainingGoal) -> int:
    row = conn.execute(
        """
        insert into training_goals (goal_type, event_name, event_date, duration_weeks, priority,
            weekly_hours_min, weekly_hours_max, available_days, constraints, tp_plan_id,
            create_tp_event)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            goal.goal_type,
            goal.event_name,
            goal.event_date,
            goal.duration_weeks,
            goal.priority,
            goal.weekly_hours_min,
            goal.weekly_hours_max,
            Jsonb(goal.available_days),
            Jsonb(goal.constraints),
            goal.tp_plan_id,
            goal.create_tp_event,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _goal(row: dict[str, Any]) -> StoredGoal:
    return StoredGoal(
        id=row["id"],
        status=row["status"],
        tp_event_id=row["tp_event_id"],
        goal=TrainingGoal(
            goal_type=row["goal_type"],
            event_name=row["event_name"],
            event_date=row["event_date"],
            duration_weeks=row["duration_weeks"],
            priority=row["priority"],
            weekly_hours_min=float(row["weekly_hours_min"]),
            weekly_hours_max=float(row["weekly_hours_max"]),
            available_days=row["available_days"],
            constraints=row["constraints"] or [],
            tp_plan_id=row["tp_plan_id"],
            create_tp_event=row["create_tp_event"],
        ),
    )


def get_goal(conn: Conn, goal_id: int) -> StoredGoal | None:
    row = conn.execute("select * from training_goals where id = %s", (goal_id,)).fetchone()
    return _goal(row) if row else None


def get_active_goal(conn: Conn) -> StoredGoal | None:
    row = conn.execute(
        "select * from training_goals where status = 'active' order by created_at desc, id desc "
        "limit 1"
    ).fetchone()
    return _goal(row) if row else None


def set_goal_event(conn: Conn, goal_id: int, tp_event_id: str) -> None:
    conn.execute("update training_goals set tp_event_id = %s where id = %s", (tp_event_id, goal_id))


def insert_plan(
    conn: Conn, goal_id: int, source: str, tp_plan_id: str | None, targets: list[WeekTarget]
) -> int:
    if not targets:
        raise ValueError("targets is empty")
    start = targets[0].week_start
    end = targets[-1].week_start + timedelta(days=6)
    row = conn.execute(
        """
        insert into training_plans (goal_id, source, tp_plan_id, start_date, end_date, targets)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (
            goal_id,
            source,
            tp_plan_id,
            start,
            end,
            Jsonb([t.model_dump(mode="json") for t in targets]),
        ),
    ).fetchone()
    assert row is not None
    plan_id = int(row["id"])
    with conn.cursor() as cur:
        for t in targets:
            cur.execute(
                "insert into plan_weeks (plan_id, week_start, phase, target_tss, target_hours) "
                "values (%s, %s, %s, %s, %s)",
                (plan_id, t.week_start, t.phase, t.target_tss, t.target_hours),
            )
    return plan_id


def _plan(row: dict[str, Any]) -> StoredPlan:
    return StoredPlan(
        id=row["id"],
        goal_id=row["goal_id"],
        source=row["source"],
        tp_plan_id=row["tp_plan_id"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        targets=[WeekTarget.model_validate(t) for t in row["targets"]],
        status=row["status"],
    )


def get_plan(conn: Conn, plan_id: int) -> StoredPlan | None:
    row = conn.execute("select * from training_plans where id = %s", (plan_id,)).fetchone()
    return _plan(row) if row else None


def get_active_plan(conn: Conn, goal_id: int) -> StoredPlan | None:
    row = conn.execute(
        "select * from training_plans where goal_id = %s and status = 'active' "
        "order by created_at desc, id desc limit 1",
        (goal_id,),
    ).fetchone()
    return _plan(row) if row else None


def derive_phase(conn: Conn) -> tuple[GraphPhase, int | None, int | None]:
    """Where a run starts, from the tables: no active goal is intake; an active goal without an
    active plan is planning; an active plan is active. Returns (phase, goal_id, plan_id)."""
    goal = get_active_goal(conn)
    if goal is None:
        return "intake", None, None
    plan = get_active_plan(conn, goal.id)
    if plan is None:
        return "planning", goal.id, None
    return "active", goal.id, plan.id


def list_weeks(conn: Conn, plan_id: int) -> list[PlanWeekRow]:
    rows = conn.execute(
        "select * from plan_weeks where plan_id = %s order by week_start", (plan_id,)
    ).fetchall()
    return [
        PlanWeekRow(
            plan_id=r["plan_id"],
            week_start=r["week_start"],
            phase=r["phase"],
            target_tss=float(r["target_tss"]) if r["target_tss"] is not None else None,
            target_hours=float(r["target_hours"]) if r["target_hours"] is not None else None,
            designed=PlannedWeek.model_validate(r["designed"]) if r["designed"] else None,
            written_to_tp=r["written_to_tp"],
        )
        for r in rows
    ]


def set_week_designed(conn: Conn, plan_id: int, week_start: date, week: PlannedWeek) -> None:
    conn.execute(
        "update plan_weeks set designed = %s where plan_id = %s and week_start = %s",
        (Jsonb(week.model_dump(mode="json")), plan_id, week_start),
    )


def mark_weeks_written(conn: Conn, plan_id: int, week_starts: list[date]) -> None:
    if not week_starts:
        return
    conn.execute(
        "update plan_weeks set written_to_tp = true where plan_id = %s and week_start = any(%s)",
        (plan_id, week_starts),
    )


def insert_change(
    conn: Conn,
    plan_id: int | None,
    thread_id: str,
    change: CalendarChange,
    *,
    tp_workout_id: str | None,
    result: dict[str, Any] | None,
) -> int:
    row = conn.execute(
        """
        insert into plan_changes (plan_id, thread_id, operation, tp_workout_id, workout_date,
            payload, result, reason)
        values (%s, %s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (
            plan_id,
            thread_id,
            change.op,
            tp_workout_id,
            change.workout_date,
            Jsonb(change.model_dump(mode="json")),
            Jsonb(result) if result is not None else None,
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def owned_workout_ids(conn: Conn, plan_id: int) -> set[str]:
    rows = conn.execute(
        "select operation, tp_workout_id from plan_changes "
        "where plan_id = %s and tp_workout_id is not null",
        (plan_id,),
    ).fetchall()
    created = {r["tp_workout_id"] for r in rows if r["operation"] in ("create", "apply_plan")}
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    return created - deleted


def abandon_active(conn: Conn) -> tuple[int, int]:
    plans = conn.execute(
        "update training_plans set status = 'superseded' where status = 'active'"
    ).rowcount
    goals = conn.execute(
        "update training_goals set status = 'abandoned' where status = 'active'"
    ).rowcount
    return goals, plans


def fitness_snapshot(conn: Conn, as_of: date) -> FitnessSnapshot:
    ctl_row = conn.execute(
        "select ctl from daily_metrics where metric_date <= %s and ctl is not null "
        "order by metric_date desc limit 1",
        (as_of,),
    ).fetchone()
    tss_row = conn.execute(
        "select sum(tss_day) as total, count(tss_day) as n from daily_metrics "
        "where metric_date between %s and %s",
        (as_of - timedelta(days=28), as_of - timedelta(days=1)),
    ).fetchone()
    weekly = None
    if tss_row and tss_row["n"]:
        weekly = float(tss_row["total"]) / 4
    return FitnessSnapshot(ctl=float(ctl_row["ctl"]) if ctl_row else None, recent_weekly_tss=weekly)


def athlete_thresholds(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, hr_zones, power_zones, pace_zones from athlete_profile where id = 1"
    ).fetchone()


def owned_workouts(conn: Conn, plan_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select operation, tp_workout_id, workout_date, payload from plan_changes "
        "where plan_id = %s and tp_workout_id is not null order by applied_at, id",
        (plan_id,),
    ).fetchall()
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["operation"] not in ("create", "apply_plan") or r["tp_workout_id"] in deleted:
            continue
        w = (r["payload"] or {}).get("workout") or {}
        out[r["tp_workout_id"]] = {
            "tp_workout_id": r["tp_workout_id"],
            "workout_date": r["workout_date"],
            "sport": w.get("sport"),
            "title": w.get("title"),
        }
    return sorted(out.values(), key=lambda d: (d["workout_date"] or date.min, d["tp_workout_id"]))


def recent_sessions(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select workout_date, sport, title, completed, planned_tss, actual_tss, "
        "planned_duration_sec, actual_duration_sec, rpe, feeling from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def _avg(conn: Conn, col: str, start: date, end: date) -> float | None:
    row = conn.execute(
        f"select avg({col}) as v from daily_metrics where metric_date between %s and %s",
        (start, end),
    ).fetchone()
    return float(row["v"]) if row and row["v"] is not None else None


def recovery_baseline(conn: Conn, as_of: date) -> dict[str, float | None]:
    d1, d3, d30 = as_of - timedelta(days=1), as_of - timedelta(days=3), as_of - timedelta(days=30)
    tsb_row = conn.execute(
        "select tsb from daily_metrics where metric_date <= %s and tsb is not null "
        "order by metric_date desc limit 1",
        (as_of,),
    ).fetchone()
    return {
        "readiness_3d": _avg(conn, "training_readiness", d3, d1),
        "readiness_30d": _avg(conn, "training_readiness", d30, d1),
        "hrv_3d": _avg(conn, "hrv_overnight_avg", d3, d1),
        "hrv_30d": _avg(conn, "hrv_overnight_avg", d30, d1),
        "tsb": float(tsb_row["tsb"]) if tsb_row else None,
    }
