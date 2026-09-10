# tri-nutrition — Endurance Nutrition Agent (package `tri_nutrition`)

**Date:** 2026-09-10
**Status:** Approved design, pending implementation plan
**Purpose:** A LangChain/LangGraph learning project that also produces a useful tool: an agent that interviews the athlete about diet, restrictions, habits, body composition and physique goals, then derives periodized daily nutrition targets and per-session fueling plans from the training plan, writes them to Garmin Connect and TrainingPeaks after approval, and checks in against logged intake and body composition as training unfolds.

Companion specs: `tri-analyze` (2026-09-06) and `tri-planning` (2026-09-07). This spec assumes both and copies their patterns.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Package | `packages/tri-nutrition`, module `tri_nutrition`, command `tri-nutrition`; depends on `tri-core` only | Same rule as the other agents: no agent imports another. Planning's tables are read through SQL. |
| Architecture | Hand-built LangGraph `StateGraph`; `create_agent` sub-agents inside the two conversational nodes; Python owns the math | Same shape as planning, so every piece has a proven twin. Embeddable as a subgraph by the future orchestrator. |
| Long-term memory | The athlete's nutrition profile, fuel log and product library live in the LangGraph Store (`AsyncPostgresStore`), not in a table | The profile is memory that must outlive threads. This is the learning goal of the project. |
| Time series | Daily targets, fuel plans and the write audit live in Postgres tables (`003_nutrition.sql`) | Trend queries and audit are SQL-shaped; the Store is key-value. |
| Write safety | Propose, then approve. `interrupt()` before any Garmin or TrainingPeaks write | Same as planning. |
| Targets | Python derives daily calorie and macro targets from RMR, body mass and the planned sessions; the LLM writes fueling notes and the race-day plan within Python-checked bounds | Deterministic, testable safety math; the model does prose and product choice. |
| Horizon | Rolling window of `TRI_NUTRITION_HORIZON_DAYS` (default 14) days of targets and notes | Targets change when the plan changes; the window is cheap to regenerate. |
| Data sources | Garmin Connect (Index scale body composition, food log, nutrition settings), TrainingPeaks (calendar, notes), local Postgres (plan tables, workouts, metrics) | Verified 2026-09-10 that the athlete uses a Garmin Index scale and logs food in Garmin Connect. |
| Interface | Terminal REPL and CLI | Same as the other agents. |
| LLM | `claude-opus-5` via `langchain-anthropic` | Same as the other agents. |
| Learning goals | LangGraph Store, subgraph-ready composition, LangSmith evaluation | Chosen 2026-09-10. |

## 2. Feasibility, verified 2026-09-10

Verified from the pinned server sources (garmin_mcp `e8554bcd`, trainingpeaks-mcp `a412a84e`) and the installed packages (langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2).

Garmin MCP tools (all take `YYYY-MM-DD` dates and return `json.dumps` on success, a plain string on empty or error):

- `get_body_composition(start_date, end_date?)`: weight, BMI, body fat %, muscle mass, bone mass, body water % from the Index scale.
- `get_daily_weigh_ins(date)`, `get_user_profile()`.
- `get_nutrition_daily_food_log(date)`: logged items with calories and macros per item.
- `get_nutrition_daily_meals(date)`: per-meal totals.
- `get_nutrition_daily_settings(date)`: current calorie and macro targets.
- `set_nutrition_daily_settings(date, calorie_goal?, carbs_grams?, fat_grams?, protein_grams?)`: read-modify-write of the day's targets; Garmin silently corrects a calorie goal that disagrees with `4c + 4p + 9f`.
- `get_hydration_data(date)`, `get_stats(date)` (daily total and BMR kcal).

These tools are not in `GARMIN_ENABLED_TOOLS` today. `tri_core.mcp.servers.garmin_spec` gains an `enabled_tools` parameter so each agent registers the set it needs; the default stays the current list.

TrainingPeaks MCP tools:

