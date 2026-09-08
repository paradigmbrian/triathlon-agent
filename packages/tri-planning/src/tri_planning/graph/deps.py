"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_core.sync import ToolCaller
from tri_planning.config import PlanningSettings

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    db_url: str  # for the read-only SQL tool, which opens its own connections
    tp: ToolCaller | None = None  # live TrainingPeaks session; None when the server is down
    garmin_tools: list[BaseTool] = field(default_factory=list)  # Plan 4
    horizon_weeks: int = 3
    today: Callable[[], date] = date.today


def make_deps(settings: PlanningSettings, model: BaseChatModel, tp: ToolCaller | None) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        tp=tp,
        horizon_weeks=settings.tri_planning_horizon_weeks,
    )
