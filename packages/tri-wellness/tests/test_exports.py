import contextlib
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.nodes.extract import make_extract_node
from tri_wellness.labs.extract.exports import (
    ExportError,
    detect_format,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import RecordingScriptedModel, load_extracted

FIX = Path(__file__).parent / "fixtures" / "exports"


def test_detect_generic_csv():
    assert detect_format(FIX / "generic.csv") == "generic_csv"
    assert detect_format(FIX / "unknown.csv") is None


def test_parse_generic_csv():
    panel = parse_export(FIX / "generic.csv")
    assert panel is not None
    assert panel.drawn_on == date(2026, 8, 20) and panel.lab_name == "Function Health"
    assert [r.name for r in panel.results] == ["Ferritin", "hs-CRP", "Glucose", "Vitamin D"]
    crp = panel.results[1]
    assert (crp.value, crp.unit, crp.ref_low, crp.ref_high, crp.flag) == (
        "<0.3",
        "mg/L",
        None,
        "3.0",
        None,
    )
    assert panel.results[3].flag == "L"
    assert all(r.page is None for r in panel.results)
    # a ragged trailing line (fewer cells than the header) is skipped, not a crash
    assert len(panel.results) == 4


def test_parse_generic_csv_without_date_or_lab(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Test,Result,Units\nFerritin,42,ng/mL\n")
    panel = parse_export(p)
    assert panel is not None and panel.drawn_on is None and panel.lab_name is None
    assert panel.results[0].unit == "ng/mL" and panel.results[0].ref_low is None


def test_unknown_layout_returns_none():
    assert parse_export(FIX / "unknown.csv") is None


async def test_model_fallback_puts_file_text_in_prompt():
    fixture = load_extracted("pdf_panel")
    model = RecordingScriptedModel(script=[tool_call("ExtractedPanel", fixture)])
    panel = await extract_export_with_model(model, FIX / "unknown.csv", date(2026, 8, 20), None)
    assert panel.results[0].name == "Ferritin"
    human = model.received[0][1]
    assert isinstance(human, HumanMessage) and isinstance(human.content, list)
    assert len(human.content) == 1 and "foo,bar,baz" in human.content[0]["text"]
    assert "2026-08-20" in human.content[0]["text"]


TWO_DATES = (
    "name,value,unit,collected\n"
    "Ferritin,42,ng/mL,2026-08-20\n"
    "Glucose,92,mg/dL,2026-08-20\n"
    "Vitamin D,38,ng/mL,2026-09-03\n"
)


def test_two_date_csv_is_refused_naming_the_dates(tmp_path):
    p = tmp_path / "two.csv"
    p.write_text(TWO_DATES)
    with pytest.raises(ExportError, match=r"2 draw dates \(2026-08-20, 2026-09-03\).*split"):
        parse_export(p)
    p.write_text(TWO_DATES.replace("2026-09-03", "2026-08-20"))
    assert parse_export(p).drawn_on == date(2026, 8, 20)  # one date across rows is fine


async def test_extract_node_ends_the_run_on_a_two_date_csv(tmp_path):
    p = tmp_path / "two.csv"
    p.write_text(TWO_DATES)
    deps = GraphDeps(
        model=ScriptedChatModel(script=[]),
        connect=lambda: contextlib.nullcontext(None),
        registry=load_registry("male", MARKERS_PATH),
    )
    out = await make_extract_node(deps)(
        {"source_path": str(p), "source_kind": "export", "drawn_on_hint": None}, {}
    )
    assert "2026-08-20, 2026-09-03" in out["last_error"] and "split" in out["last_error"]
    assert out["raw_results"] == [] and deps.model.calls == 0  # no model fallback either
