# Data layer: sync ahead, tombstones, Garmin activities, record-before-write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `workouts` match the TrainingPeaks calendar 28 days forward and backwards (deletions included), keep every Garmin activity so a brick has both legs, and put a `pending` row in the change tables before every TrainingPeaks or Garmin write.

**Architecture:** Migration 007 adds `workouts.deleted_at`, the `garmin_activities` table and `status`/`error` on `plan_changes` and `nutrition_changes`. The sync runner lists TrainingPeaks to `today + 28`, tombstones rows in the fetched window that the listing no longer has, and stores every Garmin activity before matching. A new `tri_core.db.writes.recorded_write` wraps each external write: `pending` row, call, `applied` or `failed`. Planning and nutrition apply use it and reconcile old `pending` rows against the server at the start of each apply. Every reader of `workouts` filters `deleted_at is null`.

**Tech Stack:** Python 3.12, uv workspace, psycopg 3 on Postgres 16, pydantic 2, LangGraph, pytest with pytest-asyncio in auto mode, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-24-data-layer-design.md`. The spec's line numbers are `main` @ 6540055. This plan's line numbers are `main` @ b14a0bc (correctness fixes plan 01 merged). Correctness fixes plan 02 (`2026-09-24-correctness-fixes-02-planning-coach-core.md`) must be merged before this plan starts; every "replace" block below was chosen to avoid the lines plan 02 rewrites, so it matches both before and after plan 02, but line numbers in `runner.py`, `sql_tool.py`, `tri_planning/repo.py` and `tri_planning/graph/nodes/apply.py` shift once plan 02 is in. Find blocks by text, not by line.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon-agent-data-layer -b feat/data-layer main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout.
- **Precondition:** correctness fixes plan 02 is merged: `grep -q "def calendar_before" packages/tri-planning/src/tri_planning/repo.py` exits 0 on `main`. If it does not, stop and tell Brian.
- **Baseline B:** run `uv run pytest -q` before Task 1 and record the result. Every task's Definition of done expects the count to rise by that task's new tests and never to lose a test except where a task quotes an existing test and shows its replacement.
- **The database is not yours to migrate.** Task 1 writes `migrations/007_data_layer.sql`. After Task 1, stop, print `docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/007_data_layer.sql`, and ask Brian to run it. Tasks 2-8 need 007 on the test database; do not start Task 2 until Brian confirms. Never run psql, DDL or DML against either database yourself. Brian applies 007 to `tri_analyze` at rollout (spec §9).
- **Every "replace ... with" block is an exact string match.** If a block does not match, stop and report; do not improvise the edit.
- **Test rules:** fixtures keep their signatures. An existing assertion changes only where a task quotes the old test and shows the new one.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages scripts`
  2. `uv run ruff check --fix packages scripts`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing langsmith `DeprecationWarning`. `ruff check --fix` may reorder imports; accept its order. Never add `# type: ignore`. Ruff has bugbear (`B`) on: no closures over a loop variable inside a `for` body (B023), which is why Tasks 6 and 7 put the per-change write in a module-level helper.
