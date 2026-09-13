"""The analyst's eval cases: a question, an athlete context for a fixed today (Wednesday
2026-09-16, the date the tri-coach eval uses), which tools to bind, canned tool results, and the
flags the code checks read. Inputs are JSON-safe so they can live in a LangSmith dataset."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from tri_analyze.repo import AthleteContext

TODAY = date(2026, 9, 16)
Kind = Literal["session", "trend", "readiness"]
KINDS: tuple[Kind, ...] = ("session", "trend", "readiness")
EXTRA_TOOLS = ("read_body_composition", "read_intake_vs_targets")

PROFILE: dict[str, Any] = {
    "ftp_watts": 250,
    "run_threshold_pace_sec_per_km": 255,
    "swim_css_sec_per_100m": 100,
    "lthr_bpm": 172,
    "max_hr_bpm": 188,
    "weight_kg": 74.0,
}


def jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def rows(*items: dict[str, Any]) -> str:
    """A tool result: JSON text, as query_training_db and the MCP tools return."""
    return json.dumps(list(items), default=str)


def _day(
    d: date, tss: int, ctl: float, atl: float, sleep: int, hrv: int, ready: int
) -> dict[str, Any]:
    return {
        "metric_date": d,
        "tss_day": tss,
        "ctl": ctl,
        "atl": atl,
        "tsb": round(ctl - atl, 1),
        "sleep_score": sleep,
        "hrv_overnight_avg": hrv,
        "resting_hr": 46,
        "training_readiness": ready,
    }


def _workout(
    d: date, sport: str, title: str, planned: int, actual: int | None, *, completed: bool = True
) -> dict[str, Any]:
    return {
        "workout_date": d,
        "sport": sport,
        "title": title,
        "completed": completed,
        "planned_tss": planned,
        "actual_tss": actual,
        "planned_duration_sec": None,
        "actual_duration_sec": None,
    }


WEEK_DAYS = [
    _day(date(2026, 9, 9), 92, 47.0, 52.0, 74, 62, 55),
    _day(date(2026, 9, 10), 0, 46.7, 49.4, 81, 66, 68),
    _day(date(2026, 9, 11), 45, 46.6, 48.8, 78, 64, 66),
    _day(date(2026, 9, 12), 0, 46.3, 46.0, 83, 68, 74),
    _day(date(2026, 9, 13), 128, 47.7, 55.4, 72, 60, 58),
    _day(date(2026, 9, 14), 58, 47.9, 55.7, 77, 63, 61),
    _day(date(2026, 9, 15), 74, 48.3, 57.7, 70, 58, 49),
]

WEEK_WORKOUTS = [
    _workout(date(2026, 9, 9), "bike", "Threshold 3x10", 85, 92),
    _workout(date(2026, 9, 11), "run", "Easy 45 min", 45, 45),
    _workout(date(2026, 9, 12), "swim", "CSS 10x100", 40, None, completed=False),
    _workout(date(2026, 9, 13), "brick", "Brick: 2h ride + 20 min run", 130, 128),
    _workout(date(2026, 9, 14), "bike", "Z2 ride", 60, 58),
    _workout(date(2026, 9, 15), "run", "Intervals 6x800", 70, 74),
    _workout(date(2026, 9, 17), "run", "Tempo 40 min", 55, None, completed=False),
    _workout(date(2026, 9, 19), "bike", "Long ride", 150, None, completed=False),
]


def athlete(**over: Any) -> AthleteContext:
    base: dict[str, Any] = {
        "today": TODAY,
        "profile": dict(PROFILE),
        "recent_days": [dict(d) for d in WEEK_DAYS],
        "recent_workouts": [dict(w) for w in WEEK_WORKOUTS],
    }
    base.update(over)
    return AthleteContext(**base)


@dataclass(frozen=True)
class EvalCase:
    name: str
    question: str
    athlete: AthleteContext
    kind: Kind
    live: bool = True
    extra_tools: list[str] = field(default_factory=list)
    tool_results: dict[str, list[str]] = field(default_factory=dict)  # per tool, in call order
    requires_sql: bool = True
    requires_splits: bool = False
    expects_window: bool = False

    def inputs(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "athlete": jsonable(asdict(self.athlete)),
            "live": self.live,
            "extra_tools": list(self.extra_tools),
            "tool_results": {k: list(v) for k, v in self.tool_results.items()},
        }

    def outputs(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requires_sql": self.requires_sql,
            "requires_splits": self.requires_splits,
            "expects_window": self.expects_window,
        }


Z2_RIDE = {
    "workout_date": "2026-09-14",
    "sport": "bike",
    "title": "Z2 ride",
    "completed": True,
    "planned_duration_sec": 5400,
    "actual_duration_sec": 5460,
    "planned_tss": 60,
    "actual_tss": 58,
    "actual_if": 0.62,
    "avg_power": 155,
    "normalized_power": 160,
    "avg_hr": 132,
    "feeling": 7,
    "rpe": 4,
    "comments": None,
    "garmin_activity_id": "g-1401",
}
INTERVAL_RUN = {
    "workout_date": "2026-09-15",
    "sport": "run",
    "title": "Intervals 6x800",
    "completed": True,
    "description": "WU 15 min, 6x800 m at threshold pace (4:15/km) with 2 min jog, CD 10 min",
    "actual_duration_sec": 3540,
    "actual_distance_m": 10600,
    "planned_tss": 70,
    "actual_tss": 74,
    "avg_hr": 158,
    "feeling": 6,
    "rpe": 7,
    "comments": None,
    "garmin_activity_id": "g-1502",
}
INTERVAL_SPLITS = [
    {"lap": 1, "type": "warmup", "distance_m": 2500, "duration_sec": 900, "avg_hr": 128},
    {
        "lap": 2,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 200,
        "avg_pace_sec_per_km": 250,
        "avg_hr": 168,
    },
    {"lap": 3, "type": "rest", "distance_m": 260, "duration_sec": 120, "avg_hr": 150},
    {
        "lap": 4,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 202,
        "avg_pace_sec_per_km": 252,
        "avg_hr": 172,
    },
    {"lap": 5, "type": "rest", "distance_m": 255, "duration_sec": 120, "avg_hr": 152},
    {
        "lap": 6,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 203,
        "avg_pace_sec_per_km": 254,
        "avg_hr": 175,
    },
    {"lap": 7, "type": "rest", "distance_m": 250, "duration_sec": 120, "avg_hr": 154},
    {
        "lap": 8,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 206,
        "avg_pace_sec_per_km": 258,
        "avg_hr": 177,
    },
    {"lap": 9, "type": "rest", "distance_m": 245, "duration_sec": 120, "avg_hr": 156},
    {
        "lap": 10,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 211,
        "avg_pace_sec_per_km": 264,
        "avg_hr": 179,
    },
    {"lap": 11, "type": "rest", "distance_m": 240, "duration_sec": 120, "avg_hr": 157},
    {
        "lap": 12,
        "type": "work",
        "distance_m": 800,
        "duration_sec": 218,
        "avg_pace_sec_per_km": 272,
        "avg_hr": 181,
    },
    {"lap": 13, "type": "cooldown", "distance_m": 1850, "duration_sec": 600, "avg_hr": 140},
]
MISSED_SWIM = {
    "workout_date": "2026-09-12",
    "sport": "swim",
    "title": "CSS 10x100",
    "completed": False,
    "description": "400 WU, 10x100 at CSS on 1:50, 200 CD",
    "planned_duration_sec": 3000,
    "planned_tss": 40,
    "actual_duration_sec": None,
    "actual_tss": None,
    "comments": None,
    "garmin_activity_id": None,
}
THRESHOLD_RIDE = {
    "workout_date": "2026-09-09",
    "sport": "bike",
    "title": "Threshold 3x10",
    "completed": True,
    "description": "3x10 min at 95-100% FTP, 5 min easy between",
    "planned_duration_sec": 4500,
    "actual_duration_sec": 4380,
    "planned_tss": 85,
    "actual_tss": 92,
    "actual_if": 0.87,
    "avg_power": 205,
    "normalized_power": 218,
    "avg_hr": 164,
    "feeling": 3,
    "rpe": 9,
    "comments": [
        {
            "author": "athlete",
            "text": "Legs were dead from the start; the third rep fell apart at 6 min.",
        }
    ],
    "garmin_activity_id": "g-0901",
}
BRICK = {
    "workout_date": "2026-09-13",
    "sport": "brick",
    "title": "Brick: 2h ride + 20 min run",
    "completed": True,
    "description": "2 h ride, 3x15 min at race power (200 W), then 20 min run at race pace",
    "planned_duration_sec": 8400,
    "actual_duration_sec": 8520,
    "planned_tss": 130,
    "actual_tss": 128,
    "actual_if": 0.74,
    "avg_power": 178,
    "normalized_power": 186,
    "avg_hr": 149,
    "feeling": 6,
    "rpe": 7,
    "comments": [{"author": "athlete", "text": "Run legs came around after 8 min."}],
    "garmin_activity_id": "g-1301",
}
BRICK_SPLITS = [
    {
        "lap": 1,
        "type": "bike",
        "distance_m": 60500,
        "duration_sec": 7200,
        "avg_power": 178,
        "avg_hr": 146,
    },
    {
        "lap": 2,
        "type": "run",
        "distance_m": 4300,
        "duration_sec": 1320,
        "avg_pace_sec_per_km": 307,
        "avg_hr": 163,
    },
]
WEEKLY_TSS = [
    {"week_start": "2026-07-20", "tss": 388},
    {"week_start": "2026-07-27", "tss": 412},
    {"week_start": "2026-08-03", "tss": 445},
    {"week_start": "2026-08-10", "tss": 290},
    {"week_start": "2026-08-17", "tss": 430},
    {"week_start": "2026-08-24", "tss": 462},
    {"week_start": "2026-08-31", "tss": 470},
    {"week_start": "2026-09-07", "tss": 397},
]
RUN_VOLUME = [
    {"month": "2026-06", "sessions": 12, "distance_m": 118400, "duration_sec": 38160},
    {"month": "2026-07", "sessions": 14, "distance_m": 141900, "duration_sec": 45600},
    {"month": "2026-08", "sessions": 15, "distance_m": 156200, "duration_sec": 49800},
]
SLEEP_HRV = [
    {"metric_date": f"2026-09-{d:02d}", "sleep_score": s, "hrv_overnight_avg": h}
    for d, s, h in [
        (2, 84, 69),
        (3, 79, 66),
        (4, 61, 55),
        (5, 66, 57),
        (6, 82, 67),
        (7, 80, 66),
        (8, 58, 54),
        (9, 74, 62),
        (10, 81, 66),
        (11, 78, 64),
        (12, 83, 68),
        (13, 72, 60),
        (14, 77, 63),
        (15, 70, 58),
    ]
]
READINESS_TODAY = {
    "date": "2026-09-16",
    "score": 42,
    "level": "LOW",
    "sleep_score": 64,
    "recovery_time_hours": 31,
    "hrv_status": "UNBALANCED",
    "acute_load": 356,
}
HRV_TODAY = {
    "date": "2026-09-16",
    "last_night_avg": 54,
    "weekly_avg": 61,
    "baseline_low": 58,
    "baseline_high": 70,
    "status": "UNBALANCED",
}
BODY_COMP = [
    {"date": "2026-08-17", "weight_kg": 75.4, "body_fat_pct": 12.8, "muscle_mass_kg": 36.1},
    {"date": "2026-08-24", "weight_kg": 75.0, "body_fat_pct": 12.6, "muscle_mass_kg": 36.1},
    {"date": "2026-08-31", "weight_kg": 74.6, "body_fat_pct": 12.3, "muscle_mass_kg": 36.0},
    {"date": "2026-09-07", "weight_kg": 74.2, "body_fat_pct": 12.1, "muscle_mass_kg": 36.0},
    {"date": "2026-09-14", "weight_kg": 74.0, "body_fat_pct": 12.0, "muscle_mass_kg": 35.9},
]

CASES: list[EvalCase] = [
    EvalCase(
        name="last_z2_ride",
        question="Give me feedback on my last completed ride.",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(Z2_RIDE)],
            "get_activity": [
                rows(
                    {
                        "activityId": "g-1401",
                        "averageHR": 132,
                        "maxHR": 148,
                        "avgPower": 155,
                        "duration": 5460,
                        "distance": 45200,
                    }
                )
            ],
        },
    ),
    EvalCase(
        name="run_intervals",
        question="How did yesterday's interval run go? Look at the reps.",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(INTERVAL_RUN)],
            "get_activity_splits": [rows(*INTERVAL_SPLITS)],
        },
        requires_splits=True,
    ),
    EvalCase(
        name="missed_swim",
        question="What happened with Saturday's swim?",
        athlete=athlete(),
        kind="session",
        tool_results={"query_training_db": [rows(MISSED_SWIM)]},
    ),
    EvalCase(
        name="threshold_rpe9",
        question="Feedback on last Wednesday's threshold ride please. I felt awful.",
        athlete=athlete(),
        kind="session",
        tool_results={"query_training_db": [rows(THRESHOLD_RIDE)]},
    ),
    EvalCase(
        name="brick_sunday",
        question="How did Sunday's brick go?",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(BRICK)],
            "get_activity_splits": [rows(*BRICK_SPLITS)],
        },
    ),
    EvalCase(
        name="weekly_tss_8w",
        question="Show my weekly TSS for the last 8 weeks.",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*WEEKLY_TSS)]},
        expects_window=True,
    ),
    EvalCase(
        name="run_volume_mom",
        question="How has my run volume changed month over month?",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*RUN_VOLUME)]},
        expects_window=True,
    ),
    EvalCase(
        name="sleep_vs_hrv",
        question="Is my sleep affecting my HRV?",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*SLEEP_HRV)]},
        expects_window=True,
    ),
    EvalCase(
        name="go_hard_today",
        question="Should I go hard today?",
        athlete=athlete(),
        kind="readiness",
        tool_results={
            "get_training_readiness": [rows(READINESS_TODAY)],
            "get_hrv_data": [rows(HRV_TODAY)],
        },
        requires_sql=False,
    ),
    EvalCase(
        name="trend_no_data",
        question="What was my average weekly bike TSS in June?",
        athlete=athlete(),
        kind="trend",
        expects_window=True,
    ),
    EvalCase(
        name="intervals_no_live",
        question="Break down the reps from yesterday's interval run.",
        athlete=athlete(),
        kind="session",
        live=False,
        tool_results={"query_training_db": [rows(INTERVAL_RUN)]},
        requires_splits=True,
    ),
    EvalCase(
        name="body_composition",
        question="How has my weight trended over the last month?",
        athlete=athlete(),
        kind="trend",
        extra_tools=["read_body_composition"],
        tool_results={"read_body_composition": [rows(*BODY_COMP)]},
        requires_sql=False,
        expects_window=True,
    ),
]
