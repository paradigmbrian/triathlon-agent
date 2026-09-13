from typer.testing import CliRunner

from tri_coach.cli import app


def test_help_lists_the_three_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("chat", "memory", "reset"):
        assert name in result.output
