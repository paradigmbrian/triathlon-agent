"""The analyst eval without LangSmith, a database or a real model."""

import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.evals.cases import CASES, EXTRA_TOOLS, KINDS, TODAY, EvalCase, jsonable
from tri_analyze.evals.evaluators import pulls_splits, states_window, uses_sql
from tri_analyze.evals.target import Canned, athlete_from_inputs, make_target, stub_tools
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool
from tri_core.testing import ScriptedChatModel, tool_call


def case(name: str) -> EvalCase:
    return next(c for c in CASES if c.name == name)


def test_cases_are_valid_and_cover_every_kind():
    assert len({c.name for c in CASES}) == len(CASES) == 12
    assert date(2026, 9, 16) == TODAY
    assert {c.kind for c in CASES} == set(KINDS)
    for c in CASES:
        assert c.athlete.today == TODAY, c.name
        assert c.question.strip(), c.name
        assert set(c.extra_tools) <= set(EXTRA_TOOLS), c.name
        for name, responses in c.tool_results.items():
            assert responses and all(isinstance(r, str) for r in responses), (c.name, name)
        i, o = c.inputs(), c.outputs()
        assert set(i) == {"question", "athlete", "live", "extra_tools", "tool_results"}, c.name
        assert o == {
            "kind": c.kind,
            "requires_sql": c.requires_sql,
            "requires_splits": c.requires_splits,
            "expects_window": c.expects_window,
        }, c.name
        json.dumps(i)  # JSON-safe: dates are ISO strings
        json.dumps(o)
        assert i["athlete"]["today"] == "2026-09-16"
    assert all(c.requires_sql for c in CASES if c.requires_splits)  # splits need the activity id
    assert any(c.requires_splits and c.live for c in CASES)
    assert any(c.requires_splits and not c.live for c in CASES)
    assert any(not c.requires_sql for c in CASES)
    assert any(c.expects_window for c in CASES)
    assert any("read_body_composition" in c.extra_tools for c in CASES)
    assert any(not c.tool_results for c in CASES)  # a case whose SQL returns []


def test_jsonable_converts_nested_dates():
    ctx = AthleteContext(
        today=date(2026, 9, 16),
        profile={"ftp_watts": 250},
        recent_days=[{"metric_date": date(2026, 9, 15), "ctl": 48.0}],
    )
    from dataclasses import asdict

    out = jsonable(asdict(ctx))
    assert out["today"] == "2026-09-16"
    assert out["recent_days"][0]["metric_date"] == "2026-09-15" and out["profile"] == {
        "ftp_watts": 250
    }
    assert jsonable([date(2026, 1, 2), 3, "x"]) == ["2026-01-02", 3, "x"]


def test_athlete_round_trips_through_inputs():
    for c in CASES:
        assert athlete_from_inputs(c.inputs()) == c.athlete, c.name


