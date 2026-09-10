"""Nutrition-agent settings: everything in tri_core.config plus the nutrition knobs."""

from functools import lru_cache

from tri_core.config import Settings


class NutritionSettings(Settings):
    tri_nutrition_horizon_days: int = 14
    tri_nutrition_langsmith_project: str = "tri_nutrition"


@lru_cache(maxsize=1)
def get_nutrition_settings() -> NutritionSettings:
    return NutritionSettings()
