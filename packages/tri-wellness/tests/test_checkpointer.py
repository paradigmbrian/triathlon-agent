import logging
import uuid
from datetime import time

import pytest
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.checkpointer import checkpointer_ready, make_serde, open_checkpointer
from tri_wellness.graph.graph import build_ingest_graph
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped
from tri_wellness.testing import load_extracted


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    raw = RawResult(name="Ferritin", value="42", unit="ng/mL")
    result = LabResult(marker="ferritin", value=42.0, unit="ng/mL", raw=raw)
    unmapped = Unmapped(raw=RawResult(name="ESR", value="4"), reason="name")
    ctx = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["iron"])
    state = {"raw_results": [raw], "results": [result], "unmapped": [unmapped], "context": ctx}
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed(state))
    assert back == state
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]


@pytest.mark.db
async def test_second_process_resumes_the_ingest_thread_from_postgres(
    nocommit, make_deps, tiny_pdf
):
    url = Settings().test_database_url
    if not checkpointer_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"ingest:test-{uuid.uuid4()}"}}
    src = {"source_path": str(tiny_pdf), "source_kind": "pdf", "drawn_on_hint": None}
    script = [tool_call("ExtractedPanel", load_extracted("pdf_panel"))]
    try:
        async with open_checkpointer(url) as saver:
            graph = build_ingest_graph(make_deps(ScriptedChatModel(script=script)), saver)
            out = await graph.ainvoke(src, thread)
            assert "__interrupt__" in out
        async with open_checkpointer(url) as saver2:
            graph2 = build_ingest_graph(make_deps(ScriptedChatModel(script=[])), saver2)
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            assert snap.tasks[0].interrupts[0].value["lab_name"] == "Quest Diagnostics"
            out = await graph2.ainvoke(
                Command(resume={"action": "approve", "context": {"fasting": True}}), thread
            )
            assert out["panel_id"] is not None  # written through the rolled-back connection
    finally:
        async with open_checkpointer(url) as saver3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
