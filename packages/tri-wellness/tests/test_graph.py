import uuid
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness import repo
from tri_wellness.graph.graph import after_extract, after_review, build_ingest_graph
from tri_wellness.graph.nodes.review import blocking_rows
from tri_wellness.labs.models import RawResult, Unmapped
from tri_wellness.testing import load_extracted

pytestmark = pytest.mark.db
FIX = Path(__file__).parent / "fixtures"
CTX = {"fasting": True, "draw_time": "07:30:00", "supplements": ["vitamin d"], "symptoms": []}
APPROVE = Command(resume={"action": "approve", "context": CTX})


def cfg():
    return {"configurable": {"thread_id": f"ingest:test-{uuid.uuid4()}"}}


def pdf_input(tiny_pdf, **over):
    base = {"source_path": str(tiny_pdf), "source_kind": "pdf", "drawn_on_hint": None}
    base.update(over)
    return base


def scripted(name="pdf_panel", **over):
    fixture = {**load_extracted(name), **over}
    return ScriptedChatModel(script=[tool_call("ExtractedPanel", fixture)])


def test_routing_functions():
    assert after_extract({"last_error": "no rows"}) == "__end__"
    assert after_extract({"last_error": None, "raw_results": []}) == "normalize"
    assert after_review({"decision": "approve"}) == "store"
    assert after_review({"decision": "reject"}) == "__end__"
    assert after_review({"decision": None}) == "review"


def test_blocking_rows_are_unit_and_value_only():
    rows = [
        Unmapped(raw=RawResult(name="a", value="1"), reason="name"),
        Unmapped(raw=RawResult(name="b", value="1"), reason="unit", marker="ferritin"),
        Unmapped(raw=RawResult(name="c", value="x"), reason="value", marker="tsh"),
        Unmapped(raw=RawResult(name="d", value="1"), reason="duplicate", marker="tsh"),
    ]
    assert [u.raw.name for u in blocking_rows(rows)] == ["b", "c"]


async def test_pdf_ingest_pauses_at_review_with_nothing_stored(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["drawn_on"] == "2026-08-20" and payload["lab_name"] == "Quest Diagnostics"
    assert [r["marker"] for r in payload["results"]] == [
        "ferritin",
        "iron_serum",
        "hs_crp",
        "glucose",
        "tsh",
    ]
    assert [(u["raw"]["name"], u["reason"]) for u in payload["unmapped"]] == [
        ("Sed Rate, Westergren", "name")
    ]
    assert payload["duplicates"] == [] and payload["last_error"] is None
    assert payload["context"] is None
    snap = await graph.aget_state(c)
    assert snap.next == ("review",)
    assert snap.values["page_count"] == 2 and snap.values["decision"] is None
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


async def test_approve_stores_one_panel_with_context_and_raw_extract(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(APPROVE, c)
    pid = out["panel_id"]
    assert isinstance(pid, int) and out["decision"] == "approve"
    panel = repo.get_panel(nocommit, pid)
    assert panel is not None
    assert (panel.drawn_on, panel.lab_name, panel.source_kind) == (
        date(2026, 8, 20),
        "Quest Diagnostics",
        "pdf",
    )
    assert panel.source_file == str(tiny_pdf)
    assert panel.context.fasting is True and panel.context.supplements == ["vitamin d"]
    assert len(panel.raw_extract) == 6  # every extracted row, mapped or not
    assert [r.marker for r in repo.list_results(nocommit, pid)] == [
        "ferritin",
        "glucose",
        "hs_crp",
        "iron_serum",
        "tsh",
    ]
    assert (await graph.aget_state(c)).next == ()


async def test_reject_stores_nothing_and_ends(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "wrong file"}), c)
    assert out["decision"] == "reject" and out.get("panel_id") is None
    assert (await graph.aget_state(c)).next == ()
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


async def test_rerun_after_reject_re_extracts(nocommit, make_deps, tiny_pdf):
    fixture = load_extracted("pdf_panel")
    model = ScriptedChatModel(
        script=[tool_call("ExtractedPanel", fixture), tool_call("ExtractedPanel", fixture)]
    )
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    rejected = await graph.ainvoke(Command(resume={"action": "reject", "note": "wrong file"}), c)
    assert rejected["decision"] == "reject"
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    assert model.calls == 2
    assert "__interrupt__" in out
    snap = await graph.aget_state(c)
    assert snap.next == ("review",) and snap.values["decision"] is None


