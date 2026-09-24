"""Command-line entry points for the wellness agent: ingest, panels, report, chat, eval."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from pydantic import ValidationError
from rich.console import Console

from tri_wellness.config import get_wellness_settings

app = typer.Typer(help="Functional-medicine lab interpreter", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Functional-medicine lab interpreter.

    Runs before every command. .env is read here, not at import, so importing this module
    (tests do) never switches LangSmith tracing on.
    """
    load_dotenv()
    os.environ["LANGSMITH_PROJECT"] = os.environ.get(
        "TRI_WELLNESS_LANGSMITH_PROJECT", "tri_wellness"
    )


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


async def _read() -> str | None:
    try:
        return await asyncio.to_thread(console.input, "[bold cyan]review>[/] ")
    except EOFError:
        return None


def make_editor(registry: Any) -> Any:
    """`$EDITOR` over the review document. Returns the parsed fields, or None (with the errors
    printed) so the dialogue re-prompts."""
    from tri_wellness.repl import review_from_yaml, review_to_yaml

    async def edit_in_editor(payload: dict[str, Any]) -> dict[str, Any] | None:
        editor = os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(review_to_yaml(payload))
            path = f.name
        try:
            try:
                await asyncio.to_thread(subprocess.call, [editor, path])
            except OSError as exc:
                _out(f"could not run editor '{editor}': {exc}\n")
                return None
            with open(path, encoding="utf-8") as fh:
                return review_from_yaml(fh.read(), registry)
        except ValueError as exc:
            _out(f"edited YAML is not valid:\n{exc}\n")
            return None
        finally:
            os.unlink(path)

    return edit_in_editor


@app.command()
def ingest(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    kind: str | None = typer.Option(
        None, "--kind", help="pdf or export; sniffed from the extension"
    ),
    drawn_on: str | None = typer.Option(
        None, "--drawn-on", help="Draw date YYYY-MM-DD when the file does not print one"
    ),
) -> None:
    """Extract a lab panel, review it, store it. Rerunning the same file resumes at review."""
    raise typer.Exit(code=asyncio.run(_ingest(file, kind, drawn_on)))


def _settings_or_exit() -> Any:
    try:
        return get_wellness_settings()
    except ValidationError:
        console.print("TRI_ATHLETE_SEX must be set to male or female in .env", style="red")
        raise typer.Exit(code=2) from None


async def _ingest(file: Path, kind: str | None, drawn_on: str | None) -> int:
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_core.llm import Role, make_model
    from tri_wellness.graph.deps import make_deps
    from tri_wellness.graph.graph import build_ingest_graph
    from tri_wellness.graph.state import STATE_TYPES
    from tri_wellness.labs.extract import file_sha256, sniff
    from tri_wellness.repl import run_ingest

    if kind not in (None, "pdf", "export"):
        console.print("--kind must be pdf or export", style="red")
        return 2
    try:
        source_kind = sniff(file, kind)  # type: ignore[arg-type]
    except ValueError as exc:
        console.print(str(exc), style="red")
        return 2
    hint: date | None = None
    if drawn_on is not None:
        try:
            hint = date.fromisoformat(drawn_on)
        except ValueError:
            console.print("--drawn-on must be YYYY-MM-DD", style="red")
            return 2
    settings = _settings_or_exit()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        return 2
    thread_id = f"ingest:{file_sha256(file)}"
    async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
        deps = make_deps(settings, make_model(settings, Role.LAB_EXTRACT))
        graph = build_ingest_graph(deps, saver)
        return await run_ingest(
            graph,
            source_path=str(file.resolve()),
            source_kind=source_kind,
            drawn_on_hint=hint,
            thread_id=thread_id,
            read=_read,
            out=_out,
            edit=make_editor(deps.registry),
        )


@app.command()
def panels() -> None:
    """List stored panels: date, lab, result count, unmapped count, whether a report exists."""
    from tri_core.db.connection import connect
    from tri_wellness import repo
    from tri_wellness.repl import render_panels

    settings = _settings_or_exit()
    with connect(settings.database_url) as conn:
        console.print(render_panels(repo.list_panels(conn)), markup=False, highlight=False)


