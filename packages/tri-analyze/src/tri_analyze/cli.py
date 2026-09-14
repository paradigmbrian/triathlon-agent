"""Command-line entry points: chat and eval."""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import TYPE_CHECKING

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_analyze.config import get_analyze_settings

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

load_dotenv()
# The agents share one .env; give the analyst its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_analyze_settings().tri_analyze_langsmith_project

app = typer.Typer(
    help="Triathlon training analysis agent (run `tri sync` to load data)", no_args_is_help=True
)
console = Console()
THREAD_ID = "analyze"


@app.callback()
def main() -> None:
    """Triathlon training analysis agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


async def _read() -> str | None:
    try:
        return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
    except EOFError:
        return None


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Bind only the database tool"),
) -> None:
    """Chat with the training analyst agent."""
    raise typer.Exit(code=asyncio.run(_chat(no_live=no_live)))


async def _chat(*, no_live: bool) -> int:
    from contextlib import AsyncExitStack

    import psycopg

    from tri_analyze.agent import build_agent
    from tri_analyze.llm import make_model
    from tri_analyze.prompts.analyst import render_system_prompt
    from tri_analyze.repl import chat_loop
    from tri_analyze.repo import AthleteContext, load_athlete_context
    from tri_analyze.tools.live import open_live_tools
    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_core.sync.runner import run_sync

    settings = get_analyze_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2

    def load_context() -> AthleteContext:
        with connect(settings.database_url) as conn:
            return load_athlete_context(conn, date.today())

    # Load the context before the MCP servers start, so a down database fails in well under
    # a second instead of after a 10 to 20 s server launch.
    try:
        current: list[AthleteContext] = [load_context()]
    except psycopg.OperationalError as exc:
        console.print(f"database unreachable: {exc}", style="red")
        return 2

    async with AsyncExitStack() as stack:
        live_tools: list[BaseTool] = []
        if not no_live:
            live_tools = await stack.enter_async_context(
                open_live_tools(settings, lambda m: _out(m + "\n"))
            )
        tools: list[BaseTool] = [make_query_tool(settings.database_url), *live_tools]
        agent = build_agent(make_model(settings), tools)

        async def cmd_tools() -> str:
            return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)

        async def cmd_prompt() -> str:
            return render_system_prompt(current[0], [t.name for t in tools])

        async def cmd_sync() -> str:
            report = None
            try:
                report = await run_sync(settings, log=lambda m: _out(m + "\n"))
                current[0] = load_context()
            except psycopg.OperationalError as exc:
                if report is None:
                    return f"sync failed: database unreachable: {exc}"
                status = "sync " + ("ok" if report.ok else "had errors")
                return f"{status}; athlete context not refreshed: database unreachable: {exc}"
            status = "sync " + ("ok" if report.ok else "had errors")
            return f"{status}; athlete context refreshed"

        await chat_loop(
            agent,
            read=_read,
            out=_out,
            context=lambda: current[0],
            thread_id=THREAD_ID,
            commands={"tools": cmd_tools, "prompt": cmd_prompt, "sync": cmd_sync},
        )
    return 0


@app.command(name="eval")
def eval_cmd(
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default analyst-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate-dataset",
        help="Delete and re-create the LangSmith dataset from the cases in code",
    ),
) -> None:
    """Run the analyst over the feedback dataset in LangSmith and print the pass rate per
    evaluator (exit 1 when any evaluator is below 100% or any example errored)."""
    raise typer.Exit(code=asyncio.run(_eval(prefix=prefix, recreate=recreate)))


async def _eval(*, prefix: str | None, recreate: bool) -> int:
    from tri_analyze.evals.run import run_eval
    from tri_analyze.llm import make_model

    settings = get_analyze_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates, errors = await run_eval(
        settings,
        make_model(settings),
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and errors == 0 and all(r == 1.0 for r in rates.values()) else 1


if __name__ == "__main__":
    app()
