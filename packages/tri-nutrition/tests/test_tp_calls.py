from datetime import date

import pytest

from tri_nutrition.nutrition.models import NutritionChange, RaceFuelPlan, SessionFuel
from tri_nutrition.nutrition.tp_calls import (
    race_note_change,
    race_note_title,
    result_note_id,
    session_note_change,
    to_tp_call,
)
from tri_nutrition.testing import MONDAY, race_plan_json, session_fuel_json


def test_session_note_change_and_call():
    fuel = SessionFuel.model_validate(session_fuel_json("w1", MONDAY))
    c = session_note_change(fuel)
    assert c.op == "set_session_note" and c.target_key == "w1" and c.day == MONDAY
    assert c.payload == {"workout_id": "w1", "note": fuel.note_text}
    assert "60 g/h" in c.reason
    assert to_tp_call(c) == ("tp_set_workout_note", {"workout_id": "w1", "note": fuel.note_text})
    assert result_note_id(c, {"success": True}) is None


def test_race_note_create_then_update():
    plan = RaceFuelPlan.model_validate(race_plan_json(date(2026, 10, 4)))
    title = race_note_title("City Tri", "olympic", plan.event_date)
    assert title == "Race fuel: City Tri 2026-10-04"
    assert race_note_title(None, None, plan.event_date) == "Race fuel: race 2026-10-04"
    create = race_note_change(plan, title, None)
    assert create.op == "set_race_note" and create.target_key == ""
    assert create.day == plan.event_date
    name, args = to_tp_call(create)
    assert name == "tp_create_note"
    assert args == {"date": "2026-10-04", "title": title, "description": plan.note_text}
    assert result_note_id(create, {"success": True, "note_id": 123}) == "123"
    update = race_note_change(plan, title, "123")
    name, args = to_tp_call(update)
    assert name == "tp_update_note"
    assert args == {"note_id": "123", "title": title, "description": plan.note_text}
    assert result_note_id(update, {"success": True}) == "123"


def test_to_tp_call_rejects_garmin_ops():
    c = NutritionChange(
        op="set_day_targets", target_key="2026-09-14", day=MONDAY, payload={}, reason=""
    )
    with pytest.raises(ValueError):
        to_tp_call(c)
