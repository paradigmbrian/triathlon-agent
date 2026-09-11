import json
from datetime import date

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.testing import FakeTp
from tri_planning.tools.changes import make_change_tool
from tri_planning.tools.tp_read import make_tp_read_tools


def session():
    return PlannedSession(
        date=date(2026, 9, 22),
        sport="run",
        title="Easy run",
        description="",
        duration_minutes=40,
        tss_planned=30,
        intensity="endurance",
    )


def test_propose_returns_validated_changes():
    tool = make_change_tool()
    out = json.loads(
        tool.invoke(
            {
                "summary": "lighter Tuesday",
                "changes": [
                    {
                        "op": "move",
                        "tp_workout_id": "w9",
                        "new_date": "2026-09-24",
                        "reason": "swap with Thursday",
                    },
                    {
                        "op": "create",
                        "workout_date": "2026-09-22",
                        "workout": session().model_dump(mode="json"),
                        "reason": "fill",
                    },
                ],
            }
        )
    )
    assert out["summary"] == "lighter Tuesday" and [c["op"] for c in out["changes"]] == [
        "move",
        "create",
    ]
    assert CalendarChange.model_validate(out["changes"][0]).new_date == date(2026, 9, 24)


def test_propose_rejects_incomplete_changes_without_proposing():
    tool = make_change_tool()
    out = json.loads(
        tool.invoke({"summary": "s", "changes": [{"op": "delete", "reason": "no id"}]})
    )
    assert "error" in out and "delete" in out["error"][0] and "changes" not in out


def test_propose_rejects_ops_outside_the_review_vocabulary():
    tool = make_change_tool()
    out = json.loads(
        tool.invoke(
            {
                "summary": "s",
                "changes": [{"op": "apply_plan", "payload": {"plan_id": "p1"}, "reason": "x"}],
            }
        )
    )
    assert "error" in out and "apply_plan" in out["error"] and "changes" not in out


def test_propose_schema_hides_apply_ops_and_payload():
    schema = json.dumps(make_change_tool().args_schema.model_json_schema())
    assert "apply_plan" not in schema and "create_event" not in schema
    assert "payload" not in schema


async def test_tp_get_workouts_wrapper():
    (tool,) = make_tp_read_tools(
        FakeTp(responses={"tp_get_workouts": {"workouts": [{"id": "1"}], "count": 1}})
    )
    assert '"id": "1"' in await tool.ainvoke({"start_date": "2026-09-21", "end_date": "2026-09-27"})
    (tool,) = make_tp_read_tools(None)
    assert "unavailable" in await tool.ainvoke(
        {"start_date": "2026-09-21", "end_date": "2026-09-27"}
    )
