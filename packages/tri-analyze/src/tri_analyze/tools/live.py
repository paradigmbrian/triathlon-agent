"""The analyst's live tools: the shared MCP opener with this agent's allow-lists."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_core.config import Settings
from tri_core.mcp.live_tools import open_live_tools as _open
from tri_core.mcp.servers import ServerSpec, garmin_spec, trainingpeaks_spec


@asynccontextmanager
async def open_live_tools(
    settings: Settings, log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    specs: dict[str, tuple[ServerSpec, Sequence[str]]] = {
        "garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS),
        "trainingpeaks": (trainingpeaks_spec(settings), TP_LIVE_TOOLS),
    }
    async with _open(specs, log) as tools:
        yield tools
