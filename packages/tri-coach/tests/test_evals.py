"""The routing eval without LangSmith, a database or a real model."""

from datetime import date
from typing import Any

from langchain_core.messages import AIMessage

import tri_coach.evals.run as coach_run
from tri_coach.config import CoachSettings
from tri_coach.evals import target as target_module
from tri_coach.evals.cases import CASES, ROUTES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    render_judge_prompt,
    routing_accuracy,
)
from tri_coach.evals.run import DATASET_NAME, case_examples, ensure_dataset
from tri_coach.evals.target import classify, make_target, stub_tools
from tri_coach.prompts.coach import CHECKIN_REQUEST, PROMPT_VERSION
from tri_coach.tools.analyst import make_analyst_tool
from tri_coach.tools.wellness import make_wellness_tool
from tri_core.harness.agents import one_tool_call_at_a_time
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.ranges.registry import load_registry


def case(name):
    return next(c for c in CASES if c.name == name)


def _unreachable_connect():
    raise AssertionError("connect must not be called when only comparing tool descriptions")


def test_cases_are_valid_and_cover_every_route():
    assert len({c.name for c in CASES}) == len(CASES) >= 12
    for c in CASES:
        assert c.expected and set(c.expected) <= set(ROUTES), c.name
        i = c.inputs()
        assert i["context"].startswith("Today is 2026-09-16."), c.name
        assert i["messages"][-1] == {"role": "user", "content": c.message}
        assert ("Labs: panel 2026-08-30" in i["context"]) == c.labs_enabled, c.name
        assert i["memory"].startswith("Athlete memory")
        assert c.outputs() == {
            "expected_routes": list(c.expected),
            "pure_question": c.pure_question,
        }
    assert {r for c in CASES for r in c.expected} == set(ROUTES)
    assert any(c.message == CHECKIN_REQUEST for c in CASES)
    assert any(c.pure_question for c in CASES) and any(not c.pure_question for c in CASES)


def test_stub_tools_use_the_real_names_and_bind_wellness_only_with_labs():
    names = {t.name for t in stub_tools({"labs_enabled": True})}
    assert names == {
        "ask_analyst",
        "ask_wellness",
        "consult_planning",
        "consult_nutrition",
        "propose_changes",
        "remember",
        "forget",
    }
    assert "ask_wellness" not in {t.name for t in stub_tools({"labs_enabled": False})}


def test_stub_descriptions_match_the_real_tools():
    real_analyst = make_analyst_tool(
        ScriptedChatModel(script=[]), [], _unreachable_connect, lambda: date(2026, 9, 16)
    )
    stub_analyst = next(t for t in stub_tools({"labs_enabled": True}) if t.name == "ask_analyst")
    assert stub_analyst.description == real_analyst.description

    registry = load_registry("male")
    real_wellness = make_wellness_tool(
        ScriptedChatModel(script=[]),
        _unreachable_connect,
        "postgresql://unused/db",
        registry,
        lambda: date(2026, 9, 16),
    )
    stub_wellness = next(t for t in stub_tools({"labs_enabled": True}) if t.name == "ask_wellness")
    assert stub_wellness.description == real_wellness.description


def test_classify_routes():
    def call(name):
        return {"name": name, "args": {}}

    assert classify([]) == "none"
    assert classify([call("remember")]) == "none"
    assert classify([call("ask_analyst")]) == "analyst"
    assert classify([call("ask_analyst"), call("ask_wellness")]) == "wellness"
    assert classify([call("ask_wellness"), call("consult_nutrition")]) == "nutrition"
    assert classify([call("ask_analyst"), call("consult_planning")]) == "planning"
    assert classify([call("consult_planning"), call("consult_nutrition")]) == "both"


