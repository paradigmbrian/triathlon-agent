"""Wellness-agent settings: everything in tri_core.config plus the athlete's sex for
sex-specific ranges and the LangSmith project."""

from functools import lru_cache
from typing import Literal

from tri_core.config import Settings

Sex = Literal["male", "female"]


class WellnessSettings(Settings):
    tri_athlete_sex: Sex
    tri_wellness_langsmith_project: str = "tri_wellness"


@lru_cache(maxsize=1)
def get_wellness_settings() -> WellnessSettings:
    return WellnessSettings()
