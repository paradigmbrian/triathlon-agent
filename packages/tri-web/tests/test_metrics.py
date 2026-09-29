"""The pure numbers behind the Today cards."""

import pytest

from tri_web.metrics import (
    BASELINE_MIN,
    RAMP_CAUTION,
    acwr,
    acwr_flag,
    load_sparks,
    ramp,
    trend,
    tsb_zone,
)


def test_trend_is_none_without_todays_value():
    assert trend([60.0, 61.0, None], higher_is_better=True) is None
    assert trend([], higher_is_better=True) is None


def test_trend_below_the_minimum_has_averages_but_no_band():
    t = trend([60.0] * (BASELINE_MIN - 2) + [50.0], higher_is_better=True)
    assert t is not None
    assert t.band is None and t.better is False and t.now == 50.0
    assert t.avg_28d is not None and t.avg_7d is not None


def test_trend_band_edges_and_direction():
    base = [58.0, 62.0] * 10  # mean 60, population sd 2
    low = trend(base + [57.0], higher_is_better=True)
    assert low is not None and low.band == "below" and low.better is False
    high_rhr = trend([48.0, 52.0] * 10 + [52.5], higher_is_better=False)
    assert high_rhr is not None and high_rhr.band == "above" and high_rhr.better is False
    normal = trend(base + [60.0], higher_is_better=True)
    assert normal is not None and normal.band == "normal" and normal.better is None


def test_trend_uses_only_the_last_28_days_and_keeps_gaps_in_the_spark():
    values: list[float | None] = [100.0] * 10 + [60.0] * 27 + [None, 60.0]
    t = trend(values, higher_is_better=True)
    assert t is not None and t.avg_28d == 60.0
    assert len(t.spark) == 14 and t.spark[-2] is None and t.spark[-1] == 60.0


@pytest.mark.parametrize(
    ("tsb", "zone"),
    [
        (None, None),
        (-30.1, "overreaching"),
        (-30, "productive"),
        (-10.1, "productive"),
        (-10, "neutral"),
        (4.9, "neutral"),
        (5, "fresh"),
        (24.9, "fresh"),
        (25, "detraining"),
    ],
)
def test_tsb_zone_boundaries(tsb, zone):
    assert tsb_zone(tsb) == zone


def test_ramp_and_acwr_with_missing_inputs():
    assert ramp(50.0, 45.0) == 5.0
    assert ramp(None, 45.0) is None and ramp(50.0, None) is None
    assert acwr(60.0, 50.0) == 1.2
    assert acwr(60.0, 0) is None and acwr(60.0, None) is None and acwr(None, 50.0) is None
    assert RAMP_CAUTION == 8


def test_acwr_flag_band():
    assert acwr_flag(None) is None
    assert acwr_flag(0.79) == "low"
    assert acwr_flag(0.8) is None and acwr_flag(1.3) is None
    assert acwr_flag(1.31) == "high"


def test_load_sparks_follow_each_day():
    ctl: list[float | None] = [40 + 0.5 * i for i in range(28)]
    atl: list[float | None] = [50.0] * 28
    tsb: list[float | None] = [float(i) for i in range(28)]
    s = load_sparks(ctl, atl, tsb)
    assert s["tsb"] == tsb[-14:]
    assert len(s["acwr"]) == 14 and s["acwr"][-1] == round(50 / 53.5, 2)
    assert s["ramp"] == [3.5] * 14  # 0.5 a day for seven days


def test_load_sparks_keep_a_gap_as_a_gap():
    ctl: list[float | None] = [40.0] * 28
    ctl[20] = None  # the day a week before the last one, and the 7th of the 14 shown
    atl: list[float | None] = [50.0] * 28
    atl[26] = None
    tsb: list[float | None] = [0.0] * 28
    tsb[25] = None
    s = load_sparks(ctl, atl, tsb)
    assert s["tsb"][11] is None and s["tsb"][10] == 0.0
    assert s["acwr"][12] is None and s["acwr"][13] == 1.25
    assert s["ramp"][6] is None  # CTL missing that day
    assert s["ramp"][13] is None  # CTL missing seven days before the last day
    assert s["ramp"][12] == 0.0
