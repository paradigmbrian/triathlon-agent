"""Command-line entry points for the wellness agent: ingest (report, chat, panels arrive in
Plan 3)."""

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

load_dotenv()
# The agents share one .env; give this one its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = os.environ.get("TRI_WELLNESS_LANGSMITH_PROJECT", "tri_wellness")

app = typer.Typer(help="Functional-medicine lab interpreter", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Functional-medicine lab interpreter."""


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
            await asyncio.to_thread(subprocess.call, [editor, path])
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


async def _ingest(file: Path, kind: str | None, drawn_on: str | None) -> int:
    from tri_wellness.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_wellness.graph.deps import make_deps
    from tri_wellness.graph.graph import build_ingest_graph
    from tri_wellness.graph.llm import make_model
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
    try:
        settings = get_wellness_settings()
    except ValidationError:
        console.print("TRI_ATHLETE_SEX must be set to male or female in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        return 2
    thread_id = f"ingest:{file_sha256(file)}"
    async with open_checkpointer(settings.database_url) as saver:
        deps = make_deps(settings, make_model(settings))
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


if __name__ == "__main__":
    app()
