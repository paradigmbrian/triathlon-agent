from tri_core.config import Settings


def test_defaults_when_env_empty(monkeypatch):
    for key in ("DATABASE_URL", "TEST_DATABASE_URL", "GARMIN_MCP_REF", "TP_MCP_REF", "TRI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql://tri_analyze:tri_analyze@localhost:5435/")
    assert s.database_url.endswith("/tri_analyze")
    assert s.test_database_url.endswith("/tri_analyze_test")
    assert s.garmin_mcp_ref == "e8554bcd761a4494dc12a98461224bb3dcf1fbc5"
    assert s.tp_mcp_ref == "a412a84eb4f9c8f03e108a1f27beb053d83a207d"
    assert s.tri_model == "claude-opus-5"
    assert s.anthropic_api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/x")
    monkeypatch.setenv("TRI_MODEL", "claude-sonnet-5")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://u:p@h:1/x"
    assert s.tri_model == "claude-sonnet-5"
