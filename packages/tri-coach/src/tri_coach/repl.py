"""Terminal REPL for the coach graph: stream a turn, label sub-graph activity, run the review
dialogue over both domains.

Events are (namespace, mode, data). The namespace is () for the coach graph's own nodes,
("coach:<id>",) inside the coach sub-agent, ("planning:<id>", ...) and ("nutrition:<id>", ...)
inside a consultation; the first segment's name is the label. ask_analyst and ask_wellness each
run their own agent inside a tool, which streams at the root namespace under nodes `model` and
`tools`; the coach graph has no such nodes, so those events are the tool's, and the `tool:ask_*`
tag agent_tool puts on the run says which."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import yaml
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from tri_coach.models import Proposal, ReviewDecision
from tri_core.harness.messages import text_of
from tri_core.harness.turns import Out as Out  # re-exported: tri_coach.checkin imports it
from tri_core.harness.turns import format_failure, stream_turn, turn_config
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.repl import render_review as render_nutrition
from tri_planning.repl import render_changes as render_planning

CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[Proposal]], Awaitable[list[Proposal] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Only a consultation's output is tagged: the coach speaks to the athlete in its own voice.
TAGGED = frozenset({"planning", "nutrition"})
# Nodes of the coach graph itself; any other node at the root namespace belongs to an agent tool.
ROOT_NODES = frozenset({"start", "coach", "planning", "nutrition", "review", "apply"})
# agent_tool tags each run "tool:<name>"; the coach's agent tools are ask_analyst and ask_wellness.
TOOL_TAG_PREFIX = "tool:ask_"


Event = tuple[str, dict[str, Any]]


def label(namespace: tuple[str, ...]) -> str:
    return namespace[0].split(":", 1)[0] if namespace else ""


def tool_speaker(tags: Sequence[str]) -> str:
    """The agent tool a run's tags name ("analyst", "wellness"); the analyst when none does."""
    for tag in tags:
        if tag.startswith(TOOL_TAG_PREFIX):
            return tag[len(TOOL_TAG_PREFIX) :]
    return "analyst"


def _tag(where: str, node: str = "", tags: Sequence[str] = ()) -> str:
    """The bracket label: a consultation's, the agent tool's, or "" for the coach and the root."""
    if where in TAGGED:
        return where
    if not where and node in ("model", "tools"):
        return tool_speaker(tags)
    return ""


def where_of(namespace_label: str, node: str, tags: Sequence[str] = ()) -> str:
    """Who is speaking: the tag, or "coach" for the coach's own voice and the root nodes. `tags`
    are the run's, from the messages stream metadata; they say which agent tool is at the root."""
    return _tag(namespace_label, node, tags) or "coach"


class TurnClassifier:
    """Raw stream events in, (kind, payload) tuples out. Kinds: token, tool_call, assistant,
    tool_result, consult, report, interrupt. Tracks the coach's final text and the interrupt."""

    def __init__(self) -> None:
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
        self._root_tags: list[str] = []  # the last root model call's tags: which agent tool

    def classify(self, namespace: tuple[str, ...], mode: str, data: Any) -> list[Event]:
        where = label(namespace)
        if mode == "messages":
            chunk, meta = data
            if not where and meta.get("tags"):
                # updates carry no tags: the root run's model and tools nodes are labelled by
                # the tags its model call streamed with
                self._root_tags = list(meta["tags"])
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    if where == "coach":
                        self.final_text += text
                    who = where_of(where, "model", self._root_tags)
                    return [("token", {"where": who, "text": text})]
            return []
        if mode != "updates" or not isinstance(data, dict):
            return []
        if "__interrupt__" in data:
            self.interrupt = dict(data["__interrupt__"][0].value)
            return [("interrupt", self.interrupt)]
        events: list[Event] = []
        for node, payload in data.items():
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    who = where_of(where, node, self._root_tags)
                    for tc in msg.tool_calls:
                        events.append(
                            ("tool_call", {"where": who, "name": tc["name"], "args": tc["args"]})
                        )
                    if not msg.tool_calls:
                        text = text_of(msg)
                        if where == "coach" and text:
                            self.final_text = text
                        events.append(("assistant", {"where": who, "text": text}))
                elif node == "tools" and isinstance(msg, ToolMessage):
                    events.append(
                        (
                            "tool_result",
                            {
                                "where": where_of(where, node, self._root_tags),
                                "name": msg.name,
                                "chars": len(text_of(msg)),
                            },
                        )
                    )
                elif (
                    not where and node in ("planning", "nutrition") and isinstance(msg, ToolMessage)
                ):  # a consultation's result, once, from the coach graph's own node
                    events.append(
                        ("consult", {"domain": node, "name": msg.name, "text": text_of(msg)})
                    )
                elif (
                    not where
                    and node in ("apply", "review", "nutrition")
                    and isinstance(msg, AIMessage | HumanMessage)
                ):
                    text = text_of(msg)
                    if isinstance(msg, AIMessage):
                        self.final_text = text
                    role = "ai" if isinstance(msg, AIMessage) else "human"
                    events.append(("report", {"text": text, "node": node, "role": role}))
        return events


