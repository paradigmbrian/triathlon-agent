import contextlib
from contextlib import asynccontextmanager
from datetime import date

from langchain_core.tools import tool

from tri_analyze.prompts.analyst import TOOL_GUIDE
from tri_coach.config import CoachSettings
from tri_coach.graph.deps import analyst_tools_for, make_deps
from tri_coach.servers import Servers, open_servers
from tri_core.mcp.caller import ToolsCaller
from tri_core.testing import ScriptedChatModel


def named(*names):
    out = []
    for n in names:

        def f(x: str = "") -> str:
            """fake"""
            return "{}"

        f.__name__ = n
        out.append(tool(n)(f))
    return out


async def test_open_servers_binds_unions_and_builds_callers(monkeypatch):
    garmin = named(
        "get_activity",
        "get_training_readiness",
        "get_body_composition",
        "set_nutrition_daily_settings",
    )
    tp = named("tp_get_workout", "tp_get_workouts", "tp_create_workout", "tp_set_workout_note")
    seen = {}

    @asynccontextmanager
    async def fake_open(specs, log):
        seen["specs"] = specs
        yield {"garmin": garmin, "trainingpeaks": tp}

    monkeypatch.setattr("tri_coach.servers.open_live_servers", fake_open)
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        s = await open_servers(
            stack, CoachSettings(_env_file=None), no_live=False, log=lambda m: None
        )
    assert isinstance(s, Servers)
    assert [t.name for t in s.garmin_tools] == [t.name for t in garmin]
    assert isinstance(s.garmin, ToolsCaller) and isinstance(s.tp, ToolsCaller)
    assert "set_nutrition_daily_settings" in s.garmin.names and "tp_create_workout" in s.tp.names
    garmin_spec, garmin_allow = seen["specs"]["garmin"]
    assert "get_body_composition" in garmin_spec.env["GARMIN_ENABLED_TOOLS"]
    assert (
        "get_body_composition" in garmin_allow
        and "tp_create_workout" in seen["specs"]["trainingpeaks"][1]
    )


async def test_open_servers_no_live_and_dead_server(monkeypatch):
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        s = await open_servers(
            stack, CoachSettings(_env_file=None), no_live=True, log=lambda m: None
        )
    assert s == Servers(garmin_tools=[], tp_tools=[], garmin=None, tp=None)

    @asynccontextmanager
    async def only_tp(specs, log):
        yield {"trainingpeaks": named("tp_get_workout")}

    monkeypatch.setattr("tri_coach.servers.open_live_servers", only_tp)
    async with AsyncExitStack() as stack:
        s = await open_servers(
            stack, CoachSettings(_env_file=None), no_live=False, log=lambda m: None
        )
    assert s.garmin is None and s.garmin_tools == [] and s.tp is not None


def test_analyst_tools_are_read_only_and_include_body_composition():
    servers = Servers(
        garmin_tools=named(
            "get_activity", "get_hrv_data", "get_body_composition", "set_nutrition_daily_settings"
        ),
        tp_tools=named("tp_get_workout", "tp_create_workout"),
        garmin=ToolsCaller(named("get_body_composition")),
        tp=ToolsCaller([]),
    )
    tools = analyst_tools_for(
        servers,
        CoachSettings(_env_file=None).test_database_url,
        lambda: date(2026, 9, 14),
        lambda: contextlib.nullcontext(None),
    )
    names = [t.name for t in tools]
    assert names == [
        "query_training_db",
        "get_activity",
        "get_hrv_data",
        "tp_get_workout",
        "read_body_composition",
        "read_intake_vs_targets",
    ]
    assert not {"record_fuel_feedback", "propose_target_changes"} & set(names)
    assert set(names) <= set(TOOL_GUIDE)


def test_make_deps_wires_sub_agent_deps():
    servers = Servers(
        garmin_tools=named("get_training_readiness", "get_activity"),
        tp_tools=[],
        garmin=ToolsCaller([]),
        tp=ToolsCaller([]),
    )
    model = ScriptedChatModel(script=[])
    deps = make_deps(CoachSettings(_env_file=None), model, servers, today=lambda: date(2026, 9, 14))
    assert deps.model is model and deps.analyst_model is model
    assert deps.planning_deps.tp is servers.tp and deps.nutrition_deps.garmin is servers.garmin
    assert [t.name for t in deps.planning_deps.garmin_tools] == ["get_training_readiness"]
    assert deps.max_consults == 2 and deps.today() == date(2026, 9, 14)
    assert deps.planning_deps.today() == date(2026, 9, 14) == deps.nutrition_deps.today()


def test_make_deps_loads_the_wellness_registry_only_when_sex_is_set(monkeypatch):
    servers = Servers()
    model = ScriptedChatModel(script=[])
    monkeypatch.delenv("TRI_ATHLETE_SEX", raising=False)
    deps = make_deps(CoachSettings(_env_file=None), model, servers)
    assert deps.wellness_registry is None and deps.wellness_model is model
    monkeypatch.setenv("TRI_ATHLETE_SEX", "male")
    deps = make_deps(CoachSettings(_env_file=None), model, servers)
    assert deps.wellness_registry is not None and deps.wellness_registry.sex == "male"
