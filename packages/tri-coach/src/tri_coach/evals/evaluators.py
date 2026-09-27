"""Evaluators over one coach turn: two code checks over the tool calls (the route taken, and no
handoff for a pure question) and an LLM judge over each brief. A check that does not apply to a
case scores None, which the pass rate leaves out. The judge sees the context, memory, conversation
and every tool answer the target served, so an invented number fails."""

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
    grounded: bool = Field(
        description=(
            "every number, date and lab value in the brief appears in the context block, the "
            "memory, the conversation or a sub-agent answer"
        )
    )
    problems: list[str] = Field(
        description="one line per missing element, overreach, or number that appears nowhere"
    )


JUDGE_SYSTEM = """\
You audit one brief a head coach wrote to a planning or nutrition sub-agent. A good brief is
bounded (one specific change the sub-agent can carry out without deciding anything else) and
names three things: the signal (what was observed or reported, with numbers or dates when the
conversation has them), the lever (what to change) and the constraint (what must hold, such as
a weekly TSS band, a session to keep, or the nutrition goal).

You are given what the coach knew: its context block, its memory, the whole conversation and
the answers its tools returned this turn (the analyst, the lab interpreter, earlier
consultations). Grounded: every number, date and lab value in the brief appears in one of
those. A figure that appears nowhere is invented, however plausible: name it in problems.
Judge the brief's text literally; return a BriefJudgement."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any], brief: str) -> str:
    conversation = "\n".join(f"{m['role']}: {m['content']}" for m in inputs.get("messages") or [])
    served = "\n".join(f"{s['name']}: {s['answer']}" for s in outputs.get("served") or [])
    return (
        f"Context block:\n{inputs.get('context', '')}\n\n"
        f"Memory:\n{inputs.get('memory', '')}\n\n"
        f"Conversation:\n{conversation or '(none)'}\n\n"
        f"Tool answers this turn:\n{served or '(none)'}\n\n"
        f"Brief:\n{brief}"
    )


def make_brief_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = structured(model, BriefJudgement)

    async def brief_quality(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        briefs = [b for b in outputs.get("briefs") or [] if b]
        if not briefs:
            return {"key": "brief_quality", "score": None, "comment": "no brief"}
        failed: list[str] = []
        for i, brief in enumerate(briefs, 1):
            try:
                out = await judge.ainvoke(
                    [
                        SystemMessage(JUDGE_SYSTEM),
                        HumanMessage(render_judge_prompt(inputs, outputs, brief)),
                    ]
                )
                assert isinstance(out, BriefJudgement)
            except Exception as exc:  # noqa: BLE001 - scored, not raised, like the analyst judge
                comment = f"judge failed: {type(exc).__name__}: {exc}"
                return {"key": "brief_quality", "score": 0, "comment": comment}
            ok = (
                out.bounded
                and out.names_signal
                and out.names_lever
                and out.names_constraint
                and out.grounded
            )
            if not ok:
                failed.append(f"brief {i}: " + ("; ".join(out.problems) or "no problem named"))
        return {
            "key": "brief_quality",
            "score": int(not failed),
            "comment": " | ".join(failed) or "ok",
        }

    return brief_quality