- `tp_set_workout_note(workout_id, note)`: the note field on a calendar workout.
- `tp_create_note(date, title, description?)`, `tp_update_note`, `tp_delete_note`, `tp_get_note`, `tp_list_notes`: calendar notes.
- `tp_get_metrics(start_date, end_date)`, `tp_log_metrics(date, weight_kg?, rmr?, ...)`, `tp_get_nutrition(start_date, end_date)`, `tp_update_nutrition(planned_calories)`: read-only use in this spec, except that `tp_update_nutrition` is not used because it carries only one planned calorie value.

LangGraph: `AsyncPostgresStore.from_conn_string(url)` with `setup()`; `StateGraph.compile(store=...)` and `create_agent(..., store=...)` both accept it; tools reach the store through `get_store()` from `langgraph.config` or the injected runtime.

## 3. System overview

```
                     ┌──────────────────────┐
  garmin_mcp ───────►│  tri sync            │──► Postgres (shared db)
  tp_mcp ───────────►│  (tri-core ETL)      │      ▲          ▲          ▲
                     └──────────────────────┘      │ SQL      │ targets, │ LangGraph Store
                                                   │ read     │ fuel     │ (profile, fuel log,
                     ┌──────────────────────┐      │          │ plans,   │  product library)
  garmin_mcp ───────►│  tri-nutrition       │──────┘          │ audit    │
  (body comp, food   │  LangGraph StateGraph│─────────────────┴──────────┘
   log, settings)    │  intake ─► targets ─► fuel ─► review ─► apply
  tp_mcp ───────────►│  checkin ───────────────────────┘  │
  (calendar, notes)  │                                     └── interrupt(): athlete approves
                     └──────────────────────┘
                              ▲
                              │ tri-nutrition chat | check-in | reset
```

## 4. Package layout

```
packages/tri-nutrition/
  pyproject.toml                     tri-nutrition; depends on tri-core; script tri-nutrition
  src/tri_nutrition/
    cli.py                           chat, check-in, reset [--forget-profile]
    config.py                        TRI_NUTRITION_HORIZON_DAYS (14), LangSmith project tri_nutrition
    allowlist.py                     Garmin read tools per node; Garmin and TP write tools for apply only
    store.py                         open_store(url); NAMESPACE = ("athlete", "nutrition"); typed get/put
    repo.py                          nutrition_targets, fuel_plans, nutrition_changes reads and writes
    nutrition/                       pure Python, no model calls
      models.py                      NutritionProfile, Product, DayTarget, SessionFuel, RaceFuelPlan,
                                     RaceFuelStep, NutritionChange, ReviewDecision
      constants.py                   macro table, activity factors, deficit and surplus sizes, bounds
      energy.py                      rmr(), session_kcal(), day_type()
      targets.py                     build(profile, sessions, phases, today, horizon) -> list[DayTarget]
      bounds.py                      validate_targets(), validate_fuel(), validate_race()
    graph/
      state.py                       NutritionState TypedDict
      deps.py                        GraphDeps: model, connect, db_url, garmin, tp, today, horizon
      llm.py                         make_model, make_subagent (copied from planning)
      checkpointer.py                open_checkpointer with the state's Pydantic types registered
      graph.py                       build_graph(deps, checkpointer, store)
      nodes/
        intake.py                    create_agent sub-agent; exits on save_nutrition_profile
        targets.py                   pure Python; writes nutrition_targets; sets pending targets
        fuel.py                      structured-output calls per session and for the race
        review.py                    interrupt(); returns ReviewDecision
        apply.py                     NutritionChange -> Garmin or TP call; audit rows
        checkin.py                   create_agent sub-agent; exits on propose_target_changes or END
    tools/
      profile.py                     save_nutrition_profile, read_nutrition_profile
      plan.py                        read_training_plan (goal, phase per week, sessions in the horizon)
      checkin.py                     record_fuel_feedback, propose_target_changes
    prompts/
      intake.py, fuel.py, race.py, checkin.py
    repl.py                          streaming loop, target table, race timeline, /status /profile /pending
  tests/
migrations/003_nutrition.sql
scripts/setup_checkpointer.py        also runs AsyncPostgresStore.setup()
```

## 5. Data model

### 5.1 The Store (long-term memory)

