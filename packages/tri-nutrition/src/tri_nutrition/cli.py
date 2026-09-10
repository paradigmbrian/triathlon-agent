"""Command-line entry points for the nutrition agent: chat, today, reset (check-in arrives in
Plan 4)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from datetime import date, timedelta
from typing import Any

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console

from tri_nutrition.config import get_nutrition_settings

load_dotenv()
# The agents share one .env; give this agent its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_nutrition_settings().tri_nutrition_langsmith_project

app = typer.Typer(help="Endurance nutrition agent", no_args_is_help=True)
console = Console()
THREAD_ID = "nutrition"
GARMIN_START_TIMEOUT_S = 120


@app.callback()
def main() -> None:
    """Endurance nutrition agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the Garmin server"),
) -> None:
    """Set up the nutrition profile and daily targets in conversation; every Garmin write is
    approved first."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from contextlib import AsyncExitStack

    from tri_core.db.connection import connect
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec
    from tri_core.sync.runner import run_sync
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS
    from tri_nutrition.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.nutrition.models import NutritionChange
    from tri_nutrition.repl import changes_from_yaml, changes_to_yaml, chat_loop

    settings = get_nutrition_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        raise typer.Exit(code=2)
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        raise typer.Exit(code=2)

    async with AsyncExitStack() as stack:
        garmin = None
        if not no_live:
            try:
                garmin = await asyncio.wait_for(
                    stack.enter_async_context(
                        McpToolClient(garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS))
                    ),
                    timeout=GARMIN_START_TIMEOUT_S,
                )
                _out("garmin: connected (writes happen only after you approve)\n")
            except Exception as exc:  # the chat still works; apply holds changes pending
                _out(
                    f"warning: garmin MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "intake will ask for weight and age, and apply will hold Garmin writes\n"
                )
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin), saver, store)
        cfg = {"configurable": {"thread_id": THREAD_ID}}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def cmd_status() -> str:
            snap = await graph.aget_state(cfg)
            values: dict[str, Any] = snap.values or {}
            profile = await S.get_profile(store)
            if profile is None:
                return "no nutrition profile yet; say hello to start intake"
            today = date.today()
            with connect(settings.database_url) as conn:
                stored = repo.list_targets(conn, today, today + timedelta(days=365))
                last = repo.last_change_at(conn)
            written = [s for s in stored if s.written_to_garmin]
            body_fat = profile.body_fat_pct if profile.body_fat_pct is not None else "-"
            lines = [
                f"goal: {profile.goal}; weight {profile.weight_kg:g} kg; body fat {body_fat} %",
                f"targets from today: {len(stored)} days ({len(written)} written to Garmin)",
                f"last write: {last.isoformat(timespec='minutes') if last else 'never'}",
                f"next node: {snap.next or '-'}",
            ]
            if values.get("last_error"):
                lines.append(f"last error: {values['last_error']}")
            return "\n".join(lines)

        async def cmd_profile() -> str:
            profile = await S.get_profile(store)
            if profile is None:
                return "no nutrition profile yet"
            return yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False)

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            return "sync " + ("ok" if report.ok else "had errors")

        async def edit_in_editor(changes: list[NutritionChange]) -> list[NutritionChange] | None:
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
            commands={"status": cmd_status, "profile": cmd_profile, "sync": cmd_sync},
            edit=edit_in_editor,
        )


@app.command()
def today(
    yes: bool = typer.Option(False, "--yes", help="Write without asking"),
    no_live: bool = typer.Option(False, "--no-live", help="Regenerate only; do not start Garmin"),
) -> None:
    """Regenerate the horizon and write today's target to Garmin (the daily write; Garmin holds
    only the current day's goal)."""
    raise typer.Exit(code=asyncio.run(_today(yes=yes, no_live=no_live)))


async def _today(*, yes: bool, no_live: bool) -> int:
    from contextlib import AsyncExitStack

    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec
    from tri_nutrition import store as S
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS
    from tri_nutrition.daily import describe_change, propose_today, write_today
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.llm import make_model

    settings = get_nutrition_settings()
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
    async with AsyncExitStack() as stack:
        garmin = None
        if not no_live:
            try:
                garmin = await asyncio.wait_for(
                    stack.enter_async_context(
                        McpToolClient(garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS))
                    ),
                    timeout=GARMIN_START_TIMEOUT_S,
                )
            except Exception as exc:
                _out(f"garmin MCP server unavailable ({type(exc).__name__}: {exc})\n")
                return 1
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), garmin)
        h = await propose_today(deps, store)
        _out(h.summary() + "\n")
        if h.error or h.violations:
            return 1
        if not h.changes:
            return 0
        if garmin is None:
            _out("(--no-live: horizon stored, nothing written)\n")
            return 0
        if not yes and not typer.confirm(f"Write {describe_change(h)} to Garmin?"):
            return 1
        _out(await write_today(deps, h) + "\n")
    return 0


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
    forget_profile: bool = typer.Option(
        False, "--forget-profile", help="Also delete the profile, fuel log and product library"
    ),
) -> None:
    """Clear the conversation and unwritten targets. Never touches Garmin or TrainingPeaks."""
    what = "the conversation, unwritten targets" + (
        " and the saved profile" if forget_profile else ""
    )
    if not yes and not typer.confirm(f"Forget {what}?"):
        raise typer.Exit(code=1)
    asyncio.run(_reset(forget_profile))


async def _reset(forget_profile: bool) -> None:
    from tri_core.db.connection import connect
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import checkpointer_ready, open_checkpointer

    settings = get_nutrition_settings()
    with connect(settings.database_url) as conn:
        targets = repo.delete_unwritten_targets(conn)
        plans = repo.delete_unwritten_fuel_plans(conn)
        conn.commit()
    if checkpointer_ready(settings.database_url):
        async with open_checkpointer(settings.database_url) as saver:
            await saver.adelete_thread(THREAD_ID)
    forgotten = 0
    if forget_profile and S.store_ready(settings.database_url):
        async with S.open_store(settings.database_url) as store:
            forgotten = await S.forget_all(store)
    console.print(
        f"reset: {targets} unwritten target(s) and {plans} fuel plan(s) deleted, thread cleared"
        + (f", {forgotten} store key(s) forgotten" if forget_profile else "")
    )


if __name__ == "__main__":
    app()
