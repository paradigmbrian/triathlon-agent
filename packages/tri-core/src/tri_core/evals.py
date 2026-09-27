"""Pass rates for every package's LangSmith eval, in one format: the rate and the scored count
per evaluator key, so "every example passed" can be read from the log without LangSmith."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

KEY_WIDTH = 26


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
