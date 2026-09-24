"""Command-line entry points for the planning agent: chat, check-in, reset."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date, timedelta
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_planning.config import get_planning_settings

load_dotenv()
# Both agents share one .env; give this agent its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_planning_settings().tri_planning_langsmith_project

app = typer.Typer(help="Triathlon training planning agent", no_args_is_help=True)
console = Console()
THREAD_ID = "planning"
TP_START_TIMEOUT_S = 120


@app.callback()
def main() -> None:
    """Triathlon training planning agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


@asynccontextmanager
async def _open_graph(*, no_live: bool) -> AsyncIterator[Any]:
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_core.llm import Role, make_model
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.live_tools import open_live_tools
    from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec
    from tri_planning.allowlist import GARMIN_LIVE_TOOLS
    from tri_planning.graph.deps import make_deps
    from tri_planning.graph.graph import build_graph
    from tri_planning.graph.state import STATE_TYPES

    settings = get_planning_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        raise typer.Exit(code=2)
    async with AsyncExitStack() as stack:
        tp = None
        garmin_tools: list[Any] = []
        if not no_live:
            try:
                tp = await asyncio.wait_for(
                    stack.enter_async_context(McpToolClient(trainingpeaks_spec(settings))),
                    timeout=TP_START_TIMEOUT_S,
                )
                _out("trainingpeaks: connected (writes happen only after you approve)\n")
            except Exception as exc:  # the chat still works; apply refuses until the server is back
                _out(
                    f"warning: trainingpeaks MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "apply will refuse to write\n"
                )
            garmin_tools = await stack.enter_async_context(
                open_live_tools(
                    {"garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS)}, lambda m: _out(m + "\n")
                )
            )
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
        deps = make_deps(
            settings,
            make_model(settings, Role.PLANNING_AGENT),
            tp,
            design_model=make_model(settings, Role.PLANNING_DESIGN),
        )
        deps.garmin_tools = garmin_tools
        yield build_graph(deps, saver)


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Plan and adjust training in conversation; every calendar write is approved first."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_planning import repo
    from tri_planning.planning.models import CalendarChange
    from tri_planning.planning.targets import week_monday
    from tri_planning.repl import changes_from_yaml, changes_to_yaml, chat_loop

    settings = get_planning_settings()

    async with _open_graph(no_live=no_live) as graph:
        cfg = {"configurable": {"thread_id": THREAD_ID}}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def cmd_status() -> str:
            snap = await graph.aget_state(cfg)
            values: dict[str, Any] = snap.values or {}
            with connect(settings.database_url) as conn:
                phase, _, _ = repo.derive_phase(conn)
                goal = repo.get_active_goal(conn)
                if goal is None:
                    return f"no active goal; phase {phase}"
                plan = repo.get_active_plan(conn, goal.id)
                monday = week_monday(date.today())
                actual = conn.execute(
                    "select coalesce(sum(tss_day), 0) as t from daily_metrics "
                    "where metric_date between %s and %s",
                    (monday, monday + timedelta(days=6)),
                ).fetchone()
                g = goal.goal
                lines = [
                    f"goal: {g.goal_type} {g.event_name or ''} {g.event_date or ''}".rstrip(),
                    f"phase: {phase}; next node: {snap.next or '-'}",
                ]
                if plan is not None:
                    weeks = repo.list_weeks(conn, plan.id)
                    this = next((w for w in weeks if w.week_start == monday), None)
                    if this is not None:
                        target = f"{this.target_tss:.0f}" if this.target_tss is not None else "-"
                        so_far = float(actual["t"]) if actual else 0.0
                        lines.append(
                            f"this week ({this.phase}): target {target} TSS, "
                            f"actual so far {so_far:.0f}"
                        )
                    on_calendar = sum(
                        1 for w in weeks if w.written_to_tp and w.week_start >= monday
                    )
                    lines.append(
                        f"weeks on the calendar from this week: {on_calendar} of {len(weeks)}"
                    )
                if values.get("last_error"):
                    lines.append(f"last error: {values['last_error']}")
                return "\n".join(lines)

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            return "sync " + ("ok" if report.ok else "had errors")

        async def edit_in_editor(changes: list[CalendarChange]) -> list[CalendarChange] | None:
            editor = os.environ.get("EDITOR", "vi")
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                f.write(changes_to_yaml(changes))
                path = f.name
            await asyncio.to_thread(subprocess.call, [editor, path])
            try:
                with open(path) as f:
                    return changes_from_yaml(f.read())
            except Exception as exc:
                _out(f"could not parse edited YAML: {exc}\n")
                return None
            finally:
                os.unlink(path)

        await chat_loop(
            graph,
            read=read,
            out=_out,
            thread_id=THREAD_ID,
            commands={"status": cmd_status, "sync": cmd_sync},
            edit=edit_in_editor,
        )


@app.command("check-in")
def check_in(
    yes: bool = typer.Option(False, "--yes", help="Approve the proposed changes without asking"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip `tri sync` first"),
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Sync, review the last week against plan, propose changes; pause at review unless --yes."""
    raise typer.Exit(code=asyncio.run(_check_in(yes=yes, no_sync=no_sync, no_live=no_live)))


async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_planning import repo
    from tri_planning.checkin import run_checkin

    settings = get_planning_settings()
    if not no_sync:
        report = await run_sync(settings, log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("check-in: sync had errors; continuing with existing data\n")
    with connect(settings.database_url) as conn:
        phase, _, _ = repo.derive_phase(conn)
    async with _open_graph(no_live=no_live) as graph:
        return await run_checkin(graph, phase=phase, yes=yes, out=_out, thread_id=THREAD_ID)


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation")) -> None:
    """Abandon the active goal and plan and clear the conversation. Never touches TrainingPeaks."""
    if not yes and not typer.confirm(
        "Abandon the active goal and plan and forget the conversation?"
    ):
        raise typer.Exit(code=1)
    asyncio.run(_reset())


async def _reset() -> None:
    from tri_core.db.connection import connect
    from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
    from tri_planning import repo
    from tri_planning.graph.state import STATE_TYPES

    settings = get_planning_settings()
    with connect(settings.database_url) as conn:
        goals, plans = repo.abandon_active(conn)
        conn.commit()
    if checkpointer_ready(settings.database_url):
        async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
            await saver.adelete_thread(THREAD_ID)
    console.print(f"reset: {goals} goal(s) abandoned, {plans} plan(s) superseded, thread cleared")


if __name__ == "__main__":
    app()
