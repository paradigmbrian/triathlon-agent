"""Evaluators over one analyst answer: three code checks over the tool calls and the answer
(SQL for data questions, splits for interval questions, a stated window for trends) and, in
make_judge, an LLM judge for grounding and feedback quality. A check that does not apply to a
case scores None, which the pass rate leaves out. A bare month name only counts as a stated
window when it carries a day, a year, or an adjacent from/to/since/between/until word, so "in
May" does not count but "June 2026" and "from June to August" do."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith.evaluation import EvaluationResult, EvaluationResults
from pydantic import BaseModel, Field

from tri_analyze.evals.target import athlete_from_inputs, stub_tools
from tri_analyze.prompts.analyst import render_system_prompt

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_FRAME = r"(?:from|to|since|between|until)"
_WORD_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_UNIT = r"(?:days?|weeks?|months?|quarters?|years?)"
WINDOW_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date: "2026-09-13"
    re.compile(r"\b\d{4}-\d{2}\b(?!-\d)"),  # bare ISO year-month: "2026-06"
    re.compile(  # month and day, either order, optional ordinal: "Sep 13", "September 13th",
        # "13 September"
        rf"\b{_MONTH}\.? {_DAY}\b|\b{_DAY} {_MONTH}\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\b{_MONTH}\.? \d{{4}}\b", re.IGNORECASE),  # month and year: "June 2026"
    re.compile(  # a bare month framed by from/to/since/between/until: "from June", "June to"
        rf"\b{_FRAME} {_MONTH}\b|\b{_MONTH} {_FRAME}\b", re.IGNORECASE
    ),
    re.compile(  # relative window, count optional: "last 8 weeks", "the last month",
        # "past two months", "previous 30 days"
        rf"\b(?:last|past|previous) (?:(?:\d+|{_WORD_NUM}) )?{_UNIT}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),  # slash date: "9/2", "9/13/2026"
)


def _names(outputs: dict[str, Any]) -> list[str]:
    return [str(c["name"]) for c in outputs.get("calls") or []]


def uses_sql(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("requires_sql"):
        return {"key": "uses_sql", "score": None, "comment": "SQL not required"}
    n = _names(outputs).count("query_training_db")
    return {"key": "uses_sql", "score": int(n > 0), "comment": f"{n} query_training_db call(s)"}


def pulls_splits(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not (reference_outputs.get("requires_splits") and inputs.get("live")):
        return {
            "key": "pulls_splits",
            "score": None,
            "comment": "splits not required, or no live tools bound",
        }
    n = _names(outputs).count("get_activity_splits")
    return {
        "key": "pulls_splits",
        "score": int(n > 0),
        "comment": f"{n} get_activity_splits call(s)",
    }


def states_window(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("expects_window"):
        return {"key": "states_window", "score": None, "comment": "no window expected"}
    answer = str(outputs.get("answer") or "")
    hit: str | None = None
    for pattern in WINDOW_PATTERNS:
        match = pattern.search(answer)
        if match:
            hit = match.group(0)
            break
    return {
        "key": "states_window",
        "score": int(hit is not None),
        "comment": f"window: {hit}" if hit else "no date or relative window in the answer",
    }


AsyncEvaluator = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], Awaitable[EvaluationResults]
]


class FeedbackJudgement(BaseModel):
    grounded: bool = Field(
        description=(
            "every number in the answer appears in the system prompt's context or in the tool "
            "results, and data that is missing is stated as missing rather than guessed"
        )
    )
    covers_rules: bool = Field(
        description=(
            "for a session review: planned vs actual, execution quality, load context "
            "(week position, CTL/ATL/TSB, sleep, HRV, readiness), the athlete's comments and "
            "RPE when present, and takeaways are all covered; true for a non-session answer"
        )
    )
    uses_athlete_comments: bool = Field(
        description=(
            "when the tool results carry athlete comments, feeling or RPE, the answer uses "
            "them; true when there are none"
        )
    )
    concrete_takeaways: bool = Field(
        description="one or two concrete takeaways for the next similar session"
    )
    no_generic_encouragement: bool = Field(description="no filler praise or generic encouragement")
    problems: list[str] = Field(description="one line per ungrounded number or missing element")


JUDGE_SYSTEM = """\
You audit one answer a triathlon coach's analyst gave to an athlete. You are given the
analyst's system prompt (the athlete's context, the bound tools and the feedback rules), the
athlete's question, the tool results the analyst received, and the analyst's answer.

Grounded: every number in the answer (durations, distances, watts, paces, heart rates, TSS,
scores, dates) appears in the system prompt's context or in the tool results, possibly after
a unit conversion or an arithmetic step you can verify; when the tool results are empty or
lack what the question needs, the answer says so instead of inventing figures.

Feedback quality applies to a session review: the five feedback rules are covered, the
athlete's own comments, feeling and RPE are used when the tool results carry them, there are
one or two concrete takeaways for the next similar session, and there is no generic
encouragement. Judge the answer's text literally; return a FeedbackJudgement."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any]) -> str:
    """Grounds the judge on what the analyst actually received: `outputs["tool_results"]`
    (the served `ToolMessage`s from `run_case`), not the case's full canned corpus — a canned
    fixture the analyst never called never appears here."""
    system = render_system_prompt(athlete_from_inputs(inputs), [t.name for t in stub_tools(inputs)])
    served = outputs.get("tool_results") or []
    grouped: dict[str, list[str]] = {}
    for result in served:
        grouped.setdefault(str(result["name"]), []).append(str(result["content"]))
    rendered = "\n".join(f"{name}:\n" + "\n".join(responses) for name, responses in grouped.items())
    return (
        f"Analyst system prompt:\n{system}\n\n"
        f"Question:\n{inputs.get('question', '')}\n\n"
        f"Tool results:\n{rendered or '(none)'}\n\n"
        f"Answer:\n{outputs.get('answer') or ''}"
    )


def make_judge(model: BaseChatModel) -> AsyncEvaluator:
    """One structured-output call per example, scoring `grounded` always and
    `feedback_quality` for session reviews. A judge call that raises scores both keys 0 with the
    error as the comment."""
    judge = model.with_structured_output(FeedbackJudgement)

    async def feedback_judge(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> EvaluationResults:
        session = reference_outputs.get("kind") == "session"
        try:
            out = await judge.ainvoke(
                [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, outputs))]
            )
            assert isinstance(out, FeedbackJudgement)
        except Exception as exc:
            comment = f"judge failed: {type(exc).__name__}: {exc}"
            return {
                "results": [
                    EvaluationResult(key="grounded", score=0, comment=comment),
                    EvaluationResult(key="feedback_quality", score=0, comment=comment),
                ]
            }
        problems = "; ".join(out.problems) or "ok"
        quality = (
            out.covers_rules
            and out.uses_athlete_comments
            and out.concrete_takeaways
            and out.no_generic_encouragement
        )
        return {
            "results": [
                EvaluationResult(key="grounded", score=int(out.grounded), comment=problems),
                EvaluationResult(
                    key="feedback_quality",
                    score=int(quality) if session else None,
                    comment=problems if session else "not a session review",
                ),
            ]
        }

    return feedback_judge
