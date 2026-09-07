"""Command-line entry points for the planning agent."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Triathlon training planning agent", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Triathlon training planning agent."""


if __name__ == "__main__":
    app()
