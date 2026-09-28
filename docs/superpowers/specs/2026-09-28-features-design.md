# Features: a personal lab baseline, a gut-training ladder and sweat rate, resumable turns with an ask-while-paused composer, weekly and race readiness, per-sport TSS

**Date:** 2026-09-28
**Status:** Draft
**Purpose:** Build the four features from `docs/notes/2026-09-24-codebase-review.md` that the round-one specs left open. One of three round-two specs, alongside `2026-09-28-optimizations-design.md` and `2026-09-28-test-gaps-design.md`. It yields five plans, C1, C2, C3, C4a and C4b, independent of each other. Line numbers are `fix/eval-followups` @ 0c096ca.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | All four features: lab baseline, gut training and sweat rate, resumable turns, weekly and readiness (chosen 2026-09-28). | Consult edit-diff and `similar_sessions` wait. |
| Storage | No migration. New data rides in existing jsonb (`lab_reports.findings`, `fuel_plans.payload`, `plan_weeks.designed`, `training_plans.targets`) or is computed on read. | Brian's rule: schema changes need sign-off; none is needed. |
| Sweat rate | Proposed through the nutrition check-in's existing review gate, never applied silently (chosen 2026-09-28). | A profile field changes the fluid target every day. |
| Readiness surface | `tri-analyze weekly` and a race card on the web today view (chosen 2026-09-28). | The same numbers in both places. |
| Ask while paused | A message sent while a coach review waits becomes an `ask` decision: the coach answers and the same review pauses again. | The composer is disabled today (`Chat.tsx:76`); a new turn would drop the review. |
| Turn resumption | Within one process: turn ids and a replayable transcript. A server restart still shows "stuck". | Jobs already work this way (`tri_web/jobs.py:1-4`). |

## 2. Feasibility, verified 2026-09-28

- Labs: `Finding` (`tri_wellness/labs/models.py:79-96`) carries `previous`/`delta_pct`; `active_confounders` (`labs/evaluate.py:74-112`) derives panel-level confounders from `TrainingContext` and `PanelContext`; `evaluate` (`:168-208`) is pure and called from `report.py:96-101`, `tools/findings.py:81-83` and `evals/target.py:45`. `previous_values` and `marker_history` (`repo.py:210`, `:248`) read earlier panels by `(drawn_on, id)`. The report prompt renders "previous … (delta)" (`prompts/report.py:187-190`); `PROMPT_VERSION = "2"` (`:13`).
- Nutrition: tiers `FUEL_CARBS_TIER_1/2/MAX` = 60/90/120 (`nutrition/constants.py:93-95`); `carbs_evidence` (`nutrition/bounds.py:57`) is the best ok carbs/h; `Outcome = ok | gi_upset | bonk | cramps | other` (`nutrition/models.py:20`); `SessionFuel.gut_training` is model-set (`:155`, `prompts/fuel.py:25-26`); fuel `PROMPT_VERSION = "4"` (`:17`). `read_hydration` returns daily `sweat_loss_ml` from `get_hydration_data` (`tools/garmin.py:133-146`, `:193-208`); `known_sweat_rate_l_per_h` feeds `fluid_baseline_ml` (`nutrition/targets.py:117-121`); `propose_target_changes` accepts any `NutritionProfile` field (`tools/checkin.py:36`, `:187-201`).
- Web turns: `start_turn`/`TurnRun` (`tri_web/events.py:47-96`) stream through an unrecorded queue; `Job` (`jobs.py:23-60`) records events and replays to late followers; `Runtime` holds `lock`, `running`, `turn_task`, `jobs` (`runtime.py:38-41`); `ThreadView` has no turn id (`thread.py:36-41`); `ReviewIn.action` is `approve | reject | edit` (`schemas.py:19-22`); the frontend polls every 2 s while busy (`useTurnStream.ts:144`). The coach's `ReviewDecision` lives in tri-coach (`tri_coach/models.py:71-74`); `review_node` is pure before `interrupt()` (`graph/nodes/review.py:22-65`); `after_review` routes to `apply` or `coach` (`graph/graph.py:55`, `:88`); the REPL parses `approve`/`reject`/`edit` (`repl.py:36`, `:258-261`).
- Readiness: goals carry `goal_type` and `event_date` (`tri_planning/planning/models.py:11-13`, `:27-47`); `WeekTarget` has one `target_tss`/`target_hours` (`:53-60`); `targets.build` (`planning/targets.py:133`) and `ctl_after_week` (`:102`); `validate.week` (`planning/validate.py:50`); design `PROMPT_VERSION = "2"` (`prompts/design.py:10`); planning check-in `run_checkin` (`checkin.py:45`). `TodayView` shows goal, week and raw CTL/ATL/TSB (`tri_web/today.py:28-150`); cards in `web/src/components/today/`. tri-analyze has only `chat` and `eval` (`cli.py:50`, `:130`) and does not depend on tri-planning.

