import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.checkpointer import checkpointer_ready, open_checkpointer
from tri_planning.graph.graph import build_graph
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db


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
        async with open_checkpointer(url) as saver:
            graph = build_graph(make_deps(ScriptedChatModel(script=script), tp=tp), saver)
            out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, thread)
            assert "__interrupt__" in out
        # "second process": a new saver, a new graph, a model with nothing left to say
        async with open_checkpointer(url) as saver2:
            graph2 = build_graph(make_deps(ScriptedChatModel(script=[]), tp=tp), saver2)
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), thread)
            assert out["phase"] == "active" and len(tp.calls) == 3
    finally:
        async with open_checkpointer(url) as saver3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