Namespace `("athlete", "nutrition")`. Three keys:

| Key | Value | Written by |
|---|---|---|
| `profile` | `NutritionProfile.model_dump()` | `save_nutrition_profile` (intake), edited later in chat through the same tool |
| `fuel_log` | `{"entries": [FuelLogEntry, ...]}`: date, tp_workout_id, sport, duration, carbs_g_per_h taken, products, outcome (`ok`, `gi_upset`, `bonk`, `cramps`, `other`), note | `record_fuel_feedback` (check-in and chat) |
| `product_library` | `{"products": [Product, ...]}`: name, form (gel, chew, drink, bar, real food), carbs_g, sodium_mg, caffeine_mg per serving | `save_nutrition_profile` seeds it from `tested_products`; `record_fuel_feedback` may add a product with `tested: true` after a good outcome |

Every node reads `profile` at entry. `reset` never touches the Store unless `--forget-profile` is passed, which deletes all three keys.

### 5.2 Tables, `migrations/003_nutrition.sql`

```sql
create table nutrition_targets (
  day               date primary key,
  day_type          text not null,        -- rest | easy | moderate | hard | long | race | carb_load
  session_kcal      int not null,
  total_kcal        int not null,
  carbs_g           int not null,
  protein_g         int not null,
  fat_g             int not null,
  fluid_baseline_ml int not null,
  notes             jsonb not null default '[]',
  plan_phase        text,                 -- copied from plan_weeks.phase when a plan exists
  source            text not null,        -- plan | tp_calendar | profile_hours
  written_to_garmin boolean not null default false,
  generated_at      timestamptz not null default now()
);

create table fuel_plans (
  id            serial primary key,
  kind          text not null,            -- session | race
  day           date not null,
  tp_workout_id text,                     -- session plans
  tp_note_id    text,                     -- race plans, once written
  payload       jsonb not null,           -- SessionFuel or RaceFuelPlan
  violations    jsonb not null default '[]',
  written       boolean not null default false,
  generated_at  timestamptz not null default now()
);
create unique index on fuel_plans (kind, day, coalesce(tp_workout_id, ''));

create table nutrition_changes (
  id            serial primary key,
  thread_id     text not null,
  operation     text not null,            -- set_day_targets | set_session_note | set_race_note
  target_key    text not null,            -- the date, workout id or note id
  payload       jsonb not null,           -- exactly what we sent
  result        jsonb,                    -- exactly what the server returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index on nutrition_changes (operation, target_key);
```

`nutrition_changes` is both audit and ownership: a TP note is agent-authored iff its id appears here, and `apply` only updates or replaces notes it owns. Checkpoint and Store tables are created by `scripts/setup_checkpointer.py`, run once per database by Brian. Migrations are applied by Brian with `psql` to both `tri_analyze` and `tri_analyze_test`.

## 6. The graph

### 6.1 State

```python
class NutritionState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    has_profile: bool                      # set by the route node from the Store each run
    profile_overrides: dict[str, Any] | None  # from propose_target_changes; persisted on approve
    regenerate_from: Literal["intake", "checkin"] | None
    pending_changes: list[NutritionChange]
    pending_summary: str | None
    review_decision: ReviewDecision | None
    last_error: str | None
```

Persisted per thread by `AsyncPostgresSaver` on thread `nutrition`. The Store is opened in the same `AsyncExitStack` and passed to `compile(store=...)`.

### 6.2 Nodes and edges

```
START   -> route    (a node: reads the Store, sets has_profile)
route   -> review   (pending_changes) | intake (no profile) | checkin
intake  -> targets  (save_nutrition_profile was called) | END
targets -> fuel     | END (bounds violated)
fuel    -> review
review  -> apply    (approve or edit) | intake or checkin (reject, note appended as HumanMessage) | END
apply   -> END
checkin -> targets  (save_nutrition_profile or propose_target_changes was called) | END
```

Edge functions are pure over state, so a `route` node does the one Store read that routing needs.

