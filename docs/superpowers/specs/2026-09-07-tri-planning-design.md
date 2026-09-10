# tri-planning — Triathlon Training Planning Agent (package `tri_planning`)

**Date:** 2026-09-07
**Status:** Approved design, pending implementation plan
**Purpose:** A LangChain/LangGraph learning project that also produces a useful tool: an agent that establishes a training goal, builds a periodized plan on the athlete's TrainingPeaks calendar, and adjusts that plan as training unfolds, using Garmin and TrainingPeaks data already synced to Postgres by the analyze project.

Companion spec: `tri-analyze` design (2026-09-06), which this spec assumes and extends.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Repository layout | uv workspace monorepo at `triathlon_agent/` with `packages/tri-core`, `tri-analyze`, `tri-planning` | Long-term goal is an orchestrator agent composing several agents. One lockfile, one migrations dir, atomic cross-package changes. |
| Plan ownership | Self-coached. The athlete may also activate bought TrainingPeaks plans and let the agent adjust them. | No human coach today. |
| Write safety | Propose, then the athlete approves. The graph pauses with `interrupt()` before any TrainingPeaks write. | Mistakes stay cheap while prompts are being tuned. Human-in-the-loop is a core LangGraph concept. |
| Plan generation | Python owns periodization (phases, weekly targets); the LLM designs sessions within those bounds. | Deterministic load math is testable; the model does what it is good at. |
| Architecture | Hand-built LangGraph `StateGraph`; `create_agent` sub-agents inside the two conversational nodes | Maximizes LangChain, LangGraph and LangSmith exposure; the result is a graph an orchestrator can embed as a subgraph. |
| Horizon | Rolling window: all week targets in our DB, next `TRI_PLANNING_HORIZON_WEEKS` (default 3) of sessions written to TrainingPeaks | Adjustments stay cheap; the calendar never carries stale sessions. |
| Adjustments | Manual via chat, plus a `check-in` command that runs the review non-interactively | Prepares for orchestrator and scheduled runs. |
| Interface | Terminal REPL and CLI | Same as analyze; every node transition is visible. |
| LLM | `claude-opus-5` via `langchain-anthropic`, same as analyze | Reliable tool calling and structured output. |

## 2. Feasibility, verified 2026-09-07

The pinned `trainingpeaks-mcp` commit (`a412a84e`, same as analyze) exposes write tools. Verified from source:

- `tp_create_workout(date_str, sport, title, duration_minutes?, description?, distance_km?, tss_planned?, structure?, structured_workout?, ...)`. The simplified `structure` format is `{primaryIntensityMetric, steps: [{name, duration_seconds, intensity_min, intensity_max, intensityClass} | {type: "repetition", reps, steps: [...]}]}`; the server derives duration, IF and TSS from it when not given.
- `tp_update_workout`, `tp_delete_workout`, `tp_copy_workout`, `tp_reorder_workouts`.
- `tp_create_event(name, date, event_type?, priority?, distance_km?, ctl_target?, description?)`; `event_type` includes `MultisportTriathlon`.
- `tp_list_training_plans`, `tp_get_training_plan`, `tp_get_training_plan_workouts`, `tp_apply_training_plan(plan_id, start_date)`.
- `tp_create_availability`, `tp_get_atp` (read-only; there is no ATP write, so weekly targets live in our DB).

`langchain` 1.4.0 ships `HumanInTheLoopMiddleware`, but this design uses `langgraph.types.interrupt` directly because the graph, not a middleware, owns the pause point. `langgraph-checkpoint-postgres` provides `PostgresSaver` and is a new dependency.

## 3. System overview

