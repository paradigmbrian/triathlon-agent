"""Command-line entry points for the head coach: chat, check-in, memory, reset, eval."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date
from typing import Any

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console

from tri_coach.config import CoachSettings, get_coach_settings

load_dotenv()
# The agents share one .env; give the coach its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_coach_settings().tri_coach_langsmith_project

app = typer.Typer(
    help="Head coach: one conversation over the analyst, wellness, planning and nutrition",
    no_args_is_help=True,
)
console = Console()
THREAD_ID = "coach"


@app.callback()
def main() -> None:
    """Head coach agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


def _today() -> date:
    return date.today()


def ready(settings: CoachSettings) -> str | None:
    """Why chat cannot start, or None when the key, checkpointer and store are all there."""
    from tri_coach.graph.checkpointer import SETUP_HINT, checkpointer_ready
    from tri_nutrition import store as S

    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set in .env"
    if not checkpointer_ready(settings.database_url):
        return SETUP_HINT
    if not S.store_ready(settings.database_url):
        return S.STORE_SETUP_HINT
    return None


def _ready(settings: CoachSettings) -> int | None:
    """Exit code when chat cannot start, else None."""
    problem = ready(settings)
    if problem is None:
        return None
    console.print(problem, style="red")
    return 2


@asynccontextmanager
async def _open_graph(*, no_live: bool) -> AsyncIterator[tuple[Any, Any, Any]]:
    """Yields (graph, store, servers)."""
    from tri_coach.graph.checkpointer import open_checkpointer
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.servers import open_servers
    from tri_nutrition import store as S

    settings = get_coach_settings()
    code = _ready(settings)
    if code is not None:
        raise typer.Exit(code=code)
    async with AsyncExitStack() as stack:
        servers = await open_servers(stack, settings, no_live=no_live, log=lambda m: _out(m + "\n"))
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), servers)
        yield build_graph(deps, saver, store), store, servers


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Talk to your head coach; every plan or nutrition change is approved before it is written."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from tri_coach import memory as M
    from tri_coach.context import load_context, render_context
    from tri_coach.models import Proposal
    from tri_coach.prompts.coach import render_system_prompt
    from tri_coach.repl import chat_loop, proposals_from_yaml, proposals_to_yaml
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync

    settings = get_coach_settings()
    async with _open_graph(no_live=no_live) as (graph, store, servers):
        cfg = {"configurable": {"thread_id": THREAD_ID}}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def snapshot() -> tuple[Any, Any]:
            snap = await graph.aget_state(cfg)
            with connect(settings.database_url) as conn:
                ctx = await load_context(
                    conn,
                    store,
                    _today(),
                    (snap.values or {}).get("pending"),
                    labs_enabled=settings.tri_athlete_sex is not None,
                )
            return snap, ctx

        async def cmd_status() -> str:
            snap, ctx = await snapshot()
            entries = await M.get_entries(store)
            lines = render_context(ctx).split("\n")[1:]
            live = len(M.active(entries, ctx.today))
            lines.append(f"memory entries: {live}; next node: {snap.next or '-'}")
            if (snap.values or {}).get("last_error"):
                lines.append(f"last error: {snap.values['last_error']}")
            return "\n".join(lines)

        async def cmd_memory() -> str:
            entries = await M.get_entries(store)
            if not entries:
                return "nothing remembered yet"
            return yaml.safe_dump([e.model_dump(mode="json") for e in entries], sort_keys=False)

        async def cmd_tools() -> str:
            names = [t.name for t in servers.garmin_tools + servers.tp_tools]
            return "bound live tools: " + (
                ", ".join(names) if names else "none (--no-live or servers down)"
            )

        async def cmd_prompt() -> str:
            _, ctx = await snapshot()
            return render_system_prompt(
                ctx,
                await M.get_entries(store),
                max_consults=settings.tri_coach_max_consults_per_domain,
            )

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            return "sync " + ("ok" if report.ok else "had errors")

        async def edit_in_editor(proposals: list[Proposal]) -> list[Proposal] | None:
            editor = os.environ.get("EDITOR", "vi")
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                f.write(proposals_to_yaml(proposals))
                path = f.name
            await asyncio.to_thread(subprocess.call, [editor, path])
            try:
                with open(path) as f:
                    return proposals_from_yaml(f.read(), proposals)
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
            commands={
                "status": cmd_status,
                "memory": cmd_memory,
                "tools": cmd_tools,
                "prompt": cmd_prompt,
                "sync": cmd_sync,
            },
            edit=edit_in_editor,
        )


