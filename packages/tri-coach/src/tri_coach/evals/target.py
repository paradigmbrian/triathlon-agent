"""The function under evaluation: one coach turn over stub tools. The coach model sees the real
rules, the case's context and memory, and tools with the real names, arguments and descriptions;
the stubs answer from the case and never reach a sub-graph, the database or a device.
propose_changes ends the turn, as in the graph."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_core.tools import BaseTool, StructuredTool

from tri_coach import memory as M
from tri_coach.evals.cases import Route
from tri_coach.graph.llm import make_subagent
from tri_coach.prompts.coach import COACH_RULES
from tri_coach.text import last_ai_text
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools

MAX_CONSULTS = 2
TARGET_RECURSION_LIMIT = 30
HANDOFFS: dict[str, Route] = {"consult_planning": "planning", "consult_nutrition": "nutrition"}
REAL_DESCRIPTIONS = {
    t.name: t.description for t in [*make_handoff_tools(), *make_memory_tools(date.today)]
}


def stub_tools(inputs: dict[str, Any]) -> list[BaseTool]:
    n = 0

    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
        logged intake against nutrition targets, or how training compares to plan. It reads the
        database and the devices; it changes nothing. Ask one specific question at a time."""
        return str(inputs.get("analyst_answer") or "No data found for that question.")

    async def ask_wellness(question: str) -> str:
        """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
        functional range, what is outside optimal and why, the retest plan, supplements, or
        whether a symptom could be lab-related. It reads stored panels and reports; it changes
        nothing. Ask one specific question at a time."""
        return str(inputs.get("wellness_answer") or "No panel stored.")

    def proposal(domain: str) -> str:
        nonlocal n
        n += 1
        return f"p{n} ({domain}): a proposal that satisfies the brief\n1 change"

    async def consult_planning(instruction: str) -> str:
        return proposal("planning")

    async def consult_nutrition(instruction: str) -> str:
        return proposal("nutrition")

    async def propose_changes(narration: str, proposal_ids: list[str]) -> str:
        return f"change set {proposal_ids} sent to the athlete for review"

    async def remember(kind: M.MemoryKind, text: str, until: str | None = None) -> str:
        return json.dumps({"remembered": True, "id": "e0e0e0"})

    async def forget(entry_id: str) -> str:
        return json.dumps({"forgotten": True, "id": entry_id})

    def make(
        fn: Callable[..., Awaitable[str]], name: str, *, return_direct: bool = False
    ) -> BaseTool:
        description = REAL_DESCRIPTIONS.get(name) or inspect.cleandoc(fn.__doc__ or "")
        return StructuredTool.from_function(
            coroutine=fn, name=name, description=description, return_direct=return_direct
        )

    tools = [make(ask_analyst, "ask_analyst")]
    if inputs.get("labs_enabled"):
        tools.append(make(ask_wellness, "ask_wellness"))
    return [
        *tools,
        make(consult_planning, "consult_planning"),
        make(consult_nutrition, "consult_nutrition"),
        make(propose_changes, "propose_changes", return_direct=True),
        make(remember, "remember"),
        make(forget, "forget"),
    ]


def classify(calls: list[dict[str, Any]]) -> Route:
    names = {c["name"] for c in calls}
    handoffs = {HANDOFFS[name] for name in names if name in HANDOFFS}
    if handoffs == {"planning", "nutrition"}:
        return "both"
    if "planning" in handoffs:
        return "planning"
    if "nutrition" in handoffs:
        return "nutrition"
    if "ask_wellness" in names:
        return "wellness"
    if "ask_analyst" in names:
        return "analyst"
    return "none"


async def run_case(model: BaseChatModel, inputs: dict[str, Any]) -> dict[str, Any]:
    prompt = "\n\n".join(
        [COACH_RULES.format(max_consults=MAX_CONSULTS), inputs["context"], inputs["memory"]]
    )
    history = convert_to_messages(inputs["messages"])
    agent = make_subagent(model, stub_tools(inputs), prompt)
    out = await agent.ainvoke({"messages": history}, {"recursion_limit": TARGET_RECURSION_LIMIT})
    new = out["messages"][len(history) :]
    calls: list[dict[str, Any]] = [
        {"name": tc["name"], "args": tc["args"]}
        for m in new
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    ]
    return {
        "calls": calls,
        "route": classify(calls),
        "briefs": [str(c["args"].get("instruction", "")) for c in calls if c["name"] in HANDOFFS],
        "answer": last_ai_text(new),
    }


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(model, inputs)

    return target
