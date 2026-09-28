import json
from types import SimpleNamespace

import pytest
import requests
from langsmith import run_trees

from tri_core.eval_select import (
    EvalArgsError,
    NothingToRun,
    Selection,
    cli_selection,
    dataset_subset,
    failed_cases,
    read_results,
    rescore_rows,
    run_rescore,
    select_cases,
    selection,
    subset_examples,
)
from tri_core.eval_usage import UsageByRole

# langsmith's own: ast.Str inside the evaluator key extraction run_evaluator uses
pytestmark = pytest.mark.filterwarnings("ignore:ast.Str is deprecated:DeprecationWarning")

KNOWN = ["z2", "brick", "threshold"]


def line(case, *, scores=(), error=None, outputs=None, inputs=None, reference=None, metadata=None):
    out = {
        "case": case,
        "inputs": inputs if inputs is not None else {"q": case},
        "outputs": outputs if outputs is not None else {"answer": case},
        "error": error,
        "results": [{"key": "k", "score": s, "comment": None} for s in scores],
    }
    if reference is not None:
        out["reference_outputs"] = reference
    if metadata is not None:
        out["metadata"] = metadata
    return out


def write(path, lines):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def exact(outputs, reference_outputs):
    return {"key": "exact", "score": int(outputs.get("answer") == reference_outputs.get("want"))}


# select_cases / failed_cases / read_results


def test_select_cases_keeps_the_known_order_and_names_unknown_cases():
    assert select_cases({"threshold", "z2"}, KNOWN) == ["z2", "threshold"]
    with pytest.raises(EvalArgsError) as exc:
        select_cases({"z2", "nope", "gone"}, KNOWN)
    assert str(exc.value) == "unknown case(s): gone, nope; cases are: z2, brick, threshold"


def test_failed_cases_counts_a_low_score_or_an_error_once_and_ignores_unscored_checks():
    lines = [
        line("z2", scores=(1, None)),
        line("brick", scores=(1, 0)),
        line("threshold", error="boom"),
        line("brick", scores=(0,)),
    ]
    assert failed_cases(lines) == ["brick", "threshold"]