```
                 ┌──────────────────────┐
  garmin_mcp ───►│   tri sync           │────► Postgres (shared db)
  tp_mcp ───────►│   (tri-core ETL)     │        ▲            ▲
                 └──────────────────────┘        │ read-only  │ plan tables,
                                                 │ SQL        │ checkpoints, audit
                 ┌──────────────────────┐        │            │
  garmin_mcp ───►│  tri-planning        │────────┘            │
  (readiness,    │  LangGraph StateGraph│─────────────────────┘
   hrv, live)    │   intake ─► targets ─► design ─► review ─► apply
  tp_mcp ───────►│   adjust ───────────────────────┘    │
  (read live;    │                                       └── interrupt(): athlete approves
   write only    └──────────────────────┘
   in apply)              ▲
                          │ tri-planning chat | check-in | reset
```

## 4. Workspace layout

```
triathlon_agent/                      git root, uv workspace, one uv.lock
  pyproject.toml                      [tool.uv.workspace] members = ["packages/*"]; shared ruff/mypy/pytest config
  docker-compose.yml                  moved from tri-analyze-agent (postgres:16, host port 5435)
  .env.example                        union of both agents' settings
  migrations/                         001_initial.sql (moved), 002_planning.sql (new)
  docs/superpowers/specs/, plans/
  packages/
    tri-core/                         no LLM code
      src/tri_core/
        config.py                     pydantic-settings (moved)
        mcp/                          servers.py, client.py (moved); allow-lists stay with agents
        db/                           connection.py, models.py, repo.py (moved)
        sync/                         all of it (moved)
        cli.py                        `tri sync`
        testing/                      db fixture, ScriptedChatModel fake (moved from analyze tests)
      tests/
    tri-analyze/
      src/tri_analyze/
        agent/                        unchanged; imports tri_core
        allowlist.py                  moved from mcp/
        cli.py                        `tri-analyze chat`
      tests/
    tri-planning/
      src/tri_planning/
        cli.py                        chat, check-in, reset
        config.py                     TRI_PLANNING_HORIZON_WEEKS and LangSmith project name
        allowlist.py                  live read tools per sub-agent; write tools for apply only
        planning/
          models.py                   TrainingGoal, PlannedSession, PlannedWeek, CalendarChange
          periodization.py            constants: phase tables, ramp caps, recovery cadence, taper
          targets.py                 goal + fitness -> list of week targets (pure)
          validate.py                 PlannedWeek vs week target and constraints (pure)
        graph/
          state.py                    PlanningState TypedDict
          graph.py                    build_graph(model, tools, checkpointer) -> CompiledStateGraph
          nodes/
            intake.py                 create_agent sub-agent, exits on set_training_goal
            targets.py               calls planning.targets, writes training_plans/plan_weeks
            design.py                 structured-output call per week, validate, retry once
            review.py                 interrupt(); returns decision
            apply.py                  translates CalendarChange -> TP tool calls; audit rows
            adjust.py                 create_agent sub-agent, exits on propose_calendar_changes
        tools/
          goal.py                     set_training_goal, list_tp_training_plans
          changes.py                  propose_calendar_changes
          design_next_week.py         adjust-only: designs the next target week via the design prompt
        prompts/
          intake.py, design.py, adjust.py, checkin.py
        repl.py                       streaming loop, review table, /status /pending
        repo.py                       planning-table reads and writes
      tests/
```

Dependency direction: `tri-analyze` and `tri-planning` depend on `tri-core`. Neither depends on the other. The future orchestrator depends on all three.

### 4.1 Migration of the existing repos (milestone 1)

- `tri-analyze-agent/.git` (two commits, GitHub remote) becomes `triathlon_agent/.git`, so history is preserved. Files are moved with `git mv` into `packages/tri-analyze`, then the core modules are moved again into `packages/tri-core`.
- `tri-planning-agent/` has an empty `.git` and is deleted.
- Brian runs every git command; the assistant prints them. The implementation plan lists them verbatim as its first task.
- Definition of done for the restructure: `uv sync` at the root, all existing analyze tests green, `tri sync` and `tri-analyze chat` still work.

## 5. Data model, `migrations/002_planning.sql`

