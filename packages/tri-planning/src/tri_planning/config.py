"""Planning-agent settings: everything in tri_core.config plus the planning knobs."""

from functools import lru_cache

from tri_core.config import Settings


class PlanningSettings(Settings):
    tri_planning_horizon_weeks: int = 3
    tri_planning_langsmith_project: str = "tri-planning"


@lru_cache(maxsize=1)
def get_planning_settings() -> PlanningSettings:
    return PlanningSettings()
