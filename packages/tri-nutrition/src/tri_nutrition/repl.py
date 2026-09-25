"""Terminal REPL for the nutrition graph: stream a turn, show node activity, run the review
dialogue, render the horizon table.

With `subgraphs=True` every stream event is (namespace, mode, data). The namespace is () for the
parent graph and ("intake:<id>",) or ("checkin:<id>",) inside a sub-agent. An interrupt shows up
as an "updates" event whose only key is "__interrupt__".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_core.harness.turns import GraphTurnPrinter, run_graph_turn
from tri_core.harness.turns import Out as Out
from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    RaceFuelPlan,
    ReviewDecision,
    SessionFuel,
)
from tri_nutrition.prompts.checkin import CHECKIN_REQUEST

CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[NutritionChange]], Awaitable[list[NutritionChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Nodes that host a sub-agent: their text was already streamed token by token, so the parent
# update that carries the same messages is not echoed again.
STREAMED_NODES = frozenset({"intake", "checkin"})


def render_targets(targets: list[DayTarget]) -> str:
    lines = [f"{'day':10}  {'type':9}  {'kcal':>5}  {'C/P/F g':>13}  {'train':>5}  notes"]
    for t in targets:
        macros = f"{t.carbs_g}/{t.protein_g}/{t.fat_g}"
        lines.append(
            f"{t.day.isoformat():10}  {t.day_type:9}  {t.total_kcal:>5}  {macros:>13}  "
            f"{t.session_kcal:>5}  {', '.join(t.notes)}"
        )
    return "\n".join(lines)


def render_fuel(fuels: list[SessionFuel], violations: dict[str, list[str]]) -> str:
    if not fuels:
        return "No sessions in the horizon need a fueling plan."
    lines = [f"{'day':10}  {'workout':10}  {'carbs':>8}  {'fluid':>7}  {'sodium':>7}  products"]
    for f in fuels:
        lines.append(
            f"{f.day.isoformat():10}  {f.tp_workout_id:10.10}  {f.carbs_g_per_h:>4} g/h  "
            f"{f.fluid_ml_per_h:>4} ml  {f.sodium_mg_per_h:>4} mg  {', '.join(f.products)}"
        )
        v = violations.get(f.tp_workout_id)
        if v:
            lines.append(f"    VIOLATIONS: {'; '.join(v)}")
    return "\n".join(lines)


def render_race(plan: RaceFuelPlan, violations: list[str]) -> str:
    lines = [f"Race fuel {plan.event_date}:"]
    for s in plan.timeline:
        prod = f" [{', '.join(s.products)}]" if s.products else ""
        lines.append(
            f"  {s.offset_min:>5} min  {s.leg:5}  {s.what}{prod}: {s.carbs_g} g carbs, "
            f"{s.fluid_ml} ml, {s.sodium_mg} mg Na, {s.caffeine_mg} mg caffeine"
        )
    t = plan.totals_per_h
    lines.append(
        f"  per hour: bike {t.get('bike_carbs', '-')} g/h carbs, {t.get('bike_fluid', '-')} ml, "
        f"{t.get('bike_sodium', '-')} mg Na; run {t.get('run_carbs', '-')} g/h carbs, "
        f"{t.get('run_fluid', '-')} ml, {t.get('run_sodium', '-')} mg Na"
    )
    lines += [f"  if: {c}" for c in plan.contingencies]
    if violations:
        lines.append("  VIOLATIONS: " + "; ".join(violations))
    return "\n".join(lines)


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> GraphTurnPrinter:
    return await run_graph_turn(graph, payload, thread_id, out, streamed_nodes=STREAMED_NODES)


def render_review(payload: dict[str, Any]) -> str:
    changes = [NutritionChange.model_validate(c) for c in payload.get("changes", [])]
    lines: list[str] = []
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
    ops = sorted({c.op for c in changes})
    n = len(changes)
    lines.append(f"{n} change{'s' if n != 1 else ''} ({', '.join(ops)}). {REVIEW_PROMPT}")
    return "\n".join(lines)


def parse_decision(line: str) -> ReviewDecision | None:
    word, _, rest = line.strip().partition(" ")
    if word == "approve":
        return ReviewDecision(action="approve")
    if word == "reject":
        return ReviewDecision(action="reject", note=rest.strip() or None)
    if word == "edit":
        return ReviewDecision(action="edit")
    return None


def changes_to_yaml(changes: list[NutritionChange]) -> str:
    return yaml.safe_dump(
        [c.model_dump(mode="json", exclude_none=True) for c in changes], sort_keys=False
    )


def changes_from_yaml(text: str) -> list[NutritionChange]:
    return [NutritionChange.model_validate(d) for d in (yaml.safe_load(text) or [])]


async def _review_dialogue(
    payload: dict[str, Any],
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    edit: EditFn | None,
) -> ReviewDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None:
            return None
        if line.strip() == "/pending":
            out(render_review(payload) + "\n")
            continue
        if line.strip() == "/quit":
            return None
        decision = parse_decision(line)
        if decision is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        if decision.action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            changes = [NutritionChange.model_validate(c) for c in payload.get("changes", [])]
            edited = await edit(changes)
            if edited is None:
                out("edit cancelled\n")
                continue
            decision = ReviewDecision(action="edit", changes=edited)
        return decision


async def chat_loop(
    graph: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    thread_id: str = "nutrition",
    commands: dict[str, CommandFn] | None = None,
    edit: EditFn | None = None,
) -> None:
    commands = dict(commands or {})
    names = ", ".join(sorted(["quit", "pending", *commands]))
    out(f"tri-nutrition chat. Type a message, /quit to exit, /<command> for: {names}\n")
    pending: dict[str, Any] | None = None
    while True:
        if pending is not None:
            decision = await _review_dialogue(pending, read, out, edit)
            if decision is None:
                out("\n")
                return
            resume: Command[Any] = Command(
                resume=decision.model_dump(mode="json", exclude_none=True)
            )
            printer = await run_turn(graph, resume, thread_id, out)
            pending = printer.interrupt
            continue
        line = await read()
        if line is None:
            out("\n")
            return
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            name = line[1:].split()[0]
            if name == "quit":
                return
            if name == "pending":
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                changes = snap.values.get("pending_changes") or []
                if not changes:
                    out("nothing pending\n")
                else:
                    pending = {
                        "summary": snap.values.get("pending_summary") or "",
                        "changes": [c.model_dump(mode="json") for c in changes],
                        "last_error": snap.values.get("last_error"),
                    }
                continue
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        printer = await run_turn(graph, {"messages": [HumanMessage(line)]}, thread_id, out)
        pending = printer.interrupt


PAUSED_HINT = "paused at review; run `tri-nutrition chat` to answer approve / reject <note> / edit"
ALREADY_PAUSED_HINT = (
    "a change set is already waiting at review; resolve it in `tri-nutrition chat` first"
)
RACE_VIOLATIONS_KEY = "race"  # the race plan's key in pending_violations (sessions use their id)


def violations_for(change: NutritionChange, violations: dict[str, list[str]]) -> list[str]:
    """The fuel violations behind one proposed note, from the review payload's `violations`."""
    if change.op == "set_session_note":
        return list(violations.get(change.target_key) or [])
    if change.op == "set_race_note":
        return list(violations.get(RACE_VIOLATIONS_KEY) or [])
    return []


