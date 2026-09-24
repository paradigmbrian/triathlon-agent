import pytest
from pydantic import ValidationError

from tri_core.config import Settings


def test_defaults_when_env_empty(monkeypatch):
    for key in (
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "GARMIN_MCP_REF",
        "TP_MCP_REF",
        "TRI_MODEL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql://tri_analyze:tri_analyze@localhost:5435/")
    assert s.database_url.endswith("/tri_analyze")
    assert s.test_database_url.endswith("/tri_analyze_test")
    assert s.garmin_mcp_ref == "6c84f7ccf7ab496621357bb4e5e603ee4018fa13"
    assert s.tp_mcp_ref == "a412a84eb4f9c8f03e108a1f27beb053d83a207d"
    assert s.tri_model is None
    assert s.anthropic_api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/x")
    monkeypatch.setenv("TRI_MODEL", "claude-sonnet-5")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://u:p@h:1/x"
    assert s.tri_model == "claude-sonnet-5"


def test_model_routing_fields_read_from_env(monkeypatch):
    monkeypatch.setenv("TRI_MODEL_ANALYST", "claude-sonnet-5")
    monkeypatch.setenv("TRI_EFFORT_ANALYST", "medium")
    monkeypatch.setenv("TRI_MODEL_FALLBACKS", "")
    monkeypatch.delenv("TRI_MODEL_COACH", raising=False)
    monkeypatch.delenv("TRI_EFFORT_JUDGE", raising=False)
    s = Settings(_env_file=None)
    assert s.tri_model_analyst == "claude-sonnet-5" and s.tri_effort_analyst == "medium"
    assert s.tri_model_fallbacks == ""
    assert s.tri_model_coach is None and s.tri_effort_judge is None


def test_an_unknown_effort_is_rejected(monkeypatch):
    monkeypatch.setenv("TRI_EFFORT_COACH", "extreme")
    with pytest.raises(ValidationError, match="tri_effort_coach"):
        Settings(_env_file=None)
