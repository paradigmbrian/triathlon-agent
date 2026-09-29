"""The numbers behind the Today cards: a metric against its own 28 days, the TSB zone, the CTL
ramp over a week and the acute:chronic ratio. Pure; build_today feeds them rows."""

from __future__ import annotations

from statistics import fmean, pstdev
from typing import Literal

from pydantic import BaseModel

BASELINE_DAYS = 28
SHORT_DAYS = 7
SPARK_DAYS = 14
BASELINE_MIN = 14  # values needed before a band is drawn
# (lower bound, inclusive; zone), highest first. Below the last bound is "overreaching".
TSB_ZONES: tuple[tuple[float, str], ...] = (
    (25, "detraining"),
    (5, "fresh"),
    (-10, "neutral"),
    (-30, "productive"),
)
RAMP_CAUTION = 8.0  # CTL gained over 7 days
ACWR_LOW = 0.8
ACWR_HIGH = 1.3

Band = Literal["below", "normal", "above"]


class MetricTrend(BaseModel):
    now: float
    avg_7d: float | None
    avg_28d: float | None
    sd_28d: float | None
    band: Band | None  # None below BASELINE_MIN values
    better: bool | None  # now against avg_28d in the metric's good direction; None when equal
    spark: list[float | None]  # the last SPARK_DAYS days, oldest first, None for a gap


def _clean(values: list[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None]


def trend(values: list[float | None], higher_is_better: bool) -> MetricTrend | None:
    """values: one per day, oldest first, ending on the readiness day."""
    if not values or values[-1] is None:
        return None
    now = float(values[-1])
    window = _clean(values[-BASELINE_DAYS:])
    week = _clean(values[-SHORT_DAYS:])
    avg = fmean(window)
    sd = pstdev(window) if len(window) >= 2 else None
    band: Band | None = None
    if len(window) >= BASELINE_MIN and sd is not None:
        band = "below" if now < avg - sd else "above" if now > avg + sd else "normal"
    better = None if now == avg else (now > avg) == higher_is_better
    return MetricTrend(
        now=now,
        avg_7d=round(fmean(week), 2),
        avg_28d=round(avg, 2),
        sd_28d=None if sd is None else round(sd, 2),
        band=band,
        better=better,
        spark=[None if v is None else float(v) for v in values[-SPARK_DAYS:]],
    )


def tsb_zone(tsb: float | None) -> str | None:
    if tsb is None:
        return None
    for bound, zone in TSB_ZONES:
        if tsb >= bound:
            return zone
    return "overreaching"


def ramp(ctl_now: float | None, ctl_week_ago: float | None) -> float | None:
    if ctl_now is None or ctl_week_ago is None:
        return None
    return round(ctl_now - ctl_week_ago, 2)


def acwr(atl: float | None, ctl: float | None) -> float | None:
    if atl is None or not ctl:
        return None
    return round(atl / ctl, 2)


def acwr_flag(value: float | None) -> Literal["low", "high"] | None:
    if value is None:
        return None
    if value < ACWR_LOW:
        return "low"
    if value > ACWR_HIGH:
        return "high"
    return None
