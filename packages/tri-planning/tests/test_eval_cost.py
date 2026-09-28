import json
from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import tri_planning.evals.run as planning_run
from tri_core.eval_select import EvalArgsError, Selection
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel
from tri_planning import cli
from tri_planning.cli import app
from tri_planning.config import PlanningSettings
from tri_planning.evals.design_eval import build_examples

# langsmith's own: ast.Str inside the evaluator key extraction a rescore uses
pytestmark = pytest.mark.filterwarnings("ignore:ast.Str is deprecated:DeprecationWarning")

runner = CliRunner()


class _NoRows:
    experiment_name = "exp"

    def __aiter__(self):
        async def rows():
            return
            yield

        return rows()


def _refuse(*a, **kw):
    raise AssertionError("must not be called")


def _recording_models():
    roles: list[Role] = []

    def models(role: Role):
        roles.append(role)
        return ScriptedChatModel(script=[])

    return models, roles


def test_every_design_example_has_a_unique_case_name():
    names = [e["metadata"]["case"] for e in build_examples(date(2026, 9, 28))]
    assert len(names) == 23 and len(set(names)) == 23
    assert "olympic-base" in names


async def test_a_local_subset_runs_only_the_chosen_weeks_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _NoRows()

    monkeypatch.setattr(planning_run, "Client", _refuse)
    monkeypatch.setattr(planning_run, "aevaluate", fake_aevaluate)
    models, _ = _recording_models()
    logged: list[str] = []
    await planning_run.run_eval(
        PlanningSettings(_env_file=None),
        models,
        local=True,
        log=logged.append,
        selection=Selection(cases=["olympic-base"]),
    )
    assert [e.metadata["case"] for e in captured["data"]] == ["olympic-base"]
    assert captured["experiment_prefix"].endswith("-subset-local")
    assert captured["metadata"]["cases"] == ["olympic-base"]
    assert captured["metadata"]["gate"] is False
    assert "pass rate over 0 of 23 examples (subset)" in "\n".join(logged)
    assert "not a gate run" in "\n".join(logged)


async def test_a_langsmith_subset_on_a_dataset_without_case_names_asks_for_a_recreate(
    monkeypatch,
):
    class OldDataset:
        def __init__(self, **kw):
            pass

        def has_dataset(self, **kw):
            return True

        def list_examples(self, dataset_name):
            return iter([SimpleNamespace(metadata={"goal_type": "olympic", "phase": "base"})])

    monkeypatch.setattr(planning_run, "Client", OldDataset)
    monkeypatch.setattr(planning_run, "aevaluate", _refuse)
    models, _ = _recording_models()
    with pytest.raises(EvalArgsError, match="--recreate-dataset"):
        await planning_run.run_eval(
            PlanningSettings(_env_file=None, langsmith_api_key="ls"),
            models,
            log=lambda m: None,
            selection=Selection(cases=["olympic-base"]),
        )


async def test_rescore_reads_the_file_and_never_designs_a_week(monkeypatch, tmp_path):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(planning_run, "Client", _refuse)
    monkeypatch.setattr(planning_run, "aevaluate", _refuse)

    def stub(outputs):
        return {"key": "stub", "score": int(outputs.get("answer") == "ok")}

    monkeypatch.setattr(planning_run, "validator_pass", stub)
    examples = planning_run.case_examples(date.today())
    src = tmp_path / "design-v2-x.jsonl"
    src.write_text(
        "".join(
            json.dumps(x, default=str) + "\n"
            for x in [
                {
                    "case": examples[0]["metadata"]["case"],
                    "inputs": examples[0]["inputs"],
                    "outputs": {"answer": "ok"},
                    "error": None,
                    "results": [],
                    "metadata": {"prompt_version": "2"},
                },
                {
                    "case": examples[1]["metadata"]["case"],
                    "inputs": examples[1]["inputs"],
                    "outputs": {"answer": "no"},
                    "error": None,
                    "results": [],
                },
            ]
        )
    )
    models, roles = _recording_models()
    rates = await planning_run.run_eval(
        PlanningSettings(_env_file=None),
        models,
        log=lambda m: None,
        selection=Selection(rescore=src),
    )
    assert rates == {"stub": 0.5} and roles == []
    [out_file] = (tmp_path / "out").glob("design-v2-x-rescore-*.jsonl")
    assert json.loads(out_file.read_text().splitlines()[0])["metadata"]["rescored_from"] == str(src)


def _settings(**kw):
    return PlanningSettings(_env_file=None, anthropic_api_key="k", **kw)


def _capture(monkeypatch):
    seen: list[dict] = []

    async def run_eval(settings, models, **kw):
        seen.append(kw)
        return {"validator_pass": 1.0}

    monkeypatch.setattr("tri_planning.evals.run.run_eval", run_eval)
    return seen


def test_eval_cases_reach_run_eval_as_a_selection(monkeypatch):
    monkeypatch.setattr(cli, "get_planning_settings", lambda: _settings(langsmith_api_key="ls"))
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", "olympic-base"])
    assert result.exit_code == 0
    assert seen[-1]["selection"] == Selection(cases=["olympic-base"])


def test_eval_rescore_runs_locally_without_a_langsmith_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_planning_settings", lambda: _settings(langsmith_api_key=None))
    seen = _capture(monkeypatch)
    src = tmp_path / "r.jsonl"
    src.write_text(json.dumps({"case": "olympic-base", "results": []}) + "\n")
    result = runner.invoke(app, ["eval", "--rescore", str(src)])
    assert result.exit_code == 0
    assert seen[-1]["local"] is True and seen[-1]["selection"].rescore == src


def test_eval_unknown_case_exits_2_and_names_it(monkeypatch):
    monkeypatch.setattr(cli, "get_planning_settings", lambda: _settings(langsmith_api_key="ls"))
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", "no_such_case"])
    assert result.exit_code == 2 and "no_such_case" in result.output and seen == []


def test_eval_a_subset_the_dataset_cannot_serve_exits_2(monkeypatch):
    monkeypatch.setattr(cli, "get_planning_settings", lambda: _settings(langsmith_api_key="ls"))

    async def run_eval(settings, models, **kw):
        raise EvalArgsError("run once with --recreate-dataset so its examples carry case names")

    monkeypatch.setattr("tri_planning.evals.run.run_eval", run_eval)
    result = runner.invoke(app, ["eval", "--cases", "olympic-base"])
    assert result.exit_code == 2 and "--recreate-dataset" in result.output
