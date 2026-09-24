# Codebase review, 2026-09-24

Main @ 01b332d. Seven package reviews (tri-core, tri-analyze, tri-coach, tri-planning, tri-nutrition, tri-wellness, tri-web plus the React frontend) and one pass over the repo layer. Every item marked **verified** was checked against the code by hand after the reviewer reported it; the rest are the reviewer's reading, marked confirmed (from reading) or plausible. Paths are repo-relative.

## Fix first

These change what the athlete sees or what gets written to TrainingPeaks, Garmin or the lab tables.

| # | Where | What | Status |
|---|---|---|---|
| 1 | `tri-wellness/labs/normalize.py:83-87` | A result's value is unit-converted but its lab reference range is not. Every SI-unit panel gets the wrong conventional status (glucose 5.2 mmol/L shows as 93.7 mg/dL against a 3.9-5.8 range: "high"). | verified |
| 2 | `tri-wellness/labs/normalize.py:19-31`, `repo.py:58-78` | `<1.0` is stored as 1.0 and `>60` as 60, the bound survives only as a note that never reaches `Finding` or the report. Tg Ab `<1.0` with range 0-0.9 flags high; eGFR `>60` flags low. | verified |
| 3 | `tri-nutrition/nutrition/energy.py:47-63` | A brick with no explicit legs is split by copying the parent, so both legs inherit `planned_tss` and `distance_km`. The bike leg is priced from the whole brick's TSS and the run added on top: a 150-min race brick comes out at ~2,450 kcal instead of ~1,620. | verified |
| 4 | `tri-nutrition/graph/nodes/fuel.py:168-176`, `repl.py:242` | A fuel plan that fails validation after the retry is still stored and proposed, and `check-in --yes` approves it. A 95 g/h or unknown-product note can reach TrainingPeaks unattended. Same shape in planning: `tools/design_next_week.py:69` returns violations that `adjust.py:50-52` drops and `checkin.py:56-57` approves. | verified |
| 5 | `tri-coach/graph/graph.py:68-80` | The embedded planning and nutrition graphs are compiled with private `InMemorySaver`s, but they are invoked with the parent node's config, which carries the Postgres checkpointer. LangGraph prefers the config's checkpointer, so every sub-graph step checkpoints to Postgres under thread `coach` with the coach's serde. The private savers never run. No data loss today; the DB grows per consult and the architecture doc is wrong. Fix: `checkpointer=False` on the embedded graphs. | verified |
| 6 | `tri-web/routes/coach.py:42-46` | A chat message posted while a review is paused makes LangGraph drop the interrupted task and the change set, unrecoverably. The REPL guards this (`tri-coach/repl.py:328`); the web route does not, and the composer stays enabled while the gate shows. | verified |
| 7 | `tri-core/sync/runner.py:57-61` | The sync window ends at today, so future planned TrainingPeaks workouts are never synced. The analyst reads seven days ahead (`tri-analyze/repo.py:37`) and renders a "next 7 days" block from an empty list. Deleted or moved TP workouts are never removed either (upsert only). | verified |
| 8 | `tri-planning/graph/graph.py:59-60` | Rejecting a bought-plan proposal returns END without clearing `pending_changes`; every later turn routes back to review. Only `reset` escapes. | verified |
| 9 | `tri-planning/repo.py:258-265` | Weekly TSS baseline divides the 28-day sum by 4 regardless of how many days have data; five days of history yields a fifth of the real load and the whole ramp starts too low. | verified |
| 10 | `tri-core/sync/match.py:34-46` | A brick is one TP workout and two Garmin activities. Matching compares one leg's duration to the whole brick within 120 s, so bricks never match. The test passes only with a 100,000 s tolerance. | verified |
| 11 | `tri-core/mcp/client.py:54-64` | `__aenter__` enters the exit stack, then `initialize()`. If that raises (bad cookie, Garmin login), nothing closes the stack and the `uvx` subprocess leaks. | verified |
| 12 | `tri-nutrition/nutrition/bounds.py:80-82`, `models.py:150` | `sodium_mg_per_h` is a non-null int and the validator requires at least 300, while the prompt says short endurance sessions "need little or nothing". A 40-min threshold run is forced to invent electrolytes. | verified |

## Bugs by package

Ranked within each package. Items above are not repeated.

**tri-planning**
- Empty plan adoption returns no `plan_id`, `design` asserts, and the next run re-applies the bought plan to TrainingPeaks (`graph/nodes/targets.py:78-82`, `graph.py:45-50`, `design.py:82`). confirmed
- An adjust-originated `create` marks an undesigned week as `written_to_tp`, so design skips it forever (`graph/nodes/apply.py:125-133`). confirmed
- Bought-plan adoption records ownership of every workout in the window, including the athlete's own (`targets.py:68-93`). confirmed
- The initial design window starts at this week's Monday while the plan starts next Monday, so horizon 3 designs 2 weeks (`design.py:30`, `targets.py:137`). verified
- Ironman peak block has no recovery week: six straight loading weeks before taper (`planning/targets.py:67-86`). verified
- Validator trusts the model's `week_start`; `structure_seconds` KeyErrors on distance-based steps; `None` from structured output asserts instead of retrying (`validate.py:25-49`, `design.py:53`). plausible
- No idempotency on creates: TP success then DB failure leaves an unowned workout that is re-created on retry (`apply.py:99-122`). plausible

**tri-nutrition**
- Profile overrides are dropped when a check-in yields no changes: review returns `decision=None`, apply never runs, and stale overrides in state get applied later by the coach's regenerate path (`review.py:21-22`, `apply.py:167-172`, `graph.py:45-47`). confirmed
- Wrong race row after an event date change: first `kind == "race"` row wins, the old note is overwritten, the new row is marked written, and the change re-proposes forever (`fuel.py:142`, `tp_calls.py:54-58`). confirmed
- Today's completed workouts drop out of today's target, so an afternoon regenerate lowers the Garmin target for a day already trained (`plan_loader.py:123`). confirmed
- Two id-less sessions on one day collapse into one row under the unique index (`migrations/004_nutrition.sql:31-32`). confirmed
- Write-then-record ownership: TP call before the audit insert; a DB failure leaves a note that later reads as foreign and raises `PermissionError` every run (`apply.py:73-86`, `:41-44`). plausible
- Race carb bound only checks the `totals_per_h` keys the model chose to emit (`bounds.py:136-140`). plausible
- `target_date` is collected and never used in the deficit maths (`targets.py:47-51`). confirmed
- Held `pending_changes` hijack the thread, as in planning (`graph.py:43-44`). confirmed

**tri-wellness**
- Parenthesised qualifiers are stripped before alias lookup: "Testosterone (Free)" maps to total, "Cortisol (PM)" to AM, "B12 (Active)" to B12 (`ranges/registry.py:89-98`). verified
- Unitless markers (ratios, differential %) can never be approved: `unit=None` is a blocking reason (`labs/normalize.py:38-44`, `models.py:93`). confirmed
- Duplicate detection is date plus lab name; the file sha is only the thread id. A re-download stores a twin panel and "previous" then reports 0% deltas (`repo.py:130-137`). verified
- A multi-date CSV export collapses into one panel with the first row's date (`labs/extract/exports.py:85-91`). confirmed
- Edited YAML with a repeated marker crashes at store and the rerun re-extracts, a paid call (`repl.py:189-222`). confirmed
- No PDF page or size limit checks; a >500-row panel overflows 32k output tokens and the truncated tool call asserts. A truncated report is saved as complete: `stop_reason` is ignored (`report.py:52-61`). plausible

**tri-coach**
- `max_consults` reaches only the prompt; nothing enforces it. The only stop is `recursion_limit=60`, which ends the turn with an opaque error (`tools/handoff.py:23-38`). verified
- Duplicate ids in `propose_changes` apply a change twice (`review.py:35-48`, `apply.py:116-119`). plausible
- `ask_wellness` output streams tagged `[analyst]` (`repl.py:49-55`). confirmed
- After an edit, the coach's history still holds the original proposal; its narration and the check-in memory describe changes that were not applied (`review.py:71-76`, `apply.py:200`). confirmed
- Follow-on proposals restart numbering at `p1` while `p1` already exists in the turn's history (`apply.py:214`, `nutrition.py:88-89`). confirmed

**tri-analyze**
- The `grounded` evaluator's field description forbids derived numbers while the judge system prompt allows arithmetic; the structured field wins. Stubs return canned rows for any SQL, so "compute with SQL" is impossible in the eval and the model sums in its head. The 8% baseline is mostly the evaluator (`evals/evaluators.py:100-134`, `evals/target.py:70-73`). confirmed
- Schema examples use `current_date` while "Today" is local; after about 19:00 Central, "yesterday" is today (`db/sql_tool.py:56-68`). plausible
- `states_window` regex matches "decoupling 5%" and "marathon 10 km"; near-vacuous for two of four trend cases (`evaluators.py:23-35`). confirmed
- A bare `/` in the REPL raises IndexError and kills the loop (`repl.py:63`). verified
- SQL tool caps rows at 200 but not bytes; `select * from workouts` returns `raw` per row, easily 100k tokens (`sql_tool.py:114`). verified

