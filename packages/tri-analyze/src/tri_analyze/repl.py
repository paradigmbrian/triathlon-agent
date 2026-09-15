"""Terminal REPL: stream a turn, show tool calls, loop.

`stream_mode=["messages", "updates"]` yields ("messages", (chunk, meta)) for token-level output
and ("updates", {node: {...}}) when a node finishes. Tool calls are visible in the model node's
update; tool results arrive as ToolMessages from the tools node. The stream loop and the printer
are tri_core.harness.turns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from tri_analyze.repo import AthleteContext
from tri_core.harness.turns import Out, run_agent_turn

Command = Callable[[], Awaitable[str]]


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
    return await run_agent_turn(
        agent, text, thread_id, out, context=context, tags=tags, catch_all="the turn failed"
    )


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
