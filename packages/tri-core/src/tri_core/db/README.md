# `db/`: Postgres schema and access

Four tables, one migration so far, and a small repository module that owns every write.
See also: [`../sync/README.md`](../sync/README.md) for who fills the tables,
[`../agent/README.md`](../agent/README.md) for who reads them.

## Modules

```
db/
  connection.py   connect(url) -> psycopg Connection with dict rows, autocommit off
  models.py       Row dataclasses: AthleteProfileRow, WorkoutRow, DailyMetricsRow, SyncState
  repo.py         upsert_* functions and the few reads the sync needs; callers commit
```

Schema lives in `migrations/*.sql` at the repo root. **Migrations are applied by hand with
psql** (see the top-level README); the assistant writes them, Brian runs them.

## Tables

**`athlete_profile`** (single row, `id = 1` enforced by a check constraint): FTP, run threshold
pace, swim CSS, LTHR, max HR, weight, and the full zone tables as jsonb. Thresholds are
derived from TrainingPeaks' zone groups keyed by `workoutTypeId` (1 swim, 2 bike, 3 run);
speed thresholds arrive in m/s and are stored as sec/km and sec/100m.

**`workouts`** (one row per TrainingPeaks workout, keyed by `tp_workout_id`): planned and actual
columns side by side because that is how TP stores them. `completed` is derived from the
presence of an actual duration, since TP's own `completed` flag is often null. `sport` is the
normalized vocabulary; `sport_raw` keeps TP's label. `garmin_activity_id` and
`start_time_local` are filled by the matching step, not by TP. `start_time_local` is a naive
timestamp because Garmin reports local time with no offset.

**`daily_metrics`** (one row per calendar day): Garmin physiology (sleep seconds and score,
overnight HRV, resting HR, body battery high/low, stress, training readiness) and the
TrainingPeaks fitness curve (`ctl`, `atl`, `tsb`, `tss_day`) on the same row. Each source fills
its half.

**`sync_state`** (one row per source): watermark date, last run time, status, last error.

Every table keeps a `raw jsonb` column (`raw`, `garmin_raw`, `tp_raw`) holding the full server
payload, so a field that was not modeled can still be queried with `->>` without a resync.

## Upsert semantics

- `upsert_workouts` replaces every modeled column on conflict, **except** the two Garmin match
  columns, which are not in its column list and therefore survive a TP resync.
- `upsert_daily_metrics` merges with `coalesce(excluded.col, daily_metrics.col)`, so a Garmin
  row never nulls out TP columns and vice versa. This is what lets two sources share a row.
- `upsert_athlete_profile` always writes `id = 1`.
- jsonb columns are wrapped in `psycopg.types.json.Jsonb` by `_params`; add new jsonb columns
  to `_JSON_COLS`.

## Conventions

- `timestamptz` everywhere except `workouts.start_time_local`.
- Distances in metres, durations in seconds, paces derived at query time.
- Numeric columns come back from psycopg as `Decimal`; the agent's SQL tool stringifies them
  for JSON.

## Test database

`tri_analyze_test` on the same container, created once by hand and migrated with the same
files. The `db` fixture in `tri_core.testing.fixtures` (registered by the root `conftest.py`) opens a connection, yields it, and rolls back
after every test, so tests never leave rows behind. When Postgres is down the fixture skips
with a clear message instead of failing.

## Read-only rule

The assistant never runs `INSERT/UPDATE/DELETE` or DDL against the store. Writes happen only
through `tri sync`, which Brian runs, and through tests inside rolled-back
transactions. The agent's `query_training_db` tool runs on a `read_only=True` connection.
