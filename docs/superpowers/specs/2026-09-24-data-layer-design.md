# Data layer: sync ahead, tombstones, Garmin activities, record-before-write

**Date:** 2026-09-24
**Status:** Draft
**Purpose:** Make the `workouts` table say what the TrainingPeaks calendar says, forwards and backwards, keep every Garmin activity so a brick has both legs, and never let a TrainingPeaks or Garmin write succeed without a row that says it happened. Second of five specs; assumes the correctness fixes are in. Line numbers are `main` @ 6540055.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Sync window | TrainingPeaks syncs to `today + 28`; Garmin stays at `today` (chosen 2026-09-24). | Covers the 3-week planning horizon and the 14-day nutrition horizon. Garmin has nothing in the future. |
| Deletions | Soft delete: `workouts.deleted_at` set when a row in the window is missing from the listing, cleared when it reappears (chosen 2026-09-24). | The analyst can still answer "what happened to Tuesday's ride". Readers filter one column. |
| Garmin activities | A `garmin_activities` table keyed by activity id with a nullable `tp_workout_id`; `workouts.garmin_activity_id` stays as the first matched leg (chosen 2026-09-24). | Bricks keep both legs; unmatched activities are visible; existing readers keep working. |
| Record before write | Every TrainingPeaks and Garmin write inserts a `pending` row first, then updates it to `applied` or `failed`. A `pending` row older than the run is reconciled on the next apply. | A DB failure after a successful call can no longer lock the athlete out of their own note or duplicate a workout. |
| Watermark | `sync_state.last_synced_date` keeps its meaning: the last day whose past is complete. The forward window is not watermarked; every run re-lists it. | 28 days of listing is one `tp_get_workouts` call. |

## 2. Feasibility, verified 2026-09-24

- `resolve_window` (`tri_core/sync/runner.py:49-61`) ends every window at `today`; `_sync_trainingpeaks` (`:73-82`) upserts and never reconciles; `fetch_trainingpeaks` (`sync/trainingpeaks.py:151-187`) holds the listing ids in memory only. `upsert_workouts` (`db/repo.py:93-106`) overwrites every column in `_WORKOUT_COLS`, which excludes `garmin_activity_id` and `start_time_local`, so a column left out of the list survives a re-sync.
- `workouts` (`migrations/001_initial.sql:19-51`) has `garmin_activity_id text unique` and no `deleted_at`. `GarminActivity` (`sync/garmin.py:19-29`) has id, type_key, sport, start_time_local, duration_sec, distance_m, avg_hr, name, raw; `_sync_garmin` (`runner.py:85-94`) drops unmatched activities.
- `match_activities` (`sync/match.py:14-50`) marks a workout used after one activity and compares one activity's duration to the whole brick. `test_brick_matches_any_sport_once` passes only with `tolerance_sec=100000`.
- Readers of `workouts` outside tri-core: `tri_analyze/repo.py:33-38` (±7 days), `tri_coach/context.py:115-119` (completed, week to date), `tri_nutrition/plan_loader.py:94-99, 119-125` (`not completed`, horizon), `tri_planning/repo.py:296-302`, `tri_wellness/labs/training_context.py:27-47` (completed, 3 days back), `tri_web/today.py:213-214` (`list_workouts_between`). `tri_planning/tools/tp_read.py:12-30` reads the calendar live over MCP because the DB has no future rows.
- Writes: `tri_planning/graph/nodes/apply.py:88-124` calls TP then `repo.insert_change`; a create's id comes only from the result (`planning/tp_calls.py:74-80`). `owned_workout_ids` (`tri_planning/repo.py:230-238`) derives ownership from `plan_changes` rows. `tri_nutrition/graph/nodes/apply.py:52-88` does the same for Garmin daily targets and TP notes, with `_check_ownership` (`:33-49`) reading the note back from TP when no row owns it. `plan_changes` (`002_planning.sql:44-56`) and `nutrition_changes` (`004_nutrition.sql:34-44`) have `payload`, `result`, `applied_at` and no status.
- `ToolCaller.call_json` (`sync/__init__.py:6-7`) is the interface both sync and the agents use for TP and Garmin.

