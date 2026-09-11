"""Opt-in: creates one workout 400 days out on the real calendar, updates it, deletes it."""

from datetime import date, timedelta

import pytest

from tri_core.config import Settings
from tri_core.mcp.client import McpToolClient
from tri_core.mcp.servers import trainingpeaks_spec
from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call

pytestmark = pytest.mark.live


async def test_create_update_delete_roundtrip():
    day = date.today() + timedelta(days=400)
    session = PlannedSession(
        date=day,
        sport="bike",
        title="tri-planning live test",
        description="delete me",
        duration_minutes=30,
        tss_planned=20,
        intensity="recovery",
    )
    async with McpToolClient(trainingpeaks_spec(Settings())) as tp:
        name, args = to_tp_call(
            CalendarChange(op="create", workout_date=day, workout=session, reason="test")
        )
        created = await tp.call_json(name, args)
        wid = result_workout_id(CalendarChange(op="create", workout=session, reason="t"), created)
        assert wid, created
        try:
            name, args = to_tp_call(
                CalendarChange(
                    op="update",
                    tp_workout_id=wid,
                    workout=session.model_copy(
                        update={"title": "tri-planning live test (updated)"}
                    ),
                    reason="t",
                )
            )
            assert (await tp.call_json(name, args))["success"] is True
            listed = await tp.call_json(
                "tp_get_workouts", {"start_date": day.isoformat(), "end_date": day.isoformat()}
            )
            assert any(w["id"] == wid and "updated" in w["title"] for w in listed["workouts"])
        finally:
            name, args = to_tp_call(CalendarChange(op="delete", tp_workout_id=wid, reason="t"))
            assert (await tp.call_json(name, args))["success"] is True
        listed = await tp.call_json(
            "tp_get_workouts", {"start_date": day.isoformat(), "end_date": day.isoformat()}
        )
        assert all(w["id"] != wid for w in listed["workouts"])