- **intake**: `create_agent` sub-agent with `query_training_db`, `read_training_plan`, Garmin live `get_body_composition`, `get_user_profile`, `get_nutrition_daily_settings`, and `save_nutrition_profile`. The prompt tells it to open by reading weight, body fat, age and the current Garmin targets so it confirms rather than asks cold; then to establish, in order: goal and timeline; dietary pattern, allergies, intolerances and medical restrictions; GI history by sport; meals, cooking, caffeine, alcohol, food tracking and scale cadence; tested products and sweat rate; constraints. It warns when a `lose` goal overlaps peak, taper or race weeks of the active plan, and when the requested rate exceeds `max_weekly_change_pct`. Language suggesting disordered eating triggers a fixed referral message and the tool refuses `goal = lose`. After confirmation it calls `save_nutrition_profile` once and replies with a fixed sentence. Later profile edits happen in chat through the checkin sub-agent, which also holds `save_nutrition_profile`; the tool overwrites the Store key and the graph regenerates targets.
- **targets**: pure Python. Reads the profile from the Store, the horizon's sessions from `plan_weeks.designed` and `workouts` (planned, not completed), and phases from `plan_weeks`. Calls `targets.build`, runs `bounds.validate_targets`; on violations it writes nothing, puts the violations in `last_error` and an `AIMessage`, and routes to END. Otherwise upserts `nutrition_targets` and emits one `set_day_targets` change per day whose kcal or macros differ from the row's previous values when that row had `written_to_garmin = true`, or for every day otherwise. `profile_overrides` in state are applied on top of the Store profile before building.
- **fuel**: for each session in the horizon with duration over 75 minutes or intensity in {threshold, vo2, race}, one `with_structured_output(SessionFuel)` call; for the goal event when it lies within 21 days, one `with_structured_output(RaceFuelPlan)` call. Inputs are the profile, product library, fuel log, the session, and that day's `DayTarget`. Runs `bounds.validate_fuel` or `validate_race`; retries once with the violation list; then upserts `fuel_plans` with any remaining violations and emits `set_session_note` and `set_race_note` changes. Traces are tagged `day` and `kind`.
- **review**: `interrupt({"summary", "changes"})`. Resume is `Command(resume=decision)`. Reject routes to the conversational node that started the run (`regenerate_from`: intake or checkin) with the note appended as a `HumanMessage`, so the athlete can say what to change.
- **apply**: translates each `NutritionChange` to one server call, checks the Garmin calorie goal against `4c + 4p + 9f` (recomputes the goal from the macros when off by more than 20 kcal), checks note ownership, records a `nutrition_changes` row per call, marks `written_to_garmin` and `written`, and persists any `profile_overrides` into the Store profile. A failed call stops the batch; the partial result lands in `last_error`.
- **checkin**: `create_agent` sub-agent with `query_training_db`, `read_training_plan`, Garmin live `get_body_composition`, `get_nutrition_daily_food_log`, `get_nutrition_daily_meals`, `get_hydration_data`, and the commit tools `record_fuel_feedback` and `propose_target_changes`. Its prompt encodes the check-in: logged intake versus target per day type over 7 days; weight and body fat trend over 14 and 28 days against the goal rate; low-intake days followed by poor readiness or sleep; TP workout comments mentioning GI trouble; whether fewer than 7 days of targets remain. `propose_target_changes` accepts profile field overrides (for example a changed activity factor or a paused deficit) and a reason; it writes them to `profile_overrides` in state and sets `regenerate_from = "checkin"`. The graph re-runs `targets` and `fuel` with the overrides applied and the result goes to review; on approve, `apply` persists the overrides into the Store profile, and on reject they are discarded and the note returns to checkin. Extending the horizon is the same call with no overrides.

Write tools are never bound to a sub-agent. Only `apply` holds the write allow-list.

### 6.3 Models