def test_read_results_refuses_a_missing_file_and_names_a_bad_line(tmp_path):
    with pytest.raises(EvalArgsError, match="cannot read"):
        read_results(tmp_path / "missing.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(line("z2")) + "\n{not json\n")
    with pytest.raises(EvalArgsError, match="line 2"):
        read_results(bad)
    shapeless = tmp_path / "shapeless.jsonl"
    shapeless.write_text('{"answer": 1}\n')
    with pytest.raises(EvalArgsError, match="line 1"):
        read_results(shapeless)


# selection


def test_no_options_selects_everything():
    assert selection(cases=None, failed_from=None, rescore=None, known=KNOWN) == Selection()


def test_cases_are_trimmed_and_blank_names_ignored():
    chosen = selection(cases="brick, z2,", failed_from=None, rescore=None, known=KNOWN)
    assert chosen == Selection(cases=["z2", "brick"])
    with pytest.raises(EvalArgsError, match="at least one"):
        selection(cases=",", failed_from=None, rescore=None, known=KNOWN)


def test_failed_from_and_cases_are_a_union(tmp_path):
    src = write(tmp_path / "r.jsonl", [line("z2", scores=(1,)), line("threshold", scores=(0,))])
    chosen = selection(cases="brick", failed_from=src, rescore=None, known=KNOWN)
    assert chosen.cases == ["brick", "threshold"]


def test_failed_from_with_nothing_failed_is_nothing_to_run(tmp_path):
    src = write(tmp_path / "r.jsonl", [line("z2", scores=(1,))])
    with pytest.raises(NothingToRun) as exc:
        selection(cases=None, failed_from=src, rescore=None, known=KNOWN)
    assert str(exc.value) == f"nothing failed in {src}"
    # with --cases as well there is still something to run
    assert selection(cases="z2", failed_from=src, rescore=None, known=KNOWN).cases == ["z2"]


def test_rescore_knows_the_files_cases_and_refuses_dataset_and_database_options(tmp_path):
    src = write(tmp_path / "r.jsonl", [line("old_case", scores=(0,)), line("z2")])
    chosen = selection(cases="old_case", failed_from=None, rescore=src, known=KNOWN)
    assert chosen == Selection(cases=["old_case"], rescore=src)
    with pytest.raises(EvalArgsError, match="--recreate-dataset"):
        selection(cases=None, failed_from=None, rescore=src, known=KNOWN, recreate=True)
    with pytest.raises(EvalArgsError, match="--eval-db"):
        selection(cases=None, failed_from=None, rescore=src, known=KNOWN, eval_db="postgresql://x")


def test_rescore_with_failed_from_on_the_same_file_picks_only_the_failures(tmp_path):
    src = write(tmp_path / "r.jsonl", [line("z2", scores=(1,)), line("brick", scores=(0,))])
    assert selection(cases=None, failed_from=src, rescore=src, known=KNOWN) == Selection(
        cases=["brick"], rescore=src
    )


def test_cli_selection_turns_errors_into_exit_codes(tmp_path):
    said: list[str] = []
    shouted: list[str] = []
    kw = {"failed_from": None, "rescore": None, "known": KNOWN, "out": said.append}
    assert cli_selection(cases="nope", err=shouted.append, **kw) == 2
    assert shouted and "nope" in shouted[0]
    src = write(tmp_path / "r.jsonl", [line("z2", scores=(1,))])
    assert (
        cli_selection(
            cases=None, failed_from=src, rescore=None, known=KNOWN, out=said.append, err=print
        )
        == 0
    )
    assert said == [f"nothing failed in {src}"]
    assert cli_selection(cases="z2", err=print, **kw) == Selection(cases=["z2"])


# subsets


def test_subset_examples_filters_by_case_name():
    examples = [{"metadata": {"case": name}} for name in KNOWN]
    assert subset_examples(examples, None) == examples
    assert subset_examples(examples, ["brick"]) == [{"metadata": {"case": "brick"}}]


def test_dataset_subset_keeps_named_examples_and_asks_for_a_recreate_when_names_are_missing():
    stored = [SimpleNamespace(metadata={"case": "z2"}), SimpleNamespace(metadata={"phase": "base"})]
    client = SimpleNamespace(list_examples=lambda dataset_name: iter(stored))
    assert dataset_subset(client, "d", ["z2"]) == [stored[0]]
    with pytest.raises(EvalArgsError, match="--recreate-dataset") as exc:
        dataset_subset(client, "d", ["z2", "brick"])
    assert "brick" in str(exc.value)


# rescore_rows


async def test_rescore_scores_saved_outputs_against_the_file_or_the_current_reference():
    async def judge(inputs, outputs):
        return {"results": [{"key": "judged", "score": 1, "comment": inputs["q"]}]}

    current = {
        "brick": {"inputs": {"q": "brick"}, "outputs": {"want": "brick"}},
        "threshold": {"inputs": {"q": "NEW"}, "outputs": {"want": "x"}},
    }
    lines = [
        line("z2", reference={"want": "z2"}),
        line("brick"),
        line("threshold", reference={"want": "nope"}),
        line("run", error="IndexError: boom", outputs={}),
        line("gone"),
    ]
    logged: list[str] = []
    rows, errored = await rescore_rows(
        lines, [exact, judge], lookup=current.get, cases=None, log=logged.append
    )
    assert errored == 1
    assert [r["example"].metadata["case"] for r in rows] == ["z2", "brick", "threshold"]
    assert [[(x.key, x.score) for x in r["evaluation_results"]["results"]] for r in rows] == [
        [("exact", 1), ("judged", 1)],
        [("exact", 1), ("judged", 1)],
        [("exact", 0), ("judged", 1)],
    ]
    assert rows[1]["example"].outputs == {"want": "brick"}
    assert "skipped: gone (no longer a case)" in logged
    assert "threshold: inputs changed since this file; scoring the saved inputs" in logged


async def test_rescore_runs_only_the_selected_cases():
    lines = [line("z2", reference={"want": "z2"}), line("brick", reference={"want": "brick"})]
    rows, _ = await rescore_rows(
        lines, [exact], lookup=lambda n: None, cases=["brick"], log=lambda m: None
    )
    assert [r["example"].metadata["case"] for r in rows] == ["brick"]


async def test_a_raising_evaluator_is_logged_and_the_others_still_score():
    def broken(outputs):
        raise ValueError("bad shape")

    logged: list[str] = []
    rows, _ = await rescore_rows(
        [line("z2", reference={"want": "z2"})],
        [broken, exact],
        lookup=lambda n: None,
        cases=None,
        log=logged.append,
    )
    assert [x.key for x in rows[0]["evaluation_results"]["results"]] == ["exact"]
    assert any("broken raised ValueError: bad shape" in m for m in logged)


async def test_rescore_makes_no_network_call(monkeypatch):
    monkeypatch.setattr(run_trees, "_CLIENT", None)
    attempted: list[tuple] = []

    def refuse(self, *a, **kw):
        attempted.append(a[:2])
        raise AssertionError(f"unexpected network call: {a[:2]}")

    monkeypatch.setattr(requests.Session, "request", refuse)
    rows, _ = await rescore_rows(
        [line("z2", reference={"want": "z2"})],
        [exact],
        lookup=lambda n: None,
        cases=None,
        log=lambda m: None,
    )
    assert len(rows) == 1 and attempted == [] and run_trees._CLIENT is None


# run_rescore


async def test_run_rescore_names_the_experiment_after_its_source_and_records_where_it_came_from(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    src = write(
        tmp_path / "analyst-v3-judge2-local-00e7585f.jsonl",
        [
            line(
                "z2",
                scores=(0,),
                reference={"want": "z2"},
                metadata={
                    "prompt_version": "3",
                    "model": "claude-opus-5",
                    "judge_model": "old",
                    "judge_version": "1",
                },
            ),
            line("run", error="boom", outputs={}, metadata={"prompt_version": "3"}),
        ],
    )
    logged: list[str] = []
    rates, errored = await run_rescore(
        src,
        evaluators=[exact],
        lookup=lambda name: None,
        cases=None,
        current={"judge_model": "claude-sonnet-5", "judge_version": "2"},
        usage=UsageByRole(),
        log=logged.append,
    )
    assert rates == {"exact": 1.0} and errored == 1
    [named] = [m for m in logged if m.startswith("experiment: ")]
    assert named.startswith("experiment: analyst-v3-judge2-local-00e7585f-rescore-")
    assert "1 errored in the source, not rescored" in logged
    assert "usage: no model calls" in logged
    assert "not a gate run" in logged
    assert "pass rate over 1 examples (prompt version 3):" in "\n".join(logged)
    [out_file] = (tmp_path / "out").glob("*-rescore-*.jsonl")
    out = json.loads(out_file.read_text().splitlines()[0])
    assert out["metadata"] == {
        "prompt_version": "3",
        "model": "claude-opus-5",
        "judge_model": "claude-sonnet-5",
        "judge_version": "2",
        "rescored_from": str(src),
        "gate": False,
    }
    assert out["reference_outputs"] == {"want": "z2"}


async def test_run_rescore_of_a_subset_marks_it(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    src = write(
        tmp_path / "r.jsonl",
        [line("z2", reference={"want": "z2"}), line("brick", reference={"want": "brick"})],
    )
    logged: list[str] = []
    await run_rescore(
        src,
        evaluators=[exact],
        lookup=lambda n: None,
        cases=["brick"],
        current={},
        usage=UsageByRole(),
        log=logged.append,
    )
    assert "pass rate over 1 of 2 examples (subset):" in "\n".join(logged)
    [out_file] = (tmp_path / "out").glob("*-rescore-*.jsonl")
    out = json.loads(out_file.read_text())["metadata"]
    assert out["cases"] == ["brick"] and out["gate"] is False


async def test_run_rescore_survives_a_source_where_every_row_errored(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    src = write(tmp_path / "r.jsonl", [line("z2", error="boom", outputs={})] * 2)
    logged: list[str] = []
    rates, errored = await run_rescore(
        src,
        evaluators=[exact],
        lookup=lambda n: None,
        cases=None,
        current={},
        usage=UsageByRole(),
        log=logged.append,
    )
    assert rates == {} and errored == 2
    assert "2 errored in the source, not rescored" in logged
    assert "pass rate over 0 examples:" in "\n".join(logged)


async def test_run_rescore_of_another_packages_file_skips_every_row(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path / "out"))
    src = write(tmp_path / "coach-v4-x.jsonl", [line("knee_pain_planning"), line("z2_swap")])
    logged: list[str] = []
    rates, errored = await run_rescore(
        src,
        evaluators=[exact],
        lookup=lambda n: None,
        cases=None,
        current={},
        usage=UsageByRole(),
        log=logged.append,
    )
    assert rates == {} and errored == 0
    assert "skipped: knee_pain_planning (no longer a case)" in logged
    assert "skipped: z2_swap (no longer a case)" in logged
