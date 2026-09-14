from tri_web.config import WebSettings


def test_defaults_bind_localhost_on_8321():
    s = WebSettings(_env_file=None)
    assert s.tri_web_host == "127.0.0.1" and s.tri_web_port == 8321
    assert s.tri_web_dist == "web/dist"
    assert s.tri_coach_langsmith_project == "tri_coach"  # inherits CoachSettings


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TRI_WEB_PORT", "9000")
    monkeypatch.setenv("TRI_WEB_HOST", "0.0.0.0")
    s = WebSettings(_env_file=None)
    assert s.tri_web_port == 9000 and s.tri_web_host == "0.0.0.0"
