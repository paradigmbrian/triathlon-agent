# Progress Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the `/progress` placeholder with a PMC chart, ramp rates, weekly volume by sport, longest workout and sport share, all computed from data already synced.

**Architecture:** One `GET /api/progress?range=` endpoint in `tri-web` runs a pure `compute_progress` over `workouts` and `daily_metrics` rows and returns a `ProgressView`. The React page draws it with hand-rolled SVG and HTML components that share a `ChartFrame` (summary text, "view as table" toggle) and a keyboard `Scrubber`. The range lives in the `?range=` URL param.

**Tech Stack:** FastAPI + Pydantic + psycopg (Python 3.12, pytest, ruff, mypy strict); React 19, TanStack Query, react-router 7, Tailwind v4, vitest, Playwright. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-29-progress-page-design.md`

## Global Constraints

- No chart library and no new npm or Python dependency.
- Ranges are exactly `6w`, `6m`, `12m`, `all`; default `12m`; an invalid value is a 422.
- Weeks start on Monday (`week_monday` from `tri_planning.planning.targets`).
- Missing values stay `null` end to end: no interpolation, no zero-filling of gaps in the PMC.
- Deleted workouts are excluded (the repo's `list_workouts_between` already does this).
- The server sends metric units (metres, seconds); the UI shows miles, feet, hours and kcal, matching the TrainingPeaks dashboard Brian uses. Assumption from the screenshots; change `web/src/components/progress/units.ts` only if that is wrong.
- Sport is never shown by colour alone: the legend and readouts carry sport names, the legend also carries a marker shape.
- WCAG 2.2 AA: text summary and "view as table" on every chart, keyboard access without mouse, targets at least 24px, `prefers-reduced-motion` honoured, no text below 12px (`tests/styles.test.ts` enforces this).
- The 3-day stale threshold for `as_of` is fixed in `STALE_DAYS`.
- No `tri-* eval` runs and no `pytest --live` in this plan; nothing here spends Anthropic credit.
- Before editing code that uses a dependency, check current docs with Context7 (Brian's standing rule); Tasks 2 and 3 name the lookups.
- Definition of Done, in order: full tests, lint and type checks, production build (Task 8).
- Any markdown created is copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

## Review Focus

- A brand-new athlete with no workouts or metrics: every chart says "No data in this range", nothing throws or shows `NaN` (Tasks 1, 4, 5, 6).
- CTL missing for the whole range but workouts present: PMC shows empty state, weekly charts still draw (Tasks 1, 4).
- The current week is partial: it must be labelled, and it must not drag the average line down (Tasks 1, 5).
- One week of data (a `1` element series): scrubber hidden, no divide-by-zero in scales, bar still drawn (Tasks 3, 5).
- A sport the app doesn't know ("brick", "walk", anything): folds into "Other", never crashes or vanishes from totals (Tasks 3, 5, 6).
- A range switch mid-load or a failed request: previous range's data is never shown under the new label; error state has a working retry (Task 7).
- Very long history (`all`, 150+ weeks): no per-bar tab stops; the scrubber is the only stop (Task 5).

## File Structure

Backend (`packages/`):
- Modify `tri-core/src/tri_core/db/repo.py`: add `list_daily_metrics_between`.
- Create `tri-web/src/tri_web/progress.py`: models, `range_floor`, `metrics_floor`, `compute_progress`, `build_progress`.
- Create `tri-web/src/tri_web/routes/progress.py`: the route.
- Modify `tri-web/src/tri_web/app.py`: register the router.
- Create `tri-web/tests/test_progress.py` (pure) and `tri-web/tests/test_routes_progress.py` (db).

Frontend (`web/`):
- Regenerate `openapi.json`, `src/api/types.ts`; modify `src/api/queries.ts`.
- Modify `src/index.css`: sport tokens.
- Create `src/components/progress/`: `units.ts`, `sports.tsx`, `scale.ts`, `ChartFrame.tsx`, `Scrubber.tsx`, `RangePicker.tsx`, `Pmc.tsx`, `RampRates.tsx`, `StackedBars.tsx`, `WeeklyBars.tsx`, `LongestWorkout.tsx`, `ShareBars.tsx`.
- Create `src/pages/Progress.tsx`; modify `src/router.tsx`, `src/pages/Placeholder.tsx`, `tests/shell.test.tsx` (the Progress route now renders the real page).
- Tests: `tests/progressFixtures.ts`, `tests/scale.test.ts`, `tests/progressFrame.test.tsx`, `tests/pmc.test.tsx`, `tests/weekly.test.tsx`, `tests/share.test.tsx`, `tests/progressPage.test.tsx`, `tests/e2e/progress.spec.ts`; extend `tests/styles.test.ts`.

---

### Task 1: Progress aggregation (pure)

**Files:**
- Create: `packages/tri-web/src/tri_web/progress.py`
- Test: `packages/tri-web/tests/test_progress.py`

**Interfaces:**
- Consumes: `tri_planning.planning.targets.week_monday(d: date) -> date`; `tri_web.metrics.ramp(now: float | None, then: float | None) -> float | None`.
- Produces (used by Tasks 2 and 3): `RangeKey = Literal["6w","6m","12m","all"]`, `range_floor(range_, today) -> date`, `metrics_floor(range_, today) -> date`, `compute_progress(range_, today, workouts, metrics) -> ProgressView`, `STALE_DAYS = 3`, and the models `SportTotals`, `PmcPoint`, `RampOut`, `LongestOut`, `WeekOut`, `ShareTotals`, `ShareOut`, `ProgressView`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-web/tests/test_progress.py`:

```python
"""compute_progress: weeks, the PMC, ramp windows, range clipping and sport sums, over plain dict
rows (no database)."""

from datetime import date, timedelta
from decimal import Decimal

from tri_web.progress import compute_progress, metrics_floor, range_floor

TODAY = date(2026, 9, 16)  # a Wednesday


def w(day: date, sport: str = "run", *, completed: bool = True, **cols):
    return {"workout_date": day, "sport": sport, "completed": completed, **cols}


def m(day: date, ctl=None, atl=None, tsb=None, tss_day=None):
    return {"metric_date": day, "ctl": ctl, "atl": atl, "tsb": tsb, "tss_day": tss_day}


def test_weeks_split_on_monday_and_the_current_week_is_partial():
    rows = [
        w(date(2026, 9, 13), actual_duration_sec=3600),  # Sunday
        w(date(2026, 9, 14), actual_duration_sec=1800),  # Monday
    ]
    out = compute_progress("6w", TODAY, rows, [])
    by_start = {x.week_start: x for x in out.weeks}
    assert by_start[date(2026, 9, 7)].by_sport["run"].duration_sec == 3600
    assert by_start[date(2026, 9, 14)].by_sport["run"].duration_sec == 1800
    assert [x.partial for x in out.weeks] == [False] * 6 + [True]


def test_range_starts_on_a_monday_and_clips_older_rows():
    assert range_floor("6w", TODAY) == date(2026, 8, 3)
    assert metrics_floor("6w", TODAY) == TODAY - timedelta(days=365)
    rows = [w(date(2026, 8, 2), actual_duration_sec=999), w(date(2026, 8, 3), actual_duration_sec=60)]
    out = compute_progress("6w", TODAY, rows, [])
    assert out.start == date(2026, 8, 3)
    assert out.weeks[0].week_start == date(2026, 8, 3)
    assert out.weeks[0].by_sport["run"].duration_sec == 60
    assert out.share.completed.duration_sec == {"run": 60}


def test_all_starts_at_the_earliest_data_monday():
    out = compute_progress("all", TODAY, [w(date(2025, 3, 5), actual_tss=40)], [m(date(2025, 6, 1), ctl=10)])
    assert out.start == date(2025, 3, 3)
    assert len(out.pmc) == (TODAY - date(2025, 3, 3)).days + 1


def test_pmc_keeps_a_gap_as_null_and_never_interpolates():
    out = compute_progress(
        "6w", TODAY, [], [m(date(2026, 9, 14), ctl=40, atl=44, tsb=-4, tss_day=60), m(date(2026, 9, 16), ctl=Decimal("41.5"), atl=45, tsb=-3.5)]
    )
    by = {p.date: p for p in out.pmc}
    assert by[date(2026, 9, 15)].ctl is None and by[date(2026, 9, 15)].tsb is None
    assert by[date(2026, 9, 16)].ctl == 41.5
    assert out.as_of == date(2026, 9, 16)
    assert len(out.pmc) == 45  # 2026-08-03 through today


def test_ramp_windows_and_a_missing_start_gives_no_delta():
    metrics = [m(date(2026, 9, 16), ctl=40.0), m(date(2026, 9, 9), ctl=38.5)]
    out = compute_progress("6w", TODAY, [], metrics)
    r = {x.days: x for x in out.ramp}
    assert r[7].delta == 1.5 and len(r[7].series) == 8 and r[7].series[0] == 38.5 and r[7].series[-1] == 40.0
    assert r[28].delta is None and len(r[28].series) == 29
    assert sorted(r) == [7, 28, 90, 365]


def test_ramp_reaches_past_the_range_for_the_long_windows():
    metrics = [m(date(2026, 9, 16), ctl=40.0), m(TODAY - timedelta(days=90), ctl=30.0)]
    out = compute_progress("6w", TODAY, [], metrics)
    assert {x.days: x.delta for x in out.ramp}[90] == 10.0


def test_sums_treat_null_columns_as_zero_and_null_never_wins_longest():
    rows = [
        w(date(2026, 9, 14), "bike", actual_duration_sec=3600, actual_distance_m=None, elevation_gain_m=None, calories=None, actual_tss=None),
        w(date(2026, 9, 15), "bike", actual_duration_sec=None, actual_distance_m=5000, elevation_gain_m=120, calories=300, actual_tss=50),
    ]
    week = compute_progress("6w", TODAY, rows, []).weeks[-1]
    bike = week.by_sport["bike"]
    assert (bike.duration_sec, bike.distance_m, bike.elevation_m, bike.calories, bike.tss) == (3600, 5000, 120, 300, 50)
    assert week.longest.duration_sec == 3600 and week.longest.distance_m == 5000


def test_a_week_with_no_workouts_is_zeroed_not_missing():
    week = compute_progress("6w", TODAY, [], []).weeks[0]
    assert week.by_sport == {} and week.longest.duration_sec == 0 and week.longest.distance_m == 0


def test_share_uses_actuals_for_completed_and_planned_columns_for_everything():
    rows = [
        w(date(2026, 9, 14), "swim", actual_duration_sec=1800, actual_distance_m=1500, planned_duration_sec=2400, planned_distance_m=2000),
        w(date(2026, 9, 15), "run", completed=False, planned_duration_sec=3600, planned_distance_m=10000, actual_duration_sec=77),
    ]
    share = compute_progress("6w", TODAY, rows, []).share
    assert share.completed.duration_sec == {"swim": 1800}
    assert share.completed.distance_m == {"swim": 1500}
    assert share.planned.duration_sec == {"swim": 2400, "run": 3600}
    assert share.planned.distance_m == {"swim": 2000, "run": 10000}


def test_rows_after_today_are_ignored():
    out = compute_progress("6w", TODAY, [w(date(2026, 9, 20), actual_duration_sec=60)], [m(date(2026, 9, 20), ctl=99)])
    assert out.as_of is None and out.weeks[-1].by_sport == {}


def test_an_empty_store_is_all_empty_and_never_raises():
    out = compute_progress("12m", TODAY, [], [])
    assert out.as_of is None
    assert all(p.ctl is None for p in out.pmc)
    assert all(x.delta is None for x in out.ramp)
    assert out.share.completed.duration_sec == {} and out.share.planned.distance_m == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_progress.py -v`
