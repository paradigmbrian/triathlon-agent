from langchain_core.messages import AIMessage

import tri_wellness.evals.run as wellness_run
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel
from tri_wellness.config import WellnessSettings
from tri_wellness.evals.cases import CASES
from tri_wellness.evals.evaluators import (
    cites_functional_ranges,
    has_required_sections,
    names_active_confounders,
)
from tri_wellness.evals.run import DATASET_NAME, case_examples, pass_rates, render_pass_rates
from tri_wellness.evals.target import make_target, parse_inputs
from tri_wellness.labs.evaluate import evaluate
from tri_wellness.prompts.report import DISCLAIMER, PROMPT_VERSION
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import REPORT_BODY, REPORT_OK


def case(name):
    return next(c for c in CASES if c.name == name)


def test_cases_are_valid_and_cover_the_rules():
    reg = load_registry("male", MARKERS_PATH)
    assert len({c.name for c in CASES}) == len(CASES) >= 4
    flagged_total = 0
    for c in CASES:
        results, context, training, previous, _ = parse_inputs(c.inputs())
        findings = evaluate(results, reg, previous, context, training)
        assert len(findings) == len(results), c.name
        flagged_total += sum(f.functional_status != "optimal" for f in findings)
    assert flagged_total >= 6
    assert any(not parse_inputs(c.inputs())[3] for c in CASES)  # a first-panel case
    assert any(parse_inputs(c.inputs())[3] for c in CASES)  # a case with a previous panel
    assert all(
        f.functional_status == "optimal" for f in evaluate(*_parts(case("all_optimal"), reg))
    )
    examples = case_examples()
    assert len(examples) == len(CASES) and examples[0]["metadata"]["case"] == CASES[0].name
    assert DATASET_NAME == "tri_wellness_reports"


def _parts(c, reg):
    results, context, training, previous, _ = parse_inputs(c.inputs())
    return results, reg, previous, context, training


async def test_target_writes_and_code_evaluators_pass_on_a_good_report():
    reg = load_registry("male", MARKERS_PATH)
    c = case("iron_after_long_ride")
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_BODY)])
    out = await make_target(model, reg)(c.inputs())
    assert out["report_md"] == REPORT_OK and model.calls == 1  # disclaimer prepended by the target
    assert {f["marker"] for f in out["findings"]} == {"ferritin", "hs_crp", "hemoglobin", "tsh"}
    assert cites_functional_ranges(c.inputs(), out) == {
        "key": "cites_functional_ranges",
        "score": 1,
        "comment": "ok",
    }
    assert has_required_sections(c.inputs(), out)["score"] == 1
    assert names_active_confounders(c.inputs(), out)["score"] == 1


def test_evaluators_catch_a_bad_report():
    reg = load_registry("male", MARKERS_PATH)
    c = case("iron_after_long_ride")
    findings = evaluate(*_parts(c, reg))
    bad = "Looks fine.\n\n## Priorities\n1. Eat well.\n"
    out = {"report_md": bad, "findings": [f.model_dump(mode="json") for f in findings]}
    r = cites_functional_ranges(c.inputs(), out)
    assert r["score"] == 0 and "Ferritin" in r["comment"] and "50-150" in r["comment"]
    s = has_required_sections(c.inputs(), out)
    assert s["score"] == 0 and "disclaimer" in s["comment"] and "Draw conditions" in s["comment"]
    assert "Changes since last panel" in s["comment"]
    n = names_active_confounders(c.inputs(), out)
    assert n["score"] == 0 and "recent_hard_session" in n["comment"]


def test_sections_evaluator_requires_changes_only_with_a_previous_panel():
    reg = load_registry("male", MARKERS_PATH)
    first = case("lipids_metabolic_first_panel")
    findings = evaluate(*_parts(first, reg))
    md = REPORT_OK.split("## Changes since last panel")[0]
    out = {"report_md": md, "findings": [f.model_dump(mode="json") for f in findings]}
    assert has_required_sections(first.inputs(), out)["score"] == 1
    with_changes = {"report_md": REPORT_OK, "findings": out["findings"]}
    r = has_required_sections(first.inputs(), with_changes)
    assert r["score"] == 0 and "no previous panel" in r["comment"]
    assert DISCLAIMER.split(";")[0] in REPORT_OK


def test_pass_rates_and_rendering():
    class R:
        def __init__(self, key, score):
            self.key, self.score = key, score

    rows = [
        {
            "evaluation_results": {
                "results": [R("cites_functional_ranges", 1), R("has_required_sections", 0)]
            }
        },
        {
            "evaluation_results": {
                "results": [R("cites_functional_ranges", 1), R("has_required_sections", 1)]
            }
        },
    ]
    rates = pass_rates(rows)
    assert rates == {"cites_functional_ranges": 1.0, "has_required_sections": 0.5}
    text = render_pass_rates(rates, 2)
    assert "2 examples" in text and "has_required_sections" in text and "50%" in text


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


async def test_run_eval_uses_the_lab_report_role_and_no_judge(monkeypatch):
    captured = _stub_langsmith(monkeypatch, wellness_run)
    models, roles = _recording_models()
    settings = WellnessSettings(_env_file=None, tri_athlete_sex="male", langsmith_api_key="ls")
    assert await wellness_run.run_eval(settings, models, log=lambda m: None) == {}
    assert roles == [Role.LAB_REPORT]
    meta = captured["metadata"]
    assert meta["prompt_version"] == PROMPT_VERSION and "ranges_version" in meta
    assert meta["model"] == "claude-opus-5" and meta["effort"] is None
    assert "judge_model" not in meta
