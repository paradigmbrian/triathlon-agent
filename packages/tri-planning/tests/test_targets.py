from datetime import date, timedelta

import pytest

from tri_planning.planning import periodization as P
from tri_planning.planning import targets
from tri_planning.planning.models import FitnessSnapshot, TrainingGoal

MONDAY = date(2026, 9, 14)
ALL_DAYS = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def race_goal(goal_type: str, weeks: int, **over) -> TrainingGoal:
    base = dict(
        goal_type=goal_type,
        event_name="Race",
        event_date=MONDAY + timedelta(weeks=weeks - 1, days=6),  # Sunday of the last week
        priority="A",
        weekly_hours_min=0,
        weekly_hours_max=30,
        available_days=ALL_DAYS,
    )
    base.update(over)
    return TrainingGoal(**base)


def flat_goal(goal_type: str, weeks: int, **over) -> TrainingGoal:
    base = dict(
        goal_type=goal_type,
        weekly_hours_min=0,
        weekly_hours_max=30,
        available_days=ALL_DAYS,
        duration_weeks=weeks,
    )
    base.update(over)
    return TrainingGoal(**base)


FIT = FitnessSnapshot(ctl=50, recent_weekly_tss=350)


def test_next_monday():
    assert targets.next_monday(date(2026, 9, 14)) == date(2026, 9, 14)  # a Monday
    assert targets.next_monday(date(2026, 9, 16)) == date(2026, 9, 21)
    assert targets.next_monday(date(2026, 9, 20)) == date(2026, 9, 21)


def test_count_weeks_inclusive_of_race_week():
    assert targets.count_weeks(race_goal("sprint", 10), MONDAY) == 10
    assert targets.count_weeks(flat_goal("build", 6), MONDAY) == 6


@pytest.mark.parametrize(
    "goal_type,total,expected",
    [
        ("sprint", 10, {"base": 2, "build": 4, "peak": 2, "taper": 1, "race": 1}),
        ("olympic", 14, {"base": 4, "build": 5, "peak": 3, "taper": 1, "race": 1}),
        ("half_ironman", 20, {"base": 8, "build": 6, "peak": 3, "taper": 2, "race": 1}),
        ("ironman", 24, {"base": 8, "build": 8, "peak": 4, "taper": 3, "race": 1}),
        ("build", 6, {"build": 6}),
        ("maintenance", 4, {"base": 4}),
        ("recovery", 2, {"recovery": 2}),
    ],
)
def test_phase_table_rows(goal_type, total, expected):
    phases, compressed = targets.allocate_phases(goal_type, total)
    counts = {p: phases.count(p) for p in set(phases)}
    assert counts == expected
    assert compressed is False
    # chronological order: base, build, peak, taper, race
    order = ["base", "build", "peak", "taper", "race", "recovery"]
    assert phases == sorted(phases, key=order.index)


def test_compression_drops_base_then_build():
    phases, compressed = targets.allocate_phases("sprint", 7)  # minimum is 8
    assert compressed is True
    assert phases.count("base") == 0
    assert phases.count("build") == 3
    assert phases[-4:] == ["peak", "peak", "taper", "race"]


def test_too_few_weeks_raises():
    with pytest.raises(ValueError, match="at least 4 weeks"):
        targets.allocate_phases("sprint", 3)  # peak 2 + taper 1 + race 1


def test_recovery_every_fourth_week_in_base_and_build_only():
    phases, _ = targets.allocate_phases("olympic", 14)  # 4 base, 5 build, 3 peak, 1 taper, 1 race
    flags = targets.recovery_flags("olympic", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7]
    assert not any(flags[9:])


def test_ironman_build_recovers_every_third_week():
    phases, _ = targets.allocate_phases("ironman", 24)  # 8 base, 8 build
    flags = targets.recovery_flags("ironman", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7, 10, 13]


def test_week1_fallback_chain():
    assert targets.week1_tss("sprint", FitnessSnapshot(ctl=50, recent_weekly_tss=350)) == 350
    assert targets.week1_tss("sprint", FitnessSnapshot(ctl=50)) == 350
    assert targets.week1_tss("ironman", FitnessSnapshot()) == P.GOAL_FLOOR_TSS["ironman"]


