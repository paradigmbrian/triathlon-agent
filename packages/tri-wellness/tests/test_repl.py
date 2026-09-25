from datetime import date, time

import anthropic
import httpx
import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness import repo
from tri_wellness.graph.graph import build_ingest_graph
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.repl import (
    collect_context,
    parse_decision,
    render_review,
    review_dialogue,
    review_from_yaml,
    review_to_yaml,
    run_ingest,
    run_turn,
)
from tri_wellness.testing import load_extracted


def lr(marker, value, unit, name=None, low=None, high=None, flag=None, note=None, bound=None):
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        bound=bound,
        raw=RawResult(name=name or marker, value=f"{bound or ''}{value}", unit=unit, flag=flag),
        lab_ref_low=low,
        lab_ref_high=high,
        note=note,
    )


def payload(**over):
    base = {
        "source_path": "/labs/aug.pdf",
        "drawn_on": "2026-08-20",
        "lab_name": "Quest",
        "results": [
            lr("ferritin", 42.0, "ng/mL", "Ferritin, Serum", 30.0, 400.0).model_dump(mode="json"),
            lr("hs_crp", 0.3, "mg/L", "hs-CRP", None, 3.0, bound="<").model_dump(mode="json"),
        ],
        "unmapped": [
            Unmapped(
                raw=RawResult(name="Sed Rate", value="4", unit="mm/h"), reason="name"
            ).model_dump(mode="json"),
        ],
        "context": None,
        "duplicates": [],
        "last_error": None,
    }
    base.update(over)
    return base


def reads(lines):
    it = iter(lines)

    async def read():
        return next(it, None)

    return read


def test_render_review_table_unmapped_duplicates_and_error():
    text = render_review(payload(duplicates=[7], last_error="approve needs the panel context"))
    assert "/labs/aug.pdf" in text and "2026-08-20" in text and "Quest" in text
    assert "ferritin" in text and "42" in text and "ng/mL" in text and "30-400" in text
    assert "Ferritin, Serum" in text and "hs-CRP" in text and "-3" in text  # one-sided lab range
    assert "<0.3" in text  # a bounded value shows its bound
    assert "[name" in text and "Sed Rate" in text
    assert "panel(s) 7" in text and "approve needs the panel context" in text
    assert "already ingested as panel 9" in render_review(payload(already_ingested=9))
    assert "already ingested" not in text
    assert "2 results, 1 unmapped (0 blocking)" in text
    blocked = payload(
        unmapped=[
            {
                "raw": {
                    "name": "Zinc",
                    "value": "90",
                    "unit": "furlongs",
                    "ref_low": None,
                    "ref_high": None,
                    "flag": None,
                    "page": None,
                },
                "reason": "unit",
                "marker": "zinc",
            }
        ]
    )
    assert "1 blocking" in render_review(blocked) and "-> zinc" in render_review(blocked)


def test_parse_decision():
    assert parse_decision("approve") == ("approve", None)
    assert parse_decision("  edit ") == ("edit", None)
    assert parse_decision("reject wrong file") == ("reject", "wrong file")
    assert parse_decision("reject") == ("reject", None)
    assert parse_decision("/quit") == ("quit", None) and parse_decision("quit") == ("quit", None)
    assert parse_decision("yes") is None


async def test_collect_context_prompts_and_parses():
    out = []
    ctx = await collect_context(
        reads(["y", "7:30", "iron, vitamin d", "", "fatigue", "slept badly"]), out.append
    )
    assert ctx == PanelContext(
        fasting=True,
        draw_time=time(7, 30),
        supplements=["iron", "vitamin d"],
        diet_pattern=None,
        symptoms=["fatigue"],
        notes="slept badly",
    )
    assert any("fasting" in s for s in out)


async def test_collect_context_reasks_bad_time_and_handles_eof():
    out = []
    ctx = await collect_context(reads(["n", "half seven", "07:30", "", "", "", ""]), out.append)
    assert ctx is not None and ctx.fasting is False and ctx.draw_time == time(7, 30)
    assert sum(s.startswith("draw time") for s in out) == 2 and "use HH:MM\n" in out
    assert await collect_context(reads(["y"]), out.append) is None


