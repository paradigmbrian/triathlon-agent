from tri_analyze.config import AnalyzeSettings, get_analyze_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_ANALYZE_LANGSMITH_PROJECT", raising=False)
    s = AnalyzeSettings(_env_file=None)
    assert s.tri_analyze_langsmith_project == "tri_analyze"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_ANALYZE_LANGSMITH_PROJECT", "analyst-dev")
    s = AnalyzeSettings(_env_file=None)
    assert s.tri_analyze_langsmith_project == "analyst-dev"


def test_get_analyze_settings_is_cached():
    get_analyze_settings.cache_clear()
    assert get_analyze_settings() is get_analyze_settings()
    get_analyze_settings.cache_clear()