def test_stub_names_and_order_match_the_real_binding():
    live = [t.name for t in stub_tools({"live": True})]
    assert live == ["query_training_db", *GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
    assert [t.name for t in stub_tools({"live": False})] == ["query_training_db"]
    coach = [t.name for t in stub_tools({"live": True, "extra_tools": list(EXTRA_TOOLS)})]
    assert coach == [*live, *EXTRA_TOOLS]
    only_extra = stub_tools({"live": False, "extra_tools": ["read_intake_vs_targets"]})
    assert [t.name for t in only_extra] == ["query_training_db", "read_intake_vs_targets"]


def test_stub_sql_description_equals_the_real_tool_and_arguments_are_named_like_the_real_ones():
    stubs = {t.name: t for t in stub_tools({"live": True, "extra_tools": list(EXTRA_TOOLS)})}
    real = make_query_tool("postgresql://unused/db")
    assert stubs["query_training_db"].description == real.description
    assert set(stubs["query_training_db"].args) == set(real.args) == {"sql"}
    assert set(stubs["get_activity"].args) == {"activity_id"}
    assert set(stubs["get_activity_splits"].args) == {"activity_id"}
    assert set(stubs["get_training_readiness"].args) == {"date"}
    assert set(stubs["get_hrv_data"].args) == {"date"}
    assert set(stubs["tp_get_workout"].args) == {"workout_id"}
    assert set(stubs["read_body_composition"].args) == {"days"}
    assert set(stubs["read_intake_vs_targets"].args) == {"days"}
    for name, t in stubs.items():
        assert t.description.strip(), name


def test_every_case_only_cans_results_for_tools_it_binds():
    for c in CASES:
        bound = {t.name for t in stub_tools(c.inputs())}
        assert set(c.tool_results) <= bound, c.name


def test_canned_serves_in_order_repeats_the_last_and_defaults_to_empty():
    canned = Canned({"query_training_db": ["[1]", "[2]"]})
    assert [canned("query_training_db") for _ in range(3)] == ["[1]", "[2]", "[2]"]
    assert canned("get_activity") == "[]"


async def test_stubs_answer_from_the_case():
    c = case("run_intervals")
    stubs = {t.name: t for t in stub_tools(c.inputs())}
    assert (
        await stubs["query_training_db"].ainvoke({"sql": "select 1"})
        == c.tool_results["query_training_db"][0]
    )
    assert (
        await stubs["get_activity_splits"].ainvoke({"activity_id": "g-1502"})
        == c.tool_results["get_activity_splits"][0]
    )
    assert await stubs["tp_get_workout"].ainvoke({"workout_id": "w"}) == "[]"


async def test_target_returns_the_calls_and_the_final_answer():
    c = case("run_intervals")
    model = ScriptedChatModel(
        script=[
            tool_call(
                "query_training_db",
                {"sql": "select * from workouts where workout_date = '2026-09-15'"},
                "c1",
            ),
            tool_call("get_activity_splits", {"activity_id": "g-1502"}, "c2"),
            AIMessage(content="Reps 1-4 held 4:10-4:18/km; 5 and 6 drifted to 4:24 and 4:32."),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert model.calls == 3
    assert [x["name"] for x in out["calls"]] == ["query_training_db", "get_activity_splits"]
    assert out["calls"][1]["args"] == {"activity_id": "g-1502"}
    assert out["answer"].startswith("Reps 1-4 held")


async def test_target_propagates_an_exception_so_langsmith_records_an_error():
    c = case("last_z2_ride")
    with pytest.raises(IndexError):
        await make_target(ScriptedChatModel(script=[]))(c.inputs())


def calls(*names: str) -> dict:
    return {"calls": [{"name": n, "args": {}} for n in names], "answer": ""}


def test_uses_sql_pass_fail_and_not_applicable():
    ref = case("last_z2_ride").outputs()
    assert uses_sql(calls("query_training_db", "get_activity"), ref) == {
        "key": "uses_sql",
        "score": 1,
        "comment": "1 query_training_db call(s)",
    }
    assert uses_sql(calls("get_activity"), ref)["score"] == 0
    assert uses_sql(calls(), case("go_hard_today").outputs())["score"] is None


def test_pulls_splits_pass_fail_and_not_applicable():
    live = case("run_intervals")
    assert (
        pulls_splits(
            live.inputs(), calls("query_training_db", "get_activity_splits"), live.outputs()
        )["score"]
        == 1
    )
    r = pulls_splits(live.inputs(), calls("query_training_db", "get_activity"), live.outputs())
    assert r["score"] == 0 and r["key"] == "pulls_splits"
    no_live = case("intervals_no_live")
    assert (
        pulls_splits(no_live.inputs(), calls("query_training_db"), no_live.outputs())["score"]
        is None
    )
    plain = case("last_z2_ride")
    assert (
        pulls_splits(plain.inputs(), calls("query_training_db"), plain.outputs())["score"] is None
    )


def test_states_window_accepts_iso_month_day_and_relative_windows():
    ref = case("weekly_tss_8w").outputs()

    def answer(text: str) -> dict:
        return {"calls": [], "answer": text}

    for text in (
        "Weeks from 2026-07-20 to 2026-09-13: TSS rose from 388 to 470.",
        "Between Jul 20 and Sep 13 the weekly TSS climbed steadily.",
        "Over the last 8 weeks TSS averaged 412.",
        "Looking at the past two months, volume grew.",
        "Since 20 July the trend is up.",
    ):
        assert states_window(answer(text), ref)["score"] == 1, text
    r = states_window(answer("TSS averaged 412 with one recovery week."), ref)
    assert r["score"] == 0 and r["key"] == "states_window"
    assert states_window(answer("anything"), case("last_z2_ride").outputs())["score"] is None
