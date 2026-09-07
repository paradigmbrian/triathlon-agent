# `sync/`: deterministic ETL from the MCP servers into Postgres

No LLM anywhere in this directory. The sync launches each MCP server as a subprocess, calls
its tools programmatically, parses the JSON they return, and upserts rows. See also:
[`../mcp/README.md`](../mcp/README.md) for how servers are launched and results parsed,
[`../db/README.md`](../db/README.md) for the tables.

## Modules

```
sync/
  __init__.py       ToolCaller protocol: anything with `await call_json(tool, args)`
  trainingpeaks.py  parse_* (pure) + fetch_trainingpeaks (chunked to TP's 90-day limit)
  garmin.py         parse_* (pure) + fetch_garmin (walks day by day; no range endpoints)
  match.py          Pair Garmin activities with TP workouts
  runner.py         Order of operations, per-source error isolation, watermarks
  dates.py          date_chunks(): split a window into API-sized pieces
  sports.py         Map both sources' sport labels onto one vocabulary
```

## Shape of every source module

Each source is split into **pure parsers** and one **fetcher**.

- `parse_*(payload) -> Row` functions take a dict exactly as the MCP tool returned it and
  produce a `db.models` row. They have no I/O and are tested against inline dicts plus the
  recorded fixtures in `tests/fixtures/mcp/`.
- `fetch_<source>(client, start, end, log) -> Snapshot` walks the date window, calls tools
  through a `ToolCaller`, and collects parsed rows. Tests inject a fake client that answers
  from a dict, so no server runs.

Keeping parsing separate from fetching means a changed field name in a server payload is a
one-line parser fix with a unit test, not a debugging session against a live API.

## What each source provides

**TrainingPeaks** is the source of truth for workouts. One TP record holds both the planned
and the completed side (`tssPlanned` next to `tssActual`), so one `workouts` row per TP id.
Steps: athlete settings (thresholds, zone tables) → workout list per ≤90-day chunk → one
detail call per workout (the list lacks power, HR, IF, comments) → fitness curve
(CTL/ATL/TSB and daily TSS). Units: TP durations are **hours as floats** and distances km;
parsers convert to seconds and metres.

**Garmin** provides physiology and the activity ids needed for lap detail. Steps: sleep
summary range (≤90 nights per call; carries HRV and resting HR) → per-day `get_stats` (body
battery, stress, resting HR) and `get_training_readiness` → paginated activity list.

## Matching Garmin activities to TP workouts (`match.py`)

TP does not expose a start time, so matching is: same calendar day, same sport family (a TP
`brick` accepts any Garmin sport), workout must be completed, closest actual duration within
120 s. A workout with no duration matches only when it is the sole candidate that day. Each
side is matched at most once and already-matched workouts are skipped. On the first real run
this matched 30 of 30 completed workouts; the 12 leftover Garmin activities had no TP record.

## Runner semantics (`runner.py`)

- **Windows.** `resolve_window` picks `[start, end]` per source: `--since` wins; otherwise a
  first run uses the source's default (TP 365 days, Garmin 60 days); otherwise incremental
  from the watermark minus a 3-day overlap so late-edited workouts are picked up.
- **Isolation.** Each source runs in its own try/except. A Garmin failure rolls back only
  Garmin's rows; TP's commit stands. `sync_state` records `ok`/`error` and the message.
- **Idempotent.** Every write is an upsert on the natural key. Rerunning is always safe.
- **Openers.** The runner takes `open_tp`/`open_garmin` factories so tests substitute fakes;
  production builds `McpToolClient` from `mcp/servers.py`.

## Why the Garmin window is shorter

Garmin has no range endpoints for daily stats or readiness, so each day costs two calls, and
Garmin rate-limits aggressively. Sixty days is a few minutes; a year would be over 700 calls.
TrainingPeaks provides the year of training load, which is what long trends need.

## Knobs

- `TP_FIRST_RUN_DAYS`, `GARMIN_FIRST_RUN_DAYS`, `OVERLAP_DAYS` at the top of `runner.py`.
- `tolerance_sec` argument of `match_activities`.
- Sport vocabulary in `sports.py`: `swim | bike | run | brick | strength | race | rest | other`.

## Adding a field

1. Add the column in a new `migrations/00N_*.sql` (Brian applies it).
2. Add it to the row dataclass in `db/models.py` and the column list in `db/repo.py`.
3. Read it in the relevant `parse_*` and add an assertion to the parser test.
4. If the agent should know about it, add a line to `SCHEMA_DOC` in `agent/sql_tool.py`.
