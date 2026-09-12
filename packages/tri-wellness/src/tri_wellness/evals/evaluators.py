"""Code evaluators over a report: every non-optimal marker cites its functional range, the fixed
structure is present, and active confounders are named. No model."""

from __future__ import annotations

import re
from typing import Any

from tri_wellness.labs.models import Finding
from tri_wellness.prompts.report import (
    CHANGES_TITLE,
    DISCLAIMER,
    SECTION_TITLES,
    format_range,
)


def _result(key: str, ok: bool, problems: list[str]) -> dict[str, Any]:
    return {"key": key, "score": int(ok), "comment": "; ".join(problems) or "ok"}


def _findings(outputs: dict[str, Any]) -> list[Finding]:
    return [Finding.model_validate(f) for f in outputs.get("findings", [])]


def _g(v: float) -> str:
    return f"{v:g}"


def _mentions_bound(report: str, v: float) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(_g(v))}(?![\d.])", report) is not None


def cites_functional_ranges(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "")
    problems: list[str] = []
    for f in _findings(outputs):
        if f.functional_status == "optimal":
            continue
        low, high = f.functional_range
        named = f.display.lower() in report.lower() or f.marker in report
        bounds_ok = all(_mentions_bound(report, v) for v in (low, high) if v is not None)
        if not (named and bounds_ok):
            problems.append(
                f"{f.display}: functional range {format_range(*f.functional_range)} not cited"
            )
    return _result("cites_functional_ranges", not problems, problems)


def has_required_sections(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "")
    problems: list[str] = []
    first = next((ln.strip() for ln in report.splitlines() if ln.strip()), "")
    if first != DISCLAIMER:
        problems.append("first line is not the disclaimer")
    headings = [m.group(1).strip() for m in re.finditer(r"^##[ \t]+(.+?)[ \t]*$", report, re.M)]
    positions = {h.lower(): i for i, h in enumerate(headings)}
    last = -1
    for title in SECTION_TITLES:
        i = positions.get(title.lower())
        if i is None:
            problems.append(f"missing section '{title}'")
        elif i < last:
            problems.append(f"section '{title}' out of order")
        else:
            last = i
    has_previous = bool(inputs.get("previous"))
    has_changes = CHANGES_TITLE.lower() in positions
    if has_previous and not has_changes:
        problems.append(f"missing section '{CHANGES_TITLE}'")
    if has_changes and not has_previous:
        problems.append(f"'{CHANGES_TITLE}' present but there is no previous panel")
    return _result("has_required_sections", not problems, problems)


def names_active_confounders(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "").lower()
    problems: list[str] = []
    seen: set[str] = set()
    for f in _findings(outputs):
        if f.functional_status == "optimal":
            continue
        for c in f.active_confounders:
            if c in seen:
                continue
            seen.add(c)
            if c not in report and c.replace("_", " ") not in report:
                problems.append(f"{c} applies to {f.display} but is not named")
    return _result("names_active_confounders", not problems, problems)