## 3. C1: personal lab baseline (tri-wellness)

**Rested panel.** `is_rested(context: PanelContext, training: TrainingContext) -> bool` in `labs/evaluate.py`: true when none of `recent_hard_session`, `high_acute_load`, `poor_sleep`, `low_hrv` fires (reusing `active_confounders` with `results=[]`) and `context.fasting is not False`. Missing inputs do not fire a confounder, as today.

**Baseline.** Constants in `labs/evaluate.py`: `BASELINE_MIN_PANELS = 3`, `BASELINE_WINDOW_DAYS = 730`. New `repo.rested_history(conn, panel_id) -> dict[str, list[tuple[date, float]]]`: per marker, values from panels strictly earlier than this one by `(drawn_on, id)` and within the window, excluding bounded rows; it loads each earlier panel's `TrainingContext` with `load_training_context` and keeps only rested panels. Pure `baselines(history) -> dict[str, Baseline]` with `Baseline(value: float, n: int)`, the median of the values, only when `n >= BASELINE_MIN_PANELS`.

**Finding.** Gains `baseline: float | None = None`, `baseline_n: int = 0`, `baseline_delta_pct: float | None = None` (None when the current value is bounded). `evaluate(...)` gains `baselines: dict[str, Baseline] | None = None` as a keyword argument; the three callers pass `baselines(repo.rested_history(conn, pid))`. Stored inside `lab_reports.findings`.

**Surface.** `findings_block` appends `; your rested baseline {value} over {n} panels ({delta:+.1f}%)`. `REPORT_RULES` gains one sentence: compare to the personal baseline when given, and prefer it over the population range for trend language. Report `PROMPT_VERSION` → "3".

**Errors.** A panel whose training context cannot load is treated as not rested. Fewer than three rested panels means no baseline, and nothing is said.

**Testing.** `is_rested` truth table; `baselines` median and minimum; `rested_history` on the test DB with four panels, one of them unrested; the report-prompt line; a report eval case with a baseline.

## 4. C2: gut-training ladder and sweat rate (tri-nutrition)

**Ladder.** Constants: `GUT_STEP_G_PER_H = 10`. The gut issues are `gi_upset`, `bonk` and `cramps`. Pure `gut_training_target(fuel_log: list[FuelLogEntry]) -> int` in `nutrition/bounds.py`:
- `best = carbs_evidence(fuel_log)`.
- `cap = TIER_1 if best < TIER_1 else TIER_2 if best < TIER_2 else MAX`.
- `target = min(best + GUT_STEP_G_PER_H, cap)`.
- When the newest entry by day has a gut-issue outcome: `target = min(target, entry.carbs_g_per_h - GUT_STEP_G_PER_H)`.
- The result is floored at 0.

The target never exceeds what `_carbs_per_h_violations` allows.

**Where it applies.** Sessions that qualify for fueling (`fuel.py` `qualifies`) with duration above 90 minutes are gut-training sessions. The session prompt receives `gut training target: {n} g/h`. `FUEL_SYSTEM` says: on a gut-training session, set `carbs_g_per_h` to the target and `gut_training` true; on any other session, stay at or below the best tolerated. The model no longer decides when to train the gut. Fuel `PROMPT_VERSION` → "5". The target joins optimizations spec A's fuel fingerprint inputs when both land.

**Sweat rate.** Constants: `SWEAT_MIN_SESSIONS = 4`, `SWEAT_WINDOW_DAYS = 42`, `SWEAT_CHANGE_PCT = 15`. Pure `estimate_sweat_rate(hydration: list[dict], sessions: dict[date, list[int]]) -> SweatEstimate | None`, where `sessions` maps a day to the completed sessions' `actual_duration_sec`:
- Only days with exactly one completed session and a non-null `sweat_loss_ml` are used.
- The rate per day is `sweat_loss_ml / 1000 / hours`.
- The result is `SweatEstimate(l_per_h: float, n: int)`, the median over the days, or None below the minimum.