class TurnPrinter:
    """Formats the classifier's events for the terminal. Subclasses override print_event."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.classifier = TurnClassifier()
        self.error: str | None = None
        self._line_label = ""  # tag printed at the start of the current streamed line

    @property
    def final_text(self) -> str:
        return self.classifier.final_text

    @property
    def interrupt(self) -> dict[str, Any] | None:
        return self.classifier.interrupt

    def _stream(self, tag: str, text: str) -> None:
        if self._line_label != tag:
            self.out(f"\n[{tag}] " if tag else "\n")
            self._line_label = tag
        self.out(text)

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        for kind, payload in self.classifier.classify(namespace, mode, data):
            self.print_event(kind, payload)

    def print_event(self, kind: str, payload: dict[str, Any]) -> None:
        where = payload.get("where", "coach")
        tag = "" if where == "coach" else where
        prefix = f"[{tag}] " if tag else ""
        if kind == "token":
            self._stream(tag, payload["text"])
        elif kind == "tool_call":
            self.out(f"\n{prefix}→ {payload['name']}({payload['args']})\n")
            self._line_label = ""
        elif kind == "assistant":
            self.out("\n")  # close the streamed line
            self._line_label = ""
        elif kind == "tool_result":
            self._line_label = ""
            self.out(f"{prefix}← {payload['name']}: {payload['chars']} chars\n")
        elif kind == "consult":
            self.out(f"← {payload['name']}: {payload['text']}\n")
        elif kind == "report":
            self.out(f"{payload['text']}\n")


async def run_turn(
    graph: Any,
    payload: dict[str, Any] | Command[Any],
    thread_id: str,
    out: Out,
    *,
    tags: list[str] | None = None,
    printer: TurnPrinter | None = None,
) -> TurnPrinter:
    """One coach turn. Any failure is printed and kept in `printer.error`; the chat keeps the
    state at the last checkpoint."""
    printer = printer or TurnPrinter(out)
    failure = await stream_turn(
        graph,
        payload,
        turn_config(thread_id, tags=tags, recursion_limit=60),
        printer,
        subgraphs=True,
        catch_all="the turn failed",
    )
    if failure is not None:
        printer.error = format_failure(failure)
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
    commands: dict[str, CommandFn],
) -> ReviewDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None or line.strip() == "/quit":
            return None
        text = line.strip()
        if text == "/pending":
            out(render_review(payload) + "\n")
            continue
        if text.startswith("/"):
            parts = text[1:].split()
            name = parts[0] if parts else ""
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}; {REVIEW_PROMPT}\n")
            else:
                out(await handler() + "\n")
            continue
        decision = parse_decision(text)
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


def paused_review(snap: Any) -> dict[str, Any] | None:
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
    pending = paused_review(await graph.aget_state({"configurable": {"thread_id": thread_id}}))
    while True:
        if pending is not None:
            decision = await _review_dialogue(pending, read, out, edit, commands)
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
                paused = paused_review(snap)
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
