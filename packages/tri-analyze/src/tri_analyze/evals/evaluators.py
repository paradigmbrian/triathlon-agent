"""Evaluators over one analyst answer: three code checks over the tool calls and the answer
(SQL for data questions, splits for interval questions, a stated window for trends) and, in
make_judge, an LLM judge for grounding and feedback quality. A check that does not apply to a
case scores None, which the pass rate leaves out."""

from __future__ import annotations

import re
from typing import Any

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
WINDOW_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date
    re.compile(  # month and day, either order: "Sep 13", "September 13th", "13 September"
        rf"\b{_MONTH}\.? {_DAY}\b|\b{_DAY} {_MONTH}\b", re.IGNORECASE
    ),
    re.compile(  # relative window: "last 8 weeks", "past two months", "previous 30 days"
        r"\b(?:last|past|previous) (?:\d+|two|three|four|five|six|seven|eight|nine|ten|twelve)"
        r" (?:days?|weeks?|months?)\b",
        re.IGNORECASE,
    ),
)


def _names(outputs: dict[str, Any]) -> list[str]:
    return [str(c["name"]) for c in outputs.get("calls") or []]


def uses_sql(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("requires_sql"):
        return {"key": "uses_sql", "score": None, "comment": "SQL not required"}
    n = _names(outputs).count("query_training_db")
    return {"key": "uses_sql", "score": int(n > 0), "comment": f"{n} query_training_db call(s)"}


def pulls_splits(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not (reference_outputs.get("requires_splits") and inputs.get("live")):
        return {
            "key": "pulls_splits",
            "score": None,
            "comment": "splits not required, or no live tools bound",
        }
    n = _names(outputs).count("get_activity_splits")
    return {
        "key": "pulls_splits",
        "score": int(n > 0),
        "comment": f"{n} get_activity_splits call(s)",
    }


def states_window(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("expects_window"):
        return {"key": "states_window", "score": None, "comment": "no window expected"}
    answer = str(outputs.get("answer") or "")
    hit: str | None = None
    for pattern in WINDOW_PATTERNS:
        match = pattern.search(answer)
        if match:
            hit = match.group(0)
            break
    return {
        "key": "states_window",
        "score": int(hit is not None),
        "comment": f"window: {hit}" if hit else "no date or relative window in the answer",
    }
