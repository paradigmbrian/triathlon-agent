"""The analyst eval without LangSmith, a database or a real model."""

import json
from datetime import date

import psycopg
import pytest
from langchain_core.messages import AIMessage
from langsmith.schemas import Example

import tri_analyze.evals.run as analyze_run
from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import (
    CASES,
    EXTRA_TOOLS,
    INTERVAL_RUN,
    KINDS,
    SQL_ENVELOPE_EMPTY,
    THRESHOLD_RIDE,
    TODAY,
    EvalCase,
    jsonable,
    sql_rows,
)
from tri_analyze.evals.evaluators import (
    JUDGE_VERSION,
    FeedbackJudgement,
    make_judge,
    pulls_splits,
    render_judge_prompt,
    states_window,
    uses_sql,
)
from tri_analyze.evals.run import DATASET_NAME, case_examples, ensure_dataset
from tri_analyze.evals.target import Canned, athlete_from_inputs, make_target, stub_tools
from tri_analyze.prompts.analyst import FEEDBACK_RULES, PROMPT_VERSION
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool
from tri_core.evals import OFFLINE_API_URL
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
    base = case("run_intervals")
    c = EvalCase(
        **{
            **base.__dict__,
            "tool_results": {**base.tool_results, "query_training_db": [sql_rows(INTERVAL_RUN)]},
        }
    )
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
    base = case("run_intervals")
    c = EvalCase(
        **{
            **base.__dict__,
            "tool_results": {**base.tool_results, "query_training_db": [sql_rows(INTERVAL_RUN)]},
        }
    )
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
    base = case("threshold_rpe9")
    c = EvalCase(
        **{
            **base.__dict__,
            "tool_results": {**base.tool_results, "query_training_db": [sql_rows(THRESHOLD_RIDE)]},
        }
    )
    served = c.tool_results["query_training_db"][0]
    text = render_judge_prompt(
        c.inputs(),
        {
            "calls": [],
            "answer": "Third rep fell apart.",
            "tool_results": [{"name": "query_training_db", "content": served}],
        },
    )
    assert "Today is 2026-09-16 (Wed)." in text and FEEDBACK_RULES in text
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
    captured: dict = {"seeded": [], "cleared": [], "verified": []}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    monkeypatch.setattr(run_module, "Client", _FakeClient)
    monkeypatch.setattr(run_module, "aevaluate", fake_aevaluate)
    monkeypatch.setattr(run_module, "seed_database", captured["seeded"].append)
    monkeypatch.setattr(run_module, "clear_database", captured["cleared"].append)
    monkeypatch.setattr(run_module, "verify_readable", captured["verified"].append)
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
    logged: list[str] = []
    assert await analyze_run.run_eval(settings, models, log=logged.append) == ({}, 0)
    assert sorted(roles) == sorted([Role.ANALYST, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": "medium",
        "judge_model": "claude-opus-5",
        "judge_version": JUDGE_VERSION,
    }
    assert f"(prompt version {PROMPT_VERSION}):" in "\n".join(logged)


async def test_run_eval_without_the_judge_records_no_judge_model(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, roles = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert roles == [Role.ANALYST] and "judge_model" not in captured["metadata"]
    assert "judge_version" not in captured["metadata"]


GROUNDED = (
    "every number in the answer appears in the context or the tool results, or can be "
    "reproduced from them by a unit conversion or arithmetic within the answer's rounding; a "
    "number that appears nowhere or does not reproduce is ungrounded; a prescribed range must "
    "come from the athlete's zones or a stated fraction of a threshold; missing data is stated "
    "as missing"
)


def test_grounded_accepts_derivations_the_judge_can_reproduce():
    from tri_analyze.evals.evaluators import JUDGE_SYSTEM

    assert FeedbackJudgement.model_fields["grounded"].description == GROUNDED
    flat = " ".join(JUDGE_SYSTEM.split())
    for sentence in (
        "can be reproduced from them by a unit conversion or arithmetic within the answer's "
        "rounding",
        "Check each derivation yourself; do not flag a correct one because its arithmetic is "
        "not written out.",
        "must come from the athlete's zones or a stated fraction of a threshold",
        "numbers that do not reproduce (give the value you get)",
        "Use the calendar line to name weekdays; never infer a weekday otherwise.",
    ):
        assert sentence in flat, sentence
    assert "arithmetic the answer shows" not in flat


def test_no_case_cans_sql_any_more():
    assert all("query_training_db" not in c.tool_results for c in CASES)


async def test_the_target_binds_the_given_sql_tool():
    seen: list[str] = []

    async def query_training_db(sql: str) -> str:
        seen.append(sql)
        return SQL_ENVELOPE_EMPTY

    from langchain_core.tools import StructuredTool

    real = StructuredTool.from_function(
        coroutine=query_training_db, name="query_training_db", description="the real tool"
    )
    tools = stub_tools(case("trend_no_data").inputs(), sql_tool=real)
    assert tools[0] is real


async def test_run_eval_seeds_the_test_database_and_clears_it_after(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert captured["seeded"] == [settings.test_database_url]
    assert captured["cleared"] == [settings.test_database_url]
    assert captured["verified"] == [settings.test_database_url]


async def test_run_eval_clears_even_when_the_run_fails(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)

    async def boom(target, **kw):
        raise RuntimeError("langsmith down")

    monkeypatch.setattr(analyze_run, "aevaluate", boom)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    with pytest.raises(RuntimeError):
        await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert captured["cleared"] == [settings.test_database_url]


async def test_run_eval_logs_but_does_not_raise_when_clearing_fails(monkeypatch):
    _stub_langsmith(monkeypatch, analyze_run)

    def boom(url):
        raise psycopg.OperationalError("connection reset")

    monkeypatch.setattr(analyze_run, "clear_database", boom)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    logged: list[str] = []
    rates, errors = await analyze_run.run_eval(settings, models, judge=False, log=logged.append)
    assert (rates, errors) == ({}, 0)
    assert any(
        "could not empty the eval database: OperationalError: connection reset" in line
        for line in logged
    )


async def test_run_eval_refuses_the_athletes_database(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    with pytest.raises(ValueError, match="athlete's database"):
        await analyze_run.run_eval(
            settings, models, log=lambda m: None, eval_db_url=settings.database_url
        )
    assert captured["seeded"] == []


@pytest.mark.db
async def test_the_target_runs_real_sql_against_the_seeded_history():
    from tri_analyze.evals import seed
    from tri_core.config import Settings, reader_url

    url = Settings().test_database_url
    try:
        seed.seed_database(url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable: {exc}")
    try:
        sql = "select title, actual_tss from workouts where workout_date = date '2026-09-14'"
        model = ScriptedChatModel(
            script=[
                tool_call("query_training_db", {"sql": sql}, "c1"),
                AIMessage(content="The Z2 ride scored 58 TSS."),
            ]
        )
        out = await make_target(model, reader_url(url))(case("last_z2_ride").inputs())
        assert '"Z2 ride"' in out["tool_results"][0]["content"]
        assert "58" in out["tool_results"][0]["content"]
    finally:
        seed.clear_database(url)


async def test_run_eval_logs_failed_checks_and_writes_the_results_file(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    _stub_langsmith(monkeypatch, analyze_run)
    row = {
        "run": SimpleNamespace(outputs={"answer": "TSB -18"}, error=None),
        "example": SimpleNamespace(id="e1", inputs={}, metadata={"case": "threshold_rpe9"}),
        "evaluation_results": {
            "results": [SimpleNamespace(key="grounded", score=0, comment="-18 appears nowhere")]
        },
    }

    class OneRow(_FakeResults):
        def __aiter__(self):
            async def rows():
                yield row

            return rows()

    async def fake_aevaluate(target, **kw):
        return OneRow()

    monkeypatch.setattr(analyze_run, "aevaluate", fake_aevaluate)
    models, _ = _recording_models()
    logged: list[str] = []
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=logged.append)
    text = "\n".join(logged)
    assert "  grounded  threshold_rpe9: -18 appears nowhere" in text
    assert f"results: {tmp_path / 'exp.jsonl'}" in text
    assert '"case": "threshold_rpe9"' in (tmp_path / "exp.jsonl").read_text()


async def test_run_eval_local_skips_the_dataset_and_uses_local_examples(monkeypatch):
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    def raising_client(*a, **kw):
        raise AssertionError("Client must not be constructed in local mode")

    monkeypatch.setattr(analyze_run, "Client", raising_client)
    monkeypatch.setattr(analyze_run, "aevaluate", fake_aevaluate)
    monkeypatch.setattr(analyze_run, "seed_database", lambda url: None)
    monkeypatch.setattr(analyze_run, "clear_database", lambda url: None)
    monkeypatch.setattr(analyze_run, "verify_readable", lambda url: None)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key=None)
    logged: list[str] = []
    await analyze_run.run_eval(settings, models, judge=False, local=True, log=logged.append)
    assert captured["client"].api_url == OFFLINE_API_URL
    assert captured["upload_results"] is False
    assert isinstance(captured["data"], list) and len(captured["data"]) == len(CASES)
    assert all(isinstance(e, Example) for e in captured["data"])
    assert captured["experiment_prefix"].endswith("-local")
    # langsmith hands back a random name when nothing is uploaded; ours keeps the prefix
    [named] = [m for m in logged if m.startswith("experiment: ")]
    assert named.startswith(f"experiment: {captured['experiment_prefix']}-")
    assert f"/{named.removeprefix('experiment: ')}.jsonl" in logged[-1]


def _judged(content: str, name: str = "query_training_db") -> str:
    return render_judge_prompt(
        case("last_z2_ride").inputs(),
        {"calls": [], "answer": "ok", "tool_results": [{"name": name, "content": content}]},
    )


# The row the analyst fetched in fresh-decision-92, in its column order: a wide row whose
# positions the judge misread (power as HR and cadence).
Z2_ROW = {
    "workout_date": "2026-09-14",
    "sport": "bike",
    "title": "Z2 ride",
    "actual_duration_sec": 5460,
    "actual_tss": 58,
    "actual_if": 0.62,
    "normalized_power": 160,
    "avg_power": 155,
    "avg_hr": 132,
    "avg_cadence": 88,
    "feeling": 7,
    "rpe": 4,
    "comments": None,
}


def test_the_judge_sees_a_calendar_line_before_the_context():
    text = render_judge_prompt(case("last_z2_ride").inputs(), {"calls": [], "answer": "ok"})
    assert text.startswith(
        "Calendar: today 2026-09-16 is a Wednesday. Weeks start Monday: 2026-08-17, "
        "2026-08-24, 2026-08-31, 2026-09-07, 2026-09-14, 2026-09-21.\n\nAnalyst system prompt:\n"
    )


def test_the_judge_reads_sql_rows_as_column_value_lines():
    served = sql_rows(Z2_ROW)
    text = _judged(served)
    assert "query_training_db:\n- workout_date: 2026-09-14; sport: bike; title: Z2 ride; " in text
    assert "normalized_power: 160; avg_power: 155; avg_hr: 132" in text
    assert "comments: null" in text
    assert "row_count: 1; truncated: false" in text
    assert served not in text


def test_the_judge_keeps_the_empty_result_and_the_truncation_note():
    assert "query_training_db:\nrow_count: 0; truncated: false" in _judged(SQL_ENVELOPE_EMPTY)
    cut = json.dumps(
        {
            "columns": ["n", "tags"],
            "rows": [[1, ["a", "b"]], [2, None]],
            "row_count": 2,
            "truncated": True,
            "note": "result cut at 2 rows",
        }
    )
    assert (
        '- n: 1; tags: ["a", "b"]\n- n: 2; tags: null\n'
        "row_count: 2; truncated: true; note: result cut at 2 rows"
    ) in _judged(cut)


@pytest.mark.parametrize(
    "content",
    [
        '{"error": "sql error: boom"}',
        "not json",
        "[1, 2]",
        '{"columns": ["a", "b"], "rows": [[1]], "row_count": 1, "truncated": false}',
        '{"columns": ["a"], "rows": "x", "row_count": 1, "truncated": false}',
    ],
)
def test_the_judge_passes_anything_but_the_envelope_through(content):
    assert f"query_training_db:\n{content}" in _judged(content)


def test_other_tools_pass_through_even_when_shaped_like_the_envelope():
    env = sql_rows({"a": 1})
    assert f"get_activity:\n{env}" in _judged(env, name="get_activity")


async def test_run_eval_records_the_judge_version_in_the_experiment_and_the_results_file(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    captured = _stub_langsmith(monkeypatch, analyze_run)
    row = {
        "run": SimpleNamespace(outputs={"answer": "ok"}, error=None),
        "example": SimpleNamespace(id="e1", inputs={}, metadata={"case": "last_z2_ride"}),
        "evaluation_results": {"results": []},
    }

    class OneRow(_FakeResults):
        def __aiter__(self):
            async def rows():
                yield row

            return rows()

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return OneRow()

    monkeypatch.setattr(analyze_run, "aevaluate", fake_aevaluate)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, log=lambda m: None)
    assert captured["metadata"]["judge_version"] == JUDGE_VERSION == "2"
    line = json.loads((tmp_path / "exp.jsonl").read_text().splitlines()[0])
    assert line["metadata"] == captured["metadata"]


def test_a_multi_line_text_value_keeps_its_row_on_one_line():
    served = sql_rows(
        {"workout_date": "2026-09-14", "description": "WU 15'\nMS 3x10'\r\nCD", "tss": 85}
    )
    text = _judged(served)
    assert (
        "query_training_db:\n"
        "- workout_date: 2026-09-14; description: \"WU 15'\\nMS 3x10'\\r\\nCD\"; tss: 85\n"
        "row_count: 1; truncated: false"
    ) in text