A new check-in tool, `estimate_sweat_rate()`, reads hydration for `SWEAT_WINDOW_DAYS` and completed workouts from `workouts` (deleted rows excluded). It returns the estimate, the saved rate and `differs: bool` (more than `SWEAT_CHANGE_PCT` apart, or no saved rate). The check-in prompt gains a step: call `estimate_sweat_rate`; when `differs`, include `known_sweat_rate_l_per_h` in the one `propose_target_changes` call with the reason "Garmin sweat rate over n sessions". The check-in prompt has no version constant.

**Errors.** A Garmin error returns `{"error": …}` and the step says so; a missing duration skips the day.

**Testing.** Ladder table: empty log; best 50, 60, 85 and 90; newest entry gi_upset. `estimate_sweat_rate`: multi-session days skipped, fewer than four days, median. The tool with a fake Garmin client. A fuel-node test that the target reaches the prompt. A fuel eval case.

## 5. C3: resumable turns and the ask-while-paused composer (tri-web, tri-coach, web/)

**Transcript.** A turn becomes a `Job` of kind `turn` or `review` in `rt.jobs`, which reuses its recorded events and follower replay. `start_turn` keeps the lock semantics and returns the `Job`. `TurnEmitter` emits into the job. `sse_response` follows the job from event 0. `Runtime` gains `turn_id: str | None`, set while a turn runs.

**Endpoints.**
- `POST /api/coach/turns` and `POST /api/coach/review` answer with an `X-Turn-Id` header.
- New `GET /api/coach/turns/{id}/events` replays and then follows, like `/api/jobs/{id}/events`, and returns 404 for an unknown id.
- `ThreadView` gains `turn_id: str | None`.

**Frontend.** On load, or when the thread shows `running` with a `turn_id`, `useTurnStream` attaches to the events endpoint and rebuilds the bubbles from the replay. It stops polling. The 2 s poll stays only when `running` has no `turn_id` (a check-in job).

**Ask decision.**
- tri-coach `ReviewDecision.action` gains `"ask"`, with `note` holding the question.
- `review_node` on `ask` keeps `proposal_request` and `pending` unchanged, appends `HumanMessage(note)` and records the decision. It does not reset `consults`.
- `after_review` routes `ask` to a new node `answer`. That node makes one call on the coach model, with no tools, the thread and `render_review` of the paused proposals, under a short `ANSWER_SYSTEM`: answer the question about these proposals and do not propose or consult. It appends the AI message.
- An edge from `answer` goes back to `review`, which rebuilds the same change set and interrupts again.

`ReviewIn.action` gains `"ask"` (note required, 422 without it). The REPL's review prompt gains `ask <question>`. The composer is enabled while paused, with the hint "ask about the proposal", and sends to `/api/coach/review` as `ask`. `COACH_RULES` does not change; coach `PROMPT_VERSION` stays "4".

**Errors.** An answer-model failure is caught as for any node; the review pauses again with an activity line "could not answer: …". An ask while nothing is paused returns 409 `no_review`, as today.

**Testing.**
- tri-coach graph: ask → answer → the same interrupt payload, with the consults map unchanged.
- REPL parse.
- Web routes: the `X-Turn-Id` header, events replay after the stream ends, 404, and ask without a note gives 422.
- Frontend: reattach on reload replays the bubbles, and the composer is enabled while paused and sends ask (`chat.test.tsx` updated).

## 6. C4a: `tri-analyze weekly` and race readiness (tri-core, tri-analyze, tri-web, web/)

**Projection.** Pure functions in a new `tri_core/load.py`:
- `project(ctl: float, atl: float, daily_tss: list[float]) -> list[tuple[float, float]]` uses the 42/7-day exponentially weighted moving average: `ctl += (tss - ctl) / 42`, `atl += (tss - atl) / 7`.
- `race_readiness(ctl, atl, daily_tss, event_date, today) -> Readiness` returns `days_to_go`, `ctl_now`, `ctl_peak`, `ctl_race_day`, `tsb_race_day` and `in_taper_band`.

Constants: `TAPER_TSB_LOW = 5`, `TAPER_TSB_HIGH = 25`.

**Daily TSS source,** for tomorrow through the event day: the TP calendar's `planned_tss` from `workouts` (not completed, not deleted), which is synced 28 days ahead. Beyond that, the active plan's week targets from `training_plans.targets` at `target_tss / 7` per day. Zero on days that have neither. tri-analyze reads goals and plans with SQL, without importing tri-planning.

**Weekly summary.** `tri_analyze/weekly.py`, `weekly(conn, week_start) -> WeeklyReport`, gives:
- per sport: planned versus actual TSS and hours (bricks split by legs when present, else 75% bike and 25% run);
- sessions completed out of planned;
- CTL, ATL and TSB at the start and end of the week;
- readiness when there is an active race goal.

