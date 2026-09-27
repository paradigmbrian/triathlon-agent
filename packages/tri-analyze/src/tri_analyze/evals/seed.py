"""One synthetic athlete history for the analyst eval, seeded into Postgres so the analyst's SQL
runs for real. June is a run block (no bike), then a triathlon build from 2026-07-06 with a
recovery week from 2026-08-10, then the cases' own week from 2026-09-07. tss_day is each day's
completed load and CTL/ATL follow it, except the seven WEEK_DAYS rows the context block shows.

Every row the eval writes is marked (workout ids start "eval-", the profile's tp_athlete_id is
"eval"); seeding refuses a database that holds anything else."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from tri_analyze.evals.cases import (
    BRICK,
    BRICK_SPLITS,
    INTERVAL_RUN,
    MISSED_SWIM,
    PROFILE,
    SLEEP_HRV,
    THRESHOLD_RIDE,
    TODAY,
    WEEK_DAYS,
    Z2_RIDE,
)
from tri_core.db.connection import connect
from tri_core.db.models import AthleteProfileRow, DailyMetricsRow, GarminActivityRow, WorkoutRow
from tri_core.db.repo import (
    Conn,
    set_garmin_match,
    upsert_athlete_profile,
    upsert_daily_metrics,
    upsert_garmin_activities,
    upsert_workouts,
)

EVAL_ID = "eval"
SEEDED_TABLES = ("garmin_activities", "workouts", "daily_metrics", "athlete_profile")
START = date(2026, 6, 1)  # a Monday
BUILD_START = date(2026, 7, 6)
RECOVERY_WEEK = date(2026, 8, 10)
CASE_WEEK = date(2026, 9, 7)  # from here on, the cases' own sessions

# (weekday, sport, title, planned TSS, intensity factor, metres per hour)
Template = tuple[int, str, str, int, float, int]
RUN_BLOCK: list[Template] = [
    (1, "run", "Intervals 6x800", 70, 0.90, 12000),
    (2, "swim", "CSS 10x100", 40, 0.85, 3300),
    (3, "run", "Easy 45 min", 45, 0.72, 10900),
    (5, "run", "Long run", 80, 0.75, 10600),
    (6, "swim", "Easy swim", 35, 0.70, 3000),
]
BUILD: list[Template] = [
    (1, "bike", "Threshold 3x10", 85, 0.88, 30000),
    (2, "swim", "CSS 10x100", 40, 0.85, 3300),
    (3, "run", "Easy 45 min", 45, 0.72, 10900),
    (5, "bike", "Long ride", 150, 0.70, 28500),
    (6, "run", "Long run", 75, 0.75, 10600),
]

EASY_SWIM = {
    "workout_date": "2026-09-08",
    "sport": "swim",
    "title": "Easy swim",
    "completed": True,
    "planned_tss": 35,
    "actual_tss": 34,
    "planned_duration_sec": 2600,
    "actual_duration_sec": 2580,
    "actual_distance_m": 2300,
}
EASY_RUN = {
    "workout_date": "2026-09-11",
    "sport": "run",
    "title": "Easy 45 min",
    "completed": True,
    "planned_tss": 45,
    "actual_tss": 45,
    "planned_duration_sec": 2700,
    "actual_duration_sec": 2760,
    "actual_distance_m": 8300,
    "avg_hr": 138,
    "feeling": 7,
    "rpe": 3,
}
TEMPO = {
    "workout_date": "2026-09-17",
    "sport": "run",
    "title": "Tempo 40 min",
    "completed": False,
    "planned_tss": 55,
    "planned_duration_sec": 3600,
}
LONG_RIDE = {
    "workout_date": "2026-09-19",
    "sport": "bike",
    "title": "Long ride",
    "completed": False,
    "planned_tss": 150,
    "planned_duration_sec": 11000,
}
CASE_WEEK_ROWS: list[tuple[str, dict[str, Any]]] = [
    ("easy-swim", EASY_SWIM),
    ("threshold", THRESHOLD_RIDE),
    ("easy-run", EASY_RUN),
    ("missed-swim", MISSED_SWIM),
    ("brick", BRICK),
    ("z2", Z2_RIDE),
    ("intervals", INTERVAL_RUN),
    ("tempo", TEMPO),
    ("long-ride", LONG_RIDE),
]


class EvalDatabaseInUse(RuntimeError):
    """The eval database holds rows the eval did not write."""


def workout_row(r: dict[str, Any]) -> WorkoutRow:
    """A WorkoutRow from a dict holding any of its fields; the rest are None, `completed` True
    and `raw` {}. `workout_date` may be an ISO string; keys that are not fields are ignored."""
    fields: dict[str, Any] = dict.fromkeys(WorkoutRow.__dataclass_fields__)
    fields.update(completed=True, raw={}, title="")
    fields.update({k: v for k, v in r.items() if k in fields})
    if isinstance(fields["workout_date"], str):
        fields["workout_date"] = date.fromisoformat(fields["workout_date"])
    return WorkoutRow(**fields)


def _seconds(tss: float, intensity: float) -> int:
    return round(tss / (intensity * intensity * 100) * 3600)


def _templated(d: date, t: Template, factor: float) -> dict[str, Any]:
    _, sport, title, tss, intensity, speed = t
    planned = round(tss * factor)
    actual = planned + d.toordinal() % 7 - 3
    secs = _seconds(actual, intensity)
    row: dict[str, Any] = {
        "tp_workout_id": f"{EVAL_ID}-{d.isoformat()}-{sport}",
        "workout_date": d,
        "sport": sport,
        "title": title,
        "completed": True,
        "planned_tss": planned,
        "planned_duration_sec": _seconds(planned, intensity),
        "actual_tss": actual,
        "actual_duration_sec": secs,
        "actual_distance_m": round(speed * secs / 3600),
        "actual_if": intensity,
        "avg_hr": round(100 + intensity * 70),
        "feeling": 6,
        "rpe": round(intensity * 10) - 2,
    }
    if sport == "bike":
        row["normalized_power"] = round(intensity * PROFILE["ftp_watts"])
        row["avg_power"] = round(intensity * PROFILE["ftp_watts"] * 0.95)
    return row


def workouts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = START
    while d < CASE_WEEK:
        monday = d - timedelta(days=d.weekday())
        plan = RUN_BLOCK if d < BUILD_START else BUILD
        factor = 0.65 if monday == RECOVERY_WEEK else 1.0
        out += [_templated(d, t, factor) for t in plan if t[0] == d.weekday()]
        d += timedelta(days=1)
    for slug, row in CASE_WEEK_ROWS:
        out.append(
            {
                **row,
                "tp_workout_id": f"{EVAL_ID}-{slug}",
                "workout_date": date.fromisoformat(str(row["workout_date"])),
            }
        )
    return out


def daily_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    load: dict[date, float] = defaultdict(float)
    for w in rows:
        if w.get("completed") and w.get("actual_tss") is not None:
            load[w["workout_date"]] += float(w["actual_tss"])
    fixed = {d["metric_date"]: d for d in WEEK_DAYS}
    sleep = {date.fromisoformat(str(s["metric_date"])): s for s in SLEEP_HRV}
    ctl = atl = 40.0
    out: list[dict[str, Any]] = []
    d = START
    while d < TODAY:
        tss = load.get(d, 0.0)
        ctl += (tss - ctl) / 42
        atl += (tss - atl) / 7
        if d in fixed:
            out.append(dict(fixed[d]))  # the cases' own days, exactly as the context shows them
            ctl, atl = float(fixed[d]["ctl"]), float(fixed[d]["atl"])
        else:
            n = d.toordinal()
            s: dict[str, Any] = sleep.get(d) or {
                "sleep_score": 70 + n * 7 % 15,
                "hrv_overnight_avg": 58 + n * 5 % 11,
            }
            score, hrv = int(s["sleep_score"]), int(s["hrv_overnight_avg"])
            out.append(
                {
                    "metric_date": d,
                    "tss_day": tss,
                    "ctl": round(ctl, 1),
                    "atl": round(atl, 1),
                    "tsb": round(ctl - atl, 1),
                    "sleep_score": score,
                    "hrv_overnight_avg": hrv,
                    "resting_hr": 46,
                    "training_readiness": max(20, min(95, 40 + (score - 60) + (hrv - 55))),
                }
            )
        d += timedelta(days=1)
    return out


def _activities(rows: list[dict[str, Any]]) -> list[tuple[GarminActivityRow, str]]:
    """One Garmin activity per linked session, and the brick's run leg as a second one."""
    out: list[tuple[GarminActivityRow, str]] = []
    for w in rows:
        gid = w.get("garmin_activity_id")
        if not gid:
            continue
        start = datetime.combine(w["workout_date"], time(7, 0))
        sport = "cycling" if w["sport"] in ("bike", "brick") else w["sport"]
        first: dict[str, Any] = BRICK_SPLITS[0] if w["sport"] == "brick" else {}
        out.append(
            (
                GarminActivityRow(
                    id=gid,
                    type_key=sport,
                    sport=sport,
                    start_time_local=start,
                    duration_sec=first.get("duration_sec", w.get("actual_duration_sec")),
                    distance_m=first.get("distance_m", w.get("actual_distance_m")),
                    avg_hr=first.get("avg_hr", w.get("avg_hr")),
                    name=w["title"],
                    raw={},
                ),
                w["tp_workout_id"],
            )
        )
        if w["sport"] == "brick":
            leg: dict[str, Any] = BRICK_SPLITS[1]
            out.append(
                (
                    GarminActivityRow(
                        id=f"{gid}-run",
                        type_key="running",
                        sport="running",
                        start_time_local=start + timedelta(seconds=int(first["duration_sec"])),
                        duration_sec=leg["duration_sec"],
                        distance_m=leg["distance_m"],
                        avg_hr=leg["avg_hr"],
                        name=f"{w['title']} (run)",
                        raw={},
                    ),
                    w["tp_workout_id"],
                )
            )
    return out


