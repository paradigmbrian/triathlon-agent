from datetime import date, timedelta

from tri_planning.planning.models import DesignedSession, DesignedWeek, WeekTarget
from tri_planning.planning.tss import scale_to_target, session_tss

MON = date(2026, 9, 14)
INTERVALS = {
    "primaryIntensityMetric": "percentOfThresholdPace",
    "steps": [
        {"name": "wu", "duration_seconds": 600, "intensity_min": 60, "intensity_max": 70},
        {
            "type": "repetition",
            "reps": 4,
            "steps": [
                {"name": "on", "duration_seconds": 300, "intensity_min": 95, "intensity_max": 100},
                {"name": "off", "duration_seconds": 180, "intensity_min": 60, "intensity_max": 70},
            ],
        },
        {"name": "cd", "duration_seconds": 1080, "intensity_min": 60, "intensity_max": 70},
    ],
}


def s(day=0, minutes=60, intensity="endurance", sport="bike", structure=None) -> DesignedSession:
    return DesignedSession(
        date=MON + timedelta(days=day),
        sport=sport,
        title=f"{sport} {minutes}",
        description="",
        duration_minutes=minutes,
        intensity=intensity,
        structure=structure,
    )


def wk(*sessions) -> DesignedWeek:
    return DesignedWeek(week_start=MON, sessions=list(sessions), coach_note="note")


def tgt(tss: float) -> WeekTarget:
    return WeekTarget(week_start=MON, phase="build", target_tss=tss, target_hours=6)


def test_session_tss_is_hours_times_if_squared_times_100():
    assert session_tss(60, "threshold") == 81.0
    assert session_tss(90, "endurance") == 73.5
    assert session_tss(45, "recovery") == 31.7
    assert session_tss(30, "vo2") == 50.0
    assert session_tss(0, "race") == 0.0


def test_a_week_inside_the_tolerance_is_not_scaled():
    week = wk(s(0, 180), s(2, 60, "threshold", "run", INTERVALS))  # 147 + 81 = 228
    planned, violations = scale_to_target(week, tgt(240))
    assert violations == []
    assert [x.duration_minutes for x in planned.sessions] == [180, 60]
    assert [x.tss_planned for x in planned.sessions] == [147.0, 81.0]
    assert planned.sessions[1].structure == INTERVALS
    assert planned.week_start == MON and planned.coach_note == "note"


def test_scaling_moves_every_duration_by_one_factor_rounded_to_five_minutes():
    week = wk(s(0, 180), s(2, 60, "threshold", "run", INTERVALS))  # 228 vs 280: factor 1.228
    planned, violations = scale_to_target(week, tgt(280))
    assert violations == []
    assert [x.duration_minutes for x in planned.sessions] == [220, 75]
    assert abs(planned.total_tss - 280) <= 28
    steps = planned.sessions[1].structure["steps"]
    # the steps scale by the session's own 75 / 60, so they still sum to its duration
    assert steps[0]["duration_seconds"] == 750
    assert [x["duration_seconds"] for x in steps[1]["steps"]] == [375, 225]
    assert steps[2]["duration_seconds"] == 1350
    assert INTERVALS["steps"][0]["duration_seconds"] == 600  # the input is not mutated


def test_the_factor_is_clamped_and_a_remaining_gap_is_a_violation():
    planned, violations = scale_to_target(wk(s(0, 120), s(2, 120)), tgt(300))  # 196: 1.53 -> 1.25
    assert [x.duration_minutes for x in planned.sessions] == [150, 150]
    assert len(violations) == 1
    assert violations[0].startswith("total TSS 245 cannot reach target 300 by scaling")
    assert "add a session" in violations[0]

    planned, violations = scale_to_target(wk(s(0, 180), s(2, 60, "threshold")), tgt(150))
    assert [x.duration_minutes for x in planned.sessions] == [135, 45]  # 0.66 -> 0.75
    assert violations[0].startswith("total TSS 171 cannot reach target 150 by scaling")
    assert "remove a session" in violations[0]


def test_race_sessions_count_but_do_not_scale():
    week = wk(s(0, 60, "race", "run"), s(2, 60))  # 100 fixed + 49 scalable vs 200
    planned, violations = scale_to_target(week, tgt(200))
    assert [x.duration_minutes for x in planned.sessions] == [60, 75]
    assert planned.sessions[0].tss_planned == 100.0
    assert violations and violations[0].startswith("total TSS 161 cannot reach target 200")


def test_rest_sessions_carry_no_load_and_are_not_scaled():
    week = wk(s(0, 180), s(1, 30, "recovery", "rest"), s(2, 60, "threshold"))
    planned, _ = scale_to_target(week, tgt(280))
    assert planned.sessions[1].duration_minutes == 30 and planned.sessions[1].tss_planned == 0.0


def test_an_empty_week_cannot_reach_the_target():
    planned, violations = scale_to_target(wk(), tgt(300))
    assert planned.sessions == []
    assert violations[0].startswith("total TSS 0 cannot reach target 300 by scaling")
    assert scale_to_target(wk(), tgt(0)) == (planned, [])  # no target, nothing to reach


def test_a_structure_without_step_durations_is_left_as_is():
    swim = {"steps": [{"name": "swim", "distance_meters": 400}]}
    week = wk(s(0, 180), s(2, 60, "threshold", "swim", swim))
    planned, _ = scale_to_target(week, tgt(280))
    assert planned.sessions[1].duration_minutes == 75
    assert planned.sessions[1].structure == swim
