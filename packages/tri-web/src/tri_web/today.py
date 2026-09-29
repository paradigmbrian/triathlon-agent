"""The Today strip in one call: what load_context already knows (phase, goal, plan, this week,
labs) plus today's rows from workouts, daily_metrics, nutrition_targets and fuel_plans."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from tri_coach.context import LabSummary, load_context
from tri_core.db import repo as crepo
from tri_core.harness.turns import paused_review
from tri_nutrition import repo as nrepo
from tri_planning import repo as prepo
from tri_planning.planning.targets import week_monday
from tri_web.metrics import (
    BASELINE_DAYS,
    RAMP_CAUTION,
    MetricTrend,
    acwr,
    acwr_flag,
    ramp,
    trend,
    tsb_zone,
)
from tri_web.runtime import Runtime, cfg
from tri_web.thread import ReviewPayload, review_payload

SOURCES = ("trainingpeaks", "garmin")


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


class GoalOut(BaseModel):
    goal_type: str
    event_name: str | None
    event_date: date | None
    days_to_go: int | None


class WeekHeader(BaseModel):
    start: date
    number: int | None  # 1-based week of the plan; None without a plan
    of: int | None


class SyncOut(BaseModel):
    source: str
    last_synced_date: date
    last_run_at: datetime
    status: str
    error: str | None


class HeaderOut(BaseModel):
    today: date
    phase: str
    goal: GoalOut | None
    week: WeekHeader
    last_sync: list[SyncOut]


class WorkoutOut(BaseModel):
    tp_workout_id: str
    sport: str
    title: str | None
    completed: bool
    planned_duration_sec: int | None
    planned_tss: float | None
    actual_duration_sec: int | None
    actual_tss: float | None
    actual_if: float | None
    avg_hr: int | None
    avg_power: int | None
    normalized_power: int | None


class FuelPlanOut(BaseModel):
    id: int
    kind: str
    tp_workout_id: str | None
    payload: dict[str, Any]
    violations: list[str]
    written: bool


class SessionOut(BaseModel):
    """null: "No session planned"."""

    workouts: list[WorkoutOut]
    fuel: FuelPlanOut | None  # the plan for the first planned workout, when one is stored


class ReadinessOut(BaseModel):
    """null: "No Garmin data yet, sync first"."""

    date: date
    is_today: bool
    sleep_score: int | None
    sleep_hours: float | None
    hrv: int | None
    resting_hr: int | None
    body_battery: int | None
    training_readiness: int | None
    ctl: float | None
    atl: float | None
    tsb: float | None
    trends: dict[str, MetricTrend]  # a key is absent when that metric is null on this day
    tsb_zone: str | None
    ramp_7d: float | None  # CTL now minus CTL seven days earlier
    ramp_caution: bool
    acwr: float | None  # ATL / CTL
    acwr_flag: Literal["low", "high"] | None


class TargetOut(BaseModel):
    day_type: str
    total_kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    fluid_baseline_ml: int
    written_to_garmin: bool


class FuelOut(BaseModel):
    """target null: "No targets yet, ask the coach"."""

    target: TargetOut | None
    targets_through: date | None


class SportCount(BaseModel):
    sport: str
    planned: int
    completed: int
    planned_tss: float
    actual_tss: float
    planned_hours: float
    actual_hours: float


class WeekOut(BaseModel):
    """null: "No plan; ask the coach to build one"."""

    phase: str
    target_hours: float | None
    target_tss: float | None
    actual_hours: float
    actual_tss: float
    sessions: list[SportCount]
    planned_to_date: int  # sessions dated on or before today
    completed_to_date: int


class LabsOut(BaseModel):
    """null with labs_enabled: "No panels stored"; labs_missing: "apply
    migrations/005_wellness.sql"."""

    panel_id: int
    drawn_on: date
    lab_name: str | None
    report_on: date | None
    outside_optimal: int | None
    markers: int | None
    priorities: str | None


class TodayView(BaseModel):
    header: HeaderOut
    session: SessionOut | None
    readiness: ReadinessOut | None
    fuel: FuelOut
    week: WeekOut | None
    labs: LabsOut | None
    labs_enabled: bool
    labs_missing: bool
    pending: ReviewPayload | None = Field(default=None)


