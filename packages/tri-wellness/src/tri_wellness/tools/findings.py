"""Chat tools over the lab tables: the schema doc for query_training_db and three findings
tools (get_panel_findings, get_marker_spec, get_marker_history)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from tri_wellness import repo
from tri_wellness.labs.evaluate import evaluate, functional_status
from tri_wellness.labs.training_context import load_training_context
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec
from tri_wellness.report import ConnectFactory

WELLNESS_SCHEMA_DOC = """\
lab_panels (wellness agent; one row per lab draw): id, drawn_on date, lab_name, source_kind
  ('pdf'|'export'|'manual'), context jsonb (fasting bool, draw_time, supplements [], diet_pattern,
  symptoms [], notes), raw_extract jsonb (every printed row, mapped or not), created_at.
lab_results (one row per mapped marker per panel): panel_id, marker text (canonical key such as
  ferritin, hs_crp, vitamin_d, testosterone_total; see get_marker_spec), value numeric in the
  canonical unit, unit, raw_name (what the lab printed), raw_value, lab_ref_low, lab_ref_high,
  flag (the lab's H/L).
lab_reports: id, panel_id, ranges_version, findings jsonb (list of Finding: marker, value,
  functional_status, functional_range, previous, delta_pct, active_confounders), report_md,
  created_at. Several reports per panel are possible; the newest id is current.

Examples:
  -- every ferritin value, oldest first
  select p.drawn_on, r.value, r.unit from lab_results r join lab_panels p on p.id = r.panel_id
  where r.marker = 'ferritin' order by 1;
  -- load and sleep in the week before a draw
  select metric_date, tss_day, ctl, atl, sleep_seconds, hrv_overnight_avg from daily_metrics
  where metric_date between date '2026-08-13' and date '2026-08-20' order by 1;
  -- sessions in the 72 h before a draw
  select workout_date, sport, title, actual_duration_sec, actual_tss from workouts
  where completed and workout_date between date '2026-08-17' and date '2026-08-19' order by 1;
"""

_FINDING_EXCLUDE = {"athlete_note"}


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _resolve(registry: MarkerRegistry, marker: str) -> MarkerSpec | None:
    if marker in registry.markers:
        return registry.get(marker)
    return registry.lookup(marker)


def make_findings_tools(connect: ConnectFactory, registry: MarkerRegistry) -> list[BaseTool]:
    @tool("get_panel_findings")
    def get_panel_findings(panel: str = "latest") -> str:
        """Evaluate one stored lab panel against the functional ranges and return JSON.

        `panel` is a panel id or "latest". The answer has: panel (id, drawn_on, lab_name,
        context: fasting, draw_time, supplements, symptoms, notes), training (CTL, ATL, TSB,
        sessions and sleep/HRV around the draw), ranges_version, and findings: one per marker
        with value, unit, conventional_status, functional_status, functional_range, previous
        (date, value), delta_pct and active_confounders. Call this before answering anything
        about a panel's results; do not read lab_results directly for interpretation.
        """
        with connect() as conn:
            if panel == "latest":
                pid = repo.latest_panel_id(conn)
                if pid is None:
                    return _dump({"error": "no panels stored"})
            else:
                try:
                    pid = int(panel)
                except ValueError:
                    return _dump({"error": f"panel must be an id or 'latest', got {panel!r}"})
            stored = repo.get_panel(conn, pid)
            if stored is None:
                return _dump({"error": f"no panel {pid}"})
            results = repo.lab_results_for_panel(conn, pid)
            previous = repo.previous_values(conn, pid)
            training = load_training_context(conn, stored.drawn_on)
        findings = evaluate(results, registry, previous, stored.context, training)
        return _dump(
            {
                "panel": {
                    "id": stored.id,
                    "drawn_on": stored.drawn_on.isoformat(),
                    "lab_name": stored.lab_name,
                    "context": stored.context.model_dump(mode="json"),
                },
                "training": training.model_dump(mode="json"),
                "ranges_version": registry.version,
                "findings": [f.model_dump(mode="json", exclude=_FINDING_EXCLUDE) for f in findings],
            }
        )

    @tool("get_marker_spec")
    def get_marker_spec(marker: str) -> str:
        """The curated range-table entry for one marker, by canonical key or any printed alias
        (for example "ferritin" or "Ferritin, Serum"): display, system, unit, conventional and
        functional ranges resolved for this athlete's sex, direction, athlete_note, confounders
        and sources. JSON. Use it to explain why a marker is flagged and what the note says.
        """
        spec = _resolve(registry, marker)
        if spec is None:
            return _dump({"error": f"unknown marker {marker!r}"})
        return _dump({"sex": registry.sex, **spec.model_dump(mode="json")})

    @tool("get_marker_history")
    def get_marker_history(marker: str) -> str:
        """Every stored value of one marker (key or alias), oldest first: panel_id, drawn_on,
        value, functional_status, with the marker's unit and functional_range. JSON. Use it for
        trend questions instead of writing SQL.
        """
        spec = _resolve(registry, marker)
        if spec is None:
            return _dump({"error": f"unknown marker {marker!r}"})
        with connect() as conn:
            rows = repo.marker_history(conn, spec.key)
        return _dump(
            {
                "marker": spec.key,
                "unit": spec.unit,
                "functional_range": [spec.functional.low, spec.functional.high],
                "history": [
                    {
                        "panel_id": pid,
                        "drawn_on": drawn.isoformat(),
                        "value": value,
                        "functional_status": functional_status(value, spec),
                    }
                    for pid, drawn, value, _unit in rows
                ],
            }
        )

    return [get_panel_findings, get_marker_spec, get_marker_history]
