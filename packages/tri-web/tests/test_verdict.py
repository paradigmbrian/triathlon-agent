"""The readiness level from Garmin's score and the athlete's own numbers."""

from datetime import date, timedelta
from typing import Any

import pytest

from tri_web.metrics import MetricTrend
from tri_web.today import ReadinessOut
from tri_web.verdict import conditions, verdict

TODAY = date(2026, 9, 29)


def trend(now: float, avg: float, sd: float, band: str | None) -> MetricTrend:
    return MetricTrend(
        now=now, avg_7d=avg, avg_28d=avg, sd_28d=sd, band=band, better=None, spark=[]
    )


TRENDS = {
    "hrv": trend(60, 60, 3, "normal"),
    "resting_hr": trend(48, 48, 2, "normal"),
    "sleep_score": trend(80, 78, 4, "normal"),
    "sleep_hours": trend(7.5, 7.3, 0.4, "normal"),
    "training_readiness": trend(70, 68, 6, "normal"),
}


def rd(**over: Any) -> ReadinessOut:
    base: dict[str, Any] = dict(
        date=TODAY,
        is_today=True,
        sleep_score=80,
        sleep_hours=7.5,
        hrv=60,
        resting_hr=48,
        body_battery=80,
        training_readiness=70,
        ctl=40.0,
        atl=42.0,
        tsb=-2.0,
        trends=dict(TRENDS),
        tsb_zone="neutral",
        ramp_7d=2.0,
        ramp_caution=False,
        acwr=1.05,
        acwr_flag=None,
    )
    base.update(over)
    return ReadinessOut(**base)


def with_trend(key: str, t: MetricTrend, **over: Any) -> ReadinessOut:
    return rd(trends={**TRENDS, key: t}, **over)


HRV_LOW = trend(52, 60, 3, "below")
RHR_HIGH = trend(55, 48, 2, "above")

# Garmin's top band, so only the flags can cap the level. Never pass training_readiness as well.
PRIME: dict[str, Any] = dict(training_readiness=96)


def level(r: ReadinessOut | None, todays: list[dict[str, Any]] | None = None) -> str:
    return verdict(r, todays or [], TODAY).level


def test_no_readiness_is_no_reading():
    v = verdict(None, [], TODAY)
    assert v.level == "none" and v.based_on is None and not v.stale
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin data, sync first", "info")
    ]


def test_clean_day_with_a_prime_score_is_prime():
    v = verdict(rd(**PRIME), [], TODAY)
    assert v.level == "prime" and v.reasons == [] and v.based_on == TODAY and not v.stale


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (24, "poor"),
        (25, "low"),
        (49, "low"),
        (50, "moderate"),
        (74, "moderate"),
        (75, "high"),
        (94, "high"),
        (95, "prime"),
    ],
)
def test_garmin_bands_set_the_level(score, expected):
    assert level(rd(training_readiness=score)) == expected


def test_missing_garmin_score_caps_at_high_and_says_so():
    v = verdict(rd(training_readiness=None), [], TODAY)
    assert v.level == "high"
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin readiness score today, capped at high", "info")
    ]


def test_garmin_holds_the_level_down_and_gives_the_reason():
    v = verdict(rd(training_readiness=62), [], TODAY)
    assert v.level == "moderate"
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "Garmin readiness 62, moderate band", "info")
    ]


def test_no_extra_reason_when_a_readiness_flag_already_explains():
    v = verdict(rd(training_readiness=40), [], TODAY)
    assert v.level == "low"
    assert [(r.key, r.severity) for r in v.reasons] == [("training_readiness", "caution")]


def test_no_extra_reason_when_the_flags_are_the_cap():
    v = verdict(rd(sleep_score=59, **PRIME), [], TODAY)
    assert v.level == "high"
    assert [(r.key, r.severity) for r in v.reasons] == [("sleep_score", "caution")]


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (with_trend("hrv", HRV_LOW, hrv=52, **PRIME), "hrv"),
        (with_trend("resting_hr", RHR_HIGH, resting_hr=55, **PRIME), "resting_hr"),
        (rd(sleep_score=59, **PRIME), "sleep_score"),
        (rd(acwr=1.31, acwr_flag="high", **PRIME), "acwr"),
        (rd(ramp_7d=9.0, ramp_caution=True, **PRIME), "ramp"),
    ],
)
def test_each_caution_alone_caps_at_high(r, key):
    v = verdict(r, [], TODAY)
    assert v.level == "high"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "caution")]


