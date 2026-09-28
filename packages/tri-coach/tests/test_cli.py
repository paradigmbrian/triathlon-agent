from typer.testing import CliRunner

from tri_coach import cli
from tri_coach.cli import app, ready
from tri_coach.config import CoachSettings

runner = CliRunner()


def test_help_lists_the_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("chat", "check-in", "memory", "reset", "eval"):
        assert name in result.output


def test_eval_local_needs_no_langsmith_key_and_passes_local_through(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_coach_settings",
        lambda: CoachSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    seen: list[dict] = []

    async def run_eval(settings, model, **kw):
        seen.append(kw)
        return {"routing_accuracy": 1.0}

    monkeypatch.setattr("tri_coach.evals.run.run_eval", run_eval)
    result = runner.invoke(app, ["eval", "--local"])
    assert result.exit_code == 0 and seen[-1]["local"] is True


def test_tri_eval_local_env_makes_it_local_without_the_flag(monkeypatch):
    monkeypatch.setenv("TRI_EVAL_LOCAL", "1")
    monkeypatch.setattr(
        cli,
        "get_coach_settings",
        lambda: CoachSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    seen: list[dict] = []

    async def run_eval(settings, model, **kw):
        seen.append(kw)
        return {"routing_accuracy": 1.0}

    monkeypatch.setattr("tri_coach.evals.run.run_eval", run_eval)
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0 and seen[-1]["local"] is True


def test_ready_names_the_missing_piece(monkeypatch):
    assert ready(CoachSettings(_env_file=None, anthropic_api_key=None)) == (
        "ANTHROPIC_API_KEY is not set in .env"
    )
    monkeypatch.setattr("tri_core.harness.persistence.checkpointer_ready", lambda url: False)
    s = CoachSettings(_env_file=None, anthropic_api_key="k", database_url="postgresql://x/y")
    assert ready(s) is not None and "uv run tri migrate" in ready(s)
    monkeypatch.setattr("tri_core.harness.persistence.checkpointer_ready", lambda url: True)
    monkeypatch.setattr("tri_core.harness.persistence.store_ready", lambda url: False)
    assert ready(s) is not None and "LangGraph store tables are missing" in ready(s)
    monkeypatch.setattr("tri_core.harness.persistence.store_ready", lambda url: True)
    assert ready(s) is None
