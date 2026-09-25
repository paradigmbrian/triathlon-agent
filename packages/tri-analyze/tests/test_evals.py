"""The analyst eval without LangSmith, a database or a real model."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

import tri_analyze.evals.run as analyze_run
from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import (
    CASES,
    EXTRA_TOOLS,
    KINDS,
    SQL_ENVELOPE_EMPTY,
    TODAY,
    EvalCase,
    jsonable,
)
from tri_analyze.evals.evaluators import (
    FeedbackJudgement,
    make_judge,
    pulls_splits,
    render_judge_prompt,
    states_window,
    uses_sql,
)
from tri_analyze.evals.run import (
    DATASET_NAME,
    case_examples,
    ensure_dataset,
    errored,
    pass_rates,
    render_pass_rates,
)
from tri_analyze.evals.target import Canned, athlete_from_inputs, make_target, stub_tools
from tri_analyze.prompts.analyst import FEEDBACK_RULES, PROMPT_VERSION
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool
from tri_core.llm import Role
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
            if name == "query_training_db":
                for r in responses:
                    assert set(json.loads(r)) == {"columns", "rows", "row_count", "truncated"}, (
                        c.name,
                        r,
                    )
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
    empty = Canned({})
    assert empty("get_activity") == "[]"  # the generic default
    assert empty("query_training_db", default=SQL_ENVELOPE_EMPTY) == SQL_ENVELOPE_EMPTY


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


async def test_query_training_db_stub_defaults_to_the_empty_envelope():
    c = case("trend_no_data")  # no canned query_training_db result
    stubs = {t.name: t for t in stub_tools(c.inputs())}
    assert await stubs["query_training_db"].ainvoke({"sql": "select 1"}) == SQL_ENVELOPE_EMPTY


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
    assert [r["name"] for r in out["tool_results"]] == ["query_training_db", "get_activity_splits"]
    assert out["tool_results"][1]["content"] == c.tool_results["get_activity_splits"][0]


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
    inputs = case("weekly_tss_8w").inputs()
    ref = case("weekly_tss_8w").outputs()

    def answer(text: str) -> dict:
        return {"calls": [], "answer": text}

    for text in (
        "Weeks from 2026-07-20 to 2026-09-13: TSS rose from 388 to 470.",
        "Between Jul 20 and Sep 13 the weekly TSS climbed steadily.",
        "Over the last 8 weeks TSS averaged 412.",
        "Looking at the past two months, volume grew.",
        "Since 20 July the trend is up.",
        "Your weight is down 1.4 kg over the last month.",  # bare singular relative window
        "In the last week you averaged 400 TSS.",
        "Weight fell 2 kg over the past year.",
        "Monthly totals: 2026-06 118.4 km, 2026-07 141.9 km, 2026-08 156.2 km.",  # ISO year-month
        "Run volume grew from June to August: up 20%.",  # month framed by from/to
        "No bike sessions are recorded for June 2026, so I cannot compute an average.",  # +year
        "September 13th was the best day.",  # month + ordinal day
        "Across 9/2 to 9/15 sleep tracked HRV.",  # slash dates
        "Weight fell from 75.4 kg on 9/13/2026 to 74.0 kg.",
        "Sept. 3 was the hardest day.",  # abbreviation with a period
        # the question is ignored, the answer's own window counts
        "Show my weekly TSS for the last 8 weeks. Over the past 8 weeks it rose from 388 to 470.",
    ):
        assert states_window(inputs, answer(text), ref)["score"] == 1, text
    for text in (
        "TSS averaged 412 with one recovery week.",
        "Here is a weekly summary of your training.",
        "I don't have data for this session.",
        "May I suggest an easier week?",  # bare month name, no day/year/framing word
        "Aerobic decoupling 5% on the long ride.",  # a month prefix inside a word
        "Marathon 4 hours; augmented 2 reps; a decent 3 watts up.",
        # echoes the question
        "Show my weekly TSS for the last 8 weeks. Here they are: 388, 402, 470.",
    ):
        r = states_window(inputs, answer(text), ref)
        assert r["score"] == 0 and r["key"] == "states_window", text
    plain = case("last_z2_ride")
    assert states_window(plain.inputs(), answer("anything"), plain.outputs())["score"] is None


def verdict(**over) -> dict:
    base = {
        "grounded": True,
        "covers_rules": True,
        "uses_athlete_comments": True,
        "concrete_takeaways": True,
        "no_generic_encouragement": True,
        "problems": [],
    }
    base.update(over)
    return base


def test_judge_prompt_carries_the_rendered_system_prompt_question_results_and_answer():
    c = case("threshold_rpe9")
    served = c.tool_results["query_training_db"][0]
    text = render_judge_prompt(
        c.inputs(),
        {
            "calls": [],
            "answer": "Third rep fell apart.",
            "tool_results": [{"name": "query_training_db", "content": served}],
        },
    )
    assert "Today is 2026-09-16." in text and FEEDBACK_RULES in text
    assert "Tools bound this session: query_training_db, get_activity, get_activity_splits" in text
    assert c.question in text
    assert "Legs were dead from the start" in text  # served, not merely canned
    assert text.rstrip().endswith("Third rep fell apart.")
    unserved = render_judge_prompt(c.inputs(), {"calls": [], "answer": "Third rep fell apart."})
    assert "Legs were dead from the start" not in unserved  # canned but never served
    assert "Tool results:\n(none)" in unserved
    bare = render_judge_prompt(case("trend_no_data").inputs(), {"calls": [], "answer": ""})
    assert "Tool results:\n(none)" in bare


async def test_judge_scores_grounded_and_feedback_quality_for_a_session():
    c = case("threshold_rpe9")
    judge = make_judge(
        ScriptedChatModel(
            script=[
                tool_call(
                    "FeedbackJudgement",
                    verdict(
                        uses_athlete_comments=False, problems=["ignores the athlete's comment"]
                    ),
                )
            ]
        )
    )
    res = await judge(c.inputs(), {"calls": [], "answer": "A hard ride."}, c.outputs())
    by_key = {r.key: r for r in res["results"]}
    assert set(by_key) == {"grounded", "feedback_quality"}
    assert by_key["grounded"].score == 1
    assert by_key["feedback_quality"].score == 0
    assert "ignores the athlete's comment" in str(by_key["feedback_quality"].comment)


async def test_judge_skips_feedback_quality_outside_session_reviews():
    c = case("weekly_tss_8w")
    judge = make_judge(
        ScriptedChatModel(
            script=[
                tool_call(
                    "FeedbackJudgement",
                    verdict(grounded=False, problems=["470 is not in the data"]),
                )
            ]
        )
    )
    res = await judge(c.inputs(), {"calls": [], "answer": "TSS peaked at 470."}, c.outputs())
    by_key = {r.key: r for r in res["results"]}
    assert by_key["grounded"].score == 0 and "470 is not in the data" in str(
        by_key["grounded"].comment
    )
    assert by_key["feedback_quality"].score is None
    assert by_key["feedback_quality"].comment == "not a session review"


async def test_a_raising_judge_scores_both_keys_zero_with_the_error():
    c = case("last_z2_ride")
    res = await make_judge(ScriptedChatModel(script=[]))(
        c.inputs(), {"calls": [], "answer": "x"}, c.outputs()
    )
    for r in res["results"]:
        assert r.score == 0 and str(r.comment).startswith("judge failed: IndexError")
    assert {r.key for r in res["results"]} == {"grounded", "feedback_quality"}
    assert FeedbackJudgement.model_fields.keys() == verdict().keys()


class FakeClient:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.created: list[str] = []
        self.examples: list[dict] = []
        self.deleted = 0

    def has_dataset(self, dataset_name):
        return dataset_name in self.names

    def delete_dataset(self, dataset_name):
        self.names.discard(dataset_name)
        self.deleted += 1

    def create_dataset(self, name, description):
        self.names.add(name)
        self.created.append(name)

    def create_examples(self, dataset_name, examples):
        self.examples += examples


def test_dataset_examples_are_created_once_and_recreated_on_request():
    examples = case_examples()
    assert DATASET_NAME == "tri_analyze_feedback" and len(examples) == len(CASES)
    assert examples[0]["inputs"] == CASES[0].inputs()
    assert examples[0]["outputs"] == CASES[0].outputs()
    assert examples[0]["metadata"] == {"case": CASES[0].name}
    client = FakeClient()
    ensure_dataset(client)
    ensure_dataset(client)
    assert client.created == [DATASET_NAME] and len(client.examples) == len(CASES)
    ensure_dataset(client, recreate=True)
    assert client.deleted == 1 and client.created == [DATASET_NAME, DATASET_NAME]


def test_pass_rates_skip_none_and_rendering_names_the_prompt_version():
    def R(key, score):
        return SimpleNamespace(key=key, score=score)

    rows = [
        {
            "evaluation_results": {
                "results": [R("uses_sql", 1), R("pulls_splits", None), R("grounded", 0)]
            }
        },
        {
            "evaluation_results": {
                "results": [R("uses_sql", 0), R("pulls_splits", 1), R("grounded", 1)]
            }
        },
    ]
    rates = pass_rates(rows)
    assert rates == {"uses_sql": 0.5, "pulls_splits": 1.0, "grounded": 0.5}
    text = render_pass_rates(rates, 2)
    assert text.startswith("pass rate over 2 examples (prompt version 1):")
    assert "uses_sql" in text and "50%" in text and "100%" in text


def test_errored_counts_rows_whose_run_carries_an_error():
    rows = [
        {"run": SimpleNamespace(error=None)},
        {"run": SimpleNamespace(error="IndexError: list index out of range")},
        {"run": SimpleNamespace(error="")},
    ]
    assert errored(rows) == 1 and errored([]) == 0


class _FakeClient:
    def __init__(self, **kw):
        pass

    def has_dataset(self, **kw):
        return True


class _FakeResults:
    experiment_name = "exp"

    def __aiter__(self):
        async def rows():
            return
            yield

        return rows()


def _stub_langsmith(monkeypatch, run_module) -> dict:
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    monkeypatch.setattr(run_module, "Client", _FakeClient)
    monkeypatch.setattr(run_module, "aevaluate", fake_aevaluate)
    return captured


def _recording_models():
    roles: list[Role] = []
    fake = ScriptedChatModel(script=[])

    def models(role: Role):
        roles.append(role)
        return fake

    return models, roles


async def test_run_eval_uses_the_analyst_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, roles = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    assert await analyze_run.run_eval(settings, models, log=lambda m: None) == ({}, 0)
    assert sorted(roles) == sorted([Role.ANALYST, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": "medium",
        "judge_model": "claude-opus-5",
    }


async def test_run_eval_without_the_judge_records_no_judge_model(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, roles = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert roles == [Role.ANALYST] and "judge_model" not in captured["metadata"]