- **Commits:** one commit per task on `feat/data-layer`; local git writes are allowed in this repo. End every message with the executing model's `Co-Authored-By:` line from the session's git attribution reminder. Never `git push`, and never rebase, `reset --hard`, delete a branch or amend without asking Brian first.
- **Look up dependencies before editing.** Before a task's first code edit, check the current docs through the Context7 MCP tool for each dependency that task's code uses, for the version in `uv.lock`: psycopg 3 (`psycopg.sql.SQL`/`Identifier`, list adaptation for `= any(%s)` and `<> all(%s)`, `Cursor.rowcount`, `Jsonb`) in Tasks 2, 3, 5, 6, 7; Postgres 16 (`make_interval`, partial and expression indexes) in Tasks 1 and 5; pydantic 2 (`model_validate`) in Tasks 6 and 7; pytest and pytest-asyncio (`ExceptionInfo`, `__notes__`, auto mode) in Tasks 2-7; the MCP Python SDK (`ClientSession.list_tools`, `Tool.inputSchema`) in Task 7 Step 1. If Context7 has no coverage, `curl` the official docs; do not use web search. If the docs contradict a code block here, stop and report.
- **Existing tests this plan changes** (Brian's approval of the plan authorizes exactly these, no others): `test_brick_matches_any_sport_once` is replaced by `test_brick_takes_both_legs` (Task 3); the row-count assertion in `tri-planning` `test_mid_batch_failure_keeps_remainder_pending` (Task 6); the row-count assertion in `tri-nutrition` `test_garmin_failure_keeps_change_pending` (Task 7). Each is quoted in its task. No assertion is weakened: each now also checks the new `failed` row.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file created or edited is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Stop conditions

Stop and report to Brian without working around it if:
- a "replace" block does not match the current file;
- an existing assertion outside the tests a task names fails;
- Task 7 Step 1 shows `tp_list_notes` takes no date range, or `tp_get_note` / `tp_list_notes` answer in a shape other than the one Task 7 assumes.

## Review Focus

1. **A TrainingPeaks listing chunk that comes back empty-handed** (`None`, or no `workouts` list) must not tombstone the chunk's workouts; the run upserts what it has, skips deletion for the whole window, and says so. Test: Task 2, `test_a_failed_listing_deletes_nothing`.
2. **The forward window must not store projected fitness.** `tp_get_fitness` over `today + 28` may answer future days; `daily_metrics` must keep no row after today, or every "latest row" query reads a projection. Test: Task 2, `test_future_fitness_is_not_stored`.
3. **Reconciling a pending create must not adopt the athlete's own workout.** Two unrecorded workouts on the day with the pending create's title and sport are ambiguous; the row becomes `failed` rather than claiming one (claiming would let the agent later delete the athlete's session). Test: Task 6, `test_an_ambiguous_pending_create_is_failed`.
4. **A database outage during the failure mark must not hide the server error.** The caller sees the original `McpToolError`, with a note that the row stayed `pending`. Test: Task 5, `test_the_call_error_survives_a_failed_failure_mark`.
5. **A Garmin multisport activity** (`sport = 'brick'`) is the whole brick: it fills a brick on its own and the brick takes no second leg; on a later sync, a brick with one linked leg still takes its second. Tests: Task 3, `test_a_multisport_activity_fills_the_brick` and `test_second_leg_on_a_later_sync`.

---

## Tasks

1. Migration 007, backfill, `GarminActivityRow`
2. TrainingPeaks syncs ahead and tombstones missing workouts
3. Garmin activities are kept; bricks take two legs
4. Readers hide deleted workouts; `SCHEMA_DOC`
5. `recorded_write`
6. Planning apply records before writing and reconciles pending rows
7. Nutrition apply records before writing and reconciles pending rows
8. Docs and final checks

---

### Task 1: Migration 007, backfill, `GarminActivityRow`

**Files:**
- Create: `migrations/007_data_layer.sql`
- Modify: `packages/tri-core/src/tri_core/db/models.py:72` (append after `DailyMetricsRow`)
- Modify: `packages/tri-core/src/tri_core/sync/garmin.py:10, 19-29`
- Test: `packages/tri-core/tests/test_sync_garmin.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `workouts.deleted_at timestamptz`; index `workouts_live_date_idx`.
  - Table `garmin_activities(id text pk, tp_workout_id text fk workouts on delete set null, sport text not null, type_key, start_time_local timestamp not null, duration_sec numeric, distance_m numeric, avg_hr int, name, raw jsonb not null, synced_at)`.
  - `plan_changes.status text not null default 'applied'`, `plan_changes.error text`; the same two on `nutrition_changes`.
  - `tri_core.db.models.GarminActivityRow` (fields `id, type_key, sport, start_time_local, duration_sec, distance_m, avg_hr, name, raw`, `slots=True`). `tri_core.sync.garmin.GarminActivity` becomes an alias of it, so every existing import keeps working.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_sync_garmin.py`:

```python
def test_garmin_activity_is_the_db_row_type():
    from tri_core.db.models import GarminActivityRow
    from tri_core.sync.garmin import GarminActivity

    assert GarminActivity is GarminActivityRow
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_sync_garmin.py::test_garmin_activity_is_the_db_row_type -v`
Expected: FAIL with `ImportError: cannot import name 'GarminActivityRow'`.

- [ ] **Step 3: Write the migration**

Create `migrations/007_data_layer.sql`:

```sql
-- 007_data_layer.sql  (apply to tri_analyze and tri_analyze_test)
-- Data layer, 2026-09-24 spec: tombstones for workouts removed from TrainingPeaks, every Garmin
-- activity kept (a brick has two), and a status on every recorded external write.

alter table workouts add column if not exists deleted_at timestamptz;
create index if not exists workouts_live_date_idx on workouts (workout_date) where deleted_at is null;

create table if not exists garmin_activities (
  id                text primary key,
  tp_workout_id     text references workouts on delete set null,
  sport             text not null,
  type_key          text,
  start_time_local  timestamp not null,
  duration_sec      numeric,
  distance_m        numeric,
  avg_hr            int,
  name              text,
  raw               jsonb not null,
  synced_at         timestamptz not null default now()
);
create index if not exists garmin_activities_workout_idx on garmin_activities (tp_workout_id);
create index if not exists garmin_activities_day_idx on garmin_activities ((start_time_local::date));

-- One row per activity already matched; the next Garmin sync fills the rest inside its window.
insert into garmin_activities (id, tp_workout_id, sport, start_time_local, raw)
select garmin_activity_id, tp_workout_id, sport,
       coalesce(start_time_local, workout_date::timestamp), '{}'::jsonb
from workouts
where garmin_activity_id is not null
on conflict (id) do nothing;

-- Existing rows were written after a successful call: they are 'applied'.
alter table plan_changes add column if not exists status text not null default 'applied';
alter table plan_changes add column if not exists error text;
alter table nutrition_changes add column if not exists status text not null default 'applied';
alter table nutrition_changes add column if not exists error text;
```

- [ ] **Step 4: Add the row type**

In `packages/tri-core/src/tri_core/db/models.py`, replace:

```python
@dataclass(slots=True)
class SyncState:
```

with:

```python
@dataclass(slots=True)
class GarminActivityRow:
    id: str
    type_key: str | None
    sport: str
    start_time_local: datetime
    duration_sec: float | None
    distance_m: float | None
    avg_hr: int | None
    name: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class SyncState:
```

In `packages/tri-core/src/tri_core/sync/garmin.py`, replace:

```python
from tri_core.db.models import DailyMetricsRow
```

with:

```python
from tri_core.db.models import DailyMetricsRow, GarminActivityRow
```

and replace:

```python
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
```

with:

```python
GarminActivity = GarminActivityRow  # parsed from the activity list; stored as it is
```

If ruff then reports `dataclass` unused in `garmin.py`, it is not: `GarminSnapshot` still uses it. Leave the import line as `ruff check --fix` leaves it.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass.

- [ ] **Step 6: Definition of done, then commit**

```bash
git add migrations/007_data_layer.sql packages/tri-core/src/tri_core/db/models.py packages/tri-core/src/tri_core/sync/garmin.py packages/tri-core/tests/test_sync_garmin.py
git commit -m "db: migration 007, data layer (tombstones, garmin_activities, change status)"
```

- [ ] **Step 7: Stop for the migration**

Print, and ask Brian to run, then wait for confirmation:

```bash
docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/007_data_layer.sql
```

---

### Task 2: TrainingPeaks syncs ahead and tombstones missing workouts

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/repo.py:93-106, 158-163`
- Modify: `packages/tri-core/src/tri_core/sync/trainingpeaks.py:21-25, 163-177`
- Modify: `packages/tri-core/src/tri_core/sync/runner.py:23-25, 49-61, 73-82, 110-124`
- Test: `packages/tri-core/tests/test_repo.py` (append), `packages/tri-core/tests/test_sync_runner.py` (append)

**Interfaces:**
- Consumes: `workouts.deleted_at` (Task 1).
- Produces:
  - `runner.SYNC_AHEAD_DAYS = 28`.
  - `resolve_window(state, since, full, today, first_run_days, *, ahead_days=0, overlap_days=OVERLAP_DAYS) -> tuple[date, date]`; the end is `today + ahead_days`.
  - `repo.list_workouts_between(conn, start, end, *, include_deleted=False)`.
  - `repo.mark_missing_deleted(conn, start: date, end: date, seen_ids: Collection[str]) -> int` (rows tombstoned).
  - `repo.count_deleted(conn, ids: Collection[str]) -> int`.
  - `upsert_workouts` clears `deleted_at` on conflict.
  - `TPSnapshot.listed_ids: set[str]`, `TPSnapshot.listing_complete: bool`.
  - `sync_state.last_synced_date` is never after today.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_repo.py`:

```python
def test_mark_missing_deleted_stays_inside_the_window(db):
    repo.upsert_workouts(
        db,
        [
            _workout(tp_workout_id="w1", workout_date=date(2026, 9, 1)),
            _workout(tp_workout_id="w2", workout_date=date(2026, 9, 2)),
            _workout(tp_workout_id="w3", workout_date=date(2026, 9, 10)),
        ],
    )
    assert repo.mark_missing_deleted(db, date(2026, 9, 1), date(2026, 9, 5), {"w1"}) == 1
    live = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 10))
    assert [r["tp_workout_id"] for r in live] == ["w1", "w3"]
    every = repo.list_workouts_between(
        db, date(2026, 9, 1), date(2026, 9, 10), include_deleted=True
    )
    assert [(r["tp_workout_id"], r["deleted_at"] is not None) for r in every] == [
        ("w1", False),
        ("w2", True),
        ("w3", False),
    ]
    # already tombstoned: not counted again
    assert repo.mark_missing_deleted(db, date(2026, 9, 1), date(2026, 9, 5), {"w1"}) == 0


def test_upsert_restores_a_tombstoned_workout(db):
    repo.upsert_workouts(db, [_workout()])
    repo.mark_missing_deleted(db, date(2026, 9, 1), date(2026, 9, 1), set())
    assert repo.count_deleted(db, ["w1"]) == 1
    repo.upsert_workouts(db, [_workout(title="Back")])
    assert repo.count_deleted(db, ["w1"]) == 0
    row = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert row["title"] == "Back" and row["deleted_at"] is None
```

Append to `packages/tri-core/tests/test_sync_runner.py`:

```python
from datetime import timedelta

from tri_core.sync.runner import SYNC_AHEAD_DAYS
from tri_core.sync.trainingpeaks import fetch_trainingpeaks


def test_resolve_window_reaches_ahead():
    st = SyncState("trainingpeaks", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    ahead = date(2026, 10, 4)  # TODAY + 28
    assert SYNC_AHEAD_DAYS == 28
    assert resolve_window(st, None, False, TODAY, 365, ahead_days=28) == (date(2026, 8, 29), ahead)
    assert resolve_window(None, None, False, TODAY, 365, ahead_days=28) == (date(2025, 9, 6), ahead)
    assert resolve_window(st, date(2026, 6, 1), False, TODAY, 365, ahead_days=28) == (
        date(2026, 6, 1),
        ahead,
    )


def _detail(wid, day):
    return {
        "id": wid,
        "date": day,
        "sport": "Bike",
        "title": f"ride {wid}",
        "metrics": {"tss_planned": 50},
    }


def _tp_calendar(listing):
    """TrainingPeaks answers whose listing is the `listing` dict, so a test can change it."""
    days = {"w1": "2026-09-01", "w2": "2026-09-02"}
    return {
        "tp_get_athlete_settings": {"settings": {"athleteId": 9}},
        "tp_get_workouts": listing,
        "tp_get_workout": lambda a: _detail(a["workout_id"], days[a["workout_id"]]),
        "tp_get_fitness": {"daily_data": []},
    }


async def test_fetch_records_listed_ids_and_completeness():
    listing = {"workouts": [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]}
    snap = await fetch_trainingpeaks(
        _Fake(_tp_calendar(listing)), date(2026, 8, 30), date(2026, 9, 3), log=lambda m: None
    )
    assert snap.listed_ids == {"w1", "w2"} and snap.listing_complete is True
    broken = await fetch_trainingpeaks(
        _Fake(_tp_calendar(None)), date(2026, 8, 30), date(2026, 9, 3), log=lambda m: None
    )
    assert broken.listed_ids == set() and broken.listing_complete is False


async def _tp_sync(db, monkeypatch, answers, lines):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))
    return await run_sync(
        settings,
        since=date(2026, 8, 30),
        sources=("trainingpeaks",),
        log=lines.append,
        open_tp=_factory(_Fake(answers)),
    )


@pytest.mark.db
async def test_a_workout_removed_from_tp_is_tombstoned_then_restored(db, monkeypatch):
    both = [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]
    listing = {"workouts": list(both)}
    answers = _tp_calendar(listing)
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    lines: list[str] = []

    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1", "w2"]

    listing["workouts"] = both[:1]  # w2 deleted in TrainingPeaks
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1"]
    every = repo.list_workouts_between(db, d1, d2, include_deleted=True)
    assert [w["deleted_at"] is not None for w in every] == [False, True]
    assert any("1 deleted, 0 restored" in line for line in lines)

    listing["workouts"] = list(both)  # w2 back
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1", "w2"]
    assert any("0 deleted, 1 restored" in line for line in lines)


@pytest.mark.db
async def test_a_failed_listing_deletes_nothing(db, monkeypatch):
    listing = {"workouts": [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]}
    lines: list[str] = []
    assert (await _tp_sync(db, monkeypatch, _tp_calendar(listing), lines)).ok
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, _tp_calendar(None), lines)).ok
    live = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 2))
    assert [w["tp_workout_id"] for w in live] == ["w1", "w2"]
    assert any("deletions not reconciled" in line for line in lines)


@pytest.mark.db
async def test_tp_lands_future_workouts_and_the_watermark_stops_at_today(db, monkeypatch):
    ahead = (date.today() + timedelta(days=20)).isoformat()
    answers = _tp_calendar({"workouts": [{"id": "w9", "date": ahead}]})
    answers["tp_get_workout"] = lambda a: _detail("w9", ahead)
    assert (await _tp_sync(db, monkeypatch, answers, [])).ok
    day = date.fromisoformat(ahead)
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, day, day)] == ["w9"]
    assert repo.get_sync_state(db, "trainingpeaks").last_synced_date == date.today()


@pytest.mark.db
async def test_future_fitness_is_not_stored(db, monkeypatch):
    future = date.today() + timedelta(days=5)
    answers = _tp_calendar({"workouts": []})
    answers["tp_get_fitness"] = {
        "daily_data": [
            {"date": "2026-09-01", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5},
            {"date": future.isoformat(), "tss": 0, "ctl": 55, "atl": 30, "tsb": 25},
        ]
    }
    assert (await _tp_sync(db, monkeypatch, answers, [])).ok
    got = db.execute(
        "select metric_date from daily_metrics where metric_date in (%s, %s) order by 1",
        (date(2026, 9, 1), future),
    ).fetchall()
    assert [r["metric_date"] for r in got] == [date(2026, 9, 1)]
```

Move the two new imports (`timedelta`, `SYNC_AHEAD_DAYS`, `fetch_trainingpeaks`) into the file's import block; `ruff check --fix` sorts them.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_repo.py packages/tri-core/tests/test_sync_runner.py -q`
Expected: the new tests FAIL (`AttributeError: module 'tri_core.db.repo' has no attribute 'mark_missing_deleted'`, `ImportError: cannot import name 'SYNC_AHEAD_DAYS'`); every existing test still passes.

- [ ] **Step 3: Repository**

In `packages/tri-core/src/tri_core/db/repo.py`, replace:

```python
from collections.abc import Iterable
```

with:

```python
from collections.abc import Collection, Iterable
```

replace:

```python
    sql = (
        f"insert into workouts ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (tp_workout_id) do update set {updates}, synced_at = now()"
    )
```

with:

```python
    # A workout back in the listing is live again.
    sql = (
        f"insert into workouts ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (tp_workout_id) do update set {updates}, deleted_at = null, "
        "synced_at = now()"
    )
```

and replace:

```python
def list_workouts_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select * from workouts where workout_date between %s and %s "
        "order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()
```

with:

```python
def list_workouts_between(
    conn: Conn, start: date, end: date, *, include_deleted: bool = False
) -> list[dict[str, Any]]:
    live = "" if include_deleted else "and deleted_at is null "
    return conn.execute(
        f"select * from workouts where workout_date between %s and %s {live}"
        "order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def mark_missing_deleted(conn: Conn, start: date, end: date, seen_ids: Collection[str]) -> int:
    """Tombstone live workouts dated in [start, end] that the TrainingPeaks listing for that
    window did not return. Rows outside the window are never touched."""
    return conn.execute(
        "update workouts set deleted_at = now() "
        "where workout_date between %s and %s and deleted_at is null "
        "and tp_workout_id <> all(%s)",
        (start, end, list(seen_ids)),
    ).rowcount


def count_deleted(conn: Conn, ids: Collection[str]) -> int:
    row = conn.execute(
        "select count(*) as n from workouts where deleted_at is not null "
        "and tp_workout_id = any(%s)",
        (list(ids),),
    ).fetchone()
    return int(row["n"]) if row else 0
```

- [ ] **Step 4: The fetch keeps the listing**

In `packages/tri-core/src/tri_core/sync/trainingpeaks.py`, replace:

```python
@dataclass
class TPSnapshot:
    profile: AthleteProfileRow | None
    workouts: list[WorkoutRow] = field(default_factory=list)
    fitness: list[DailyMetricsRow] = field(default_factory=list)
```

with:

```python
@dataclass
class TPSnapshot:
    profile: AthleteProfileRow | None
    workouts: list[WorkoutRow] = field(default_factory=list)
    fitness: list[DailyMetricsRow] = field(default_factory=list)
    listed_ids: set[str] = field(default_factory=set)  # every id the listing returned
    listing_complete: bool = True  # False when any chunk's listing did not come back
```

replace:

```python
    ids: dict[str, None] = {}
    fitness: list[DailyMetricsRow] = []
    for s, e in date_chunks(start, end, TP_MAX_RANGE_DAYS):
        listed = await client.call_json(
            "tp_get_workouts",
            {"start_date": s.isoformat(), "end_date": e.isoformat(), "workout_filter": "all"},
        )
        for w in (listed or {}).get("workouts", []):
            ids.setdefault(str(w["id"]), None)
```

with:

```python
    ids: dict[str, None] = {}
    fitness: list[DailyMetricsRow] = []
    complete = True
    for s, e in date_chunks(start, end, TP_MAX_RANGE_DAYS):
        listed = await client.call_json(
            "tp_get_workouts",
            {"start_date": s.isoformat(), "end_date": e.isoformat(), "workout_filter": "all"},
        )
        chunk = listed.get("workouts") if isinstance(listed, dict) else None
        if not isinstance(chunk, list):
            complete = False
            log(f"trainingpeaks: {s} to {e}: no workout listing returned")
            chunk = []
        for w in chunk:
            ids.setdefault(str(w["id"]), None)
```

and replace:

```python
    return TPSnapshot(profile=profile, workouts=workouts, fitness=fitness)
```

with:

```python
    return TPSnapshot(
        profile=profile,
        workouts=workouts,
        fitness=fitness,
        listed_ids=set(ids),
        listing_complete=complete,
    )
```

- [ ] **Step 5: The runner**

In `packages/tri-core/src/tri_core/sync/runner.py`, replace:

```python
TP_FIRST_RUN_DAYS = 365
GARMIN_FIRST_RUN_DAYS = 60
OVERLAP_DAYS = 3
```

with:

```python
TP_FIRST_RUN_DAYS = 365
GARMIN_FIRST_RUN_DAYS = 60
OVERLAP_DAYS = 3
SYNC_AHEAD_DAYS = 28  # TrainingPeaks only: the 3-week planning and 14-day nutrition horizons
```

replace:

```python
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
```

with:

```python
def resolve_window(
    state: SyncState | None,
    since: date | None,
    full: bool,
    today: date,
    first_run_days: int,
    *,
    ahead_days: int = 0,
    overlap_days: int = OVERLAP_DAYS,
) -> tuple[date, date]:
    """[start, end] for one source. The start follows the watermark (the last day whose past is
    complete); the end is `today + ahead_days`, re-listed on every run and never watermarked."""
    end = today + timedelta(days=ahead_days)
    if since is not None:
        return since, end
    if full or state is None:
        return today - timedelta(days=first_run_days), end
    return state.last_synced_date - timedelta(days=overlap_days), end
```

replace:

```python
    rows = 0
    if snap.profile is not None:
        repo.upsert_athlete_profile(conn, snap.profile)
        rows += 1
    rows += repo.upsert_workouts(conn, snap.workouts)
    rows += repo.upsert_daily_metrics(conn, snap.fitness)
    return rows
```

with:

```python
    rows = 0
    if snap.profile is not None:
        repo.upsert_athlete_profile(conn, snap.profile)
        rows += 1
    restored = repo.count_deleted(conn, [w.tp_workout_id for w in snap.workouts])
    rows += repo.upsert_workouts(conn, snap.workouts)
    if snap.listing_complete:
        deleted = repo.mark_missing_deleted(conn, start, end, snap.listed_ids)
        log(f"trainingpeaks: {deleted} deleted, {restored} restored")
    else:
        log(f"trainingpeaks: {restored} restored; a listing failed, deletions not reconciled")
    # The forward window may carry projected fitness; daily_metrics holds only what happened.
    today = date.today()
    rows += repo.upsert_daily_metrics(conn, [f for f in snap.fitness if f.metric_date <= today])
    return rows
```

replace:

```python
    plan: list[tuple[str, int, Opener, SourceFn]] = [
        ("trainingpeaks", TP_FIRST_RUN_DAYS, open_tp, _sync_trainingpeaks),
        ("garmin", GARMIN_FIRST_RUN_DAYS, open_garmin, _sync_garmin),
    ]
```

with:

```python
    plan: list[tuple[str, int, int, Opener, SourceFn]] = [
        ("trainingpeaks", TP_FIRST_RUN_DAYS, SYNC_AHEAD_DAYS, open_tp, _sync_trainingpeaks),
        ("garmin", GARMIN_FIRST_RUN_DAYS, 0, open_garmin, _sync_garmin),
    ]
```

and replace:

```python
        for source, first_run_days, opener, fn in plan:
            if source not in sources:
                continue
            state = repo.get_sync_state(conn, source)
            start, end = resolve_window(state, since, full, today, first_run_days)
            log(f"== {source}: {start} to {end}")
            try:
                rows = await fn(conn, opener, start, end, log)
                repo.set_sync_state(conn, source, end, "ok", None)
```

with:

```python
        for source, first_run_days, ahead_days, opener, fn in plan:
            if source not in sources:
                continue
            state = repo.get_sync_state(conn, source)
            start, end = resolve_window(
                state, since, full, today, first_run_days, ahead_days=ahead_days
            )
            log(f"== {source}: {start} to {end}")
            try:
                rows = await fn(conn, opener, start, end, log)
                repo.set_sync_state(conn, source, min(end, today), "ok", None)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass, including `test_run_sync_end_to_end` and `test_run_sync_isolates_source_failure` unchanged.

- [ ] **Step 7: Definition of done, then commit**

```bash
git add packages/tri-core/src/tri_core/db/repo.py packages/tri-core/src/tri_core/sync/trainingpeaks.py packages/tri-core/src/tri_core/sync/runner.py packages/tri-core/tests/test_repo.py packages/tri-core/tests/test_sync_runner.py
git commit -m "feat(sync): TrainingPeaks syncs 28 days ahead and tombstones removed workouts"
```

---

### Task 3: Garmin activities are kept; bricks take two legs

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/repo.py` (imports; append after `set_garmin_match`)
- Modify: `packages/tri-core/src/tri_core/sync/match.py` (whole file)
- Modify: `packages/tri-core/src/tri_core/sync/runner.py:85-94`
- Test: `packages/tri-core/tests/test_sync_match.py` (rewrite one test, append), `packages/tri-core/tests/test_repo.py` (append), `packages/tri-core/tests/test_sync_runner.py` (append)

**Interfaces:**
- Consumes: `garmin_activities` (Task 1), `GarminActivityRow` (Task 1), `list_workouts_between` hiding deleted rows (Task 2).
- Produces:
  - `repo.upsert_garmin_activities(conn, rows: Iterable[GarminActivityRow]) -> int`; never overwrites `tp_workout_id`.
  - `repo.linked_activities(conn, start: date, end: date) -> dict[str, list[GarminActivityRow]]` keyed by `tp_workout_id`, activities whose local start day is in the window, in start order.
  - `repo.link_activity(conn, activity_id: str, tp_workout_id: str) -> None`; sets the FK and fills `workouts.garmin_activity_id`/`start_time_local` only when the workout has none.
  - `match_activities(workouts, activities, tolerance_sec=120, *, linked=None) -> list[tuple[str, GarminActivity]]`. `linked` maps workout id to its already-linked activities; those activities are never re-assigned.
  - `set_garmin_match` stays (tests use it); the runner no longer calls it.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-core/tests/test_sync_match.py`, replace:

```python
def test_brick_matches_any_sport_once():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    pairs = match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2], tolerance_sec=100000)
    assert len(pairs) == 1 and pairs[0][0] == "w1"
