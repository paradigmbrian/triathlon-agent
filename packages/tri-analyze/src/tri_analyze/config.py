"""Analyst settings: everything in tri_core.config plus this agent's LangSmith project."""

from functools import lru_cache

from tri_core.config import Settings


class AnalyzeSettings(Settings):
    tri_analyze_langsmith_project: str = "tri_analyze"


@lru_cache(maxsize=1)
def get_analyze_settings() -> AnalyzeSettings:
    return AnalyzeSettings()
