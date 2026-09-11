"""Test doubles for the nutrition graph: a fake Garmin caller, a no-commit connection wrapper,
a canned profile, and SQL seeds for planning's tables. Imported by tests only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from psycopg.types.json import Jsonb

from tri_core.db.models import AthleteProfileRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_athlete_profile, upsert_workouts
from tri_core.mcp.client import McpToolError

MONDAY = date(2026, 9, 14)

PROFILE_ARGS: dict[str, Any] = {
    "height_cm": 180,
    "weight_kg": 80,
    "body_fat_pct": 18,
    "sex": "m",
    "age": 40,
    "activity_factor": 1.35,
    "goal": "maintain",
    "target_weight_kg": None,
    "target_date": None,
    "max_weekly_change_pct": 0.5,
    "pattern": "omnivore",
    "restrictions": [],
    "dislikes": ["liver"],
    "gi_issues": [],
    "meals_per_day": 3,
    "cooks": True,
    "caffeine_mg_per_day": 200,
    "alcohol_drinks_per_week": 2,
    "tracks_food": True,
    "scale_days_per_week": 3,
    "known_sweat_rate_l_per_h": None,
    "tested_products": [{"name": "Gel", "form": "gel", "carbs_g": 25, "sodium_mg": 50}],
    "fuel_notes": [],
    "unit_preference": "metric",
    "constraints": [],
    "medical_flags": [],
}


class FakeGarmin:
    """Records every call; answers like the real server. `fail_on_call` raises on the nth call."""

    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        a = dict(args or {})
        self.calls.append((tool, a))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "Error updating nutrition settings: boom")
        if tool in self.responses:
            r = self.responses[tool]
            return r(a) if callable(r) else r
        if tool == "set_nutrition_daily_settings":
            return {
                "status": "updated",
                "date": a.get("date"),
                "calorie_goal": a.get("calorie_goal"),
                "carbs_grams": a.get("carbs_grams"),
                "fat_grams": a.get("fat_grams"),
                "protein_grams": a.get("protein_grams"),
            }
        if tool == "get_nutrition_daily_settings":
            return {"weightChangeType": "NO_GOAL", "macroGoals": {}}
        if tool == "get_hydration_data":
            return {
                "calendarDate": a.get("date"),
                "valueInML": 1500.0,
                "goalInML": 2800.0,
                "sweatLossInML": None,
            }
        if tool == "get_nutrition_daily_food_log":
            return {
                "mealDate": a.get("date"),
                "dailyNutritionContent": {
                    "calories": 2400,
                    "carbs": 300.0,
                    "protein": 150.0,
                    "fat": 70.0,
                },
                "mealDetails": [
                    {
                        "meal": {"mealName": "BREAKFAST"},
                        "mealNutritionContent": {
                            "calories": 600,
                            "carbs": 80.0,
                            "protein": 30.0,
                            "fat": 15.0,
                        },
                        "loggedFoods": [{"foodMetaData": {"foodName": "Oats"}, "servingQty": 1.0}],
                    }
                ],
            }
        return None


class NoCommit:
    """The rolled-back test connection; commit/close are no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def session_json(
    day: date, sport: str = "bike", minutes: int = 60, intensity: str = "endurance", tss: float = 50
) -> dict[str, Any]:
    """One PlannedSession as planning stores it inside plan_weeks.designed."""
    return {
        "date": day.isoformat(),
        "sport": sport,
        "title": f"{sport} {minutes}",
        "description": "",
        "duration_minutes": minutes,
        "tss_planned": tss,
        "intensity": intensity,
    }


