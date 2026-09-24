"""Command-line entry point for tri-core: `tri sync`."""

from __future__ import annotations

import asyncio
from datetime import date

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_core.config import get_settings
from tri_core.sync.runner import run_sync

app = typer.Typer(help="Shared triathlon data tools", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Shared triathlon data tools.

    Runs before every command. .env is read here, not at import, so importing this module
    (tests do) never switches LangSmith tracing on.
    """
    load_dotenv()


@app.command()
def sync(
    since: str | None = typer.Option(None, help="Start date YYYY-MM-DD (overrides watermark)"),
    source: str = typer.Option("all", help="trainingpeaks | garmin | all"),
    full: bool = typer.Option(False, help="Ignore watermark; use each source's first-run window"),
) -> None:
    """Pull TrainingPeaks and Garmin data into Postgres."""
    sources = ("trainingpeaks", "garmin") if source == "all" else (source,)
    since_date = date.fromisoformat(since) if since else None
    report = asyncio.run(
        run_sync(
            get_settings(),
            since=since_date,
            sources=sources,
            full=full,
            log=lambda m: console.print(m, markup=False, highlight=False),
        )
    )
    for r in report.results:
        style = "green" if r.status == "ok" else "red"
        detail = f" {r.error}" if r.error else ""
        console.print(f"{r.source}: {r.status} ({r.rows} rows){detail}", style=style, markup=False)
    raise typer.Exit(code=0 if report.ok else 1)


if __name__ == "__main__":
    app()
