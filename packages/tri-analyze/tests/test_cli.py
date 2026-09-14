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


def test_langsmith_project_is_set_on_import(monkeypatch):
    import importlib

    from tri_analyze.config import get_analyze_settings

    monkeypatch.setenv("LANGSMITH_PROJECT", "something-else")  # restored on teardown
    monkeypatch.setenv("TRI_ANALYZE_LANGSMITH_PROJECT", "analyst-import-test")
    get_analyze_settings.cache_clear()
    try:
        importlib.reload(cli)
        assert os.environ["LANGSMITH_PROJECT"] == "analyst-import-test"
    finally:
        get_analyze_settings.cache_clear()
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


def test_cmd_sync_reports_a_down_database_instead_of_raising(monkeypatch):
    monkeypatch.setattr(
        cli, "get_analyze_settings", lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k")
    )

    class _FakeCursor:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class _FakeConnection:
        def execute(self, *args, **kwargs):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("tri_core.db.connection.connect", lambda url: _FakeConnection())

    async def down(*args, **kwargs):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr("tri_core.sync.runner.run_sync", down)

    lines = iter(["/sync", None])

    async def fake_read():
        return next(lines)

    monkeypatch.setattr(cli, "_read", fake_read)

    result = runner.invoke(app, ["chat", "--no-live"])
    assert result.exit_code == 0
    assert "sync failed: database unreachable: down" in result.output


def test_help_lists_eval():
    result = runner.invoke(app, ["--help"])
    assert "eval" in result.output


def test_eval_exits_2_without_langsmith_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "LANGSMITH_API_KEY" in result.output


def test_eval_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key=None, langsmith_api_key="ls"),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_eval_exit_code_follows_rates_and_errors(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen: list[dict] = []

    def stub(rates, errors):
        async def run_eval(settings, model, **kw):
            seen.append(kw)
            kw["log"]("experiment: analyst-v1-test")
            return rates, errors

        monkeypatch.setattr("tri_analyze.evals.run.run_eval", run_eval)

    stub({"uses_sql": 1.0, "grounded": 1.0}, 0)
    result = runner.invoke(app, ["eval", "--prefix", "try", "--recreate-dataset"])
    assert result.exit_code == 0 and "experiment: analyst-v1-test" in result.output
    assert seen[-1]["prefix"] == "try" and seen[-1]["recreate"] is True
    stub({"uses_sql": 0.5, "grounded": 1.0}, 0)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({"uses_sql": 1.0}, 2)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({}, 0)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    assert seen[-1]["prefix"] is None and seen[-1]["recreate"] is False
