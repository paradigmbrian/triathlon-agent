"""Application settings loaded from environment and .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze"
    test_database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test"

    garmin_email: str | None = None
    garmin_password: str | None = None
    tp_auth_cookie: str | None = None

    garmin_mcp_ref: str = "e8554bcd761a4494dc12a98461224bb3dcf1fbc5"
    tp_mcp_ref: str = "a412a84eb4f9c8f03e108a1f27beb053d83a207d"

    tri_model: str = "claude-opus-5"

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "tri_analyze"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
