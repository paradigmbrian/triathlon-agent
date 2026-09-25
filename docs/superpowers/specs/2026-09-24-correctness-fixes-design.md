# Correctness fixes: what the athlete sees and what gets written

**Date:** 2026-09-24
**Status:** Draft
**Purpose:** Fix the defects from `docs/notes/2026-09-24-codebase-review.md` that misreport a result or write something wrong to TrainingPeaks, Garmin or the lab tables. Each item is one function or one guard. First of five specs; the data layer, guardrails, evaluators and hygiene specs follow and assume these are in. Line numbers are `main` @ 6540055.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Bounded lab values (`<1.0`, `>60`) | Bound-aware status: the bound and raw string travel to `Finding`; a status the bound cannot decide is `indeterminate` (chosen 2026-09-24). | A bound is information, not a number. Storing 1.0 for `<1.0` flags Tg Ab high against a 0-0.9 range. |
| `check-in --yes` with violations | Skip the violating changes, print them, exit 1; interactive runs still show them and let the athlete decide (chosen 2026-09-24). | One bad session must not block the week, and cron must not write a 95 g/h note unattended. |
| Report framing | Practitioner-first, no dosing: disclaimer prepended in code, conventionally abnormal markers lead Priorities, Supplements name compound and target marker only (chosen 2026-09-24). | A personal tool that names dose ranges while calling itself "not a prescription" is not safe enough. |
| Alias qualifiers | Parenthesised qualifiers stay in the alias key; unqualified fallback is removed. | "Testosterone (Free)" mapping to total is a silent wrong marker. An unmapped row is a visible review line. |
| Scope | No new features. Sync window, brick matching and Python-owned TSS belong to the next specs. | Keep this plan small enough to land in a day. |

## 2. The fixes

Each row: what is wrong, the change, and the test that pins it. Paths are under `packages/<pkg>/src/<pkg>/`.

### 2.1 tri-wellness

| # | Defect | Change | Test |
|---|---|---|---|
| W1 | `labs/normalize.py:82-83` stores `lab_ref_low/high` unconverted while `value` is multiplied by `factor`. | Multiply both refs by `factor` when present. `repl.py:58-65` review table then shows range and value in the same unit. | `test_normalize.py`: a row with `5.2 mmol/L`, refs `3.9-5.8`, converts value and refs together. |
| W2 | `parse_value` (`normalize.py:19-31`) turns `<1.0` into 1.0 with a note that never reaches `Finding` or the report. | `parse_value` returns `(number, bound)` with `bound: Bound | None`, `Bound = Literal["<", "<=", ">", ">="]`. `LabResult` gains `bound`; `lab_results` gains `bound text` (migration 006); `Finding` gains `bound` and `raw_value: str`. `ConventionalStatus` and `FunctionalStatus` gain `"indeterminate"`. `evaluate.py` evaluates a bounded value as an interval: `<x` is `[0, x)`, `>x` is `(x, inf)`; the status at both ends is computed and returned when equal, else `indeterminate`. `delta_pct` is `None` when either value is bounded. `_finding_line` prints `raw_value` for bounded rows and `indeterminate (reported as <1.0)`. | `test_evaluate.py`: `<1.0` vs 0-0.9 is `in_range`/`optimal`; `>60` eGFR vs a 60+ range is `in_range`; `<15` ferritin vs low 30 is `low`; `<50` vs a 30-100 range is `indeterminate`. `test_repo.py` round-trips `bound`. `test_report_prompt.py`: the line shows `<1.0`. |
| W3 | `ranges/registry.py:94-98` strips `(...)` before lookup, so qualified labels map to the wrong marker. | `normalize_alias` keeps parenthesised words (`testosterone (free)` becomes `testosterone free`). `markers.yaml` gains the qualified aliases for testosterone free/total, cortisol AM/PM, B12 active/total, vitamin D 25-OH, and the alias collision check stays. | `test_registry.py`: `"Testosterone (Free)"` maps to `testosterone_free`, `"Cortisol (PM)"` is unmapped, and a golden list of 40 LabCorp and Quest labels resolves without collision. |
| W4 | `_factor` (`normalize.py:38-44`) returns `None` for `unit=None`, so ratios and `%` rows block review. | When `spec.unit` is dimensionless (`ratio`, `%`, `index`, `score`), a missing raw unit means the canonical unit and `factor = 1.0`. Dimensioned markers keep the blocking reason. | `test_normalize.py`: `bun_creatinine_ratio` with no unit is accepted; ferritin with no unit still blocks. |
| W5 | `repo.py:130-137` detects duplicates by date and lab name only; a re-download stores a twin and `previous_values` reports 0% deltas. | `lab_panels` gains `source_sha text` (migration 006). Ingest computes the sha of the file bytes and blocks with `already ingested as panel <id>` when it matches; the date-plus-lab warning stays for different bytes. | `test_repo.py` and `test_graph.py`: the same file twice blocks at review. |
| W6 | `labs/extract/exports.py:85-91` takes the first row's date for a multi-date CSV. | Group rows by date; more than one date is a blocking review reason naming the dates, with the hint to split the file. | `test_exports.py`: a two-date CSV blocks. |
| W7 | `repl.py:189-222` accepts YAML with a repeated marker; the PK raises at store and the rerun re-extracts. | `review_from_yaml` rejects duplicates with the marker name before store. | `test_repl.py`: duplicate marker is a validation error. |
| W8 | `report.py:52-61` saves a truncated stream as a complete report. | `ReportWriter.write` reads the final chunk's `response_metadata["stop_reason"]`; `max_tokens` raises `ReportTruncated`, which `run_report` prints and does not save. | `test_report.py` with a scripted `stop_reason`. |
| W9 | Prompt framing (`prompts/report.py:43-46, 57-58, 64-66`). | The disclaimer is prepended by `run_report`, not requested from the model. Priorities rule: any `conventional_status` of `low` or `high` leads, with "discuss with your practitioner first". Supplements rule: compound, target marker, what would show it worked; no dose, no timing. `PROMPT_VERSION = "2"`. | `test_report_prompt.py` updated; `tri-wellness eval` rerun as `report-v2` after merge (athlete-run). |

Existing stored panels: W1 affects only panels whose lab printed SI units. Brian's panels are US labs in conventional units, so no data repair is scheduled; `tri-wellness ingest` of a new SI panel is correct from this change on.

### 2.2 tri-nutrition

| # | Defect | Change | Test |
|---|---|---|---|
| N1 | `nutrition/energy.py:47-63` copies `planned_tss` and `distance_km` onto both brick legs. | The bike leg gets `planned_tss * BRICK_BIKE_FRACTION` and `distance_km=None`; the run leg gets `planned_tss=None` and `distance_km=None`, so it prices by duration and intensity. | `test_energy.py`: a 150-min brick, TSS 180, FTP 250 prices near 1,600 kcal, not 2,450. |
| N2 | `bounds.py:76-87` requires sodium in 300-1500 whenever the field is set, and the field is a non-null int (`models.py:150`). | The sodium range applies only when `sodium > 0`; `0` means none and is valid. Same for fluid. The prompt line "under 90 minutes need little or nothing" stays. | `test_bounds.py`: sodium 0 on a 40-min session passes; 100 fails; 300 passes. |
| N3 | `graph/nodes/fuel.py:168-176` proposes a plan that still has violations; `repl.py:239-243` approves it under `--yes`. | The node keeps storing the plan with its violations but puts `violations_by_id` in state as `pending_violations`; the review payload carries it. `checkin_run(approve=True)` resumes with `{"action": "edit", "changes": <clean ones>}`, prints each skipped change with its violations, and returns 1 when any were skipped, 0 otherwise. It also refuses a review it did not produce (the `snap.next == ("review",)` branch returns 3 without approving), matching planning. | `test_graph.py`: `checkin_run(approve=True)` with one violating session writes the other and exits 1; a pre-existing paused review is not approved. |
| N4 | `review.py:21-22` returns `decision=None` when overrides exist but no changes, so `apply` never persists the overrides and they stay in state. | Review persists overrides itself when the change list is empty and clears `profile_overrides`; `after_review` then ends. | `test_graph.py`: an override-only check-in stores the override and leaves state clean. |
| N5 | `fuel.py:142` picks the first `kind == "race"` row regardless of day. | Filter on `p.day == ctx.event_date`; a race row on another day is left alone. | `test_fuel_node.py`: a moved event date creates a new note and does not overwrite the old one. |
| N6 | `plan_loader.py:123` drops today's completed workouts, so an afternoon regenerate lowers today's Garmin target. | Include workouts dated today regardless of `completed`. | `test_plan_loader.py`. |
| N7 | `migrations/004_nutrition.sql:31-32` collapses id-less sessions on one day. | The unique index key adds `coalesce(title, '')`; `upsert_fuel_plan` passes the title (migration 006). | `test_repo.py`: two id-less sessions on one day are two rows. |
| N8 | `targets.py:47-51` ignores `target_date`. | The weekly change needed to reach `target_weight` by `target_date` is computed; when it exceeds `max_weekly_change_pct` the intake conversation says so and the cap wins. | `test_targets.py`. |

