import json

from tri_nutrition.allowlist import (
    GARMIN_CHECKIN_TOOLS,
    GARMIN_INTAKE_TOOLS,
    GARMIN_SERVER_TOOLS,
    GARMIN_WRITE_TOOLS,
)
from tri_nutrition.testing import MONDAY, FakeGarmin
from tri_nutrition.tools.garmin import make_garmin_read_tools, parse_body_composition

BODY = {
    "startDate": "2026-08-27",
    "endDate": "2026-09-09",
    "dateWeightList": [
        {"calendarDate": "2026-09-01", "weight": 81510.0, "bodyFat": 21.7, "muscleMass": 33409},
        {"calendarDate": "2026-08-29", "weight": 81900.0, "bodyFat": 22.0, "muscleMass": 33200},
    ],
    "totalAverage": {"weight": 81705.0},
}


def test_allowlists():
    for name in GARMIN_INTAKE_TOOLS + GARMIN_CHECKIN_TOOLS:
        assert name.startswith("get_") and name in GARMIN_SERVER_TOOLS
    assert GARMIN_WRITE_TOOLS == ["set_nutrition_daily_settings"]
    assert "set_nutrition_daily_settings" in GARMIN_SERVER_TOOLS
    assert "get_nutrition_daily_meals" not in GARMIN_SERVER_TOOLS


def test_parse_body_composition_orders_and_converts():
    rows = parse_body_composition(BODY)
    assert [r["date"] for r in rows] == ["2026-08-29", "2026-09-01"]
    assert rows[-1] == {
        "date": "2026-09-01",
        "weight_kg": 81.5,
        "body_fat_pct": 21.7,
        "muscle_mass_kg": 33.4,
    }
    assert parse_body_composition(None) == []


async def test_read_tools_call_server_and_trim():
    profile = {
        "id": 1,
        "userData": {
            "gender": "MALE",
            "weight": 81510.0,
            "height": 180.34,
            "birthDate": "1986-06-11",
            "measurementSystem": "statute_us",
        },
    }
    settings = {"calorieGoal": 2500, "macroGoals": {"carbs": 300, "protein": 150, "fat": 70}}
    g = FakeGarmin(
        responses={
            "get_user_profile": profile,
            "get_body_composition": BODY,
            "get_nutrition_daily_settings": settings,
        }
    )
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    assert set(tools) == {
        "read_garmin_profile",
        "read_body_composition",
        "read_garmin_nutrition_settings",
        "read_hydration",
    }
    p = json.loads(await tools["read_garmin_profile"].ainvoke({}))
    assert p == {
        "sex": "m",
        "weight_kg": 81.5,
        "height_cm": 180.3,
        "age": 40,
        "unit_preference": "imperial",
    }
    b = json.loads(await tools["read_body_composition"].ainvoke({"days": 14}))
    assert b[-1]["weight_kg"] == 81.5
    assert g.calls[-1] == (
        "get_body_composition",
        {"start_date": "2026-08-31", "end_date": "2026-09-14"},
    )
    s = json.loads(await tools["read_garmin_nutrition_settings"].ainvoke({}))
    assert s == {"calorie_goal": 2500, "carbs_g": 300, "protein_g": 150, "fat_g": 70}
    assert g.calls[-1] == ("get_nutrition_daily_settings", {"date": "2026-09-14"})


async def test_read_tools_without_server_and_on_error():
    tools = {t.name: t for t in make_garmin_read_tools(None, lambda: MONDAY)}
    assert "unavailable" in json.loads(await tools["read_garmin_profile"].ainvoke({}))["error"]
    g = FakeGarmin(fail_on_call=1)
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    out = json.loads(await tools["read_body_composition"].ainvoke({"days": 7}))
    assert "boom" in out["error"]
    empty = FakeGarmin(responses={"get_nutrition_daily_settings": {"macroGoals": {}}})
    tools = {t.name: t for t in make_garmin_read_tools(empty, lambda: MONDAY)}
    s = json.loads(await tools["read_garmin_nutrition_settings"].ainvoke({}))
    assert s == {"calorie_goal": None, "carbs_g": None, "protein_g": None, "fat_g": None}


def test_parse_food_log_from_fixture():
    import json as _json
    from pathlib import Path

    from tri_nutrition.tools.garmin import parse_food_log, parse_hydration

    fixture = Path(__file__).parent / "fixtures" / "mcp" / "get_nutrition_daily_food_log.json"
    payload = _json.loads(fixture.read_text())["result"]
    out = parse_food_log(payload)
    assert out["logged"] is True
    assert (out["kcal"], out["carbs_g"], out["protein_g"], out["fat_g"]) == (213, 2, 18, 15)
    assert out["meals"]["breakfast"] == 213 and out["items"] == ["Eggs (3 large)"]
    assert parse_food_log("No food logged") == {
        "logged": False,
        "kcal": 0,
        "carbs_g": 0,
        "protein_g": 0,
        "fat_g": 0,
        "meals": {},
        "items": [],
    }
    hyd = parse_hydration(
        {
            "calendarDate": "2026-09-10",
            "valueInML": 1500.4,
            "goalInML": 2839.056,
            "sweatLossInML": None,
        }
    )
    assert hyd == {"date": "2026-09-10", "intake_ml": 1500, "goal_ml": 2839, "sweat_loss_ml": None}
    assert parse_hydration(None) == {
        "date": None,
        "intake_ml": None,
        "goal_ml": None,
        "sweat_loss_ml": None,
    }


async def test_read_hydration_walks_back_from_yesterday_and_only_filters():
    from tri_nutrition.allowlist import CHECKIN_READ_TOOLS, INTAKE_READ_TOOLS

    g = FakeGarmin(
        responses={
            "get_hydration_data": lambda a: {
                "calendarDate": a["date"],
                "valueInML": 1000.0,
                "goalInML": 2500.0,
                "sweatLossInML": None,
            }
        }
    )
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    rows = json.loads(await tools["read_hydration"].ainvoke({"days": 3}))
    assert [r["date"] for r in rows] == ["2026-09-11", "2026-09-12", "2026-09-13"]
    assert rows[0]["intake_ml"] == 1000
    assert [c[1]["date"] for c in g.calls] == ["2026-09-11", "2026-09-12", "2026-09-13"]
    intake = make_garmin_read_tools(g, lambda: MONDAY, only=INTAKE_READ_TOOLS)
    assert sorted(t.name for t in intake) == sorted(INTAKE_READ_TOOLS)
    checkin = make_garmin_read_tools(g, lambda: MONDAY, only=CHECKIN_READ_TOOLS)
    assert sorted(t.name for t in checkin) == sorted(CHECKIN_READ_TOOLS)
    down = {t.name: t for t in make_garmin_read_tools(None, lambda: MONDAY)}
    assert json.loads(await down["read_hydration"].ainvoke({}))["error"]
