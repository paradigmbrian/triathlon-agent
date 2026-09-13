# tri-analyze-agent — Triathlon Training Analysis Agent (package `tri_analyze`)

**Date:** 2026-09-06
**Status:** Implemented 2026-09-06 (plans `2026-09-06-foundation-and-sync.md`, `2026-09-06-agent-v1.md`). Superseded for the agent by `2026-09-13-tri-analyze-alignment-design.md`; sync and the data layer now live in `tri-core`.
**Purpose:** A learning project for LangChain that also produces a useful tool: an agent that gives feedback on completed triathlon sessions and analyzes training trends over time, using data from Garmin Connect and TrainingPeaks.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.12 (uv-managed) | Primary LangChain implementation; both MCP servers are Python; garmin_mcp requires 3.12+ |
| LLM | Anthropic Claude, `claude-opus-5` via `langchain-anthropic` | Reliable tool calling over large tool sets, long context, prompt caching |
| Interface | Interactive CLI chat (REPL) | Best for learning: every tool call is visible as it happens |
| Data setup | Garmin auto-syncs to TrainingPeaks; coach plan lives in TP | TP = planned vs. actual; Garmin = physiology and recovery |
| Data layer | Local Postgres store, populated by a sync command | Deterministic trend math, unlimited history, matches Brian's default stack |
| Architecture (milestone 1) | Single LangChain tool-calling agent | Learn the core abstraction first; refactor to LangGraph as milestone 5 |
| Sync mechanism | Plain Python ETL acting as an MCP client (no LLM in the loop) | ETL does not benefit from an LLM; reuses the MCP servers' auth |

## 2. System overview

```
                 ┌──────────────────────┐
  garmin_mcp ───►│                      │
  (stdio)        │  tri-analyze sync    │────► Postgres (tri_analyze db)
  trainingpeaks_ │  (MCP client, ETL)   │            ▲
  mcp (stdio) ──►│                      │            │ read-only SQL
                 └──────────────────────┘            │
                                                     │
                 ┌──────────────────────┐            │
  garmin_mcp ───►│  tri-analyze chat    │────────────┘
  trainingpeaks_ │  LangChain agent     │
  mcp ──────────►│  ChatAnthropic       │◄──── user (terminal REPL)
                 └──────────────────────┘
```

Two entry points share one package:

- `tri-analyze sync` — incremental ETL from both MCP servers into Postgres. No LLM.
- `tri-analyze chat` — the agent REPL. Reads Postgres through a SQL tool and calls a small allow-list of live MCP tools.

## 3. Repository layout

```
tri-analyze-agent/
  pyproject.toml            # uv project, python = ">=3.12,<3.13"
  docker-compose.yml        # postgres:16 on host port 5435
  .env.example              # ANTHROPIC_API_KEY, DATABASE_URL, GARMIN_*, TP_AUTH_COOKIE, LANGSMITH_*
  migrations/
    001_initial.sql
  src/tri_analyze/
    __init__.py
    cli.py                  # typer app: sync, chat, (later) weekly-review
    config.py               # pydantic-settings; loads .env
    mcp/
      servers.py            # server launch specs (command, args, env) for both MCPs
      client.py             # thin wrapper: start server, call tool, parse JSON result
      allowlist.py          # names of the MCP tools the agent may use
    sync/
      garmin.py             # daily metrics, activity ids
      trainingpeaks.py      # athlete profile, planned workouts, completed activities, fitness curve
      runner.py             # orchestrates sources, watermarks, idempotent upserts
    db/
      connection.py         # psycopg3 pool from DATABASE_URL
      repo.py               # typed upsert/select helpers used by sync and tools
    agent/
      tools.py              # query_training_db, get_activity_detail, get_today_readiness
      prompt.py             # system prompt builder (injects athlete profile + current load)
      agent.py              # create_agent(...) assembly
      repl.py               # streaming REPL, prints tool calls
  tests/
    fixtures/mcp/           # recorded JSON responses from both servers
    test_sync_*.py
    test_tools.py
    test_prompt.py
    test_live_smoke.py      # marked `live`, skipped by default
  docs/superpowers/specs/
```

## 4. Data layer

### 4.1 Postgres

- Dedicated container: `postgres:16`, host port **5435**, database `tri_analyze`, user `tri_analyze`. Non-default port avoids collision with the Homebrew Postgres 14 and the other project's Docker Postgres.
- Migrations are numbered plain-SQL files under `migrations/`. **Brian applies them with `psql`**; the assistant writes them but never executes DDL (global rule: database read-only for Claude).
- All timestamps stored as `timestamptz`. Dates that are athlete-local (e.g., "the day's sleep") stored as `date`.

### 4.2 Schema (`001_initial.sql`)

