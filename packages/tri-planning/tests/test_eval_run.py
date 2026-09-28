from datetime import date

import tri_planning.evals.run as planning_run
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel
from tri_planning.config import PlanningSettings
from tri_planning.evals.run import DATASET_NAME, case_examples
from tri_planning.prompts.design import PROMPT_VERSION


def test_the_dataset_keeps_the_scripts_name_and_examples_carry_empty_outputs():
    assert DATASET_NAME == "tri-planning-design-weeks"
    ex = case_examples(date(2026, 9, 14))
    assert len(ex) >= 16
    assert all(
        e["outputs"] == {} and "goal" in e["inputs"] and "phase" in e["metadata"] for e in ex
    )


async def test_run_eval_designs_on_the_design_role(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kw):
            pass

        def has_dataset(self, **kw):
            return True

    class FakeResults:
        experiment_name = "exp"

        def __aiter__(self):
            async def rows():
                return
                yield

            return rows()

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return FakeResults()

    monkeypatch.setattr(planning_run, "Client", FakeClient)
    monkeypatch.setattr(planning_run, "aevaluate", fake_aevaluate)
    roles: list[Role] = []

    def models(role: Role):
        roles.append(role)
        return ScriptedChatModel(script=[])

    settings = PlanningSettings(_env_file=None, langsmith_api_key="ls")
    logged: list[str] = []
    assert await planning_run.run_eval(settings, models, log=logged.append) == {}
    assert roles == [Role.PLANNING_DESIGN]
    assert captured["experiment_prefix"] == "design-v2"
    assert captured["metadata"] == {"prompt_version": "2", "model": "claude-opus-5", "effort": None}
    assert [e.__name__ for e in captured["evaluators"]] == ["validator_pass"]
    assert f"(prompt version {PROMPT_VERSION}):" in "\n".join(logged)
