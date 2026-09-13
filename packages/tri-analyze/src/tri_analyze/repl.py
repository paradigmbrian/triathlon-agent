"""Terminal REPL: stream a turn, show tool calls, loop.

`stream_mode=["messages", "updates"]` yields ("messages", (chunk, meta)) for token-level output
and ("updates", {node: {...}}) when a node finishes. Tool calls are visible in the model node's
update; tool results arrive as ToolMessages from the tools node.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from tri_analyze.repo import AthleteContext

Out = Callable[[str], None]
Command = Callable[[], Awaitable[str]]


def text_of(msg: BaseMessage) -> str:
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
    """Renders agent stream events to `out`. Text streams inline; tool activity gets lines."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""

    def on_event(self, mode: str, data: Any) -> None:
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
        if mode == "updates":
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


async def run_turn(
    agent: Any,
    text: str,
    thread_id: str,
    out: Out,
    *,
    context: AthleteContext,
    tags: list[str] | None = None,
) -> str:
    """One turn: stream the agent, print as it goes, return the final text. Anthropic errors and
    any other failure are printed; the loop continues and the thread keeps its last checkpoint."""
    printer = TurnPrinter(out)
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if tags:
        cfg["tags"] = list(tags)
    try:
        async for mode, data in agent.astream(
            {"messages": [HumanMessage(text)]},
            config=cfg,
            stream_mode=["messages", "updates"],
            context=context,
        ):
            printer.on_event(mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    except Exception as exc:
        out(f"\n[the turn failed: {type(exc).__name__}: {exc}]\n")
    return printer.final_text


async def chat_loop(
    agent: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    context: Callable[[], AthleteContext],
    thread_id: str = "analyze",
    commands: dict[str, Command] | None = None,
) -> None:
    """Read lines until EOF or /quit. `context()` is called before each turn, so a command that
    replaces what it returns (such as /sync) changes the next turn's prompt."""
    commands = dict(commands or {})
    out(
        "tri-analyze chat. Type a question, /quit to exit, /<command> for: "
        + ", ".join(sorted(["quit", *commands]))
        + "\n"
    )
    while True:
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
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        await run_turn(agent, line, thread_id, out, context=context(), tags=["chat"])