def test_a_readiness_caution_is_low_because_the_score_is_under_50():
    v = verdict(rd(training_readiness=49), [], TODAY)
    assert v.level == "low"
    assert [(x.key, x.severity) for x in v.reasons] == [("training_readiness", "caution")]


def test_threshold_edges_do_not_flag():
    assert level(rd(sleep_score=60, **PRIME)) == "prime"
    assert level(rd(acwr=1.3, **PRIME)) == "prime"
    v = verdict(rd(training_readiness=50), [], TODAY)
    assert v.level == "moderate"
    assert [r.severity for r in v.reasons] == ["info"]  # the Garmin band only, no flag


def test_two_cautions_moderate_three_low():
    two = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, **PRIME)
    assert level(two) == "moderate"
    three = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, acwr=1.31, acwr_flag="high", **PRIME)
    assert level(three) == "low"


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (rd(training_readiness=24), "training_readiness"),
        (rd(tsb=-31.0, tsb_zone="overreaching", **PRIME), "tsb"),
        (rd(acwr=1.51, acwr_flag="high", **PRIME), "acwr"),
    ],
)
def test_each_stop_is_poor(r, key):
    v = verdict(r, [], TODAY)
    assert v.level == "poor"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "stop")]


def test_readiness_25_is_a_caution_not_a_stop():
    v = verdict(rd(training_readiness=25), [], TODAY)
    assert v.level == "low" and v.reasons[0].severity == "caution"


def test_hrv_low_and_rhr_high_together_are_one_stop():
    r = rd(
        trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55, **PRIME
    )
    v = verdict(r, [], TODAY)
    assert v.level == "poor"
    assert [(x.key, x.severity) for x in v.reasons] == [("hrv", "stop")]
    assert "52" in v.reasons[0].text and "55" in v.reasons[0].text


def test_stops_come_before_cautions():
    v = verdict(rd(sleep_score=59, training_readiness=24), [], TODAY)
    assert [x.severity for x in v.reasons] == ["stop", "caution"]


def test_acwr_guard():
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=19.9, **PRIME)) == "prime"
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=20.0, **PRIME)) == "poor"
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=None, **PRIME)) == "prime"


def test_stale_edges():
    one = verdict(rd(date=TODAY - timedelta(days=1), is_today=False, **PRIME), [], TODAY)
    assert one.level == "prime" and one.stale and one.based_on == TODAY - timedelta(days=1)
    three = verdict(rd(date=TODAY - timedelta(days=3), is_today=False, **PRIME), [], TODAY)
    assert three.level == "prime" and three.stale
    four = verdict(rd(date=TODAY - timedelta(days=4), is_today=False, **PRIME), [], TODAY)
    assert four.level == "none" and four.based_on == TODAY - timedelta(days=4)
    assert four.reasons[0].text == "Last Garmin data Fri Sep 25, sync first"


def w(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        completed=False, planned_if=None, planned_tss=None, planned_duration_sec=3600
    )
    base.update(over)
    return base


def test_harder_than_call():
    moderate = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, **PRIME)
    assert verdict(moderate, [w(planned_if=0.8)], TODAY).harder_than_call
    assert not verdict(moderate, [w(planned_if=0.7)], TODAY).harder_than_call
    assert verdict(moderate, [w(planned_tss=60)], TODAY).harder_than_call  # 60 TSS/h, IF unknown
    assert not verdict(moderate, [w(planned_tss=50)], TODAY).harder_than_call
    assert not verdict(moderate, [w(planned_if=0.8, completed=True)], TODAY).harder_than_call
    assert not verdict(rd(**PRIME), [w(planned_if=0.9)], TODAY).harder_than_call  # prime
    high = rd(sleep_score=59, **PRIME)  # one caution no longer warns
    assert not verdict(high, [w(planned_if=0.9)], TODAY).harder_than_call


