"""Adjust prompt: stable rules first (cacheable), then this turn's data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_planning import repo
from tri_planning.planning.models import PlanWeekRow, TrainingGoal
from tri_planning.planning.targets import week_monday

MIN_DESIGNED_WEEKS = 2

ADJUST_RULES = """\
You are a self-coached triathlete's planning assistant. The plan is active and its sessions are on
the TrainingPeaks calendar. Your job each turn: review how training is going against the plan and,
only when warranted, propose calendar changes. The athlete approves every change before it is
written, so propose what you would actually do and give a one-line reason per change.

Review checklist:
1. Last 7 days: planned versus actual per session (TSS, duration); missed sessions and why.
2. Sessions marked FLAG below (RPE >= 8 or feeling <= 3): ask whether they cost more than planned.
3. Recovery: 3-day readiness and HRV against the 30-day baseline; use get_training_readiness and
   get_hrv_data for today's numbers when they matter.
4. TSB entering this week; a deeply negative TSB before a hard week is a reason to lighten it.
5. This week's and next week's sessions against their targets; anything now unrealistic.

Lever order when something must give: swap days, shorten, downgrade intensity, drop,
re-plan the week. Use the smallest lever that solves the problem.

Rules:
- You may update, move or delete only agent-authored workouts (listed below with their ids). If
  the athlete explicitly asks you to change a workout that is not in that list, set
  athlete_requested true on that change and say so in the reason.
- tp_get_workouts shows the live calendar (planned and completed) with workout ids.
- query_training_db answers anything about history; do arithmetic in SQL.
- When "Window extension needed" is yes, call design_next_week once; its sessions are added to
  the proposal automatically. Do not repeat them in propose_calendar_changes.
- Finish with exactly one call to propose_calendar_changes, or with a short message saying no
  changes are needed and why. Be concise: findings first, then the proposal."""


@dataclass
class AdjustContext:
    today: date
    goal: TrainingGoal
    this_week: PlanWeekRow | None
    next_week: PlanWeekRow | None
    actual_tss_this_week: float
    sessions: list[dict[str, Any]]
    baseline: dict[str, float | None]
    owned: list[dict[str, Any]]
    weeks_on_calendar: int
    horizon: int
    extension_needed: bool
    checkin: bool = False
    constraints: list[str] = field(default_factory=list)


def load_adjust_context(conn: Conn, today: date, plan_id: int, horizon: int) -> AdjustContext:
    plan = repo.get_plan(conn, plan_id)
    assert plan is not None
    stored = repo.get_goal(conn, plan.goal_id)
    assert stored is not None
    monday = week_monday(today)
    weeks = repo.list_weeks(conn, plan_id)
    this_week = next((w for w in weeks if w.week_start == monday), None)
    next_week = next((w for w in weeks if w.week_start == monday + timedelta(weeks=1)), None)
    actual = conn.execute(
        "select coalesce(sum(tss_day), 0) as t from daily_metrics "
        "where metric_date between %s and %s",
        (monday, today),
    ).fetchone()
    weeks_on_calendar = sum(1 for w in weeks if w.written_to_tp and w.week_start >= monday)
    return AdjustContext(
        today=today,
        goal=stored.goal,
        this_week=this_week,
        next_week=next_week,
        actual_tss_this_week=float(actual["t"]) if actual else 0.0,
        sessions=repo.recent_sessions(conn, today - timedelta(days=7), today),
        baseline=repo.recovery_baseline(conn, today),
        owned=repo.owned_workouts(conn, plan_id),
        weeks_on_calendar=weeks_on_calendar,
        horizon=horizon,
        extension_needed=weeks_on_calendar < MIN_DESIGNED_WEEKS,
        constraints=stored.goal.constraints,
    )


def _n(v: Any, nd: int = 0) -> str:
    return "-" if v is None else f"{float(v):.{nd}f}"


def _week_line(label: str, w: PlanWeekRow | None) -> str:
    if w is None:
        return f"{label}: not in plan"
    sessions = len(w.designed.sessions) if w.designed else 0
    return (
        f"{label}: {w.week_start} {w.phase}, target {_n(w.target_tss)} TSS / "
        f"{_n(w.target_hours, 1)} h, {sessions} designed sessions, "
        f"{'on calendar' if w.written_to_tp else 'not on calendar'}"
    )


def render_adjust_prompt(ctx: AdjustContext) -> str:
    lines = [ADJUST_RULES, "", f"Today is {ctx.today.isoformat()}."]
    g = ctx.goal
    lines.append(
        f"Goal: {g.goal_type}"
        + (f", {g.event_name} on {g.event_date}" if g.event_date else "")
        + f"; {g.weekly_hours_min:g}-{g.weekly_hours_max:g} h/week."
        + (" Constraints: " + "; ".join(ctx.constraints) if ctx.constraints else "")
    )
    lines.append(
        _week_line("This week", ctx.this_week)
        + f"; actual so far {ctx.actual_tss_this_week:.0f} TSS"
    )
    lines.append(_week_line("Next week", ctx.next_week))
    b = ctx.baseline
    lines.append(
        f"Recovery: readiness 3d {_n(b.get('readiness_3d'))} vs 30d {_n(b.get('readiness_30d'))}; "
        f"HRV 3d {_n(b.get('hrv_3d'))} vs 30d {_n(b.get('hrv_30d'))}; TSB {_n(b.get('tsb'), 1)}"
    )
    lines.append("Last 7 days (planned -> actual TSS):")
    for s in ctx.sessions:
        flagged: list[str] = []
        if (s.get("rpe") or 0) >= 8:
            flagged.append(f"rpe {s['rpe']}")
        if s.get("feeling") is not None and s["feeling"] <= 3:
            flagged.append(f"feeling {s['feeling']}")
        flag = f" FLAG {', '.join(flagged)}" if flagged else ""
        status = (
            "done"
            if s.get("completed")
            else ("missed" if s["workout_date"] < ctx.today else "planned")
        )
        lines.append(
            f"  {s['workout_date']} {s['sport']} {s.get('title') or ''} [{status}] "
            f"{_n(s.get('planned_tss'))} -> {_n(s.get('actual_tss'))}{flag}"
        )
    lines.append("Agent-authored workouts on the calendar (id date sport title):")
    lines += [
        f"  {o['tp_workout_id']} {o['workout_date']} {o.get('sport') or ''} {o.get('title') or ''}"
        for o in ctx.owned
    ] or ["  none"]
    lines.append(
        f"Weeks already on the calendar from this week: {ctx.weeks_on_calendar} "
        f"(horizon {ctx.horizon}). "
        f"Window extension needed: {'yes' if ctx.extension_needed else 'no'}."
    )
    if ctx.checkin:
        lines.append("This is a scheduled check-in with no athlete message; do the full checklist.")
    return "\n".join(lines)
