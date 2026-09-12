from datetime import date

import pytest
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import ReportWriter, run_report
from tri_wellness.testing import REPORT_OK, seed_daily_metrics, seed_panel

pytestmark = pytest.mark.db
D1, D2 = date(2031, 1, 15), date(2031, 4, 15)


@pytest.fixture
def reg():
    return load_registry("male", MARKERS_PATH)


def connect_factory(nocommit):
    import contextlib

    return lambda: contextlib.nullcontext(nocommit)


async def test_writer_streams_and_returns_full_text():
    model = ScriptedChatModel(script=[AIMessage(content="# hello\n\nworld")])
    chunks = []
    text = await ReportWriter(model).write("prompt", chunks.append, ["panel_id:1"])
    assert text == "# hello\n\nworld" and "".join(chunks) == text


async def test_run_report_evaluates_saves_and_writes_file(nocommit, reg, tmp_path):
    seed_daily_metrics(nocommit, [{"metric_date": D2, "ctl": 60.0, "atl": 80.0, "tsb": -20.0}])
    p1 = seed_panel(nocommit, D1, [("ferritin", 35.0, "ng/mL")])
    repo.insert_report(nocommit, p1, "old", [], "## Priorities\n1. Iron.\n\n## Retest plan\nMarch")
    p2 = seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    out = []
    path = tmp_path / "report.md"
    code = await run_report(model, connect_factory(nocommit), reg, None, out.append, path)
    assert code == 0
    assert path.read_text() == REPORT_OK
    saved = repo.latest_report_for_panel(nocommit, p2)
    assert (
        saved is not None and saved.report_md == REPORT_OK and saved.ranges_version == reg.version
    )
    fer = next(f for f in saved.findings if f.marker == "ferritin")
    assert fer.previous == (D1, 35.0) and fer.delta_pct == 20.0
    assert fer.active_confounders == [] and "high_acute_load" not in fer.active_confounders
    joined = "".join(out)
    assert REPORT_OK in joined and f"saved report {saved.id} for panel {p2}" in joined
    # the prompt carried the previous priorities: check what the model received
    # (ScriptedChatModel does not record; covered by test_report_prompt) and that a second run
    # adds a row rather than replacing
    model2 = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    assert await run_report(model2, connect_factory(nocommit), reg, p2, out.append, None) == 0
    assert repo.latest_report_for_panel(nocommit, p2).id > saved.id


async def test_run_report_without_panels_or_with_bad_id(nocommit, reg):
    out = []
    assert (
        await run_report(
            ScriptedChatModel(script=[]), connect_factory(nocommit), reg, None, out.append, None
        )
        == 1
    )
    assert any("no panels" in s for s in out)
    assert (
        await run_report(
            ScriptedChatModel(script=[]), connect_factory(nocommit), reg, 999999, out.append, None
        )
        == 1
    )
    assert any("no panel 999999" in s for s in out)
