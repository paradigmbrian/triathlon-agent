import logging
import uuid
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.checkpointer import checkpointer_ready, make_serde, open_checkpointer
from tri_nutrition.graph.graph import build_graph
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision
from tri_nutrition.testing import PROFILE_ARGS, FakeGarmin


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    change = NutritionChange(
        op="set_day_targets",
        target_key="2026-09-14",
        day=date(2026, 9, 14),
        payload={"calorie_goal": 2500, "carbs_grams": 300, "protein_grams": 150, "fat_grams": 60},
        reason="r",
    )
    decision = ReviewDecision(action="edit", changes=[change])
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(
            serde.dumps_typed({"pending_changes": [change], "review_decision": decision})
        )
    assert back == {"pending_changes": [change], "review_decision": decision}
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]


@pytest.mark.db
async def test_second_process_resumes_and_reads_profile_from_postgres(nocommit, make_deps):
    url = Settings().test_database_url
    if not checkpointer_ready(url) or not S.store_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    thread = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
    script = [
        tool_call("save_nutrition_profile", PROFILE_ARGS),
        AIMessage(content="Profile saved. Building your targets."),
    ]
    garmin = FakeGarmin()
    try:
        async with open_checkpointer(url) as saver, S.open_store(url) as store:
            # The profile lands in the real namespace of the test database; cleaned up in finally.
            deps = make_deps(ScriptedChatModel(script=script), garmin=garmin, horizon=2)
            graph = build_graph(deps, saver, store)
            out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, thread)
            assert "__interrupt__" in out
        async with open_checkpointer(url) as saver2, S.open_store(url) as store2:
            deps2 = make_deps(ScriptedChatModel(script=[]), garmin=garmin, horizon=2)
            graph2 = build_graph(deps2, saver2, store2)
            assert (await S.get_profile(store2)) is not None  # a second process sees the profile
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), thread)
            assert out["pending_changes"] == [] and len(garmin.calls) == 1
    finally:
        async with open_checkpointer(url) as saver3, S.open_store(url) as store3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
            await S.forget_all(store3)
