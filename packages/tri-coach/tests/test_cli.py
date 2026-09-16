from typer.testing import CliRunner

from tri_coach.cli import app, ready
from tri_coach.config import CoachSettings


def test_help_lists_the_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("chat", "check-in", "memory", "reset", "eval"):
        assert name in result.output


def test_ready_names_the_missing_piece(monkeypatch):
    assert ready(CoachSettings(_env_file=None, anthropic_api_key=None)) == (
        "ANTHROPIC_API_KEY is not set in .env"
    )
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: False)
    s = CoachSettings(_env_file=None, anthropic_api_key="k", database_url="postgresql://x/y")
    assert ready(s) is not None and "setup_checkpointer" in ready(s)
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: True)
    monkeypatch.setattr("tri_core.harness.persistence.store_ready", lambda url: False)
    assert ready(s) is not None and "LangGraph store tables are missing" in ready(s)
    monkeypatch.setattr("tri_core.harness.persistence.store_ready", lambda url: True)
    assert ready(s) is None