Existing tables are untouched.

```sql
create table training_goals (
  id                serial primary key,
  goal_type         text not null,      -- sprint | olympic | half_ironman | ironman | maintenance | build | recovery
  event_name        text,
  event_date        date,               -- null for maintenance/build/recovery
  tp_event_id       text,               -- set if we created the race event in TP
  priority          text,               -- A | B | C
  weekly_hours_min  numeric,
  weekly_hours_max  numeric,
  available_days    jsonb not null,     -- {"mon": ["swim"], "tue": ["bike","run"], "sat": "any", "sun": []}
  constraints       jsonb,              -- free-form list of strings from intake
  status            text not null default 'active',   -- active | completed | abandoned
  created_at        timestamptz not null default now()
);

create table training_plans (
  id            serial primary key,
  goal_id       int not null references training_goals,
  source        text not null,          -- generated | tp_plan
  tp_plan_id    text,
  start_date    date not null,
  end_date      date not null,
  targets       jsonb not null,         -- [{week_start, phase, target_tss, target_hours, is_recovery, flags, sport_hint}]
  status        text not null default 'active',   -- active | superseded | completed
  created_at    timestamptz not null default now()
);

create table plan_weeks (
  plan_id       int not null references training_plans,
  week_start    date not null,          -- Monday
  phase         text not null,          -- base | build | peak | taper | race | recovery
  target_tss    numeric,
  target_hours  numeric,
  designed      jsonb,                  -- validated PlannedWeek; null outside the rolling window
  written_to_tp boolean not null default false,
  primary key (plan_id, week_start)
);

create table plan_changes (
  id            serial primary key,
  plan_id       int references training_plans,
  thread_id     text not null,
  operation     text not null,          -- create | update | delete | move | apply_plan | create_event
  tp_workout_id text,
  workout_date  date,
  payload       jsonb not null,         -- exactly what we sent
  result        jsonb,                  -- exactly what TP returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index on plan_changes (tp_workout_id);
```

Notes:

- The targets cover the whole block; `plan_weeks.designed` is filled only inside the rolling window.
- `plan_changes` is both audit trail and ownership record. A calendar workout is agent-authored iff its `tp_workout_id` appears here. Adjust reads it before proposing update, move or delete.
- LangGraph checkpoints live in the same database via `PostgresSaver`. Its `setup()` creates its own tables; Brian runs it once by hand (documented in the README) so the app never executes DDL.
- Migrations are applied by Brian with `psql`, to both `tri_analyze` and `tri_analyze_test`, per the global read-only rule.

## 6. The graph

### 6.1 State

```python
class PlanningState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    phase: Literal["intake", "planning", "active"]
    goal_id: int | None
    plan_id: int | None
    pending_changes: list[CalendarChange]
    pending_summary: str | None
    review_decision: ReviewDecision | None     # approve | reject(note) | edit(changes)
    last_error: str | None
```

Persisted per thread by `PostgresSaver`. `chat`, `check-in` and `reset` all use thread `planning`; `reset` starts a new thread id and marks the old goal and plan abandoned.

### 6.2 Nodes and edges

```
START -> route
route: phase == intake   -> intake
       phase == planning -> targets
       phase == active   -> adjust
intake   -> targets  (when set_training_goal was called)  | END (turn ended without a goal)
targets -> design    (source = generated)
targets -> review    (source = tp_plan: a single apply_plan change)
design   -> review
adjust   -> review    (when propose_calendar_changes was called) | END
review   -> apply     (approve or edit) | design or adjust (reject, with note as a HumanMessage)
apply    -> targets  (after apply_plan: derive week targets from the applied workouts, then END)
apply    -> END       (otherwise)
```