def test_yaml_round_trip_and_validation():
    reg = load_registry("male", MARKERS_PATH)
    text = review_to_yaml(payload())
    assert (
        "marker: ferritin" in text
        and "raw_name: Ferritin, Serum" in text
        and "reason: name" in text
    )
    back = review_from_yaml(text, reg)
    assert [r.model_dump(mode="json") for r in back["results"]] == payload()["results"]
    assert [u.model_dump(mode="json") for u in back["unmapped"]] == payload()["unmapped"]
    assert back["drawn_on"] == date(2026, 8, 20) and back["lab_name"] == "Quest"
    assert back["context"] is None  # the untouched, all-empty template counts as no edit
    # an unmapped row moved into results with a marker, value and the canonical unit
    doc = yaml.safe_load(text)
    row = doc["unmapped"].pop()
    doc["results"].insert(
        0,
        {
            "marker": "uric_acid",
            "value": 5.1,
            "unit": "mg/dL",
            "raw_name": row["name"],
            "raw_value": row["value"],
        },
    )
    fixed = review_from_yaml(yaml.safe_dump(doc), reg)
    assert fixed["unmapped"] == [] and fixed["results"][0].marker == "uric_acid"
    assert fixed["results"][0].raw.name == "Sed Rate" and fixed["results"][0].raw.value == "4"
    with pytest.raises(ValueError, match=r"results\[0\].*marker"):
        review_from_yaml(text.replace("marker: ferritin", "marker: ferritine"), reg)
    with pytest.raises(ValueError, match=r"results\[0\].*unit"):
        review_from_yaml(text.replace("unit: ng/mL", "unit: ug/L", 1), reg)
    with pytest.raises(ValueError, match=r"results\[1\].*value"):
        review_from_yaml(text.replace("value: 0.3", "value: abc"), reg)
    with pytest.raises(ValueError, match="drawn_on"):
        review_from_yaml(text.replace("2026-08-20", "yesterday"), reg)
    assert "bound: <" in text
    with pytest.raises(ValueError, match=r"results\[1\].*bound"):
        review_from_yaml(text.replace("bound: <", "bound: about"), reg)


def test_yaml_parse_failure_raises_value_error():
    reg = load_registry("male", MARKERS_PATH)
    with pytest.raises(ValueError, match="^yaml:"):
        review_from_yaml("results: [\n  - marker: ferritin\n", reg)


async def test_review_dialogue_paths():
    out = []
    # approve is blocked while a unit row remains
    blocked = payload(
        unmapped=[
            {
                "raw": {
                    "name": "Zinc",
                    "value": "90",
                    "unit": "furlongs",
                    "ref_low": None,
                    "ref_high": None,
                    "flag": None,
                    "page": None,
                },
                "reason": "unit",
                "marker": "zinc",
            }
        ]
    )
    d = await review_dialogue(blocked, reads(["approve", "reject bad units"]), out.append, None)
    assert d is not None and d.action == "reject" and d.note == "bad units"
    assert any("need a unit or value fix" in s for s in out)
    # approve collects the context
    d = await review_dialogue(
        payload(), reads(["approve", "y", "07:30", "", "", "", ""]), out.append, None
    )
    assert (
        d is not None
        and d.action == "approve"
        and d.context is not None
        and d.context.fasting is True
    )
    # approve reuses a context that came back from an edit
    ctx = PanelContext(fasting=False).model_dump(mode="json")
    d = await review_dialogue(payload(context=ctx), reads(["approve"]), out.append, None)
    assert d is not None and d.context is not None and d.context.fasting is False
    # unknown word re-prompts; quit returns None
    assert await review_dialogue(payload(), reads(["what", "/quit"]), out.append, None) is None

    # edit calls the editor and returns its fields
    async def edit(p):
        return {
            "drawn_on": date(2026, 8, 21),
            "results": [],
            "unmapped": [],
            "lab_name": None,
            "context": PanelContext(),
        }

    d = await review_dialogue(payload(), reads(["edit"]), out.append, edit)
    assert (
        d is not None and d.action == "edit" and d.drawn_on == date(2026, 8, 21) and d.results == []
    )

    # a cancelled edit re-prompts
    async def cancel(p):
        return None

    d = await review_dialogue(payload(), reads(["edit", "reject"]), out.append, cancel)
    assert d is not None and d.action == "reject" and any("edit cancelled" in s for s in out)
    # no editor available
    d = await review_dialogue(payload(), reads(["edit", "reject"]), out.append, None)
    assert any("not available" in s for s in out)


