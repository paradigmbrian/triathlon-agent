"""Non-interactive review: one graph turn with the fixed check-in prompt."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_planning.prompts.checkin import CHECKIN_PROMPT
from tri_planning.repl import Out, render_changes, run_turn

EXIT_OK, EXIT_NO_PLAN, EXIT_PAUSED = 0, 2, 3


async def run_checkin(graph: Any, *, yes: bool, out: Out, thread_id: str = "planning") -> int:
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = snap.values or {}
    if values.get("phase") != "active" and not values.get("pending_changes"):
        out("check-in: no active plan; run `tri-planning chat` to set a goal first\n")
        return EXIT_NO_PLAN
    printer = await run_turn(graph, {"messages": [HumanMessage(CHECKIN_PROMPT)]}, thread_id, out)
    if printer.interrupt is None:
        return EXIT_OK
    out(render_changes(printer.interrupt) + "\n")
    if not yes:
        out("check-in: paused at review; run `tri-planning chat` and type /pending to decide\n")
        return EXIT_PAUSED
    out("check-in: --yes given, approving\n")
    printer = await run_turn(graph, Command(resume={"action": "approve"}), thread_id, out)
    return EXIT_PAUSED if printer.interrupt is not None else EXIT_OK
