"""Terminal REPL for the coach graph: stream a turn, label sub-graph activity, run the review
dialogue over both domains.

Events are (namespace, mode, data). The namespace is () for the coach graph's own nodes,
("coach:<id>",) inside the coach sub-agent, ("planning:<id>", ...) and ("nutrition:<id>", ...)
inside a consultation; the first segment's name is the label. ask_analyst runs its own agent
inside a tool, which streams at the root namespace under nodes `model` and `tools`; the coach
graph has no such nodes, so those events are the analyst's."""

from __future__ import annotations

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

from tri_coach.models import Proposal, ReviewDecision
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.repl import render_review as render_nutrition
from tri_planning.repl import render_changes as render_planning

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[Proposal]], Awaitable[list[Proposal] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Only a consultation's output is tagged: the coach speaks to the athlete in its own voice.
TAGGED = frozenset({"planning", "nutrition"})
# Nodes of the coach graph itself; any other node at the root namespace belongs to the analyst.
ROOT_NODES = frozenset({"start", "coach", "planning", "nutrition", "review", "apply"})


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(
        str(b.get("text", ""))
        if isinstance(b, dict) and b.get("type") == "text"
        else (b if isinstance(b, str) else "")
        for b in content
    )


def label(namespace: tuple[str, ...]) -> str:
    return namespace[0].split(":", 1)[0] if namespace else ""


def _tag(where: str, node: str = "") -> str:
    """The bracket label: a consultation's, the analyst's, or "" for the coach and the root."""
    if where in TAGGED:
        return where
    if not where and node in ("model", "tools"):
        return "analyst"
    return ""


class TurnPrinter:
    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
        self.error: str | None = None
        self._line_label = ""  # tag printed at the start of the current streamed line

    def _stream(self, where: str, node: str, text: str) -> None:
        tag = _tag(where, node)
        if self._line_label != tag:
            self.out(f"\n[{tag}] " if tag else "\n")
            self._line_label = tag
        self.out(text)

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        where = label(namespace)
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = _text_of(chunk)
                if text:
                    self._stream(where, "model", text)
                    if where == "coach":
                        self.final_text += text
            return
        if mode != "updates" or not isinstance(data, dict):
            return
        if "__interrupt__" in data:
            self.interrupt = dict(data["__interrupt__"][0].value)
            return
        for node, payload in data.items():
            tag = _tag(where, node)
            prefix = f"[{tag}] " if tag else ""
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n{prefix}→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls and (where or tag):
                        if where == "coach":
                            self.final_text = _text_of(msg) or self.final_text
                        self.out("\n")  # close the streamed line
                    self._line_label = ""
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self._line_label = ""
                    self.out(f"{prefix}← {msg.name}: {len(_text_of(msg))} chars\n")
                elif (
                    not where and node in ("planning", "nutrition") and isinstance(msg, ToolMessage)
                ):  # a consultation's result, once, from the coach graph's own node
                    self.out(f"← {msg.name}: {_text_of(msg)}\n")
                elif (
                    not where
                    and node in ("apply", "review", "nutrition")
                    and isinstance(msg, AIMessage | HumanMessage)
                ):
                    text = _text_of(msg)
                    self.out(f"{text}\n")
                    if isinstance(msg, AIMessage):
                        self.final_text = text


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> TurnPrinter:
    printer = TurnPrinter(out)
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    try:
        async for namespace, mode, data in graph.astream(
            payload, config=cfg, stream_mode=["messages", "updates"], subgraphs=True
        ):
            printer.on_event(tuple(namespace), mode, data)
    except anthropic.RateLimitError as exc:
        printer.error = f"\n[rate limited: {exc}. Wait a moment and try again.]\n"
        out(printer.error)
    except anthropic.APIStatusError as exc:
        printer.error = f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n"
        out(printer.error)
    except anthropic.APIConnectionError as exc:
        printer.error = f"\n[connection error talking to Anthropic: {exc}]\n"
        out(printer.error)
    except Exception as exc:  # noqa: BLE001 - the chat keeps the state at the last checkpoint
        printer.error = f"\n[the turn failed: {type(exc).__name__}: {exc}]\n"
        out(printer.error)
    return printer


def render_review(payload: dict[str, Any]) -> str:
    proposals = [Proposal.model_validate(p) for p in payload.get("proposals", [])]
    lines = [str(payload.get("narration") or ""), ""]
    for p in proposals:
        lines.append(f"-- {p.domain} ({p.id}): {p.summary}")
        sub = {
            "summary": "",
            "changes": [c.model_dump(mode="json") for c in p.changes],
            "last_error": None,
        }
        body = render_planning(sub) if p.domain == "planning" else render_nutrition(sub)
        # each package's renderer ends with its own review prompt line; drop it, one prompt below
        lines += [ln for ln in body.rstrip().split("\n") if not ln.endswith(REVIEW_PROMPT)]
        if p.domain == "nutrition":
            # tri_nutrition's renderer is a one-line count; name the days each change touches
            lines += [
                f"  {c.op} {c.target_key or c.day.isoformat()}: {c.reason}"
                for c in p.changes
                if isinstance(c, NutritionChange)
            ]
        if p.violations:
            lines.append("violations: " + "; ".join(p.violations))
        if p.overrides:
            lines.append(f"profile overrides: {p.overrides}")
        lines.append("")
    n = sum(len(p.changes) for p in proposals)
    lines.append(f"{n} changes across {len(proposals)} proposals. {REVIEW_PROMPT}")
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


def proposals_to_yaml(proposals: list[Proposal]) -> str:
    doc = {p.id: p.model_dump(mode="json", exclude_none=True, exclude={"id"}) for p in proposals}
    return yaml.safe_dump(doc, sort_keys=False)


def proposals_from_yaml(text: str, originals: list[Proposal]) -> list[Proposal]:
    doc = yaml.safe_load(text) or {}
    by_id = {p.id: p for p in originals}
    out: list[Proposal] = []
    for pid, body in doc.items():
        base = by_id.get(str(pid))
        data = {**(base.model_dump(mode="json") if base else {}), **(body or {}), "id": str(pid)}
        out.append(Proposal.model_validate(data))
    return out


async def _review_dialogue(
    payload: dict[str, Any],
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    edit: EditFn | None,
) -> ReviewDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None or line.strip() == "/quit":
            return None
        if line.strip() == "/pending":
            out(render_review(payload) + "\n")
            continue
        decision = parse_decision(line)
        if decision is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        if decision.action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            edited = await edit([Proposal.model_validate(p) for p in payload.get("proposals", [])])
            if edited is None:
                out("edit cancelled\n")
                continue
            decision = ReviewDecision(action="edit", proposals=edited)
        return decision


def _paused_review(snap: Any) -> dict[str, Any] | None:
    """The interrupt payload of a review that is still waiting, from a state snapshot."""
    if snap is None or getattr(snap, "next", ()) != ("review",):
        return None
    tasks = getattr(snap, "tasks", ()) or ()
    if tasks and tasks[0].interrupts:
        return dict(tasks[0].interrupts[0].value)
    return None


async def chat_loop(
    graph: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    thread_id: str = "coach",
    commands: dict[str, CommandFn] | None = None,
    edit: EditFn | None = None,
) -> None:
    commands = dict(commands or {})
    names = ", ".join(sorted(["quit", "pending", *commands]))
    out(f"tri-coach chat. Type a message, /quit to exit, /<command> for: {names}\n")
    # A review the athlete walked away from is still paused in the checkpoint: finish it first,
    # or the next typed message makes LangGraph drop the unfinished task and the change set.
    pending = _paused_review(await graph.aget_state({"configurable": {"thread_id": thread_id}}))
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
            parts = line[1:].split()
            if not parts:  # a bare "/" is not a command
                continue
            name = parts[0]
            if name == "quit":
                return
            if name == "pending":
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                paused = _paused_review(snap)
                if paused is not None:
                    pending = paused
                elif snap.values.get("pending") is not None:
                    held = snap.values["pending"]
                    out(
                        render_review(
                            {
                                "narration": held.narration,
                                "proposals": [p.model_dump(mode="json") for p in held.proposals],
                            }
                        )
                        + "\n(held from an earlier apply; ask the coach to re-propose it)\n"
                    )
                else:
                    out("nothing pending\n")
                continue
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        printer = await run_turn(graph, {"messages": [HumanMessage(line)]}, thread_id, out)
        pending = printer.interrupt
