"""`tri-web serve`: open the coach runtime and serve the API on localhost, plus web/dist when built.
`tri-web openapi`: print the OpenAPI document the frontend's types are generated from."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console

from tri_web.config import WebSettings, get_web_settings

if TYPE_CHECKING:
    from collections.abc import Generator

    from tri_web.runtime import Log, Runtime

app = typer.Typer(help="Local web UI over the head coach", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """tri-web server.

    Runs before every command. .env is read here, not at import, so importing this module
    (tests do) never switches LangSmith tracing on.
    """
    load_dotenv()


def _log(m: str) -> None:
    console.print(m, markup=False, highlight=False, soft_wrap=True)


@app.command()
def serve(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
    host: str | None = typer.Option(None, "--host", help="Bind address (default TRI_WEB_HOST)"),
    port: int | None = typer.Option(None, "--port", help="Port (default TRI_WEB_PORT, 8321)"),
) -> None:
    """Serve the coach API on localhost, plus web/dist when built."""
    settings = get_web_settings()
    raise typer.Exit(
        code=asyncio.run(
            _serve(
                settings,
                no_live=no_live,
                host=host or settings.tri_web_host,
                port=port or settings.tri_web_port,
            )
        )
    )


class _Server(uvicorn.Server):
    """uvicorn re-raises the captured signal when serve() returns; clearing it lets _serve finish
    the running turn and close the runtime before the process exits. A second Ctrl-C still
    interrupts."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        with super().capture_signals():
            yield
            self._captured_signals.clear()


def _allowed_hosts(host: str) -> list[str]:
    """Host header values the app accepts: loopback names plus the bind address when it is one."""
    hosts = ["127.0.0.1", "localhost"]
    if host not in ("0.0.0.0", "::") and host not in hosts:
        hosts.append(host)
    return hosts


async def _finish_running_turn(rt: Runtime, log: Log) -> None:
    """Wait out a turn still running when `serve()` returns, so the exit stack never closes the
    checkpointer, store or MCP sessions mid-write. No cancellation, no timeout."""
    task = rt.turn_task
    if task is not None and not task.done():
        log("tri-web: waiting for the running turn to finish")
        await task


async def _serve(settings: WebSettings, *, no_live: bool, host: str, port: int) -> int:
    from tri_web.app import create_app
    from tri_web.runtime import NotReady, open_runtime

    try:
        async with open_runtime(settings, no_live=no_live, log=_log) as rt:
            server = _Server(
                uvicorn.Config(
                    create_app(rt, allowed_hosts=_allowed_hosts(host), log=_log),
                    host=host,
                    port=port,
                    log_level="info",
                )
            )
            _log(
                f"tri-web: http://{host}:{port}  (thread coach, live={'no' if no_live else 'yes'})"
            )
            await server.serve()
            await _finish_running_turn(rt, _log)
    except NotReady as exc:
        console.print(str(exc), style="red")
        return 2
    return 0


@app.command()
def openapi() -> None:
    """Print the OpenAPI document (web/src/api/types.ts is generated from it)."""
    from tri_web.app import create_app

    typer.echo(json.dumps(create_app(None).openapi(), indent=2))


if __name__ == "__main__":
    app()
