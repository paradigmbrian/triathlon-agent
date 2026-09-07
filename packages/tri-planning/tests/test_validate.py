from datetime import date, timedelta

from tri_planning.planning import validate
from tri_planning.planning.models import PlannedSession, PlannedWeek, TrainingGoal, WeekTarget

MON = date(2026, 9, 14)


def goal(**over) -> TrainingGoal:
    base = dict(
        goal_type="olympic",
        event_date=date(2026, 12, 13),
        weekly_hours_min=0,
        weekly_hours_max=10,
        available_days={d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
    )
    base.update(over)
    return TrainingGoal(**base)


def target(tss=300.0, hours=6.0) -> WeekTarget:
    return WeekTarget(week_start=MON, phase="build", target_tss=tss, target_hours=hours)


def session(day=0, sport="bike", minutes=60, tss=50.0, intensity="endurance", structure=None):
    return PlannedSession(
        date=MON + timedelta(days=day),
        sport=sport,
        title="s",
        description="",
        duration_minutes=minutes,
        tss_planned=tss,
        intensity=intensity,
        structure=structure,
    )


def week(*sessions) -> PlannedWeek:
    return PlannedWeek(week_start=MON, sessions=list(sessions), coach_note="")


def test_valid_week_has_no_violations():
    w = week(session(0), session(2), session(4), session(5, tss=150, minutes=180))
    assert validate.week(w, target(), goal()) == []


def test_tss_outside_ten_percent():
    w = week(session(0, tss=100), session(2, tss=100))  # 200 vs 300
    out = validate.week(w, target(), goal())
    assert any("TSS" in v and "300" in v for v in out)
    ok = week(session(0, tss=140), session(2, tss=140))  # 280, within 10 %
    assert not any("TSS" in v for v in validate.week(ok, target(), goal()))


def test_session_on_unavailable_day():
    g = goal(available_days={"mon": []})
    out = validate.week(week(session(0, tss=300)), target(), g)
    assert any("mon" in v and "unavailable" in v for v in out)


def test_sport_not_allowed_that_day():
    g = goal(available_days={"tue": ["swim"]})
    out = validate.week(week(session(1, sport="run", tss=300)), target(), g)
    assert any("run" in v and "tue" in v for v in out)


def test_rest_and_brick_rules():
    assert validate.sport_allowed("rest", [])
    assert validate.sport_allowed("brick", ["bike", "run"])
    assert not validate.sport_allowed("brick", ["bike"])
    assert validate.sport_allowed("brick", "any")


def test_consecutive_hard_days():
    w = week(session(0, intensity="threshold", tss=150), session(1, intensity="vo2", tss=150))
    out = validate.week(w, target(), goal())
    assert any("consecutive" in v for v in out)
    spaced = week(session(0, intensity="threshold", tss=150), session(2, intensity="race", tss=150))
    assert not any("consecutive" in v for v in validate.week(spaced, target(), goal()))


def test_hours_over_weekly_max():
    w = week(session(0, minutes=400, tss=150), session(2, minutes=300, tss=150))  # 11.7 h > 10
    out = validate.week(w, target(), goal())
    assert any("hours" in v and "10" in v for v in out)


def test_structure_must_match_duration_within_five_minutes():
    structure = {
        "primaryIntensityMetric": "percentOfFtp",
        "steps": [
            {"name": "wu", "duration_seconds": 600, "intensity_min": 50, "intensity_max": 60},
            {
                "type": "repetition",
                "reps": 4,
                "steps": [
                    {
                        "name": "on",
                        "duration_seconds": 300,
                        "intensity_min": 95,
                        "intensity_max": 105,
                    },
                    {
                        "name": "off",
                        "duration_seconds": 180,
                        "intensity_min": 50,
                        "intensity_max": 60,
                    },
                ],
            },
        ],
    }
    assert validate.structure_seconds(structure) == 600 + 4 * 480
    good = week(session(0, minutes=42, tss=300, structure=structure))
    assert not any("structure" in v for v in validate.week(good, target(), goal()))
    bad = week(session(0, minutes=60, tss=300, structure=structure))
    assert any("structure" in v for v in validate.week(bad, target(), goal()))


def test_session_outside_week():
    out = validate.week(week(session(7, tss=300)), target(), goal())
    assert any("outside" in v for v in out)
