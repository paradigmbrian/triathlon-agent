"""tri-coach check-in: one unattended coach turn with the fixed check-in request on thread coach.

Exit codes, as `tri-planning check-in`: 0 a clean week, or every gate approved and applied;
1 a model or API error, an apply that did not complete, or a change skipped under --yes for
validator violations; 2 neither an active plan nor a nutrition profile; 3 paused at review, or
refused because a review or a held change set is already pending (its owner decides it in chat,
and --yes must not approve it) or the thread stopped mid-run. --yes approves the change set and
a second gate only when it is the nutrition follow-on, and never a change a validator flagged:
a designed week with violations, or a fuel note with violations."""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_coach.models import Proposal
from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_coach.repl import Out, paused_review, render_review, run_turn
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.repl import split_violating
from tri_planning.checkin import changes_without_violations

EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3
CHECKIN_TAGS = ["checkin"]
MAX_GATES = 2  # the change set and its nutrition follow-on (spec 6.5)
PAUSED_HINT = "check-in: paused at review; run `tri-coach chat` and type /pending to decide"


def _is_nutrition_follow_on(payload: dict[str, Any]) -> bool:
    proposals = payload.get("proposals") or []
    return bool(proposals) and all(p.get("domain") == "nutrition" for p in proposals)


def without_violations(payload: dict[str, Any]) -> tuple[list[Proposal], list[str]]:
    """The review payload's proposals with every change a validator flagged left out, and one
    line per skip. Each domain decides what a violation covers, as its own check-in does: a
    designed week (tri-planning), a session or race note (tri-nutrition)."""
    kept: list[Proposal] = []
    skipped: list[str] = []
    for raw in payload.get("proposals") or []:
        p = Proposal.model_validate(raw)
        keyed = p.pending_violations
        if p.domain == "planning":
            dumped = [c.model_dump(mode="json") for c in p.changes]
            weeks_clean, weeks = changes_without_violations(
                {"changes": dumped, "violations": keyed}
            )
            skipped += [f"{p.id} week of {w}: " + "; ".join(keyed[w]) for w in weeks]
            kept.append(p.model_copy(update={"changes": weeks_clean}))
        else:
            clean, flagged = split_violating(cast(list[NutritionChange], p.changes), keyed)
            skipped += [
                f"{p.id} {c.op} {c.target_key or c.day}: " + "; ".join(v) for c, v in flagged
            ]
            kept.append(p.model_copy(update={"changes": clean}))
    return kept, skipped


async def run_checkin(
    graph: Any,
    *,
    has_plan: bool,
    has_profile: bool,
    yes: bool,
    out: Out,
    thread_id: str = "coach",
) -> int:
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    paused = paused_review(snap)
    held = (snap.values or {}).get("pending") if snap is not None else None
    if paused is None and held is None and snap is not None and snap.next:
        at = ", ".join(snap.next)
        out(
            f"check-in: the coach thread stopped mid-run at {at}; "
            "send any message in `tri-coach chat` to clear it\n"
        )
        return EXIT_PAUSED
    if paused is not None or held is not None:
        if paused is not None:
            out(render_review(paused) + "\n")
        elif held is not None:
            proposals = [p.model_dump(mode="json") for p in held.proposals]
            out(render_review({"narration": held.narration, "proposals": proposals}) + "\n")
        out("check-in: a change set is already pending; decide it in `tri-coach chat` (/pending)\n")
        return EXIT_PAUSED
    if not has_plan and not has_profile:
        out("check-in: no active plan and no nutrition profile; start in `tri-coach chat`\n")
        return EXIT_NO_PLAN
    request = {"messages": [HumanMessage(CHECKIN_REQUEST)]}
    printer = await run_turn(graph, request, thread_id, out, tags=CHECKIN_TAGS)
    gates = skipped = 0
    while True:
        if printer.error is not None:
            return EXIT_ERROR
        if printer.interrupt is None:
            break
        out("\n" + render_review(printer.interrupt) + "\n")
        if not yes or gates >= MAX_GATES:
            out(PAUSED_HINT + "\n")
            return EXIT_PAUSED
        if gates == 1 and not _is_nutrition_follow_on(printer.interrupt):
            # --yes covers the change set and its nutrition follow-on, never a second plan change
            out("check-in: the second gate is not the nutrition follow-on; --yes stops here\n")
            out(PAUSED_HINT + "\n")
            return EXIT_PAUSED
        gates += 1
        kept, flagged = without_violations(printer.interrupt)
        resume: dict[str, Any] = {"action": "approve"}
        if flagged:
            # An unattended run never writes a change a validator flagged: the rest go through
            # as an edit, and the run exits 1 so the cron run is noticed.
            for line in flagged:
                out(f"check-in: skipping {line}\n")
            skipped += len(flagged)
            out("check-in: --yes given, approving the changes without violations\n")
            resume = {"action": "edit", "proposals": [p.model_dump(mode="json") for p in kept]}
        else:
            out("check-in: --yes given, approving\n")
        command: Command[Any] = Command(resume=resume)
        printer = await run_turn(graph, command, thread_id, out, tags=CHECKIN_TAGS)
    if gates:
        # apply reports a failed or partial write through state, not an interrupt
        after = (await graph.aget_state(cfg)).values or {}
        if after.get("last_error") or after.get("pending") is not None:
            reason = after.get("last_error") or "changes still pending"
            out(f"check-in: apply did not complete: {reason}\n")
            return EXIT_ERROR
    return EXIT_ERROR if skipped else EXIT_OK