Expected: FAIL at import (`No module named 'tri_web.progress'`).

- [ ] **Step 3: Implement `progress.py`**

Create `packages/tri-web/src/tri_web/progress.py`:

```python
"""The Progress page in one call: the PMC, ramp rates, weekly totals by sport and sport share.
compute_progress is pure over row dicts; build_progress fetches them."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from tri_core.db import repo as crepo
from tri_planning.planning.targets import week_monday
from tri_web.metrics import ramp
from tri_web.runtime import Runtime

RangeKey = Literal["6w", "6m", "12m", "all"]
RANGE_DAYS: dict[str, int] = {"6w": 42, "6m": 182, "12m": 365}
RAMP_WINDOWS = (7, 28, 90, 365)
EARLIEST = date(2000, 1, 1)
STALE_DAYS = 3  # the page flags a curve older than this


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _n(v: Any) -> float:
    return 0.0 if v is None else float(v)


class SportTotals(BaseModel):
    duration_sec: float = 0
    distance_m: float = 0
    elevation_m: float = 0
    calories: float = 0
    tss: float = 0


class PmcPoint(BaseModel):
    date: date
    ctl: float | None
    atl: float | None
    tsb: float | None
    tss: float | None


class RampOut(BaseModel):
    days: int
    delta: float | None
    series: list[float | None]  # CTL over the window, oldest first, days + 1 long, None for a gap


class LongestOut(BaseModel):
    duration_sec: float = 0
    distance_m: float = 0


class WeekOut(BaseModel):
    week_start: date
    partial: bool
    by_sport: dict[str, SportTotals]
    longest: LongestOut


class ShareTotals(BaseModel):
    duration_sec: dict[str, float] = Field(default_factory=dict)
    distance_m: dict[str, float] = Field(default_factory=dict)


class ShareOut(BaseModel):
    completed: ShareTotals
    planned: ShareTotals


class ProgressView(BaseModel):
    range: RangeKey
    start: date
    end: date
    as_of: date | None  # the latest day with a CTL reading
    pmc: list[PmcPoint]
    ramp: list[RampOut]
    weeks: list[WeekOut]
    share: ShareOut


def range_floor(range_: RangeKey, today: date) -> date:
    """First day fetched for workouts: a Monday, so the first week is a whole week."""
    if range_ == "all":
        return EARLIEST
    return week_monday(today - timedelta(days=RANGE_DAYS[range_]))


def metrics_floor(range_: RangeKey, today: date) -> date:
    """Metrics reach back at least as far as the longest ramp window."""
    return min(range_floor(range_, today), today - timedelta(days=max(RAMP_WINDOWS)))


def _ramp_out(by_day: dict[date, dict[str, Any]], as_of: date | None, days: int) -> RampOut:
    if as_of is None:
        return RampOut(days=days, delta=None, series=[])
    series = [
        _f(by_day[d].get("ctl")) if (d := as_of - timedelta(days=days - i)) in by_day else None
        for i in range(days + 1)
    ]
    return RampOut(days=days, delta=ramp(series[-1], series[0]), series=series)


def compute_progress(
    range_: RangeKey, today: date, workouts: list[dict[str, Any]], metrics: list[dict[str, Any]]
) -> ProgressView:
    by_day = {r["metric_date"]: r for r in metrics if r["metric_date"] <= today}
    floor = range_floor(range_, today)
    live = [w for w in workouts if floor <= w["workout_date"] <= today]
    if range_ == "all":
        earliest = min([w["workout_date"] for w in live] + list(by_day), default=today)
        start = week_monday(earliest)
    else:
        start = floor

    pmc: list[PmcPoint] = []
    for i in range((today - start).days + 1):
        d = start + timedelta(days=i)
        r = by_day.get(d, {})
        pmc.append(
            PmcPoint(
                date=d,
                ctl=_f(r.get("ctl")),
                atl=_f(r.get("atl")),
                tsb=_f(r.get("tsb")),
                tss=_f(r.get("tss_day")),
            )
        )
    as_of = max((d for d, r in by_day.items() if r.get("ctl") is not None), default=None)

    this_week = week_monday(today)
    totals: dict[date, dict[str, SportTotals]] = defaultdict(dict)
    longest: dict[date, LongestOut] = defaultdict(LongestOut)
    completed = ShareTotals()
    planned = ShareTotals()
    for row in live:
        sport = row["sport"]
        if row.get("completed"):
            monday = week_monday(row["workout_date"])
            t = totals[monday].setdefault(sport, SportTotals())
            t.duration_sec += _n(row.get("actual_duration_sec"))
            t.distance_m += _n(row.get("actual_distance_m"))
            t.elevation_m += _n(row.get("elevation_gain_m"))
            t.calories += _n(row.get("calories"))
            t.tss += _n(row.get("actual_tss"))
            lg = longest[monday]
            lg.duration_sec = max(lg.duration_sec, _n(row.get("actual_duration_sec")))
            lg.distance_m = max(lg.distance_m, _n(row.get("actual_distance_m")))
            for bucket, col in ((completed.duration_sec, "actual_duration_sec"), (completed.distance_m, "actual_distance_m")):
                if row.get(col) is not None:
                    bucket[sport] = bucket.get(sport, 0.0) + float(row[col])
        for bucket, col in ((planned.duration_sec, "planned_duration_sec"), (planned.distance_m, "planned_distance_m")):
            if row.get(col) is not None:
                bucket[sport] = bucket.get(sport, 0.0) + float(row[col])

    weeks = [
        WeekOut(
            week_start=monday,
            partial=monday == this_week,
            by_sport=totals.get(monday, {}),
            longest=longest.get(monday, LongestOut()),
        )
        for monday in (start + timedelta(days=7 * i) for i in range((this_week - start).days // 7 + 1))
    ]
    return ProgressView(
        range=range_,
        start=start,
        end=today,
        as_of=as_of,
        pmc=pmc,
        ramp=[_ramp_out(by_day, as_of, days) for days in RAMP_WINDOWS],
        weeks=weeks,
        share=ShareOut(completed=completed, planned=planned),
    )


async def build_progress(rt: Runtime, range_: RangeKey) -> ProgressView:
    today = rt.today()
    with rt.connect() as conn:
        workouts = crepo.list_workouts_between(conn, range_floor(range_, today), today)
        metrics = crepo.list_daily_metrics_between(conn, metrics_floor(range_, today), today)
    return compute_progress(range_, today, workouts, metrics)
```