def test_ramp_is_capped_at_eight_percent():
    weeks = targets.build(race_goal("sprint", 10), FIT, MONDAY)
    assert [w.phase for w in weeks[:2]] == ["base", "base"]
    assert weeks[0].target_tss == 350
    assert weeks[1].target_tss == pytest.approx(350 * 1.08, abs=1)
    assert weeks[2].target_tss == pytest.approx(350 * 1.08**2, abs=1)


def test_ctl_cap_binds_before_ramp_when_ctl_is_low():
    fit = FitnessSnapshot(ctl=10, recent_weekly_tss=350)
    weeks = targets.build(race_goal("sprint", 10), fit, MONDAY)
    assert weeks[1].target_tss < 350 * 1.08
    # the cap for week 2 uses the CTL modeled after week 1's load, not the starting CTL
    ctl_after_w1 = targets.ctl_after_week(10, 350)
    assert weeks[1].target_tss == pytest.approx(targets.max_tss_for_ctl_rise(ctl_after_w1), abs=1)


def test_recovery_week_is_sixty_percent_and_ramp_resumes_from_last_load():
    weeks = targets.build(race_goal("olympic", 14), FIT, MONDAY)
    assert weeks[3].is_recovery
    assert weeks[3].target_tss == pytest.approx(weeks[2].target_tss * 0.6, abs=1)
    assert weeks[4].target_tss == pytest.approx(weeks[2].target_tss * 1.08, abs=1)


def test_peak_taper_race_factors():
    weeks = targets.build(race_goal("ironman", 24), FIT, MONDAY)
    by_phase = {}
    for w in weeks:
        by_phase.setdefault(w.phase, []).append(w)
    peak = by_phase["peak"][0].target_tss
    assert all(w.target_tss == peak for w in by_phase["peak"])
    assert [w.target_tss for w in by_phase["taper"]] == [
        pytest.approx(peak * f, abs=1) for f in (0.80, 0.60, 0.45)
    ]
    assert by_phase["race"][0].target_tss == pytest.approx(peak * 0.30, abs=1)
    assert by_phase["peak"][0].sport_hint == P.SPORT_HINTS["peak"]


def test_maintenance_flat_and_recovery_goal_half():
    m = targets.build(flat_goal("maintenance", 4), FIT, MONDAY)
    assert {w.target_tss for w in m} == {350}
    r = targets.build(flat_goal("recovery", 2), FIT, MONDAY)
    assert {w.target_tss for w in r} == {175}
    assert {w.phase for w in r} == {"recovery"}


def test_hours_cap_recomputes_tss_and_flags():
    g = race_goal("sprint", 10, weekly_hours_max=5)
    w = targets.build(g, FIT, MONDAY)[0]  # base, IF 0.70: 350 TSS would be 7.1 h
    assert w.target_hours == 5
    assert w.target_tss == pytest.approx(5 * 0.70**2 * 100, abs=1)
    assert P.FLAG_HOURS_CAPPED in w.flags


def test_hours_floor_not_applied_to_recovery_taper_race():
    g = race_goal("olympic", 14, weekly_hours_min=8, weekly_hours_max=30)
    weeks = targets.build(g, FIT, MONDAY)
    assert weeks[0].target_hours == 8 and P.FLAG_HOURS_CAPPED in weeks[0].flags
    rec = weeks[3]
    assert rec.is_recovery and rec.target_hours < 8
    assert weeks[-1].phase == "race" and weeks[-1].target_hours < 8


def test_compressed_flag_on_every_week():
    weeks = targets.build(race_goal("sprint", 7), FIT, MONDAY)
    assert all(P.FLAG_COMPRESSED in w.flags for w in weeks)


def test_build_requires_monday():
    with pytest.raises(ValueError, match="Monday"):
        targets.build(race_goal("sprint", 10), FIT, MONDAY + timedelta(days=1))


def test_week_dates_are_consecutive_mondays():
    weeks = targets.build(race_goal("sprint", 10), FIT, MONDAY)
    assert [w.week_start for w in weeks] == [MONDAY + timedelta(weeks=i) for i in range(10)]


def test_infer_phases_from_load_curve():
    curve = [300, 320, 340, 360, 380, 390, 400, 320, 250, 120]
    assert targets.infer_phases(curve) == [
        "build",
        "build",
        "build",
        "peak",
        "peak",
        "peak",
        "peak",
        "taper",
        "taper",
        "race",
    ]
    assert targets.infer_phases([200]) == ["race"]
    assert targets.infer_phases([]) == []