**tri-core**
- Mid-stream retryable error in an agent replays partial text (already accepted in the spec, §6.4); `streaming()` has first-chunk semantics, the middleware does not (`llm.py:219-230`). plausible
- A role's default effort is validated against the profile; if profile data lags, a tuned role silently runs at no effort with no log (`llm.py:135-138`). plausible
- Full `os.environ`, including `ANTHROPIC_API_KEY`, `DATABASE_URL` and LangSmith keys, is handed to both git-pinned MCP subprocesses (`mcp/client.py:59`, `live_tools.py:35`). verified
- Decimal columns reach the model as strings (`db/sql_tool.py:91-96`). verified
- Garmin readiness keeps the day's max of several entries (`sync/garmin.py:91-97`); the `except` path in `run_sync` can itself raise on a dead connection (`runner.py:128-135`). plausible
- The judge role falls back like any other; an overloaded run scores on Opus 4.8 and `eval_metadata` records the resolved model, not the one used (`llm.py:86`, `:271-278`). confirmed

**tri-web and frontend**
- The single-turn lock is an `asyncio.Lock` in one process while the thread is shared with the CLI; a page loaded during a CLI turn reads as `stuck` and invites a second concurrent run (`runtime.py:38`, `thread.py:104`). plausible
- Retry after a failed turn posts the same text again: two `HumanMessage`s (`useTurnStream.ts:122-136`). plausible
- Synchronous psycopg on the event loop in `/api/today` and `load_context`; a window-focus refetch stalls SSE tokens (`today.py:211-222`). verified
- TypeScript `strict` is off, so every `| null` in the generated types is unenforced. verified
- `--host` accepts any address with no authentication: anyone on the LAN can approve TrainingPeaks writes (`cli.py:44-54`). verified
- Concurrent sync jobs take no lock; job memory is never evicted; 500 bodies leak exception text with the DB host (`routes/jobs.py:37-44`, `app.py:63-66`). plausible

## Anti-patterns that repeat across packages

1. **The model owns the arithmetic.** Planning asks the model to make `tss_planned` sum within 10% and structure steps sum to duration, then retries when it fails. Nutrition asks per-session numbers it then bounds. Compute TSS and totals in Python from what the model chose (durations, intensities, products) and validate only what a model can reason about: days, sports, spacing, restrictions. Most retries disappear and a 30-min "vo2" at 200 TSS stops passing.
2. **Validate, then propose anyway.** Planning and nutrition both surface violations and still store and propose the plan; `--yes` then writes it. Either refuse, or mark each change and make unattended mode skip marked ones.
3. **Soft limits in prose.** `max_consults`, "propose once", "under 90 minutes need nothing" live in prompt text and are contradicted or ignored by code. Count consults in state and return an error tool message past the limit.
4. **Pending changes hijack the thread.** Planning, nutrition and the web route all route any later message into review or drop the review. One rule per graph: a held change set is answered or cleared before ordinary turns resume.
5. **Write, then record.** Every TrainingPeaks and Garmin write happens before the ownership or audit row. Record intent first, or reconcile by note text, so a DB failure cannot lock the athlete out of their own notes or duplicate a workout.
6. **Sync is a snapshot to today.** No future window, no tombstones, one Garmin id per workout. The analyst, the today view and adherence queries all assume otherwise. Sync `today + horizon`, mark rows absent from the listing, and store activities in their own table keyed to the workout.
7. **Evaluators grade shape, not truth.** The analyst judge forbids derived numbers; the coach judge never sees the context or sub-agent answers, so a hallucinated "Ferritin 18" passes; `states_window` and `cites_functional_ranges` are regexes that match noise. The 8% "grounded" baseline is not a model problem.
8. **Two conventional bounds in wellness.** `conventional_status` uses the lab's printed range while `functional_status` uses the registry's, so "ferritin 25 low (conventional in range)" is a normal line. The registry also contradicts its own notes (WBC, testosterone, creatinine) and flags a dozen markers on a typical endurance panel that the notes then dismiss. An athlete tier or a personal-baseline comparison would cut the noise.
9. **Medical framing.** The report prompt makes the model a practitioner who names compounds and dose ranges while the disclaimer says it is not a prescription. For a personal tool: prepend the disclaimer in code, lead Priorities with any conventionally abnormal marker and "practitioner first", and leave dosing out.
10. **SQL safety is lexical where it should be a role.** The single-statement check plus `BEGIN READ ONLY` holds, but the tool uses the ETL's role, so `pg_terminate_backend` on the checkpointer's connection is callable. A dedicated read-only role makes the boundary real and lets the lexical check go.
11. **Repo layer.** No CI; the six definition-of-done commands run only by hand. Five hand-applied migrations with no tracking table. The frontend has no tests and `strict` off. The Garmin and TrainingPeaks MCP servers get the whole environment.

