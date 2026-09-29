"""The Progress page in one call: the PMC, ramp rates, weekly totals by sport and sport share.
compute_progress is pure over row dicts; build_progress fetches them."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from tri_core.db import repo as crepo
from tri_planning.planning.targets import week_monday
from tri_web.metrics import ramp
from tri_web.runtime import Runtime

RangeKey = Literal["6w", "6m", "12m", "all"]
RANGE_DAYS: dict[str, int] = {"6w": 42, "6m": 182, "12m": 365}
RAMP_WINDOWS = (7, 28, 90, 365)
EARLIEST = date(2000, 1, 1)
STALE_DAYS = 3  # the page flags a curve older than this


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _n(v: Any) -> float:
    return 0.0 if v is None else float(v)


class SportTotals(BaseModel):
    duration_sec: float = 0
    distance_m: float = 0
    elevation_m: float = 0
    calories: float = 0
    tss: float = 0


class PmcPoint(BaseModel):
    date: date
    ctl: float | None
    atl: float | None
    tsb: float | None
    tss: float | None


class RampOut(BaseModel):
    days: int
    delta: float | None
    series: list[float | None]  # CTL over the window, oldest first, days + 1 long, None for a gap


class LongestOut(BaseModel):
    duration_sec: float = 0
    distance_m: float = 0


class WeekOut(BaseModel):
    week_start: date
    partial: bool
    by_sport: dict[str, SportTotals]
    longest: LongestOut


class ShareTotals(BaseModel):
    duration_sec: dict[str, float] = Field(default_factory=dict)
    distance_m: dict[str, float] = Field(default_factory=dict)


class ShareOut(BaseModel):
    completed: ShareTotals
    planned: ShareTotals


class ProgressView(BaseModel):
    range: RangeKey
    start: date
    end: date
    as_of: date | None  # the latest day with a CTL reading
    pmc: list[PmcPoint]
    ramp: list[RampOut]
    weeks: list[WeekOut]
    share: ShareOut


def range_floor(range_: RangeKey, today: date) -> date:
    """First day fetched for workouts: a Monday, so the first week is a whole week."""
    if range_ == "all":
        return EARLIEST
    return week_monday(today - timedelta(days=RANGE_DAYS[range_]))


def metrics_floor(range_: RangeKey, today: date, as_of: date | None = None) -> date:
    """Metrics reach back a full ramp window before the latest CTL day (a lagging sync must not
    push the 365-day start out of reach), and at least to the range's own start."""
    return min(range_floor(range_, today), (as_of or today) - timedelta(days=max(RAMP_WINDOWS)))


def _ramp_out(by_day: dict[date, dict[str, Any]], as_of: date | None, days: int) -> RampOut:
    if as_of is None:
        return RampOut(days=days, delta=None, series=[])
    series = [
        _f(by_day[d].get("ctl")) if (d := as_of - timedelta(days=days - i)) in by_day else None
        for i in range(days + 1)
    ]
    return RampOut(days=days, delta=ramp(series[-1], series[0]), series=series)


def _add(bucket: dict[str, float], sport: str, value: Any) -> None:
    if value is not None:
        bucket[sport] = bucket.get(sport, 0.0) + float(value)


def compute_progress(
    range_: RangeKey, today: date, workouts: list[dict[str, Any]], metrics: list[dict[str, Any]]
) -> ProgressView:
    by_day = {r["metric_date"]: r for r in metrics if r["metric_date"] <= today}
    floor = range_floor(range_, today)
    live = [w for w in workouts if floor <= w["workout_date"] <= today]
    if range_ == "all":
        earliest = min([w["workout_date"] for w in live] + list(by_day), default=today)
        start = week_monday(earliest)
    else:
        start = floor

    pmc: list[PmcPoint] = []
    for i in range((today - start).days + 1):
        d = start + timedelta(days=i)
        r = by_day.get(d, {})
        pmc.append(
            PmcPoint(
                date=d,
                ctl=_f(r.get("ctl")),
                atl=_f(r.get("atl")),
                tsb=_f(r.get("tsb")),
                tss=_f(r.get("tss_day")),
            )
        )
    as_of = max((d for d, r in by_day.items() if r.get("ctl") is not None), default=None)

    this_week = week_monday(today)
    totals: dict[date, dict[str, SportTotals]] = defaultdict(dict)
    longest: dict[date, LongestOut] = defaultdict(LongestOut)
    completed = ShareTotals()
    planned = ShareTotals()
    for row in live:
        sport = row["sport"]
        if row.get("completed"):
            monday = week_monday(row["workout_date"])
            t = totals[monday].setdefault(sport, SportTotals())
            t.duration_sec += _n(row.get("actual_duration_sec"))
            t.distance_m += _n(row.get("actual_distance_m"))
            t.elevation_m += _n(row.get("elevation_gain_m"))
            t.calories += _n(row.get("calories"))
            t.tss += _n(row.get("actual_tss"))
            lg = longest[monday]
            lg.duration_sec = max(lg.duration_sec, _n(row.get("actual_duration_sec")))
            lg.distance_m = max(lg.distance_m, _n(row.get("actual_distance_m")))
            _add(completed.duration_sec, sport, row.get("actual_duration_sec"))
            _add(completed.distance_m, sport, row.get("actual_distance_m"))
        _add(planned.duration_sec, sport, row.get("planned_duration_sec"))
        _add(planned.distance_m, sport, row.get("planned_distance_m"))

    weeks = [
        WeekOut(
            week_start=monday,
            partial=monday == this_week,
            by_sport=totals.get(monday, {}),
            longest=longest.get(monday, LongestOut()),
        )
        for monday in (
            start + timedelta(days=7 * i) for i in range((this_week - start).days // 7 + 1)
        )
    ]
    return ProgressView(
        range=range_,
        start=start,
        end=today,
        as_of=as_of,
        pmc=pmc,
        ramp=[_ramp_out(by_day, as_of, days) for days in RAMP_WINDOWS],
        weeks=weeks,
        share=ShareOut(completed=completed, planned=planned),
    )


async def build_progress(rt: Runtime, range_: RangeKey) -> ProgressView:
    today = rt.today()
    with rt.connect() as conn:
        workouts = crepo.list_workouts_between(conn, range_floor(range_, today), today)
        as_of = crepo.latest_ctl_date(conn, today)
        metrics = crepo.list_daily_metrics_between(conn, metrics_floor(range_, today, as_of), today)
    return compute_progress(range_, today, workouts, metrics)