def _workout(row: dict[str, Any]) -> WorkoutOut:
    return WorkoutOut(
        tp_workout_id=row["tp_workout_id"],
        sport=row["sport"],
        title=row.get("title"),
        completed=bool(row["completed"]),
        planned_duration_sec=row.get("planned_duration_sec"),
        planned_tss=_f(row.get("planned_tss")),
        actual_duration_sec=row.get("actual_duration_sec"),
        actual_tss=_f(row.get("actual_tss")),
        actual_if=_f(row.get("actual_if")),
        avg_hr=row.get("avg_hr"),
        avg_power=row.get("avg_power"),
        normalized_power=row.get("normalized_power"),
    )


# (key, daily_metrics column, higher is better)
TRENDS = (
    ("hrv", "hrv_overnight_avg", True),
    ("resting_hr", "resting_hr", False),
    ("sleep_score", "sleep_score", True),
    ("sleep_hours", "sleep_seconds", True),
    ("training_readiness", "training_readiness", True),
)


def _readiness(row: dict[str, Any], today: date, history: list[dict[str, Any]]) -> ReadinessOut:
    """history: daily_metrics rows in the BASELINE_DAYS ending on row's date, any order."""
    end: date = row["metric_date"]
    by_day = {h["metric_date"]: h for h in history}
    days = [end - timedelta(days=BASELINE_DAYS - 1 - i) for i in range(BASELINE_DAYS)]

    def series(column: str) -> list[float | None]:
        out: list[float | None] = []
        for d in days:
            v = _f(by_day[d].get(column)) if d in by_day else None
            out.append(round(v / 3600, 2) if v is not None and column == "sleep_seconds" else v)
        return out

    trends = {key: t for key, column, up in TRENDS if (t := trend(series(column), up)) is not None}
    secs = row.get("sleep_seconds")
    ctl, atl, tsb = _f(row.get("ctl")), _f(row.get("atl")), _f(row.get("tsb"))
    week_ago = by_day.get(end - timedelta(days=7))
    ramp_7d = ramp(ctl, _f(week_ago.get("ctl")) if week_ago else None)
    ratio = acwr(atl, ctl)
    return ReadinessOut(
        date=end,
        is_today=end == today,
        sleep_score=row.get("sleep_score"),
        sleep_hours=round(secs / 3600, 2) if secs is not None else None,
        hrv=row.get("hrv_overnight_avg"),
        resting_hr=row.get("resting_hr"),
        body_battery=row.get("body_battery_high"),
        training_readiness=row.get("training_readiness"),
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        trends=trends,
        tsb_zone=tsb_zone(tsb),
        ramp_7d=ramp_7d,
        ramp_caution=ramp_7d is not None and ramp_7d > RAMP_CAUTION,
        acwr=ratio,
        acwr_flag=acwr_flag(ratio),
    )


def _labs(s: LabSummary | None) -> LabsOut | None:
    if s is None:
        return None
    return LabsOut(
        panel_id=s.panel_id,
        drawn_on=s.drawn_on,
        lab_name=s.lab_name,
        report_on=s.report_on,
        outside_optimal=s.outside_optimal,
        markers=s.markers,
        priorities=s.priorities,
    )


