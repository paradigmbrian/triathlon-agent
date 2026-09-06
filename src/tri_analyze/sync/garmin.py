"""Garmin: parse MCP tool payloads into rows, and fetch a date window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from typing import Any

from tri_analyze.db.models import DailyMetricsRow
from tri_analyze.sync import ToolCaller
from tri_analyze.sync.dates import date_chunks
from tri_analyze.sync.sports import normalize_garmin_sport

SLEEP_MAX_NIGHTS = 90
ACTIVITY_PAGE_SIZE = 200


@dataclass
class GarminActivity:
    id: str
    type_key: str | None
    sport: str
    start_time_local: datetime
    duration_sec: float | None
    distance_m: float | None
    avg_hr: int | None
    name: str | None
    raw: dict[str, Any]


@dataclass
class GarminSnapshot:
    daily: list[DailyMetricsRow] = field(default_factory=list)
    activities: list[GarminActivity] = field(default_factory=list)


# ---------- pure parsers ----------


def _int(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


def _float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _date(v: Any) -> date:
    return date.fromisoformat(str(v)[:10])


def parse_sleep_range(payload: dict[str, Any]) -> dict[date, DailyMetricsRow]:
    nights: list[dict[str, Any]] = []
    for v in payload.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "date" in v[0]:
            nights = v
            break
    out: dict[date, DailyMetricsRow] = {}
    for n in nights:
        d = _date(n["date"])
        out[d] = DailyMetricsRow(
            metric_date=d,
            sleep_seconds=_int(n.get("sleep_seconds")),
            sleep_score=_int(n.get("sleep_score")),
            hrv_overnight_avg=_int(n.get("avg_overnight_hrv")),
            resting_hr=_int(n.get("resting_heart_rate_bpm")),
            garmin_raw={"sleep": n},
        )
    return out


def parse_stats(payload: dict[str, Any]) -> DailyMetricsRow:
    return DailyMetricsRow(
        metric_date=_date(payload["date"]),
        resting_hr=_int(payload.get("resting_heart_rate_bpm")),
        body_battery_high=_int(payload.get("body_battery_highest")),
        body_battery_low=_int(payload.get("body_battery_lowest")),
        stress_avg=_int(payload.get("avg_stress_level")),
        garmin_raw={"stats": payload},
    )


def parse_readiness(payload: Any) -> tuple[date, int] | None:
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = [payload]
    else:
        entries = []
    scored = [
        e for e in entries if isinstance(e, dict) and e.get("score") is not None and e.get("date")
    ]
    if not scored:
        return None
    best = max(scored, key=lambda e: float(e["score"]))
    return _date(best["date"]), int(round(float(best["score"])))


def parse_activity_list(payload: dict[str, Any]) -> list[GarminActivity]:
    out: list[GarminActivity] = []
    for a in payload.get("activities") or []:
        if a.get("id") is None or not a.get("start_time"):
            continue
        out.append(
            GarminActivity(
                id=str(a["id"]),
                type_key=a.get("type"),
                sport=normalize_garmin_sport(a.get("type")),
                start_time_local=datetime.fromisoformat(str(a["start_time"]).replace(" ", "T")),
                duration_sec=_float(a.get("duration_seconds")),
                distance_m=_float(a.get("distance_meters")),
                avg_hr=_int(a.get("avg_hr_bpm")),
                name=a.get("name"),
                raw=a,
            )
        )
    return out


def merge_daily(*parts: dict[date, DailyMetricsRow]) -> list[DailyMetricsRow]:
    """Combine per-source rows for the same day. Later parts win for non-None fields."""
    merged: dict[date, DailyMetricsRow] = {}
    for part in parts:
        for d, row in part.items():
            cur = merged.get(d)
            if cur is None:
                cur = DailyMetricsRow(**{f.name: getattr(row, f.name) for f in fields(row)})
                cur.garmin_raw = dict(row.garmin_raw or {})
                merged[d] = cur
                continue
            for f in fields(row):
                if f.name in ("metric_date", "garmin_raw"):
                    continue
                v = getattr(row, f.name)
                if v is not None:
                    setattr(cur, f.name, v)
            cur.garmin_raw = {**(cur.garmin_raw or {}), **(row.garmin_raw or {})}
    return [merged[d] for d in sorted(merged)]


# ---------- fetch ----------


async def fetch_garmin(
    client: ToolCaller,
    start: date,
    end: date,
    log: Callable[[str], None] = print,
) -> GarminSnapshot:
    sleep: dict[date, DailyMetricsRow] = {}
    for s, e in date_chunks(start, end, SLEEP_MAX_NIGHTS - 1):
        payload = await client.call_json(
            "get_sleep_summary_range", {"start_date": s.isoformat(), "end_date": e.isoformat()}
        )
        if isinstance(payload, dict):
            sleep.update(parse_sleep_range(payload))
    log(f"garmin: {len(sleep)} nights of sleep")

    stats: dict[date, DailyMetricsRow] = {}
    readiness: dict[date, DailyMetricsRow] = {}
    day = start
    n_days = (end - start).days + 1
    while day <= end:
        ds = day.isoformat()
        st = await client.call_json("get_stats", {"date": ds})
        if isinstance(st, dict) and st.get("date"):
            stats[day] = parse_stats(st)
        rd = await client.call_json("get_training_readiness", {"date": ds})
        parsed = parse_readiness(rd)
        if parsed:
            readiness[day] = DailyMetricsRow(
                metric_date=day, training_readiness=parsed[1], garmin_raw={"readiness": rd}
            )
        if (day - start).days % 10 == 9:
            log(f"garmin: {(day - start).days + 1}/{n_days} days of stats/readiness")
        day += timedelta(days=1)
    daily = merge_daily(sleep, stats, readiness)
    log(f"garmin: {len(daily)} daily rows")

    activities: list[GarminActivity] = []
    page = 0
    while True:
        payload = await client.call_json(
            "get_activities_by_date",
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "page": page,
                "page_size": ACTIVITY_PAGE_SIZE,
            },
        )
        if not isinstance(payload, dict):
            break
        activities.extend(parse_activity_list(payload))
        if not payload.get("has_more"):
            break
        page = int(payload.get("next_page", page + 1))
    log(f"garmin: {len(activities)} activities")
    return GarminSnapshot(daily=daily, activities=activities)
