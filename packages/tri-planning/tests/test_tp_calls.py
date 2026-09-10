from datetime import date

import pytest

from tri_planning.allowlist import TP_READ_TOOLS, TP_WRITE_TOOLS
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal
from tri_planning.planning.tp_calls import event_change, result_workout_id, to_tp_call

STRUCTURE = {
    "primaryIntensityMetric": "percentOfFtp",
    "steps": [
        {"name": "steady", "duration_seconds": 3600, "intensity_min": 60, "intensity_max": 70}
    ],
}


def session(**over) -> PlannedSession:
    base = dict(
        date=date(2026, 9, 14),
        sport="bike",
        title="Endurance ride",
        description="Zone 2",
        duration_minutes=60,
        tss_planned=55.0,
        intensity="endurance",
        structure=None,
    )
    base.update(over)
    return PlannedSession(**base)


def test_create_maps_sport_and_fields():
    name, args = to_tp_call(
        CalendarChange(
            op="create",
            workout_date=date(2026, 9, 14),
            workout=session(structure=STRUCTURE),
            reason="r",
        )
    )
    assert name == "tp_create_workout"
    assert args == {
        "date": "2026-09-14",
        "sport": "Bike",
        "title": "Endurance ride",
        "duration_minutes": 60,
        "description": "Zone 2",
        "tss_planned": 55.0,
        "structure": STRUCTURE,
    }


def test_create_without_structure_omits_key():
    _, args = to_tp_call(CalendarChange(op="create", workout=session(), reason="r"))
    assert "structure" not in args


def test_update_move_delete():
    _, args = to_tp_call(
        CalendarChange(op="update", tp_workout_id="9", workout=session(title="T"), reason="r")
    )
    assert args["workout_id"] == "9" and args["title"] == "T" and args["sport"] == "Bike"
    name, args = to_tp_call(
        CalendarChange(op="move", tp_workout_id="9", new_date=date(2026, 9, 16), reason="r")
    )
    assert (name, args) == ("tp_update_workout", {"workout_id": "9", "date": "2026-09-16"})
    name, args = to_tp_call(CalendarChange(op="delete", tp_workout_id="9", reason="r"))
    assert (name, args) == ("tp_delete_workout", {"workout_id": "9"})


def test_apply_plan_and_event_pass_payload():
    name, args = to_tp_call(
        CalendarChange(
            op="apply_plan", payload={"plan_id": "p1", "start_date": "2026-09-14"}, reason="r"
        )
    )
    assert (name, args) == (
        "tp_apply_training_plan",
        {"plan_id": "p1", "start_date": "2026-09-14"},
    )
    name, args = to_tp_call(
        CalendarChange(op="create_event", payload={"name": "X", "date": "2026-12-13"}, reason="r")
    )
    assert name == "tp_create_event" and args["name"] == "X"


@pytest.mark.parametrize(
    "change",
    [
        CalendarChange(op="create", reason="no workout"),
        CalendarChange(op="delete", reason="no id"),
        CalendarChange(op="move", tp_workout_id="1", reason="no new_date"),
        CalendarChange(op="apply_plan", reason="no payload"),
    ],
)
def test_missing_fields_raise(change):
    with pytest.raises(ValueError):
        to_tp_call(change)


def test_result_workout_id():
    create = CalendarChange(op="create", workout=session(), reason="r")
    assert result_workout_id(create, {"success": True, "workout_id": 123}) == "123"
    assert result_workout_id(create, {"success": True}) is None
    delete = CalendarChange(op="delete", tp_workout_id="9", reason="r")
    assert result_workout_id(delete, {"success": True}) == "9"
    assert result_workout_id(CalendarChange(op="apply_plan", payload={}, reason="r"), {}) is None


def test_event_change_from_goal():
    g = TrainingGoal(
        goal_type="olympic",
        event_name="City Tri",
        event_date=date(2026, 12, 13),
        priority="A",
        weekly_hours_min=5,
        weekly_hours_max=10,
        available_days={},
        create_tp_event=True,
    )
    c = event_change(g)
    assert c.op == "create_event"
    assert c.payload == {
        "name": "City Tri",
        "date": "2026-12-13",
        "event_type": "MultisportTriathlon",
        "priority": "A",
    }


def test_allowlists_are_disjoint_and_named_as_expected():
    assert set(TP_WRITE_TOOLS).isdisjoint(TP_READ_TOOLS)
    assert all(t.startswith("tp_") for t in TP_WRITE_TOOLS + TP_READ_TOOLS)
