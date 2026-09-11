"""Load, sleep and HRV around a draw date, from the tables tri-core syncs. Read-only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_wellness.labs.evaluate import HARD_SESSION_MIN, HARD_SESSION_TSS
from tri_wellness.labs.models import TrainingContext

SESSION_WINDOW_DAYS = 3  # sessions on the three calendar days before the draw (the 72 h)
MAX_SESSIONS = 3
NIGHTS = 2  # the two nights ending on the draw morning: metric_date in {D-1, D}
BASELINE_DAYS = 30  # metric_date in [D-30, D-1]
LOAD_FALLBACK_DAYS = 7  # newest ctl within this many days when the draw-day row is missing
TSS_WINDOW_DAYS = 7  # tss_day summed over [D-7, D-1]

_NIGHT_COLUMNS = frozenset({"sleep_seconds", "hrv_overnight_avg"})


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _sessions(conn: Conn, drawn_on: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        select workout_date, sport, title, actual_duration_sec, actual_tss
        from workouts
        where completed and workout_date between %s and %s
        -- hardness first: a session over evaluate.py's HARD_SESSION_TSS/HARD_SESSION_MIN
        -- outranks every non-qualifying session, so a hard session can never be cut by
        -- `limit`; ties break by actual TSS, then duration, then most recent workout_date
        order by
            (case when actual_tss > {HARD_SESSION_TSS}
                       or actual_duration_sec > {HARD_SESSION_MIN * 60}
                  then 1 else 0 end) desc,
            actual_tss desc nulls last, actual_duration_sec desc nulls last, workout_date desc
        limit %s
        """,
        (
            drawn_on - timedelta(days=SESSION_WINDOW_DAYS),
            drawn_on - timedelta(days=1),
            MAX_SESSIONS,
        ),
    ).fetchall()
    return [
        {
            "date": r["workout_date"].isoformat(),
            "sport": r["sport"],
            "duration_min": (
                None if r["actual_duration_sec"] is None else r["actual_duration_sec"] // 60
            ),
            "tss": _f(r["actual_tss"]),
            "title": r["title"],
        }
        for r in rows
    ]


def _night_avg(conn: Conn, column: str, start: date, end: date) -> int | None:
    assert column in _NIGHT_COLUMNS
    row = conn.execute(
        f"select avg({column}) as v from daily_metrics where metric_date between %s and %s",
        (start, end),
    ).fetchone()
    return None if row is None or row["v"] is None else round(float(row["v"]))


def load_training_context(conn: Conn, drawn_on: date) -> TrainingContext:
    eve = drawn_on - timedelta(days=1)
    load = conn.execute(
        """
        select ctl, atl, tsb from daily_metrics
        where metric_date between %s and %s and ctl is not null
        order by metric_date desc limit 1
        """,
        (drawn_on - timedelta(days=LOAD_FALLBACK_DAYS), drawn_on),
    ).fetchone()
    tss = conn.execute(
        "select sum(tss_day) as v from daily_metrics where metric_date between %s and %s",
        (drawn_on - timedelta(days=TSS_WINDOW_DAYS), eve),
    ).fetchone()
    first_night = drawn_on - timedelta(days=NIGHTS - 1)
    baseline_start = drawn_on - timedelta(days=BASELINE_DAYS)
    return TrainingContext(
        drawn_on=drawn_on,
        ctl=_f(load["ctl"]) if load else None,
        atl=_f(load["atl"]) if load else None,
        tsb=_f(load["tsb"]) if load else None,
        tss_7d=_f(tss["v"]) if tss else None,
        last_sessions=_sessions(conn, drawn_on),
        sleep_2n_avg_sec=_night_avg(conn, "sleep_seconds", first_night, drawn_on),
        sleep_30d_avg_sec=_night_avg(conn, "sleep_seconds", baseline_start, eve),
        hrv_2n_avg=_night_avg(conn, "hrv_overnight_avg", first_night, drawn_on),
        hrv_30d_avg=_night_avg(conn, "hrv_overnight_avg", baseline_start, eve),
    )