```python
class Product(BaseModel):
    name: str
    form: Literal["gel", "chew", "drink", "bar", "real_food", "other"]
    carbs_g: float
    sodium_mg: float = 0
    caffeine_mg: float = 0
    tested: bool = True

class NutritionProfile(BaseModel):
    height_cm: float
    weight_kg: float
    body_fat_pct: float | None
    sex: Literal["m", "f"]
    age: int
    activity_factor: float = 1.35          # non-exercise daily activity, 1.2 to 1.5
    goal: Literal["lose", "maintain", "gain_lean"]
    target_weight_kg: float | None
    target_date: date | None
    max_weekly_change_pct: float = 0.5     # bound: at most 1.0
    pattern: Literal["omnivore", "pescatarian", "vegetarian", "vegan", "other"]
    restrictions: list[str]
    dislikes: list[str]
    gi_issues: list[str]
    meals_per_day: int
    cooks: bool
    caffeine_mg_per_day: int | None
    alcohol_drinks_per_week: int | None
    tracks_food: bool
    scale_days_per_week: int
    known_sweat_rate_l_per_h: float | None
    tested_products: list[Product]
    fuel_notes: list[str]
    unit_preference: Literal["metric", "imperial"]
    constraints: list[str]
    medical_flags: list[str]

class DayTarget(BaseModel):
    day: date
    day_type: Literal["rest", "easy", "moderate", "hard", "long", "race", "carb_load"]
    session_kcal: int
    total_kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    fluid_baseline_ml: int
    plan_phase: str | None
    source: Literal["plan", "tp_calendar", "profile_hours"]
    notes: list[str]

class SessionFuel(BaseModel):
    tp_workout_id: str
    day: date
    pre: str
    carbs_g_per_h: int
    fluid_ml_per_h: int
    sodium_mg_per_h: int
    caffeine_mg: int | None
    products: list[str]
    post: str
    gut_training: bool
    note_text: str

class RaceFuelStep(BaseModel):
    offset_min: int                        # from race start; negative is before
    leg: Literal["pre", "swim", "t1", "bike", "t2", "run", "post"]
    what: str
    carbs_g: int
    fluid_ml: int
    sodium_mg: int
    caffeine_mg: int

class RaceFuelPlan(BaseModel):
    event_date: date
    timeline: list[RaceFuelStep]
    totals_per_h: dict[str, int]           # bike_carbs, run_carbs, bike_fluid, run_fluid, bike_sodium, run_sodium
    contingencies: list[str]
    note_text: str

class NutritionChange(BaseModel):
    op: Literal["set_day_targets", "set_session_note", "set_race_note"]
    target_key: str                        # date, tp_workout_id, or tp_note_id (empty when creating)
    day: date
    payload: dict
    reason: str

class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None
    changes: list[NutritionChange] | None
```

## 7. Nutrition logic (`nutrition/`)

All constants live in `constants.py`.

### 7.1 Energy

- RMR: Cunningham, `500 + 22 × lean mass kg`, when body fat is known; otherwise Mifflin-St Jeor from weight, height, age and sex.
- Non-exercise expenditure: `RMR × activity_factor`.
- Session kcal by sport from planned fields: bike `TSS × FTP × 36 / 1000` kcal (kJ taken as kcal); run `weight_kg × distance_km` when distance is planned, else `duration_h × weight_kg × pace-zone factor`; swim `duration_h × weight_kg × intensity factor`; brick as the sum of its legs; strength `duration_h × 5 × weight_kg`. Completed sessions on past days use `workouts.calories` when present.
- Total kcal: `RMR × activity_factor + session_kcal`, then the goal adjustment.

### 7.2 Day type

From the day's planned sessions: no session is `rest`; total duration under 60 minutes and no session above endurance intensity is `easy`; up to 120 minutes or one tempo session is `moderate`; any threshold, vo2 or race-intensity session is `hard`; any single session of 150 minutes or more is `long`; the event date of the active goal in `training_goals` is `race`; the two days before it are `carb_load` when its priority is A, otherwise they keep their session-derived type. `hard` and `long` share a macro row.

### 7.3 Macros, grams per kg body mass

| Day type | Carbs | Protein | Fat |
|---|---|---|---|
| rest, easy | 3 to 4 | 1.8 | remainder, at least 0.8 |
| moderate | 5 to 6 | 1.8 | remainder, at least 0.8 |
| hard, long | 7 to 8 | 2.0 | remainder, at least 0.8 |
| carb_load | 10 | 1.6 | remainder, at least 0.6 |
| race | 8 (in-race intake is separate) | 1.6 | remainder, at least 0.6 |

