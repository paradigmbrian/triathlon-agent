"""Chat system prompt, rendered once per session: profile, panels, the latest report's
priorities and retest plan, the tools, and the same rules the report follows."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_wellness.labs.models import PanelSummary, StoredReport
from tri_wellness.prompts.report import REPORT_RULES, profile_block
from tri_wellness.report import extract_section

TOOL_GUIDE = """\
Tools, in the order to reach for them:
- get_panel_findings(panel): the evaluated findings for a panel ("latest" or an id). Always
  call it before discussing a panel's results; it carries each marker's status, functional
  range, previous value and confounders.
- get_marker_spec(marker): the range-table entry, athlete note and sources for one marker.
- get_marker_history(marker): every stored value with its functional status, oldest first.
- query_training_db(sql): read-only SQL over workouts, daily_metrics, athlete_profile and the
  lab tables, for load, sleep and HRV around a draw or anything the tools above do not cover."""


def _panels_block(panels: list[PanelSummary]) -> str:
    if not panels:
        return "Panels: no panels stored yet (run `tri-wellness ingest <file>`)."
    lines = ["Panels, newest first:"]
    for p in panels:
        lines.append(
            f"- panel {p.id}: {p.drawn_on.isoformat()} {p.lab_name or '-'}, "
            f"{p.result_count} results, report {'yes' if p.has_report else 'no'}"
        )
    return "\n".join(lines)


def _report_block(report: StoredReport | None) -> str:
    if report is None:
        return "Latest report: no report yet (run `tri-wellness report`)."
    head = f"Latest report (panel {report.panel_id}, {report.created_at.date().isoformat()}):"
    parts = [head]
    for title in ("Priorities", "Retest plan"):
        body = extract_section(report.report_md, title)
        if body:
            parts.append(f"{title}:\n{body}")
    return "\n\n".join(parts)


def render_chat_prompt(
    profile: dict[str, Any] | None,
    sex: str,
    panels: list[PanelSummary],
    latest_report: StoredReport | None,
    today: date,
    tool_names: list[str],
) -> str:
    return "\n\n".join(
        [
            "You are a functional-medicine practitioner who works with one endurance athlete. "
            "You answer questions about the athlete's lab panels using the tools below. Python "
            "has already evaluated every marker against a curated range table; you explain "
            "patterns and answer follow-ups, you do not re-judge numbers from memory.",
            f"Today is {today.isoformat()}.",
            profile_block(profile, sex),
            _panels_block(panels),
            _report_block(latest_report),
            "Tools bound this session: " + ", ".join(tool_names) + ".",
            TOOL_GUIDE,
            REPORT_RULES,
        ]
    )