- **intake**: a `create_agent` sub-agent with tools `query_training_db`, `list_tp_training_plans`, `set_training_goal`. Its system prompt lists the goal types, what it must establish (goal type, event and date, priority, weekly hour range, available days per sport, constraints, whether to activate a bought TP plan), and tells it to warn when the available weeks are below the minimum for the goal. `set_training_goal` validates a `TrainingGoal` Pydantic model, inserts the row, sets `goal_id` and `phase = planning`.
- **targets**: pure Python, no model call. Reads goal, `athlete_profile`, and fitness from `daily_metrics`. For `source = generated` it calls `planning.targets.build`, writes `training_plans` and `plan_weeks`, and routes to design. For `source = tp_plan` it emits one `CalendarChange(op="apply_plan")` and routes to review; after apply, the graph re-enters targets, which reads the applied workouts with `tp_get_workouts`, records their ids in `plan_changes` for ownership, derives week targets by summing planned TSS per week, writes `training_plans` and `plan_weeks` with `written_to_tp = true`, and ends with `phase = active`. Bought plans skip design because their sessions already exist.
- **design**: for each week in the window without `designed`, one `with_structured_output(PlannedWeek)` call with the week target, sport hint, availability, constraints, thresholds and zones, and the previous designed week. Runs `validate.week`; on violations, retries once with the violation list. Converts sessions to `CalendarChange(op="create")` and sets `pending_changes`. Traces are tagged `week_start` and `phase`.
- **review**: `interrupt({"summary", "changes"})`. The REPL renders the change set and collects a `ReviewDecision`. Resume is `Command(resume=decision)`. Reject routes back to the node that produced the changes with the note appended as a `HumanMessage`.
- **apply**: translates each `CalendarChange` to one TP call, checks ownership for update, move and delete against `plan_changes`, records payload and result per change, marks `plan_weeks.written_to_tp`, sets `phase = active`. A failed call stops the batch; the partial result is recorded and returned in `last_error`.
- **adjust**: a `create_agent` sub-agent with tools `query_training_db`, Garmin live `get_training_readiness`, `get_hrv_data`, TP live `tp_get_workouts`, and `propose_calendar_changes`. Its prompt encodes the review checklist and the lever order (swap days, shorten, downgrade intensity, drop, re-plan the week). It also extends the window when fewer than two designed weeks remain by emitting `create` changes for the next target week, using the same design prompt via a tool `design_next_week`.

Write tools are never bound to a sub-agent. Only `apply` holds the write allow-list.

### 6.3 Models

```python
class TrainingGoal(BaseModel):
    goal_type: GoalType
    event_name: str | None
    event_date: date | None
    priority: Literal["A", "B", "C"] | None
    weekly_hours_min: float
    weekly_hours_max: float
    available_days: dict[Weekday, list[Sport] | Literal["any"]]
    constraints: list[str]
    tp_plan_id: str | None
    create_tp_event: bool

class PlannedSession(BaseModel):
    date: date
    sport: Sport                       # swim | bike | run | brick | strength | rest
    title: str
    description: str
    duration_minutes: int
    tss_planned: float
    intensity: Literal["recovery", "endurance", "tempo", "threshold", "vo2", "race"]
    structure: dict | None             # TP simplified structure

class PlannedWeek(BaseModel):
    week_start: date
    sessions: list[PlannedSession]
    coach_note: str

class CalendarChange(BaseModel):
    op: Literal["create", "update", "delete", "move", "apply_plan", "create_event"]
    workout_date: date | None
    tp_workout_id: str | None
    workout: PlannedSession | None
    new_date: date | None
    payload: dict | None               # for apply_plan / create_event
    reason: str
```

## 7. Planning logic (`planning/`)

### 7.1 Phase allocation, working backward from the event

