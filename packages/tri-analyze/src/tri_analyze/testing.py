"""Test doubles and SQL seeds for the analyst package. Imported by tests only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from tri_analyze.evals.seed import workout_row
from tri_analyze.repo import AthleteContext
from tri_core.db.models import DailyMetricsRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts
from tri_core.testing import ScriptedChatModel

TODAY = date(2026, 9, 6)


def athlete_context(**over: Any) -> AthleteContext:
    """The prompt fixture: FTP 230, LTHR 180, run threshold 4:30/km, CSS 1:44/100m, one day of
    metrics and one completed Z2 ride. Keyword overrides replace whole fields."""
    base: dict[str, Any] = {
        "today": TODAY,
        "profile": {
            "ftp_watts": 230,
            "lthr_bpm": 180,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 104,
            "max_hr_bpm": 182,
        },
        "recent_days": [
            {
                "metric_date": date(2026, 9, 5),
                "tss_day": 55,
                "ctl": 15.2,
                "atl": 19.6,
                "tsb": -7.3,
                "sleep_score": 79,
                "hrv_overnight_avg": 71,
                "training_readiness": 51,
            }
        ],
        "recent_workouts": [
            {
                "workout_date": date(2026, 9, 5),
                "sport": "bike",
                "title": "Z2 ride",
                "completed": True,
                "planned_tss": 60,
                "actual_tss": 55,
            }
        ],
    }
    base.update(over)
    return AthleteContext(**base)


class RecordingScriptedModel(ScriptedChatModel):
    """ScriptedChatModel that keeps every message list it received, for invoke and stream."""

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

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self.received = [*self.received, list(messages)]
        yield from super()._stream(messages, stop, run_manager, **kwargs)


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport and any other WorkoutRow field (the
    rest None; completed True)."""
    upsert_workouts(conn, [workout_row(r) for r in rows])


def seed_daily_metrics(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with metric_date and any other DailyMetricsRow field."""
    upsert_daily_metrics(conn, [DailyMetricsRow(**r) for r in rows])
