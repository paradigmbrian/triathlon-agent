"""The per-turn context block: what the coach knows before it asks anything. Loaded from the
tables and both Store namespaces; rendered byte-stable for a fixed input."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from langgraph.store.base import BaseStore

from tri_analyze.repo import load_athlete_context
from tri_coach.models import ChangeSet
from tri_core.db.repo import Conn
from tri_nutrition import repo as nrepo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile
from tri_planning import repo
from tri_planning.planning.models import GraphPhase, PlanWeekRow, StoredGoal, StoredPlan
from tri_planning.planning.targets import week_monday
from tri_wellness import repo as wrepo
from tri_wellness.report import extract_section

PRIORITIES_CHARS = 300


@dataclass
class LabSummary:
    panel_id: int
    drawn_on: date
    lab_name: str | None
    report_on: date | None  # the latest report's creation date; None when no report yet
    outside_optimal: int | None  # findings whose functional_status is not "optimal"
    markers: int | None
    priorities: str | None  # the report's Priorities section, whitespace collapsed, clipped


def _lab_tables_present(conn: Conn) -> bool:
    row = conn.execute("select to_regclass('lab_panels') as t").fetchone()
    return row is not None and row["t"] is not None


def load_lab_summary(conn: Conn) -> LabSummary | None:
    """The latest stored panel and its latest report, or None when no panel is stored. Callers
    check _lab_tables_present first; the coach must not fail a turn because wellness is not
    set up."""
    pid = wrepo.latest_panel_id(conn)
    if pid is None:
        return None
    panel = wrepo.get_panel(conn, pid)
    if panel is None:
        return None
    report = wrepo.latest_report_for_panel(conn, pid)
    if report is None:
        return LabSummary(pid, panel.drawn_on, panel.lab_name, None, None, None, None)
    priorities = extract_section(report.report_md, "Priorities")
    if priorities:
        priorities = " ".join(priorities.split())
        if len(priorities) > PRIORITIES_CHARS:
            priorities = priorities[: PRIORITIES_CHARS - 1].rstrip() + "…"
    return LabSummary(
        panel_id=pid,
        drawn_on=panel.drawn_on,
        lab_name=panel.lab_name,
        report_on=report.created_at.date(),
        outside_optimal=sum(1 for f in report.findings if f.functional_status != "optimal"),
        markers=len(report.findings),
        priorities=priorities or None,
    )


@dataclass
class CoachContext:
    today: date
    thresholds: dict[str, Any] | None
    phase: GraphPhase
    goal: StoredGoal | None
    plan: StoredPlan | None
    this_week: PlanWeekRow | None
    actual_tss: float
    actual_hours: float
    designed_remaining: int
    profile: NutritionProfile | None
    targets_through: date | None
    recent_days: list[dict[str, Any]] = field(default_factory=list)
    pending: ChangeSet | None = None
    labs_enabled: bool = False  # TRI_ATHLETE_SEX set: the wellness consult is bound
    labs: LabSummary | None = None
    labs_missing: bool = False  # labs_enabled but lab_panels is not there: migrations not applied


async def load_context(
    conn: Conn,
    store: BaseStore,
    today: date,
    pending: ChangeSet | None,
    *,
    labs_enabled: bool = False,
) -> CoachContext:
    phase, goal_id, plan_id = repo.derive_phase(conn)
    goal = repo.get_goal(conn, goal_id) if goal_id is not None else None
    plan = repo.get_plan(conn, plan_id) if plan_id is not None else None
    monday = week_monday(today)
    this_week: PlanWeekRow | None = None
    designed_remaining = 0
    if plan is not None:
        weeks = repo.list_weeks(conn, plan.id)
        this_week = next((w for w in weeks if w.week_start == monday), None)
        designed_remaining = sum(1 for w in weeks if w.designed and w.week_start >= monday)
    row = conn.execute(
        "select coalesce(sum(tss_day), 0) as tss from daily_metrics "
        "where metric_date between %s and %s",
        (monday, today),
    ).fetchone()
    hours_row = conn.execute(
        "select coalesce(sum(actual_duration_sec), 0) as sec from workouts "
        "where completed and workout_date between %s and %s",
        (monday, today),
    ).fetchone()
    profile = await S.get_profile(store)
    stored = nrepo.list_targets(conn, today, today + timedelta(days=365))
    labs_missing = labs_enabled and not _lab_tables_present(conn)
    labs = load_lab_summary(conn) if labs_enabled and not labs_missing else None
    return CoachContext(
        today=today,
        thresholds=repo.athlete_thresholds(conn),
        phase=phase,
        goal=goal,
        plan=plan,
        this_week=this_week,
        actual_tss=float(row["tss"]) if row else 0.0,
        actual_hours=(float(hours_row["sec"]) / 3600) if hours_row else 0.0,
        designed_remaining=designed_remaining,
        profile=profile,
        targets_through=stored[-1].target.day if stored else None,
        recent_days=load_athlete_context(conn, today).recent_days,
        pending=pending,
        labs_enabled=labs_enabled,
        labs=labs,
        labs_missing=labs_missing,
    )


def _pace(sec: Any, unit: str) -> str:
    if sec is None:
        return "n/a"
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}{unit}"


def _n(v: Any, nd: int = 0) -> str:
    return "-" if v is None else f"{float(v):.{nd}f}"


def _plan_lines(ctx: CoachContext) -> list[str]:
    if ctx.goal is None:
        return [f"Training plan: none (phase {ctx.phase})."]
    g = ctx.goal.goal
    head = f"Training plan: {g.goal_type}"
    if g.event_name or g.event_date:
        head += f", {g.event_name or 'event'} on {g.event_date}"
    head += f"; phase {ctx.phase}"
    if ctx.plan is not None:
        head += f"; plan {ctx.plan.start_date} to {ctx.plan.end_date} ({ctx.plan.source})"
    lines = [head + "."]
    if ctx.this_week is not None:
        w = ctx.this_week
        lines.append(
            f"This week ({w.phase}): target {_n(w.target_tss)} TSS / {_n(w.target_hours, 1)} h; "
            f"actual so far {_n(ctx.actual_tss)} TSS / {ctx.actual_hours:.1f} h; "
            f"designed weeks remaining: {ctx.designed_remaining}."
        )
    elif ctx.plan is not None:
        lines.append(
            f"This week is not in the plan; designed weeks remaining: {ctx.designed_remaining}."
        )
    return lines


def _nutrition_line(ctx: CoachContext) -> str:
    if ctx.profile is None:
        return "Nutrition: no profile (intake not done)."
    p = ctx.profile
    fat = f", body fat {p.body_fat_pct:g} %" if p.body_fat_pct is not None else ""
    through = ctx.targets_through.isoformat() if ctx.targets_through else "none"
    return f"Nutrition: goal {p.goal}, {p.weight_kg:g} kg{fat}; targets through {through}."


def _labs_line(ctx: CoachContext) -> str:
    if not ctx.labs_enabled:
        return "Labs: not configured (set TRI_ATHLETE_SEX to enable the wellness consult)."
    if ctx.labs_missing:
        return "Labs: lab tables missing (apply migrations/005_wellness.sql)."
    s = ctx.labs
    if s is None:
        return "Labs: no panels stored (tri-wellness ingest)."
    lab = f" ({s.lab_name})" if s.lab_name else ""
    if s.report_on is None:
        return (
            f"Labs: latest panel {s.drawn_on.isoformat()}{lab} has no report yet "
            "(run tri-wellness report)."
        )
    line = (
        f"Labs: panel {s.drawn_on.isoformat()}{lab}, report {s.report_on.isoformat()}: "
        f"{s.outside_optimal} of {s.markers} markers outside optimal."
    )
    if s.priorities:
        line += f" Priorities: {s.priorities}"
    return line


def _days_lines(days: list[dict[str, Any]]) -> list[str]:
    if not days:
        return ["Recent load: not available."]
    lines = ["Last 7 days (TSS, CTL/ATL/TSB, sleep, HRV, readiness):"]
    for d in days:
        lines.append(
            f"- {d['metric_date']}: {_n(d.get('tss_day'))}, {_n(d.get('ctl'), 1)}/"
            f"{_n(d.get('atl'), 1)}/{_n(d.get('tsb'), 1)}, {_n(d.get('sleep_score'))}, "
            f"{_n(d.get('hrv_overnight_avg'))}, {_n(d.get('training_readiness'))}"
        )
    return lines


def _pending_line(pending: ChangeSet | None) -> str | None:
    if pending is None:
        return None
    n_plan = sum(len(p.changes) for p in pending.proposals if p.domain == "planning")
    n_nut = sum(len(p.changes) for p in pending.proposals if p.domain == "nutrition")
    ids = ", ".join(p.id for p in pending.proposals)
    return (
        f"Pending change set from an earlier turn ({n_plan} planning, {n_nut} nutrition): "
        f"{pending.narration} Re-propose it with propose_changes using the ids {ids} when the "
        "athlete wants it applied."
    )


def render_context(ctx: CoachContext) -> str:
    lines = [f"Today is {ctx.today.isoformat()}."]
    t = ctx.thresholds
    if t:
        lines.append(
            f"Thresholds: FTP {t.get('ftp_watts') or 'n/a'} W, run threshold "
            f"{_pace(t.get('run_threshold_pace_sec_per_km'), '/km')}, swim CSS "
            f"{_pace(t.get('swim_css_sec_per_100m'), '/100m')}, "
            f"LTHR {t.get('lthr_bpm') or 'n/a'} bpm, max HR {t.get('max_hr_bpm') or 'n/a'} bpm."
        )
    else:
        lines.append("Thresholds: not available (run `tri sync`).")
    lines += _plan_lines(ctx)
    lines.append(_nutrition_line(ctx))
    lines.append(_labs_line(ctx))
    lines += _days_lines(ctx.recent_days)
    pending = _pending_line(ctx.pending)
    if pending:
        lines.append(pending)
    return "\n".join(lines)