async def test_approve_refused_until_unit_row_is_edited_away(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted("pdf_panel_bad_unit")), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    payload = out["__interrupt__"][0].value
    assert [(u["reason"], u["marker"]) for u in payload["unmapped"]] == [
        ("unit", "ferritin"),
        ("name", None),
    ]
    out = await graph.ainvoke(APPROVE, c)
    assert "__interrupt__" in out
    again = out["__interrupt__"][0].value
    assert "unit" in again["last_error"] and again["unmapped"] == payload["unmapped"]
    remaining = [u for u in payload["unmapped"] if u["reason"] == "name"]
    out = await graph.ainvoke(Command(resume={"action": "edit", "unmapped": remaining}), c)
    edited = out["__interrupt__"][0].value
    assert edited["last_error"] is None and [u["reason"] for u in edited["unmapped"]] == ["name"]
    out = await graph.ainvoke(APPROVE, c)
    assert out["panel_id"] is not None
    assert len(repo.get_panel(nocommit, out["panel_id"]).raw_extract) == 6


async def test_approve_without_context_is_refused(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), c)
    assert "context" in out["__interrupt__"][0].value["last_error"]


async def test_edit_replaces_results_and_date(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    results = out["__interrupt__"][0].value["results"][:2]
    results[0]["value"] = 43.0
    out = await graph.ainvoke(
        Command(resume={"action": "edit", "results": results, "drawn_on": "2026-08-21"}), c
    )
    payload = out["__interrupt__"][0].value
    assert payload["drawn_on"] == "2026-08-21" and len(payload["results"]) == 2
    out = await graph.ainvoke(APPROVE, c)
    stored = repo.list_results(nocommit, out["panel_id"])
    assert [(r.marker, r.value) for r in stored] == [("ferritin", 43.0), ("iron_serum", 95.0)]
    assert repo.get_panel(nocommit, out["panel_id"]).drawn_on == date(2026, 8, 21)


async def test_extraction_with_no_rows_ends_before_review(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted(results=[])), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf), cfg())
    assert "__interrupt__" not in out and "no rows" in out["last_error"]


async def test_missing_draw_date_uses_hint_or_ends(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted(drawn_on=None)), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf), cfg())
    assert "__interrupt__" not in out and "draw date" in out["last_error"]
    graph = build_ingest_graph(make_deps(scripted(drawn_on=None)), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf, drawn_on_hint=date(2026, 8, 22)), cfg())
    assert out["__interrupt__"][0].value["drawn_on"] == "2026-08-22"


async def test_export_path_is_deterministic_and_blocks_the_same_file(nocommit, make_deps, tmp_path):
    model = ScriptedChatModel(script=[])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    c = cfg()
    src = {"source_path": str(FIX / "exports" / "generic.csv"), "source_kind": "export"}
    out = await graph.ainvoke(src, c)
    payload = out["__interrupt__"][0].value
    assert model.calls == 0
    assert [r["marker"] for r in payload["results"]] == [
        "ferritin",
        "hs_crp",
        "glucose",
        "vitamin_d",
    ]
    assert payload["lab_name"] == "Function Health"
    assert payload["duplicates"] == [] and payload["already_ingested"] is None
    first = (await graph.ainvoke(APPROVE, c))["panel_id"]
    assert repo.get_panel(nocommit, first).source_sha is not None
    # the same bytes again (a re-download) are blocked at review
    c2 = cfg()
    out = await graph.ainvoke(src, c2)
    payload = out["__interrupt__"][0].value
    assert payload["duplicates"] == [first] and payload["already_ingested"] == first
    out = await graph.ainvoke(APPROVE, c2)
    again = out["__interrupt__"][0].value
    assert again["last_error"] == f"already ingested as panel {first}"
    assert (await graph.aget_state(c2)).next == ("review",)
    # different bytes for the same date and lab: a warning, and approve stores another
    other = tmp_path / "generic-2.csv"
    other.write_text((FIX / "exports" / "generic.csv").read_text().replace(",42,", ",43,"))
    c3 = cfg()
    out = await graph.ainvoke({"source_path": str(other), "source_kind": "export"}, c3)
    payload = out["__interrupt__"][0].value
    assert payload["duplicates"] == [first] and payload["already_ingested"] is None
    second = (await graph.ainvoke(APPROVE, c3))["panel_id"]
    assert second != first  # a second panel, not a merge


async def test_second_graph_on_the_same_checkpointer_resumes_at_review(
    nocommit, make_deps, tiny_pdf
):
    saver = InMemorySaver()
    c = cfg()
    await build_ingest_graph(make_deps(scripted()), saver).ainvoke(pdf_input(tiny_pdf), c)
    graph2 = build_ingest_graph(make_deps(ScriptedChatModel(script=[])), saver)
    assert (await graph2.aget_state(c)).next == ("review",)
    out = await graph2.ainvoke(APPROVE, c)
    assert out["panel_id"] is not None