async def test_target_records_the_calls_briefs_and_route():
    c = case("knee_pain_planning")
    brief = "Knee pain on runs since Sunday. No running for 7 days; hold weekly TSS; keep Saturday."
    model = ScriptedChatModel(
        script=[
            tool_call("ask_analyst", {"question": "Runs since Sunday?"}, "a1"),
            tool_call("consult_planning", {"instruction": brief}, "c1"),
            tool_call("propose_changes", {"narration": "Knee.", "proposal_ids": ["p1"]}, "c2"),
            AIMessage(content="never reached: propose_changes ends the turn"),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert model.calls == 3
    assert [x["name"] for x in out["calls"]] == [
        "ask_analyst",
        "consult_planning",
        "propose_changes",
    ]
    assert out["route"] == "planning" and out["briefs"] == [brief]
    assert routing_accuracy(out, c.outputs()) == {
        "key": "routing_accuracy",
        "score": 1,
        "comment": "route planning; expected one of planning",
    }
    assert no_unrequested_adjustment(out, c.outputs())["score"] is None


async def test_the_eval_target_disables_parallel_tool_calls(monkeypatch):
    """Spec S6.4: run_case builds its sub-agent with middleware=[one_tool_call_at_a_time], same
    as the real coach node."""
    captured: list[Any] = []
    real = target_module.make_subagent

    def record(model, tools, system_prompt, **kwargs):
        captured.append(kwargs.get("middleware"))
        return real(model, tools, system_prompt, **kwargs)

    monkeypatch.setattr(target_module, "make_subagent", record)
    c = case("tsb_from_context")
    model = ScriptedChatModel(script=[AIMessage(content="TSB is -8.")])
    await make_target(model)(c.inputs())
    assert captured == [[one_tool_call_at_a_time]]


async def test_a_pure_question_answered_from_context_consults_nothing():
    c = case("tsb_from_context")
    model = ScriptedChatModel(script=[AIMessage(content="TSB is -8.")])
    out = await make_target(model)(c.inputs())
    assert out["route"] == "none" and out["answer"] == "TSB is -8." and out["briefs"] == []
    assert routing_accuracy(out, c.outputs())["score"] == 1
    assert no_unrequested_adjustment(out, c.outputs())["score"] == 1
    bad = {"calls": [{"name": "consult_planning", "args": {}}], "route": "planning"}
    res = no_unrequested_adjustment(bad, c.outputs())
    assert res["score"] == 0 and "consult_planning" in res["comment"]


async def test_brief_judge_scores_every_brief_and_skips_a_turn_without_one():
    verdict = {
        "bounded": True,
        "names_signal": True,
        "names_lever": True,
        "names_constraint": False,
        "grounded": True,
        "problems": ["no constraint named"],
    }
    c = case("knee_pain_planning")
    judge = make_brief_judge(ScriptedChatModel(script=[tool_call("BriefJudgement", verdict)]))
    res = await judge(c.inputs(), {"briefs": ["Knee pain. No running for 7 days."]})
    assert res["key"] == "brief_quality" and res["score"] == 0
    assert "no constraint named" in res["comment"]
    res = await make_brief_judge(ScriptedChatModel(script=[]))(c.inputs(), {"briefs": []})
    assert res["score"] is None


class FakeClient:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.created: list[str] = []
        self.examples: list[dict] = []
        self.deleted = 0

    def has_dataset(self, dataset_name):
        return dataset_name in self.names

    def delete_dataset(self, dataset_name):
        self.names.discard(dataset_name)
        self.deleted += 1

    def create_dataset(self, name, description):
        self.names.add(name)
        self.created.append(name)

    def create_examples(self, dataset_name, examples):
        self.examples += examples


def test_dataset_examples_are_created_once_and_recreated_on_request():
    examples = case_examples()
    assert DATASET_NAME == "tri_coach_routing" and len(examples) == len(CASES)
    assert examples[0]["outputs"] == CASES[0].outputs()
    assert examples[0]["metadata"] == {"case": CASES[0].name}
    client = FakeClient()
    ensure_dataset(client)
    ensure_dataset(client)
    assert client.created == [DATASET_NAME] and len(client.examples) == len(CASES)
    ensure_dataset(client, recreate=True)
    assert client.deleted == 1 and client.created == [DATASET_NAME, DATASET_NAME]


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


async def test_run_eval_uses_the_coach_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, coach_run)
    models, roles = _recording_models()
    settings = CoachSettings(_env_file=None, langsmith_api_key="ls")
    logged: list[str] = []
    assert await coach_run.run_eval(settings, models, log=logged.append) == {}
    assert sorted(roles) == sorted([Role.COACH, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }
    assert f"(prompt version {PROMPT_VERSION}):" in "\n".join(logged)


async def test_the_target_returns_every_answer_it_served():
    c = case("knee_pain_planning")
    model = ScriptedChatModel(
        script=[
            tool_call("ask_analyst", {"question": "Runs since Sunday?"}, "a1"),
            tool_call("consult_planning", {"instruction": "Knee. No running 7 days."}, "c1"),
            AIMessage(content="Planning will move the runs."),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert [s["name"] for s in out["served"]] == ["ask_analyst", "consult_planning"]
    assert out["served"][0]["answer"] == c.inputs()["analyst_answer"]
    assert out["served"][1]["answer"].startswith("p1 (planning)")


def test_the_judge_sees_context_memory_conversation_and_served_answers():
    c = case("knee_pain_planning")
    served = [{"name": "ask_analyst", "answer": "TSB -18 entering the week."}]
    text = render_judge_prompt(c.inputs(), {"served": served}, "TSB -18. Drop Thursday's run.")
    inputs = c.inputs()
    assert inputs["context"] in text and inputs["memory"] in text
    assert all(m["content"] in text for m in inputs["messages"])
    assert "ask_analyst: TSB -18 entering the week." in text
    assert text.rstrip().endswith("TSB -18. Drop Thursday's run.")
    bare = render_judge_prompt(c.inputs(), {}, "b")
    assert "Tool answers this turn:\n(none)" in bare


async def test_an_ungrounded_brief_fails_naming_its_index():
    good = {
        "bounded": True,
        "names_signal": True,
        "names_lever": True,
        "names_constraint": True,
        "grounded": True,
        "problems": [],
    }
    bad = {**good, "grounded": False, "problems": ["Ferritin 18 appears nowhere"]}
    judge = make_brief_judge(
        ScriptedChatModel(
            script=[tool_call("BriefJudgement", good), tool_call("BriefJudgement", bad)]
        )
    )
    res = await judge(case("knee_pain_planning").inputs(), {"briefs": ["one", "two"]})
    assert res["score"] == 0 and res["comment"] == "brief 2: Ferritin 18 appears nowhere"


async def test_a_raising_brief_judge_scores_zero_with_the_error():
    judge = make_brief_judge(ScriptedChatModel(script=[]))  # IndexError on the first call
    res = await judge(case("knee_pain_planning").inputs(), {"briefs": ["one"]})
    assert res["score"] == 0 and res["comment"].startswith("judge failed: IndexError")


def test_the_eval_context_names_the_consults_left():
    assert "Consults left this turn: planning 2, nutrition 2." in case("knee_pain_planning").context


async def test_a_raising_judge_keeps_the_failures_already_found():
    bad = {
        "bounded": True,
        "names_signal": True,
        "names_lever": True,
        "names_constraint": True,
        "grounded": False,
        "problems": ["Ferritin 18 appears nowhere"],
    }
    # the second call finds the script empty and raises IndexError
    judge = make_brief_judge(ScriptedChatModel(script=[tool_call("BriefJudgement", bad)]))
    res = await judge(case("knee_pain_planning").inputs(), {"briefs": ["one", "two"]})
    assert res["score"] == 0 and res["comment"].startswith("judge failed: IndexError")
    assert "brief 1: Ferritin 18 appears nowhere" in res["comment"]
