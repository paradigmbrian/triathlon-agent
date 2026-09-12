"""Command-line entry points for the head coach: chat, memory, reset."""

from __future__ import annotations

import os

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_coach.config import get_coach_settings

load_dotenv()
# The agents share one .env; give the coach its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_coach_settings().tri_coach_langsmith_project

app = typer.Typer(
    help="Head coach: one conversation over the analyst, planning and nutrition",
    no_args_is_help=True,
)
console = Console()
THREAD_ID = "coach"


@app.callback()
def main() -> None:
    """Head coach agent."""


if __name__ == "__main__":
    app()