def test_session_done():
    assert verdict(rd(), [w(completed=True), w(completed=True)], TODAY).session_done
    assert not verdict(rd(), [w(completed=True), w()], TODAY).session_done
    assert not verdict(rd(), [], TODAY).session_done


KEYS = [
    "training_readiness",
    "hrv",
    "resting_hr",
    "sleep_score",
    "sleep_hours",
    "tsb",
    "acwr",
    "ramp",
]


def rows(r: ReadinessOut | None) -> dict[str, Any]:
    return {c.key: c for c in conditions(r)}


def test_no_readiness_no_rows():
    assert conditions(None) == []


def test_row_order_labels_and_units():
    cs = conditions(rd())
    assert [c.key for c in cs] == KEYS
    assert [c.label for c in cs] == [
        "Readiness",
        "HRV",
        "RHR",
        "Sleep",
        "Slept",
        "Form (TSB)",
        "ACWR",
        "Ramp",
    ]
    assert [c.unit for c in cs] == ["", "ms", "bpm", "", "h", "", "", "/wk"]


def test_trend_rows_carry_baseline_band_and_status():
    c = rows(with_trend("hrv", HRV_LOW, hrv=52))["hrv"]
    assert (c.value, c.baseline, c.band_low, c.band_high) == (52, 60, 57, 63)
    assert c.status == "low" and c.flagged
    assert rows(rd())["hrv"].status == "within" and not rows(rd())["hrv"].flagged
    assert rows(with_trend("resting_hr", RHR_HIGH, resting_hr=55))["resting_hr"].status == "high"


def test_rows_without_data_or_baseline():
    no_band = trend(60, 60, 3, None)
    assert rows(with_trend("hrv", no_band))["hrv"].status == "no baseline"
    r = rows(rd(sleep_hours=None, trends={k: v for k, v in TRENDS.items() if k != "sleep_hours"}))
    assert r["sleep_hours"].status == "no data" and r["sleep_hours"].value is None


def test_sleep_score_flag_follows_the_threshold_not_the_band():
    assert rows(rd(sleep_score=59))["sleep_score"].flagged


def test_tsb_row():
    c = rows(rd(tsb=-31.0, tsb_zone="overreaching"))["tsb"]
    assert (c.band_low, c.band_high, c.status, c.flagged) == (-30, 25, "overreaching", True)
    assert rows(rd(tsb=None, tsb_zone=None))["tsb"].status == "no data"


def test_acwr_row_statuses():
    assert rows(rd(acwr=1.05))["acwr"].status == "within"
    assert rows(rd(acwr=1.4))["acwr"].status == "high"
    assert rows(rd(acwr=1.4))["acwr"].flagged
    assert rows(rd(acwr=0.7))["acwr"].status == "low"
    assert not rows(rd(acwr=0.7))["acwr"].flagged
    guarded = rows(rd(acwr=1.6, ctl=19.0))["acwr"]
    assert guarded.status == "ignored: CTL under 20" and not guarded.flagged
    c = rows(rd())["acwr"]
    assert (c.band_low, c.band_high) == (0.8, 1.3)


def test_ramp_row():
    c = rows(rd(ramp_7d=9.0, ramp_caution=True))["ramp"]
    assert (c.value, c.band_low, c.band_high, c.status, c.flagged) == (9.0, None, 8, "fast", True)
    assert rows(rd(ramp_7d=None))["ramp"].status == "no data"


def test_combined_stop_flags_both_rows():
    r = rd(trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55)
    assert rows(r)["hrv"].flagged and rows(r)["resting_hr"].flagged


def test_trend_rows_carry_their_history_and_the_rest_carry_none():
    spark: list[float | None] = [55, 56, None, 58, 60]
    hist = MetricTrend(
        now=60, avg_7d=58, avg_28d=58, sd_28d=3, band="normal", better=None, spark=spark
    )
    r = rows(with_trend("hrv", hist))
    assert r["hrv"].spark == spark
    assert r["tsb"].spark == [] and r["acwr"].spark == [] and r["ramp"].spark == []
    no_trend = rows(rd(trends={k: v for k, v in TRENDS.items() if k != "hrv"}))
    assert no_trend["hrv"].spark == []
