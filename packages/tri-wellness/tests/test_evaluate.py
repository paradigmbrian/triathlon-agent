from datetime import date, time

import pytest

from tri_wellness.labs.evaluate import (
    active_confounders,
    conventional_status,
    evaluate,
    functional_status,
)
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, TrainingContext
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry

D = date(2026, 9, 1)


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def lr(marker, value, unit, lab_low=None, lab_high=None) -> LabResult:
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        raw=RawResult(name=marker, value=str(value), unit=unit),
        lab_ref_low=lab_low,
        lab_ref_high=lab_high,
    )


def quiet_training(**over) -> TrainingContext:
    base = dict(
        drawn_on=D,
        ctl=60.0,
        atl=62.0,
        tsb=-2.0,
        tss_7d=350.0,
        last_sessions=[],
        sleep_2n_avg_sec=27000,
        sleep_30d_avg_sec=27000,
        hrv_2n_avg=60,
        hrv_30d_avg=60,
    )
    base.update(over)
    return TrainingContext(**base)


FASTED_AM = PanelContext(fasting=True, draw_time=time(7, 30))


# ---- status rules (spec §6) ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (29.9, "low"),  # below table conventional low 30
        (30.0, "suboptimal_low"),
        (49.9, "suboptimal_low"),
        (50.0, "optimal"),
        (150.0, "optimal"),
        (150.1, "suboptimal_high"),
        (400.0, "suboptimal_high"),
        (400.1, "high"),
    ],
)
def test_functional_status_boundaries_direction_both(reg, value, expected):
    assert functional_status(value, reg.get("ferritin")) == expected


def test_functional_status_direction_high_collapses_low_side(reg):
    crp = reg.get("hs_crp")  # conventional {high: 3.0}, functional {high: 1.0}
    assert functional_status(0.0, crp) == "optimal"
    assert functional_status(1.0, crp) == "optimal"
    assert functional_status(1.1, crp) == "suboptimal_high"
    assert functional_status(3.1, crp) == "high"
    ldl = reg.get("ldl")  # direction high, conventional {low: 0, high: 100}
    assert functional_status(0.0, ldl) == "optimal"


def test_functional_status_direction_low_collapses_high_side(reg):
    hdl = reg.get("hdl")  # male conventional {low: 40}, functional {low: 55, high: 85}
    assert functional_status(39.0, hdl) == "low"
    assert functional_status(50.0, hdl) == "suboptimal_low"
    assert functional_status(70.0, hdl) == "optimal"
    assert functional_status(120.0, hdl) == "optimal"  # high side collapsed


def test_conventional_status_prefers_lab_range(reg):
    f = reg.get("ferritin")
    assert conventional_status(25.0, 20.0, 300.0, f) == "in_range"  # lab range 20-300
    assert conventional_status(25.0, None, None, f) == "low"  # table range 30-400
    assert conventional_status(350.0, 20.0, 300.0, f) == "high"
    assert conventional_status(45.0, 39.0, None, reg.get("hdl")) == "in_range"  # one-sided lab
    assert conventional_status(38.0, 39.0, None, reg.get("hdl")) == "low"


# ---- confounders (spec §8) -------------------------------------------------------------------


def test_no_confounders_on_a_quiet_fasted_morning(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training()) == []


def test_recent_hard_session_by_tss_or_duration(reg):
    easy = {"date": "2026-08-31", "sport": "run", "duration_min": 45, "tss": 40, "title": "easy"}
    big_tss = {**easy, "tss": 151}
    long_ride = {**easy, "sport": "bike", "duration_min": 121, "tss": 100}
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[easy])) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[big_tss])) == [
        "recent_hard_session"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[long_ride])) == [
        "recent_hard_session"
    ]
    boundary = {**easy, "tss": 150, "duration_min": 120}
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[boundary])) == []
    no_tss = {**easy, "tss": None, "duration_min": 130}
    assert "recent_hard_session" in active_confounders(
        [], reg, FASTED_AM, quiet_training(last_sessions=[no_tss])
    )


def test_high_acute_load(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=60, atl=75)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=60, atl=75.1)) == [
        "high_acute_load"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=None, atl=90)) == []


def test_poor_sleep(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_2n_avg_sec=23400)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_2n_avg_sec=23399)) == [
        "poor_sleep"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_30d_avg_sec=None)) == []


def test_low_hrv(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=54)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=53)) == ["low_hrv"]
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=None)) == []


def test_not_fasting_and_afternoon_draw(reg):
    t = quiet_training()
    assert active_confounders([], reg, PanelContext(fasting=False), t) == ["not_fasting"]
    assert active_confounders([], reg, PanelContext(fasting=None), t) == []
    assert active_confounders([], reg, PanelContext(draw_time=time(10, 0)), t) == []
    assert active_confounders([], reg, PanelContext(draw_time=time(10, 1)), t) == ["afternoon_draw"]


