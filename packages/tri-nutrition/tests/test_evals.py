from datetime import date

from langsmith.evaluation import EvaluationResult

import tri_nutrition.evals.run as nutrition_run
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition.config import NutritionSettings
from tri_nutrition.evals.cases import CASES
from tri_nutrition.evals.evaluators import (
    fuel_within_bounds,
    make_fuel_judge,
    targets_within_bounds,
)
from tri_nutrition.evals.run import DATASET_NAME, case_examples, pass_rates, render_pass_rates
from tri_nutrition.evals.target import make_target, parse_inputs
from tri_nutrition.graph.nodes.fuel import qualifies, race_due
from tri_nutrition.prompts.fuel import PROMPT_VERSION
from tri_nutrition.testing import race_plan_json, session_fuel_json


def case(name):
    return next(c for c in CASES if c.name == name)


def fuel_calls(c, **over):
    _, sessions, _, _, _ = parse_inputs(c.inputs())
    return [
        tool_call("SessionFuel", session_fuel_json(s.tp_workout_id or "", s.day, **over))
        for s in sessions
        if qualifies(s)
    ]


def test_cases_are_valid_and_each_has_a_qualifying_session():
    assert len({c.name for c in CASES}) == len(CASES) >= 5
    for c in CASES:
        profile, sessions, ctx, fuel_log, today = parse_inputs(c.inputs())
        assert today == date(2026, 9, 14)
        assert all(0 <= (s.day - today).days < 7 for s in sessions)
        assert any(qualifies(s) for s in sessions)
        assert profile.tested_products, c.name
    assert race_due(parse_inputs(case("race_week_olympic").inputs())[2], date(2026, 9, 14))
    examples = case_examples()
    assert len(examples) == len(CASES) and examples[0]["metadata"]["case"] == CASES[0].name
    assert DATASET_NAME == "tri_nutrition_fueling"


async def test_target_runs_a_week_and_code_evaluators_pass():
    c = case("maintain_build_week")
    calls = fuel_calls(c)
    model = ScriptedChatModel(script=calls)
    out = await make_target(model)(c.inputs())
    assert model.calls == len(calls) and len(out["fuels"]) == len(calls)
    assert len(out["targets"]) == 7 and out["target_violations"] == [] and out["race"] is None
    assert all(f["violations"] == [] for f in out["fuels"])
    assert targets_within_bounds(c.inputs(), out) == {
        "key": "targets_within_bounds",
        "score": 1,
        "comment": "ok",
    }
    assert fuel_within_bounds(c.inputs(), out)["score"] == 1


async def test_race_case_plans_the_race_and_retries_bad_fuel():
    c = case("race_week_olympic")
    _, _, ctx, _, _ = parse_inputs(c.inputs())
    bad = fuel_calls(c, products=["Mystery"])
    race = tool_call("RaceFuelPlan", race_plan_json(ctx.event_date))
    model = ScriptedChatModel(script=[*bad, *bad, race])
    out = await make_target(model)(c.inputs())
    assert out["race"] is not None and out["race"]["violations"] == []
    assert all(any("Mystery" in v for v in f["violations"]) for f in out["fuels"])
    res = fuel_within_bounds(c.inputs(), out)
    assert res["score"] == 0 and "Mystery" in res["comment"]


async def test_judge_uses_the_model_only_when_there_are_notes():
    c = case("vegan_lose_gluten_free")
    model = ScriptedChatModel(script=fuel_calls(c, products=["Oat bar"]))
    out = await make_target(model)(c.inputs())
    verdict = {
        "respects_restrictions": False,
        "only_library_products": True,
        "problems": ["2026-09-15 pre: banana, a listed dislike"],
    }
    judge_model = ScriptedChatModel(script=[tool_call("FuelJudgement", verdict)])
    res = await make_fuel_judge(judge_model)(c.inputs(), out)
    assert res["key"] == "fuel_respects_profile" and res["score"] == 0
    assert "banana" in res["comment"]
    empty = {"fuels": [], "race": None}
    res = await make_fuel_judge(ScriptedChatModel(script=[]))(c.inputs(), empty)
    assert res["score"] == 1


def test_pass_rates_and_rendering():
    rows = [
        {
            "evaluation_results": {
                "results": [EvaluationResult(key="a", score=1), EvaluationResult(key="b", score=0)]
            }
        },
        {
            "evaluation_results": {
                "results": [
                    EvaluationResult(key="a", score=1),
                    EvaluationResult(key="b", score=1),
                    EvaluationResult(key="c", score=None),
                ]
            }
        },
    ]
    rates = pass_rates(rows)
    assert rates == {"a": 1.0, "b": 0.5}
    text = render_pass_rates(rates, 2)
    assert "a" in text and "100%" in text and "50%" in text and "2 examples" in text


class _FakeClient:
    def __init__(self, **kw):
        pass

    def has_dataset(self, **kw):
        return True


class _FakeResults:
    experiment_name = "exp"

    def __aiter__(self):
        async def rows():
            return
            yield

        return rows()


def _stub_langsmith(monkeypatch, run_module) -> dict:
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    monkeypatch.setattr(run_module, "Client", _FakeClient)
    monkeypatch.setattr(run_module, "aevaluate", fake_aevaluate)
    return captured


def _recording_models():
    roles: list[Role] = []
    fake = ScriptedChatModel(script=[])

    def models(role: Role):
        roles.append(role)
        return fake

    return models, roles


async def test_run_eval_uses_the_fuel_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, nutrition_run)
    models, roles = _recording_models()
    settings = NutritionSettings(_env_file=None, langsmith_api_key="ls")
    assert await nutrition_run.run_eval(settings, models, log=lambda m: None) == {}
    assert sorted(roles) == sorted([Role.NUTRITION_FUEL, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }
