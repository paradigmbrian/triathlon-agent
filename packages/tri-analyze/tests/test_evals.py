"""The analyst eval without LangSmith, a database or a real model."""

import json
from datetime import date

from tri_analyze.evals.cases import CASES, EXTRA_TOOLS, KINDS, TODAY, EvalCase, jsonable
from tri_analyze.repo import AthleteContext


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
