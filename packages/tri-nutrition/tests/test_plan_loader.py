from datetime import timedelta

import pytest

from tri_nutrition import plan_loader as L
from tri_nutrition.testing import MONDAY, seed_ftp, seed_goal_and_plan, seed_workouts, session_json

pytestmark = pytest.mark.db


@pytest.fixture
def pdb(db):
    if db.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied to the test database")
    return db


def test_intensity_from_if():
    assert L.intensity_from_if(None) == "endurance"
    assert L.intensity_from_if(0.7) == "endurance"
    assert L.intensity_from_if(0.8) == "tempo"
    assert L.intensity_from_if(0.9) == "threshold"
    assert L.intensity_from_if(1.0) == "vo2"


def test_session_from_workout_maps_fields_and_skips_unknown_sports():
    row = {
        "tp_workout_id": "w1",
        "workout_date": MONDAY,
        "sport": "run",
        "title": "Tempo run",
        "planned_duration_sec": 3600,
        "planned_distance_m": 12000,
        "planned_tss": 70,
        "planned_if": 0.82,
    }
    s = L.session_from_workout(row)
    assert s is not None
    assert (s.sport, s.duration_min, s.distance_km, s.intensity, s.tp_workout_id) == (
        "run",
        60,
        12.0,
        "tempo",
        "w1",
    )
    assert L.session_from_workout({**row, "sport": "rest"}) is None
    assert L.session_from_workout({**row, "planned_duration_sec": None}) is None


def test_sessions_from_designed_filters_to_window():
    designed = {
        "week_start": MONDAY.isoformat(),
        "coach_note": "",
        "sessions": [
            session_json(MONDAY, "bike", 90, "endurance", 80),
            session_json(MONDAY + timedelta(days=3), "run", 50, "threshold", 60),
            session_json(MONDAY + timedelta(days=6), "brick", 150, "endurance", 120),
        ],
    }
    out = L.sessions_from_designed(designed, MONDAY, MONDAY + timedelta(days=4))
    assert [(s.sport, s.duration_min, s.planned_tss) for s in out] == [
        ("bike", 90, 80),
        ("run", 50, 60),
    ]
    assert out[1].intensity == "threshold" and out[1].tp_workout_id is None


def test_load_horizon_from_plan(pdb):
    seed_ftp(pdb, 250)
    weeks = [
        (
            "build",
            [session_json(MONDAY, "bike", 90), session_json(MONDAY + timedelta(days=2), "run", 40)],
        ),
        ("peak", [session_json(MONDAY + timedelta(days=7), "swim", 45)]),
        ("taper", None),
    ]
    seed_goal_and_plan(pdb, MONDAY, weeks, event_date=MONDAY + timedelta(days=20))
    sessions, ctx = L.load_horizon(pdb, MONDAY + timedelta(days=1), 14)
    assert ctx.source == "plan" and ctx.ftp_watts == 250
    assert ctx.event_date == MONDAY + timedelta(days=20) and ctx.event_priority == "A"
    assert ctx.phases == {
        MONDAY: "build",
        MONDAY + timedelta(days=7): "peak",
        MONDAY + timedelta(days=14): "taper",
    }
    assert [(s.day, s.sport) for s in sessions] == [
        (MONDAY + timedelta(days=2), "run"),
        (MONDAY + timedelta(days=7), "swim"),
    ]


def test_load_horizon_from_tp_calendar_when_no_designed_weeks(pdb):
    seed_goal_and_plan(pdb, MONDAY, [("base", None), ("base", None)])
    seed_workouts(
        pdb,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 5400,
                "planned_tss": 80,
            },
            {
                "tp_workout_id": "w2",
                "workout_date": MONDAY + timedelta(days=1),
                "sport": "run",
                "planned_duration_sec": 2400,
                "completed": True,
            },
            {
                "tp_workout_id": "w3",
                "workout_date": MONDAY + timedelta(days=30),
                "sport": "run",
                "planned_duration_sec": 2400,
            },
        ],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert ctx.source == "tp_calendar" and ctx.phases[MONDAY] == "base"
    assert [s.tp_workout_id for s in sessions] == ["w1"]  # completed and out-of-window rows dropped


def test_load_horizon_keeps_todays_completed_workout(pdb):
    # an afternoon regenerate must not drop the session already done today and lower the target
    seed_goal_and_plan(pdb, MONDAY, [("base", None)])
    seed_workouts(
        pdb,
        [
            {
                "tp_workout_id": "done-today",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 5400,
                "completed": True,
            },
            {
                "tp_workout_id": "done-later",
                "workout_date": MONDAY + timedelta(days=1),
                "sport": "run",
                "planned_duration_sec": 2400,
                "completed": True,
            },
            {
                "tp_workout_id": "w3",
                "workout_date": MONDAY + timedelta(days=2),
                "sport": "run",
                "planned_duration_sec": 2400,
            },
        ],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert ctx.source == "tp_calendar"
    assert [s.tp_workout_id for s in sessions] == ["done-today", "w3"]


def test_load_horizon_profile_hours_fallback(pdb):
    seed_goal_and_plan(pdb, MONDAY, [("base", None)], weekly_hours=9)
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert sessions == [] and ctx.source == "profile_hours" and ctx.weekly_hours == 9


def test_load_horizon_nothing_at_all(pdb):
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert sessions == [] and ctx.source == "profile_hours" and ctx.weekly_hours is None
    assert ctx.phases == {} and ctx.event_date is None


def test_attach_workout_ids_matches_day_and_sport_then_title():
    a = session_json(MONDAY, "bike", 90)
    b = session_json(MONDAY, "bike", 30)
    b["title"] = "Openers"
    designed = {"week_start": MONDAY.isoformat(), "coach_note": "", "sessions": [a, b]}
    sessions = L.sessions_from_designed(designed, MONDAY, MONDAY)
    rows = [
        {"tp_workout_id": "w2", "workout_date": MONDAY, "sport": "bike", "title": "Openers"},
        {"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "title": "bike 90"},
        {"tp_workout_id": "w9", "workout_date": MONDAY, "sport": "run", "title": "x"},
    ]
    out = L.attach_workout_ids(sessions, rows)
    assert [(s.title, s.tp_workout_id) for s in out] == [("bike 90", "w1"), ("Openers", "w2")]
    kept = sessions[0].model_copy(update={"tp_workout_id": "kept"})
    assert L.attach_workout_ids([kept], rows)[0].tp_workout_id == "kept"
    assert L.attach_workout_ids(sessions, [])[0].tp_workout_id is None


def test_load_horizon_attaches_ids_and_goal_fields(pdb):
    seed_goal_and_plan(
        pdb,
        MONDAY,
        [("build", [session_json(MONDAY, "bike", 90)])],
        event_date=MONDAY + timedelta(days=10),
    )
    seed_workouts(
        pdb,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 5400,
                "title": "bike 90",
            }
        ],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 7)
    assert ctx.source == "plan" and sessions[0].tp_workout_id == "w1"
    assert ctx.event_name == "City Tri" and ctx.goal_type == "olympic"
