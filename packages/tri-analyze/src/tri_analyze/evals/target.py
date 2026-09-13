"""The function under evaluation: the real analyst agent over stub tools that answer from the
case's canned results. No database, no MCP servers. Exceptions propagate so LangSmith records
the example as errored."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool

from tri_analyze.agent import build_agent
from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.repl import text_of
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool

TARGET_RECURSION_LIMIT = 30
SQL_DESCRIPTION = make_query_tool("postgresql://unused/db").description
LIVE_DESCRIPTIONS = {
    "get_activity": "A Garmin activity summary by activity_id.",
    "get_activity_splits": "Lap and interval detail for a Garmin activity by activity_id.",
    "get_training_readiness": "Garmin training readiness for a date (YYYY-MM-DD).",
    "get_hrv_data": "Garmin overnight HRV for a date (YYYY-MM-DD).",
    "tp_get_workout": "One TrainingPeaks workout with its structure and comments, by workout_id.",
}
EXTRA_DESCRIPTIONS = {
    "read_body_composition": (
        "Index-scale readings for the last `days` days: date, weight_kg, body_fat_pct, "
        "muscle_mass_kg, oldest first."
    ),
    "read_intake_vs_targets": (
        "Logged intake against the nutrition targets for the last `days` days, one row per day."
    ),
}


def athlete_from_inputs(inputs: dict[str, Any]) -> AthleteContext:
    """The inverse of EvalCase.inputs(): ISO strings back to dates."""
    a = inputs["athlete"]
    return AthleteContext(
        today=date.fromisoformat(str(a["today"])),
        profile=a.get("profile"),
        recent_days=[
            {**r, "metric_date": date.fromisoformat(str(r["metric_date"]))}
            for r in a.get("recent_days") or []
        ],
        recent_workouts=[
            {**w, "workout_date": date.fromisoformat(str(w["workout_date"]))}
            for w in a.get("recent_workouts") or []
        ],
    )


class Canned:
    """Serves each tool's responses in call order, repeating the last; "[]" when none."""

    def __init__(self, results: dict[str, list[str]]) -> None:
        self.results = {k: list(v) for k, v in results.items() if v}
        self.served: dict[str, int] = defaultdict(int)

    def __call__(self, name: str) -> str:
        queue = self.results.get(name) or ["[]"]
        i = min(self.served[name], len(queue) - 1)
        self.served[name] += 1
        return queue[i]


def stub_tools(inputs: dict[str, Any]) -> list[BaseTool]:
    """query_training_db (real description), the five live tools when `live`, then each name in
    `extra_tools`. Same names, argument names and order as the real binding."""
    canned = Canned(inputs.get("tool_results") or {})

    async def query_training_db(sql: str) -> str:
        return canned("query_training_db")

    async def get_activity(activity_id: str) -> str:
        return canned("get_activity")

    async def get_activity_splits(activity_id: str) -> str:
        return canned("get_activity_splits")

    async def get_training_readiness(date: str) -> str:
        return canned("get_training_readiness")

    async def get_hrv_data(date: str) -> str:
        return canned("get_hrv_data")

    async def tp_get_workout(workout_id: str) -> str:
        return canned("tp_get_workout")

    async def read_body_composition(days: int = 28) -> str:
        return canned("read_body_composition")

    async def read_intake_vs_targets(days: int = 7) -> str:
        return canned("read_intake_vs_targets")

    live_fns: dict[str, Callable[..., Awaitable[str]]] = {
        "get_activity": get_activity,
        "get_activity_splits": get_activity_splits,
        "get_training_readiness": get_training_readiness,
        "get_hrv_data": get_hrv_data,
        "tp_get_workout": tp_get_workout,
    }
    extra_fns: dict[str, Callable[..., Awaitable[str]]] = {
        "read_body_composition": read_body_composition,
        "read_intake_vs_targets": read_intake_vs_targets,
    }

    def make(fn: Callable[..., Awaitable[str]], name: str, description: str) -> BaseTool:
        # from_function() strips the description; set it back so the SQL stub's description is
        # byte-for-byte the real tool's (SCHEMA_DOC has a trailing newline).
        t = StructuredTool.from_function(coroutine=fn, name=name, description=description)
        t.description = description
        return t

    tools = [make(query_training_db, "query_training_db", SQL_DESCRIPTION)]
    if inputs.get("live"):
        tools += [
            make(live_fns[n], n, LIVE_DESCRIPTIONS[n]) for n in [*GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
        ]
    tools += [make(extra_fns[n], n, EXTRA_DESCRIPTIONS[n]) for n in inputs.get("extra_tools") or []]
    return tools


async def run_case(model: BaseChatModel, inputs: dict[str, Any]) -> dict[str, Any]:
    agent = build_agent(model, stub_tools(inputs))
    out = await agent.ainvoke(
        {"messages": [HumanMessage(str(inputs["question"]))]},
        {
            "configurable": {"thread_id": f"eval-{uuid4()}"},
            "recursion_limit": TARGET_RECURSION_LIMIT,
            "tags": ["eval"],
        },
        context=athlete_from_inputs(inputs),
    )
    messages = out["messages"]
    calls = [
        {"name": tc["name"], "args": tc["args"]}
        for m in messages
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    ]
    answer = next(
        (text_of(m) for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls),
        "",
    )
    return {"calls": calls, "answer": answer}


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(model, inputs)

    return target
