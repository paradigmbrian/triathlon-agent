import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, make_serde, open_checkpointer
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.graph import build_graph
from tri_planning.graph.state import STATE_TYPES
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    import logging
    from datetime import date

    from langgraph.checkpoint.serde import jsonplus

    from tri_planning.planning.models import CalendarChange, PlannedSession

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    session = PlannedSession(
        date=date(2026, 9, 14),
        sport="bike",
        title="Ride",
        description="",
        duration_minutes=60,
        tss_planned=50,
        intensity="endurance",
    )
    change = CalendarChange(op="create", workout_date=session.date, workout=session, reason="r")
    serde = make_serde(STATE_TYPES)
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed({"pending_changes": [change]}))
    assert back == {"pending_changes": [change]}
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]


async def test_second_process_resumes_from_postgres(nocommit, make_deps):
    url = Settings().test_database_url
    if not checkpointer_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
    script = [
        tool_call("set_training_goal", GOAL_ARGS),
        AIMessage(content="Goal saved."),
        tool_call("PlannedWeek", week_json(MONDAY, 300)),
    ]
    tp = FakeTp()
    try:
        async with open_checkpointer(url, STATE_TYPES) as saver:
            graph = build_graph(make_deps(ScriptedChatModel(script=script), tp=tp), saver)
            out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, thread)
            assert "__interrupt__" in out
        # "second process": a new saver, a new graph, a model with nothing left to say
        async with open_checkpointer(url, STATE_TYPES) as saver2:
            graph2 = build_graph(make_deps(ScriptedChatModel(script=[]), tp=tp), saver2)
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), thread)
            assert out["phase"] == "active" and len(tp.calls) == 3
    finally:
        async with open_checkpointer(url, STATE_TYPES) as saver3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
