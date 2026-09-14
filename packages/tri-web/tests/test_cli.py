import json

from typer.testing import CliRunner

from tri_web.cli import app


def test_help_lists_the_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("serve", "openapi"):
        assert name in result.output


def test_openapi_prints_the_document_with_the_routes():
    result = CliRunner().invoke(app, ["openapi"])
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert "/api/coach/turns" in doc["paths"] and "/api/system/status" in doc["paths"]
    assert "ThreadView" in doc["components"]["schemas"]


def test_serve_exits_2_when_not_ready(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from tri_web import config

    config.get_web_settings.cache_clear()
    result = CliRunner().invoke(app, ["serve", "--no-live"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output
