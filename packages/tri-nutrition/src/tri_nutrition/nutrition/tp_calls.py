"""SessionFuel / RaceFuelPlan -> NutritionChange -> (TrainingPeaks MCP tool name, arguments). Pure.

Session notes go to the workout's private note (tp_set_workout_note). If Brian finds that field
too hidden in the TrainingPeaks apps (spec §15 item 3), switch `to_tp_call` to
("tp_update_workout", {"workout_id", "description"}); nothing else changes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_nutrition.nutrition.models import NutritionChange, RaceFuelPlan, SessionFuel


def race_note_title(event_name: str | None, goal_type: str | None, event_date: date) -> str:
    return f"Race fuel: {event_name or goal_type or 'race'} {event_date.isoformat()}"


def session_note_change(fuel: SessionFuel) -> NutritionChange:
    caffeine = f", {fuel.caffeine_mg} mg caffeine" if fuel.caffeine_mg else ""
    return NutritionChange(
        op="set_session_note",
        target_key=fuel.tp_workout_id,
        day=fuel.day,
        payload={"workout_id": fuel.tp_workout_id, "note": fuel.note_text},
        reason=(
            f"{fuel.carbs_g_per_h} g/h carbs, {fuel.fluid_ml_per_h} ml/h, "
            f"{fuel.sodium_mg_per_h} mg/h sodium{caffeine}; {', '.join(fuel.products)}"
        ),
    )


def race_note_change(plan: RaceFuelPlan, title: str, note_id: str | None) -> NutritionChange:
    return NutritionChange(
        op="set_race_note",
        target_key=note_id or "",
        day=plan.event_date,
        payload={
            "date": plan.event_date.isoformat(),
            "title": title,
            "description": plan.note_text,
        },
        reason=("update" if note_id else "create") + f" race fuel note for {plan.event_date}",
    )


def to_tp_call(change: NutritionChange) -> tuple[str, dict[str, Any]]:
    p = change.payload
    if change.op == "set_session_note":
        return "tp_set_workout_note", {"workout_id": str(p["workout_id"]), "note": str(p["note"])}
    if change.op == "set_race_note":
        if change.target_key:
            return "tp_update_note", {
                "note_id": change.target_key,
                "title": str(p["title"]),
                "description": str(p["description"]),
            }
        return "tp_create_note", {
            "date": str(p["date"]),
            "title": str(p["title"]),
            "description": str(p["description"]),
        }
    raise ValueError(f"{change.op} is not a TrainingPeaks operation")


def result_note_id(change: NutritionChange, result: Any) -> str | None:
    if change.op != "set_race_note":
        return None
    if change.target_key:
        return change.target_key
    nid = result.get("note_id") if isinstance(result, dict) else None
    return str(nid) if nid is not None else None
