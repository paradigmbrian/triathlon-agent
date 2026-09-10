"""Profile tools: save and read the athlete's NutritionProfile in the LangGraph Store.

The tools find the Store through langgraph.config.get_store(), which resolves to the store the
parent graph was compiled with, so the same tool objects work in chat and in tests.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, ValidationError

from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile

DISORDERED_EATING_FLAG = "disordered_eating"
REFERRAL_MESSAGE = (
    "A weight-loss goal is not set when disordered eating is flagged. Please talk to a doctor "
    "or a registered sports dietitian before changing intake; the profile can be saved with "
    "goal = maintain and revisited later."
)

SAVE_DESCRIPTION = """\
Commit the athlete's nutrition profile once every field is established and confirmed. Fields:
height_cm, weight_kg, body_fat_pct (null if unknown), sex (m | f), age; activity_factor for
non-exercise daily activity (1.2 desk-bound .. 1.5 on your feet all day, default 1.35);
goal (lose | maintain | gain_lean) with target_weight_kg and target_date (YYYY-MM-DD) for lose or
gain_lean; max_weekly_change_pct (default 0.5, at most 1.0); pattern (omnivore | pescatarian |
vegetarian | vegan | other); restrictions, dislikes, gi_issues, constraints, medical_flags as
lists of short strings (use the flag "disordered_eating" when the athlete's language suggests
it); meals_per_day; cooks; caffeine_mg_per_day and alcohol_drinks_per_week (null if unknown);
tracks_food; scale_days_per_week; known_sweat_rate_l_per_h (null if unknown); tested_products,
a list of {name, form (gel | chew | drink | bar | real_food | other), carbs_g, sodium_mg,
caffeine_mg} per serving; fuel_notes; unit_preference (metric | imperial). Returns JSON with
saved: true, or an error explaining what to fix. Do not call it more than once per confirmation."""


class NoArgs(BaseModel):
    pass


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def make_profile_tools() -> list[BaseTool]:
    async def save_nutrition_profile(**kwargs: Any) -> str:
        try:
            profile = NutritionProfile(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        if profile.goal == "lose" and DISORDERED_EATING_FLAG in profile.medical_flags:
            return json.dumps({"error": REFERRAL_MESSAGE})
        await S.put_profile(get_store(), profile)
        return json.dumps({"saved": True, "weight_kg": profile.weight_kg, "goal": profile.goal})

    async def read_nutrition_profile() -> str:
        """The athlete's saved nutrition profile as JSON, or {"profile": null} before intake."""
        profile = await S.get_profile(get_store())
        return json.dumps({"profile": profile.model_dump(mode="json") if profile else None})

    return [
        StructuredTool.from_function(
            coroutine=save_nutrition_profile,
            name="save_nutrition_profile",
            description=SAVE_DESCRIPTION,
            args_schema=NutritionProfile,
            handle_validation_error=_error_json,
        ),
        StructuredTool.from_function(
            coroutine=read_nutrition_profile,
            name="read_nutrition_profile",
            description=read_nutrition_profile.__doc__ or "",
            args_schema=NoArgs,
        ),
    ]
