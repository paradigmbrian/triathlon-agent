"""Chat tools over the lab tables: the schema doc for query_training_db and three findings
tools (get_panel_findings, get_marker_spec, get_marker_history)."""

from __future__ import annotations

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
