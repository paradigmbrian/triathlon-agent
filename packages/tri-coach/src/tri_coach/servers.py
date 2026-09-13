"""One Garmin session and one TrainingPeaks session for the whole coach process. The bound tools
go to the models that may read them; a ToolsCaller per server goes to the graph deps so the
packages' apply functions and read tools call the same sessions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from tri_coach.allowlist import GARMIN_TOOLS, TP_TOOLS
from tri_core.config import Settings
from tri_core.mcp.caller import ToolsCaller
from tri_core.mcp.live_tools import open_live_servers
from tri_core.mcp.servers import ServerSpec, garmin_spec, trainingpeaks_spec


@dataclass
class Servers:
    garmin_tools: list[BaseTool] = field(default_factory=list)
    tp_tools: list[BaseTool] = field(default_factory=list)
    garmin: ToolsCaller | None = None  # None when the server is down or --no-live
    tp: ToolsCaller | None = None


async def open_servers(
    stack: AsyncExitStack, settings: Settings, *, no_live: bool, log: Callable[[str], None]
) -> Servers:
    if no_live:
        return Servers()
    specs: dict[str, tuple[ServerSpec, Sequence[str]]] = {
        "garmin": (garmin_spec(settings, enabled_tools=GARMIN_TOOLS), GARMIN_TOOLS),
        "trainingpeaks": (trainingpeaks_spec(settings), TP_TOOLS),
    }
    bound = await stack.enter_async_context(open_live_servers(specs, log))
    garmin = bound.get("garmin")
    tp = bound.get("trainingpeaks")
    return Servers(
        garmin_tools=list(garmin or []),
        tp_tools=list(tp or []),
        garmin=ToolsCaller(garmin) if garmin is not None else None,
        tp=ToolsCaller(tp) if tp is not None else None,
    )