| Goal | Race week | Taper | Peak | Build | Base | Minimum weeks |
|---|---|---|---|---|---|---|
| Sprint | 1 | 1 | 2 | 4 | remaining | 8 |
| Olympic | 1 | 1 | 3 | 5 | remaining | 12 |
| Half Ironman | 1 | 2 | 3 | 6 | remaining | 16 |
| Ironman | 1 | 3 | 4 | 8 | remaining | 20 |
| Build (no race) | 0 | 0 | 0 | all | 0 | 4 |
| Maintenance | 0 | 0 | 0 | 0 | all, flat | 2 |
| Recovery | 0 | 0 | 0 | 0 | all, reduced | 1 |

With fewer weeks than the minimum: drop base first, then shorten build; flag the plan `compressed`. Intake reports this before the goal is committed.

### 7.2 Load progression

- Week 1 target TSS = recent 4-week average weekly TSS from `daily_metrics.tss_day`, else 7 × current CTL, else a per-goal floor constant.
- Base and build ramp at most 8 % per week, additionally capped so the modeled CTL rise is at most 5 points per week (whichever binds first).
- Recovery week every 4th week at 60 % of the previous week; every 3rd during Ironman build.
- Peak holds load at the block maximum; the sport hint asks for intensity, not volume.
- Taper weeks are 80 %, 60 %, 45 % of peak in order; race week 30 % of peak, excluding the race itself.
- Maintenance: flat at week 1 load. Recovery goal: 50 % of week 1 load, flat.
- Target hours derive from target TSS at an assumed intensity factor per phase (base 0.70, build 0.75, peak 0.80, taper 0.75, recovery 0.65), then clamp to the athlete's hour range. If the clamp binds, TSS is recomputed from the hours cap and the week is flagged `hours_capped`.
- Sport hints per phase are strings passed to the design prompt: base = swim and run frequency, aerobic bike; build = bike volume and one brick; peak = race-specific bricks and race-pace work; taper = keep frequency, cut duration.
- For `tp_plan` sources the targets are derived from the applied plan's weekly planned TSS, and phases are inferred from the load curve (rising = build, flat top = peak, falling into the event = taper).

All constants live in `periodization.py`.

### 7.3 Validation (`validate.py`)

A `PlannedWeek` is rejected when: total TSS is more than 10 % from target; any session falls on a day marked unavailable or on a day whose allowed sports exclude that sport; two sessions with intensity in {threshold, vo2, race} fall on consecutive days; total hours exceed the athlete's weekly max; a `structure` is present but its steps do not sum to the session duration within 5 minutes. Violations are returned as a list of strings.

## 8. Commands

- `tri-planning chat`: REPL. Streams tokens, prints `→ tool(args)` and `← tool: N chars` as in analyze. On interrupt, prints the change set grouped by week with the reason column and prompts `approve / reject <note> / edit`. `edit` opens the change set as YAML in `$EDITOR`. `/status` prints goal, phase, this week's target versus actual TSS, and designed weeks remaining. `/pending` re-prints a paused change set. `/sync` runs `tri sync`. `/quit`.
- `tri-planning check-in [--yes]`: runs `tri sync`, then invokes the graph on thread `planning` with the fixed check-in prompt: review the last 7 days against plan, flag sessions with RPE ≥ 8 or feeling ≤ 3, compare 3-day readiness and HRV to the 30-day baseline, note TSB entering the week, extend the window if fewer than 2 designed weeks remain. Prints the proposed change set and exits paused at review. `--yes` resumes with approve immediately.
- `tri-planning reset`: marks active goal and plan abandoned, starts a new thread. Never touches TrainingPeaks.

## 9. Error handling

| Failure | Behavior |
|---|---|
| MCP server fails to start | Sub-agent binds without that server's tools; a warning names the server. `apply` refuses to run without the TP server and leaves the change set pending. |
| TP write fails mid-batch | Batch stops. Applied changes are recorded. `last_error` names the failed change; the REPL prints applied versus not applied. Re-running review re-proposes only the unapplied remainder. |
| Design validation fails twice | The week surfaces at review with the violations listed; the athlete can edit or reject with guidance. |
| Ownership check fails | The change is dropped from the batch with a printed reason unless the reason field contains an explicit athlete instruction captured at intake or in chat. |
| Auth expired | Detected from server error text; the exact re-auth command is printed (same as analyze). |
| Anthropic API error | Caught per turn, printed, REPL continues. Graph state is at the last checkpoint. |
| Checkpointer unavailable | `chat` refuses to start with a clear message; there is no in-memory fallback because review decisions must survive process exit. |