### 2.3 tri-planning

| # | Defect | Change | Test |
|---|---|---|---|
| P1 | `graph/graph.py:59-60` ends on reject with `changes_from == "targets"` without clearing `pending_changes`; `route_start` then always routes to review. | `review_node` clears `pending_changes` on reject when the origin is not `design` or `adjust`; `after_review` unchanged. | `test_graph.py`: reject on a bought plan ends clean and the next message reaches `adjust`. |
| P2 | `targets.py:78-82` returns no `plan_id` on an empty adoption; `design.py:82` asserts; the next run re-applies the bought plan. | `after_targets` returns END when `plan_id` is absent, with a message naming the empty adoption; `targets` records the adoption in `training_goals` before proposing so it is never proposed twice. | `test_targets_node.py`. |
| P3 | `tools/design_next_week.py:69` returns violations that `adjust.py:44-55` drops; `checkin.py:53-57` approves. | `changes_from_messages` returns `(changes, summary, violations_by_week)`; the adjust node puts them in `pending_violations`; the review payload carries them; `checkin --yes` skips the violating week's changes, prints them, exits 1 when any were skipped. Interactive review prints them under the summary. | `test_adjust_node.py`, `test_checkin.py`. |
| P4 | `apply.py:125-133` marks any week receiving a `create` as written. | Mark only weeks whose `designed` is not null. | `test_apply_node.py`. |
| P5 | `targets.py:68-93` records ownership of every workout in the window on adoption. | List the calendar before `tp_apply_training_plan`, then after; own only ids that appeared. | `test_targets_node.py`: a pre-existing athlete workout is not owned. |
| P6 | `repo.py:258-265` divides the 28-day sum by 4 regardless of days present. | `weekly = total / days_with_data * 7` when `n >= 7`, else `None` so `week1_tss` falls back to CTL. | `test_repo.py`: five days of data yields `None`; 14 days scales. |
| P7 | `design.py:30` starts the window at this week's Monday while the plan starts next Monday. | `window_weeks(weeks, today, horizon)` starts at the first plan week on or after `week_monday(today)`: `first = max(week_monday(today), weeks[0].week_start)`. | `test_design_node.py`: horizon 3 on a Wednesday designs 3 weeks. |
| P8 | `planning/targets.py:67-86` gives the Ironman peak block no recovery week and does not reset the counter at a phase change. | `peak` counts as a loading phase with `RECOVERY_EVERY_N_WEEKS`; `since` resets when the phase changes. | `test_targets.py`: 24-week Ironman has a recovery week inside peak; the first build week is not a recovery week. |
| P9 | `validate.py:42-49` bounds dates by the model's `week_start`; `structure_seconds` KeyErrors on distance steps; `None` from structured output asserts. | Validate against `target.week_start` and reject a mismatched `week_start`; a step without `duration_seconds` is a violation, not an exception; `None` from the designer is retried once, then a violation. | `test_validate.py`, `test_design_node.py`. |

### 2.4 tri-core

