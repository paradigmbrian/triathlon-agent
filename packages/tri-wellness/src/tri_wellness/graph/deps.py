"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_wellness.config import WellnessSettings
from tri_wellness.ranges.registry import MarkerRegistry, load_registry

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    registry: MarkerRegistry


def make_deps(settings: WellnessSettings, model: BaseChatModel) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        registry=load_registry(settings.tri_athlete_sex),
    )
