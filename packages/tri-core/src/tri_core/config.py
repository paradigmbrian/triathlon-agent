"""Application settings loaded from environment and .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze"
    test_database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test"

    garmin_email: str | None = None
    garmin_password: str | None = None
    tp_auth_cookie: str | None = None

    garmin_mcp_ref: str = "6c84f7ccf7ab496621357bb4e5e603ee4018fa13"
    tp_mcp_ref: str = "a412a84eb4f9c8f03e108a1f27beb053d83a207d"

    # Model routing (tri_core.llm). TRI_MODEL pins every role; TRI_MODEL_<ROLE> and
    # TRI_EFFORT_<ROLE> override one role; TRI_MODEL_FALLBACKS is comma-separated, "" disables it.
    tri_model: str | None = None
    tri_model_fallbacks: str | None = None
    tri_model_coach: str | None = None
    tri_effort_coach: Effort | None = None
    tri_model_analyst: str | None = None
    tri_effort_analyst: Effort | None = None
    tri_model_wellness_chat: str | None = None
    tri_effort_wellness_chat: Effort | None = None
    tri_model_planning_agent: str | None = None
    tri_effort_planning_agent: Effort | None = None
    tri_model_planning_design: str | None = None
    tri_effort_planning_design: Effort | None = None
    tri_model_nutrition_agent: str | None = None
    tri_effort_nutrition_agent: Effort | None = None
    tri_model_nutrition_fuel: str | None = None
    tri_effort_nutrition_fuel: Effort | None = None
    tri_model_lab_extract: str | None = None
    tri_effort_lab_extract: Effort | None = None
    tri_model_lab_report: str | None = None
    tri_effort_lab_report: Effort | None = None
    tri_model_judge: str | None = None
    tri_effort_judge: Effort | None = None

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "tri_analyze"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