async def build_today(rt: Runtime) -> TodayView:
    today = rt.today()
    monday = week_monday(today)
    snap = await rt.graph.aget_state(cfg(rt))
    values = snap.values or {}
    paused = paused_review(snap)
    held = values.get("pending")
    labs_enabled = rt.settings.tri_athlete_sex is not None
    with rt.connect() as conn:
        ctx = await load_context(conn, rt.store, today, held, labs_enabled=labs_enabled)
        todays = crepo.list_workouts_between(conn, today, today)
        week_rows = crepo.list_workouts_between(conn, monday, monday + timedelta(days=6))
        metric = conn.execute(
            "select * from daily_metrics where metric_date <= %s order by metric_date desc limit 1",
            (today,),
        ).fetchone()
        history = (
            conn.execute(
                "select * from daily_metrics where metric_date between %s and %s",
                (metric["metric_date"] - timedelta(days=BASELINE_DAYS - 1), metric["metric_date"]),
            ).fetchall()
            if metric is not None
            else []
        )
        targets = nrepo.list_targets(conn, today, today)
        fuel_plans = nrepo.list_fuel_plans(conn, today, today)
        syncs = [s for s in (crepo.get_sync_state(conn, src) for src in SOURCES) if s is not None]
        weeks = prepo.list_weeks(conn, ctx.plan.id) if ctx.plan is not None else []

    goal = None
    if ctx.goal is not None:
        g = ctx.goal.goal
        goal = GoalOut(
            goal_type=g.goal_type,
            event_name=g.event_name,
            event_date=g.event_date,
            days_to_go=(g.event_date - today).days if g.event_date else None,
        )
    number = of = None
    if ctx.this_week is not None:
        assert ctx.plan is not None  # this_week is only set alongside a plan
        number = (monday - ctx.plan.start_date).days // 7 + 1
        of = len(weeks)
    header = HeaderOut(
        today=today,
        phase=ctx.phase,
        goal=goal,
        week=WeekHeader(start=monday, number=number, of=of),
        last_sync=[
            SyncOut(
                source=s.source,
                last_synced_date=s.last_synced_date,
                last_run_at=s.last_run_at,
                status=s.last_status,
                error=s.last_error,
            )
            for s in syncs
        ],
    )

    session = None
    if todays:
        first = next((w for w in todays if not w["completed"]), todays[0])
        plan = next((p for p in fuel_plans if p.tp_workout_id == first["tp_workout_id"]), None)
        session = SessionOut(
            workouts=[_workout(w) for w in todays],
            fuel=FuelPlanOut(**plan.model_dump()) if plan is not None else None,
        )

    readiness = _readiness(metric, today, history) if metric is not None else None

    target = None
    if targets:
        t = targets[0]
        target = TargetOut(
            day_type=t.target.day_type,
            total_kcal=t.target.total_kcal,
            carbs_g=t.target.carbs_g,
            protein_g=t.target.protein_g,
            fat_g=t.target.fat_g,
            fluid_baseline_ml=t.target.fluid_baseline_ml,
            written_to_garmin=t.written_to_garmin,
        )
    fuel = FuelOut(target=target, targets_through=ctx.targets_through)

    week = None
    if ctx.this_week is not None:
        per: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for w in week_rows:
            a = per[w["sport"]]
            a["planned"] += 1
            a["completed"] += int(bool(w["completed"]))
            a["planned_tss"] += float(w["planned_tss"] or 0)
            a["actual_tss"] += float(w["actual_tss"] or 0)
            a["planned_hours"] += (w["planned_duration_sec"] or 0) / 3600
            a["actual_hours"] += (w["actual_duration_sec"] or 0) / 3600
        to_date = [w for w in week_rows if w["workout_date"] <= today]
        week = WeekOut(
            phase=ctx.this_week.phase,
            target_hours=ctx.this_week.target_hours,
            target_tss=ctx.this_week.target_tss,
            actual_hours=round(ctx.actual_hours, 2),
            actual_tss=round(ctx.actual_tss, 1),
            sessions=[
                SportCount(
                    sport=s,
                    planned=int(a["planned"]),
                    completed=int(a["completed"]),
                    planned_tss=round(a["planned_tss"], 1),
                    actual_tss=round(a["actual_tss"], 1),
                    planned_hours=round(a["planned_hours"], 2),
                    actual_hours=round(a["actual_hours"], 2),
                )
                for s, a in sorted(per.items())
            ],
            planned_to_date=len(to_date),
            completed_to_date=sum(1 for w in to_date if w["completed"]),
        )

    pending = review_payload(paused) if paused is not None else review_payload(held)
    return TodayView(
        header=header,
        session=session,
        readiness=readiness,
        fuel=fuel,
        week=week,
        labs=_labs(ctx.labs),
        labs_enabled=ctx.labs_enabled,
        labs_missing=ctx.labs_missing,
        pending=pending,
    )
