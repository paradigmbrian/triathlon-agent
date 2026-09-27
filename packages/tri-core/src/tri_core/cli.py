"""Command-line entry point for tri-core: `tri sync` and `tri migrate`."""

from __future__ import annotations

import asyncio
from datetime import date

import psycopg
import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_core.config import get_settings
from tri_core.db.migrate import (
    MigrationError,
    apply_migrations,
    discover,
    ensure_langgraph_tables,
)
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


@app.command()
def migrate(
    test: bool = typer.Option(False, help="Migrate TEST_DATABASE_URL instead of DATABASE_URL"),
    dry_run: bool = typer.Option(False, help="Print what would run; change nothing"),
) -> None:
    """Apply migrations/*.sql in order, record each in schema_migrations, then create LangGraph's
    checkpoint and store tables. Running it twice is a no-op."""
    settings = get_settings()
    url = settings.test_database_url if test else settings.database_url

    def out(m: str) -> None:
        console.print(m, markup=False, highlight=False)

    try:
        migrations = discover()
        with psycopg.connect(url, autocommit=True) as conn:
            apply_migrations(conn, migrations, dry_run=dry_run, log=out)
        if not dry_run:
            ensure_langgraph_tables(url)
            out("checkpoint and store tables ready")
    except (MigrationError, psycopg.Error) as exc:
        console.print(str(exc), style="red", markup=False, highlight=False)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
