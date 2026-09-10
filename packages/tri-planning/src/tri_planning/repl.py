"""Terminal REPL for the planning graph: stream a turn, show node activity, run the review dialogue.

With `subgraphs=True` every stream event is (namespace, mode, data). The namespace is () for the
parent graph and ("intake:<id>",) inside the intake sub-agent. An interrupt shows up as an
"updates" event whose only key is "__interrupt__".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
import yaml
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from tri_planning.planning.models import CalendarChange, ReviewDecision
from tri_planning.planning.targets import week_monday

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[CalendarChange]], Awaitable[list[CalendarChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Nodes that host a sub-agent: their text was already streamed token by token, so the
# parent update that carries the same messages is not echoed again.
STREAMED_NODES = frozenset({"intake"})


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


class TurnPrinter:
    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = _text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode != "updates" or not isinstance(data, dict):
            return
        if "__interrupt__" in data:
            first = data["__interrupt__"][0]
            self.interrupt = dict(first.value)
            return
        for node, payload in data.items():
            if not namespace and node in STREAMED_NODES:
                continue
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls:
                        self.final_text = _text_of(msg) or self.final_text
                        self.out("\n")
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self.out(f"← {msg.name}: {len(_text_of(msg))} chars\n")
                elif not namespace and isinstance(msg, AIMessage):
                    text = _text_of(msg)
                    self.out(f"[{node}] {text}\n")
                    self.final_text = text


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> TurnPrinter:
    printer = TurnPrinter(out)
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        async for namespace, mode, data in graph.astream(
            payload, config=cfg, stream_mode=["messages", "updates"], subgraphs=True
        ):
            printer.on_event(tuple(namespace), mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    return printer


def render_changes(payload: dict[str, Any]) -> str:
    changes = [CalendarChange.model_validate(c) for c in payload.get("changes", [])]
    lines: list[str] = []
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
    by_week: dict[str, list[CalendarChange]] = defaultdict(list)
    for c in changes:
        key = str(week_monday(c.workout_date)) if c.workout_date else "(no date)"
        by_week[key].append(c)
    lines.append(
        f"{'date':10}  {'sport':8}  {'op':11}  {'title':28}  {'min':>4}  {'tss':>4}  reason"
    )
    for key in sorted(by_week):
        lines.append(f"-- week of {key}")
        for c in by_week[key]:
            w = c.workout
            title = w.title if w else (c.tp_workout_id or "")
            minutes = str(w.duration_minutes) if w else ""
            tss = f"{w.tss_planned:.0f}" if w else ""
            lines.append(
                f"{str(c.workout_date or ''):10}  {(w.sport if w else ''):8}  {c.op:11}  "
                f"{title:28.28}  {minutes:>4}  {tss:>4}  {c.reason[:60]}"
            )
    lines.append(f"{len(changes)} changes. {REVIEW_PROMPT}")
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


def changes_to_yaml(changes: list[CalendarChange]) -> str:
    return yaml.safe_dump(
        [c.model_dump(mode="json", exclude_none=True) for c in changes], sort_keys=False
    )


def changes_from_yaml(text: str) -> list[CalendarChange]:
    return [CalendarChange.model_validate(d) for d in (yaml.safe_load(text) or [])]


async def _review_dialogue(
    payload: dict[str, Any],
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    edit: EditFn | None,
) -> ReviewDecision | None:
    out(render_changes(payload) + "\n")
    while True:
        line = await read()
        if line is None:
            return None
        if line.strip() == "/pending":
            out(render_changes(payload) + "\n")
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
            changes = [CalendarChange.model_validate(c) for c in payload.get("changes", [])]
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
    thread_id: str = "planning",
    commands: dict[str, CommandFn] | None = None,
    edit: EditFn | None = None,
) -> None:
    commands = dict(commands or {})
    names = ", ".join(sorted(["quit", "pending", *commands]))
    out(f"tri-planning chat. Type a message, /quit to exit, /<command> for: {names}\n")
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
