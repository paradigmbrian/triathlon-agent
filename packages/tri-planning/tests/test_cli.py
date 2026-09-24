from typer.testing import CliRunner

from tri_planning import cli
from tri_planning.cli import app
from tri_planning.config import PlanningSettings

runner = CliRunner()


def test_help_lists_eval():
    assert "eval" in runner.invoke(app, ["--help"]).output


def test_eval_exits_2_without_langsmith_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "LANGSMITH_API_KEY" in result.output


def test_eval_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key=None, langsmith_api_key="ls"),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_eval_exit_code_follows_rates(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen: list[dict] = []

    def stub(rates):
        async def run_eval(settings, models, **kw):
            seen.append(kw)
            kw["log"]("experiment: design-test")
            return rates

        monkeypatch.setattr("tri_planning.evals.run.run_eval", run_eval)

    stub({"validator_pass": 1.0})
    result = runner.invoke(app, ["eval", "--prefix", "try", "--recreate-dataset"])
    assert result.exit_code == 0 and "experiment: design-test" in result.output
    assert seen[-1]["prefix"] == "try" and seen[-1]["recreate"] is True
    stub({"validator_pass": 0.5})
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({})
    assert runner.invoke(app, ["eval"]).exit_code == 1
    assert seen[-1]["prefix"] is None and seen[-1]["recreate"] is False
