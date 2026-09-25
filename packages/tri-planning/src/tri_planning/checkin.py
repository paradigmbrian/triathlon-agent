"""Non-interactive review: one graph turn with the fixed check-in prompt.

Exit codes: 0 applied or nothing to do, 1 model/API error, apply failure, or a week skipped
for validator violations under --yes, 2 no active plan, 3 paused at review.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.prompts.checkin import CHECKIN_PROMPT
from tri_planning.repl import Out, render_changes, run_turn

EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3


def changes_without_violations(
    payload: dict[str, Any],
) -> tuple[list[CalendarChange], list[str]]:
    """The review payload's changes minus every change dated inside a week that has validator
    violations, and those weeks (ISO Mondays, sorted). A change without a date is kept."""
    violations: dict[str, list[str]] = payload.get("violations") or {}
    kept = [
        c
        for c in (CalendarChange.model_validate(x) for x in payload.get("changes", []))
        if c.workout_date is None or week_monday(c.workout_date).isoformat() not in violations
    ]
    return kept, sorted(violations)


async def run_checkin(
    graph: Any, *, phase: str, yes: bool, out: Out, thread_id: str = "planning"
) -> int:
    """Run one check-in turn. `phase` is derived from the tables by the caller
    (`repo.derive_phase`), not read from the thread. See module docstring for exit codes."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    values = snap.values or {}
    pending = values.get("pending_changes") or []
    if snap.next or pending:
        # A thread paused at review belongs to whoever started it; --yes must not approve a
        # change set this check-in did not propose.
        out(
            render_changes(
                {
                    "summary": values.get("pending_summary") or "",
                    "changes": [c.model_dump(mode="json") for c in pending],
                    "violations": values.get("pending_violations") or {},
                    "last_error": values.get("last_error"),
                }
            )
            + "\n"
        )
        out("check-in: a review is already pending; resolve it in `tri-planning chat` first\n")
        return EXIT_PAUSED
    if phase != "active":
        out("check-in: no active plan; run `tri-planning chat` to set a goal first\n")
        return EXIT_NO_PLAN
    printer = await run_turn(graph, {"messages": [HumanMessage(CHECKIN_PROMPT)]}, thread_id, out)
    if printer.error is not None:
        return EXIT_ERROR
    if printer.interrupt is None:
        return EXIT_OK
    out(render_changes(printer.interrupt) + "\n")
    if not yes:
        out("check-in: paused at review; run `tri-planning chat` and type /pending to decide\n")
        return EXIT_PAUSED
    kept, skipped = changes_without_violations(printer.interrupt)
    resume: dict[str, Any] = {"action": "approve"}
    if skipped:
        # A designed week that still fails validation is not written unattended: resume with
        # an edit holding the other weeks' changes, and exit 1 so the cron run is noticed.
        for week in skipped:
            reasons = "; ".join(printer.interrupt["violations"][week])
            out(f"check-in: skipping week of {week}: {reasons}\n")
        out(f"check-in: --yes given, approving {len(kept)} change(s) from other weeks\n")
        resume = {"action": "edit", "changes": [c.model_dump(mode="json") for c in kept]}
    else:
        out("check-in: --yes given, approving\n")
    printer = await run_turn(graph, Command(resume=resume), thread_id, out)
    if printer.error is not None:
        return EXIT_ERROR
    if printer.interrupt is not None:
        return EXIT_PAUSED
    # The apply node reports a failed or partial write through state, not an interrupt.
    after = (await graph.aget_state(cfg)).values or {}
    if after.get("last_error") or after.get("pending_changes"):
        reason = after.get("last_error") or "changes still pending"
        out(f"check-in: apply did not complete: {reason}\n")
        return EXIT_ERROR
    return EXIT_ERROR if skipped else EXIT_OK
