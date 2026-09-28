import json

import pytest
from langsmith.schemas import Example
from typer.testing import CliRunner

import tri_analyze.evals.run as analyze_run
from tri_analyze import cli
from tri_analyze.cli import app
from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import CASES
from tri_core.eval_select import Selection
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel

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


async def test_a_local_subset_runs_only_the_chosen_cases_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _NoRows()

    monkeypatch.setattr(analyze_run, "Client", _refuse)
    monkeypatch.setattr(analyze_run, "aevaluate", fake_aevaluate)
    monkeypatch.setattr(analyze_run, "seed_database", lambda url: None)
    monkeypatch.setattr(analyze_run, "clear_database", lambda url: None)
    monkeypatch.setattr(analyze_run, "verify_readable", lambda url: None)
    models, _ = _recording_models()
    name = CASES[1].name
    logged: list[str] = []
    await analyze_run.run_eval(
        AnalyzeSettings(_env_file=None),
        models,
        judge=False,
        local=True,
        log=logged.append,
        selection=Selection(cases=[name]),
    )
    assert [e.metadata["case"] for e in captured["data"]] == [name]
    assert all(isinstance(e, Example) for e in captured["data"])
    assert captured["experiment_prefix"].endswith("-subset-local")
    assert captured["metadata"]["cases"] == [name]
    text = "\n".join(logged)
    assert f"pass rate over 0 of {len(CASES)} examples (subset)" in text
    assert "usage: no model calls" in text


async def test_rescore_reads_the_file_and_never_builds_the_analyst_or_touches_the_database(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    for attr in ("Client", "aevaluate", "seed_database", "clear_database", "verify_readable"):
        monkeypatch.setattr(analyze_run, attr, _refuse)

    def stub(outputs):
        return {"key": "stub", "score": int(outputs.get("answer") == "ok")}

    monkeypatch.setattr(analyze_run, "_evaluators", lambda models, judge: [stub])
    examples = analyze_run.case_examples()
    src = tmp_path / "analyst-v3-x.jsonl"
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
                    "metadata": {"prompt_version": "3", "model": "claude-opus-5"},
                },
                {
                    "case": CASES[1].name,
                    "inputs": examples[1]["inputs"],
                    "outputs": {"answer": "no"},
                    "error": None,
                    "results": [],
                },
                {
                    "case": CASES[2].name,
                    "inputs": examples[2]["inputs"],
                    "outputs": None,
                    "error": "boom",
                    "results": [],
                },
            ]
        )
    )
    models, roles = _recording_models()
    logged: list[str] = []
    rates, errors = await analyze_run.run_eval(
        AnalyzeSettings(_env_file=None),
        models,
        log=logged.append,
        selection=Selection(rescore=src),
    )
    assert rates == {"stub": 0.5} and errors == 1
    assert Role.ANALYST not in roles
    [out_file] = (tmp_path / "out").glob("analyst-v3-x-rescore-*.jsonl")
    meta = json.loads(out_file.read_text().splitlines()[0])["metadata"]
    assert meta["rescored_from"] == str(src) and meta["judge_version"]
    assert "1 errored in the source, not rescored" in logged


def _settings(**kw):
    return AnalyzeSettings(_env_file=None, anthropic_api_key="k", **kw)


def _capture(monkeypatch):
    seen: list[dict] = []

    async def run_eval(settings, models, **kw):
        seen.append(kw)
        return {"uses_sql": 1.0}, 0

    monkeypatch.setattr("tri_analyze.evals.run.run_eval", run_eval)
    return seen


def test_eval_cases_reach_run_eval_as_a_selection(monkeypatch):
    monkeypatch.setattr(cli, "get_analyze_settings", lambda: _settings(langsmith_api_key="ls"))
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", CASES[0].name])
    assert result.exit_code == 0
    assert seen[-1]["selection"] == Selection(cases=[CASES[0].name])


def test_eval_rescore_runs_locally_without_a_langsmith_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_analyze_settings", lambda: _settings(langsmith_api_key=None))
    seen = _capture(monkeypatch)
    src = tmp_path / "r.jsonl"
    src.write_text(json.dumps({"case": CASES[0].name, "results": []}) + "\n")
    result = runner.invoke(app, ["eval", "--rescore", str(src)])
    assert result.exit_code == 0
    assert seen[-1]["local"] is True and seen[-1]["selection"].rescore == src


def test_eval_unknown_case_exits_2_and_names_it(monkeypatch):
    monkeypatch.setattr(cli, "get_analyze_settings", lambda: _settings(langsmith_api_key="ls"))
    seen = _capture(monkeypatch)
    result = runner.invoke(app, ["eval", "--cases", "no_such_case"])
    assert result.exit_code == 2 and "no_such_case" in result.output and seen == []


def test_eval_failed_from_with_nothing_failed_exits_0_without_running(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_analyze_settings", lambda: _settings(langsmith_api_key="ls"))
    seen = _capture(monkeypatch)
    src = tmp_path / "r.jsonl"
    src.write_text(json.dumps({"case": CASES[0].name, "results": [{"key": "k", "score": 1}]}))
    result = runner.invoke(app, ["eval", "--failed-from", str(src)])
    assert result.exit_code == 0 and "nothing failed in" in result.output and seen == []


def test_eval_a_subset_the_dataset_cannot_serve_exits_2(monkeypatch):
    from tri_core.eval_select import EvalArgsError

    monkeypatch.setattr(cli, "get_analyze_settings", lambda: _settings(langsmith_api_key="ls"))

    async def run_eval(settings, models, **kw):
        raise EvalArgsError(
            "the LangSmith dataset d has no example named x; run once with "
            "--recreate-dataset so its examples carry case names"
        )

    monkeypatch.setattr("tri_analyze.evals.run.run_eval", run_eval)
    result = runner.invoke(app, ["eval", "--cases", CASES[0].name])
    assert result.exit_code == 2 and "--recreate-dataset" in result.output
