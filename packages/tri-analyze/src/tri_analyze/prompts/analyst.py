"""The analyst's system prompt, rendered from the athlete context and the names of the bound
tools. A pure function of its arguments: equal inputs give equal bytes, which is what Anthropic's
prompt cache matches on."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from tri_analyze.repo import AthleteContext

# Bump whenever the prompt text changes; names the eval experiment analyst-v<N>.
PROMPT_VERSION = "2"

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
seconds, paces derive from those. Today is the reference for "this week" and "yesterday"; in
SQL write it as a literal (date 'YYYY-MM-DD'), never use current_date. When you derive a
number, show the arithmetic in a few words."""


def _pace(sec: Any, unit: str) -> str:
    if sec is None:
        return "n/a"
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}{unit}"


def _num(v: Any, nd: int = 1) -> str:
    if v is None:
        return "-"
    return f"{float(v):.{nd}f}" if nd else str(int(round(float(v))))


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def dated(d: date) -> str:
    """`2026-09-12 (Sat)`. Weekday names are fixed English, not the locale's."""
    return f"{d.isoformat()} ({WEEKDAYS[d.weekday()][:3]})"


def calendar_line(today: date) -> str:
    """The Mondays of the six weeks from four weeks back to next week. The analyst's today line
    and the judge's calendar line both end with it, so both name weeks the same way."""
    monday = today - timedelta(days=today.weekday())
    mondays = [monday + timedelta(weeks=n) for n in range(-4, 2)]
    return "Weeks start Monday: " + ", ".join(m.isoformat() for m in mondays) + "."


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


# TrainingPeaks zone groups are keyed by workoutTypeId: 1 swim, 2 bike, 3 run (0 = default).
_DEFAULT, _SWIM, _BIKE, _RUN = 0, 1, 2, 3
_ZONE_LABEL = re.compile(r"Zone\s+(\w+)(?:\s*:\s*(.*))?")
NO_ZONES = "Zones: not synced; prescribe only as a stated % of a threshold."

Zone = tuple[str, float, float]  # name, minimum, maximum


def _zone_name(label: Any, n: int) -> str:
    """`Zone 2: Aerobic` -> `Z2 Aerobic`, `Zone 5A` -> `Z5A`; anything else is `Z<position>`."""
    m = _ZONE_LABEL.fullmatch(str(label or "").strip())
    if not m:
        return f"Z{n}"
    return f"Z{m.group(1)} {m.group(2).strip()}" if m.group(2) else f"Z{m.group(1)}"


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _zones(group: Any) -> list[Zone] | None:
    """A group's zones sorted slow to fast, or None when the group or any zone is garbled."""
    zs = group.get("zones") if isinstance(group, dict) else None
    if not isinstance(zs, list) or not zs:
        return None
    out: list[Zone] = []
    for n, z in enumerate(zs, 1):
        if not isinstance(z, dict) or not (_is_num(z.get("minimum")) and _is_num(z.get("maximum"))):
            return None
        out.append((_zone_name(z.get("label"), n), float(z["minimum"]), float(z["maximum"])))
    return sorted(out, key=lambda z: z[1])


def _pick(groups: Any, *types: int) -> list[Zone] | None:
    """The first well-formed group for each workoutTypeId in turn."""
    if not isinstance(groups, list):
        return None
    for t in types:
        for g in groups:
            if isinstance(g, dict) and g.get("workoutTypeId") == t:
                zones = _zones(g)
                if zones:
                    return zones
    return None


def _numeric_zones(zones: list[Zone], unit: str) -> str:
    last = len(zones) - 1
    return ", ".join(
        f"{name} {round(lo)}+ {unit}" if i == last else f"{name} {round(lo)}-{round(hi)} {unit}"
        for i, (name, lo, hi) in enumerate(zones)
    )


def _pace_zones(zones: list[Zone] | None, metres: int, unit: str) -> str | None:
    """Speed zones (m/s) as min:ss per `metres`, slowest first; None if a bound is unusable."""
    if not zones or any(hi <= 0 for _, _, hi in zones):
        return None
    last = len(zones) - 1
    parts: list[str] = []
    for i, (name, lo, hi) in enumerate(zones):
        if lo <= 0:
            parts.append(f"{name} slower than {_pace(round(metres / hi), unit)}")
        elif i == last:
            parts.append(f"{name} faster than {_pace(round(metres / lo), unit)}")
        else:
            slow, fast = round(metres / lo), round(metres / hi)
            parts.append(f"{name} {_pace(slow, '')}-{_pace(fast, unit)}")
    return ", ".join(parts)


def _zones_block(p: dict[str, Any] | None) -> str:
    """Bike power, run HR, bike HR (when it differs), run and swim pace, from the synced
    TrainingPeaks groups. Garbled groups are skipped; with none left, the not-synced line."""
    p = p or {}
    lines: list[str] = []
    power = _pick(p.get("power_zones"), _BIKE, _DEFAULT)
    if power:
        lines.append(f"- Bike power: {_numeric_zones(power, 'W')}")
    run_hr = _pick(p.get("hr_zones"), _RUN, _DEFAULT)
    if run_hr:
        lines.append(f"- Run HR: {_numeric_zones(run_hr, 'bpm')}")
    bike_hr = _pick(p.get("hr_zones"), _BIKE)
    if bike_hr and bike_hr != run_hr:
        lines.append(f"- Bike HR: {_numeric_zones(bike_hr, 'bpm')}")
    run_pace = _pace_zones(_pick(p.get("pace_zones"), _RUN), 1000, "/km")
    if run_pace:
        lines.append(f"- Run pace: {run_pace}")
    swim_pace = _pace_zones(_pick(p.get("pace_zones"), _SWIM), 100, "/100m")
    if swim_pace:
        lines.append(f"- Swim pace: {swim_pace}")
    if not lines:
        return NO_ZONES
    return "Athlete zones (from TrainingPeaks):\n" + "\n".join(lines)


def _days_block(days: list[dict[str, Any]]) -> str:
    if not days:
        return "Recent load: not available."
    lines = ["Recent load and recovery (last 7 days):"]
    for d in days:
        lines.append(
            f"- {dated(d['metric_date'])}: TSS {_num(d.get('tss_day'), 0)}, "
            f"CTL {_num(d.get('ctl'))}, ATL {_num(d.get('atl'))}, TSB {_num(d.get('tsb'))}, "
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
            f"- {dated(w['workout_date'])} {w['sport']}: {w.get('title') or '(untitled)'} "
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
            f"Today is {dated(ctx.today)}. {calendar_line(ctx.today)}",
            _profile_block(ctx.profile),
            _zones_block(ctx.profile),
            _days_block(ctx.recent_days),
            _workouts_block(ctx.recent_workouts, ctx.today),
            _tools_block(tool_names),
            FEEDBACK_RULES,
        ]
    )
