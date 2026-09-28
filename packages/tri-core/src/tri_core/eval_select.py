"""Choosing which cases an eval runs, and re-scoring a results file's saved outputs: the two
ways to check a change without paying for a full run
(docs/superpowers/specs/2026-09-28-eval-cost-design.md §4-5)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langsmith import tracing_context
from langsmith.evaluation import EvaluationResult
from langsmith.evaluation.evaluator import run_evaluator
from langsmith.schemas import Example, Run

from tri_core.eval_usage import UsageByRole
from tri_core.evals import LOCAL_DATASET_ID, finish_run

CASES_HELP = "Comma-separated case names: runs only those (a subset, never a gate)"
FAILED_FROM_HELP = "Runs only the cases that failed or errored in this .evals/ results file"
RESCORE_HELP = (
    "Re-runs the evaluators over this .evals/ results file's saved outputs: no target calls, no "
    "database, always local"
)

CaseLookup = Callable[[str], dict[str, Any] | None]

# Carried from the source's metadata by a rescore only when the current run doesn't set them.
_NOT_CARRIED = frozenset({"judge_model", "judge_version", "cases", "rescored_from"})


class EvalArgsError(ValueError):
    """A bad --cases / --failed-from / --rescore request: the CLI prints it and exits 2."""


class NothingToRun(Exception):
    """--failed-from named a file where nothing failed: the CLI prints it and exits 0."""


@dataclass(frozen=True)
class Selection:
    cases: list[str] | None = None  # None: every case
    rescore: Path | None = None  # a results file to re-score instead of running the target


def read_results(path: Path) -> list[dict[str, Any]]:
    """The lines of a `.evals/<experiment>.jsonl` file; EvalArgsError when it can't be read or a
    line isn't a results line."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise EvalArgsError(f"cannot read {path}: {exc.strerror or exc}") from None
    lines: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict) or "case" not in parsed:
            raise EvalArgsError(f"{path} line {number} is not a .evals results line")
        lines.append(parsed)
    return lines


def failed_cases(lines: Sequence[dict[str, Any]]) -> list[str]:
    """Cases with an error or any scored check below 1, once each, in file order."""
    out: list[str] = []
    for line in lines:
        failed = bool(line.get("error")) or any(
            r.get("score") is not None and float(r["score"]) < 1.0
            for r in line.get("results") or []
        )
        if failed and line["case"] not in out:
            out.append(line["case"])
    return out


def select_cases(requested: set[str], known: Sequence[str]) -> list[str]:
    unknown = sorted(requested - set(known))
    if unknown:
        raise EvalArgsError(f"unknown case(s): {', '.join(unknown)}; cases are: {', '.join(known)}")
    return [name for name in known if name in requested]


def selection(
    *,
    cases: str | None,
    failed_from: Path | None,
    rescore: Path | None,
    known: Sequence[str],
    recreate: bool = False,
    eval_db: str | None = None,
) -> Selection:
    """The CLI's --cases / --failed-from / --rescore as a Selection. For --rescore the known
    cases are the file's own."""
    if rescore is not None and recreate:
        raise EvalArgsError("--rescore reads a results file; drop --recreate-dataset")
    if rescore is not None and eval_db is not None:
        raise EvalArgsError("--rescore touches no database; drop --eval-db")
    if rescore is not None:
        known = [line["case"] for line in read_results(rescore)]
    requested: set[str] = set()
    if cases is not None:
        requested |= {name.strip() for name in cases.split(",") if name.strip()}
        if not requested:
            raise EvalArgsError("--cases needs at least one case name")
    if failed_from is not None:
        failed = failed_cases(read_results(failed_from))
        if not failed and cases is None:
            raise NothingToRun(f"nothing failed in {failed_from}")
        requested |= set(failed)
    if cases is None and failed_from is None:
        return Selection(rescore=rescore)
    return Selection(cases=select_cases(requested, known), rescore=rescore)


def cli_selection(
    *,
    cases: str | None,
    failed_from: Path | None,
    rescore: Path | None,
    known: Sequence[str],
    out: Callable[[str], None],
    err: Callable[[str], None],
    recreate: bool = False,
    eval_db: str | None = None,
) -> Selection | int:
    """`selection` for an `eval` command: the Selection, or the exit code when there is nothing
    to run (0, told with `out`) or the request is bad (2, told with `err`)."""
    try:
        return selection(
            cases=cases,
            failed_from=failed_from,
            rescore=rescore,
            known=known,
            recreate=recreate,
            eval_db=eval_db,
        )
    except NothingToRun as exc:
        out(str(exc))
        return 0
    except EvalArgsError as exc:
        err(str(exc))
        return 2


def subset_examples(
    examples: list[dict[str, Any]], cases: list[str] | None
) -> list[dict[str, Any]]:
    if cases is None:
        return examples
    chosen = set(cases)
    return [e for e in examples if (e.get("metadata") or {}).get("case") in chosen]


