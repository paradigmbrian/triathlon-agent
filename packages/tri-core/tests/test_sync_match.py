from datetime import date, datetime

from tri_core.sync.garmin import GarminActivity
from tri_core.sync.match import match_activities


def _act(id, sport, day, dur, hour=7):
    return GarminActivity(
        id=id,
        type_key=None,
        sport=sport,
        start_time_local=datetime(2026, 9, day, hour),
        duration_sec=dur,
        distance_m=None,
        avg_hr=None,
        name=None,
        raw={},
    )


def _wo(id, sport, day, dur, completed=True, gid=None):
    return {
        "tp_workout_id": id,
        "workout_date": date(2026, 9, day),
        "sport": sport,
        "actual_duration_sec": dur,
        "completed": completed,
        "garmin_activity_id": gid,
    }


def test_matches_by_date_sport_and_closest_duration():
    workouts = [_wo("w1", "bike", 1, 5400), _wo("w2", "bike", 1, 3600), _wo("w3", "run", 1, 3600)]
    acts = [
        _act("g1", "bike", 1, 3650.0),
        _act("g2", "run", 1, 3590.0),
        _act("g3", "bike", 1, 5390.0),
    ]
    pairs = dict(match_activities(workouts, acts))
    assert pairs == {"w2": acts[0], "w3": acts[1], "w1": acts[2]}


def test_respects_tolerance():
    assert match_activities([_wo("w1", "bike", 1, 5400)], [_act("g1", "bike", 1, 3000.0)]) == []


def test_skips_planned_and_already_matched():
    workouts = [_wo("w1", "bike", 1, 5400, completed=False), _wo("w2", "bike", 1, 5400, gid="old")]
    assert match_activities(workouts, [_act("g1", "bike", 1, 5400.0)]) == []


def test_no_duration_matches_only_sole_candidate():
    a = _act("g1", "run", 2, 2400.0)
    assert match_activities([_wo("w1", "run", 2, None)], [a]) == [("w1", a)]
    two = [_wo("w1", "run", 2, None), _wo("w2", "run", 2, None)]
    assert match_activities(two, [a]) == []


def test_brick_takes_both_legs():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1), ("w1", a2)]


def test_brick_second_leg_must_bring_the_total_within_tolerance():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 3000.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1)]


def test_brick_legs_are_different_sports():
    a1, a2 = _act("g1", "bike", 3, 2400.0), _act("g2", "bike", 3, 2400.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1)]


def test_a_single_workout_is_preferred_to_a_brick_leg():
    run = _act("g1", "run", 3, 1800.0)
    workouts = [_wo("w1", "brick", 3, 5400), _wo("w2", "run", 3, 1790)]
    assert match_activities(workouts, [run]) == [("w2", run)]


def test_a_multisport_activity_fills_the_brick():
    whole, extra = _act("g1", "brick", 3, 4790.0), _act("g2", "run", 3, 600.0, hour=9)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [whole, extra]) == [("w1", whole)]


def test_second_leg_on_a_later_sync():
    first, second = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    w = _wo("w1", "brick", 3, 4800, gid="g1")
    pairs = match_activities([w], [first, second], linked={"w1": [first]})
    assert pairs == [("w1", second)]


def test_a_linked_activity_is_never_reassigned():
    a = _act("g1", "run", 2, 2400.0)
    workouts = [_wo("w1", "run", 2, 2000, gid="g1"), _wo("w2", "run", 2, 2400)]
    assert match_activities(workouts, [a], linked={"w1": [a]}) == []


def test_a_first_leg_matches_on_sport_and_day_whatever_its_duration():
    long_ride = _act("g1", "bike", 3, 10800.0)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [long_ride]) == [("w1", long_ride)]