async def test_review_dialogue_edit_with_no_context_still_prompts_on_approve():
    out = []

    # an edit that only changed drawn_on: review_from_yaml now reports context as None
    async def edit_drawn_on_only(p):
        return {
            "drawn_on": date(2026, 8, 21),
            "results": None,
            "unmapped": None,
            "lab_name": None,
            "context": None,
        }

    d = await review_dialogue(payload(), reads(["edit"]), out.append, edit_drawn_on_only)
    assert d is not None and d.action == "edit" and d.context is None
    assert d.drawn_on == date(2026, 8, 21)

    # the review node would merge that edit and hand back a payload whose context is still
    # None -- approve must run the six context prompts, not silently reuse an empty one
    d = await review_dialogue(
        payload(drawn_on="2026-08-21", context=None),
        reads(["approve", "y", "07:30", "", "", "", ""]),
        out.append,
        None,
    )
    assert d is not None and d.action == "approve"
    assert d.context is not None and d.context.fasting is True
    assert not any("using the context from your edit" in s for s in out)


async def test_review_dialogue_all_empty_context_dict_is_treated_as_absent():
    out = []
    empty_ctx = PanelContext().model_dump(mode="json")
    d = await review_dialogue(
        payload(context=empty_ctx),
        reads(["approve", "n", "", "", "", "", ""]),
        out.append,
        None,
    )
    assert d is not None and d.action == "approve"
    assert d.context is not None and d.context.fasting is False
    assert not any("using the context from your edit" in s for s in out)


async def test_run_turn_sets_error_on_api_connection_failure():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
            yield  # pragma: no cover - makes this an async generator

    out = []
    result = await run_turn(RaisingGraph(), {"source_path": "x"}, "t1", out.append)
    assert result.error is not None and "connection error" in result.error
    assert any("connection error" in s for s in out)
    assert result.interrupt is None


async def test_run_turn_sets_error_on_unexpected_exception():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None):
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

    out = []
    result = await run_turn(RaisingGraph(), {"source_path": "x"}, "t1", out.append)
    assert result.error is not None and "boom" in result.error
    assert any("boom" in s for s in out)


async def test_run_ingest_returns_1_when_graph_raises(tiny_pdf):
    class RaisingGraph:
        async def aget_state(self, cfg):
            class S:
                values: dict = {}
                next: tuple = ()

            return S()

        async def astream(self, payload, config=None, stream_mode=None):
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

    out = []
    code = await run_ingest(
        RaisingGraph(),
        source_path=str(tiny_pdf),
        source_kind="pdf",
        drawn_on_hint=None,
        thread_id="ingest:err",
        read=reads([]),
        out=out.append,
        edit=None,
    )
    assert code == 1
    assert any("boom" in s for s in out)


@pytest.mark.db
async def test_run_ingest_end_to_end(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", load_extracted("pdf_panel"))])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    kw = dict(
        source_path=str(tiny_pdf),
        source_kind="pdf",
        drawn_on_hint=None,
        thread_id="ingest:abc",
        out=out.append,
        edit=None,
    )
    code = await run_ingest(graph, read=reads(["approve", "y", "07:30", "", "", "", ""]), **kw)
    assert code == 0 and any("stored panel" in s for s in out)
    pid = int(next(s for s in out if "stored panel" in s).split()[-1])
    assert repo.get_panel(nocommit, pid) is not None
    # rerunning the same thread does not re-extract or re-store
    code = await run_ingest(graph, read=reads([]), **kw)
    assert code == 0 and model.calls == 1 and any("already stored" in s for s in out)


@pytest.mark.db
async def test_run_ingest_pause_and_resume_then_reject(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", load_extracted("pdf_panel"))])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    kw = dict(
        source_path=str(tiny_pdf),
        source_kind="pdf",
        drawn_on_hint=None,
        thread_id="ingest:def",
        out=out.append,
        edit=None,
    )
    assert await run_ingest(graph, read=reads(["/quit"]), **kw) == 3
    assert await run_ingest(graph, read=reads(["reject nope"]), **kw) == 2
    assert model.calls == 1 and any("resuming" in s for s in out)
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


@pytest.mark.db
async def test_run_ingest_reports_extraction_failure(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", {"results": []})])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    code = await run_ingest(
        graph,
        source_path=str(tiny_pdf),
        source_kind="pdf",
        drawn_on_hint=None,
        thread_id="ingest:ghi",
        read=reads([]),
        out=out.append,
        edit=None,
    )
    assert code == 1 and any("no rows" in s for s in out)


async def test_run_turn_rate_limit_line_keeps_the_resume_hint():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None):
            raise anthropic.RateLimitError(
                message="slow down",
                response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
                body=None,
            )
            yield  # pragma: no cover - makes this an async generator

    out = []
    result = await run_turn(RaisingGraph(), {"source_path": "x"}, "t1", out.append)
    assert result.error == "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    assert out == ["[rate limited: slow down. Wait a moment and rerun; the thread resumes.]\n"]
    assert result.interrupt is None