def dataset_subset(client: Any, dataset_name: str, cases: list[str]) -> list[Any]:
    """The stored examples named in `cases`, for a LangSmith-mode subset; the dataset itself is
    never rebuilt."""
    chosen = set(cases)
    examples = [
        e
        for e in client.list_examples(dataset_name=dataset_name)
        if (e.metadata or {}).get("case") in chosen
    ]
    missing = sorted(chosen - {(e.metadata or {}).get("case") for e in examples})
    if missing:
        raise EvalArgsError(
            f"the LangSmith dataset {dataset_name} has no example named {', '.join(missing)}; "
            "run once with --recreate-dataset so its examples carry case names"
        )
    return examples


def _jsonable(value: Any) -> Any:
    """What `value` looks like after a results file's JSON round trip."""
    return json.loads(json.dumps(value, default=str))


async def rescore_rows(
    lines: Sequence[dict[str, Any]],
    evaluators: Sequence[Callable[..., Any]],
    *,
    lookup: CaseLookup,
    cases: list[str] | None,
    log: Callable[[str], None],
) -> tuple[list[dict[str, Any]], int]:
    """Runs `evaluators` over each line's saved outputs the way aevaluate maps their arguments,
    two lines at a time, with tracing off. Returns rows in the shape pass_rates and record_rows
    read, and the number of lines skipped because their target errored."""
    wanted = set(cases) if cases is not None else None
    todo: list[tuple[dict[str, Any], dict[str, Any]]] = []
    errored = 0
    for line in lines:
        name = line["case"]
        if wanted is not None and name not in wanted:
            continue
        if line.get("error") and not line.get("outputs"):
            errored += 1
            continue
        current = lookup(name)
        reference = line.get("reference_outputs")
        if reference is None:
            if current is None:
                log(f"skipped: {name} (no longer a case)")
                continue
            reference = current.get("outputs") or {}
        if current is not None and _jsonable(current.get("inputs")) != line.get("inputs"):
            log(f"{name}: inputs changed since this file; scoring the saved inputs")
        todo.append((line, reference))

    wrapped = [(getattr(e, "__name__", repr(e)), run_evaluator(e)) for e in evaluators]
    gate = asyncio.Semaphore(2)

    async def score(line: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            example = Example(
                id=uuid.uuid4(),
                dataset_id=LOCAL_DATASET_ID,
                inputs=line.get("inputs") or {},
                outputs=reference,
                metadata={"case": line["case"]},
            )
            run = Run(
                id=uuid.uuid4(),
                name="rescore",
                start_time=datetime.now(UTC),
                run_type="chain",
                inputs=example.inputs,
                outputs=line.get("outputs") or {},
                error=line.get("error"),
                trace_id=uuid.uuid4(),
            )
            results: list[EvaluationResult] = []
            for name, evaluator in wrapped:
                try:
                    out = await evaluator.aevaluate_run(run, example)
                except Exception as exc:
                    log(f"{line['case']}: {name} raised {type(exc).__name__}: {exc}")
                    continue
                if isinstance(out, EvaluationResult):
                    results.append(out)
                else:
                    results.extend(out["results"])
            return {"run": run, "example": example, "evaluation_results": {"results": results}}

    with tracing_context(enabled=False):
        rows = await asyncio.gather(*(score(line, ref) for line, ref in todo))
    return list(rows), errored


async def run_rescore(
    path: Path,
    *,
    evaluators: Sequence[Callable[..., Any]],
    lookup: CaseLookup,
    cases: list[str] | None,
    current: dict[str, Any],
    usage: UsageByRole,
    log: Callable[[str], None],
) -> tuple[dict[str, float], int]:
    """Re-scores `path` and reports it like any run, under `<stem>-rescore-<8 hex>`. `current`
    is the judge fields of this run. Returns the pass rates and the lines not rescored because
    their target errored."""
    lines = read_results(path)
    rows, errored = await rescore_rows(lines, evaluators, lookup=lookup, cases=cases, log=log)
    if errored:
        log(f"{errored} errored in the source, not rescored")
    source = (lines[0].get("metadata") or {}) if lines else {}
    metadata = {k: v for k, v in source.items() if k not in _NOT_CARRIED}
    metadata.update(current)
    metadata["rescored_from"] = str(path)
    metadata["gate"] = False  # no target calls: never a gate
    if cases is not None:
        metadata["cases"] = cases
    version = metadata.get("prompt_version")
    rates, _ = finish_run(
        rows,
        f"{path.stem}-rescore-{uuid.uuid4().hex[:8]}",
        version=None if version is None else str(version),
        metadata=metadata,
        usage=usage,
        log=log,
        total=len(lines) if cases is not None else None,
    )
    return rates, errored