```sql
create table athlete_profile (
  id              int primary key default 1 check (id = 1),   -- single-athlete app
  tp_athlete_id   text,
  ftp_watts       int,
  run_threshold_pace_sec_per_km  int,
  swim_css_sec_per_100m          int,
  lthr_bpm        int,
  max_hr_bpm      int,
  hr_zones        jsonb,           -- per sport: [{zone, low, high}]
  power_zones     jsonb,
  pace_zones      jsonb,
  weight_kg       numeric(5,2),
  raw             jsonb not null,  -- full TP settings payload for anything not modeled
  updated_at      timestamptz not null default now()
);

create table workouts (
  tp_workout_id       text primary key,       -- TP holds planned + actual on one record
  workout_date        date not null,
  sport               text not null,          -- swim | bike | run | brick | strength | race | rest | other
  sport_raw           text,                   -- TP's own label (e.g. "MtnBike")
  title               text,
  description         text,                   -- coach's workout description
  completed           boolean not null default false,
  -- planned
  planned_duration_sec  int,
  planned_distance_m    numeric,
  planned_tss           numeric,
  planned_if            numeric,
  -- actual
  actual_duration_sec   int,
  actual_distance_m     numeric,
  actual_tss            numeric,
  actual_if             numeric,
  normalized_power    int,
  avg_power           int,
  avg_hr              int,
  avg_cadence         numeric,
  elevation_gain_m    numeric,
  calories            int,
  feeling             int,                    -- TP feeling 0–10
  rpe                 int,                    -- TP RPE 0–10
  comments            jsonb,                  -- TP workoutComments (athlete + coach)
  structure           jsonb,                  -- TP structured workout, if present
  garmin_activity_id  text unique,            -- filled by Garmin matching step
  start_time_local    timestamp,              -- from Garmin (TP does not expose start time)
  raw                 jsonb not null,         -- full tp_get_workout payload
  synced_at           timestamptz not null default now()
);
create index on workouts (workout_date);
create index on workouts (sport, workout_date);

create table daily_metrics (
  metric_date       date primary key,
  -- Garmin
  sleep_seconds     int,
  sleep_score       int,
  hrv_overnight_avg int,
  resting_hr        int,
  body_battery_high int,
  body_battery_low  int,
  stress_avg        int,
  training_readiness int,
  garmin_raw        jsonb,
  -- TrainingPeaks fitness curve
  ctl               numeric,
  atl               numeric,
  tsb               numeric,
  tss_day           numeric,        -- per-day TSS from the TP fitness curve
  tp_raw            jsonb,
  synced_at         timestamptz not null default now()
);

create table sync_state (
  source            text primary key,       -- 'garmin' | 'trainingpeaks'
  last_synced_date  date not null,
  last_run_at       timestamptz not null,
  last_status       text not null,          -- 'ok' | 'error'
  last_error        text
);
```

Design notes:
- Every table keeps `raw jsonb` so nothing the servers return is lost. Modeled columns are the ones trend queries need; the agent can `->>` into `raw` for anything else.
- Planned↔actual: verified in the TP server source that one TP workout record carries both planned and actual fields (`tssPlanned`/`tssActual`, `totalTimePlanned`/`totalTime`). One row per TP workout, no linking logic. Decided 2026-09-06 after the spec was first approved.
- The `id = 1` check on `athlete_profile` makes single-athlete explicit; widening later is a migration, not a redesign.

### 4.3 Sync command

`tri-analyze sync [--since YYYY-MM-DD] [--source garmin|trainingpeaks|all] [--full]`

- Default window: from each source's `sync_state.last_synced_date` minus 3 days (overlap catches late-edited workouts) through today. First run defaults to 365 days back.
- Idempotent: every write is an upsert keyed on the natural ID. Re-running is always safe.
- Order: TP athlete profile → TP workouts (list per ≤90-day chunk, then detail per workout) → TP fitness curve → Garmin daily metrics → Garmin activity list (only to populate `workouts.garmin_activity_id` by matching date, sport family, and closest duration within 120 s).
- Default first-run windows differ by source: TP 365 days (a few dozen calls), Garmin 60 days (two calls per day for stats and readiness; Garmin has no range endpoint for these and rate-limits aggressively). Both overridable with `--since`.
- TP list and detail durations are hours as floats and distances are metres; the sync converts to seconds and metres. Verified against the server's `WorkoutSummary`/`WorkoutDetail` models.
- Each source runs in its own try/except; a Garmin failure does not roll back TP data. `sync_state` records per-source status and the last error message.
- Progress printed per stage with row counts.

### 4.4 Sync talks MCP directly

The sync uses the `mcp` Python SDK's stdio client to launch each server and call tools programmatically, without an LLM. Reasons: reuses the servers' auth and caching, stays on the two projects Brian named, and teaches the MCP protocol from the client side.