@app.command("check-in")
def check_in(
    yes: bool = typer.Option(
        False, "--yes", help="Approve the change set and its nutrition follow-on without asking"
    ),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip `tri sync` first"),
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Sync, run the coach's weekly check-in, and pause at review (exit 3) unless --yes."""
    raise typer.Exit(code=asyncio.run(_check_in(yes=yes, no_sync=no_sync, no_live=no_live)))


async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from tri_coach.checkin import run_checkin
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
    from tri_planning import repo

    settings = get_coach_settings()
    code = _ready(settings)
    if code is not None:
        return code
    if not no_sync:
        report = await run_sync(settings, log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("check-in: sync had errors; continuing with existing data\n")
    with connect(settings.database_url) as conn:
        phase, _, _ = repo.derive_phase(conn)
    async with _open_graph(no_live=no_live) as (graph, store, _servers):
        profile = await S.get_profile(store)
        return await run_checkin(
            graph,
            has_plan=phase == "active",
            has_profile=profile is not None,
            yes=yes,
            out=_out,
            thread_id=THREAD_ID,
        )


@app.command()
def memory(
    forget: str | None = typer.Option(None, "--forget", help="Remove the entry with this id"),
) -> None:
    """Print the coach's athlete memory, or remove one entry."""
    raise typer.Exit(code=asyncio.run(_memory(forget=forget)))


async def _memory(*, forget: str | None) -> int:
    from tri_coach import memory as M
    from tri_nutrition import store as S

    settings = get_coach_settings()
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
    async with S.open_store(settings.database_url) as store:
        if forget:
            ok = await M.forget_entry(store, forget)
            _out(("forgot " if ok else "no entry ") + forget + "\n")
            return 0 if ok else 1
        entries = await M.get_entries(store)
        _out(
            yaml.safe_dump([e.model_dump(mode="json") for e in entries], sort_keys=False)
            if entries
            else "nothing remembered yet\n"
        )
        return 0


@app.command(name="eval")
def eval_cmd(
    judge: bool = typer.Option(True, "--judge/--no-judge", help="Also run the brief judge"),
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default coach-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate-dataset",
        help="Delete and re-create the LangSmith dataset from the cases in code",
    ),
) -> None:
    """Run the coach over the routing dataset in LangSmith and print the pass rate per evaluator
    (exit 1 when any evaluator is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(judge=judge, prefix=prefix, recreate=recreate)))


async def _eval(*, judge: bool, prefix: str | None, recreate: bool) -> int:
    from tri_coach.evals.run import run_eval
    from tri_coach.graph.llm import make_model

    settings = get_coach_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings,
        make_model(settings),
        judge=judge,
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
    forget_memory: bool = typer.Option(
        False, "--forget-memory", help="Also delete the coach's athlete memory"
    ),
) -> None:
    """Clear the coach conversation. Never touches Garmin, TrainingPeaks, or the other agents'
    threads, tables or Store keys."""
    what = "the coach conversation" + (" and its athlete memory" if forget_memory else "")
    if not yes and not typer.confirm(f"Forget {what}?"):
        raise typer.Exit(code=1)
    console.print(asyncio.run(reset_thread(get_coach_settings(), forget_memory=forget_memory)))


async def reset_thread(settings: CoachSettings, *, forget_memory: bool) -> str:
    from tri_coach import memory as M
    from tri_coach.graph.checkpointer import checkpointer_ready, open_checkpointer
    from tri_nutrition import store as S

    parts = []
    if checkpointer_ready(settings.database_url):
        async with open_checkpointer(settings.database_url) as saver:
            await saver.adelete_thread(THREAD_ID)
        parts.append("thread cleared")
    if forget_memory and S.store_ready(settings.database_url):
        async with S.open_store(settings.database_url) as store:
            await M.clear(store)
        parts.append("memory forgotten")
    return "reset: " + (", ".join(parts) if parts else "nothing to do")


if __name__ == "__main__":
    app()