## 3. Layout

```
migrations/007_data_layer.sql                     NEW
packages/tri-core/src/tri_core/sync/runner.py     SYNC_AHEAD_DAYS; resolve_window returns per-source ends; reconcile step
packages/tri-core/src/tri_core/sync/match.py      activities keyed to workouts, bricks take two legs
packages/tri-core/src/tri_core/db/repo.py         mark_missing_deleted, upsert_garmin_activities, link_activity, list_workouts_between(include_deleted=False)
packages/tri-core/src/tri_core/db/models.py       GarminActivityRow; WorkoutRow unchanged
packages/tri-core/src/tri_core/db/sql_tool.py     SCHEMA_DOC: deleted_at, garmin_activities, example queries
packages/tri-core/src/tri_core/db/writes.py       NEW: recorded_write(...)
packages/tri-planning/src/tri_planning/{repo.py,graph/nodes/apply.py,tools/tp_read.py}
packages/tri-nutrition/src/tri_nutrition/{repo.py,graph/nodes/apply.py,plan_loader.py}
readers listed in §2 add `deleted_at is null`
tests in tri-core, tri-planning, tri-nutrition
```

## 4. Interfaces

### 4.1 Migration 007

```sql
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

alter table plan_changes add column if not exists status text not null default 'applied';
alter table plan_changes add column if not exists error text;
alter table nutrition_changes add column if not exists status text not null default 'applied';
alter table nutrition_changes add column if not exists error text;
```

Existing rows default to `applied`, which is what they were. A backfill inserts one `garmin_activities` row per existing `workouts.garmin_activity_id` with the fields the row has (sport, start_time_local, `raw = '{}'`); the next Garmin sync fills the rest because the window overlaps.

### 4.2 Sync

```python
SYNC_AHEAD_DAYS = 28

def resolve_window(state, since, full, today, first_run_days, *, ahead_days=0, overlap_days=OVERLAP_DAYS) -> tuple[date, date]
```

TrainingPeaks passes `ahead_days=SYNC_AHEAD_DAYS`; Garmin passes `0`. `set_sync_state` records `min(end, today)`.

`_sync_trainingpeaks` gains a reconcile step after the upsert: `repo.mark_missing_deleted(conn, start, end, seen_ids)` sets `deleted_at = now()` on rows in `[start, end]` whose id is not in the listing and whose `deleted_at` is null, and `upsert_workouts` sets `deleted_at = null` on conflict. The log line reports `n deleted, m restored`.

`_sync_garmin` upserts every fetched activity into `garmin_activities`, then matches. `match_activities(workouts, activities, tolerance_sec=120)` returns `list[tuple[str, GarminActivity]]` as today with two changes: a workout of sport `brick` stays a candidate for a second activity of a different sport on the same day, and for a brick the duration test is `sum(leg durations) within tolerance of actual_duration_sec` once both legs are present, else the leg's own sport and day match. `repo.link_activity(conn, activity_id, tp_workout_id)` sets the FK; `workouts.garmin_activity_id` is set to the first linked leg when null, so existing readers and `get_activity_splits` keep working.

### 4.3 Readers

`list_workouts_between(conn, start, end, *, include_deleted=False)`; every reader in §2 adds `deleted_at is null` to its own SQL. `SCHEMA_DOC` documents `deleted_at` ("a workout removed from TrainingPeaks; filter `deleted_at is null` unless asked about removals") and `garmin_activities`, and every example query carries the filter. `tri_planning/tools/tp_read.py` keeps reading live: the DB now has the same rows, but the tool is what the adjust agent uses to confirm before proposing, and one MCP call per check-in is fine.

`plan_loader._planned_workouts` keeps `not completed` except for today (fixes spec N6) and adds the filter.

### 4.4 Record-before-write

`tri_core.db.writes`:

