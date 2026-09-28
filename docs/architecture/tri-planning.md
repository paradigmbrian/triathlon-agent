# tri-planning

[Architecture index](README.md) · [Package README](../../packages/tri-planning/README.md)

Turns a goal into week targets, designs each week with one structured model call, and adjusts the live calendar with an agent. Standalone, it has its own review and apply. When the coach embeds it (`embedded=True`), the graph has no review or apply nodes; it stops at a proposal, and the coach reviews and applies it.

![tri-planning graph](diagrams/tri-planning.svg)

- **route** is code: `repo.derive_phase` reads the tables and picks intake, planning or active. Pending changes go straight to review.
- **intake** is an agent loop on `PLANNING_AGENT` with `query_training_db`, `set_training_goal` and `list_tp_training_plans`.
- **targets** is code: goal and fitness become `WeekTarget`s.
- **design** makes one `structured()` call on `PLANNING_DESIGN` per week in the window and retries once with the violations. A week that still fails is stored with its violations and not proposed.
- **adjust** is an agent loop on `PLANNING_AGENT` with the SQL tool, Garmin readiness and HRV, `tp_get_workouts`, `design_next_week` and `propose_calendar_changes`. The last one writes nothing; it validates the proposal and returns it.
- **review** pauses with `interrupt()`. A reject goes back to whichever of design or adjust made the changes.
- **apply** is the only TrainingPeaks writer. It reconciles pending rows first, writes each change through `recorded_write` into `plan_changes`, and touches only workouts it owns unless the athlete asked. After a TrainingPeaks plan is applied, it goes back to targets.

## Guardrails

`validate.week` checks each designed week: TSS within 10% of target, hours under the weekly maximum and at least 80% of target, sessions of at most 360 minutes, a VO2 duration cap, only available days and allowed sports, structure that sums to the duration, and no hard sessions on consecutive days.

## Data and evals

- Writes `training_goals`, `training_plans`, `plan_weeks` and `plan_changes`. Reads `daily_metrics`, `workouts` and `athlete_profile`.
- The eval runs `design_target` on `PLANNING_DESIGN` and scores it with the `validator_pass` code check. There is no judge.
