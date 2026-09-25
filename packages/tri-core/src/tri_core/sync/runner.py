"""Sequence the sources, isolate failures, record watermarks."""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_core.config import Settings
from tri_core.db import repo
from tri_core.db.connection import connect
from tri_core.db.models import SyncState
from tri_core.mcp.client import McpToolClient
from tri_core.mcp.servers import ServerSpec, garmin_spec, trainingpeaks_spec
from tri_core.sync import ToolCaller
from tri_core.sync.garmin import fetch_garmin
from tri_core.sync.match import match_activities
from tri_core.sync.trainingpeaks import fetch_trainingpeaks

TP_FIRST_RUN_DAYS = 365
GARMIN_FIRST_RUN_DAYS = 60
OVERLAP_DAYS = 3

Log = Callable[[str], None]
Opener = Callable[[], AbstractAsyncContextManager[ToolCaller]]
SourceFn = Callable[[Any, Opener, date, date, Log], Awaitable[int]]


@dataclass
class SourceResult:
    source: str
    status: str
    rows: int = 0
    error: str | None = None


@dataclass
class SyncReport:
    results: list[SourceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.status == "ok" for r in self.results)


def resolve_window(
    state: SyncState | None,
    since: date | None,
    full: bool,
    today: date,
    first_run_days: int,
    overlap_days: int = OVERLAP_DAYS,
) -> tuple[date, date]:
    if since is not None:
        return since, today
    if full or state is None:
        return today - timedelta(days=first_run_days), today
    return state.last_synced_date - timedelta(days=overlap_days), today


def _default_opener(spec_fn: Callable[[Settings], ServerSpec], settings: Settings) -> Opener:
    @asynccontextmanager
    async def _open() -> AsyncIterator[ToolCaller]:
        async with McpToolClient(spec_fn(settings)) as client:
            yield client

    return _open


async def _sync_trainingpeaks(conn: Any, opener: Opener, start: date, end: date, log: Log) -> int:
    async with opener() as client:
        snap = await fetch_trainingpeaks(client, start, end, log=log)
    rows = 0
    if snap.profile is not None:
        repo.upsert_athlete_profile(conn, snap.profile)
        rows += 1
    rows += repo.upsert_workouts(conn, snap.workouts)
    rows += repo.upsert_daily_metrics(conn, snap.fitness)
    return rows


async def _sync_garmin(conn: Any, opener: Opener, start: date, end: date, log: Log) -> int:
    async with opener() as client:
        snap = await fetch_garmin(client, start, end, log=log)
    rows = repo.upsert_daily_metrics(conn, snap.daily)
    workouts = repo.list_workouts_between(conn, start, end)
    pairs = match_activities(workouts, snap.activities)
    for tp_id, act in pairs:
        repo.set_garmin_match(conn, tp_id, act.id, act.start_time_local)
    log(f"garmin: matched {len(pairs)} of {len(snap.activities)} activities to TP workouts")
    return rows + len(pairs)


async def run_sync(
    settings: Settings,
    *,
    since: date | None = None,
    sources: tuple[str, ...] = ("trainingpeaks", "garmin"),
    full: bool = False,
    log: Log = print,
    open_tp: Opener | None = None,
    open_garmin: Opener | None = None,
) -> SyncReport:
    today = date.today()
    open_tp = open_tp or _default_opener(trainingpeaks_spec, settings)
    open_garmin = open_garmin or _default_opener(garmin_spec, settings)
    plan: list[tuple[str, int, Opener, SourceFn]] = [
        ("trainingpeaks", TP_FIRST_RUN_DAYS, open_tp, _sync_trainingpeaks),
        ("garmin", GARMIN_FIRST_RUN_DAYS, open_garmin, _sync_garmin),
    ]
    report = SyncReport()
    with connect(settings.database_url) as conn:
        for source, first_run_days, opener, fn in plan:
            if source not in sources:
                continue
            state = repo.get_sync_state(conn, source)
            start, end = resolve_window(state, since, full, today, first_run_days)
            log(f"== {source}: {start} to {end}")
            try:
                rows = await fn(conn, opener, start, end, log)
                repo.set_sync_state(conn, source, end, "ok", None)
                conn.commit()
                report.results.append(SourceResult(source, "ok", rows))
                log(f"== {source}: ok, {rows} rows")
            except Exception as exc:  # per-source isolation is the point
                err = f"{type(exc).__name__}: {exc}"
                log(f"== {source}: ERROR {err}\n{traceback.format_exc()}")
                last = state.last_synced_date if state else start
                try:
                    conn.rollback()
                    repo.set_sync_state(conn, source, last, "error", err[:2000])
                    conn.commit()
                except Exception as state_exc:  # a dead connection must not hide the source error
                    state_err = f"{type(state_exc).__name__}: {state_exc}"
                    log(f"== {source}: could not record the error state: {state_err}")
                    err = f"{err}; sync_state not updated: {state_err}"
                report.results.append(SourceResult(source, "error", 0, err))
    return report