Note: `build_progress` calls `crepo.list_daily_metrics_between`, added in Task 2. Until then only the pure tests run.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_progress.py -v`
Expected: PASS (10 tests). If `test_all_starts_at_the_earliest_data_monday` fails, check that the `all` branch takes the earliest of workout and metric dates.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check packages/tri-web && uv run ruff format --check packages/tri-web && uv run mypy`
Expected: clean. Fix line-length findings by wrapping (ruff's limit is 100); run `uv run ruff format packages/tri-web` if only formatting fails.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-web/src/tri_web/progress.py packages/tri-web/tests/test_progress.py
git commit -m "feat(web): compute_progress for the Progress page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Repo query, route and generated types

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/repo.py` (after `list_workouts_between`, about line 249)
- Modify: `packages/tri-web/src/tri_web/app.py:15` and `:46`
- Create: `packages/tri-web/src/tri_web/routes/progress.py`
- Test: `packages/tri-web/tests/test_routes_progress.py`
- Regenerate: `web/openapi.json`, `web/src/api/types.ts`

**Interfaces:**
- Consumes: `build_progress(rt: Runtime, range_: RangeKey) -> ProgressView`, `RangeKey`, `ProgressView` (Task 1).
- Produces: `crepo.list_daily_metrics_between(conn, start: date, end: date) -> list[dict[str, Any]]`; HTTP `GET /api/progress?range=` returning `ProgressView`; the TS type `components["schemas"]["ProgressView"]` (Task 3).

- [ ] **Step 1: Look up current docs**

Use Context7 for FastAPI: `Query` with `alias` and a `Literal` parameter (how an invalid value becomes a 422). Confirm the signature used in Step 4 before writing it.

- [ ] **Step 2: Write the failing route tests**

Create `packages/tri-web/tests/test_routes_progress.py`:

```python
"""GET /api/progress over the rolled-back test database."""

from datetime import date

import pytest

pytestmark = pytest.mark.db

TODAY = date(2026, 9, 16)


def workout(conn, wid, day, sport, *, completed=True, deleted=False, **cols):
    base = {"actual_duration_sec": None, "actual_distance_m": None, "actual_tss": None,
            "elevation_gain_m": None, "calories": None, "planned_duration_sec": None}
    base.update(cols)
    conn.execute(
        "insert into workouts (tp_workout_id, workout_date, sport, completed, actual_duration_sec, "
        "actual_distance_m, actual_tss, elevation_gain_m, calories, planned_duration_sec, raw, deleted_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', %s)",
        (wid, day, sport, completed, base["actual_duration_sec"], base["actual_distance_m"],
         base["actual_tss"], base["elevation_gain_m"], base["calories"], base["planned_duration_sec"],
         "2026-09-10T00:00:00Z" if deleted else None),
    )


async def test_default_range_returns_the_view(runtime, client, nocommit):
    workout(nocommit, "w1", date(2026, 9, 14), "bike", actual_duration_sec=3600, actual_distance_m=30000)
    nocommit.execute(
        "insert into daily_metrics (metric_date, ctl, atl, tsb) values (%s, 40, 44, -4)", (TODAY,)
    )
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress")
    assert r.status_code == 200
    body = r.json()
    assert body["range"] == "12m" and body["end"] == "2026-09-16"
    assert body["as_of"] == "2026-09-16"
    assert body["weeks"][-1]["partial"] is True
    assert body["weeks"][-1]["by_sport"]["bike"]["duration_sec"] == 3600
    assert body["pmc"][-1] == {"date": "2026-09-16", "ctl": 40.0, "atl": 44.0, "tsb": -4.0, "tss": None}


@pytest.mark.parametrize("value", ["6w", "6m", "12m", "all"])
async def test_every_range_is_accepted(runtime, client, value):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress", params={"range": value})
    assert r.status_code == 200 and r.json()["range"] == value


async def test_an_invalid_range_is_a_422(runtime, client):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress", params={"range": "3d"})
    assert r.status_code == 422


async def test_deleted_workouts_and_old_rows_are_left_out(runtime, client, nocommit):
    workout(nocommit, "gone", date(2026, 9, 15), "run", deleted=True, actual_duration_sec=999)
    workout(nocommit, "old", date(2025, 1, 6), "run", actual_duration_sec=888)
    async with client(runtime(today=TODAY)) as c:
        six = (await c.get("/api/progress", params={"range": "6w"})).json()
        everything = (await c.get("/api/progress", params={"range": "all"})).json()
    assert six["share"]["completed"]["duration_sec"] == {}
    assert everything["share"]["completed"]["duration_sec"] == {"run": 888.0}


async def test_an_empty_database_still_answers(runtime, client):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress")
    body = r.json()
    assert r.status_code == 200 and body["as_of"] is None
    assert all(p["ctl"] is None for p in body["pmc"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_routes_progress.py -v`
Expected: FAIL (404 on `/api/progress`) or SKIP if Postgres is not reachable. If skipped, start the test database per `README.md` and rerun; do not proceed on a skip.

- [ ] **Step 4: Implement the repo query, route and registration**

Add to `packages/tri-core/src/tri_core/db/repo.py`, directly after `list_workouts_between`:

```python
def list_daily_metrics_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select * from daily_metrics where metric_date between %s and %s order by metric_date",
        (start, end),
    ).fetchall()
```

Create `packages/tri-web/src/tri_web/routes/progress.py`:

```python
"""GET /api/progress: the Progress page's charts in one call."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from tri_web.progress import ProgressView, RangeKey, build_progress

router = APIRouter()


@router.get("/progress", response_model=ProgressView)
async def get_progress(request: Request, range_: RangeKey = Query("12m", alias="range")) -> ProgressView:
    from tri_web.app import runtime_of

    return await build_progress(runtime_of(request), range_)
```

In `packages/tri-web/src/tri_web/app.py`, change the routes import to `from tri_web.routes import coach, jobs, memory, progress, system, today` and add after the `today` router line: `app.include_router(progress.router, prefix="/api", tags=["progress"])`.

- [ ] **Step 5: Run tests, lint and types**

Run: `uv run pytest packages/tri-web/tests/test_routes_progress.py packages/tri-web/tests/test_progress.py -v && uv run ruff check packages && uv run ruff format --check packages && uv run mypy`
Expected: PASS and clean. If `test_default_range_returns_the_view` fails on the `pmc[-1]` shape, print `r.json()["pmc"][-1]` and fix the test's expectation only if the server value is right (numeric columns arrive as floats).

- [ ] **Step 6: Regenerate the OpenAPI types**

Run: `cd web && npm run types`
Expected: `web/openapi.json` and `web/src/api/types.ts` change; `grep -c "ProgressView" src/api/types.ts` is at least 1.

- [ ] **Step 7: Commit**

```bash
git add packages web/openapi.json web/src/api/types.ts
git commit -m "feat(web): GET /api/progress

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Frontend foundations (query, tokens, helpers, frame, picker, scrubber)

**Files:**
- Modify: `web/src/api/queries.ts`, `web/src/index.css`
- Create: `web/src/components/progress/{units.ts,sports.tsx,scale.ts,ChartFrame.tsx,Scrubber.tsx,RangePicker.tsx}`
- Test: `web/tests/progressFixtures.ts`, `web/tests/scale.test.ts`, `web/tests/progressFrame.test.tsx`; extend `web/tests/styles.test.ts`

**Interfaces:**
- Consumes: `components["schemas"]["ProgressView"]` (Task 2).
- Produces (used by Tasks 4 to 7):
  - `queries.ts`: `type ProgressView`, `type ProgressRange = "6w"|"6m"|"12m"|"all"`, `useProgress(range: ProgressRange)`.
  - `units.ts`: `type Metric`, `METRICS: Record<Metric, {label; unit; digits; of(t: SportTotals): number}>`, `miles(m)`, `hoursOf(sec)`, `signed(v: number | null, digits = 1): string`.
  - `sports.tsx`: `SPORTS`, `type Sport`, `sportKey(s: string): Sport`, `SPORT_LABEL`, `sportColor(s: Sport): string`, `fold<T>(rec: Record<string, T>, add: (a: T, b: T) => T): Partial<Record<Sport, T>>`, `<Marker sport size?/>`, `<Legend sports/>`.
  - `scale.ts`: `scaleLinear`, `niceMax`, `ticks`, `segments`, `axisDate`, `axisLabels`.
  - `ChartFrame({title, summary, table:{head: string[]; rows: (string|number)[][]}, controls?, children})`, `Scrubber({label, count, index, valueText, onChange})`, `RangePicker({value, onChange})`.
  - Test fixture: `progressFull(): ProgressView`, `progressEmpty(): ProgressView`.

- [ ] **Step 1: Look up current docs**

Use Context7 for `react-router` v7: `useSearchParams` (read and set a param without a full navigation). Use Context7 for TanStack Query v5: `keepPreviousData` is not used here (see Review Focus: previous range's data must not show under a new label), so confirm a changed `queryKey` gives `data === undefined` while loading.

- [ ] **Step 2: Write the failing tests**

Create `web/tests/progressFixtures.ts`:

```ts
import type { ProgressView } from "../src/api/queries";

const totals = (o: Partial<{ duration_sec: number; distance_m: number; elevation_m: number; calories: number; tss: number }> = {}) => ({
  duration_sec: 0, distance_m: 0, elevation_m: 0, calories: 0, tss: 0, ...o,
});

/** Three weeks (the last partial), five PMC days with a gap, two sports plus one the UI does not know. */
export function progressFull(): ProgressView {
  return {
    range: "12m",
    start: "2026-08-31",
    end: "2026-09-16",
    as_of: "2026-09-16",
    pmc: [
      { date: "2026-09-12", ctl: 38, atl: 42, tsb: -4, tss: 60 },
      { date: "2026-09-13", ctl: 38.5, atl: 43, tsb: -4.5, tss: 0 },
      { date: "2026-09-14", ctl: null, atl: null, tsb: null, tss: null },
      { date: "2026-09-15", ctl: 39.5, atl: 44, tsb: -4.5, tss: 80 },
      { date: "2026-09-16", ctl: 40, atl: 45, tsb: -5, tss: 50 },
    ],
    ramp: [
      { days: 7, delta: 1.5, series: [38.5, null, 39, 39.5, 39.8, 39.9, 40, 40] },
      { days: 28, delta: null, series: [] },
      { days: 90, delta: -4, series: [44, 43, 40] },
      { days: 365, delta: -41, series: [81, 60, 40] },
    ],
    weeks: [
      { week_start: "2026-08-31", partial: false, by_sport: { bike: totals({ duration_sec: 7200, distance_m: 48280, elevation_m: 300, calories: 1200, tss: 90 }), run: totals({ duration_sec: 3600, distance_m: 10000, elevation_m: 50, calories: 700, tss: 60 }) }, longest: { duration_sec: 7200, distance_m: 48280 } },
      { week_start: "2026-09-07", partial: false, by_sport: { bike: totals({ duration_sec: 3600, distance_m: 24140, elevation_m: 100, calories: 600, tss: 45 }), brick: totals({ duration_sec: 1800, distance_m: 5000, elevation_m: 10, calories: 300, tss: 30 }) }, longest: { duration_sec: 3600, distance_m: 24140 } },
      { week_start: "2026-09-14", partial: true, by_sport: { run: totals({ duration_sec: 1800, distance_m: 5000, elevation_m: 20, calories: 350, tss: 30 }) }, longest: { duration_sec: 1800, distance_m: 5000 } },
    ],
    share: {
      completed: { duration_sec: { bike: 10800, run: 5400, brick: 1800 }, distance_m: { bike: 72420, run: 15000 } },
      planned: { duration_sec: { bike: 12000, run: 7200 }, distance_m: { bike: 80000, run: 20000 } },
    },
  };
}

export function progressEmpty(): ProgressView {
  return {
    range: "12m", start: "2026-08-31", end: "2026-09-16", as_of: null,
    pmc: [{ date: "2026-09-16", ctl: null, atl: null, tsb: null, tss: null }],
    ramp: [7, 28, 90, 365].map((days) => ({ days, delta: null, series: [] })),
    weeks: [{ week_start: "2026-09-14", partial: true, by_sport: {}, longest: { duration_sec: 0, distance_m: 0 } }],
    share: { completed: { duration_sec: {}, distance_m: {} }, planned: { duration_sec: {}, distance_m: {} } },
  };
}
```

Create `web/tests/scale.test.ts`:

```ts
import { axisLabels, niceMax, scaleLinear, segments, ticks } from "../src/components/progress/scale";
import { METRICS, signed } from "../src/components/progress/units";
import { fold, sportKey } from "../src/components/progress/sports";

test("scaleLinear maps the domain to the range and survives a flat domain", () => {
  const s = scaleLinear(0, 10, 100, 0);
  expect([s(0), s(5), s(10)]).toEqual([100, 50, 0]);
  expect(Number.isFinite(scaleLinear(5, 5, 0, 10)(5))).toBe(true);
});

test("niceMax rounds up to 1, 2, 5 or 10 times a power of ten and never returns 0", () => {
  expect([niceMax(0), niceMax(0.3), niceMax(7), niceMax(43), niceMax(101)]).toEqual([1, 0.5, 10, 50, 200]);
  expect(ticks(43)).toEqual([0, 12.5, 25, 37.5, 50]);
});

test("segments breaks the line at a gap and draws a lone point as a dot", () => {
  const out = segments([1, 2, null, 3, null, 4, 5], (i) => i * 10, (v) => v);
  expect(out).toEqual(["M0,1 L10,2", "M30,3 L30,3", "M50,4 L60,5"]);
  expect(segments([null, null], (i) => i, (v) => v)).toEqual([]);
});

test("axisLabels picks evenly spaced dates, one for a single date, none for none", () => {
  expect(axisLabels(["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"], 3).map((l) => l.i)).toEqual([0, 2, 4]);
  expect(axisLabels(["2026-01-05"], 5).map((l) => l.i)).toEqual([0]);
  expect(axisLabels([], 5)).toEqual([]);
});

test("metrics convert to miles, feet and hours; signed shows a plus and a real minus", () => {
  const t = { duration_sec: 7200, distance_m: 1609.344, elevation_m: 100, calories: 500, tss: 0 };
  expect(METRICS.distance.of(t)).toBeCloseTo(1);
  expect(METRICS.duration.of(t)).toBe(2);
  expect(METRICS.elevation.of(t)).toBeCloseTo(328.084);
  expect(signed(1.5)).toBe("+1.5");
  expect(signed(-4)).toBe("−4.0");
  expect(signed(0)).toBe("0.0");
  expect(signed(null)).toBe("–");
});

test("unknown sports fold into other and their totals add", () => {
  expect(sportKey("brick")).toBe("other");
  expect(sportKey("bike")).toBe("bike");
  expect(fold({ bike: 1, brick: 2, walk: 4 }, (a, b) => a + b)).toEqual({ bike: 1, other: 6 });
});
```

Create `web/tests/progressFrame.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChartFrame from "../src/components/progress/ChartFrame";
import RangePicker from "../src/components/progress/RangePicker";
import Scrubber from "../src/components/progress/Scrubber";

test("ChartFrame shows the summary and swaps the chart for a table on toggle", async () => {
  const user = userEvent.setup();
  render(
    <ChartFrame title="Weekly volume" summary="Average 4 mi per week." table={{ head: ["Week", "mi"], rows: [["Sep 7", 4]] }}>
      <svg data-testid="chart" />
    </ChartFrame>,
  );
  expect(screen.getByRole("heading", { name: "Weekly volume" })).toBeInTheDocument();
  expect(screen.getByText("Average 4 mi per week.")).toBeInTheDocument();
  expect(screen.getByTestId("chart")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "View as table" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await user.click(toggle);
  expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Weekly volume" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Sep 7" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "View as chart" })).toHaveAttribute("aria-pressed", "true");
});

test("RangePicker marks the current range and reports a change", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<RangePicker value="12m" onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();
  await user.click(screen.getByRole("radio", { name: "6 weeks" }));
  expect(onChange).toHaveBeenCalledWith("6w");
});

test("Scrubber steps with the arrow keys and is hidden for fewer than two points", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const { rerender } = render(<Scrubber label="Inspect week" count={3} index={0} valueText="Sep 7" onChange={onChange} />);
  const slider = screen.getByRole("slider", { name: "Inspect week" });
  expect(slider).toHaveAttribute("aria-valuetext", "Sep 7");
  slider.focus();
  await user.keyboard("{ArrowRight}");
  expect(onChange).toHaveBeenCalledWith(1);
  rerender(<Scrubber label="Inspect week" count={1} index={0} valueText="" onChange={onChange} />);
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});
```

Extend `web/tests/styles.test.ts` (append; it already reads `css` and `files`):

```ts
const luminance = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const token = (block: string, name: string) => new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6});`).exec(block)![1];

test("sport colours reach 3:1 against the surface in both themes", () => {
  const dark = css.slice(0, css.indexOf("@media (prefers-color-scheme: light)"));
  const light = css.slice(css.indexOf("@media (prefers-color-scheme: light)"), css.indexOf("@theme"));
  for (const block of [dark, light]) {
    const surface = token(block, "--surface");
    for (const s of ["swim", "bike", "run", "strength", "other"]) {
      expect(contrast(token(block, `--sport-${s}`), surface)).toBeGreaterThanOrEqual(3);
    }
  }
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/scale.test.ts tests/progressFrame.test.tsx tests/styles.test.ts`
Expected: FAIL (modules and tokens not found).

- [ ] **Step 4: Add tokens and the query**

In `web/src/index.css`, add to the dark `:root` block (after `--on-fill`):

```css
  --sport-swim: #4fb3d9;
  --sport-bike: #b08cf0;
  --sport-run: #f0a15c;
  --sport-strength: #e0709f;
  --sport-other: #95a0ae;
```

Add to the light `:root` block (after `--on-fill: #ffffff;`):

```css
    --sport-swim: #0b6f94;
    --sport-bike: #6b41c2;
    --sport-run: #a3520f;
    --sport-strength: #b02a66;
    --sport-other: #555e6b;
```

Add to the `@theme inline` block:

```css
  --color-sport-swim: var(--sport-swim);
  --color-sport-bike: var(--sport-bike);
  --color-sport-run: var(--sport-run);
  --color-sport-strength: var(--sport-strength);
  --color-sport-other: var(--sport-other);
```

In `web/src/api/queries.ts`, add after the `ConditionOut` type line:

```ts
export type ProgressView = S["ProgressView"];
export type ProgressRange = "6w" | "6m" | "12m" | "all";
```

and after the `useStatus` line:

```ts
export const useProgress = (range: ProgressRange) =>
  useQuery({ queryKey: ["progress", range], queryFn: () => api<ProgressView>(`/api/progress?range=${range}`) });
```

- [ ] **Step 5: Implement the helpers**

Create `web/src/components/progress/units.ts`:

```ts
import type { ProgressView } from "../../api/queries";

export type SportTotals = ProgressView["weeks"][number]["by_sport"][string];
export type Metric = "distance" | "duration" | "elevation" | "calories";

export const miles = (m: number) => m / 1609.344;
export const hoursOf = (sec: number) => sec / 3600;

export const METRICS: Record<Metric, { label: string; unit: string; digits: number; of: (t: SportTotals) => number }> = {
  distance: { label: "Distance", unit: "mi", digits: 1, of: (t) => miles(t.distance_m) },
  duration: { label: "Duration", unit: "h", digits: 1, of: (t) => hoursOf(t.duration_sec) },
  elevation: { label: "Elevation", unit: "ft", digits: 0, of: (t) => t.elevation_m * 3.28084 },
  calories: { label: "Calories", unit: "kcal", digits: 0, of: (t) => t.calories },
};

/** A signed figure for a change: "+1.5", "−4.0" (a real minus), "0.0", or a dash for no data. */
export function signed(v: number | null, digits = 1): string {
  if (v == null) return "–";
  const x = Number(v.toFixed(digits));
  if (x === 0) return (0).toFixed(digits);
  return `${x > 0 ? "+" : "−"}${Math.abs(x).toFixed(digits)}`;
}
```

Create `web/src/components/progress/sports.tsx`:

```tsx
export const SPORTS = ["swim", "bike", "run", "strength", "other"] as const;
export type Sport = (typeof SPORTS)[number];

export const SPORT_LABEL: Record<Sport, string> = { swim: "Swim", bike: "Bike", run: "Run", strength: "Strength", other: "Other" };

export const sportKey = (s: string): Sport => ((SPORTS as readonly string[]).includes(s) ? (s as Sport) : "other");
export const sportColor = (s: Sport) => `var(--sport-${s})`;

/** Merge a record keyed by any sport label into the five the UI draws; unknown labels add into "other". */
export function fold<T>(rec: Record<string, T>, add: (a: T, b: T) => T): Partial<Record<Sport, T>> {
  const out: Partial<Record<Sport, T>> = {};
  for (const [k, v] of Object.entries(rec)) {
    const s = sportKey(k);
    out[s] = out[s] === undefined ? v : add(out[s] as T, v);
  }
  return out;
}

/** A shape per sport (circle, square, triangle, diamond, ring) so the legend never relies on colour alone. */
export function Marker({ sport, size = 12 }: { sport: Sport; size?: number }) {
  const c = sportColor(sport);
  const h = size / 2;
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {sport === "swim" && <circle cx={h} cy={h} r={h - 1} fill={c} />}
      {sport === "bike" && <rect x={1} y={1} width={size - 2} height={size - 2} fill={c} />}
      {sport === "run" && <polygon points={`${h},1 ${size - 1},${size - 1} 1,${size - 1}`} fill={c} />}
      {sport === "strength" && <polygon points={`${h},1 ${size - 1},${h} ${h},${size - 1} 1,${h}`} fill={c} />}
      {sport === "other" && <circle cx={h} cy={h} r={h - 1.5} fill="none" stroke={c} strokeWidth={2} />}
    </svg>
  );
}

export function Legend({ sports }: { sports: readonly Sport[] }) {
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {sports.map((s) => (
        <li key={s} className="inline-flex items-center gap-1.5">
          <Marker sport={s} />
          {SPORT_LABEL[s]}
        </li>
      ))}
    </ul>
  );
}
```

Create `web/src/components/progress/scale.ts`:

```ts
export function scaleLinear(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Round a maximum up to 1, 2, 5 or 10 times a power of ten; never 0. */
export function niceMax(max: number): number {
  if (!(max > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(max));
  const f = max / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** Five gridline values from 0 to niceMax(max). */
export function ticks(max: number): number[] {
  const m = niceMax(max);
  return [0, m / 4, m / 2, (3 * m) / 4, m];
}

/** SVG path strings for each unbroken run of values; a lone point becomes a zero-length line so a round cap draws a dot. */
export function segments(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string[] {
  const out: string[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length === 1) out.push(`M${run[0]} L${run[0]}`);
    else if (run.length > 1) out.push(`M${run.join(" L")}`);
    run = [];
  };
  values.forEach((v, i) => {
    if (v == null) flush();
    else run.push(`${x(i)},${y(v)}`);
  });
  flush();
  return out;
}

export function axisDate(iso: string, withYear = false): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, withYear ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" });
}

/** About `n` evenly spaced axis labels for a list of ISO dates: [{i, text}]. */
export function axisLabels(dates: string[], n: number): { i: number; text: string }[] {
  if (dates.length === 0) return [];
  const withYear = dates.length > 120;
  const at = dates.length === 1 ? [0] : Array.from({ length: n }, (_, k) => Math.round((k * (dates.length - 1)) / (n - 1)));
  return [...new Set(at)].map((i) => ({ i, text: axisDate(dates[i], withYear) }));
}
```

Create `web/src/components/progress/ChartFrame.tsx`:

```tsx
import { useId, useState, type ReactNode } from "react";

export type ChartTable = { head: string[]; rows: (string | number)[][] };

/** A titled card for one chart: a sentence that states the point, optional controls, the chart or its data table. */
export default function ChartFrame({ title, summary, table, controls, children }: {
  title: string;
  summary: string;
  table: ChartTable;
  controls?: ReactNode;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <section aria-labelledby={id} className="rounded-md border border-line bg-surface-2 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id={id} className="text-xs font-medium tracking-wider text-ink-2 uppercase">{title}</h2>
          <p className="mt-1 text-sm">{summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          <button
            type="button"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
            className="min-h-7 rounded-sm border border-line px-3 text-xs text-ink-2 hover:text-ink"
          >
            {asTable ? "View as chart" : "View as table"}
          </button>
        </div>
      </div>
      <div className="mt-3">
        {asTable ? (
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left text-xs tabular-nums">
              <caption className="sr-only">{title}</caption>
              <thead className="sticky top-0 bg-surface-2 text-ink-2">
                <tr>{table.head.map((h) => <th key={h} scope="col" className="py-1 pr-4 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    {r.map((c, j) => (j === 0 ? <th key={j} scope="row" className="py-1 pr-4 font-normal">{c}</th> : <td key={j} className="py-1 pr-4">{c}</td>))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
```

Create `web/src/components/progress/Scrubber.tsx`:

```tsx
/** A slider that steps through a chart's points with the arrow keys; the keyboard route to each value. */
export default function Scrubber({ label, count, index, valueText, onChange }: {
  label: string;
  count: number;
  index: number;
  valueText: string;
  onChange: (i: number) => void;
}) {
  if (count < 2) return null;
  return (
    <label className="mt-2 flex items-center gap-3 text-xs text-ink-2">
      <span className="shrink-0">{label}</span>
      <input
        type="range"
        min={0}
        max={count - 1}
        step={1}
        value={index}
        aria-valuetext={valueText}
        onChange={(e) => onChange(Number(e.target.value))}
        className="min-h-6 min-w-0 flex-1 accent-[var(--accent)]"
      />
    </label>
  );
}
```

Create `web/src/components/progress/RangePicker.tsx`:

```tsx
import type { ProgressRange } from "../../api/queries";

const OPTIONS: { value: ProgressRange; label: string }[] = [
  { value: "6w", label: "6 weeks" },
  { value: "6m", label: "6 months" },
  { value: "12m", label: "12 months" },
  { value: "all", label: "All" },
];

export default function RangePicker({ value, onChange }: { value: ProgressRange; onChange: (r: ProgressRange) => void }) {
  return (
    <div role="radiogroup" aria-label="Range" className="inline-flex rounded-sm border border-line">
      {OPTIONS.map((o) => (
        <label
          key={o.value}
          className={`inline-flex min-h-8 cursor-pointer items-center px-3 text-xs has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
            value === o.value ? "bg-hold text-on-fill" : "text-ink-2 hover:text-ink"
          }`}
        >
          <input type="radio" name="range" value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
          {o.label}
        </label>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/scale.test.ts tests/progressFrame.test.tsx tests/styles.test.ts`
Expected: PASS. If the `niceMax(0.3)` expectation fails: `0.3/0.1 = 3` gives 5 times `0.1` = 0.5, which is the expected value; check floating error (`10 ** -1`), and compare with `toBeCloseTo` in the test if needed. If the contrast test fails, darken or lighten the failing token until it reaches 3:1 and keep the hue.

- [ ] **Step 7: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): Progress foundations: query, sport tokens, chart frame, scrubber, range picker

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: PMC chart and ramp rates

**Files:**
- Create: `web/src/components/progress/Pmc.tsx`, `web/src/components/progress/RampRates.tsx`
- Test: `web/tests/pmc.test.tsx`

**Interfaces:**
- Consumes: `ProgressView`, `ChartFrame`, `Scrubber`, `scaleLinear`, `ticks`, `segments`, `axisLabels`, `signed` (Task 3); the existing `web/src/components/board/Sparkline.tsx` (`{values, low, high}`).
- Produces: `<Pmc pmc={ProgressView["pmc"]} ramp28={number | null} />`, `<RampRates ramp={ProgressView["ramp"]} />`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/pmc.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Pmc from "../src/components/progress/Pmc";
import RampRates from "../src/components/progress/RampRates";
import { progressEmpty, progressFull } from "./progressFixtures";

test("Pmc states the latest CTL and form and breaks the line at the gap", () => {
  const p = progressFull();
  const { container } = render(<Pmc pmc={p.pmc} ramp28={null} />);
  expect(screen.getByText(/CTL 40\.0/)).toBeInTheDocument();
  expect(screen.getByText(/form −5\.0/)).toBeInTheDocument();
  // 12, 13 | gap | 15, 16: two CTL runs
  expect(container.querySelectorAll("path[data-series='ctl']")).toHaveLength(2);
});

test("Pmc adds the 28-day change to the summary when known", () => {
  const p = progressFull();
  render(<Pmc pmc={p.pmc} ramp28={2.5} />);
  expect(screen.getByText(/\+2\.5 over 28 days/)).toBeInTheDocument();
});

test("the scrubber reads a day's values and a gap day says no reading", async () => {
  const user = userEvent.setup();
  render(<Pmc pmc={progressFull().pmc} ramp28={null} />);
  const slider = screen.getByRole("slider", { name: "Inspect day" });
  expect(slider).toHaveValue("4");
  expect(screen.getByTestId("pmc-readout")).toHaveTextContent("CTL 40.0 · ATL 45.0 · TSB −5.0");
  slider.focus();
  await user.keyboard("{ArrowLeft}{ArrowLeft}");
  expect(screen.getByTestId("pmc-readout")).toHaveTextContent("no reading");
});

test("Pmc with no CTL at all says so and draws no series", () => {
  const { container } = render(<Pmc pmc={progressEmpty().pmc} ramp28={null} />);
  expect(screen.getByText("No data in this range.")).toBeInTheDocument();
  expect(container.querySelectorAll("path[data-series]")).toHaveLength(0);
});

test("RampRates shows four signed tiles and a dash for a missing delta", () => {
  render(<RampRates ramp={progressFull().ramp} />);
  const tiles = screen.getAllByRole("group");
  expect(tiles).toHaveLength(4);
  expect(tiles[0]).toHaveTextContent("+1.5");
  expect(tiles[0]).toHaveTextContent("Last 7 days");
  expect(tiles[1]).toHaveTextContent("–");
  expect(tiles[2]).toHaveTextContent("−4.0");
  expect(tiles[3]).toHaveTextContent("Last 365 days");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/pmc.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `Pmc.tsx`**

Two stacked panels share an x axis: CTL (area) with ATL (line) above, TSB (line) with a zero line and a shaded band below. This replaces the spec's "second axis" with a second panel, which reads more clearly and needs no dual scale. Task 8 updates the spec to say so.

Create `web/src/components/progress/Pmc.tsx`:

```tsx
import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import { axisDate, axisLabels, niceMax, scaleLinear, segments, ticks } from "./scale";
import { signed } from "./units";

const W = 800;
const LEFT = 40;
const RIGHT = 8;
const TOP_H = 170;
const GAP = 22;
const BOT_H = 70;
const H = TOP_H + GAP + BOT_H + 22;
const FORM_BAND: [number, number] = [-10, 5]; // the "neutral" TSB zone in metrics.py

type Point = ProgressView["pmc"][number];
const f1 = (v: number | null) => (v == null ? "–" : v.toFixed(1));

export default function Pmc({ pmc, ramp28 }: { pmc: Point[]; ramp28: number | null }) {
  const [picked, setPicked] = useState<number | null>(null);
  const known = pmc.filter((p) => p.ctl != null);
  const last = known.at(-1);
  const index = picked ?? pmc.length - 1;
  const at = pmc[index];
  const readout = at
    ? at.ctl == null
      ? `${axisDate(at.date)}: no reading`
      : `${axisDate(at.date)}: CTL ${f1(at.ctl)} · ATL ${f1(at.atl)} · TSB ${signed(at.tsb)}`
    : "";
  const summary = last
    ? `CTL ${f1(last.ctl)}${ramp28 != null ? `, ${signed(ramp28)} over 28 days` : ""}; form ${signed(last.tsb)}.`
    : "No data in this range.";
  const table = {
    head: ["Date", "CTL", "ATL", "TSB", "TSS"],
    rows: pmc.map((p) => [p.date, f1(p.ctl), f1(p.atl), p.tsb == null ? "–" : signed(p.tsb), f1(p.tss)]),
  };
  return (
    <ChartFrame title="Performance management" summary={summary} table={table}>
      {known.length === 0 ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <Chart pmc={pmc} index={index} onPick={setPicked} />
          <p data-testid="pmc-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect day" count={pmc.length} index={index} valueText={readout} onChange={setPicked} />
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
            <li><span aria-hidden="true" className="mr-1.5 inline-block h-2 w-4 rounded-sm bg-accent/40 align-middle" />CTL (fitness)</li>
            <li><span aria-hidden="true" className="mr-1.5 inline-block w-4 border-t-2 border-dashed border-nutrition align-middle" />ATL (fatigue)</li>
            <li><span aria-hidden="true" className="mr-1.5 inline-block w-4 border-t-2 border-ink align-middle" />TSB (form)</li>
          </ul>
        </>
      )}
    </ChartFrame>
  );
}

function Chart({ pmc, index, onPick }: { pmc: Point[]; index: number; onPick: (i: number) => void }) {
  const n = pmc.length;
  const x = (i: number) => (n > 1 ? LEFT + (i / (n - 1)) * (W - LEFT - RIGHT) : (LEFT + W - RIGHT) / 2);
  const ctl = pmc.map((p) => p.ctl);
  const atl = pmc.map((p) => p.atl);
  const tsb = pmc.map((p) => p.tsb);
  const top = niceMax(Math.max(...ctl.concat(atl).filter((v): v is number => v != null)));
  const yTop = scaleLinear(0, top, TOP_H, 0);
  const tsbVals = tsb.filter((v): v is number => v != null);
  const lo = Math.min(-15, ...tsbVals);
  const hi = Math.max(10, ...tsbVals);
  const yBot = (v: number) => TOP_H + GAP + scaleLinear(lo, hi, BOT_H, 0)(v);
  const ctlRuns = segments(ctl, x, yTop);
  const areas = ctlRuns.map((d) => {
    const pts = d.replace(/^M/, "").split(" L");
    const first = pts[0].split(",")[0];
    const lastX = pts[pts.length - 1].split(",")[0];
    return `${d} L${lastX},${TOP_H} L${first},${TOP_H} Z`;
  });
  const labels = axisLabels(pmc.map((p) => p.date), 5);
  return (
    <svg
      role="img"
      aria-label="Performance management chart: CTL, ATL and TSB by day. Use the day slider or the table for values."
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      onPointerMove={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - box.left) / box.width) * W;
        onPick(Math.max(0, Math.min(n - 1, Math.round(((px - LEFT) / (W - LEFT - RIGHT)) * (n - 1)))));
      }}
    >
      {ticks(top).map((t) => (
        <g key={t}>
          <line x1={LEFT} x2={W - RIGHT} y1={yTop(t)} y2={yTop(t)} stroke="var(--line)" strokeWidth={1} />
          <text x={LEFT - 6} y={yTop(t) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">{Math.round(t)}</text>
        </g>
      ))}
      {areas.map((d, i) => <path key={i} d={d} fill="var(--accent)" opacity={0.22} />)}
      {ctlRuns.map((d, i) => <path key={i} data-series="ctl" d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
      {segments(atl, x, yTop).map((d, i) => <path key={i} data-series="atl" d={d} fill="none" stroke="var(--nutrition)" strokeWidth={1.5} strokeDasharray="5 3" strokeLinecap="round" />)}
      <rect x={LEFT} width={W - LEFT - RIGHT} y={yBot(FORM_BAND[1])} height={yBot(FORM_BAND[0]) - yBot(FORM_BAND[1])} fill="var(--ink-2)" opacity={0.15} />
      <line x1={LEFT} x2={W - RIGHT} y1={yBot(0)} y2={yBot(0)} stroke="var(--ink-2)" strokeWidth={1} />
      <text x={LEFT - 6} y={yBot(0) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">0</text>
      {segments(tsb, x, yBot).map((d, i) => <path key={i} data-series="tsb" d={d} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />)}
      {labels.map((l) => (
        <text key={l.i} x={x(l.i)} y={H - 4} textAnchor="middle" fontSize={12} fill="var(--ink-2)">{l.text}</text>
      ))}
      <line x1={x(index)} x2={x(index)} y1={0} y2={TOP_H + GAP + BOT_H} stroke="var(--ink-2)" strokeWidth={1} />
    </svg>
  );
}
```

- [ ] **Step 4: Implement `RampRates.tsx`**

Create `web/src/components/progress/RampRates.tsx`:

```tsx
import type { ProgressView } from "../../api/queries";
import Sparkline from "../board/Sparkline";
import ChartFrame from "./ChartFrame";
import { signed } from "./units";

export default function RampRates({ ramp }: { ramp: ProgressView["ramp"] }) {
  const w28 = ramp.find((r) => r.days === 28)?.delta ?? null;
  const w7 = ramp.find((r) => r.days === 7)?.delta ?? null;
  const summary =
    w7 == null && w28 == null
      ? "No CTL history to measure a ramp."
      : `Fitness ${w7 == null ? "has no 7-day reading" : `${signed(w7)} over 7 days`}${w28 == null ? "" : `, ${signed(w28)} over 28 days`}.`;
  return (
    <ChartFrame
      title="Fitness ramp rate"
      summary={summary}
      table={{ head: ["Window", "CTL change"], rows: ramp.map((r) => [`Last ${r.days} days`, signed(r.delta)]) }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {ramp.map((r) => (
          <div key={r.days} role="group" aria-label={`Last ${r.days} days`} className="rounded-sm border border-line px-3 py-2">
            <p className="text-2xl font-semibold tracking-tight tabular-nums">{signed(r.delta)}</p>
            <p className="text-xs text-ink-2">Last {r.days} days</p>
            {r.series.some((v) => v != null) && <div className="mt-1 text-ink-2"><Sparkline values={r.series} low={null} high={null} /></div>}
          </div>
        ))}
      </div>
    </ChartFrame>
  );
}
```

Note: the tile's `role="group"` is named "Last 7 days" and its text also contains "Last 7 days"; that is intended (tests read the group text).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/pmc.test.tsx && npx vitest run tests/styles.test.ts`
Expected: PASS. If the readout expectation `no reading` fails after two ArrowLeft presses, count from the fixture: index starts 4 (2026-09-16); two steps left is index 2 (2026-09-14, the gap).

- [ ] **Step 6: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): PMC chart and ramp-rate tiles

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Weekly volume and longest workout

**Files:**
- Create: `web/src/components/progress/StackedBars.tsx`, `WeeklyBars.tsx`, `LongestWorkout.tsx`
- Test: `web/tests/weekly.test.tsx`

**Interfaces:**
- Consumes: `ProgressView["weeks"]`, `METRICS`, `Metric`, `SPORTS`, `sportKey`, `fold`, `Legend`, `sportColor`, `SPORT_LABEL`, `ChartFrame`, `Scrubber`, `scaleLinear`, `ticks`, `niceMax`, `axisLabels`, `axisDate` (Task 3).
- Produces: `<StackedBars weeks={string[]} partialLast={boolean} stacks={{key: string; label: string; color: string; values: number[]}[]} average={number | null} unit={string} digits={number} label={string} />`, `<WeeklyBars weeks={ProgressView["weeks"]} />`, `<LongestWorkout weeks={ProgressView["weeks"]} />`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/weekly.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LongestWorkout from "../src/components/progress/LongestWorkout";
import WeeklyBars from "../src/components/progress/WeeklyBars";
import { progressEmpty, progressFull } from "./progressFixtures";

test("WeeklyBars totals distance in miles and averages only the complete weeks", () => {
  render(<WeeklyBars weeks={progressFull().weeks} />);
  // week 1: (48280 + 10000) m = 36.2 mi; week 2: (24140 + 5000) m = 18.1 mi; partial week 3 excluded
  expect(screen.getByText(/Average 27\.2 mi per week over 2 complete weeks/)).toBeInTheDocument();
});

test("the metric switch changes the unit", async () => {
  const user = userEvent.setup();
  render(<WeeklyBars weeks={progressFull().weeks} />);
  await user.click(screen.getByRole("radio", { name: "Duration" }));
  expect(screen.getByText(/Average 3\.3 h per week/)).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "Elevation" }));
  expect(screen.getByText(/ft per week/)).toBeInTheDocument();
});

test("the partial week is labelled in the readout, and an unknown sport shows as Other", async () => {
  const user = userEvent.setup();
  render(<WeeklyBars weeks={progressFull().weeks} />);
  expect(screen.getByTestId("weekly-readout")).toHaveTextContent(/partial/i);
  const slider = screen.getByRole("slider", { name: "Inspect week" });
  slider.focus();
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByTestId("weekly-readout")).toHaveTextContent(/Other 3\.1 mi/);
  expect(screen.getByTestId("weekly-readout")).not.toHaveTextContent(/brick/i);
});

test("the legend names every drawn sport with a marker", () => {
  render(<WeeklyBars weeks={progressFull().weeks} />);
  const legend = screen.getByRole("list");
  for (const s of ["Bike", "Run", "Other"]) expect(within(legend).getByText(s)).toBeInTheDocument();
  expect(within(legend).queryByText("Swim")).not.toBeInTheDocument();
});

test("the table lists every week with a column per sport", async () => {
  const user = userEvent.setup();
  render(<WeeklyBars weeks={progressFull().weeks} />);
  await user.click(screen.getByRole("button", { name: "View as table" }));
  expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3 weeks
  expect(screen.getByRole("columnheader", { name: "Bike" })).toBeInTheDocument();
});

test("a single week draws with no scrubber and no NaN", () => {
  const one = progressFull().weeks.slice(0, 1);
  const { container } = render(<WeeklyBars weeks={one} />);
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test("an empty range says so", () => {
  render(<WeeklyBars weeks={progressEmpty().weeks} />);
  expect(screen.getByText("No data in this range.")).toBeInTheDocument();
});

test("LongestWorkout switches between duration and distance and states the longest", async () => {
  const user = userEvent.setup();
  render(<LongestWorkout weeks={progressFull().weeks} />);
  expect(screen.getByText(/Longest: 30\.0 mi/)).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "Duration" }));
  expect(screen.getByText(/Longest: 2\.0 h/)).toBeInTheDocument();
});
```

Fixture arithmetic for the expected numbers: week 1 distance 48280 + 10000 = 58280 m = 36.2 mi; week 2 24140 + 5000 = 29140 m = 18.1 mi; mean 27.2 mi. Duration: week 1 10800 s = 3.0 h, week 2 5400 s = 1.5 h, mean 2.25 h shown as "2.3 h" by `toFixed(1)`. That contradicts the test's "3.3 h": fix the expectation in Step 4 if it fails: the correct string is `Average 2.3 h per week` (2.25 rounds to 2.3 in `toFixed(1)`; if it prints 2.2, floating error, use `Average 2.[23] h`). Other week 2 (brick 5000 m) = 3.1 mi, matching the readout test. Longest distance is week 1's 48280 m = 30.0 mi; longest duration 7200 s = 2.0 h.

- [ ] **Step 2: Correct the duration expectation now**

In `weekly.test.tsx`, change `/Average 3\.3 h per week/` to `/Average 2\.[23] h per week/`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/weekly.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 4: Implement `StackedBars.tsx`**

Create `web/src/components/progress/StackedBars.tsx`:

```tsx
import { useId } from "react";
import { axisLabels, niceMax, scaleLinear, ticks } from "./scale";

const W = 800;
const H = 200;
const LEFT = 44;
const RIGHT = 8;
const TOP = 8;
const BOTTOM = 22;

export type Stack = { key: string; label: string; color: string; values: number[] };

/** Weekly bars, stacked, with a dashed average line and the last bar hatched when the week is partial. Decorative to assistive tech: the frame's summary, the scrubber and the table carry the data. */
export default function StackedBars({ weeks, stacks, partialLast, average, digits, label, marked }: {
  weeks: string[];
  stacks: Stack[];
  partialLast: boolean;
  average: number | null;
  digits: number;
  label: string;
  marked: number | null;
}) {
  const hatch = useId();
  const n = weeks.length;
  const totals = weeks.map((_, i) => stacks.reduce((s, st) => s + st.values[i], 0));
  const top = niceMax(Math.max(0, ...totals));
  const y = scaleLinear(0, top, H - BOTTOM, TOP);
  const slot = (W - LEFT - RIGHT) / Math.max(n, 1);
  const bw = Math.max(1, slot * 0.72);
  const x = (i: number) => LEFT + i * slot + (slot - bw) / 2;
  const labels = axisLabels(weeks, 5);
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs>
        <pattern id={hatch} width={5} height={5} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1={0} y1={0} x2={0} y2={5} stroke="var(--surface-2)" strokeWidth={2} />
        </pattern>
      </defs>
      {ticks(top).map((t) => (
        <g key={t}>
          <line x1={LEFT} x2={W - RIGHT} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
          <text x={LEFT - 6} y={y(t) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">{Number(t.toFixed(digits))}</text>
        </g>
      ))}
      {weeks.map((_, i) => {
        let base = 0;
        return (
          <g key={weeks[i]} opacity={marked == null || marked === i ? 1 : 0.55}>
            {stacks.map((st) => {
              const v = st.values[i];
              if (!(v > 0)) return null;
              const y0 = y(base);
              base += v;
              return <rect key={st.key} x={x(i)} y={y(base)} width={bw} height={Math.max(0, y0 - y(base))} fill={st.color} />;
            })}
            {partialLast && i === n - 1 && totals[i] > 0 && (
              <rect x={x(i)} y={y(totals[i])} width={bw} height={y(0) - y(totals[i])} fill={`url(#${hatch})`} />
            )}
          </g>
        );
      })}
      {average != null && average > 0 && (
        <line x1={LEFT} x2={W - RIGHT} y1={y(average)} y2={y(average)} stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="6 4" />
      )}
      {labels.map((l) => (
        <text key={l.i} x={x(l.i) + bw / 2} y={H - 4} textAnchor="middle" fontSize={12} fill="var(--ink-2)">{l.text}</text>
      ))}
    </svg>
  );
}
```

- [ ] **Step 5: Implement `WeeklyBars.tsx` and `LongestWorkout.tsx`**

Create `web/src/components/progress/WeeklyBars.tsx`:

```tsx
import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import StackedBars from "./StackedBars";
import { axisDate } from "./scale";
import { Legend, SPORTS, SPORT_LABEL, fold, sportColor, type Sport } from "./sports";
import { METRICS, type Metric, type SportTotals } from "./units";

type Week = ProgressView["weeks"][number];
const add = (a: SportTotals, b: SportTotals): SportTotals => ({
  duration_sec: a.duration_sec + b.duration_sec, distance_m: a.distance_m + b.distance_m,
  elevation_m: a.elevation_m + b.elevation_m, calories: a.calories + b.calories, tss: a.tss + b.tss,
});

export function MetricSwitch<T extends string>({ name, value, options, onChange }: {
  name: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={name} className="inline-flex rounded-sm border border-line">
      {options.map((o) => (
        <label key={o.value} className={`inline-flex min-h-7 cursor-pointer items-center px-2.5 text-xs has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${value === o.value ? "bg-hold text-on-fill" : "text-ink-2 hover:text-ink"}`}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
          {o.label}
        </label>
      ))}
    </div>
  );
}

export default function WeeklyBars({ weeks }: { weeks: Week[] }) {
  const [metric, setMetric] = useState<Metric>("distance");
  const [picked, setPicked] = useState<number | null>(null);
  const m = METRICS[metric];
  const folded = weeks.map((w) => fold(w.by_sport, add));
  const perSport = (i: number, s: Sport) => (folded[i][s] ? m.of(folded[i][s] as SportTotals) : 0);
  const used = SPORTS.filter((s) => weeks.some((_, i) => perSport(i, s) > 0));
  const stacks = used.map((s) => ({ key: s, label: SPORT_LABEL[s], color: sportColor(s), values: weeks.map((_, i) => perSport(i, s)) }));
  const totals = weeks.map((_, i) => used.reduce((sum, s) => sum + perSport(i, s), 0));
  const complete = weeks.map((w, i) => (w.partial ? null : totals[i])).filter((v): v is number => v != null);
  const average = complete.length ? complete.reduce((a, b) => a + b, 0) / complete.length : null;
  const index = picked != null && picked < weeks.length ? picked : weeks.length - 1;
  const fmt = (v: number) => v.toFixed(m.digits);
  const week = weeks[index];
  const readout = week
    ? `Week of ${axisDate(week.week_start)}${week.partial ? " (partial)" : ""}: ${fmt(totals[index])} ${m.unit}${used.filter((s) => perSport(index, s) > 0).map((s) => ` · ${SPORT_LABEL[s]} ${fmt(perSport(index, s))} ${m.unit}`).join("")}`
    : "";
  const empty = totals.every((t) => t === 0);
  const summary = empty
    ? "No data in this range."
    : `Average ${average == null ? "–" : fmt(average)} ${m.unit} per week${average == null ? "" : ` over ${complete.length} complete week${complete.length === 1 ? "" : "s"}`}.`;
  return (
    <ChartFrame
      title="Weekly volume by sport"
      summary={summary}
      controls={<MetricSwitch<Metric> name="Metric" value={metric} options={(Object.keys(METRICS) as Metric[]).map((k) => ({ value: k, label: METRICS[k].label }))} onChange={setMetric} />}
      table={{
        head: ["Week", ...used.map((s) => SPORT_LABEL[s]), "Total"],
        rows: weeks.map((w, i) => [`${w.week_start}${w.partial ? " (partial)" : ""}`, ...used.map((s) => fmt(perSport(i, s))), fmt(totals[i])]),
      }}
    >
      {empty ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <StackedBars weeks={weeks.map((w) => w.week_start)} stacks={stacks} partialLast={weeks.at(-1)?.partial ?? false} average={average} digits={m.digits} label={`Weekly ${m.label.toLowerCase()} in ${m.unit}, stacked by sport. Use the week slider or the table for values.`} marked={picked} />
          <p data-testid="weekly-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect week" count={weeks.length} index={index} valueText={readout} onChange={setPicked} />
          <Legend sports={used} />
        </>
      )}
    </ChartFrame>
  );
}
```

Create `web/src/components/progress/LongestWorkout.tsx`:

```tsx
import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import StackedBars from "./StackedBars";
import { MetricSwitch } from "./WeeklyBars";
import { axisDate } from "./scale";
import { hoursOf, miles } from "./units";

type Week = ProgressView["weeks"][number];
type Kind = "distance" | "duration";
const KIND = {
  distance: { unit: "mi", digits: 1, of: (w: Week) => miles(w.longest.distance_m) },
  duration: { unit: "h", digits: 1, of: (w: Week) => hoursOf(w.longest.duration_sec) },
};

export default function LongestWorkout({ weeks }: { weeks: Week[] }) {
  const [kind, setKind] = useState<Kind>("distance");
  const [picked, setPicked] = useState<number | null>(null);
  const k = KIND[kind];
  const values = weeks.map(k.of);
  const best = Math.max(0, ...values);
  const counted = weeks.map((w, i) => (w.partial ? null : values[i])).filter((v): v is number => v != null && v > 0);
  const average = counted.length ? counted.reduce((a, b) => a + b, 0) / counted.length : null;
  const index = picked != null && picked < weeks.length ? picked : weeks.length - 1;
  const fmt = (v: number) => v.toFixed(k.digits);
  const readout = weeks[index] ? `Week of ${axisDate(weeks[index].week_start)}${weeks[index].partial ? " (partial)" : ""}: ${fmt(values[index])} ${k.unit}` : "";
  const empty = best === 0;
  return (
    <ChartFrame
      title="Longest workout by week"
      summary={empty ? "No data in this range." : `Longest: ${fmt(best)} ${k.unit}${average == null ? "" : `; average ${fmt(average)} ${k.unit}`}.`}
      controls={<MetricSwitch<Kind> name="Longest by" value={kind} options={[{ value: "distance", label: "Distance" }, { value: "duration", label: "Duration" }]} onChange={setKind} />}
      table={{ head: ["Week", `Longest (${k.unit})`], rows: weeks.map((w, i) => [`${w.week_start}${w.partial ? " (partial)" : ""}`, fmt(values[i])]) }}
    >
      {empty ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <StackedBars weeks={weeks.map((w) => w.week_start)} stacks={[{ key: "longest", label: "Longest", color: "var(--accent)", values }]} partialLast={weeks.at(-1)?.partial ?? false} average={average} digits={k.digits} label={`Longest workout per week in ${k.unit}. Use the week slider or the table for values.`} marked={picked} />
          <p data-testid="longest-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect week" count={weeks.length} index={index} valueText={readout} onChange={setPicked} />
        </>
      )}
    </ChartFrame>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/weekly.test.tsx`
Expected: PASS. Likely fixes: if the "Other 3.1 mi" readout fails, the brick totals were not folded (check `fold` in Task 3 and that week index 1 is selected after one ArrowLeft from the last week). If `getByRole("list")` finds more than one list, scope it with `within` on the chart's `section`.

- [ ] **Step 7: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): weekly volume by sport and longest workout charts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sport share

**Files:**
- Create: `web/src/components/progress/ShareBars.tsx`
- Test: `web/tests/share.test.tsx`

**Interfaces:**
- Consumes: `ProgressView["share"]`, `fold`, `SPORTS`, `SPORT_LABEL`, `Marker`, `sportColor`, `ChartFrame`, `MetricSwitch` (Task 5), `miles`, `hoursOf` (Task 3).
- Produces: `<ShareBars share={ProgressView["share"]} />`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/share.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ShareBars from "../src/components/progress/ShareBars";
import { progressEmpty, progressFull } from "./progressFixtures";

test("each sport shows its percentage of completed and of planned duration", () => {
  render(<ShareBars share={progressFull().share} />);
  // completed: bike 10800, run 5400, brick 1800 -> other; total 18000
  const bike = screen.getByRole("group", { name: "Bike" });
  expect(bike).toHaveTextContent("Completed 60.0%");
  expect(bike).toHaveTextContent("Planned 62.5%"); // 12000 / 19200
  expect(screen.getByRole("group", { name: "Other" })).toHaveTextContent("Completed 10.0%");
  expect(screen.getByRole("group", { name: "Other" })).toHaveTextContent("Planned 0.0%");
});

test("switching to distance re-bases the shares on distance", async () => {
  const user = userEvent.setup();
  render(<ShareBars share={progressFull().share} />);
  await user.click(screen.getByRole("radio", { name: "Distance" }));
  // completed distance: bike 72420, run 15000 -> bike 82.8%
  expect(screen.getByRole("group", { name: "Bike" })).toHaveTextContent("Completed 82.8%");
});

test("sports with no share are left out and the summary names the leader", () => {
  render(<ShareBars share={progressFull().share} />);
  expect(screen.queryByRole("group", { name: "Swim" })).not.toBeInTheDocument();
  expect(screen.getByText(/Bike is 60\.0% of completed duration/)).toBeInTheDocument();
});

test("the bar widths follow the percentage", () => {
  render(<ShareBars share={progressFull().share} />);
  const bar = within(screen.getByRole("group", { name: "Bike" })).getAllByTestId("share-bar")[0];
  expect(bar).toHaveStyle({ width: "60%" });
});

test("empty shares say so and draw no bars", () => {
  render(<ShareBars share={progressEmpty().share} />);
  expect(screen.getByText("No data in this range.")).toBeInTheDocument();
  expect(screen.queryAllByTestId("share-bar")).toHaveLength(0);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/share.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `ShareBars.tsx`**

Create `web/src/components/progress/ShareBars.tsx`:

```tsx
import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import { MetricSwitch } from "./WeeklyBars";
import { Marker, SPORTS, SPORT_LABEL, fold, sportColor, type Sport } from "./sports";

type Measure = "duration_sec" | "distance_m";
const LABEL: Record<Measure, string> = { duration_sec: "duration", distance_m: "distance" };

function shares(rec: Record<string, number>): { total: number; by: Partial<Record<Sport, number>> } {
  const by = fold(rec, (a, b) => a + b);
  return { total: Object.values(by).reduce((s, v) => s + (v ?? 0), 0), by };
}

export default function ShareBars({ share }: { share: ProgressView["share"] }) {
  const [measure, setMeasure] = useState<Measure>("duration_sec");
  const done = shares(share.completed[measure]);
  const plan = shares(share.planned[measure]);
  const pct = (s: { total: number; by: Partial<Record<Sport, number>> }, sport: Sport) => (s.total > 0 ? ((s.by[sport] ?? 0) / s.total) * 100 : 0);
  const rows = SPORTS.filter((s) => (done.by[s] ?? 0) > 0 || (plan.by[s] ?? 0) > 0);
  const lead = rows.length ? [...rows].sort((a, b) => pct(done, b) - pct(done, a))[0] : null;
  const summary = lead && done.total > 0 ? `${SPORT_LABEL[lead]} is ${pct(done, lead).toFixed(1)}% of completed ${LABEL[measure]}.` : "No data in this range.";
  return (
    <ChartFrame
      title="Sport share"
      summary={summary}
      controls={<MetricSwitch<Measure> name="Share of" value={measure} options={[{ value: "duration_sec", label: "Duration" }, { value: "distance_m", label: "Distance" }]} onChange={setMeasure} />}
      table={{ head: ["Sport", "Completed %", "Planned %"], rows: rows.map((s) => [SPORT_LABEL[s], pct(done, s).toFixed(1), pct(plan, s).toFixed(1)]) }}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((s) => (
            <li key={s} role="group" aria-label={SPORT_LABEL[s]}>
              <p className="inline-flex items-center gap-1.5 text-sm"><Marker sport={s} />{SPORT_LABEL[s]}</p>
              {(["Completed", "Planned"] as const).map((kind) => {
                const p = pct(kind === "Completed" ? done : plan, s);
                return (
                  <div key={kind} className="mt-1 flex items-center gap-3 text-xs">
                    <span className="w-40 shrink-0 text-ink-2 tabular-nums sm:w-44">{kind} {p.toFixed(1)}%</span>
                    <div className="h-2 min-w-0 flex-1 rounded-sm bg-line/50">
                      {p > 0 && <div data-testid="share-bar" className={`h-full rounded-sm ${kind === "Planned" ? "opacity-50" : ""}`} style={{ width: `${p}%`, background: sportColor(s) }} />}
                    </div>
                  </div>
                );
              })}
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/share.test.tsx`
Expected: PASS. If `toHaveStyle({ width: "60%" })` fails on the first `share-bar` of Bike, the first bar is the Completed row (60.0), which is correct; a mismatch means the completed total was computed from planned data.

- [ ] **Step 5: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): sport share bars

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The Progress page, routing and states

**Files:**
- Create: `web/src/pages/Progress.tsx`
- Modify: `web/src/router.tsx`, `web/src/pages/Placeholder.tsx`, `web/tests/shell.test.tsx`
- Test: `web/tests/progressPage.test.tsx`

**Interfaces:**
- Consumes: `useProgress`, `ProgressRange`, `RangePicker`, `Pmc`, `RampRates`, `WeeklyBars`, `LongestWorkout`, `ShareBars`, `day` from `web/src/lib/format.ts`, `STALE_DAYS` mirrored as a constant here (3).
- Produces: default export `Progress` page; route `/progress`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/progressPage.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Progress from "../src/pages/Progress";
import { renderWith } from "./fixtures";
import { progressEmpty, progressFull } from "./progressFixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
afterEach(() => vi.restoreAllMocks());

test("draws every chart and defaults to 12 months", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressFull()));
  renderWith(<Progress />);
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
  for (const h of ["Fitness ramp rate", "Weekly volume by sport", "Longest workout by week", "Sport share"]) {
    expect(screen.getByRole("heading", { name: h })).toBeInTheDocument();
  }
  expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();
  expect(String(spy.mock.calls[0][0])).toBe("/api/progress?range=12m");
});

test("changing the range asks for it and never shows the old data under the new label", async () => {
  let release: (r: Response) => void = () => {};
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    String(input).endsWith("range=6w") ? new Promise<Response>((r) => (release = r)) : Promise.resolve(json(progressFull())),
  );
  const user = userEvent.setup();
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  await user.click(screen.getByRole("radio", { name: "6 weeks" }));
  expect(String(spy.mock.calls.at(-1)![0])).toBe("/api/progress?range=6w");
  expect(screen.queryByRole("heading", { name: "Performance management" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  release(json({ ...progressFull(), range: "6w" }));
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
});

test("an error shows a message and retry refetches", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => json({ detail: "internal error" }, 500));
  spy.mockImplementation(async () => json(progressFull()));
  const user = userEvent.setup();
  renderWith(<Progress />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
});

test("a fresh database shows empty states and no as-of date", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressEmpty()));
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  expect(screen.getAllByText("No data in this range.").length).toBeGreaterThanOrEqual(3);
  expect(screen.getByText(/No fitness readings yet/)).toBeInTheDocument();
});

test("a curve older than three days is flagged as stale", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ ...progressFull(), as_of: "2026-09-10", end: "2026-09-16" }));
  renderWith(<Progress />);
  await waitFor(() => expect(screen.getByText(/6 days old/)).toBeInTheDocument());
  expect(screen.getByText(/Fitness as of/)).toBeInTheDocument();
});

test("a current curve is not flagged", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressFull()));
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  expect(screen.getByText(/Fitness as of/)).toBeInTheDocument();
  expect(screen.queryByText(/days old/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/progressPage.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the page**

Create `web/src/pages/Progress.tsx`:

```tsx
import { useSearchParams } from "react-router";
import { useProgress, type ProgressRange } from "../api/queries";
import LongestWorkout from "../components/progress/LongestWorkout";
import Pmc from "../components/progress/Pmc";
import RampRates from "../components/progress/RampRates";
import RangePicker from "../components/progress/RangePicker";
import ShareBars from "../components/progress/ShareBars";
import WeeklyBars from "../components/progress/WeeklyBars";
import { day } from "../lib/format";

const RANGES: ProgressRange[] = ["6w", "6m", "12m", "all"];
const STALE_DAYS = 3; // mirrors STALE_DAYS in tri_web/progress.py

const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);

export default function Progress() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("range");
  const range: ProgressRange = RANGES.includes(asked as ProgressRange) ? (asked as ProgressRange) : "12m";
  const q = useProgress(range);
  const view = q.data;
  const age = view?.as_of ? daysBetween(view.as_of, view.end) : null;
  return (
    <section className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-sm font-semibold tracking-wide uppercase">Progress</h1>
        <RangePicker value={range} onChange={(r) => setParams({ range: r }, { replace: true })} />
      </div>
      {view && (
        <p className="mt-2 text-xs text-ink-2">
          {view.as_of ? `Fitness as of ${day(view.as_of)}` : "No fitness readings yet"}
          {age != null && age > STALE_DAYS && <span className="ml-2 font-medium text-warn">{age} days old: sync for fresh numbers</span>}
        </p>
      )}
      {q.isPending && <p role="status" className="mt-6 text-sm text-ink-2">Loading progress…</p>}
      {q.isError && (
        <div role="alert" className="mt-6 flex flex-wrap items-center gap-3 text-sm">
          <span>Could not load progress.</span>
          <button type="button" onClick={() => q.refetch()} className="min-h-8 rounded-sm border border-line px-3 text-xs hover:text-ink">Retry</button>
        </div>
      )}
      {view && (
        <div className="mt-4 space-y-4">
          <Pmc pmc={view.pmc} ramp28={view.ramp.find((r) => r.days === 28)?.delta ?? null} />
          <RampRates ramp={view.ramp} />
          <WeeklyBars weeks={view.weeks} />
          <LongestWorkout weeks={view.weeks} />
          <ShareBars share={view.share} />
        </div>
      )}
    </section>
  );
}
```

`day()` from `lib/format.ts` formats the date with a weekday and can vary by locale, which is fine for display. Because the query key includes the range, a range change starts a fresh pending query, so old data cannot show under the new label.

- [ ] **Step 4: Route it and retire the placeholder's Progress case**

In `web/src/router.tsx`: add `import Progress from "./pages/Progress";` and replace the progress route with `{ path: "/progress", element: <Progress /> },`.

In `web/src/pages/Placeholder.tsx`: remove the `2:` entry from `blurbs` and change the prop type to `subProject: 3 | 4`.

In `web/tests/shell.test.tsx`: it renders `<Placeholder name="Progress" subProject={2} />` for `/progress`; change that route element to `<Placeholder name="Nutrition" subProject={3} />` at path `/progress`? No: keep the test about navigation, not the placeholder. Replace that route element with `<div>progress body</div>` and update the assertions that look for "Coming soon" text on Progress (search the file for `Coming soon` and `Progress`; expect `progress body` instead), and remove the now-unused `Placeholder` import if nothing else uses it.

- [ ] **Step 5: Run the web suite**

Run: `cd web && npx vitest run`
Expected: all PASS, including `shell.test.tsx` and `styles.test.ts`. If `styles.test.ts` flags a file for text below 12px, replace `text-[11px]`/`text-[10px]` with `text-xs`.

- [ ] **Step 6: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): Progress page with range picker, loading, error and stale states

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: End-to-end smoke, docs and Definition of Done

**Files:**
- Create: `web/tests/e2e/progress.spec.ts`
- Modify: `docs/superpowers/specs/2026-09-29-progress-page-design.md` (the PMC wording and the scrubber), `docs/architecture/tri-web.md`, `DESIGN.md`
- Copy: spec, plan and the two edited docs to the vault

**Interfaces:**
- Consumes: everything above.
- Produces: a green Definition of Done.

- [ ] **Step 1: Write the e2e smoke test**

Create `web/tests/e2e/progress.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const week = (start: string, partial = false) => ({
  week_start: start, partial,
  by_sport: { bike: { duration_sec: 3600, distance_m: 30000, elevation_m: 100, calories: 600, tss: 50 } },
  longest: { duration_sec: 3600, distance_m: 30000 },
});
const progress = (range: string) => ({
  range, start: "2026-09-07", end: "2026-09-16", as_of: "2026-09-16",
  pmc: [
    { date: "2026-09-15", ctl: 39, atl: 44, tsb: -5, tss: 50 },
    { date: "2026-09-16", ctl: 40, atl: 45, tsb: -5, tss: 60 },
  ],
  ramp: [7, 28, 90, 365].map((days) => ({ days, delta: 1, series: [39, 40] })),
  weeks: [week("2026-09-07"), week("2026-09-14", true)],
  share: { completed: { duration_sec: { bike: 7200 }, distance_m: { bike: 60000 } }, planned: { duration_sec: { bike: 7200 }, distance_m: { bike: 60000 } } },
});
const todayStub = {
  header: { today: "2026-09-16", phase: "active", goal: null, week: { start: "2026-09-14", number: null, of: null }, last_sync: [] },
  session: null, readiness: null, fuel: { target: null, targets_through: null }, week: null,
  labs: null, labs_enabled: false, labs_missing: false,
  verdict: { level: "none", reasons: [], based_on: null, stale: false, harder_than_call: false, session_done: false },
  conditions: [], pending: null,
};

test("Progress renders every chart and the range picker changes the request", async ({ page }) => {
  const asked: string[] = [];
  await page.route("**/api/today", (r) => r.fulfill({ json: todayStub }));
  await page.route("**/api/system/status", (r) => r.fulfill({ json: { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", running: null } }));
  await page.route("**/api/progress**", (r) => {
    const range = new URL(r.request().url()).searchParams.get("range") ?? "";
    asked.push(range);
    return r.fulfill({ json: progress(range) });
  });
  await page.goto("/progress");
  for (const h of ["Performance management", "Fitness ramp rate", "Weekly volume by sport", "Longest workout by week", "Sport share"]) {
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  }
  await page.getByRole("radio", { name: "6 weeks" }).check({ force: true });
  await expect.poll(() => asked.at(-1)).toBe("6w");
  await expect(page).toHaveURL(/range=6w/);
  await page.getByRole("button", { name: "View as table" }).first().click();
  await expect(page.getByRole("table").first()).toBeVisible();
});

test("Progress fits a phone with no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.route("**/api/today", (r) => r.fulfill({ json: todayStub }));
  await page.route("**/api/system/status", (r) => r.fulfill({ json: { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", running: null } }));
  await page.route("**/api/progress**", (r) => r.fulfill({ json: progress("12m") }));
  await page.goto("/progress");
  await expect(page.getByRole("heading", { name: "Sport share" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
```

- [ ] **Step 2: Run the e2e tests**

Run: `cd web && npx playwright test tests/e2e/progress.spec.ts`
Expected: PASS (the config builds and serves the app; first run may need `npx playwright install chromium`). If the phone test fails on horizontal overflow, find the offender with a temporary `page.evaluate` that lists elements wider than the viewport, then fix its width (charts use `w-full` with a `viewBox`, so the usual culprit is the range picker or a control row missing `flex-wrap`).

- [ ] **Step 3: Update the docs**

In the spec `docs/superpowers/specs/2026-09-29-progress-page-design.md`:
- Under §3, change the `Pmc` bullet to: "PMC: CTL area with ATL line in one panel, and TSB in a second panel below on the same x axis, with a zero line and the neutral-form band (-10 to 5). Two panels replace a dual axis, which reads more clearly."
- Under §3.1, change the keyboard bullet to: "Each chart has a slider that steps through its points with the arrow keys and shows the value in a visible readout; bars and points are not individual tab stops, so a 150-week history is one stop."
- Set `**Status:**` to `Approved 2026-09-29; implemented (see plan)`.

In `docs/architecture/tri-web.md`, add `GET /api/progress?range=` to the route list with a one-line description, following the format of the neighbouring entries (read the file first and match it).

In `DESIGN.md`, add a short "Progress charts" note under the components section: the `--sport-*` tokens, the marker shapes, `ChartFrame`, and the scrubber pattern. Read the file's existing section style first and match it.

- [ ] **Step 4: Copy markdown to the vault**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/docs/superpowers/specs $V/docs/superpowers/plans $V/docs/architecture
cp docs/superpowers/specs/2026-09-29-progress-page-design.md $V/docs/superpowers/specs/
cp docs/superpowers/plans/2026-09-29-progress-page.md $V/docs/superpowers/plans/
cp docs/architecture/tri-web.md $V/docs/architecture/
cp DESIGN.md $V/DESIGN.md
```

The vault keeps `DESIGN.md` lowercase-free at its root as it does today (`ls $V` showed `DESIGN.md`).

- [ ] **Step 5: Definition of Done, in order**

Run each and read the output:

1. Tests: `uv run pytest packages -q` and `cd web && npx vitest run`
2. Lint and types: `uv run ruff check packages && uv run ruff format --check packages && uv run mypy` and `cd web && npm run lint && npx tsc -b`
3. Build: `cd web && npm run build`

Expected: all green. If a Postgres-backed test skips, say so in the report rather than claiming a pass. Fix failures as they appear and rerun from the failing step.

- [ ] **Step 6: Look at it**

Run: `uv run tri-web serve` (the app is at http://127.0.0.1:8321/progress), open the Progress tab against the real synced data, and check: the PMC matches what TrainingPeaks shows for CTL/ATL/TSB today (CTL 16, ATL 21, TSB −1 on 2026-09-29), each range loads, the table toggle works on every chart, and it reads at phone width. Report anything that looks wrong instead of tuning silently. This needs Brian's local database, so ask before starting the server if it is not already running.

- [ ] **Step 7: Commit**

```bash
git add web/tests/e2e/progress.spec.ts docs DESIGN.md
git commit -m "docs: Progress page e2e smoke, architecture and design notes

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Do not push; ask Brian first.

---

## Self-Review

**Spec coverage:** §2.1 response fields (`range/start/end`, `as_of`, `pmc`, `ramp`, `weeks`, `share`) are Task 1; §2.2 rules (repo layer, deleted excluded, null handling, no LLM) are Tasks 1 and 2; route and 422 are Task 2; §3 page, URL param, and the six components are Tasks 3 to 7 (LongestWorkout is its own component; Task 5); §3.1 accessibility is `ChartFrame`, `Scrubber`, tokens and the phone-width e2e; §3.2 loading, error, empty and stale are Task 7; §4 tests are in each task plus the Playwright smoke in Task 8; §5 delivery (types, docs, vault) is Tasks 2 and 8. Spec deviations, both recorded in Task 8's doc updates: PMC uses a second panel instead of a second axis, and the keyboard route is a slider per chart instead of per-point tab stops.

**Type consistency:** `compute_progress`, `range_floor`, `metrics_floor`, `RangeKey` and the model names match between Tasks 1 and 2; `METRICS`, `signed`, `fold`, `sportKey`, `MetricSwitch` (defined in `WeeklyBars.tsx` in Task 5, imported by Tasks 5 and 6) and the fixture names match their uses; `Pmc` takes `pmc` and `ramp28`, and the page passes exactly those.

**Placeholders:** none. Two steps say "read the file and match its style" (architecture doc and `DESIGN.md`) because their current layout was not read while planning; they name the exact content to add.

**Known risks, flagged for the executor:**
- The route tests insert rows with raw SQL through the `nocommit` fixture; if `NoCommit` does not expose `execute`, use the `db` fixture the way `test_today.py` seeds rows.
- Assumed units are miles, feet and hours (from the TrainingPeaks screenshots).
- `tests/shell.test.tsx` edits in Task 7 depend on its current assertions; read the file before changing it and change only what the Progress route swap requires.
