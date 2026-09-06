"""TrainingPeaks: parse MCP tool payloads into rows, and fetch a date window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tri_analyze.db.models import AthleteProfileRow, DailyMetricsRow, WorkoutRow
from tri_analyze.sync import ToolCaller
from tri_analyze.sync.dates import date_chunks
from tri_analyze.sync.sports import normalize_tp_sport

TP_MAX_RANGE_DAYS = 90

# TP zone groups are keyed by workoutTypeId: 1 swim, 2 bike, 3 run (0 = default).
_SWIM, _BIKE, _RUN = 1, 2, 3


@dataclass
class TPSnapshot:
    profile: AthleteProfileRow | None
    workouts: list[WorkoutRow] = field(default_factory=list)
    fitness: list[DailyMetricsRow] = field(default_factory=list)


# ---------- pure parsers ----------


def _hours_to_sec(h: Any) -> int | None:
    return int(round(float(h) * 3600)) if h is not None else None


def _km_to_m(km: Any) -> float | None:
    return float(km) * 1000 if km is not None else None


def _int(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


def _float(v: Any) -> float | None:
    return float(v) if v is not None else None


def parse_workout_detail(payload: dict[str, Any]) -> WorkoutRow:
    m = payload.get("metrics") or {}
    # TP returns completed=null even for finished workouts; an actual duration is the tell.
    completed = bool(payload.get("completed")) or m.get("duration_actual") is not None
    return WorkoutRow(
        tp_workout_id=str(payload["id"]),
        workout_date=date.fromisoformat(str(payload["date"])[:10]),
        sport=normalize_tp_sport(payload.get("sport")),
        sport_raw=payload.get("sport"),
        title=payload.get("title"),
        description=payload.get("description"),
        completed=completed,
        planned_duration_sec=_hours_to_sec(m.get("duration_planned")),
        planned_distance_m=_km_to_m(m.get("distance_planned_km")),
        planned_tss=_float(m.get("tss_planned")),
        planned_if=_float(m.get("if_planned")),
        actual_duration_sec=_hours_to_sec(m.get("duration_actual")),
        actual_distance_m=_km_to_m(m.get("distance_actual_km")),
        actual_tss=_float(m.get("tss_actual")),
        actual_if=_float(m.get("if_actual")),
        normalized_power=_int(m.get("normalized_power")),
        avg_power=_int(m.get("avg_power")),
        avg_hr=_int(m.get("avg_hr")),
        avg_cadence=_float(m.get("avg_cadence")),
        elevation_gain_m=_float(m.get("elevation_gain")),
        calories=_int(m.get("calories")),
        feeling=_int(payload.get("feeling")),
        rpe=_int(payload.get("rpe")),
        comments=payload.get("workout_comments"),
        structure=payload.get("structured_workout"),
        raw=payload,
    )


def parse_fitness(payload: dict[str, Any]) -> list[DailyMetricsRow]:
    rows: list[DailyMetricsRow] = []
    for d in payload.get("daily_data") or []:
        if not d.get("date"):
            continue
        rows.append(
            DailyMetricsRow(
                metric_date=date.fromisoformat(d["date"]),
                ctl=_float(d.get("ctl")),
                atl=_float(d.get("atl")),
                tsb=_float(d.get("tsb")),
                tss_day=_float(d.get("tss")),
                tp_raw=d,
            )
        )
    return rows


def _zone_groups(settings: dict[str, Any], key: str) -> list[dict[str, Any]]:
    groups = settings.get(key)
    return [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else []


def _group_for(groups: list[dict[str, Any]], wtid: int) -> dict[str, Any] | None:
    for g in groups:
        if g.get("workoutTypeId") == wtid:
            return g
    return None


def _pace_from_speed(mps: Any, metres: float) -> int | None:
    try:
        v = float(mps)
    except (TypeError, ValueError):
        return None
    return int(round(metres / v)) if v > 0 else None


def parse_athlete_settings(payload: dict[str, Any]) -> AthleteProfileRow:
    s = payload.get("settings") or {}
    power = _zone_groups(s, "powerZones")
    hr = _zone_groups(s, "heartRateZones")
    speed = _zone_groups(s, "speedZones")
    bike_power = _group_for(power, _BIKE) or (power[0] if power else None)
    run_hr = _group_for(hr, _RUN) or _group_for(hr, _BIKE) or (hr[0] if hr else None)
    run_speed = _group_for(speed, _RUN)
    swim_speed = _group_for(speed, _SWIM)
    athlete_id = s.get("athleteId")
    return AthleteProfileRow(
        tp_athlete_id=str(athlete_id) if athlete_id is not None else None,
        ftp_watts=_int(bike_power.get("threshold")) if bike_power else None,
        run_threshold_pace_sec_per_km=(
            _pace_from_speed(run_speed.get("threshold"), 1000) if run_speed else None
        ),
        swim_css_sec_per_100m=(
            _pace_from_speed(swim_speed.get("threshold"), 100) if swim_speed else None
        ),
        lthr_bpm=_int(run_hr.get("threshold")) if run_hr else None,
        max_hr_bpm=_int(run_hr.get("maximumHeartRate")) if run_hr else None,
        hr_zones=hr or None,
        power_zones=power or None,
        pace_zones=speed or None,
        weight_kg=_float(s.get("weight")),
        raw=s,
    )


# ---------- fetch ----------


async def fetch_trainingpeaks(
    client: ToolCaller,
    start: date,
    end: date,
    log: Callable[[str], None] = print,
) -> TPSnapshot:
    settings_payload = await client.call_json("tp_get_athlete_settings", {})
    profile = (
        parse_athlete_settings(settings_payload) if isinstance(settings_payload, dict) else None
    )
    log("trainingpeaks: athlete settings fetched")

    ids: dict[str, None] = {}
    fitness: list[DailyMetricsRow] = []
    for s, e in date_chunks(start, end, TP_MAX_RANGE_DAYS):
        listed = await client.call_json(
            "tp_get_workouts",
            {"start_date": s.isoformat(), "end_date": e.isoformat(), "workout_filter": "all"},
        )
        for w in (listed or {}).get("workouts", []):
            ids.setdefault(str(w["id"]), None)
        fit = await client.call_json(
            "tp_get_fitness", {"start_date": s.isoformat(), "end_date": e.isoformat()}
        )
        if isinstance(fit, dict):
            fitness.extend(parse_fitness(fit))
        log(f"trainingpeaks: {s} to {e}: {len(ids)} workouts so far, {len(fitness)} fitness days")

    workouts: list[WorkoutRow] = []
    for i, wid in enumerate(ids, 1):
        detail = await client.call_json("tp_get_workout", {"workout_id": wid})
        if isinstance(detail, dict):
            workouts.append(parse_workout_detail(detail))
        if i % 25 == 0:
            log(f"trainingpeaks: {i}/{len(ids)} workout details")
    log(f"trainingpeaks: {len(workouts)} workouts parsed")
    return TPSnapshot(profile=profile, workouts=workouts, fitness=fitness)
