"""Command-line entry points for the nutrition agent. chat, check-in and reset arrive later."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Endurance nutrition agent", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Endurance nutrition agent."""


if __name__ == "__main__":
    app()
