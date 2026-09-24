"""Evaluators over one coach turn: two code checks over the tool calls (the route taken, and no
handoff for a pure question) and an LLM judge over each brief. A check that does not apply to a
case scores None, which the pass rate leaves out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from tri_coach.evals.target import HANDOFFS
from tri_core.llm import structured

AsyncEvaluator = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


def routing_accuracy(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected = [str(r) for r in reference_outputs.get("expected_routes") or []]
    route = str(outputs.get("route"))
    return {
        "key": "routing_accuracy",
        "score": int(route in expected),
        "comment": f"route {route}; expected one of {', '.join(expected)}",
    }


def no_unrequested_adjustment(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not reference_outputs.get("pure_question"):
        return {"key": "no_unrequested_adjustment", "score": None, "comment": "not a pure question"}
    made = [
        c["name"]
        for c in outputs.get("calls") or []
        if c["name"] in HANDOFFS or c["name"] == "propose_changes"
    ]
    return {
        "key": "no_unrequested_adjustment",
        "score": int(not made),
        "comment": ", ".join(made) or "ok",
    }


class BriefJudgement(BaseModel):
    bounded: bool = Field(
        description="asks for one specific change, not a review, a re-plan or an open question"
    )
    names_signal: bool = Field(description="states what was observed or reported that warrants it")
    names_lever: bool = Field(description="states what to change")
    names_constraint: bool = Field(description="states what must hold while changing it")
    problems: list[str] = Field(description="one line per missing element or overreach")


JUDGE_SYSTEM = """\
You audit one brief a head coach wrote to a planning or nutrition sub-agent. A good brief is
bounded (one specific change the sub-agent can carry out without deciding anything else) and
names three things: the signal (what was observed or reported, with numbers or dates when the
conversation has them), the lever (what to change) and the constraint (what must hold, such as
a weekly TSS band, a session to keep, or the nutrition goal). You are given the athlete's last
message and the brief. Judge the brief's text literally; return a BriefJudgement."""


def render_judge_prompt(inputs: dict[str, Any], brief: str) -> str:
    messages = inputs.get("messages") or []
    last = str(messages[-1]["content"]) if messages else ""
    return f"Athlete's last message:\n{last}\n\nBrief:\n{brief}"


def make_brief_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = structured(model, BriefJudgement)

    async def brief_quality(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        briefs = [b for b in outputs.get("briefs") or [] if b]
        if not briefs:
            return {"key": "brief_quality", "score": None, "comment": "no brief"}
        ok = True
        problems: list[str] = []
        for brief in briefs:
            out = await judge.ainvoke(
                [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, brief))]
            )
            assert isinstance(out, BriefJudgement)
            ok = (
                ok and out.bounded and out.names_signal and out.names_lever and out.names_constraint
            )
            problems += out.problems
        return {"key": "brief_quality", "score": int(ok), "comment": "; ".join(problems) or "ok"}

    return brief_quality
