import pytest
from pydantic import ValidationError

from tri_core.config import Settings, reader_url, readonly_url


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


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze",
            "postgresql://tri_reader:tri_reader@localhost:5435/tri_analyze",
        ),
        ("postgresql://localhost/x", "postgresql://tri_reader:tri_reader@localhost/x"),
        (
            "postgresql://u:p@h:1/x?sslmode=require",
            "postgresql://tri_reader:tri_reader@h:1/x?sslmode=require",
        ),
    ],
)
def test_reader_url_swaps_only_the_credentials(url, expected):
    assert reader_url(url) == expected


def test_readonly_url_derives_from_database_url_when_unset(monkeypatch):
    monkeypatch.delenv("TRI_READONLY_DATABASE_URL", raising=False)
    s = Settings(_env_file=None, database_url="postgresql://a:b@h:1/x")
    assert s.tri_readonly_database_url is None
    assert readonly_url(s) == "postgresql://tri_reader:tri_reader@h:1/x"


def test_readonly_url_prefers_the_explicit_setting(monkeypatch):
    monkeypatch.setenv("TRI_READONLY_DATABASE_URL", "postgresql://ro:pw@h:1/x")
    assert readonly_url(Settings(_env_file=None)) == "postgresql://ro:pw@h:1/x"
