from datetime import date

from tri_wellness.labs.models import PanelSummary
from tri_wellness.repl import render_panels
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC


def test_render_panels_table():
    rows = [
        PanelSummary(
            id=3,
            drawn_on=date(2026, 8, 20),
            lab_name="Quest",
            result_count=42,
            unmapped_count=2,
            has_report=True,
        ),
        PanelSummary(
            id=1,
            drawn_on=date(2026, 3, 1),
            lab_name=None,
            result_count=30,
            unmapped_count=0,
            has_report=False,
        ),
    ]
    text = render_panels(rows)
    lines = text.splitlines()
    assert lines[0].split() == ["id", "drawn", "lab", "results", "unmapped", "report"]
    assert (
        "3" in lines[1]
        and "2026-08-20" in lines[1]
        and "Quest" in lines[1]
        and "42" in lines[1]
        and "yes" in lines[1]
    )
    assert "2026-03-01" in lines[2] and "-" in lines[2] and "no" in lines[2]
    assert render_panels([]) == "no panels stored; run `tri-wellness ingest <file>`"


def test_schema_doc_names_the_lab_tables():
    for table in ("lab_panels", "lab_results", "lab_reports"):
        assert table in WELLNESS_SCHEMA_DOC
    assert "marker" in WELLNESS_SCHEMA_DOC and "ferritin" in WELLNESS_SCHEMA_DOC
