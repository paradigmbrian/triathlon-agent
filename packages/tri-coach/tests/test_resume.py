"""A second process resumes the paused review from Postgres: the same thread, a new saver."""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_coach.graph.graph import build_graph
from tri_coach.graph.state import STATE_TYPES
from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
from tri_core.testing import ScriptedChatModel
from tri_planning.testing import FakeTp

pytestmark = pytest.mark.db


async def test_second_process_resumes_the_paused_review(nocommit, make_deps, mem_store):
    url = Settings().test_database_url
    if not checkpointer_ready(url):
        pytest.skip("checkpoint tables missing in the test database")
    seed_active_plan(nocommit)
    thread = f"coach-test-{uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
    tp = FakeTp()

    def deps():
        return make_deps(
            tp=tp,
            coach=ScriptedChatModel(
                script=[consult("planning", "Move w1."), propose("Move it.", ["p1"])]
            ),
            planning=ScriptedChatModel(script=[move_call(), AIMessage(content="ok")]),
            nutrition=ScriptedChatModel(script=[]),
            analyst=ScriptedChatModel(script=[]),
        )

    try:
        async with open_checkpointer(url, STATE_TYPES) as saver:
            graph = build_graph(deps(), saver, mem_store)
            out = await graph.ainvoke({"messages": [HumanMessage("do it")]}, cfg)
            assert "__interrupt__" in out
        async with open_checkpointer(
            url, STATE_TYPES
        ) as saver2:  # a new process: nothing in memory
            graph2 = build_graph(deps(), saver2, mem_store)
            snap = await graph2.aget_state(cfg)
            assert snap.next == ("review",)
            assert snap.values["proposals"][0].id == "p1"  # Pydantic types deserialised
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), cfg)
            assert [c[0] for c in tp.calls] == ["tp_update_workout"] and out["pending"] is None
    finally:
        async with open_checkpointer(url, STATE_TYPES) as saver3:
            await saver3.adelete_thread(thread)