| # | Defect | Change | Test |
|---|---|---|---|
| C1 | `mcp/client.py:54-64`: a failing `initialize` leaks the subprocess. | `__aenter__` wraps the enters in `try`; on any exception it closes the stack and re-raises. `asyncio.wait_for(..., SESSION_TIMEOUT_S)` around the whole enter. | `test_mcp_client.py` with a fake `stdio_client` that raises in `initialize`: the stack is closed. |
| C2 | `db/sql_tool.py:91-96` returns `Decimal` as a string. | `Decimal` becomes `float`. | `test_sql_tool.py`. |
| C3 | `sql_tool.py:108-114` caps rows, not bytes. | `MAX_CHARS = 8000`: the JSON is truncated to whole rows under the cap with `"truncated": true` and a note to narrow the query; the tool docstring says so. `select *` on `workouts` is still allowed. | `test_sql_tool.py`: a wide result is cut at the row boundary. |
| C4 | `sync/garmin.py:91-97` keeps the day's highest readiness. | Keep the latest entry by timestamp. | `test_sync_garmin.py`. |
| C5 | `sync/runner.py:128-135`: the `except` path can raise on a dead connection. | Wrap `set_sync_state` in its own `try`; a failure there is logged and the report row carries both errors. | `test_sync_runner.py`. |

### 2.5 tri-coach

| # | Defect | Change | Test |
|---|---|---|---|
| K1 | `review.py:35-48` applies a change twice when `propose_changes` repeats an id. | `ProposalRequest.ids` is de-duplicated in order in the review node. | `test_review_node.py`. |
| K2 | `repl.py:49-55` tags every root `model`/`tools` node as `analyst`, so `ask_wellness` output reads as the analyst's. | `agent_tool` runs each question with `tags=["tool:<name>"]`; `_tag` reads the tag and returns `analyst` or `wellness`. | `test_repl.py`: an `ask_wellness` run streams under `[wellness]`. |
| K3 | After an edit, the coach's history holds the original proposal (`review.py:71-76`, `apply.py:200`). | `apply`'s report message lists each applied change as applied, so an edit is visible to the coach and to `remember(checkin)`. | `test_graph_apply.py`. |
| K4 | `apply.py:214` resets `proposals`, so a follow-on is numbered `p1` again. | Ids continue from the turn's highest: `next_proposal_id` in state, reset in `start_node`. | `test_nodes.py`. |

### 2.6 tri-analyze and tri-web

| # | Defect | Change | Test |
|---|---|---|---|
| A1 | `repl.py:63`: a bare `/` raises `IndexError`. | `name = (line[1:].split() or [""])[0]`; an empty name prints the command list. | `test_repl.py`. |
| A2 | `evals/evaluators.py:23-35` `states_window` matches "decoupling 5%". | Month names require a word boundary and a following day or year; the check also ignores text that repeats the question. | `test_evals.py` negatives. |
| B1 | `routes/coach.py:42-46`: a turn during a paused review drops the review. | `post_turn` returns 409 `{"reason": "paused"}` when `paused_review` is not `None`. `Chat.tsx:73` disables the composer while `paused` is set, with the hint "answer the review first". | `test_routes_coach.py`; `chat.test.tsx`. |
| B2 | `app.py:63-66` returns exception text in 500 bodies. | The body is `{"detail": "internal error"}`; the text goes to the log. | `test_app.py`. |

## 3. Migration 006

`migrations/006_fixes.sql`, applied to both databases:

```sql
alter table lab_results add column if not exists bound text;
alter table lab_panels add column if not exists source_sha text;
create index if not exists lab_panels_source_sha_idx on lab_panels (source_sha);
drop index if exists fuel_plans_kind_day_workout_idx;
create unique index if not exists fuel_plans_kind_day_workout_title_idx
  on fuel_plans (kind, day, coalesce(tp_workout_id, ''), coalesce((payload->>'title'), ''));
alter table training_goals add column if not exists tp_plan_applied_at timestamptz;
```

The data layer spec takes 007, the guardrails spec 008, and the hygiene spec 009 and 010.

## 4. Testing

Every row above names its test. Beyond those: the full suite, `ruff` and `mypy` pass; `tri-wellness eval` and `tri-nutrition eval` are rerun by Brian after merge (W9 bumps the report prompt; N2 changes what the fuel judge sees), and the new rates are recorded in `docs/notes/`.

## 5. Out of scope

- The sync window, tombstones and brick matching (data layer spec).
- Python-owned TSS, validate-then-refuse and the consult budget (guardrails spec).
- The evaluators' grounding rules (evaluators spec).
- A repair of already-stored SI panels.

## 6. Rollout

One plan, one branch, one commit per package section (2.1 to 2.6) plus the migration. Brian runs migration 006 on both databases before merging. The order inside the plan is 2.1, 2.2, 2.3, 2.5, 2.4, 2.6 so the two evals that change are re-baselined last.