## Optimizations, largest first

- Tool output: byte-cap SQL results and strip `raw`, `garmin_raw`, `tp_raw` unless named; push the limit into the query. This is the biggest token lever in the analyst and every coach consult.
- Planning: compute TSS in Python (kills most design retries); on reject, redesign only the noted week, not the whole window.
- Nutrition: fingerprint fuel inputs and skip the model call when unchanged; today every regenerate re-calls every session and re-proposes every note because `note_text` is never byte-identical. Gather session calls per day.
- Sync: `tp_get_workout` per id and two Garmin calls per day are sequential; a bounded gather turns a first run from minutes into seconds. Watermark by TP `lastModified` instead of a 3-day overlap.
- Coach: the single thread grows forever and every call resends it; trim or summarise before the model call. The system prompt is re-rendered mid-turn, so the cache prefix misses after a consult; put per-turn context in the first message.
- Wellness extraction: a 200-row panel is ~12k output tokens, half of it repeated JSON keys; a compact row schema, and Sonnet for a transcription task, once `TRI_WELLNESS_LIVE_PDF` confirms it.
- Web: `/api/today` runs ~20 sequential queries on the event loop and refetches on window focus; the thread endpoint returns the whole history every 2 s while busy.
- Core: `_effort_levels` builds a full `ChatAnthropic` to read a profile; cache it and build fallbacks once.

## Test gaps that matter

- Nothing end to end covers `check-in --yes` with violations (planning or nutrition), reject on a bought plan, or a chat message during a paused review.
- Brick matching is tested only with a tolerance that hides the bug; no re-sync test where an assigned activity meets a new candidate.
- Unit conversion is tested without reference ranges; bounded values are never asserted end to end; no golden LabCorp/Quest label list against alias lookup.
- The judges are exercised with scripted verdicts only; a dozen labelled (answer, expected) pairs against the real judge would say whether 8% grounded is the evaluator.
- `claude_fallback` never runs through a real `create_agent` loop; one `make_subagent` test with a raising primary would pin that langchain rebinds tools to the fallback.
- Embedded sub-graph checkpoints staying out of the parent saver; MCP client cleanup on a failed connect; SQL tool with `%` in a literal, Decimal columns, `pg_terminate_backend`.
- Frontend: nothing asserts composer state while a gate is paused; the e2e spec stubs every route.

## Features worth building, grounded in the code

1. Sync the planning horizon and tombstone deletions; store Garmin activities per workout so bricks keep both legs and laps are queryable offline. Most analyst and today-view gaps trace back here.
2. Per-sport TSS and hours split with long-session progression in `WeekTarget`, computed in Python, and re-baselining remaining targets from live CTL/TSB at check-in.
3. Enforced consult budget with "consults left" in the coach context, and the athlete's edit diff reported back to the coach after apply.
4. Bound-aware lab findings (`<`/`>` carried to `Finding`, an indeterminate status) and a personal-baseline comparison after three rested panels.
5. Gut-training progression across a block and sweat-rate from Garmin `sweatLossInML` to set fluid and sodium per session.
6. Resumable web turns (ids plus replay) and a gate-aware composer that asks about the proposal instead of dropping it.
7. `tri-analyze weekly` and a race-readiness view from CTL/TSB trajectory to the goal's event date.
8. A `similar_sessions` tool beside SQL for the deterministic "this ride against the last N" path.

## Suggested order

1. Correctness that writes or misreports: items 1 to 12 above, plus the two `--yes` gates. Small diffs, mostly one function each.
2. The structural fixes: sync horizon and tombstones, Python-owned TSS, validate-then-refuse, record-then-write, `checkpointer=False` on embedded graphs, an enforced consult budget.
3. Evaluators, since tuning decisions rest on them: feed the coach judge its context, allow derivations in the analyst judge with shown work, seed the eval target from Postgres instead of canned rows.
4. Hygiene: CI running the six commands, a migration tracker, TypeScript strict, a read-only DB role, a trimmed environment for MCP subprocesses.