```

with:

```python
def test_brick_takes_both_legs():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1), ("w1", a2)]


def test_brick_second_leg_must_bring_the_total_within_tolerance():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 3000.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1)]


def test_brick_legs_are_different_sports():
    a1, a2 = _act("g1", "bike", 3, 2400.0), _act("g2", "bike", 3, 2400.0, hour=8)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2]) == [("w1", a1)]


def test_a_single_workout_is_preferred_to_a_brick_leg():
    run = _act("g1", "run", 3, 1800.0)
    workouts = [_wo("w1", "brick", 3, 5400), _wo("w2", "run", 3, 1790)]
    assert match_activities(workouts, [run]) == [("w2", run)]


def test_a_multisport_activity_fills_the_brick():
    whole, extra = _act("g1", "brick", 3, 4790.0), _act("g2", "run", 3, 600.0, hour=9)
    assert match_activities([_wo("w1", "brick", 3, 4800)], [whole, extra]) == [("w1", whole)]


def test_second_leg_on_a_later_sync():
    first, second = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    w = _wo("w1", "brick", 3, 4800, gid="g1")
    pairs = match_activities([w], [first, second], linked={"w1": [first]})
    assert pairs == [("w1", second)]


def test_a_linked_activity_is_never_reassigned():
    a = _act("g1", "run", 2, 2400.0)
    workouts = [_wo("w1", "run", 2, 2000, gid="g1"), _wo("w2", "run", 2, 2400)]
    assert match_activities(workouts, [a], linked={"w1": [a]}) == []
```

Append to `packages/tri-core/tests/test_repo.py`:

```python
from tri_core.db.models import GarminActivityRow


def _activity(id="g1", sport="bike", hour=6, dur=3600.0):
    return GarminActivityRow(
        id=id,
        type_key="cycling" if sport == "bike" else "running",
        sport=sport,
        start_time_local=datetime(2026, 9, 1, hour),
        duration_sec=dur,
        distance_m=None,
        avg_hr=None,
        name=None,
        raw={"id": id},
    )


def test_upsert_garmin_activities_keeps_the_link(db):
    repo.upsert_workouts(db, [_workout(sport="brick")])
    assert repo.upsert_garmin_activities(db, [_activity()]) == 1
    repo.link_activity(db, "g1", "w1")
    assert repo.upsert_garmin_activities(db, [_activity(dur=3700.0)]) == 1
    row = db.execute("select * from garmin_activities where id = 'g1'").fetchone()
    assert row["tp_workout_id"] == "w1" and float(row["duration_sec"]) == 3700.0


def test_link_activity_sets_the_first_leg_on_the_workout(db):
    repo.upsert_workouts(db, [_workout(sport="brick")])
    repo.upsert_garmin_activities(
        db, [_activity(), _activity(id="g2", sport="run", hour=7, dur=1200.0)]
    )
    repo.link_activity(db, "g1", "w1")
    repo.link_activity(db, "g2", "w1")
    w = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert w["garmin_activity_id"] == "g1" and w["start_time_local"] == datetime(2026, 9, 1, 6)
    legs = repo.linked_activities(db, date(2026, 9, 1), date(2026, 9, 1))
    assert [a.id for a in legs["w1"]] == ["g1", "g2"]
    assert legs["w1"][1].duration_sec == 1200.0