def _refuse_foreign_rows(conn: Conn) -> None:
    foreign = conn.execute(
        "select (select count(*) from workouts where tp_workout_id not like %s) "
        "+ (select count(*) from athlete_profile where tp_athlete_id is distinct from %s) as n",
        (f"{EVAL_ID}-%", EVAL_ID),
    ).fetchone()
    if foreign and foreign["n"]:
        raise EvalDatabaseInUse(
            "the eval database holds workouts or a profile the eval did not write; refusing to "
            "replace them (use the test database, or an empty one with --eval-db)"
        )


def clear_database(url: str) -> None:
    with connect(url) as conn:
        _refuse_foreign_rows(conn)
        conn.execute("truncate " + ", ".join(SEEDED_TABLES))
        conn.commit()


def seed_database(url: str) -> None:
    """Replace the seeded tables' contents with the history. Committed: the SQL tool reads them
    on its own connection."""
    rows = workouts()
    with connect(url) as conn:
        _refuse_foreign_rows(conn)
        conn.execute("truncate " + ", ".join(SEEDED_TABLES))
        upsert_athlete_profile(
            conn,
            AthleteProfileRow(
                tp_athlete_id=EVAL_ID,
                ftp_watts=PROFILE["ftp_watts"],
                run_threshold_pace_sec_per_km=PROFILE["run_threshold_pace_sec_per_km"],
                swim_css_sec_per_100m=PROFILE["swim_css_sec_per_100m"],
                lthr_bpm=PROFILE["lthr_bpm"],
                max_hr_bpm=PROFILE["max_hr_bpm"],
                hr_zones=None,
                power_zones=None,
                pace_zones=None,
                weight_kg=PROFILE["weight_kg"],
                raw={},
            ),
        )
        upsert_workouts(conn, [workout_row(r) for r in rows])
        acts = _activities(rows)
        upsert_garmin_activities(conn, [a for a, _ in acts])
        for a, tp_id in acts:
            conn.execute(
                "update garmin_activities set tp_workout_id = %s where id = %s", (tp_id, a.id)
            )
            if not a.id.endswith("-run"):
                set_garmin_match(conn, tp_id, a.id, a.start_time_local)
        upsert_daily_metrics(conn, [DailyMetricsRow(**m) for m in daily_metrics(rows)])
        conn.commit()