@app.command()
def report(
    panel: int | None = typer.Option(None, "--panel", help="Panel id (default: latest)"),
    out: Path | None = typer.Option(None, "--out", help="Also write the markdown here"),
) -> None:
    """Evaluate a stored panel and write the interpretation (saved to lab_reports)."""
    raise typer.Exit(code=asyncio.run(_report(panel, out)))


async def _report(panel: int | None, out_path: Path | None) -> int:
    from tri_core.db.connection import connect
    from tri_core.llm import Role, make_model
    from tri_wellness.ranges.registry import load_registry
    from tri_wellness.report import run_report

    settings = _settings_or_exit()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    url = settings.database_url
    return await run_report(
        make_model(settings, Role.LAB_REPORT),
        lambda: connect(url),
        load_registry(settings.tri_athlete_sex),
        panel,
        _out,
        out_path,
    )


@app.command()
def chat() -> None:
    """Ask questions about stored panels and reports."""
    asyncio.run(_chat())


async def _chat() -> None:
    from langchain_core.tools import BaseTool

    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_core.harness.agents import build_chat_agent
    from tri_core.llm import Role, make_model
    from tri_wellness import repo
    from tri_wellness.prompts.chat import render_chat_prompt
    from tri_wellness.ranges.registry import load_registry
    from tri_wellness.repl import chat_loop, render_panels
    from tri_wellness.report import athlete_profile
    from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

    settings = _settings_or_exit()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    url = settings.database_url
    registry = load_registry(settings.tri_athlete_sex)
    tools: list[BaseTool] = [
        make_query_tool(url, WELLNESS_SCHEMA_DOC),
        *make_findings_tools(lambda: connect(url), registry),
    ]
    with connect(url) as conn:
        profile = athlete_profile(conn)
        panels = repo.list_panels(conn)
        latest = repo.latest_panel_id(conn)
        latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
    prompt = render_chat_prompt(
        profile, registry.sex, panels, latest_report, date.today(), [t.name for t in tools]
    )
    agent = build_chat_agent(make_model(settings, Role.WELLNESS_CHAT), tools, system_prompt=prompt)

    async def read() -> str | None:
        try:
            return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
        except EOFError:
            return None

    async def cmd_panels(_: str) -> str:
        with connect(url) as conn:
            return render_panels(repo.list_panels(conn))

    async def cmd_report(arg: str) -> str:
        with connect(url) as conn:
            if arg:
                try:
                    pid: int | None = int(arg)
                except ValueError:
                    return "usage: /report [panel id]"
            else:
                pid = repo.latest_panel_id(conn)
            if pid is None:
                return "no panels stored"
            saved = repo.latest_report_for_panel(conn, pid)
        if saved is None:
            return f"no report for panel {pid}; run `tri-wellness report --panel {pid}`"
        return (
            f"report {saved.id} for panel {pid} ({saved.created_at.date()}):\n\n{saved.report_md}"
        )

    async def cmd_prompt(_: str) -> str:
        return prompt

    async def cmd_tools(_: str) -> str:
        return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)

    await chat_loop(
        agent,
        read=read,
        out=_out,
        commands={
            "panels": cmd_panels,
            "report": cmd_report,
            "prompt": cmd_prompt,
            "tools": cmd_tools,
        },
    )


@app.command("eval")
def eval_cmd(
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default report-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False, "--recreate-dataset", help="Delete and re-create the LangSmith dataset"
    ),
) -> None:
    """Run the report prompt over the LangSmith dataset and print the pass rate per evaluator
    (exit 1 when any evaluator is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(prefix=prefix, recreate=recreate)))


async def _eval(*, prefix: str | None, recreate: bool) -> int:
    from tri_core.llm import make_model
    from tri_wellness.evals.run import run_eval

    settings = _settings_or_exit()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings,
        lambda role: make_model(settings, role),
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1


if __name__ == "__main__":
    app()