def test_inflammation_from_hs_crp_in_the_same_panel(reg):
    t = quiet_training()
    assert active_confounders([lr("hs_crp", 1.0, "mg/L")], reg, FASTED_AM, t) == []
    assert active_confounders([lr("hs_crp", 1.1, "mg/L")], reg, FASTED_AM, t) == ["inflammation"]
    assert active_confounders([lr("ferritin", 20.0, "ng/mL")], reg, FASTED_AM, t) == []


def test_confounder_order_is_declaration_order(reg):
    hard = {"date": "2026-08-31", "sport": "bike", "duration_min": 180, "tss": 200, "title": "long"}
    out = active_confounders(
        [lr("hs_crp", 2.0, "mg/L")],
        reg,
        PanelContext(fasting=False, draw_time=time(14, 0)),
        quiet_training(last_sessions=[hard], atl=90, sleep_2n_avg_sec=20000, hrv_2n_avg=40),
    )
    assert out == [
        "recent_hard_session",
        "high_acute_load",
        "poor_sleep",
        "low_hrv",
        "not_fasting",
        "afternoon_draw",
        "inflammation",
    ]


# ---- evaluate ---------------------------------------------------------------------------------


def test_evaluate_builds_one_finding_per_result_with_only_declared_confounders(reg):
    hard = {"date": "2026-08-31", "sport": "run", "duration_min": 150, "tss": 180, "title": "long"}
    results = [
        lr("ferritin", 42.0, "ng/mL", 30.0, 400.0),
        lr("hs_crp", 2.5, "mg/L", None, 3.0),
        lr("tsh", 1.5, "mIU/L", 0.45, 4.5),
    ]
    findings = evaluate(
        results,
        reg,
        previous={"ferritin": (date(2026, 3, 1), 35.0)},
        context=PanelContext(fasting=False, draw_time=time(8, 0)),
        training=quiet_training(last_sessions=[hard]),
    )
    assert [f.marker for f in findings] == ["ferritin", "hs_crp", "tsh"]
    fer, crp, tsh = findings
    assert fer.display == "Ferritin" and fer.system == "iron" and fer.unit == "ng/mL"
    assert fer.conventional_status == "in_range" and fer.functional_status == "suboptimal_low"
    assert fer.functional_range == (50.0, 150.0)
    assert fer.previous == (date(2026, 3, 1), 35.0) and fer.delta_pct == 20.0
    # panel-level active: recent_hard_session, not_fasting, inflammation; ferritin
    # declares two
    assert fer.active_confounders == ["recent_hard_session", "inflammation"]
    assert fer.athlete_note.startswith("Endurance athletes: below 50")
    assert crp.functional_status == "suboptimal_high" and crp.functional_range == (None, 1.0)
    assert crp.active_confounders == ["recent_hard_session"]
    assert crp.previous is None and crp.delta_pct is None
    assert tsh.functional_status == "optimal" and tsh.active_confounders == []


def test_evaluate_delta_pct_rounding_and_zero_previous(reg):
    [f] = evaluate(
        [lr("ferritin", 47.0, "ng/mL")],
        reg,
        previous={"ferritin": (D, 45.0)},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert f.delta_pct == 4.4  # 2/45 = 4.444...
    [z] = evaluate(
        [lr("hs_crp", 0.5, "mg/L")],
        reg,
        previous={"hs_crp": (D, 0.0)},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert z.previous == (D, 0.0) and z.delta_pct is None


def test_evaluate_uses_lab_range_for_conventional_status_only(reg):
    [f] = evaluate(
        [lr("ferritin", 25.0, "ng/mL", 20.0, 300.0)],
        reg,
        previous={},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert f.conventional_status == "in_range"
    assert f.functional_status == "low"


def test_functional_range_collapses_the_side_direction_ignores(reg):
    # ck: direction high, functional {low: 40, high: 200} for male -- the low bound is
    # ignored by functional_status, so it must not appear in the reported range either.
    [ck] = evaluate(
        [lr("ck", 250.0, "U/L")], reg, previous={}, context=FASTED_AM, training=quiet_training()
    )
    assert ck.functional_range == (None, 200.0)
    # hdl: direction low, functional {low: 55, high: 85} for male -- the high bound is ignored.
    [hdl] = evaluate(
        [lr("hdl", 45.0, "mg/dL")], reg, previous={}, context=FASTED_AM, training=quiet_training()
    )
    assert hdl.functional_range == (55.0, None)
    # ferritin: direction both -- both bounds are kept.
    [fer] = evaluate(
        [lr("ferritin", 100.0, "ng/mL")],
        reg,
        previous={},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert fer.functional_range == (50.0, 150.0)
