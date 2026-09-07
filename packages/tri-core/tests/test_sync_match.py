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


def test_brick_matches_any_sport_once():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    pairs = match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2], tolerance_sec=100000)
    assert len(pairs) == 1 and pairs[0][0] == "w1"