```python
@dataclass(frozen=True)
class Recorded:
    row_id: int
    result: Any

async def recorded_write(
    conn_factory: ConnectFactory,
    *,
    table: Literal["plan_changes", "nutrition_changes"],
    insert_pending: Callable[[Conn], int],          # inserts the row with status 'pending', returns id
    call: Callable[[], Awaitable[Any]],             # the TP or Garmin call
    mark_applied: Callable[[Conn, int, Any], None], # sets status 'applied', result, ids the result carries
) -> Recorded
```

Sequence: open a connection, `insert_pending`, commit; `await call()`; on success open a connection, `mark_applied`, commit; on a call failure update the row to `failed` with the error text and re-raise. If `mark_applied` itself fails, the row stays `pending` with the call already made; the exception propagates as today.

Planning `apply_changes` and nutrition `write_change` use it for every op. `owned_workout_ids` and `owned_note_ids`/`session_note_owned` count rows with `status = 'applied'`.

Reconciliation runs at the start of each apply: `repo.pending_changes(conn)` returns rows with `status = 'pending'` older than 60 seconds. For each, the apply node asks TP for the target (`tp_get_workouts` for the row's date, or `tp_get_workout_note`/note listing for a note) and marks it `applied` with the found id when the payload's title and date match, else `failed` with `not found on TrainingPeaks after a pending write`. A `pending` Garmin daily target is reconciled by reading the day's settings. The count of reconciled rows goes in the apply report.

## 5. Behaviour

- **First sync after merge.** The TP window is `last_synced_date - 3` to `today + 28`; every planned session for the next four weeks lands, the analyst's "next 7 days" block fills, and `tri-web` today reads planned sessions from the DB.
- **A workout deleted in TrainingPeaks** gets `deleted_at` on the next sync and disappears from every reader; `select ... where deleted_at is not null` shows it to the analyst when asked.
- **A brick** matches two activities; both rows link to the workout; `get_activity_splits` on `garmin_activity_id` shows the first leg as today, and the analyst can query `garmin_activities` for the second.
- **A create that succeeds on TP but fails to record** is a `pending` row; the next apply finds the workout by date and title and marks it applied and owned, instead of creating it again.
- **A note write whose record fails** is reconciled the same way, so `_check_ownership` no longer raises `PermissionError` on the athlete's own note.

## 6. Errors

- Reconciliation that cannot reach TP leaves the rows `pending` and says so in the report; the apply proceeds with the new changes.
- A `pending` row whose target is not found becomes `failed`; the change is re-proposed by the normal path on the next check-in.
- `mark_missing_deleted` never touches rows outside the fetched window, so a partial listing (a chunk that failed) cannot delete a month.

## 7. Testing

- `test_sync_runner.py`: `resolve_window` with `ahead_days`; end-to-end sync where a listed id disappears then reappears (`deleted_at` set then cleared); the watermark never passes today.
- `test_sync_match.py`: `test_brick_matches_any_sport_once` becomes `test_brick_takes_both_legs` at the default tolerance; a re-sync where an assigned activity meets a new candidate does not steal it.
- `test_repo.py`: `upsert_garmin_activities`, `link_activity`, `list_workouts_between` filters.
- Each reader package: one test that a deleted row is invisible.
- `tri-core/tests/test_writes.py`: `recorded_write` marks applied, marks failed and re-raises, leaves pending when `mark_applied` raises.
- `tri-planning/tests/test_apply_node.py` and `tri-nutrition/tests/test_apply.py`: a pending row is reconciled by title and date; ownership counts applied rows only.
- `test_sql_tool.py`: `SCHEMA_DOC` names `deleted_at` and `garmin_activities`.

## 8. Out of scope

- Persisting laps (`workout_laps`); the analyst still fetches splits live.
- Watermarking by TP `lastModified`.
- Parallel detail fetches in sync (an optimisation the review lists; separate change).

## 9. Rollout

One plan: migration 007 and backfill, sync and match, readers, `recorded_write` in planning then nutrition, docs (`db/README.md`, `sync/README.md`, `SCHEMA_DOC`). Brian runs `tri migrate` (or the psql loop until the hygiene spec lands) and `tri sync` after merge; the first run reports the deleted/restored counts.