## 10. Configuration

`tri_core.config` is shared. `tri_planning.config` adds `TRI_PLANNING_HORIZON_WEEKS` (default 3) and `LANGSMITH_PROJECT` default `tri-planning`. New dependency: `langgraph-checkpoint-postgres`.

## 11. Testing

- **Unit, no DB, no model:** every row of the phase table; ramp, recovery, taper and hours-cap rules; validator rules one by one; `CalendarChange` to TP-call translation; YAML edit round trip.
- **Graph, `ScriptedChatModel`:** intake ends on `set_training_goal`; review pauses and `Command(resume=approve)` reaches apply; reject routes back with the note in messages; a second process resumes the thread from Postgres; adjust ends on `propose_calendar_changes`.
- **Apply, fake TP client:** ownership refusal, mid-batch failure, one `plan_changes` row per call.
- **DB tests** use the `tri_analyze_test` database and the rolled-back `db` fixture from `tri_core.testing`.
- **Live, opt-in:** create a workout 400 days out, update it, delete it, assert gone.
- Definition of done per task: `uv run pytest`, `ruff check`, `ruff format --check`, `mypy` strict on `src/`.

## 12. Observability

LangSmith tracing by env, project `tri-planning`. Design calls carry `week_start` and `phase` tags. Milestone 4 adds a LangSmith dataset of target weeks and a code evaluator that runs `validate.week` on the output, giving a pass rate per prompt version.

## 13. Milestones

1. **Workspace.** Restructure into `triathlon_agent/`, extract `tri-core`, both agents import from it, all existing tests green. No new behavior.
2. **Targets and schema.** `002_planning.sql`, `periodization.py`, `targets.py`, `validate.py`, models, all unit-tested. No model calls.
3. **Graph v1.** State, intake sub-agent, targets and design nodes, review interrupt, apply, Postgres checkpointer, `chat`. First plan on the calendar.
4. **Adjust and check-in.** Adjust sub-agent, `check-in`, window extension, LangSmith evaluator dataset.
5. **Later, separate spec.** Orchestrator composing analyze and planning as subgraphs.

## 14. Out of scope

Multi-athlete; nutrition; strength-workout structure (separate TP tool set); writing to Garmin; any UI beyond the terminal; scheduled execution; editing bought TP plans' library content.

## 15. Open items to verify in milestone 1

- Exact `PostgresSaver` setup and connection-string handling with psycopg 3 pools.
- Whether `tp_apply_training_plan` returns the created workout ids (needed to populate `plan_changes` ownership) or whether a follow-up `tp_get_workouts` is required.
- How `tp_create_workout` reports the new `workout_id` in its result payload.
- `uv` workspace behavior for `[project.scripts]` entry points across members.

Resolved in milestone 3 (first real conversation, 2026-09-10):

- `AsyncPostgresSaver.from_conn_string` already sets autocommit, `prepare_threshold=0` and `dict_row`; no custom connection handling needed. The saver is built with `JsonPlusSerializer(allowed_msgpack_modules=...)` listing the Pydantic models that live in state, otherwise every load logs an "unregistered type" warning.
- `tp_apply_training_plan` returns only counts; ownership needs the follow-up `tp_get_workouts` (targets node).
- `tp_create_workout` returns `{"success", "workout_id", ...}`. Its MCP input schema names the date field `date`, not `date_str` as in the Python signature; the server's dispatch maps one to the other. Plan 3's global constraints had this wrong and `tp_calls.to_tp_call` was corrected.
