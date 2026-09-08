"""Athlete context loading and system prompt rendering.

The system prompt is where domain judgment lives. It is rendered once
per session from data so it stays byte-stable across turns (prompt caching), and it tells
the model *how* to give feedback, not just what the tables are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn


@dataclass
class AthleteContext:
    today: date
    profile: dict[str, Any] | None
    recent_days: list[dict[str, Any]] = field(default_factory=list)
    recent_workouts: list[dict[str, Any]] = field(default_factory=list)


def load_athlete_context(conn: Conn, today: date) -> AthleteContext:
    profile = conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, weight_kg from athlete_profile where id = 1"
    ).fetchone()
    days = conn.execute(
        "select metric_date, tss_day, ctl, atl, tsb, sleep_score, hrv_overnight_avg, "
        "resting_hr, training_readiness from daily_metrics "
        "where metric_date between %s and %s order by metric_date",
        (today - timedelta(days=7), today),
    ).fetchall()
    workouts = conn.execute(
        "select workout_date, sport, title, completed, planned_tss, actual_tss, "
        "planned_duration_sec, actual_duration_sec from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (today - timedelta(days=7), today + timedelta(days=7)),
    ).fetchall()
    return AthleteContext(today=today, profile=profile, recent_days=days, recent_workouts=workouts)


def _pace(sec: Any, unit: str) -> str:
    if sec is None:
        return "n/a"
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}{unit}"


def _num(v: Any, nd: int = 1) -> str:
    if v is None:
        return "-"
    return f"{float(v):.{nd}f}" if nd else str(int(round(float(v))))


def _profile_block(p: dict[str, Any] | None) -> str:
    if not p:
        return "Athlete thresholds: not available (run `tri-analyze sync`)."
    return (
        "Athlete thresholds (from TrainingPeaks):\n"
        f"- FTP {p.get('ftp_watts') or 'n/a'} W\n"
        f"- Run threshold pace {_pace(p.get('run_threshold_pace_sec_per_km'), '/km')}\n"
        f"- Swim CSS {_pace(p.get('swim_css_sec_per_100m'), '/100m')}\n"
        f"- LTHR {p.get('lthr_bpm') or 'n/a'} bpm, max HR {p.get('max_hr_bpm') or 'n/a'} bpm\n"
        "Zone tables are in athlete_profile.hr_zones / power_zones / pace_zones (jsonb)."
    )


def _days_block(days: list[dict[str, Any]]) -> str:
    if not days:
        return "Recent load: not available."
    lines = ["Recent load and recovery (last 7 days):"]
    for d in days:
        lines.append(
            f"- {d['metric_date']}: TSS {_num(d.get('tss_day'), 0)}, CTL {_num(d.get('ctl'))}, "
            f"ATL {_num(d.get('atl'))}, TSB {_num(d.get('tsb'))}, "
            f"sleep {_num(d.get('sleep_score'), 0)}, HRV {_num(d.get('hrv_overnight_avg'), 0)}, "
            f"readiness {_num(d.get('training_readiness'), 0)}"
        )
    return "\n".join(lines)


def _workouts_block(ws: list[dict[str, Any]], today: date) -> str:
    if not ws:
        return "Recent and upcoming workouts: not available."
    lines = ["Workouts, last 7 days and next 7 days (planned TSS -> actual TSS):"]
    for w in ws:
        if w.get("completed"):
            marker = "done"
        elif w["workout_date"] >= today:
            marker = "planned"
        else:
            marker = "missed"
        lines.append(
            f"- {w['workout_date']} {w['sport']}: {w.get('title') or '(untitled)'} "
            f"[{marker}] {_num(w.get('planned_tss'), 0)} -> {_num(w.get('actual_tss'), 0)}"
        )
    return "\n".join(lines)


def _tools_block(live_tools: list[str]) -> str:
    if not live_tools:
        return "No live tools are bound this session; work from the database only."
    return (
        "Live tools bound this session: " + ", ".join(live_tools) + ".\n"
        "Use get_activity_splits(activity_id) with workouts.garmin_activity_id for lap/interval "
        "detail; get_activity for a Garmin summary; get_training_readiness(date) and "
        "get_hrv_data(date) for today's recovery; tp_get_workout(workout_id) for the coach's "
        "structured plan and comments. Prefer query_training_db for anything already synced."
    )


FEEDBACK_RULES = """\
How to give feedback on a completed session:
1. Planned vs actual: duration, distance, TSS, intensity factor; was the structure executed?
2. Execution quality: time in zones versus the session's intent, HR drift or decoupling on
   steady work, pacing consistency across intervals (pull laps when it matters).
3. Context: where the session sits in the week and against the current CTL/ATL/TSB; sleep,
   HRV and readiness going in.
4. The athlete's own comments, feeling and RPE when present.
5. One or two concrete takeaways for the next similar session. No generic encouragement.

For trend questions: compute with SQL (group by week, averages, sums), state the date window
you used, and say when data is missing rather than guessing. Distances are metres, durations
seconds, paces derive from those. Today is the reference for "this week" and "yesterday"."""


def render_system_prompt(ctx: AthleteContext, live_tools: list[str]) -> str:
    return "\n\n".join(
        [
            "You are a triathlon coach's analyst. You answer questions about one athlete's "
            "training using the query_training_db tool (Postgres, read-only) and the live tools "
            "listed below. Be specific and quantitative. Use the athlete's thresholds to "
            "interpret intensity.",
            f"Today is {ctx.today.isoformat()}.",
            _profile_block(ctx.profile),
            _days_block(ctx.recent_days),
            _workouts_block(ctx.recent_workouts, ctx.today),
            _tools_block(live_tools),
            FEEDBACK_RULES,
        ]
    )
