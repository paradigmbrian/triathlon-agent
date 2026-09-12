"""Coach settings: the shared tri_core Settings plus the coach's own knobs."""

from functools import lru_cache

from tri_core.config import Settings


class CoachSettings(Settings):
    tri_coach_langsmith_project: str = "tri_coach"
    tri_coach_max_consults_per_domain: int = 2


@lru_cache(maxsize=1)
def get_coach_settings() -> CoachSettings:
    return CoachSettings()
