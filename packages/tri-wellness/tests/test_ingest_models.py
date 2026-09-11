from datetime import date, time

import pytest
from pydantic import ValidationError

from tri_wellness.labs.models import ExtractedPanel, IngestDecision, PanelContext, RawResult


def test_extracted_panel_defaults_to_nothing_inferred():
    p = ExtractedPanel()
    assert p.drawn_on is None and p.lab_name is None and p.results == []
    p2 = ExtractedPanel.model_validate(
        {
            "drawn_on": "2026-08-20",
            "lab_name": "Quest",
            "results": [{"name": "Ferritin", "value": "42"}],
        }
    )
    assert p2.drawn_on == date(2026, 8, 20) and p2.results[0].unit is None


def test_ingest_decision_shapes():
    a = IngestDecision(action="approve", context=PanelContext(fasting=True, draw_time=time(7, 0)))
    assert a.results is None and a.note is None
    r = IngestDecision.model_validate({"action": "reject", "note": "wrong file"})
    assert r.note == "wrong file"
    e = IngestDecision.model_validate(
        {"action": "edit", "drawn_on": "2026-08-21", "unmapped": [], "results": None}
    )
    assert e.drawn_on == date(2026, 8, 21) and e.unmapped == [] and e.results is None
    with pytest.raises(ValidationError):
        IngestDecision(action="maybe")
    round_trip = IngestDecision.model_validate(a.model_dump(mode="json", exclude_none=True))
    assert round_trip == a


def test_raw_result_is_what_the_state_carries():
    assert RawResult(name="x", value="1").model_dump()["page"] is None