**Known risk:** MCP tool results are `TextContent` intended for a model. The first task in the plan is a spike that calls the ~6 tools the sync needs and confirms each returns JSON that `json.loads` accepts. If a tool returns prose or Markdown, the fallback for that tool is to import the server's underlying client library (`garminconnect` for Garmin; the TP server's internal API module) directly. The `mcp/client.py` wrapper isolates this so the sync modules don't care which path is used.

## 5. Agent

### 5.1 Assembly

- `create_agent` from `langchain` 1.x with `ChatAnthropic(model="claude-opus-5")`. Adaptive thinking is the model's default; no `thinking` parameter is passed. `max_tokens` is set high enough for long analyses (16k) and responses are streamed.
- Tools bound at startup, in this fixed order (stable order matters for prompt caching):
  1. `query_training_db(sql: str)` — local, read-only
  2. Garmin live via `langchain-mcp-adapters`: `get_activity`, `get_activity_splits`, `get_training_readiness`, `get_hrv_data`
  3. TrainingPeaks live: `tp_get_workout`
  The live tools are the MCP servers' own tools, allow-listed in `mcp/allowlist.py`, not hand-written wrappers (decided 2026-09-06 while planning milestone 4: less code, and it is the LangChain-plus-MCP lesson itself).
- System prompt built by `prompt.py` from the DB at session start: athlete profile (zones, thresholds), last 7 days of load (CTL/ATL/TSB and TSS per day), and today's date. Rendered once per session so the cached prefix stays stable across turns.
- Conversation memory: in-process message list for the life of the REPL session. Cross-session memory is out of scope for milestone 1 (LangGraph checkpointing is a natural milestone-5 addition).

### 5.2 `query_training_db` tool

- Accepts one SQL statement. Rejects anything that does not start with `SELECT` or `WITH`, or that contains a statement separator; runs inside a `READ ONLY` transaction with a statement timeout as the real enforcement. No SQL parser dependency.
- Caps rows at 200 and statement time at 5 s. Returns results as compact JSON with column names.
- Tool description includes the schema summary and 3–4 example queries so the model writes correct SQL on the first try. This description is part of the cached prefix.

### 5.3 What "feedback on a completed session" means

The system prompt instructs the agent to cover, for a session:
1. Planned vs. actual: duration, distance, TSS, intensity; whether the structure was executed.
2. Execution quality: time in zones vs. intent, HR drift or decoupling on steady work, pacing consistency across intervals (from `get_activity_detail` when needed).
3. Context: where the session sits in the week and the current CTL/ATL/TSB; readiness and sleep going in.
4. Athlete's own comments and feel, if present.
5. One or two concrete takeaways. No generic encouragement.

For trend questions the agent is instructed to compute with SQL, not by mental arithmetic, and to state the query window it used.

### 5.4 REPL

- `tri-analyze chat` starts both MCP servers, builds the prompt, and enters a loop.
- Streams assistant tokens to stdout. Prints each tool call as `→ tool_name(args)` and a one-line result summary (row count or byte size) so the learner sees the loop.
- `/tools` lists bound tools; `/prompt` prints the current system prompt; `/quit` exits. `/sync` runs the sync inline.

## 6. MCP integration details

- `langchain-mcp-adapters` `MultiServerMCPClient` with both servers on stdio.
- Garmin launch: `uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@<pinned-sha> garmin-mcp`, with `GARMIN_ENABLED_TOOLS` set so the server registers only the tools we use. Auth: existing tokens in `~/.garminconnect` (already present on this machine); `GARMIN_EMAIL`/`GARMIN_PASSWORD` in `.env` only needed for re-auth.
- TrainingPeaks launch: `uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<pinned-sha> tp-mcp serve`. Auth: `uvx --from <same> tp-mcp auth --from-browser chrome` once (stores the cookie in macOS Keychain, shared across uvx environments) or `TP_AUTH_COOKIE` in `.env`. No vendored clone needed; changed from the first draft for symmetry with Garmin.
- Sessions are opened once per chat with `MultiServerMCPClient.session` and stay open for the chat's lifetime; tools load with `load_mcp_tools`. A server that fails to start is logged and skipped.
- The agent loads only the tools in `mcp/allowlist.py`, not all ~190. Rationale: prompt size, cache stability, and fewer wrong-tool choices. The allow-list is the place to grow the agent's live capabilities later.
- Server start failures are reported clearly at REPL start (which server, what command, stderr tail) and the REPL still opens with the DB tool alone.

## 7. Error handling

