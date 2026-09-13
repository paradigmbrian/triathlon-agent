"""The analyst's system prompt, rendered from the athlete context and the names of the bound
tools. A pure function of its arguments: equal inputs give equal bytes, which is what Anthropic's
prompt cache matches on."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_analyze.repo import AthleteContext

# Bump whenever the prompt text changes; names the eval experiment analyst-v<N>.
PROMPT_VERSION = "1"

TOOL_GUIDE: dict[str, str] = {
    "query_training_db": (
        "anything already synced: workouts, planned vs actual, weekly volume, CTL/ATL/TSB, "
        "sleep, HRV, readiness, thresholds and zones. Prefer it over live tools for synced data."
    ),
    "get_activity_splits": (
        "lap and interval detail for one activity; activity_id is workouts.garmin_activity_id."
    ),
    "get_activity": "a Garmin activity summary; activity_id is workouts.garmin_activity_id.",
    "get_training_readiness": "Garmin readiness for a date not yet synced, such as today.",
    "get_hrv_data": "overnight HRV for a date not yet synced, such as today.",
    "tp_get_workout": "the coach's structured plan and comments for one session.",
    "read_body_composition": (
        "index-scale weight, body fat and muscle mass over the last `days` days."
    ),
    "read_intake_vs_targets": (
        "logged intake against the nutrition targets over the last `days` days."
    ),
}

NO_LIVE_TOOLS = "No live tools are bound this session; work from the database only."

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
        return "Athlete thresholds: not available (run `tri sync`)."
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


def _tools_block(tool_names: list[str]) -> str:
    lines = ["Tools bound this session: " + (", ".join(tool_names) or "none") + "."]
    guided = [name for name in tool_names if name in TOOL_GUIDE]
    if guided:
        lines.append("What each is for:")
        lines += [f"- {name}: {TOOL_GUIDE[name]}" for name in guided]
    if all(name == "query_training_db" for name in tool_names):
        lines.append(NO_LIVE_TOOLS)
    return "\n".join(lines)


def render_system_prompt(ctx: AthleteContext, tool_names: list[str]) -> str:
    """Role, today, thresholds, recent load, workouts, tools, rules. `tool_names` is the bound
    list in bound order; every name is listed, and the guide line is added for names it knows."""
    return "\n\n".join(
        [
            "You are a triathlon coach's analyst. You answer questions about one athlete's "
            "training using the query_training_db tool (Postgres, read-only) and the other "
            "tools listed below. Be specific and quantitative. Use the athlete's thresholds to "
            "interpret intensity.",
            f"Today is {ctx.today.isoformat()}.",
            _profile_block(ctx.profile),
            _days_block(ctx.recent_days),
            _workouts_block(ctx.recent_workouts, ctx.today),
            _tools_block(tool_names),
            FEEDBACK_RULES,
        ]
    )
