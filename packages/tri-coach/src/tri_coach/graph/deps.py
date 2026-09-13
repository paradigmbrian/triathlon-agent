"""What the coach's nodes and tools need, injected once at build time. The sub-agents' deps are
built here from the coach's own sessions, so one process holds one session per server."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tri_coach.allowlist import ANALYST_GARMIN_TOOLS, ANALYST_TP_TOOLS
from tri_coach.config import CoachSettings
from tri_coach.servers import Servers
from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_core.db.sql_tool import make_query_tool
from tri_core.mcp.live_tools import filter_tools
from tri_nutrition.config import get_nutrition_settings
from tri_nutrition.graph.deps import GraphDeps as NutritionDeps
from tri_nutrition.graph.deps import make_deps as make_nutrition_deps
from tri_nutrition.tools.checkin import make_checkin_tools
from tri_nutrition.tools.garmin import make_garmin_read_tools
from tri_planning import allowlist as planning_allow
from tri_planning.config import get_planning_settings
from tri_planning.graph.deps import GraphDeps as PlanningDeps
from tri_planning.graph.deps import make_deps as make_planning_deps
from tri_wellness.ranges.registry import MarkerRegistry, load_registry

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class CoachDeps:
    model: BaseChatModel  # the coach
    analyst_model: (
        BaseChatModel  # the analyst run inside ask_analyst (scripted separately in tests)
    )
    connect: ConnectFactory
    db_url: str
    planning_deps: PlanningDeps
    nutrition_deps: NutritionDeps
    analyst_tools: list[BaseTool]
    wellness_model: BaseChatModel  # the lab interpreter run inside ask_wellness
    wellness_registry: MarkerRegistry | None = None  # None: labs not configured, no tool bound
    max_consults: int = 2
    today: Callable[[], date] = date.today


def analyst_tools_for(
    servers: Servers, db_url: str, today: Callable[[], date], connect: ConnectFactory
) -> list[BaseTool]:
    """query_training_db, the analyst's own live reads, and the two nutrition reads the coach's
    context lacks: body composition and logged intake against targets. Only the read is taken
    from nutrition's check-in tools; its writers are never bound."""
    return [
        make_query_tool(db_url),
        *filter_tools(servers.garmin_tools, ANALYST_GARMIN_TOOLS),
        *filter_tools(servers.tp_tools, ANALYST_TP_TOOLS),
        *make_garmin_read_tools(servers.garmin, today, only=("read_body_composition",)),
        *filter_tools(
            make_checkin_tools(servers.garmin, connect, today), ("read_intake_vs_targets",)
        ),
    ]


def make_deps(
    settings: CoachSettings,
    model: BaseChatModel,
    servers: Servers,
    *,
    today: Callable[[], date] = date.today,
) -> CoachDeps:
    url = settings.database_url
    connect = lambda: core_connect(url)  # noqa: E731
    planning = make_planning_deps(get_planning_settings(), model, servers.tp)
    planning.garmin_tools = filter_tools(servers.garmin_tools, planning_allow.GARMIN_LIVE_TOOLS)
    planning.today = today
    nutrition = make_nutrition_deps(get_nutrition_settings(), model, servers.garmin, servers.tp)
    nutrition.today = today
    registry = load_registry(settings.tri_athlete_sex) if settings.tri_athlete_sex else None
    return CoachDeps(
        model=model,
        analyst_model=model,
        connect=connect,
        db_url=url,
        planning_deps=planning,
        nutrition_deps=nutrition,
        analyst_tools=analyst_tools_for(servers, url, today, connect),
        wellness_model=model,
        wellness_registry=registry,
        max_consults=settings.tri_coach_max_consults_per_domain,
        today=today,
    )
