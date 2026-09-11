"""Command-line entry points for the wellness agent (ingest, report, chat, panels arrive in
later plans)."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Functional-medicine lab interpreter", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Functional-medicine lab interpreter."""


if __name__ == "__main__":
    app()
