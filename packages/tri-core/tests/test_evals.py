import json
import os
import uuid
from types import SimpleNamespace

import pytest
import requests
from langchain_core.messages import AIMessage
from langsmith import aevaluate, run_trees, tracing_context
from langsmith.schemas import Example

from tri_core.evals import (
    LOCAL_DATASET_ID,
    disable_network_sampling,
    errored,
    failure_lines,
    local_default,
    local_examples,
    local_experiment_name,
    offline_client,
    pass_rates,
    record_rows,
    render_pass_rates,
    scored_counts,
)
from tri_core.testing import ScriptedChatModel


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


def test_record_rows_writes_the_experiment_metadata_on_every_line_when_given(tmp_path):
    path = record_rows(
        [_row("z2", []), _row("run", [])], "x", directory=tmp_path, metadata={"judge_version": "2"}
    )
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["metadata"] for line in lines] == [{"judge_version": "2"}] * 2
    bare = record_rows([_row("z2", [])], "y", directory=tmp_path)
    assert "metadata" not in json.loads(bare.read_text())


def test_the_directory_defaults_to_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "evals"))
    assert record_rows([], "e").parent == tmp_path / "evals"


def test_local_examples_builds_examples_from_inputs_outputs_and_metadata():
    examples = local_examples(
        [
            {"inputs": {"q": 1}, "outputs": {"a": 2}, "metadata": {"case": "x"}},
            {"inputs": {"q": 2}},
        ]
    )
    assert len(examples) == 2
    assert all(isinstance(e, Example) for e in examples)
    assert all(e.dataset_id == LOCAL_DATASET_ID for e in examples)
    assert uuid.UUID(int=0) == LOCAL_DATASET_ID
    assert len({e.id for e in examples}) == 2  # each example gets its own id
    assert examples[0].inputs == {"q": 1}
    assert examples[0].outputs == {"a": 2}
    assert examples[0].metadata == {"case": "x"}
    assert examples[1].outputs == {} and examples[1].metadata == {}


def test_local_default_is_false_when_unset(monkeypatch):
    monkeypatch.delenv("TRI_EVAL_LOCAL", raising=False)
    assert local_default() is False


@pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "Yes", "YES"])
def test_local_default_is_true_for_truthy_values(monkeypatch, value):
    monkeypatch.setenv("TRI_EVAL_LOCAL", value)
    assert local_default() is True


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "", "banana"])
def test_local_default_is_false_for_other_values(monkeypatch, value):
    monkeypatch.setenv("TRI_EVAL_LOCAL", value)
    assert local_default() is False


# langsmith's own: ast.Str inside its evaluator key extraction, and the upload_results beta notice
@pytest.mark.filterwarnings("ignore:ast.Str is deprecated:DeprecationWarning")
@pytest.mark.filterwarnings("ignore:'upload_results' parameter is in beta")
async def test_aevaluate_in_local_mode_makes_no_network_call(monkeypatch):
    """A real aevaluate() the way run_eval runs it in local mode (the offline client, in-memory
    Examples, upload_results=False, a local tracing context), with a target that makes a real
    LangChain model call so LangChain's own tracer is exercised too. Every request attempt is
    recorded (not raised: LangSmith swallows errors from its background thread); the offline
    client is flushed before asserting none, and langsmith's process-wide client must never
    have been created."""
    disable_network_sampling()
    monkeypatch.setattr(run_trees, "_CLIENT", None)
    attempted: list[tuple] = []

    def refuse(self, *a, **kw):
        attempted.append(a[:2])
        raise AssertionError(f"unexpected network call: {a[:2]}")

    monkeypatch.setattr(requests.Session, "request", refuse)
    model = ScriptedChatModel(script=[AIMessage(content="2"), AIMessage(content="4")])

    async def target(inputs: dict) -> dict:
        reply = await model.ainvoke(f"double {inputs['n']}")
        return {"answer": int(str(reply.content))}

    def doubled(run, example) -> dict:
        return {
            "key": "doubled",
            "score": 1 if run.outputs["answer"] == example.inputs["n"] * 2 else 0,
        }

    client = offline_client()
    data = local_examples([{"inputs": {"n": 1}}, {"inputs": {"n": 2}}])
    with tracing_context(enabled="local", client=client):
        results = await aevaluate(
            target,
            data=data,
            evaluators=[doubled],
            client=client,
            upload_results=False,
            experiment_prefix="local-mode-no-network-test",
            max_concurrency=0,
        )
        rows = [row async for row in results]
    client.flush(timeout=5)
    assert attempted == []
    # nothing fell back to langsmith's process-wide client (which starts a sender thread)
    assert run_trees._CLIENT is None
    assert len(rows) == 2
    for row in rows:
        scores = [r.score for r in row["evaluation_results"]["results"]]
        assert scores == [1]


def test_the_offline_client_never_points_at_langsmith():
    client = offline_client()
    assert "langchain.com" not in client.api_url and client.tracing_queue is None


def test_local_mode_overrides_a_sampling_rate_already_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING_SAMPLING_RATE", "1")
    disable_network_sampling()
    assert os.environ["LANGSMITH_TRACING_SAMPLING_RATE"] == "0"


def test_a_local_experiment_name_keeps_the_prefix():
    a, b = local_experiment_name("analyst-v2-local"), local_experiment_name("analyst-v2-local")
    assert a.startswith("analyst-v2-local-") and len(a) == len("analyst-v2-local-") + 8
    assert a != b
