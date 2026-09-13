import os

import psycopg
from typer.testing import CliRunner

from tri_analyze import cli
from tri_analyze.cli import THREAD_ID, app
from tri_analyze.config import AnalyzeSettings

runner = CliRunner()


def test_help_lists_chat():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "chat" in result.output


def test_langsmith_project_is_set_on_import():
    assert (
        os.environ["LANGSMITH_PROJECT"] == cli.get_analyze_settings().tri_analyze_langsmith_project
    )
    assert THREAD_ID == "analyze"


def test_chat_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli, "get_analyze_settings", lambda: AnalyzeSettings(_env_file=None, anthropic_api_key=None)
    )
    result = runner.invoke(app, ["chat", "--no-live"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_chat_exits_2_when_the_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        cli, "get_analyze_settings", lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k")
    )

    def down(url):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("tri_core.db.connection.connect", down)
    result = runner.invoke(app, ["chat", "--no-live"])
    assert result.exit_code == 2
    assert "database unreachable: connection refused" in result.output
