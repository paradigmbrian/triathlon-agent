"""Test doubles and SQL seeds for the wellness package. Imported by tests only."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts
from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.labs.models import LabResult, PanelContext, RawResult
from tri_wellness.prompts.report import DISCLAIMER

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, and optional title,
    actual_duration_sec, actual_tss, completed (default True)."""
    out: list[WorkoutRow] = []
    for r in rows:
        out.append(
            WorkoutRow(
                tp_workout_id=r["tp_workout_id"],
                workout_date=r["workout_date"],
                sport=r["sport"],
                sport_raw=None,
                title=r.get("title", ""),
                description=None,
                completed=bool(r.get("completed", True)),
                planned_duration_sec=r.get("planned_duration_sec"),
                planned_distance_m=None,
                planned_tss=r.get("planned_tss"),
                planned_if=None,
                actual_duration_sec=r.get("actual_duration_sec"),
                actual_distance_m=None,
                actual_tss=r.get("actual_tss"),
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=None,
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        )
    upsert_workouts(conn, out)


def seed_daily_metrics(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with metric_date and any other DailyMetricsRow field."""
    upsert_daily_metrics(conn, [DailyMetricsRow(**r) for r in rows])


class NoCommit:
    """The rolled-back test connection; commit/close are no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def load_extracted(name: str) -> dict[str, Any]:
    """A recorded ExtractedPanel from tests/fixtures/extract/<name>.json."""
    with (FIXTURES / "extract" / f"{name}.json").open(encoding="utf-8") as fh:
        return dict(json.load(fh))


class RecordingScriptedModel(ScriptedChatModel):
    """ScriptedChatModel that also keeps every message list it was called with."""

    received: list[list[BaseMessage]] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received = [*self.received, list(messages)]
        return super()._generate(messages, stop, run_manager, **kwargs)


def seed_panel(
    conn: Conn,
    drawn_on: date,
    rows: list[tuple[str, float, str]],
    lab: str | None = "Quest",
    context: PanelContext | None = None,
) -> int:
    """One stored panel from (marker, value, unit) rows; the raw row is synthesized."""
    results = [
        LabResult(marker=m, value=v, unit=u, raw=RawResult(name=m, value=str(v), unit=u))
        for m, v, u in rows
    ]
    return repo.insert_panel(
        conn,
        drawn_on=drawn_on,
        lab_name=lab,
        source_file=None,
        source_kind="manual",
        context=context or PanelContext(fasting=True),
        raw_extract=[r.raw for r in results],
        results=results,
    )


# What the model writes (prompt v2: no disclaimer, no dosing). REPORT_OK is what gets stored.
REPORT_BODY = """\
## Draw conditions
Fasted, 07:30 draw. Active confounders: recent hard session (long ride, 210 TSS, the day \
before), which raises ferritin, hs-CRP and CK for 24-72 h; weight it heavily for those three.

## By system
### Iron
Ferritin shows 42 ng/mL against a functional range of 50-150 (conventional in range, 30-400). \
With hs-CRP mildly up, the pattern suggests true stores are lower still; the inflammation \
confounder applies to ferritin as well as the recent hard session.
### Inflammation
hs-CRP shows 1.8 mg/L against a functional high of 1 (conventional under 3). The recent hard \
session confounder applies.
### Thyroid
All optimal.
### CBC
All optimal.

## Priorities
1. Iron stores: ferritin 42 (functional 50-150) with a mild hs-CRP rise.
2. Recovery: the draw followed a 210 TSS ride; retest rested before acting on CK.

## Training implications
Hold intensity for two weeks; keep long rides under 3 h until ferritin is retested.

## Levers
Red meat or heme iron three times a week, paired with vitamin C; no coffee within an hour of \
iron-rich meals.

## Supplements
Iron bisglycinate, target ferritin above 50; a retest above 50 with hs-CRP under 1 shows it \
worked. Form and amount are for your practitioner to set.

## Retest plan
Ferritin, hs-CRP, CBC in 8 weeks, fasted, 48 h after the last hard session.

## Questions for your practitioner
1. Is a full iron panel with transferrin saturation warranted now?

## Changes since last panel
Ferritin 35 -> 42 (+20.0%) since 2031-01-15.
"""

REPORT_OK = f"{DISCLAIMER}\n\n{REPORT_BODY}"
