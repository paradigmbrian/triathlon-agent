import json

import pytest
from typer.testing import CliRunner

import tri_wellness.evals.run as wellness_run
from tri_core.eval_select import Selection
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel
from tri_wellness import cli
from tri_wellness.cli import app
from tri_wellness.config import WellnessSettings
from tri_wellness.evals.cases import CASES

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


def _settings(**kw):
    return WellnessSettings(_env_file=None, tri_athlete_sex="male", **kw)


async def test_a_local_subset_runs_only_the_chosen_cases_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _NoRows()

    monkeypatch.setattr(wellness_run, "Client", _refuse)
    monkeypatch.setattr(wellness_run, "aevaluate", fake_aevaluate)
    models, _ = _recording_models()
    name = CASES[1].name
    logged: list[str] = []
    await wellness_run.run_eval(
        _settings(), models, local=True, log=logged.append, selection=Selection(cases=[name])
    )
    assert [e.metadata["case"] for e in captured["data"]] == [name]
    assert captured["experiment_prefix"].endswith("-subset-local")
    assert captured["metadata"]["cases"] == [name]
    assert captured["metadata"]["gate"] is False
    assert f"pass rate over 0 of {len(CASES)} examples (subset)" in "\n".join(logged)
    assert "not a gate run" in "\n".join(logged)


async def test_rescore_reads_the_file_and_never_writes_a_report(monkeypatch, tmp_path):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(wellness_run, "Client", _refuse)
    monkeypatch.setattr(wellness_run, "aevaluate", _refuse)
    monkeypatch.setattr(wellness_run, "load_registry", _refuse)

    def stub(outputs):
        return {"key": "stub", "score": int(outputs.get("answer") == "ok")}

    monkeypatch.setattr(wellness_run, "EVALUATORS", [stub])
    examples = wellness_run.case_examples()
    src = tmp_path / "report-v3-x.jsonl"
    src.write_text(
        "".join(
            json.dumps(x, default=str) + "\n"
            for x in [
                {
                    "case": CASES[0].name,
                    "inputs": examples[0]["inputs"],
                    "outputs": {"answer": "ok"},
                    "error": None,
                    "results": [],
                },
                {
                    "case": CASES[1].name,
                    "inputs": examples[1]["inputs"],
                    "outputs": {"answer": "no"},
                    "error": None,
                    "results": [],
                },
            ]
        )
    )
    models, roles = _recording_models()
    rates = await wellness_run.run_eval(
        _settings(), models, log=lambda m: None, selection=Selection(rescore=src)
    )
    assert rates == {"stub": 0.5} and roles == []
    [out_file] = (tmp_path / "out").glob("report-v3-x-rescore-*.jsonl")
    assert json.loads(out_file.read_text().splitlines()[0])["metadata"]["rescored_from"] == str(src)


def _capture(monkeypatch):
    seen: list[dict] = []

    async def run_eval(settings, models, **kw):
        seen.append(kw)
        return {"has_required_sections": 1.0}

    monkeypatch.setattr("tri_wellness.evals.run.run_eval", run_eval)
    return seen


def test_eval_cases_reach_run_eval_as_a_selection(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_wellness_settings",
        lambda: _settings(anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", CASES[0].name])
    assert result.exit_code == 0
    assert seen[-1]["selection"] == Selection(cases=[CASES[0].name])


def test_eval_rescore_runs_locally_without_a_langsmith_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli,
        "get_wellness_settings",
        lambda: _settings(anthropic_api_key="k", langsmith_api_key=None),
    )
    seen = _capture(monkeypatch)
    src = tmp_path / "r.jsonl"
    src.write_text(json.dumps({"case": CASES[0].name, "results": []}) + "\n")
    result = runner.invoke(app, ["eval", "--rescore", str(src)])
    assert result.exit_code == 0
    assert seen[-1]["local"] is True and seen[-1]["selection"].rescore == src


def test_eval_unknown_case_exits_2_and_names_it(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_wellness_settings",
        lambda: _settings(anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", "no_such_case"])
    assert result.exit_code == 2 and "no_such_case" in result.output and seen == []