Within a range the position scales with session kcal. Fat is the remainder of total kcal after carbs and protein, floored at the minimum; when the floor binds, total kcal rises to hold it and the day is flagged `fat_floor`.

### 7.4 Goal adjustment

- `lose`: a deficit on rest, easy and moderate days only, sized so the modeled weekly loss is at most `max_weekly_change_pct` of body mass (7700 kcal per kg), never more than 500 kcal per day. Paused, with a note, on hard, long, carb_load and race days and in any week whose plan phase is peak, taper, race or recovery.
- `gain_lean`: a surplus of 200 to 300 kcal on hard and long days only.
- `maintain`: no adjustment.

### 7.5 Fluids

`fluid_baseline_ml` is 35 ml per kg per day plus the session's planned fluid when a sweat rate is known, else plus 500 ml per hour of planned training.

### 7.6 Bounds

`validate_targets` rejects a day when: energy availability, `(total_kcal − session_kcal) / fat-free mass`, is below 30 kcal per kg; `total_kcal` is below RMR; protein is below 1.6 g per kg; carbs on a hard or long day are below 6 g per kg; the seven-day deficit exceeds the rate bound; or a deficit falls in a peak, taper or race week.

`validate_fuel` rejects a session plan when: carbs per hour exceed 60 with no fuel log entry at or above 60 with outcome `ok`, or exceed 90 with no such entry at or above 90, or exceed 120 in any case; fluid exceeds 1000 ml per hour; sodium is outside 300 to 1500 mg per hour; caffeine is present when `caffeine_mg_per_day` is 0 or exceeds 6 mg per kg summed over the day; or any product is not in the product library.

`validate_race` applies the same per-hour bounds per leg and additionally requires the pre-race step to be within 2 to 4 hours before the start, total race caffeine under 6 mg per kg, and no product outside the library.

Violations are returned as a list of strings. Nothing that fails a bound is ever written; it surfaces at review or in chat.

## 8. Commands

- `tri-nutrition chat`: REPL. Streams tokens, prints `→ tool(args)` and `← tool: N chars`. At review, prints the horizon as a table (day, type, kcal, C/P/F, note?) followed by any race timeline, then prompts `approve / reject <note> / edit`; `edit` opens the change set as YAML in `$EDITOR`. `/status` prints goal, weight and body fat trend, days of targets remaining, last write. `/profile` prints the Store profile. `/pending` re-prints a paused change set. `/sync` runs `tri sync`. `/quit`.
- `tri-nutrition check-in [--yes]`: runs `tri sync`, invokes the graph on thread `nutrition` with the fixed check-in prompt, prints the proposed change set and exits paused at review. `--yes` resumes with approve.
- `tri-nutrition reset [--yes] [--forget-profile]`: clears the thread and the tables' unwritten rows. Only `--forget-profile` deletes the Store keys. Never touches Garmin or TrainingPeaks.

## 9. Error handling

| Failure | Behavior |
|---|---|
| Garmin server unavailable | Intake asks for weight, body fat and age instead of reading them. `set_day_targets` changes are held pending; TP notes still apply. |
| TrainingPeaks server unavailable | Note changes are held pending; Garmin targets still apply. |
| No active plan in `plan_weeks` | Sessions come from `workouts` rows synced from the TP calendar (`source = tp_calendar`). If the horizon has no planned workouts either, days are typed from the profile's weekly hours and flagged `profile_hours`, and intake says so. |
| Bounds violation in targets | Nothing written; violations printed; the athlete adjusts the profile in chat. |
| Fuel validation fails twice | The plan is stored with its violations and shown at review; the athlete edits or rejects with guidance. |
| Garmin write fails mid-batch | Batch stops; applied days are recorded; `last_error` names the failed day; review re-proposes the remainder. |
| Ownership check fails on a note | The change is dropped with a printed reason. |
| Auth expired | Detected from server error text; the re-auth command is printed. |
| Anthropic API error | Caught per turn, printed, REPL continues. |
| Checkpointer or Store tables missing | `chat` refuses to start and prints the setup command. |

