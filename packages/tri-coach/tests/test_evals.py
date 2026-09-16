"""The routing eval without LangSmith, a database or a real model."""

from datetime import date
from typing import Any

from langchain_core.messages import AIMessage

from tri_coach.evals import target as target_module
from tri_coach.evals.cases import CASES, ROUTES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    routing_accuracy,
)
from tri_coach.evals.run import DATASET_NAME, case_examples, ensure_dataset, render_pass_rates
from tri_coach.evals.target import classify, make_target, stub_tools
from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_coach.tools.analyst import make_analyst_tool
from tri_coach.tools.wellness import make_wellness_tool
from tri_core.harness.agents import one_tool_call_at_a_time
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


def test_render_pass_rates_names_the_prompt_version():
    text = render_pass_rates({"routing_accuracy": 0.75, "brief_quality": 1.0}, 13)
    assert text.startswith("pass rate over 13 examples (prompt version 3):")
    assert "routing_accuracy" in text and "75%" in text and "100%" in text