| Failure | Behavior |
|---|---|
| MCP server fails to start | Sync: that source is skipped and `sync_state` records the error. Chat: warning printed, live tools for that server not bound. |
| Tool call raises during chat | Error text returned to the model as the tool result; model explains and continues. Never crashes the REPL. |
| Bad SQL from the model | Validation error returned as tool result with the reason; model retries. |
| Auth expired (TP cookie, Garmin token) | Detected from the server's error text; user told exactly which re-auth command to run. |
| Anthropic API error | Typed exceptions caught most-specific-first (`RateLimitError` → `APIStatusError` → `APIConnectionError`); message shown, REPL continues. |
| Partial sync | Per-source isolation; upserts are idempotent so rerun is safe. |

## 8. Configuration

`config.py` uses `pydantic-settings` reading `.env`:

- `ANTHROPIC_API_KEY` (required)
- `DATABASE_URL` (default `postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze`)
- `GARMIN_EMAIL`, `GARMIN_PASSWORD` (optional; re-auth only)
- `TP_AUTH_COOKIE` (optional if `tp-mcp auth` was run)
- `TP_MCP_PATH` (path to the vendored clone)
- `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` (optional; recommended while learning)
- `TRI_MODEL` (default `claude-opus-5`)

## 9. Testing

- `pytest` with `pytest-asyncio`.
- **Unit:** sync parsers against recorded fixture JSON (captured during the spike); planned↔actual linking rules; SQL validator (accepts SELECT, rejects everything else including `SELECT ...; DROP`); prompt builder output.
- **Integration:** sync runner and `query_training_db` against a test database `tri_analyze_test` created from the same migrations. Brian creates the test DB; tests only read/write inside transactions they roll back where possible.
- **Live smoke:** one test per MCP server marked `@pytest.mark.live`, skipped unless `--live` is passed. Confirms the servers still start and the allow-listed tools still exist by name.
- Definition of done per task: tests, `ruff check`, `ruff format --check`, `mypy` (strict on `src/`).

## 10. Observability

LangSmith tracing enabled by env var. Every REPL turn then shows the exact system prompt, tool schemas, model output, tool calls, and token/cache usage. This is the primary learning aid for milestones 3–4 and costs nothing to leave off.

## 11. Milestones (learning path)

1. **Foundation** — uv project, docker-compose Postgres, `001_initial.sql`, config, MCP spike (does each needed tool return JSON?), record fixtures.
2. **Sync** — MCP client wrapper, TP and Garmin sync modules, runner with watermarks, `tri-analyze sync`.
3. **Agent v1** — `create_agent` with only `query_training_db`; system prompt with athlete context; streaming REPL. First real conversations.
4. **Live tools** — `langchain-mcp-adapters` integration, allow-list, `get_activity_detail`, `get_today_readiness`, session-feedback prompt rules.
5. **Later (separate spec)** — LangGraph refactor with typed state and checkpointing; `weekly-review` command; charts.

## 12. Out of scope for this spec

- Multi-athlete support
- Writing back to TP or Garmin (creating workouts, editing notes)
- Web UI
- Scheduled/cron execution
- Cross-session conversation memory

## 13. Open items to verify during milestone 1

- ~~Exact names and JSON-ness of the TP and Garmin tools~~ Verified from source 2026-09-06: TP wraps every result as `json.dumps(dict)` with `isError` on failure; Garmin returns `json.dumps` on success and plain strings starting with "Error" or "No ... found" on failure/empty. Tools used: `tp_get_athlete_settings`, `tp_get_workouts` (90-day max), `tp_get_workout`, `tp_get_fitness`, `get_sleep_summary_range` (90-night max), `get_stats`, `get_training_readiness`, `get_activities_by_date` (paginated), `get_activity_splits`, `get_hrv_data`.
- ~~Whether TP's completed-workout payload carries the planned workout ID~~ Same record; see §4.2.
- ~~`create_agent` / `MultiServerMCPClient` signatures~~ Probed 2026-09-06: `create_agent(model, tools, *, system_prompt, middleware, checkpointer, ...)`; `MultiServerMCPClient(connections: dict[str, StdioConnection], *, tool_name_prefix, handle_tool_errors)` with `get_tools()`; `StdioConnection` keys `transport, command, args, env, cwd`.
- Remaining: the spike still records real fixtures to confirm field units (hours vs seconds) and null patterns.

## Pinned versions (as of 2026-09-06)

langchain 1.4.0 · langchain-anthropic 1.7.1 · langchain-mcp-adapters 0.3.2 (pins `mcp<2`, resolves to 1.29.1) · langgraph 1.2.11 · psycopg 3.3.5

Pinned MCP server commits: garmin_mcp `e8554bcd761a4494dc12a98461224bb3dcf1fbc5` (2026-09-01), trainingpeaks-mcp `a412a84eb4f9c8f03e108a1f27beb053d83a207d` (2026-08-03). The two servers pin incompatible `mcp` majors (Garmin <2, TP ≥2); this is fine because each runs in its own uvx environment and our client speaks the wire protocol.
