"""The go / easy / rest call from the athlete's own numbers."""

from datetime import date, timedelta
from typing import Any

import pytest

from tri_web.metrics import MetricTrend
from tri_web.today import ReadinessOut
from tri_web.verdict import verdict

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


def call(r: ReadinessOut | None, todays: list[dict[str, Any]] | None = None) -> str:
    return verdict(r, todays or [], TODAY).call


def test_no_readiness_is_no_call():
    v = verdict(None, [], TODAY)
    assert v.call == "none" and v.based_on is None and not v.stale
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin data, sync first", "info")
    ]


def test_clean_day_is_go():
    v = verdict(rd(), [], TODAY)
    assert v.call == "go" and v.reasons == [] and v.based_on == TODAY and not v.stale


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (with_trend("hrv", HRV_LOW, hrv=52), "hrv"),
        (with_trend("resting_hr", RHR_HIGH, resting_hr=55), "resting_hr"),
        (rd(sleep_score=59), "sleep_score"),
        (rd(training_readiness=49), "training_readiness"),
        (rd(acwr=1.31, acwr_flag="high"), "acwr"),
        (rd(ramp_7d=9.0, ramp_caution=True), "ramp"),
    ],
)
def test_each_caution_alone_is_easy(r, key):
    v = verdict(r, [], TODAY)
    assert v.call == "easy"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "caution")]


def test_threshold_edges_do_not_flag():
    assert call(rd(sleep_score=60)) == "go"
    assert call(rd(training_readiness=50)) == "go"
    assert call(rd(acwr=1.3)) == "go"


def test_two_cautions_easy_three_rest():
    assert call(rd(sleep_score=59, training_readiness=49)) == "easy"
    assert call(rd(sleep_score=59, training_readiness=49, ramp_7d=9.0, ramp_caution=True)) == "rest"


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (rd(training_readiness=24), "training_readiness"),
        (rd(tsb=-31.0, tsb_zone="overreaching"), "tsb"),
        (rd(acwr=1.51, acwr_flag="high"), "acwr"),
    ],
)
def test_each_stop_is_rest(r, key):
    v = verdict(r, [], TODAY)
    assert v.call == "rest"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "stop")]


def test_readiness_25_is_a_caution_not_a_stop():
    v = verdict(rd(training_readiness=25), [], TODAY)
    assert v.call == "easy" and v.reasons[0].severity == "caution"


def test_hrv_low_and_rhr_high_together_are_one_stop():
    r = rd(trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55)
    v = verdict(r, [], TODAY)
    assert v.call == "rest"
    assert [(x.key, x.severity) for x in v.reasons] == [("hrv", "stop")]
    assert "52" in v.reasons[0].text and "55" in v.reasons[0].text


def test_stops_come_before_cautions():
    v = verdict(rd(sleep_score=59, training_readiness=24), [], TODAY)
    assert [x.severity for x in v.reasons] == ["stop", "caution"]


def test_acwr_guard():
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=19.9)) == "go"
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=20.0)) == "rest"
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=None)) == "go"


def test_stale_edges():
    one = verdict(rd(date=TODAY - timedelta(days=1), is_today=False), [], TODAY)
    assert one.call == "go" and one.stale and one.based_on == TODAY - timedelta(days=1)
    three = verdict(rd(date=TODAY - timedelta(days=3), is_today=False), [], TODAY)
    assert three.call == "go" and three.stale
    four = verdict(rd(date=TODAY - timedelta(days=4), is_today=False), [], TODAY)
    assert four.call == "none" and four.based_on == TODAY - timedelta(days=4)
    assert four.reasons[0].text == "Last Garmin data Fri Sep 25, sync first"


def w(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        completed=False, planned_if=None, planned_tss=None, planned_duration_sec=3600
    )
    base.update(over)
    return base


def test_harder_than_call():
    easy = rd(sleep_score=59)
    assert verdict(easy, [w(planned_if=0.8)], TODAY).harder_than_call
    assert not verdict(easy, [w(planned_if=0.7)], TODAY).harder_than_call
    assert verdict(easy, [w(planned_tss=60)], TODAY).harder_than_call  # 60 TSS/h, IF unknown
    assert not verdict(easy, [w(planned_tss=50)], TODAY).harder_than_call
    assert not verdict(easy, [w(planned_if=0.8, completed=True)], TODAY).harder_than_call
    assert not verdict(rd(), [w(planned_if=0.9)], TODAY).harder_than_call  # go


def test_session_done():
    assert verdict(rd(), [w(completed=True), w(completed=True)], TODAY).session_done
    assert not verdict(rd(), [w(completed=True), w()], TODAY).session_done
    assert not verdict(rd(), [], TODAY).session_done
