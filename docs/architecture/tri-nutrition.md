# tri-nutrition

[Architecture index](README.md) · [Package README](../../packages/tri-nutrition/README.md)

Keeps a nutrition profile in the LangGraph Store, turns the training horizon into daily targets in code, and plans session fuel with one structured call. Apply writes Garmin daily targets and TrainingPeaks fuel notes. When the coach embeds it, the graph stops after fuel.

![tri-nutrition graph](diagrams/tri-nutrition.svg)

- **route** is code: it checks the Store for a profile. Pending changes go to review, and a targets request goes straight to targets.
- **intake** and **check-in** are agent loops on `NUTRITION_AGENT`. Intake saves the profile. Check-in compares logged intake with the targets and records fuel feedback.
- **targets** is code: profile and sessions become `DayTarget`s, checked by `validate_targets`.
- **fuel** makes one `structured()` call on `NUTRITION_FUEL` (sonnet-5) per session or race plan, validated with one retry.
- **review** pauses with `interrupt()`. With no changes, it saves the profile overrides and skips the pause. A reject goes back to intake or check-in.
- **apply** reconciles pending rows, writes each change through `recorded_write` into `nutrition_changes`, holds changes whose server is down, and refuses to touch notes it did not write.

## Tools

- Profile: `save_nutrition_profile`, `read_nutrition_profile` (the Store), `read_training_plan` (planning tables).
- Garmin reads: `read_garmin_profile`, `read_garmin_nutrition_settings`, `read_body_composition`, `read_hydration`.
- Check-in: `read_intake_vs_targets`, `record_fuel_feedback`, `propose_target_changes`.
- Both agents also get `query_training_db`.

## Guardrails

- Energy availability of at least 30 kcal/kg FFM, calories at or above RMR, protein of at least 1.6 g/kg, hard-day carbs of at least 6 g/kg, no deficit in forbidden phases, and a capped weekly change.
- Fuel: at most 120 g carbs per hour, fluid and sodium in range, only products from the athlete's library, caffeine of at most 6 mg/kg.
- A weight-loss goal together with the disordered-eating flag is refused with a referral message.

## Data and evals

- Writes `nutrition_targets`, `fuel_plans` and `nutrition_changes`. The profile, fuel log and product library live in the Store at `("athlete", "nutrition")`.
- `tri-nutrition today` proposes and writes today's targets without the graph.
- The eval checks `targets_within_bounds` and `fuel_within_bounds` in code, with an optional `fuel_respects_profile` judge.