```

Move the `GarminActivityRow` import into the file's import block.

Append to `packages/tri-core/tests/test_sync_runner.py`:

```python
@pytest.mark.db
async def test_garmin_keeps_every_activity_and_a_brick_gets_both_legs(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))
    brick = {
        "id": "w1",
        "date": "2026-09-01",
        "sport": "Brick",
        "metrics": {"duration_actual": 4800 / 3600},
        "completed": True,
    }
    tp = _tp_answers()
    tp["tp_get_workout"] = brick
    garmin = _garmin_answers()
    garmin["get_activities_by_date"] = {
        "activities": [
            {"id": 1, "type": "cycling", "start_time": "2026-09-01 06:00:00", "duration_seconds": 3600.0},
            {"id": 2, "type": "running", "start_time": "2026-09-01 07:05:00", "duration_seconds": 1200.0},
            {"id": 3, "type": "walking", "start_time": "2026-09-01 18:00:00", "duration_seconds": 900.0},
        ],
        "has_more": False,
    }
    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        log=lambda m: None,
        open_tp=_factory(_Fake(tp)),
        open_garmin=_factory(_Fake(garmin)),
    )
    assert report.ok, report
    rows = db.execute(
        "select id, tp_workout_id from garmin_activities where id in ('1', '2', '3') order by id"
    ).fetchall()
    assert [(r["id"], r["tp_workout_id"]) for r in rows] == [("1", "w1"), ("2", "w1"), ("3", None)]
    w = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert w["garmin_activity_id"] == "1"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_sync_match.py packages/tri-core/tests/test_repo.py packages/tri-core/tests/test_sync_runner.py -q`
Expected: the new tests FAIL (`TypeError: match_activities() got an unexpected keyword argument 'linked'`, `AttributeError: ... 'upsert_garmin_activities'`, `test_brick_takes_both_legs` returns one pair).

- [ ] **Step 3: Repository**

In `packages/tri-core/src/tri_core/db/repo.py`, replace:

```python
from tri_core.db.models import AthleteProfileRow, DailyMetricsRow, SyncState, WorkoutRow
```

with:

```python
from tri_core.db.models import (
    AthleteProfileRow,
    DailyMetricsRow,
    GarminActivityRow,
    SyncState,
    WorkoutRow,
)
```

and replace:

```python
def list_workouts_between(
```

with:

```python
_ACTIVITY_COLS = [
    "id",
    "type_key",
    "sport",
    "start_time_local",
    "duration_sec",
    "distance_m",
    "avg_hr",
    "name",
    "raw",
]


def upsert_garmin_activities(conn: Conn, rows: Iterable[GarminActivityRow]) -> int:
    """Every fetched activity, matched or not. `tp_workout_id` is not in the column list, so a
    re-sync keeps the link."""
    cols = ", ".join(_ACTIVITY_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _ACTIVITY_COLS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _ACTIVITY_COLS if c != "id")
    sql = (
        f"insert into garmin_activities ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (id) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


def _num(v: Any) -> float | None:
    return float(v) if v is not None else None


def linked_activities(conn: Conn, start: date, end: date) -> dict[str, list[GarminActivityRow]]:
    rows = conn.execute(
        f"select tp_workout_id, {', '.join(_ACTIVITY_COLS)} from garmin_activities "
        "where tp_workout_id is not null and start_time_local::date between %s and %s "
        "order by start_time_local, id",
        (start, end),
    ).fetchall()
    out: dict[str, list[GarminActivityRow]] = {}
    for r in rows:
        out.setdefault(r["tp_workout_id"], []).append(
            GarminActivityRow(
                id=r["id"],
                type_key=r["type_key"],
                sport=r["sport"],
                start_time_local=r["start_time_local"],
                duration_sec=_num(r["duration_sec"]),
                distance_m=_num(r["distance_m"]),
                avg_hr=r["avg_hr"],
                name=r["name"],
                raw=r["raw"],
            )
        )
    return out


def link_activity(conn: Conn, activity_id: str, tp_workout_id: str) -> None:
    """Link one activity to its workout. The workout's own `garmin_activity_id` is the first
    linked leg and is never replaced, so `get_activity_splits` readers keep working."""
    conn.execute(
        "update garmin_activities set tp_workout_id = %s where id = %s",
        (tp_workout_id, activity_id),
    )
    conn.execute(
        "update workouts w set garmin_activity_id = a.id, start_time_local = a.start_time_local "
        "from garmin_activities a "
        "where a.id = %s and w.tp_workout_id = %s and w.garmin_activity_id is null",
        (activity_id, tp_workout_id),
    )


def list_workouts_between(
```

- [ ] **Step 4: Matching**

Replace the whole of `packages/tri-core/src/tri_core/sync/match.py` with:

```python
"""Pair Garmin activities with TrainingPeaks workouts on the same day. A `brick` workout takes two
legs of different sports (or one Garmin multisport activity); every other workout takes one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tri_core.sync.garmin import GarminActivity

BRICK = "brick"


def _sport_ok(workout_sport: str, activity_sport: str) -> bool:
    return workout_sport == BRICK or workout_sport == activity_sport


def _open(w: dict[str, Any], legs: Sequence[GarminActivity]) -> bool:
    if w["sport"] == BRICK:
        return len(legs) < 2 and all(leg.sport != BRICK for leg in legs)
    return not legs and not w.get("garmin_activity_id")


def _closest_single(
    singles: list[dict[str, Any]], act: GarminActivity, tolerance_sec: int
) -> dict[str, Any] | None:
    with_dur = [
        w for w in singles if w.get("actual_duration_sec") is not None and act.duration_sec is not None
    ]
    if with_dur:
        act_dur = float(act.duration_sec or 0)
        best = min(with_dur, key=lambda w: abs(float(w["actual_duration_sec"]) - act_dur))
        return best if abs(float(best["actual_duration_sec"]) - act_dur) <= tolerance_sec else None
    return singles[0] if len(singles) == 1 else None


def _brick_gap(
    w: dict[str, Any], legs: Sequence[GarminActivity], act: GarminActivity, tolerance_sec: int
) -> float | None:
    """How far the brick's legs would fall from its actual duration with `act` added, or None
    when `act` cannot be a leg. A first leg only has to leave room for the second."""
    if any(leg.sport == act.sport for leg in legs) or (act.sport == BRICK and legs):
        return None
    total = w.get("actual_duration_sec")
    durations = [leg.duration_sec for leg in legs] + [act.duration_sec]
    if total is None or any(d is None for d in durations):
        return 0.0
    summed = sum(float(d or 0) for d in durations)
    if legs or act.sport == BRICK:  # the brick is complete with this activity
        gap = abs(float(total) - summed)
        return gap if gap <= tolerance_sec else None
    return 0.0 if summed <= float(total) + tolerance_sec else None


def match_activities(
    workouts: list[dict[str, Any]],
    activities: list[GarminActivity],
    tolerance_sec: int = 120,
    *,
    linked: Mapping[str, Sequence[GarminActivity]] | None = None,
) -> list[tuple[str, GarminActivity]]:
    """New (workout id, activity) pairs. `linked` holds each workout's activities from earlier
    syncs; they count as that workout's legs and are never assigned again."""
    legs: dict[str, list[GarminActivity]] = {k: list(v) for k, v in (linked or {}).items()}
    taken = {a.id for acts in legs.values() for a in acts}
    candidates = [w for w in workouts if w.get("completed")]
    pairs: list[tuple[str, GarminActivity]] = []

    for act in sorted(activities, key=lambda a: a.start_time_local):
        if act.id in taken:
            continue
        day = act.start_time_local.date()
        same_day = [
            w
            for w in candidates
            if w["workout_date"] == day
            and _open(w, legs.get(w["tp_workout_id"], []))
            and _sport_ok(w["sport"], act.sport)
        ]
        singles = [w for w in same_day if w["sport"] != BRICK]
        chosen = _closest_single(singles, act, tolerance_sec) if singles else None
        if chosen is None:
            fits: list[tuple[float, dict[str, Any]]] = []
            for w in same_day:
                if w["sport"] != BRICK:
                    continue
                gap = _brick_gap(w, legs.get(w["tp_workout_id"], []), act, tolerance_sec)
                if gap is not None:
                    fits.append((gap, w))
            if fits:
                chosen = min(fits, key=lambda f: f[0])[1]
        if chosen is not None:
            legs.setdefault(chosen["tp_workout_id"], []).append(act)
            taken.add(act.id)
            pairs.append((chosen["tp_workout_id"], act))
    return pairs
```

- [ ] **Step 5: The runner**

In `packages/tri-core/src/tri_core/sync/runner.py`, replace:

```python
    rows = repo.upsert_daily_metrics(conn, snap.daily)
    workouts = repo.list_workouts_between(conn, start, end)
    pairs = match_activities(workouts, snap.activities)
    for tp_id, act in pairs:
        repo.set_garmin_match(conn, tp_id, act.id, act.start_time_local)
    log(f"garmin: matched {len(pairs)} of {len(snap.activities)} activities to TP workouts")
    return rows + len(pairs)
```

with:

```python
    rows = repo.upsert_daily_metrics(conn, snap.daily)
    rows += repo.upsert_garmin_activities(conn, snap.activities)
    workouts = repo.list_workouts_between(conn, start, end)
    linked = repo.linked_activities(conn, start, end)
    pairs = match_activities(workouts, snap.activities, linked=linked)
    for tp_id, act in pairs:
        repo.link_activity(conn, act.id, tp_id)
    n_linked = sum(len(v) for v in linked.values())
    log(
        f"garmin: {len(snap.activities)} activities; {len(pairs)} newly matched, "
        f"{n_linked} matched before"
    )
    return rows + len(pairs)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass, including `test_run_sync_end_to_end` (it still sees `garmin_activity_id == "555"` and `start_time_local == 06:00`).

- [ ] **Step 7: Definition of done, then commit**

```bash
git add packages/tri-core/src/tri_core/db/repo.py packages/tri-core/src/tri_core/sync/match.py packages/tri-core/src/tri_core/sync/runner.py packages/tri-core/tests/test_sync_match.py packages/tri-core/tests/test_repo.py packages/tri-core/tests/test_sync_runner.py
git commit -m "feat(sync): keep every Garmin activity; a brick takes both legs"
```

---

### Task 4: Readers hide deleted workouts; `SCHEMA_DOC`

**Files:**
- Create: `packages/tri-core/src/tri_core/testing/rows.py`
- Modify: `packages/tri-core/src/tri_core/testing/__init__.py`
- Modify: `packages/tri-core/src/tri_core/db/sql_tool.py:24-70` (`SCHEMA_DOC` only)
- Modify: `packages/tri-analyze/src/tri_analyze/repo.py:33-37`
- Modify: `packages/tri-coach/src/tri_coach/context.py:115-119`
- Modify: `packages/tri-nutrition/src/tri_nutrition/plan_loader.py:96-101, 119-130`
- Modify: `packages/tri-planning/src/tri_planning/repo.py` (`recent_sessions`)
- Modify: `packages/tri-wellness/src/tri_wellness/labs/training_context.py:27-31`
- Test: `packages/tri-core/tests/test_sql_tool.py`, `packages/tri-analyze/tests/test_repo.py`, `packages/tri-coach/tests/test_context.py`, `packages/tri-nutrition/tests/test_plan_loader.py`, `packages/tri-planning/tests/test_repo.py`, `packages/tri-wellness/tests/test_training_context.py` (append to each)

**Interfaces:**
- Consumes: `repo.mark_missing_deleted`, `list_workouts_between` (Task 2).
- Produces: `tri_core.testing.workout_row(tp_workout_id: str, workout_date: date, **over) -> WorkoutRow` (a completed 1 h bike with 50 TSS unless overridden).

**Note for the implementer:** `tri-web`'s `today.py` reads through `list_workouts_between`, which hides deleted rows by default (Task 2 tests it), so it has no edit and no test here. `tri_planning/tools/tp_read.py` keeps reading TrainingPeaks live (spec §4.3) and has no edit. The example SQL in `tri_nutrition/prompts/checkin.py` and `tri_wellness/tools/findings.py` is left alone: both select completed or commented sessions, which a deletion does not produce, and `SCHEMA_DOC` (in every agent's SQL tool) carries the rule.

- [ ] **Step 1: The shared row builder**

Create `packages/tri-core/src/tri_core/testing/rows.py`:

```python
"""Row builders for tests that seed `workouts` directly."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_core.db.models import WorkoutRow


def workout_row(tp_workout_id: str, workout_date: date, **over: Any) -> WorkoutRow:
    """A completed one-hour bike, 50 TSS, planned and actual alike; override any field."""
    base: dict[str, Any] = dict(
        tp_workout_id=tp_workout_id,
        workout_date=workout_date,
        sport="bike",
        sport_raw="Bike",
        title=f"ride {tp_workout_id}",
        description=None,
        completed=True,
        planned_duration_sec=3600,
        planned_distance_m=None,
        planned_tss=50.0,
        planned_if=None,
        actual_duration_sec=3600,
        actual_distance_m=None,
        actual_tss=50.0,
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
    base.update(over)
    return WorkoutRow(**base)
```

Replace the whole of `packages/tri-core/src/tri_core/testing/__init__.py` with:

```python
"""Test doubles and fixtures shared by every package's tests."""

from tri_core.testing.fakes import ScriptedChatModel, tool_call
from tri_core.testing.rows import workout_row

__all__ = ["ScriptedChatModel", "tool_call", "workout_row"]
```

- [ ] **Step 2: Write the failing tests**

Every test below seeds a live workout `keep` and a workout `gone` on the same day, tombstones `gone` with `mark_missing_deleted`, and asserts the reader sees only `keep`. Add `from tri_core.testing import workout_row` to each file's imports. Add `from tri_core.db import repo as crepo` to the coach, nutrition, planning and wellness test files (their `repo`, where present, is the package's own); `tri-analyze/tests/test_repo.py` already imports `from tri_core.db import repo` and its test uses that. `ruff check --fix` sorts the imports.

Append to `packages/tri-core/tests/test_sql_tool.py`:

```python
def test_schema_doc_documents_tombstones_and_activities():
    assert "deleted_at" in SCHEMA_DOC and "garmin_activities" in SCHEMA_DOC
    assert "status" in SCHEMA_DOC.split("plan_changes:")[1]
    examples = SCHEMA_DOC.split("Examples:")[1]
    for query in examples.split("--")[1:]:
        if "from workouts" in query:
            assert "deleted_at is null" in query, query
```

Append to `packages/tri-analyze/tests/test_repo.py`:

```python
@pytest.mark.db
def test_context_skips_deleted_workouts(db):
    repo.upsert_workouts(db, [workout_row("keep", TODAY), workout_row("gone", TODAY)])
    repo.mark_missing_deleted(db, TODAY, TODAY, {"keep"})
    ctx = load_athlete_context(db, TODAY)
    assert [w["title"] for w in ctx.recent_workouts] == ["ride keep"]
```

Append to `packages/tri-coach/tests/test_context.py`:

```python
async def test_week_hours_skip_deleted_workouts(nocommit, mem_store):
    crepo.upsert_workouts(
        nocommit,
        [workout_row("keep", MONDAY), workout_row("gone", MONDAY, actual_duration_sec=7200)],
    )
    crepo.mark_missing_deleted(nocommit, MONDAY, MONDAY, {"keep"})
    ctx = await load_context(nocommit, mem_store, MONDAY, None)
    assert ctx.actual_hours == 1.0
```

Append to `packages/tri-nutrition/tests/test_plan_loader.py`:

```python
def test_loaders_skip_deleted_workouts(pdb):
    later = MONDAY + timedelta(days=1)
    crepo.upsert_workouts(
        pdb,
        [
            workout_row("keep", later, completed=False, actual_duration_sec=None),
            workout_row("gone", later, completed=False, actual_duration_sec=None),
        ],
    )
    crepo.mark_missing_deleted(pdb, later, later, {"keep"})
    assert [w["tp_workout_id"] for w in L._planned_workouts(pdb, MONDAY, later)] == ["keep"]
    assert [w["tp_workout_id"] for w in L._workouts_between(pdb, later, later)] == ["keep"]
```

Append to `packages/tri-planning/tests/test_repo.py`:

```python
def test_recent_sessions_skip_deleted_workouts(pdb):
    day = date(2026, 9, 15)
    crepo.upsert_workouts(pdb, [workout_row("keep", day), workout_row("gone", day)])
    crepo.mark_missing_deleted(pdb, day, day, {"keep"})
    assert [s["title"] for s in repo.recent_sessions(pdb, day, day)] == ["ride keep"]
```

(`date` is already imported there; if it is not, add `from datetime import date`.)

Append to `packages/tri-wellness/tests/test_training_context.py`:

```python
def test_sessions_skip_deleted_workouts(db):
    crepo.upsert_workouts(db, [workout_row("keep", day(-1)), workout_row("gone", day(-1))])
    crepo.mark_missing_deleted(db, day(-1), day(-1), {"keep"})
    assert [s["title"] for s in load_training_context(db, D).last_sessions] == ["ride keep"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_sql_tool.py packages/tri-analyze/tests/test_repo.py packages/tri-coach/tests/test_context.py packages/tri-nutrition/tests/test_plan_loader.py packages/tri-planning/tests/test_repo.py packages/tri-wellness/tests/test_training_context.py -q`
Expected: the six new tests FAIL, each seeing `gone` (or 3.0 hours in the coach test); the rest pass.

- [ ] **Step 4: Filter every reader**

`packages/tri-analyze/src/tri_analyze/repo.py`, replace:

```python
        "planned_duration_sec, actual_duration_sec from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
```

with:

```python
        "planned_duration_sec, actual_duration_sec from workouts "
        "where workout_date between %s and %s and deleted_at is null "
        "order by workout_date, tp_workout_id",
```

`packages/tri-coach/src/tri_coach/context.py`, replace:

```python
        "select coalesce(sum(actual_duration_sec), 0) as sec from workouts "
        "where completed and workout_date between %s and %s",
```

with:

```python
        "select coalesce(sum(actual_duration_sec), 0) as sec from workouts "
        "where completed and deleted_at is null and workout_date between %s and %s",
```

`packages/tri-nutrition/src/tri_nutrition/plan_loader.py`, replace:

```python
        "select tp_workout_id, workout_date, sport, title, completed from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
```

with:

```python
        "select tp_workout_id, workout_date, sport, title, completed from workouts "
        "where workout_date between %s and %s and deleted_at is null "
        "order by workout_date, tp_workout_id",
```

and replace:

```python
        "where (not completed or workout_date = %s) and workout_date between %s and %s "
```

with:

```python
        "where (not completed or workout_date = %s) and workout_date between %s and %s "
        "and deleted_at is null "
```

`packages/tri-planning/src/tri_planning/repo.py`, replace:

```python
        "planned_duration_sec, actual_duration_sec, rpe, feeling from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
```

with:

```python
        "planned_duration_sec, actual_duration_sec, rpe, feeling from workouts "
        "where workout_date between %s and %s and deleted_at is null "
        "order by workout_date, tp_workout_id",
```

`packages/tri-wellness/src/tri_wellness/labs/training_context.py`, replace:

```python
        where completed and workout_date between %s and %s
```

with:

```python
        where completed and deleted_at is null and workout_date between %s and %s
```

- [ ] **Step 5: `SCHEMA_DOC`**

In `packages/tri-core/src/tri_core/db/sql_tool.py`, replace:

```python
workouts (one row per TrainingPeaks workout; planned and actual on the same row):
```

with:

```python
workouts (one row per TrainingPeaks workout; planned and actual on the same row; planned rows
  run 28 days ahead of today):
```

replace:

```python
  garmin_activity_id text (use with get_activity_splits / get_activity for lap detail),
  start_time_local timestamp (from Garmin), raw jsonb (full TP payload).
```

with:

```python
  garmin_activity_id text (the first matched Garmin activity; use with get_activity_splits /
  get_activity for lap detail), start_time_local timestamp (from Garmin),
  raw jsonb (full TP payload),
  deleted_at timestamptz (a workout removed from TrainingPeaks; filter `deleted_at is null`
  unless asked about removals).

garmin_activities (every synced Garmin activity, matched or not; a brick has two):
  id text PK, tp_workout_id text (null when no workout matched), sport, type_key,
  start_time_local timestamp, duration_sec, distance_m, avg_hr, name, raw jsonb.
```

replace:

```python
plan_changes: plan_id, thread_id, operation, tp_workout_id, workout_date, payload jsonb,
  result jsonb, reason, applied_at  (audit of every calendar write; a workout is
  agent-authored iff its id is here).
```

with:

```python
plan_changes: plan_id, thread_id, operation, tp_workout_id, workout_date, payload jsonb,
  result jsonb, reason, applied_at, status ('pending'|'applied'|'failed'), error  (audit of
  every calendar write; a workout is agent-authored iff its id is here with status 'applied').
```

and replace:

```python
  -- yesterday's completed sessions
  select workout_date, sport, title, actual_duration_sec, actual_tss, avg_hr, garmin_activity_id
  from workouts where completed and workout_date = current_date - 1;
  -- planned vs actual this week
  select workout_date, sport, title, planned_tss, actual_tss, planned_duration_sec,
         actual_duration_sec
  from workouts where workout_date >= date_trunc('week', current_date) order by 1;
  -- weekly run volume for the last 12 weeks
  select date_trunc('week', workout_date)::date as wk, round(sum(actual_distance_m)/1000, 1) as km,
         sum(actual_duration_sec)/3600.0 as hours
  from workouts where sport='run' and completed and workout_date >= current_date - 84
  group by 1 order by 1;
```

with:

```python
  -- yesterday's completed sessions
  select workout_date, sport, title, actual_duration_sec, actual_tss, avg_hr, garmin_activity_id
  from workouts where completed and deleted_at is null and workout_date = current_date - 1;
  -- planned vs actual this week
  select workout_date, sport, title, planned_tss, actual_tss, planned_duration_sec,
         actual_duration_sec
  from workouts where deleted_at is null and workout_date >= date_trunc('week', current_date)
  order by 1;
  -- weekly run volume for the last 12 weeks
  select date_trunc('week', workout_date)::date as wk, round(sum(actual_distance_m)/1000, 1) as km,
         sum(actual_duration_sec)/3600.0 as hours
  from workouts where sport='run' and completed and deleted_at is null
    and workout_date >= current_date - 84
  group by 1 order by 1;
  -- both legs of yesterday's brick
  select a.start_time_local, a.sport, a.duration_sec, a.id
  from garmin_activities a join workouts w on w.tp_workout_id = a.tp_workout_id
  where w.sport = 'brick' and w.deleted_at is null and w.workout_date = current_date - 1
  order by 1;
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q`
Expected: all pass. If a prompt-snapshot or eval-fixture test fails because `SCHEMA_DOC` changed, that is a stop condition: report it with the failing test name.

- [ ] **Step 7: Definition of done, then commit**

```bash
git add packages/tri-core/src/tri_core/testing packages/tri-core/src/tri_core/db/sql_tool.py packages/tri-analyze/src/tri_analyze/repo.py packages/tri-coach/src/tri_coach/context.py packages/tri-nutrition/src/tri_nutrition/plan_loader.py packages/tri-planning/src/tri_planning/repo.py packages/tri-wellness/src/tri_wellness/labs/training_context.py packages/tri-core/tests/test_sql_tool.py packages/tri-analyze/tests/test_repo.py packages/tri-coach/tests/test_context.py packages/tri-nutrition/tests/test_plan_loader.py packages/tri-planning/tests/test_repo.py packages/tri-wellness/tests/test_training_context.py
git commit -m "feat(readers): every workouts reader hides tombstoned rows; SCHEMA_DOC documents them"
```

---

### Task 5: `recorded_write`

**Files:**
- Create: `packages/tri-core/src/tri_core/db/writes.py`
- Test: `packages/tri-core/tests/test_writes.py`

**Interfaces:**
- Consumes: `plan_changes.status`/`error` (Task 1).
- Produces (`tri_core.db.writes`):
  - `ChangeTable = Literal["plan_changes", "nutrition_changes"]`
  - `ConnectFactory = Callable[[], AbstractContextManager[Conn]]`
  - `PENDING_GRACE_SEC = 60`
  - `@dataclass(frozen=True) class Recorded: row_id: int; result: Any`
  - `async def recorded_write(conn_factory, *, table, insert_pending: Callable[[Conn], int], call: Callable[[], Awaitable[Any]], mark_applied: Callable[[Conn, int, Any], None]) -> Recorded`
  - `def mark_failed(conn, table: ChangeTable, row_id: int, error: str) -> None`
  - `def pending_rows(conn, table: ChangeTable, *, older_than_sec: int = PENDING_GRACE_SEC) -> list[dict[str, Any]]` (oldest first)

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-core/tests/test_writes.py`:

```python
import contextlib

import pytest
from psycopg.types.json import Jsonb

from tri_core.db.writes import Recorded, mark_failed, pending_rows, recorded_write

pytestmark = pytest.mark.db


class _Open:
    """The rolled-back test connection behind a factory; commit is a no-op."""

    def __init__(self, conn):
        self._c = conn

    def commit(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)


def _factory(db):
    wrapped = _Open(db)
    return lambda: contextlib.nullcontext(wrapped)


def _insert(conn):
    return conn.execute(
        "insert into plan_changes (thread_id, operation, payload, status) "
        "values ('t', 'create', '{}'::jsonb, 'pending') returning id"
    ).fetchone()["id"]


def _mark(conn, row_id, result):
    conn.execute(
        "update plan_changes set status = 'applied', result = %s where id = %s",
        (Jsonb(result), row_id),
    )


def _row(db, row_id):
    return db.execute(
        "select status, error, result from plan_changes where id = %s", (row_id,)
    ).fetchone()


async def test_marks_applied(db):
    seen: list[int] = []

    async def call():
        seen.append(_row(db, rid_holder[0])["status"] == "pending")
        return {"workout_id": 9}

    rid_holder: list[int] = []

    def insert(conn):
        rid_holder.append(_insert(conn))
        return rid_holder[0]

    rec = await recorded_write(
        _factory(db), table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
    )
    assert rec == Recorded(row_id=rid_holder[0], result={"workout_id": 9})
    assert seen == [True]  # the row existed, pending, before the call
    assert _row(db, rec.row_id)["status"] == "applied"


async def test_marks_failed_and_reraises(db):
    ids: list[int] = []

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await recorded_write(
            _factory(db), table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
        )
    row = _row(db, ids[0])
    assert row["status"] == "failed" and row["error"] == "RuntimeError: boom"


async def test_leaves_pending_when_mark_applied_raises(db):
    ids: list[int] = []

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        return {"ok": True}

    def broken(conn, row_id, result):
        raise RuntimeError("db went away")

    with pytest.raises(RuntimeError, match="db went away"):
        await recorded_write(
            _factory(db), table="plan_changes", insert_pending=insert, call=call, mark_applied=broken
        )
    assert _row(db, ids[0])["status"] == "pending"


async def test_the_call_error_survives_a_failed_failure_mark(db):
    ids: list[int] = []
    opens = {"n": 0}
    wrapped = _Open(db)

    def factory():
        opens["n"] += 1
        if opens["n"] > 1:
            raise OSError("database unreachable")
        return contextlib.nullcontext(wrapped)

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        raise RuntimeError("TP said no")

    with pytest.raises(RuntimeError, match="TP said no") as info:
        await recorded_write(
            factory, table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
        )
    assert any("left pending" in n for n in info.value.__notes__)
    assert _row(db, ids[0])["status"] == "pending"


def test_pending_rows_skips_young_and_settled_rows(db):
    old = _insert(db)
    young = _insert(db)
    done = _insert(db)
    db.execute(
        "update plan_changes set applied_at = now() - interval '5 minutes' where id in (%s, %s)",
        (old, done),
    )
    mark_failed(db, "plan_changes", done, "x")
    assert [r["id"] for r in pending_rows(db, "plan_changes")] == [old]
    assert young not in [r["id"] for r in pending_rows(db, "plan_changes")]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_writes.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'tri_core.db.writes'`.

- [ ] **Step 3: Write the module**

Create `packages/tri-core/src/tri_core/db/writes.py`:

```python
"""Record-before-write for every TrainingPeaks and Garmin write. The change row is inserted as
`pending` and committed before the call, then set to `applied` or `failed`. A database failure
after a successful call therefore leaves a `pending` row the next apply reconciles, instead of
a write nobody recorded."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import sql

from tri_core.db.repo import Conn

ChangeTable = Literal["plan_changes", "nutrition_changes"]
ConnectFactory = Callable[[], AbstractContextManager[Conn]]
PENDING_GRACE_SEC = 60  # a younger pending row may belong to a write still in flight


@dataclass(frozen=True)
class Recorded:
    row_id: int
    result: Any


def mark_failed(conn: Conn, table: ChangeTable, row_id: int, error: str) -> None:
    conn.execute(
        sql.SQL("update {} set status = 'failed', error = %s where id = %s").format(
            sql.Identifier(table)
        ),
        (error[:2000], row_id),
    )


def pending_rows(
    conn: Conn, table: ChangeTable, *, older_than_sec: int = PENDING_GRACE_SEC
) -> list[dict[str, Any]]:
    return conn.execute(
        sql.SQL(
            "select * from {} where status = 'pending' "
            "and applied_at < now() - make_interval(secs => %s) order by id"
        ).format(sql.Identifier(table)),
        (older_than_sec,),
    ).fetchall()


async def recorded_write(
    conn_factory: ConnectFactory,
    *,
    table: ChangeTable,
    insert_pending: Callable[[Conn], int],
    call: Callable[[], Awaitable[Any]],
    mark_applied: Callable[[Conn, int, Any], None],
) -> Recorded:
    """Insert the pending row and commit; make the call; mark the row applied (or failed, and
    re-raise). If `mark_applied` raises, the row stays pending and the exception propagates."""
    with conn_factory() as conn:
        row_id = insert_pending(conn)
        conn.commit()
    try:
        result = await call()
    except Exception as exc:
        try:
            with conn_factory() as conn:
                mark_failed(conn, table, row_id, f"{type(exc).__name__}: {exc}")
                conn.commit()
        except Exception as db_exc:  # the server's error is the one the caller must see
            exc.add_note(f"{table} row {row_id} left pending: {type(db_exc).__name__}: {db_exc}")
        raise
    with conn_factory() as conn:
        mark_applied(conn, row_id, result)
        conn.commit()
    return Recorded(row_id=row_id, result=result)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-core/tests/test_writes.py -v`
Expected: 5 passed.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-core/src/tri_core/db/writes.py packages/tri-core/tests/test_writes.py
git commit -m "feat(core): recorded_write, a pending row before every external write"
```

---

### Task 6: Planning apply records before writing and reconciles pending rows

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/repo.py` (imports; `insert_change` neighbourhood; `owned_workout_ids`; `owned_workouts`)
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/apply.py:5-20, 22-24, 33-51, 76-128`
- Test: `packages/tri-planning/tests/test_apply_node.py` (edit one test, append)

**Interfaces:**
- Consumes: `recorded_write`, `mark_failed`, `pending_rows` (Task 5).
- Produces:
  - `repo.insert_pending_change(conn, plan_id: int | None, thread_id: str, change: CalendarChange) -> int`
  - `repo.mark_change_applied(conn, row_id: int, *, tp_workout_id: str | None, result: dict[str, Any] | None) -> None`
  - `repo.pending_changes(conn) -> list[dict[str, Any]]` (`pending` rows older than 60 s)
  - `repo.recorded_create_ids(conn) -> set[str]` (ids from applied `create`/`apply_plan` rows)
  - `owned_workout_ids` and `owned_workouts` count only `status = 'applied'` rows.
  - `apply.reconcile_pending(deps: GraphDeps) -> list[str]` (one report line per row)
  - `ApplyResult.reconciled: list[str]` (default empty), shown in `report()` as `  reconciled: ...` lines.
  - Error texts: `PENDING_NOT_FOUND = "not found on TrainingPeaks after a pending write"`, `PENDING_UNVERIFIABLE = "could not be verified on TrainingPeaks after a pending write; check the calendar"`, `PENDING_AMBIGUOUS = "more than one matching workout on TrainingPeaks; not claimed"`.

**Reconciliation rules** (one `tp_get_workouts` listing per row, for one day, `workout_filter: "all"`):
- `create`: the day is `workout.date`. Exactly one listed workout with the payload's title, the TrainingPeaks sport label for its sport (`TP_SPORT`), and an id not already in `recorded_create_ids` → `applied` with that id, and its week is marked written if it is designed. None → `failed` (`PENDING_NOT_FOUND`). More than one → `failed` (`PENDING_AMBIGUOUS`).
- `update`: listed on `workout.date` with the row's id and the payload's title → `applied`; else `failed`.
- `move`: listed on `new_date` with the row's id → `applied`; else `failed`.
- `delete` with a `workout_date`: the id absent from that day → `applied`; present → `failed`.
- Anything else (`apply_plan`, `create_event`, a delete without a date) → `failed` (`PENDING_UNVERIFIABLE`).
- An `McpToolError` during reconciliation stops it: the remaining rows stay `pending`, one line says so, and the apply continues with the new changes (spec §6).

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_apply_node.py`, replace:

```python
    assert len(repo.owned_workout_ids(nocommit, pid)) == 1
    row = nocommit.execute(
        "select count(*) as n from plan_changes where plan_id = %s", (pid,)
    ).fetchone()
    assert row["n"] == 1
```

with:

```python
    assert len(repo.owned_workout_ids(nocommit, pid)) == 1
    rows = nocommit.execute(
        "select status, error from plan_changes where plan_id = %s order by id", (pid,)
    ).fetchall()
    assert [r["status"] for r in rows] == ["applied", "failed"]
    assert "boom" in rows[1]["error"]
```

Append to the same file:

```python
def _backdate(conn, row_id):
    conn.execute(
        "update plan_changes set applied_at = now() - interval '5 minutes' where id = %s", (row_id,)
    )


def _listing(*items):
    return {"tp_get_workouts": {"workouts": list(items), "count": len(items)}}


def _listed(wid, title="Ride", sport="Bike", day=MONDAY):
    return {"id": wid, "date": day.isoformat(), "title": title, "sport": sport}


def _status(conn, row_id):
    return conn.execute(
        "select status, error, tp_workout_id from plan_changes where id = %s", (row_id,)
    ).fetchone()


async def test_a_pending_create_found_on_tp_is_recorded_as_applied(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555")))
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    assert tp.calls == [
        (
            "tp_get_workouts",
            {"start_date": "2026-09-14", "end_date": "2026-09-14", "workout_filter": "all"},
        )
    ]
    assert _status(nocommit, rid)["status"] == "applied"
    assert repo.owned_workout_ids(nocommit, pid) == {"555"}
    assert "reconciled: create" in r.report(0) and "recorded as applied" in r.report(0)


async def test_a_pending_create_missing_on_tp_is_failed(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555", title="Something else")))
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    row = _status(nocommit, rid)
    assert row["status"] == "failed" and row["error"] == "not found on TrainingPeaks after a pending write"
    assert repo.owned_workout_ids(nocommit, pid) == set()
    assert "not found on TrainingPeaks" in r.report(0)


async def test_an_ambiguous_pending_create_is_failed(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555"), _listed("athletes-own")))
    await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    row = _status(nocommit, rid)
    assert row["status"] == "failed" and "more than one" in row["error"]
    assert repo.owned_workout_ids(nocommit, pid) == set()


async def test_a_young_pending_row_is_left_alone(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    tp = FakeTp(responses=_listing(_listed("555")))
    await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    assert tp.calls == [] and _status(nocommit, rid)["status"] == "pending"


async def test_unreachable_tp_leaves_rows_pending_and_the_apply_goes_on(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(fail_on_call=1)
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp),
        [create(1, "New")],
        "t",
        plan_id=pid,
        goal_id=gid,
    )
    assert _status(nocommit, rid)["status"] == "pending"
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_create_workout"]
    assert [c.workout.title for c in r.applied] == ["New"]
    assert "left pending" in r.report(1)


async def test_ownership_counts_applied_rows_only(nocommit, make_deps):
    gid, pid = seed(nocommit)
    repo.insert_change(nocommit, pid, "t", create(0), tp_workout_id="w1", result={})
    drop = CalendarChange(op="delete", tp_workout_id="w1", workout_date=MONDAY, reason="drop")
    repo.insert_pending_change(nocommit, pid, "t", drop)
    assert repo.owned_workout_ids(nocommit, pid) == {"w1"}
    assert [w["tp_workout_id"] for w in repo.owned_workouts(nocommit, pid)] == ["w1"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py -q`
Expected: the new tests FAIL with `AttributeError: module 'tri_planning.repo' has no attribute 'insert_pending_change'`; `test_mid_batch_failure_keeps_remainder_pending` FAILS with `['applied'] == ['applied', 'failed']`.

- [ ] **Step 3: Repository**

In `packages/tri-planning/src/tri_planning/repo.py`, replace:

```python
from tri_core.db.repo import Conn
```

with:

```python
from tri_core.db.repo import Conn
from tri_core.db.writes import pending_rows
```

replace:

```python
def owned_workout_ids(conn: Conn, plan_id: int) -> set[str]:
    rows = conn.execute(
        "select operation, tp_workout_id from plan_changes "
        "where plan_id = %s and tp_workout_id is not null",
```

with:

```python
def insert_pending_change(
    conn: Conn, plan_id: int | None, thread_id: str, change: CalendarChange
) -> int:
    """The row for a TrainingPeaks call about to be made; `mark_change_applied` settles it."""
    row = conn.execute(
        """
        insert into plan_changes (plan_id, thread_id, operation, tp_workout_id, workout_date,
            payload, reason, status)
        values (%s, %s, %s, %s, %s, %s, %s, 'pending') returning id
        """,
        (
            plan_id,
            thread_id,
            change.op,
            change.tp_workout_id,
            change.workout_date,
            Jsonb(change.model_dump(mode="json")),
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def mark_change_applied(
    conn: Conn, row_id: int, *, tp_workout_id: str | None, result: dict[str, Any] | None
) -> None:
    conn.execute(
        "update plan_changes set status = 'applied', tp_workout_id = %s, result = %s, "
        "applied_at = now(), error = null where id = %s",
        (tp_workout_id, Jsonb(result) if result is not None else None, row_id),
    )


def pending_changes(conn: Conn) -> list[dict[str, Any]]:
    return pending_rows(conn, "plan_changes")


def recorded_create_ids(conn: Conn) -> set[str]:
    rows = conn.execute(
        "select tp_workout_id from plan_changes where status = 'applied' "
        "and operation in ('create', 'apply_plan') and tp_workout_id is not null"
    ).fetchall()
    return {r["tp_workout_id"] for r in rows}


def owned_workout_ids(conn: Conn, plan_id: int) -> set[str]:
    rows = conn.execute(
        "select operation, tp_workout_id from plan_changes "
        "where plan_id = %s and tp_workout_id is not null and status = 'applied'",
```

and replace:

```python
        "select operation, tp_workout_id, workout_date, payload from plan_changes "
        "where plan_id = %s and tp_workout_id is not null order by applied_at, id",
```

with:

```python
        "select operation, tp_workout_id, workout_date, payload from plan_changes "
        "where plan_id = %s and tp_workout_id is not null and status = 'applied' "
        "order by applied_at, id",
```

- [ ] **Step 4: The apply node**

In `packages/tri-planning/src/tri_planning/graph/nodes/apply.py`, replace:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.mcp.client import McpToolError
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call
```

with:

```python
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.repo import Conn
from tri_core.db.writes import mark_failed, recorded_write
from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import TP_SPORT, result_workout_id, to_tp_call
```

replace:

```python
TP_UNAVAILABLE = "TrainingPeaks server unavailable; nothing applied, change set left pending."
```

with:

```python
TP_UNAVAILABLE = "TrainingPeaks server unavailable; nothing applied, change set left pending."
PENDING_NOT_FOUND = "not found on TrainingPeaks after a pending write"
PENDING_UNVERIFIABLE = (
    "could not be verified on TrainingPeaks after a pending write; check the calendar"
)
PENDING_AMBIGUOUS = "more than one matching workout on TrainingPeaks; not claimed"
```

replace:

```python
    tp_plan_applied: bool
    sessions_changed: bool  # any create/update/delete/move went through

    def report(self, total: int) -> str:
        lines = [f"TrainingPeaks: applied {len(self.applied)} of {total} changes."]
        lines += [f"  skipped: {s}" for s in self.skipped]
```

with:

```python
    tp_plan_applied: bool
    sessions_changed: bool  # any create/update/delete/move went through
    reconciled: list[str] = field(default_factory=list)  # pending rows settled before the batch

    def report(self, total: int) -> str:
        lines = [f"TrainingPeaks: applied {len(self.applied)} of {total} changes."]
        lines += [f"  reconciled: {s}" for s in self.reconciled]
        lines += [f"  skipped: {s}" for s in self.skipped]
```

replace:

```python
async def apply_changes(
    deps: GraphDeps,
```

with:

```python
Verdict = Literal["applied", "missing", "ambiguous", "unverifiable"]


async def _day_listing(tp: ToolCaller, day: str) -> list[dict[str, Any]]:
    result = await tp.call_json(
        "tp_get_workouts", {"start_date": day, "end_date": day, "workout_filter": "all"}
    )
    items = result.get("workouts") if isinstance(result, dict) else None
    return [w for w in items if isinstance(w, dict)] if isinstance(items, list) else []


async def _verify(
    tp: ToolCaller, change: CalendarChange, recorded: set[str]
) -> tuple[Verdict, str | None]:
    """Whether a pending change is on TrainingPeaks, and the workout id it concerns."""
    if change.op == "create" and change.workout is not None:
        w = change.workout
        hits = [
            str(item.get("id"))
            for item in await _day_listing(tp, w.date.isoformat())
            if item.get("title") == w.title
            and item.get("sport") == TP_SPORT[w.sport]
            and str(item.get("id")) not in recorded
        ]
        if len(hits) > 1:
            return "ambiguous", None
        if hits:
            return "applied", hits[0]
        return "missing", None
    wid = change.tp_workout_id
    if change.op == "update" and change.workout is not None and wid:
        items = await _day_listing(tp, change.workout.date.isoformat())
        on_tp = any(
            str(i.get("id")) == wid and i.get("title") == change.workout.title for i in items
        )
    elif change.op == "move" and change.new_date is not None and wid:
        items = await _day_listing(tp, change.new_date.isoformat())
        on_tp = any(str(i.get("id")) == wid for i in items)
    elif change.op == "delete" and change.workout_date is not None and wid:
        items = await _day_listing(tp, change.workout_date.isoformat())
        on_tp = all(str(i.get("id")) != wid for i in items)  # a delete is done when it is gone
    else:
        return "unverifiable", None
    if on_tp:
        return "applied", wid
    return "missing", wid


def _mark_week_written(conn: Conn, plan_id: int | None, change: CalendarChange) -> None:
    if plan_id is None or change.op != "create" or change.workout_date is None:
        return
    week = week_monday(change.workout_date)
    if any(w.week_start == week and w.designed for w in repo.list_weeks(conn, plan_id)):
        repo.mark_weeks_written(conn, plan_id, [week])


async def reconcile_pending(deps: GraphDeps) -> list[str]:
    """Settle `plan_changes` rows an earlier apply left `pending` (the call may have gone
    through while its record did not): `applied` when TrainingPeaks shows the change, else
    `failed`. Returns one report line per row settled or left."""
    tp = deps.tp
    assert tp is not None
    with deps.connect() as conn:
        rows = repo.pending_changes(conn)
        recorded = repo.recorded_create_ids(conn)
    lines: list[str] = []
    for i, row in enumerate(rows):
        change = CalendarChange.model_validate(row["payload"])
        try:
            verdict, wid = await _verify(tp, change, recorded)
        except McpToolError as exc:
            lines.append(
                f"TrainingPeaks unreachable ({exc}); {len(rows) - i} pending change(s) left pending"
            )
            break
        with deps.connect() as conn:
            if verdict == "applied":
                repo.mark_change_applied(
                    conn, row["id"], tp_workout_id=wid, result={"reconciled": True}
                )
                _mark_week_written(conn, row["plan_id"], change)
                if change.op == "create" and wid is not None:
                    recorded.add(wid)
                lines.append(f"{_label(change)}: found on TrainingPeaks; recorded as applied")
            else:
                err = {
                    "missing": PENDING_NOT_FOUND,
                    "ambiguous": PENDING_AMBIGUOUS,
                    "unverifiable": PENDING_UNVERIFIABLE,
                }[verdict]
                mark_failed(conn, "plan_changes", row["id"], err)
                lines.append(f"{_label(change)}: {err}; marked failed")
            conn.commit()
    return lines


async def _record_and_send(
    deps: GraphDeps,
    tp: ToolCaller,
    change: CalendarChange,
    call: tuple[str, dict[str, Any]],
    *,
    plan_id: int | None,
    thread_id: str,
    goal_id: int | None,
) -> Any:
    """One TrainingPeaks call inside its `plan_changes` row: pending before, applied after."""
    name, args = call

    def mark_applied(conn: Conn, row_id: int, result: Any) -> None:
        repo.mark_change_applied(
            conn,
            row_id,
            tp_workout_id=result_workout_id(change, result),
            result=result if isinstance(result, dict) else {"result": result},
        )
        if (
            change.op == "create_event"
            and goal_id is not None
            and isinstance(result, dict)
            and result.get("event_id") is not None
        ):
            repo.set_goal_event(conn, goal_id, str(result["event_id"]))

    rec = await recorded_write(
        deps.connect,
        table="plan_changes",
        insert_pending=lambda conn: repo.insert_pending_change(conn, plan_id, thread_id, change),
        call=lambda: tp.call_json(name, args),
        mark_applied=mark_applied,
    )
    return rec.result


async def apply_changes(
    deps: GraphDeps,
```

replace:

```python
    owned: set[str] = set()
    if plan_id is not None:
        with deps.connect() as conn:
            owned = repo.owned_workout_ids(conn, plan_id)
```

with:

```python
    reconciled = await reconcile_pending(deps)
    owned: set[str] = set()
    if plan_id is not None:
        with deps.connect() as conn:
            owned = repo.owned_workout_ids(conn, plan_id)
```

replace:

```python
        try:
            name, args = to_tp_call(change)
            result = await deps.tp.call_json(name, args)
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        wid = result_workout_id(change, result)
        with deps.connect() as conn:
            repo.insert_change(
                conn,
                plan_id,
                thread_id,
                change,
                tp_workout_id=wid,
                result=result if isinstance(result, dict) else {"result": result},
            )
            if (
                change.op == "create_event"
                and goal_id is not None
                and isinstance(result, dict)
                and result.get("event_id") is not None
            ):
                repo.set_goal_event(conn, goal_id, str(result["event_id"]))
            conn.commit()
        applied.append(change)
```

with:

```python
        try:
            call = to_tp_call(change)  # a malformed change fails here, before any row exists
            await _record_and_send(
                deps,
                deps.tp,
                change,
                call,
                plan_id=plan_id,
                thread_id=thread_id,
                goal_id=goal_id,
            )
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        applied.append(change)
```

and replace:

```python
        tp_plan_applied=tp_plan_applied,
        sessions_changed=any(c.op in SESSION_OPS for c in applied),
    )
```

with:

```python
        tp_plan_applied=tp_plan_applied,
        sessions_changed=any(c.op in SESSION_OPS for c in applied),
        reconciled=reconciled,
    )
```

If mypy reports `deps.tp` as `ToolCaller | None` at the `_record_and_send(deps, deps.tp, ...)` call, bind `tp = deps.tp` right after the `if deps.tp is None: return ...` block and pass `tp`. Do not add `assert` inside the loop.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-planning/tests packages/tri-coach/tests -q`
Expected: all pass (the coach suite drives this `apply_changes` with no pending rows, so its `tp.calls` sequences are unchanged).

- [ ] **Step 6: Definition of done, then commit**

```bash
git add packages/tri-planning/src/tri_planning/repo.py packages/tri-planning/src/tri_planning/graph/nodes/apply.py packages/tri-planning/tests/test_apply_node.py
git commit -m "feat(planning): record every TrainingPeaks write before sending it; reconcile pending rows"
```

---

### Task 7: Nutrition apply records before writing and reconciles pending rows

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/repo.py` (imports; after `insert_change`; `owned_note_ids`; `session_note_owned`)
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py:5-23, 52-88, 97-122, 125-180`
- Test: `packages/tri-nutrition/tests/test_apply_node.py` (edit one test, append)

**Interfaces:**
- Consumes: `recorded_write`, `mark_failed`, `pending_rows` (Task 5).
- Produces:
  - `repo.insert_pending_change(conn, thread_id: str, change: NutritionChange) -> int`
  - `repo.mark_change_applied(conn, row_id: int, result: dict[str, Any] | None, *, target_key: str | None = None) -> None` (`target_key` replaces the row's key when given: the note id of a created race note)
  - `repo.pending_changes(conn) -> list[dict[str, Any]]`
  - `owned_note_ids` and `session_note_owned` count only `status = 'applied'` rows.
  - `apply.reconcile_pending(deps: GraphDeps) -> list[str]`
  - `ApplyResult.reconciled: list[str]` (default empty), reported as `  reconciled: ...`.

**Reconciliation rules** (a row whose server is down this session stays `pending`, with a line):
- `set_day_targets`: `get_nutrition_daily_settings {"date": day}` through `trim_settings`; carbs, protein and fat equal to the payload's grams → `applied` and the day marked written.
- `set_session_note`: `tp_get_workout_note {"workout_id"}`; the note equals the payload's note (whitespace-trimmed) → `applied` and the session fuel plan marked written.
- `set_race_note` with a `target_key` (an update): `tp_get_note {"note_id"}`; title and description equal → `applied`.
- `set_race_note` without one (a create): `tp_list_notes` over the event day; a note with the payload's title → `applied`, its id becomes the row's `target_key`, the race fuel plan is marked written with it.
- Not found → `failed` with `not found on <Garmin|TrainingPeaks> after a pending write`. An `McpToolError` on one row leaves that row `pending` with a line and moves to the next.

- [ ] **Step 1: Confirm the note tools' arguments**

Run (read-only; it lists tool schemas and one week of notes):

```bash
uv run python - <<'EOF'
import asyncio, json
from datetime import date, timedelta
from tri_core.config import Settings
from tri_core.mcp.client import McpToolClient
from tri_core.mcp.servers import trainingpeaks_spec

async def main():
    async with McpToolClient(trainingpeaks_spec(Settings())) as c:
        for t in (await c._session.list_tools()).tools:
            if t.name in ("tp_list_notes", "tp_get_note", "tp_get_workout_note"):
                print(t.name, json.dumps(t.inputSchema))
        today = date.today()
        print(json.dumps(await c.call_json(
            "tp_list_notes",
            {"start_date": (today - timedelta(days=7)).isoformat(), "end_date": today.isoformat()},
        ), default=str)[:1500])

asyncio.run(main())
EOF
```

Expected: `tp_list_notes` takes `start_date` and `end_date`; its answer is `{"notes": [{"id": ..., "title": ..., "date": ...}, ...], ...}`; `tp_get_note` takes `note_id` and answers `{"note": {"id", "title", "description", "date"}}`. Any difference is a stop condition: report the printed schemas.

- [ ] **Step 2: Write the failing tests**

In `packages/tri-nutrition/tests/test_apply_node.py`, replace (inside `test_garmin_failure_keeps_change_pending`):

```python
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is False
    assert ndb.execute("select count(*) as n from nutrition_changes").fetchone()["n"] == 0
```

with:

```python
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is False
    rows = ndb.execute("select status, error from nutrition_changes").fetchall()
    assert [r["status"] for r in rows] == ["failed"] and "boom" in rows[0]["error"]
```

Append to the same file:

```python
def _backdate(conn, row_id):
    conn.execute(
        "update nutrition_changes set applied_at = now() - interval '5 minutes' where id = %s",
        (row_id,),
    )


def _status(conn, row_id):
    return conn.execute(
        "select status, error, target_key from nutrition_changes where id = %s", (row_id,)
    ).fetchone()


async def test_a_pending_day_target_found_on_garmin_is_applied(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target()])
    rid = repo.insert_pending_change(ndb, "t", day_target_change(target()))
    _backdate(ndb, rid)
    g = FakeGarmin(
        responses={
            "get_nutrition_daily_settings": {
                "calorieGoal": 2800,
                "macroGoals": {"carbs": 280, "protein": 150, "fat": 120},
            }
        }
    )
    r = await apply_changes(make_deps(ScriptedChatModel(script=[]), garmin=g), mem_store, [], "t", overrides=None)
    assert g.calls == [("get_nutrition_daily_settings", {"date": "2026-09-14"})]
    assert _status(ndb, rid)["status"] == "applied"
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is True
    assert "recorded as applied" in r.report(0, None)


async def test_a_pending_day_target_missing_on_garmin_is_failed(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target()])
    rid = repo.insert_pending_change(ndb, "t", day_target_change(target()))
    _backdate(ndb, rid)
    g = FakeGarmin()  # answers with no macro goals
    await apply_changes(make_deps(ScriptedChatModel(script=[]), garmin=g), mem_store, [], "t", overrides=None)
    row = _status(ndb, rid)
    assert row["status"] == "failed" and row["error"] == "not found on Garmin after a pending write"
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is False


async def test_a_reconciled_session_note_is_owned(ndb, make_deps, mem_store):
    fuel = SessionFuel(**session_fuel_json("w1", MONDAY))
    rid = repo.insert_pending_change(ndb, "t", session_note_change(fuel))
    _backdate(ndb, rid)
    assert repo.session_note_owned(ndb, "w1") is False  # pending does not own
    tp = FakeTp(responses={"tp_get_workout_note": {"note": fuel.note_text}})
    newer = SessionFuel(**session_fuel_json("w1", MONDAY, note_text="Fuel: 70 g/h."))
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp),
        mem_store,
        [session_note_change(newer)],
        "t",
        overrides=None,
    )
    assert _status(ndb, rid)["status"] == "applied"
    # owned now, so the write skips the ownership read that would have refused it
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note", "tp_set_workout_note"]
    assert r.error is None and [c.op for c in r.applied] == ["set_session_note"]


async def test_a_pending_race_note_create_takes_the_found_note_id(ndb, make_deps, mem_store):
    plan = RaceFuelPlan(**race_plan_json(MONDAY + timedelta(days=40)))
    change = race_note_change(plan, "Race fuel: City Tri 2026-10-24", None)
    rid = repo.insert_pending_change(ndb, "t", change)
    _backdate(ndb, rid)
    listed = {"notes": [{"id": "n77", "title": "Race fuel: City Tri 2026-10-24", "date": "2026-10-24"}]}
    tp = FakeTp(responses={"tp_list_notes": listed})
    await apply_changes(make_deps(ScriptedChatModel(script=[]), tp=tp), mem_store, [], "t", overrides=None)
    assert tp.calls == [("tp_list_notes", {"start_date": "2026-10-24", "end_date": "2026-10-24"})]
    row = _status(ndb, rid)
    assert row["status"] == "applied" and row["target_key"] == "n77"
    assert "n77" in repo.owned_note_ids(ndb)
```

`race_plan_json(event_date)` builds a `RaceFuelPlan` dated `event_date`; `MONDAY + 40 days` is 2026-10-24, the date `race_note_change` puts in the payload.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_apply_node.py -q`
Expected: new tests FAIL with `AttributeError: module 'tri_nutrition.repo' has no attribute 'insert_pending_change'`; `test_garmin_failure_keeps_change_pending` FAILS on `[] == ['failed']`.

- [ ] **Step 4: Repository**

In `packages/tri-nutrition/src/tri_nutrition/repo.py`, add to the imports:

```python
from tri_core.db.writes import pending_rows
```

replace:

```python
def owned_note_ids(conn: Conn) -> set[str]:
    rows = conn.execute(
        "select distinct target_key from nutrition_changes "
        "where operation = 'set_race_note' and target_key <> ''"
    ).fetchall()
    return {r["target_key"] for r in rows}
```

with:

```python
def insert_pending_change(conn: Conn, thread_id: str, change: NutritionChange) -> int:
    """The row for a server call about to be made; `mark_change_applied` settles it."""
    row = conn.execute(
        """
        insert into nutrition_changes (thread_id, operation, target_key, payload, reason, status)
        values (%s, %s, %s, %s, %s, 'pending') returning id
        """,
        (
            thread_id,
            change.op,
            change.target_key,
            Jsonb(change.model_dump(mode="json")),
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def mark_change_applied(
    conn: Conn, row_id: int, result: dict[str, Any] | None, *, target_key: str | None = None
) -> None:
    conn.execute(
        "update nutrition_changes set status = 'applied', result = %s, "
        "target_key = coalesce(%s, target_key), applied_at = now(), error = null where id = %s",
        (Jsonb(result) if result is not None else None, target_key, row_id),
    )


def pending_changes(conn: Conn) -> list[dict[str, Any]]:
    return pending_rows(conn, "nutrition_changes")


def owned_note_ids(conn: Conn) -> set[str]:
    rows = conn.execute(
        "select distinct target_key from nutrition_changes "
        "where operation = 'set_race_note' and target_key <> '' and status = 'applied'"
    ).fetchall()
    return {r["target_key"] for r in rows}
```

and replace:

```python
        "select 1 as x from nutrition_changes where operation = 'set_session_note' "
        "and target_key = %s limit 1",
```

with:

```python
        "select 1 as x from nutrition_changes where operation = 'set_session_note' "
        "and target_key = %s and status = 'applied' limit 1",
```

- [ ] **Step 5: The apply node**

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py`, replace:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.mcp.client import McpToolError
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.nutrition.tp_calls import result_note_id, to_tp_call
```

with:

```python
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.db.repo import Conn
from tri_core.db.writes import mark_failed, recorded_write
from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.nutrition.tp_calls import result_note_id, to_tp_call
from tri_nutrition.tools.garmin import trim_settings
```

replace the whole of `write_change` (from `async def write_change(` through its final `raise ValueError(f"unknown operation {change.op}")`) with:

```python
def _as_payload(result: Any) -> dict[str, Any]:
    return result if isinstance(result, dict) else {"result": result}


def _mark_written(conn: Conn, change: NutritionChange, note_id: str | None) -> None:
    if change.op in GARMIN_OPS:
        repo.mark_targets_written(conn, [change.day])
    elif change.op == "set_session_note":
        wid = str(change.payload["workout_id"])
        repo.mark_fuel_written_for(conn, "session", change.day, wid, None)
    else:
        repo.mark_fuel_written_for(conn, "race", change.day, None, note_id)


async def _record_and_send(
    deps: GraphDeps, server: ToolCaller, thread_id: str, change: NutritionChange, name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """One server call inside its `nutrition_changes` row: pending before, applied after."""

    def mark_applied(conn: Conn, row_id: int, result: Any) -> None:
        note_id = result_note_id(change, result)
        repo.mark_change_applied(conn, row_id, _as_payload(result), target_key=note_id)
        _mark_written(conn, change, note_id)

    rec = await recorded_write(
        deps.connect,
        table="nutrition_changes",
        insert_pending=lambda conn: repo.insert_pending_change(conn, thread_id, change),
        call=lambda: server.call_json(name, args),
        mark_applied=mark_applied,
    )
    return _as_payload(rec.result)


async def write_change(deps: GraphDeps, thread_id: str, change: NutritionChange) -> dict[str, Any]:
    """Send one change to its server with its audit row recorded first, and mark the target
    written. Raises McpToolError/ValueError on failure and PermissionError on an ownership
    refusal; neither refusal leaves a row."""
    if change.op in GARMIN_OPS:
        if deps.garmin is None:
            raise McpToolError("set_nutrition_daily_settings", "Garmin server unavailable")
        if change.day != deps.today():
            raise ValueError(f"Garmin can only hold today's target; {change.day} is not today")
        name, args = to_garmin_call(change)
        return await _record_and_send(deps, deps.garmin, thread_id, change, name, args)
    if change.op in TP_OPS:
        if deps.tp is None:
            raise McpToolError(change.op, "TrainingPeaks server unavailable")
        await _check_ownership(deps, change)
        name, args = to_tp_call(change)
        return await _record_and_send(deps, deps.tp, thread_id, change, name, args)
    raise ValueError(f"unknown operation {change.op}")


def _grams(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


async def _verify(server: ToolCaller, change: NutritionChange) -> tuple[bool, str | None]:
    """Whether a pending change is on its server, and the note id it concerns."""
    p = change.payload
    if change.op == "set_day_targets":
        s = trim_settings(
            await server.call_json("get_nutrition_daily_settings", {"date": change.day.isoformat()})
        )
        got = (_grams(s["carbs_g"]), _grams(s["protein_g"]), _grams(s["fat_g"]))
        want = (_grams(p["carbs_grams"]), _grams(p["protein_grams"]), _grams(p["fat_grams"]))
        return got == want, None
    if change.op == "set_session_note":
        cur = await server.call_json("tp_get_workout_note", {"workout_id": str(p["workout_id"])})
        note = cur.get("note") if isinstance(cur, dict) else None
        return str(note or "").strip() == str(p["note"]).strip(), None
    if change.op == "set_race_note" and change.target_key:
        cur = await server.call_json("tp_get_note", {"note_id": change.target_key})
        note = cur.get("note") if isinstance(cur, dict) else None
        same = (
            isinstance(note, dict)
            and note.get("title") == p["title"]
            and note.get("description") == p["description"]
        )
        return same, change.target_key
    if change.op == "set_race_note":
        day = str(p["date"])
        listed = await server.call_json("tp_list_notes", {"start_date": day, "end_date": day})
        notes = listed.get("notes") if isinstance(listed, dict) else None
        for n in notes if isinstance(notes, list) else []:
            if isinstance(n, dict) and n.get("title") == p["title"] and n.get("id") is not None:
                return True, str(n["id"])
        return False, None
    return False, None


async def reconcile_pending(deps: GraphDeps) -> list[str]:
    """Settle `nutrition_changes` rows an earlier apply left `pending`: `applied` when the
    server shows the change, else `failed`. Returns one report line per row settled or left."""
    with deps.connect() as conn:
        rows = repo.pending_changes(conn)
    lines: list[str] = []
    for row in rows:
        change = NutritionChange.model_validate(row["payload"])
        garmin = change.op in GARMIN_OPS
        server = deps.garmin if garmin else deps.tp
        name = "Garmin" if garmin else "TrainingPeaks"
        if server is None:
            lines.append(f"{_label(change)}: {name} unavailable; left pending")
            continue
        try:
            found, note_id = await _verify(server, change)
        except McpToolError as exc:
            lines.append(f"{_label(change)}: {name} unreachable ({exc}); left pending")
            continue
        with deps.connect() as conn:
            if found:
                repo.mark_change_applied(conn, row["id"], {"reconciled": True}, target_key=note_id)
                _mark_written(conn, change, note_id)
                lines.append(f"{_label(change)}: found on {name}; recorded as applied")
            else:
                err = f"not found on {name} after a pending write"
                mark_failed(conn, "nutrition_changes", row["id"], err)
                lines.append(f"{_label(change)}: {err}; marked failed")
            conn.commit()
    return lines
```

replace:

```python
    error: str | None
    profile_updated: bool

    def report(self, total: int, overrides: dict[str, Any] | None) -> str:
        n_garmin = sum(1 for c in self.applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in self.applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(self.applied)} of {total} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  skipped: {s}" for s in self.skipped]
```

with:

```python
    error: str | None
    profile_updated: bool
    reconciled: list[str] = field(default_factory=list)  # pending rows settled before the batch

    def report(self, total: int, overrides: dict[str, Any] | None) -> str:
        n_garmin = sum(1 for c in self.applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in self.applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(self.applied)} of {total} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  reconciled: {s}" for s in self.reconciled]
        lines += [f"  skipped: {s}" for s in self.skipped]
```

replace:

```python
    todo = list(changes)
    applied: list[NutritionChange] = []
    skipped: list[str] = []
    held: list[NutritionChange] = []
```

with:

```python
    reconciled = await reconcile_pending(deps)
    todo = list(changes)
    applied: list[NutritionChange] = []
    skipped: list[str] = []
    held: list[NutritionChange] = []
```

and replace:

```python
        held=held,
        error=error,
        profile_updated=persisted,
    )
```

with:

```python
        held=held,
        error=error,
        profile_updated=persisted,
        reconciled=reconciled,
    )
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests packages/tri-coach/tests packages/tri-web/tests -q`
Expected: all pass.

- [ ] **Step 7: Definition of done, then commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/repo.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py packages/tri-nutrition/tests/test_apply_node.py
git commit -m "feat(nutrition): record every Garmin and TrainingPeaks write before sending it; reconcile pending rows"
```

---

### Task 8: Docs and final checks

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/README.md`
- Modify: `packages/tri-core/src/tri_core/sync/README.md`
- Modify: `README.md:146` (migration list)
- Modify: `docs/superpowers/specs/2026-09-24-data-layer-design.md:4` (status)
- Vault copies of all four, plus this plan.

**Interfaces:** none.

- [ ] **Step 1: `db/README.md`**

Replace:

```markdown
Four tables, one migration so far, and a small repository module that owns every write.
```

with:

```markdown
Five sync tables and a small repository module that owns every write. `writes.py` holds
`recorded_write`, the record-before-write wrapper every TrainingPeaks and Garmin write goes
through.
```

replace:

```markdown
  models.py       Row dataclasses: AthleteProfileRow, WorkoutRow, DailyMetricsRow, SyncState
  repo.py         upsert_* functions and the few reads the sync needs; callers commit
```

with:

```markdown
  models.py       Row dataclasses: AthleteProfileRow, WorkoutRow, DailyMetricsRow,
                  GarminActivityRow, SyncState
  repo.py         upsert_* functions and the few reads the sync needs; callers commit
  writes.py       recorded_write, mark_failed, pending_rows: pending -> applied | failed
  sql_tool.py     the agents' read-only SQL tool and SCHEMA_DOC
```

replace:

```markdown
`start_time_local` are filled by the matching step, not by TP. `start_time_local` is a naive
timestamp because Garmin reports local time with no offset.
```

with:

```markdown
`start_time_local` are filled by the matching step, not by TP, from the first matched Garmin
activity. `start_time_local` is a naive timestamp because Garmin reports local time with no
offset. Rows run 28 days ahead of today. `deleted_at` is set when a workout in the synced
window is no longer in TrainingPeaks' listing and cleared when it comes back; every reader
filters `deleted_at is null`, and `list_workouts_between(..., include_deleted=True)` shows
tombstones.

**`garmin_activities`** (one row per Garmin activity, matched or not): `tp_workout_id` links it
to its workout; a brick has two rows pointing at it. Rows from before migration 007 were
backfilled from `workouts.garmin_activity_id` with `raw = '{}'`; a Garmin sync covering their
day fills the rest.

**`plan_changes` / `nutrition_changes` `status`**: `pending` (inserted before the call),
`applied`, or `failed` with `error`. Ownership reads count `applied` rows only. A `pending` row
older than 60 s is reconciled against the server at the start of the next apply.
```

and replace:

```markdown
- `upsert_workouts` replaces every modeled column on conflict, **except** the two Garmin match
  columns, which are not in its column list and therefore survive a TP resync.
```

with:

```markdown
- `upsert_workouts` replaces every modeled column on conflict and clears `deleted_at`,
  **except** the two Garmin match columns, which are not in its column list and therefore
  survive a TP resync.
- `upsert_garmin_activities` never writes `tp_workout_id`, so a Garmin resync keeps links.
```

- [ ] **Step 2: `sync/README.md`**

Replace the whole `## Matching Garmin activities to TP workouts (`match.py`)` section body (the paragraph from `TP does not expose a start time` through `the 12 leftover Garmin activities had no TP record.`) with:

```markdown
Every fetched activity is upserted into `garmin_activities` first, matched or not. Matching is
then: same calendar day, same sport family, workout completed and not deleted, closest actual
duration within 120 s. A workout with no duration matches only when it is the sole candidate
that day. A `brick` takes two legs of different sports: the first must leave room for the
second, and the two together must land within 120 s of the brick's duration; a Garmin
multisport activity fills a brick on its own. A single-sport workout that fits beats a brick
leg. Activities already linked on an earlier sync count as their workout's legs and are never
reassigned. `workouts.garmin_activity_id` keeps the first linked leg.
```

and replace:

```markdown
- **Windows.** `resolve_window` picks `[start, end]` per source: `--since` wins; otherwise a
  first run uses the source's default (TP 365 days, Garmin 60 days); otherwise incremental
  from the watermark minus a 3-day overlap so late-edited workouts are picked up.
```

with:

```markdown
- **Windows.** `resolve_window` picks `[start, end]` per source: `--since` wins; otherwise a
  first run uses the source's default (TP 365 days, Garmin 60 days); otherwise incremental
  from the watermark minus a 3-day overlap so late-edited workouts are picked up. TrainingPeaks
  ends at `today + SYNC_AHEAD_DAYS` (28), Garmin at today. The watermark records
  `min(end, today)`: the forward window is re-listed on every run.
- **Deletions.** After the TP upsert, workouts in `[start, end]` missing from the listing get
  `deleted_at`; a reappearing id clears it. If any listing chunk fails, nothing is tombstoned
  that run. Fitness rows after today are not stored.
```

and replace:

```markdown
- `TP_FIRST_RUN_DAYS`, `GARMIN_FIRST_RUN_DAYS`, `OVERLAP_DAYS` at the top of `runner.py`.
```

with:

```markdown
- `TP_FIRST_RUN_DAYS`, `GARMIN_FIRST_RUN_DAYS`, `OVERLAP_DAYS`, `SYNC_AHEAD_DAYS` at the top
  of `runner.py`.
```

- [ ] **Step 3: Top-level README and spec status**

In `README.md`, replace:

```markdown
005_wellness.sql (lab tables), 006_fixes.sql (2026-09-24 correctness fixes)
```

with:

```markdown
005_wellness.sql (lab tables), 006_fixes.sql (2026-09-24 correctness fixes), 007_data_layer.sql (tombstones, garmin_activities, change status)
```

In `docs/superpowers/specs/2026-09-24-data-layer-design.md`, replace `**Status:** Draft` with `**Status:** Implemented (plan 2026-09-25-data-layer.md)`.

- [ ] **Step 4: Vault copies**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p "$V/packages/tri-core/src/tri_core/db" "$V/packages/tri-core/src/tri_core/sync" "$V/docs/superpowers/specs" "$V/docs/superpowers/plans"
cp packages/tri-core/src/tri_core/db/README.md "$V/packages/tri-core/src/tri_core/db/readme.md"
cp packages/tri-core/src/tri_core/sync/README.md "$V/packages/tri-core/src/tri_core/sync/readme.md"
cp README.md "$V/readme.md"
cp docs/superpowers/specs/2026-09-24-data-layer-design.md "$V/docs/superpowers/specs/"
cp docs/superpowers/plans/2026-09-25-data-layer.md "$V/docs/superpowers/plans/"
```

- [ ] **Step 5: Final checks**

Run the full Definition of done (all six commands). Then:

- `uv run pytest -q` count = Baseline B + the tests Tasks 1-7 added (1 + 8 + 9 + 6 + 5 + 6 + 4 = 39; Task 3's rename of `test_brick_matches_any_sport_once` is not counted), with no test lost.
- `git diff main --stat` touches only the files this plan names.
- `grep -rn "from workouts" packages --include='*.py' | grep -v /tests/` lists no query without `deleted_at` other than the two prompt examples Task 4's note names.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/db/README.md packages/tri-core/src/tri_core/sync/README.md README.md docs/superpowers/specs/2026-09-24-data-layer-design.md
git commit -m "docs(data-layer): db and sync READMEs, migration list, spec status"
```

- [ ] **Step 7: Hand off**

Tell Brian, in this order: the branch is ready; before merging (or right after, before the next `tri` run) apply 007 to the live database with
`docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/007_data_layer.sql`;
then run `tri sync` and read the `trainingpeaks: n deleted, m restored` line. Do not run either command yourself, and ask before merging or pushing.
