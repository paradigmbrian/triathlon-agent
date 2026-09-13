"""Command-line entry points."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_core.config import get_settings
from tri_core.sync.runner import run_sync

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

load_dotenv()  # LangSmith reads LANGSMITH_* from the process environment

app = typer.Typer(
    help="Triathlon training analysis agent (run `tri sync` to load data)", no_args_is_help=True
)
console = Console()


@app.callback()
def main() -> None:
    """Triathlon training analysis agent."""


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Bind only the database tool"),
) -> None:
    """Chat with the training analyst agent."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from contextlib import AsyncExitStack

    from langgraph.checkpoint.memory import InMemorySaver

    from tri_analyze._old_agent.agent import build_agent, make_model
    from tri_analyze._old_agent.live_tools import open_live_tools
    from tri_analyze._old_agent.prompt import load_athlete_context, render_system_prompt
    from tri_analyze._old_agent.repl import chat_loop
    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool

    settings = get_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)

    def out(s: str) -> None:
        console.print(s, end="", markup=False, highlight=False, soft_wrap=True)

    async with AsyncExitStack() as stack:
        live_tools: list[BaseTool] = []
        if not no_live:
            live_tools = await stack.enter_async_context(
                open_live_tools(settings, lambda m: out(m + "\n"))
            )
        tools: list[BaseTool] = [make_query_tool(settings.database_url), *live_tools]
        saver = InMemorySaver()

        def make() -> tuple[Any, str]:
            with connect(settings.database_url) as conn:
                ctx = load_athlete_context(conn, date.today())
            prompt = render_system_prompt(ctx, [t.name for t in live_tools])
            return build_agent(make_model(settings), tools, prompt, checkpointer=saver), prompt

        agent, prompt = make()
        state: dict[str, Any] = {"agent": agent, "prompt": prompt}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def cmd_tools() -> str:
            return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)

        async def cmd_prompt() -> str:
            return str(state["prompt"])

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: out(m + "\n"))
            state["agent"], state["prompt"] = make()  # re-render context; memory survives via saver
            return "sync " + ("ok" if report.ok else "had errors") + "; athlete context refreshed"

        class _Proxy:
            """Lets /sync swap the agent while chat_loop keeps one reference."""

            def astream(self, *a: object, **k: object) -> object:
                return state["agent"].astream(*a, **k)

        await chat_loop(
            _Proxy(),
            read=read,
            out=out,
            commands={"tools": cmd_tools, "prompt": cmd_prompt, "sync": cmd_sync},
        )


if __name__ == "__main__":
    app()
