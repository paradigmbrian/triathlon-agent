"""Coach settings: the shared tri_core Settings plus the coach's own knobs."""

from functools import lru_cache

from pydantic import field_validator

from tri_core.config import Settings
from tri_wellness.config import Sex


class CoachSettings(Settings):
    tri_coach_langsmith_project: str = "tri_coach"
    tri_coach_max_consults_per_domain: int = 2
    # Optional here (required by tri-wellness itself): unset means no wellness consult.
    tri_athlete_sex: Sex | None = None

    @field_validator("tri_athlete_sex", mode="before")
    @classmethod
    def _blank_sex_is_unset(cls, v: object) -> object:
        # A copied .env can carry TRI_ATHLETE_SEX= with nothing after it; that must mean
        # unset, not a validation error.
        return None if v == "" else v


@lru_cache(maxsize=1)
def get_coach_settings() -> CoachSettings:
    return CoachSettings()
