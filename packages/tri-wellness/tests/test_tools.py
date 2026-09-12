import contextlib
import json
from datetime import date

import pytest

from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import seed_daily_metrics, seed_panel
from tri_wellness.tools.findings import make_findings_tools

pytestmark = pytest.mark.db
D1, D2 = date(2031, 1, 15), date(2031, 4, 15)


@pytest.fixture
def tools(nocommit):
    reg = load_registry("male", MARKERS_PATH)
    return make_findings_tools(lambda: contextlib.nullcontext(nocommit), reg)


def test_tool_names_and_order(tools):
    assert [t.name for t in tools] == [
        "get_panel_findings",
        "get_marker_spec",
        "get_marker_history",
    ]
    assert "latest" in tools[0].description and "alias" in tools[1].description


def test_get_panel_findings_latest_and_by_id(nocommit, tools):
    seed_daily_metrics(nocommit, [{"metric_date": D2, "ctl": 60.0, "atl": 80.0, "tsb": -20.0}])
    p1 = seed_panel(nocommit, D1, [("ferritin", 35.0, "ng/mL")])
    p2 = seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL"), ("cortisol_am", 12.0, "ug/dL")])
    findings_tool = tools[0]
    out = json.loads(findings_tool.invoke({"panel": "latest"}))
    assert out["panel"]["id"] == p2 and out["panel"]["drawn_on"] == "2031-04-15"
    assert out["panel"]["context"]["fasting"] is True
    assert out["training"]["atl"] == 80.0 and out["ranges_version"]
    by_marker = {f["marker"]: f for f in out["findings"]}
    fer = by_marker["ferritin"]
    assert fer["functional_status"] == "suboptimal_low" and fer["functional_range"] == [50.0, 150.0]
    assert fer["previous"] == ["2031-01-15", 35.0] and fer["delta_pct"] == 20.0
    assert "athlete_note" not in fer and fer["display"] == "Ferritin"
    assert by_marker["cortisol_am"]["active_confounders"] == ["high_acute_load"]
    first = json.loads(findings_tool.invoke({"panel": str(p1)}))
    assert first["panel"]["id"] == p1 and first["findings"][0]["previous"] is None
    assert "error" in json.loads(findings_tool.invoke({"panel": "999999"}))
    assert "error" in json.loads(findings_tool.invoke({"panel": "x"}))


def test_get_panel_findings_without_panels(tools):
    assert "no panels" in json.loads(tools[0].invoke({"panel": "latest"}))["error"]


def test_get_marker_spec_by_key_or_alias(tools):
    spec = json.loads(tools[1].invoke({"marker": "Ferritin, Serum"}))
    assert spec["key"] == "ferritin" and spec["unit"] == "ng/mL"
    assert spec["conventional"] == {"low": 30.0, "high": 400.0}
    assert spec["functional"] == {"low": 50.0, "high": 150.0}
    assert spec["sex"] == "male" and "acute-phase" in spec["athlete_note"]
    assert spec["confounders"] == ["recent_hard_session", "inflammation"] and spec["sources"]
    assert json.loads(tools[1].invoke({"marker": "hs_crp"}))["key"] == "hs_crp"
    assert "error" in json.loads(tools[1].invoke({"marker": "unobtainium"}))


def test_get_marker_history_oldest_first_with_status(nocommit, tools):
    seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL")])
    seed_panel(nocommit, D1, [("ferritin", 25.0, "ng/mL")])
    out = json.loads(tools[2].invoke({"marker": "ferritin"}))
    assert out["marker"] == "ferritin" and out["unit"] == "ng/mL"
    assert out["functional_range"] == [50.0, 150.0]
    assert [(h["drawn_on"], h["value"], h["functional_status"]) for h in out["history"]] == [
        ("2031-01-15", 25.0, "low"),
        ("2031-04-15", 42.0, "suboptimal_low"),
    ]
    assert json.loads(tools[2].invoke({"marker": "TSH"}))["history"] == []
    assert "error" in json.loads(tools[2].invoke({"marker": "unobtainium"}))
