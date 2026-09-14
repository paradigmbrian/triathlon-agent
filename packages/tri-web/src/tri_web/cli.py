"""`tri-web serve`: open the coach runtime, serve the API (and web/dist when built) on localhost.
`tri-web openapi`: print the OpenAPI document the frontend's types are generated from."""

from __future__ import annotations

import asyncio
import json

import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console

from tri_web.config import WebSettings, get_web_settings

load_dotenv()

app = typer.Typer(help="Local web UI over the head coach", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """tri-web server."""


def _log(m: str) -> None:
    console.print(m, markup=False, highlight=False, soft_wrap=True)


@app.command()
def serve(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
    host: str | None = typer.Option(None, "--host", help="Bind address (default TRI_WEB_HOST)"),
    port: int | None = typer.Option(None, "--port", help="Port (default TRI_WEB_PORT, 8321)"),
) -> None:
    """Serve the coach API on localhost; the built frontend too when web/dist exists."""
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


async def _serve(settings: WebSettings, *, no_live: bool, host: str, port: int) -> int:
    from tri_web.app import create_app
    from tri_web.runtime import open_runtime

    try:
        async with open_runtime(settings, no_live=no_live, log=_log) as rt:
            server = uvicorn.Server(
                uvicorn.Config(create_app(rt), host=host, port=port, log_level="info")
            )
            _log(
                f"tri-web: http://{host}:{port}  (thread coach, live={'no' if no_live else 'yes'})"
            )
            await server.serve()
    except RuntimeError as exc:
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
