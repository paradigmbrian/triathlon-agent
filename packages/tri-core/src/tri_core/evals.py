"""Pass rates for every package's LangSmith eval, in one format: the rate and the scored count
per evaluator key, so "every example passed" can be read from the log without LangSmith. Each
run's examples, outputs and judge comments are also written to a local JSONL file, so a run
LangSmith did not ingest (the monthly trace limit, 2026-09-28) can still be read."""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from langsmith.schemas import Example

KEY_WIDTH = 26

LOCAL_DATASET_ID = uuid.UUID(int=0)


def local_default() -> bool:
    """`TRI_EVAL_LOCAL`, read fresh (not cached) so a test or a caller can flip it: true for
    1/true/yes, case-insensitive, else false."""
    return (os.environ.get("TRI_EVAL_LOCAL") or "").strip().lower() in {"1", "true", "yes"}


def disable_network_sampling() -> None:
    """Belt-and-braces for local mode: `aevaluate()` traces each example's target call through a
    hard-coded `tracing_context(enabled=True)` inside langsmith itself (`_aforward` /
    `_ensure_async_traceable` in `langsmith.evaluation._arunner`), which overrides `client=None`,
    `upload_results=False` and an outer `tracing_context(enabled="local")` alike -- without this,
    every example's run is still queued for a real POST to LangSmith (confirmed by tracing a real
    `aevaluate()` call: two runs were queued and, at process exit, a real "multipart ingest"
    request reached api.smith.langchain.com and failed with 401). A tracing sample rate of 0 makes
    `Client._filter_for_sampling` drop every run before it is ever queued, so nothing is sent.
    Must run before the first LangSmith `Client` of the process is built (`aevaluate`'s internal
    `client=None` resolves to a process-wide cached client whose sample rate is fixed at
    construction); `get_env_var`'s cache is cleared so a value read earlier in this process can't
    shadow it."""
    os.environ.setdefault("LANGSMITH_TRACING_SAMPLING_RATE", "0")
    from langsmith import utils as ls_utils

    ls_utils.get_env_var.cache_clear()  # type: ignore[attr-defined]  # lru_cache on an overload


def local_examples(examples: list[dict[str, Any]]) -> list[Example]:
    """One in-memory `Example` per dict (as built by a package's `case_examples`), all under
    `LOCAL_DATASET_ID`, for an `aevaluate()` run that never talks to LangSmith."""
    return [
        Example(
            id=uuid.uuid4(),
            dataset_id=LOCAL_DATASET_ID,
            inputs=e.get("inputs") or {},
            outputs=e.get("outputs") or {},
            metadata=e.get("metadata") or {},
        )
        for e in examples
    ]


def _scores(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in (row.get("evaluation_results") or {}).get("results") or []:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return scores


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    """The mean score per key; a None score (the check did not apply) is left out."""
    return {key: sum(v) / len(v) for key, v in _scores(rows).items()}


def scored_counts(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """(passed, scored) per key; a score of 1 passes."""
    return {key: (sum(1 for s in v if s >= 1.0), len(v)) for key, v in _scores(rows).items()}


def errored(rows: list[dict[str, Any]]) -> int:
    """Examples whose target raised: LangSmith keeps the run with its error text."""
    return sum(1 for row in rows if getattr(row.get("run"), "error", None))


def render_pass_rates(
    rates: dict[str, float],
    counts: dict[str, tuple[int, int]],
    n: int,
    *,
    version: str | None,
) -> str:
    head = f"pass rate over {n} examples"
    if version is not None:
        head += f" (prompt version {version})"
    lines = [head + ":"]
    for key, rate in sorted(rates.items()):
        passed, scored = counts.get(key, (0, 0))
        lines.append(f"  {key:{KEY_WIDTH}} {rate:>4.0%} ({passed}/{scored})")
    return "\n".join(lines)


def _case(row: dict[str, Any]) -> str:
    example = row.get("example")
    metadata = getattr(example, "metadata", None) or {}
    return str(metadata.get("case") or getattr(example, "id", "?"))


def failure_lines(rows: list[dict[str, Any]]) -> list[str]:
    """One line per failed check (a score below 1): the key, the case and the evaluator's
    comment."""
    lines: list[str] = []
    for row in rows:
        for r in (row.get("evaluation_results") or {}).get("results") or []:
            if r.score is not None and float(r.score) < 1.0:
                comment = getattr(r, "comment", None) or "(no comment)"
                lines.append(f"  {r.key}  {_case(row)}: {comment}")
    return lines


def record_rows(
    rows: list[dict[str, Any]], experiment: str, *, directory: Path | None = None
) -> Path:
    """Writes `<experiment>.jsonl` under `directory` (default `$TRI_EVAL_DIR`, else `.evals`):
    one line per example with its case, inputs, outputs, error and evaluator results."""
    out_dir = directory or Path(os.environ.get("TRI_EVAL_DIR") or ".evals")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{experiment}.jsonl"
    with path.open("w") as fh:
        for row in rows:
            run, example = row.get("run"), row.get("example")
            results = (row.get("evaluation_results") or {}).get("results") or []
            line = {
                "case": _case(row),
                "inputs": getattr(example, "inputs", None),
                "outputs": getattr(run, "outputs", None),
                "error": getattr(run, "error", None),
                "results": [
                    {"key": r.key, "score": r.score, "comment": getattr(r, "comment", None)}
                    for r in results
                ],
            }
            fh.write(json.dumps(line, default=str) + "\n")
    return path