CLI: `tri-analyze weekly [--week YYYY-MM-DD]`, defaulting to the week before the current one. It prints a table plus a readiness block, and says "race-day TSB outside the taper band (5 to 25)" when it is.

**Today card.** `TodayView.race: RaceOut | None`, present only for an active race goal with an event date, built from the same `race_readiness`. `RaceCard.tsx` in `web/src/components/today/` shows days to go, CTL now and at its peak, and race-day TSB with the band.

**Errors.** No daily_metrics row with CTL means no readiness, and the CLI says so.

**Testing.** `project` matches a hand-computed series. `race_readiness` band edges. `weekly` on the test DB with a seeded week. CLI output. The today route with and without a race goal. A `RaceCard` render test.

## 7. C4b: per-sport TSS and rebasing at check-in (tri-planning)

### 7.1 Split

`WeekTarget` gains `sport_tss: dict[Literal["swim", "bike", "run"], float] = {}` and `planned_ctl_end: float | None = None`. `targets.build` fills `sport_tss` from `SPORT_SPLIT[goal_type] × target_tss`, restricted to the sports the athlete's availability allows and renormalised over them. It fills `planned_ctl_end` from the `ctl_after_week` chain. Both are stored in the targets jsonb.

| goal_type | swim | bike | run |
|---|---|---|---|
| sprint | 0.20 | 0.40 | 0.40 |
| olympic | 0.18 | 0.45 | 0.37 |
| half_ironman | 0.15 | 0.50 | 0.35 |
| ironman | 0.12 | 0.55 | 0.33 |
| maintenance, build, recovery | 0.15 | 0.50 | 0.35 |

### 7.2 Designer and validator

The design prompt shows per-sport TSS budgets; design `PROMPT_VERSION` → "3". `validate.week` adds a violation when a sport's planned TSS differs from its budget by more than `max(SPORT_TOLERANCE_PCT × budget, SPORT_TOLERANCE_MIN_TSS)`, with `SPORT_TOLERANCE_PCT = 0.20` and `SPORT_TOLERANCE_MIN_TSS = 15`. Brick TSS is split as in §6. The existing validate-then-refuse path applies. Targets without `sport_tss` (plans made before this change) skip the check.

### 7.3 Rebase

At check-in, `run_checkin` compares the latest daily_metrics CTL with the last completed week's `planned_ctl_end`. When they differ by more than `REBASE_CTL_DRIFT_PCT = 10`%, it rebuilds the remaining weeks' targets with `targets.build` from the current fitness snapshot, keeping phases and recovery flags. It proposes the change through the existing adjust review, with the reason "CTL {actual} vs planned {planned}". Weeks already designed are redesigned only after approval, as adjust does today.

**Errors.** A missing `planned_ctl_end` (an old plan) or a missing CTL skips the rebase check.

**Testing.** Split renormalisation with an unavailable sport; the validator tolerance edges, including the 15-TSS floor; drift at 9% and 11%; a check-in test that the rebase is proposed and not applied; a design eval case.

## 8. Decisions made while writing this spec

- The ask flow is a new tri-coach node `answer` (not the full coach node, which could consult or propose). `ReviewDecision` stays in tri-coach.
- Turns reuse `tri_web.jobs.Job` rather than a second transcript type.
- The load projection lives in tri-core (`tri_core/load.py`) so tri-analyze and tri-web share it without depending on tri-planning.
- Projection TSS source order: the TP calendar, then week targets, then zero.
- Gut training applies to qualifying sessions longer than 90 minutes; a gut issue caps the next target 10 g/h under the failed rung.
- A per-sport tolerance floor of 15 TSS, so a 30-TSS swim budget is not failed by 7 TSS.
- Rested requires fasting not reported false (unrecorded counts as rested); `afternoon_draw` and `inflammation` do not make a panel unrested.

## 9. Out of scope

Reporting the athlete's edit diff back to the coach after apply; a `similar_sessions` tool; keeping turns across a process restart beyond showing "stuck"; persisting sweat rate history; per-sport hours targets.

## 10. Rollout

Plans C1, C2, C3, C4a and C4b, each on its own branch off `main`, in any order. Prompt versions: wellness report 3, fuel 5, design 3; coach unchanged. Evals affected: the wellness report eval (baseline case), the fuel eval (gut ladder case) and the planning design eval (per-sport budgets). Brian re-runs `uv run tri-wellness eval`, `uv run tri-nutrition eval` and `uv run tri-planning eval` after the matching plan merges and records the results in `docs/notes/`. No migration.
