from types import SimpleNamespace

from tri_core.evals import errored, pass_rates, render_pass_rates, scored_counts


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
