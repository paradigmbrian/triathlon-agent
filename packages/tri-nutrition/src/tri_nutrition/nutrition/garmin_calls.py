"""DayTarget -> NutritionChange -> (Garmin MCP tool name, arguments). Pure."""

from __future__ import annotations

from typing import Any

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, StoredDayTarget

CALORIE_TOLERANCE = 20  # kcal; Garmin silently corrects a goal that disagrees with the macros


def consistent_calorie_goal(carbs_g: int, protein_g: int, fat_g: int, calorie_goal: int) -> int:
    from_macros = (
        C.KCAL_PER_G_CARB * carbs_g + C.KCAL_PER_G_PROTEIN * protein_g + C.KCAL_PER_G_FAT * fat_g
    )
    return calorie_goal if abs(calorie_goal - from_macros) <= CALORIE_TOLERANCE else from_macros


def day_target_change(target: DayTarget) -> NutritionChange:
    notes = f" ({', '.join(target.notes)})" if target.notes else ""
    return NutritionChange(
        op="set_day_targets",
        target_key=target.day.isoformat(),
        day=target.day,
        payload={
            "calorie_goal": target.total_kcal,
            "carbs_grams": target.carbs_g,
            "protein_grams": target.protein_g,
            "fat_grams": target.fat_g,
        },
        reason=f"{target.day_type} day, {target.session_kcal} kcal of training{notes}",
    )


def _macros(t: DayTarget) -> tuple[int, int, int, int]:
    return t.total_kcal, t.carbs_g, t.protein_g, t.fat_g


def targets_needing_write(new: list[DayTarget], existing: list[StoredDayTarget]) -> list[DayTarget]:
    by_day = {s.target.day: s for s in existing}
    out: list[DayTarget] = []
    for t in new:
        prev = by_day.get(t.day)
        if prev is not None and prev.written_to_garmin and _macros(prev.target) == _macros(t):
            continue
        out.append(t)
    return out


def to_garmin_call(change: NutritionChange) -> tuple[str, dict[str, Any]]:
    if change.op != "set_day_targets":
        raise ValueError(f"{change.op} is not a Garmin operation")
    p = change.payload
    try:
        carbs, protein, fat = int(p["carbs_grams"]), int(p["protein_grams"]), int(p["fat_grams"])
        goal = int(p["calorie_goal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"set_day_targets payload is incomplete: {exc}") from exc
    return "set_nutrition_daily_settings", {
        "date": change.day.isoformat(),
        "calorie_goal": consistent_calorie_goal(carbs, protein, fat, goal),
        "carbs_grams": carbs,
        "protein_grams": protein,
        "fat_grams": fat,
    }