## 10. Configuration

`tri_core.config` is shared. `tri_nutrition.config` adds `TRI_NUTRITION_HORIZON_DAYS` (default 14) and `TRI_NUTRITION_LANGSMITH_PROJECT` (default `tri_nutrition`). No new dependencies beyond planning's set. `tri_core.mcp.servers.garmin_spec` gains `enabled_tools: list[str] | None`, defaulting to the current list; the nutrition agent passes its own list from `allowlist.py`.

## 11. Testing

- **Unit, no DB, no model:** RMR both formulas; session kcal per sport; every day-type rule; every macro row and the fat floor; each goal adjustment including the phase pause; each bound in `validate_targets`, `validate_fuel`, `validate_race`; the Garmin calorie consistency fix; `NutritionChange` to server-call translation; YAML edit round trip.
- **Graph, `ScriptedChatModel` and `InMemoryStore`:** intake ends on `save_nutrition_profile` and the profile is in the Store; a new thread routes to `checkin` because the profile exists; review pauses and `Command(resume=approve)` reaches apply; reject routes back to intake or checkin with the note in messages; checkin ends on `propose_target_changes`, targets regenerate with the overrides, and approve persists them to the Store; a second process reads the profile from `AsyncPostgresStore`.
- **Apply, fake Garmin and TP callers:** ownership refusal, mid-batch failure, one `nutrition_changes` row per call.
- **DB tests** use `tri_analyze_test` and the rolled-back `db` fixture from `tri_core.testing`.
- **Live, opt-in:** set a Garmin nutrition target 400 days out, read it back, restore the previous values.
- Definition of done per task: `uv run pytest`, `ruff check`, `ruff format --check`, `mypy` strict on `src/`.

## 12. Observability and evaluation

LangSmith tracing by env, project `tri_nutrition`. Fuel calls carry `day` and `kind` tags. Milestone 4 adds a LangSmith dataset of (profile, training week) pairs with a code evaluator that runs `validate_targets` and `validate_fuel` on the output, and an LLM judge that checks fueling notes respect restrictions and name only library products. Pass rate per prompt version.

## 13. Milestones

1. **Math and schema.** Package scaffold, `003_nutrition.sql`, models, `energy.py`, `targets.py`, `bounds.py`, `garmin_spec(enabled_tools=...)`, all unit-tested. No model calls.
2. **Profile and targets.** Store, intake sub-agent, targets node, review, apply for Garmin day targets, checkpointer, `chat`. First targets on the watch.
3. **Fueling.** Fuel node, session notes and race plan to TrainingPeaks, YAML edit.
4. **Check-in.** Check-in sub-agent, fuel log, horizon extension, `check-in` command, LangSmith dataset and evaluators.
5. **Later, separate spec.** Orchestrator composing analyze, planning and nutrition as subgraphs.

## 14. Out of scope

Meal plans and recipes; supplement protocols beyond caffeine, and a nitrate mention in race notes; multi-athlete; writing weigh-ins or hydration to Garmin; logging food on the athlete's behalf; medical or clinical dietetics (iron, vitamin D and similar are flagged as questions for a doctor); any UI beyond the terminal; scheduled execution.

## 15. Open items to verify in milestone 1

- The exact JSON shape of `get_body_composition` for a range (field names for weight, body fat, muscle mass, water) and of `get_nutrition_daily_food_log` and `get_nutrition_daily_meals`; record fixtures with `scripts/spike_mcp.py` and scrub them.
- Whether `set_nutrition_daily_settings` for a future date creates a per-day override or changes the inherited default, and whether the watch shows per-day targets.
- Whether `tp_set_workout_note` appears in the TP calendar view and mobile app as expected, or whether `description` is the better field for a fueling note.
- `tp_create_note` return payload: does it carry the new note id needed for ownership?
- How `get_store()` is exposed inside `create_agent` tools in langchain 1.4.0 (runtime injection versus `langgraph.config.get_store`).
