"""Test doubles and SQL seeds for the wellness package. Imported by tests only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts
from tri_core.testing import ScriptedChatModel

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
