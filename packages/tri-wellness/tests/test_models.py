from datetime import date, time

import pytest
from pydantic import ValidationError

from tri_wellness.labs.models import (
    Finding,
    LabResult,
    PanelContext,
    RawResult,
    TrainingContext,
)


def raw(**over):
    base = dict(name="Ferritin, Serum", value="42", unit="ng/mL", ref_low="30", ref_high="400")
    base.update(over)
    return RawResult(**base)


def test_raw_result_defaults():
    r = raw()
    assert r.flag is None and r.page is None
    assert r.model_dump() == {
        "name": "Ferritin, Serum",
        "value": "42",
        "unit": "ng/mL",
        "ref_low": "30",
        "ref_high": "400",
        "flag": None,
        "page": None,
    }


def test_lab_result_keeps_raw():
    lr = LabResult(
        marker="ferritin",
        value=42.0,
        unit="ng/mL",
        raw=raw(),
        lab_ref_low=30,
        lab_ref_high=400,
    )
    assert lr.note is None
    assert lr.raw.name == "Ferritin, Serum"
    assert LabResult.model_validate_json(lr.model_dump_json()) == lr


def test_panel_context_defaults_and_time():
    c = PanelContext()
    assert c.fasting is None and c.supplements == [] and c.symptoms == []
    c2 = PanelContext(
        fasting=True,
        draw_time=time(7, 30),
        supplements=["iron"],
        symptoms=["fatigue"],
    )
    again = PanelContext.model_validate(c2.model_dump(mode="json"))
    assert again == c2
    assert again.draw_time == time(7, 30)


def test_training_context_defaults():
    t = TrainingContext(drawn_on=date(2026, 9, 1))
    assert t.ctl is None and t.last_sessions == [] and t.hrv_30d_avg is None


def test_finding_statuses_are_validated():
    kw = dict(
        marker="ferritin",
        display="Ferritin",
        system="iron",
        value=42.0,
        unit="ng/mL",
        conventional_status="in_range",
        functional_status="suboptimal_low",
        functional_range=(50.0, 150.0),
        previous=(date(2026, 3, 1), 38.0),
        delta_pct=10.5,
        active_confounders=["recent_hard_session"],
        athlete_note="note",
    )
    f = Finding(**kw)
    assert f.functional_range == (50.0, 150.0)
    assert Finding.model_validate(f.model_dump(mode="json")) == f
    with pytest.raises(ValidationError):
        Finding(**{**kw, "functional_status": "meh"})
    with pytest.raises(ValidationError):
        Finding(**{**kw, "active_confounders": ["jetlag"]})
