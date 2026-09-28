import json
from types import SimpleNamespace

from tri_core.evals import (
    errored,
    failure_lines,
    pass_rates,
    record_rows,
    render_pass_rates,
    scored_counts,
)


def R(key, score):
    return SimpleNamespace(key=key, score=score)


ROWS = [
    {
        "evaluation_results": {
            "results": [R("uses_sql", 1), R("pulls_splits", None), R("grounded", 0)]
        }
    },
    {"evaluation_results": {"results": [R("uses_sql", 0), R("pulls_splits", 1), R("grounded", 1)]}},
    {"evaluation_results": {"results": [R("uses_sql", 1), R("grounded", 1)]}},
]


def test_pass_rates_and_counts_leave_out_unscored_keys():
    assert pass_rates(ROWS) == {"uses_sql": 2 / 3, "pulls_splits": 1.0, "grounded": 2 / 3}
    assert scored_counts(ROWS) == {"uses_sql": (2, 3), "pulls_splits": (1, 1), "grounded": (2, 3)}
    assert pass_rates([]) == {} and scored_counts([]) == {}


def test_a_row_without_results_counts_for_nothing():
    rows = [{"evaluation_results": {"results": []}}, {"run": SimpleNamespace(error="boom")}]
    assert pass_rates(rows) == {} and scored_counts(rows) == {}


def test_render_names_the_version_and_shows_counts():
    text = render_pass_rates(pass_rates(ROWS), scored_counts(ROWS), 3, version="2")
    assert text.splitlines() == [
        "pass rate over 3 examples (prompt version 2):",
        "  grounded                    67% (2/3)",
        "  pulls_splits               100% (1/1)",
        "  uses_sql                    67% (2/3)",
    ]


def test_render_without_a_version_has_no_parenthesis():
    text = render_pass_rates({"a": 1.0}, {"a": (4, 4)}, 4, version=None)
    assert text.splitlines()[0] == "pass rate over 4 examples:"


def test_errored_counts_rows_whose_run_carries_an_error():
    rows = [
        {"run": SimpleNamespace(error=None)},
        {"run": SimpleNamespace(error="IndexError: list index out of range")},
        {"run": SimpleNamespace(error="")},
        {},
    ]
    assert errored(rows) == 1 and errored([]) == 0


def _row(case, results, *, outputs=None, error=None):
    return {
        "run": SimpleNamespace(outputs=outputs or {}, error=error),
        "example": SimpleNamespace(id="ex-1", inputs={"question": "q"}, metadata={"case": case}),
        "evaluation_results": {"results": results},
    }


def test_failure_lines_name_the_case_key_and_comment():
    rows = [
        _row("z2", [R("grounded", 1)]),
        _row("threshold", [R("grounded", 0), R("uses_sql", 1)]),
        _row("brick", [R("pulls_splits", None)]),
    ]
    rows[1]["evaluation_results"]["results"][0].comment = "TSB -18 appears nowhere"
    assert failure_lines(rows) == ["  grounded  threshold: TSB -18 appears nowhere"]


def test_a_failure_without_a_comment_or_case_still_prints():
    row = _row("x", [SimpleNamespace(key="grounded", score=0)])
    row["example"].metadata = {}
    assert failure_lines([row]) == ["  grounded  ex-1: (no comment)"]


def test_record_rows_writes_one_json_line_per_example(tmp_path):
    rows = [
        _row(
            "z2", [SimpleNamespace(key="grounded", score=0, comment="no")], outputs={"answer": "58"}
        ),
        _row("run", [], error="IndexError: boom"),
    ]
    path = record_rows(rows, "analyst-v2-x", directory=tmp_path)
    assert path == tmp_path / "analyst-v2-x.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0] == {
        "case": "z2",
        "inputs": {"question": "q"},
        "outputs": {"answer": "58"},
        "error": None,
        "results": [{"key": "grounded", "score": 0, "comment": "no"}],
    }
    assert lines[1]["error"] == "IndexError: boom" and lines[1]["results"] == []


def test_the_directory_defaults_to_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "evals"))
    assert record_rows([], "e").parent == tmp_path / "evals"
