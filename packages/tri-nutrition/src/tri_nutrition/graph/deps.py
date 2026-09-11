"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

from langchain_core.language_models import BaseChatModel

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_core.sync import ToolCaller
from tri_nutrition.config import NutritionSettings

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    db_url: str  # for the read-only SQL tool, which opens its own connections
    garmin: ToolCaller | None = None  # live Garmin session; None when the server is down
    tp: ToolCaller | None = None  # live TrainingPeaks session; None when down
    horizon_days: int = 14
    today: Callable[[], date] = date.today


def make_deps(
    settings: NutritionSettings,
    model: BaseChatModel,
    garmin: ToolCaller | None,
    tp: ToolCaller | None = None,
) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        garmin=garmin,
        tp=tp,
        horizon_days=settings.tri_nutrition_horizon_days,
    )
