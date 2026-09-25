from datetime import date
from typing import Any

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

import tri_core.llm as llm
from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import ReportTruncated, ReportWriter, run_report
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


class Overloaded(ScriptedChatModel):
    def _generate(self, *a: Any, **k: Any) -> Any:
        raise self._error()

    def _stream(self, *a: Any, **k: Any) -> Any:
        raise self._error()

    @staticmethod
    def _error() -> anthropic.OverloadedError:
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return anthropic.OverloadedError(
            "overloaded", response=httpx.Response(529, request=req), body=None
        )


async def test_writer_falls_back_when_the_report_model_is_overloaded(monkeypatch):
    backup = ScriptedChatModel(script=[AIMessage(content="from the backup")])
    monkeypatch.setattr(llm, "fallbacks_of", lambda model: [backup])
    chunks: list[str] = []
    text = await ReportWriter(Overloaded(script=[])).write("prompt", chunks.append, ["panel_id:1"])
    assert text == "from the backup" and "".join(chunks) == "from the backup"


class Truncating(ScriptedChatModel):
    """Streams half a report, then the final chunk Anthropic sends when max_tokens is hit."""

    def _stream(self, *a: Any, **k: Any) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="## Draw conditions\nhalf a"))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", response_metadata={"stop_reason": "max_tokens"})
        )


async def test_writer_raises_when_the_stream_stops_at_max_tokens():
    chunks: list[str] = []
    with pytest.raises(ReportTruncated, match="max_tokens"):
        await ReportWriter(Truncating(script=[])).write("prompt", chunks.append, ["panel_id:1"])
    assert "".join(chunks) == "## Draw conditions\nhalf a"  # what streamed is still shown


async def test_run_report_does_not_save_a_truncated_report(nocommit, reg):
    pid = seed_panel(nocommit, D1, [("ferritin", 42.0, "ng/mL")])
    out = []
    code = await run_report(
        Truncating(script=[]), connect_factory(nocommit), reg, pid, out.append, None
    )
    assert code == 1
    assert repo.latest_report_for_panel(nocommit, pid) is None
    assert any("not saved" in s and "max_tokens" in s for s in out)