def seed_goal_and_plan(
    conn: Conn,
    monday: date,
    weeks: list[tuple[str, list[dict[str, Any]] | None]],
    *,
    event_date: date | None = None,
    priority: str = "A",
    weekly_hours: float = 8,
) -> int:
    """Insert an active goal, plan and one plan_weeks row per (phase, sessions) tuple.
    A week with sessions=None has designed = null."""
    goal = conn.execute(
        "insert into training_goals (goal_type, event_name, event_date, priority, "
        "weekly_hours_min, weekly_hours_max, available_days) "
        "values ('olympic', 'City Tri', %s, %s, %s, %s, '{}') returning id",
        (event_date, priority, weekly_hours - 2, weekly_hours),
    ).fetchone()
    assert goal is not None
    plan = conn.execute(
        "insert into training_plans (goal_id, source, start_date, end_date, targets) "
        "values (%s, 'generated', %s, %s, '[]') returning id",
        (goal["id"], monday, monday + timedelta(weeks=len(weeks), days=-1)),
    ).fetchone()
    assert plan is not None
    for i, (phase, sessions) in enumerate(weeks):
        week_start = monday + timedelta(weeks=i)
        designed = (
            Jsonb({"week_start": week_start.isoformat(), "sessions": sessions, "coach_note": ""})
            if sessions is not None
            else None
        )
        conn.execute(
            "insert into plan_weeks (plan_id, week_start, phase, designed) values (%s, %s, %s, %s)",
            (plan["id"], week_start, phase, designed),
        )
    return int(plan["id"])


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, planned_duration_sec, and optional
    planned_distance_m, planned_tss, planned_if, completed."""
    out: list[WorkoutRow] = []
    for r in rows:
        out.append(
            WorkoutRow(
                tp_workout_id=r["tp_workout_id"],
                workout_date=r["workout_date"],
                sport=r["sport"],
                sport_raw=None,
                title=r.get("title", ""),
                description=None,
                completed=bool(r.get("completed", False)),
                planned_duration_sec=r.get("planned_duration_sec"),
                planned_distance_m=r.get("planned_distance_m"),
                planned_tss=r.get("planned_tss"),
                planned_if=r.get("planned_if"),
                actual_duration_sec=None,
                actual_distance_m=None,
                actual_tss=None,
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=r.get("calories"),
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        )
    upsert_workouts(conn, out)


def seed_ftp(conn: Conn, ftp_watts: int) -> None:
    upsert_athlete_profile(
        conn,
        AthleteProfileRow(
            tp_athlete_id=None,
            ftp_watts=ftp_watts,
            run_threshold_pace_sec_per_km=None,
            swim_css_sec_per_100m=None,
            lthr_bpm=None,
            max_hr_bpm=None,
            hr_zones=None,
            power_zones=None,
            pace_zones=None,
            weight_kg=None,
            raw={},
        ),
    )


class FakeTp:
    """Records every call; answers like the TrainingPeaks server. `fail_on_call` raises on the
    nth call. Override any tool's answer through `responses`."""

    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        a = dict(args or {})
        self.calls.append((tool, a))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "API_ERROR: boom")
        if tool in self.responses:
            return self.responses[tool]
        if tool == "tp_set_workout_note":
            return {"success": True, "note": a.get("note")}
        if tool == "tp_get_workout_note":
            return {"note": ""}
        if tool == "tp_create_note":
            return {
                "success": True,
                "note_id": f"n{len(self.calls)}",
                "title": a.get("title"),
                "date": a.get("date"),
            }
        if tool == "tp_update_note":
            return {"success": True, "note_id": a.get("note_id")}
        if tool == "tp_get_note":
            return {"note": {"id": a.get("note_id"), "title": "", "description": "", "date": ""}}
        if tool == "tp_list_notes":
            return {"notes": [], "count": 0}
        return {}


def session_fuel_json(workout_id: str, day: date, **over: Any) -> dict[str, Any]:
    """A SessionFuel as the model would return it, valid for PROFILE_ARGS's library."""
    base: dict[str, Any] = {
        "tp_workout_id": workout_id,
        "day": day.isoformat(),
        "pre": "Oats and a banana 2 h before.",
        "carbs_g_per_h": 60,
        "fluid_ml_per_h": 600,
        "sodium_mg_per_h": 500,
        "caffeine_mg": None,
        "products": ["Gel"],
        "post": "Shake within 30 min, then a meal.",
        "gut_training": False,
        "note_text": "Fuel: 60 g/h (2 Gel per hour), 600 ml/h, 500 mg sodium/h.",
    }
    base.update(over)
    return base


def race_plan_json(event_date: date, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_date": event_date.isoformat(),
        "timeline": [
            {
                "offset_min": -180,
                "leg": "pre",
                "what": "Oats, banana, coffee",
                "carbs_g": 120,
                "fluid_ml": 500,
                "sodium_mg": 300,
                "caffeine_mg": 100,
                "products": [],
            },
            {
                "offset_min": 20,
                "leg": "bike",
                "what": "Gel",
                "carbs_g": 25,
                "fluid_ml": 250,
                "sodium_mg": 200,
                "caffeine_mg": 0,
                "products": ["Gel"],
            },
            {
                "offset_min": 130,
                "leg": "run",
                "what": "Gel",
                "carbs_g": 25,
                "fluid_ml": 200,
                "sodium_mg": 150,
                "caffeine_mg": 0,
                "products": ["Gel"],
            },
        ],
        "totals_per_h": {
            "bike_carbs": 60,
            "run_carbs": 50,
            "bike_fluid": 700,
            "run_fluid": 500,
            "bike_sodium": 600,
            "run_sodium": 400,
        },
        "contingencies": ["If the gut turns: water and one gel per 30 min."],
        "note_text": "Race fuel plan: pre-race meal 3 h out; 60 g/h bike, 50 g/h run.",
    }
    base.update(over)
    return base


class _ToolState(TypedDict, total=False):
    out: str


async def call_tool_in_graph(store: BaseStore, tool: BaseTool, args: dict[str, Any]) -> str:
    """Run one tool inside a compiled graph so langgraph.config.get_store() resolves to `store`."""

    async def node(state: _ToolState) -> dict[str, Any]:
        return {"out": await tool.ainvoke(args)}

    g: StateGraph[_ToolState] = StateGraph(_ToolState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    result = await g.compile(store=store).ainvoke({})
    return str(result["out"])
