"""The turn driver every REPL shares: one stream loop that feeds a sink, and the sentences an
Anthropic error becomes. The loop never prints; the drivers decide how a failure reads."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command

from tri_core.harness.messages import text_of

Out = Callable[[str], None]

DEFAULT_RATE_LIMIT_HINT = "Wait a moment and try again."
DEFAULT_STREAM_MODES = ("messages", "updates")


class TurnSink(Protocol):
    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None: ...


@dataclass(frozen=True)
class TurnFailure:
    exc: Exception
    message: str  # no brackets or newlines


def api_error_message(
    exc: BaseException, *, rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT
) -> str | None:
    """The sentence for an Anthropic error, or None for anything else. RateLimitError is an
    APIStatusError, so it is checked first."""
    if isinstance(exc, anthropic.RateLimitError):
        return f"rate limited: {exc}. {rate_limit_hint}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return f"connection error talking to Anthropic: {exc}"
    return None


def turn_config(
    thread_id: str, *, tags: Sequence[str] | None = None, recursion_limit: int | None = None
) -> dict[str, Any]:
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if recursion_limit is not None:
        cfg["recursion_limit"] = recursion_limit
    if tags:
        cfg["tags"] = list(tags)
    return cfg


async def stream_turn(
    runnable: Any,
    payload: Any,
    config: dict[str, Any],
    sink: TurnSink,
    *,
    subgraphs: bool,
    stream_mode: str | Sequence[str] | None = None,
    context: Any = None,
    catch_all: str | None = None,
    rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT,
) -> TurnFailure | None:
    """Stream one run into `sink` as (namespace, mode, data). An Anthropic error, or any error
    when `catch_all` names the failure, ends the run as a TurnFailure; anything else propagates.
    `subgraphs` and `context` reach astream only when set."""
    mode: str | list[str]
    if stream_mode is None:
        mode = list(DEFAULT_STREAM_MODES)
    elif isinstance(stream_mode, str):
        mode = stream_mode
    else:
        mode = list(stream_mode)
    kwargs: dict[str, Any] = {"config": config, "stream_mode": mode}
    if subgraphs:
        kwargs["subgraphs"] = True
    if context is not None:
        kwargs["context"] = context
    try:
        async for item in runnable.astream(payload, **kwargs):
            if subgraphs:
                namespace, event_mode, data = item
                sink.on_event(tuple(namespace), event_mode, data)
            elif isinstance(mode, str):
                sink.on_event((), mode, item)
            else:
                event_mode, data = item
                sink.on_event((), event_mode, data)
    except Exception as exc:
        message = api_error_message(exc, rate_limit_hint=rate_limit_hint)
        if message is None:
            if catch_all is None:
                raise
            message = f"{catch_all}: {type(exc).__name__}: {exc}"
        return TurnFailure(exc, message)
    return None


def format_failure(failure: TurnFailure) -> str:
    """How a REPL prints a failed turn: on its own bracketed line."""
    return f"\n[{failure.message}]\n"


class AgentTurnPrinter:
    """Renders agent stream events to `out`. Text streams inline; tool activity gets lines."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode == "updates" and isinstance(data, dict):
            for node, payload in data.items():
                for msg in (payload or {}).get("messages", []):
                    if node == "model" and isinstance(msg, AIMessage):
                        for tc in msg.tool_calls:
                            self.out(f"\n→ {tc['name']}({tc['args']})\n")
                        if not msg.tool_calls:
                            # the update carries the whole final message; prefer it to the
                            # accumulated chunks, which may include text from earlier tool turns
                            self.final_text = text_of(msg) or self.final_text
                            self.out("\n")
                    elif node == "tools" and isinstance(msg, ToolMessage):
                        self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")


class GraphTurnPrinter:
    """Renders a graph run with subgraphs. Conversational nodes stream their text from inside
    their subgraph, so their root updates (`streamed_nodes`) are skipped; other root nodes print
    their message as `[node] text`. The first interrupt's value is kept."""

    def __init__(self, out: Out, streamed_nodes: frozenset[str] = frozenset()) -> None:
        self.out = out
        self.streamed_nodes = streamed_nodes
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
        self.error: str | None = None

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
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
            if not namespace and node in self.streamed_nodes:
                continue
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls:
                        self.final_text = text_of(msg) or self.final_text
                        self.out("\n")
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")
                elif not namespace and isinstance(msg, AIMessage):
                    text = text_of(msg)
                    self.out(f"[{node}] {text}\n")
                    self.final_text = text


async def run_agent_turn(
    agent: Any,
    text: str,
    thread_id: str,
    out: Out,
    *,
    context: Any = None,
    tags: Sequence[str] | None = None,
    catch_all: str | None = None,
) -> str:
    """One chat turn: stream the agent, print as it goes, return the final text. A failure is
    printed and the thread keeps its last checkpoint."""
    printer = AgentTurnPrinter(out)
    failure = await stream_turn(
        agent,
        {"messages": [HumanMessage(text)]},
        turn_config(thread_id, tags=tags),
        printer,
        subgraphs=False,
        context=context,
        catch_all=catch_all,
    )
    if failure is not None:
        out(format_failure(failure))
    return printer.final_text


async def run_graph_turn(
    graph: Any,
    payload: dict[str, Any] | Command[Any],
    thread_id: str,
    out: Out,
    *,
    streamed_nodes: frozenset[str] = frozenset(),
) -> GraphTurnPrinter:
    """One graph turn with subgraphs. An Anthropic failure is printed and kept in
    `printer.error`; any other error propagates."""
    printer = GraphTurnPrinter(out, streamed_nodes)
    failure = await stream_turn(graph, payload, turn_config(thread_id), printer, subgraphs=True)
    if failure is not None:
        printer.error = format_failure(failure)
        out(printer.error)
    return printer