def split_violating(
    changes: list[NutritionChange], violations: dict[str, list[str]]
) -> tuple[list[NutritionChange], list[tuple[NutritionChange, list[str]]]]:
    """(the clean changes in order, [(violating change, its violations)])."""
    clean: list[NutritionChange] = []
    skipped: list[tuple[NutritionChange, list[str]]] = []
    for c in changes:
        v = violations_for(c, violations)
        if v:
            skipped.append((c, v))
        else:
            clean.append(c)
    return clean, skipped


async def checkin_run(graph: Any, *, thread_id: str, out: Out, approve: bool) -> int:
    """One unattended check-in. 0: nothing pending, or approved in full; 1: approved with the
    violating changes skipped (each is printed with its violations); 3: a change set waits at
    review, either this run's without `approve`, or one an earlier run left, which is never
    approved here."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    if snap.next == ("review",):
        values = snap.values or {}
        pending = {
            "summary": values.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in values.get("pending_changes") or []],
            "last_error": values.get("last_error"),
        }
        out("a change set is already waiting at review:\n" + render_review(pending) + "\n")
        out(ALREADY_PAUSED_HINT + "\n")
        return 3
    request = {"messages": [HumanMessage(CHECKIN_REQUEST)]}
    printer = await run_turn(graph, request, thread_id, out)
    if printer.interrupt is None:
        return 0
    out("\n" + render_review(printer.interrupt) + "\n")
    if not approve:
        out(PAUSED_HINT + "\n")
        return 3
    changes = [NutritionChange.model_validate(c) for c in printer.interrupt.get("changes", [])]
    clean, skipped = split_violating(changes, printer.interrupt.get("violations") or {})
    for change, reasons in skipped:
        out(f"skipped {change.op} {change.target_key or change.day}: {'; '.join(reasons)}\n")
    resume: dict[str, Any] = {"action": "approve"}
    if skipped:
        resume = {"action": "edit", "changes": [c.model_dump(mode="json") for c in clean]}
    printer = await run_turn(graph, Command(resume=resume), thread_id, out)
    if printer.interrupt is not None:
        return 3
    return 1 if skipped else 0
