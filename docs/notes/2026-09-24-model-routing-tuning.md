# Model routing tuning, 2026-09-24

The §7.2 runs from `docs/superpowers/specs/2026-09-15-model-routing-design.md`, plan 02 Task 3. Every run was gated on its printed pass rates: LangSmith rejected every trace upload that day (the workspace's monthly trace quota was spent by the test suite, see commit f5e64e4), so the experiments are not stored there. Passing counts are rate × N. No run fell back to another model (`fell back` never appears in a log), so each result is on the model it names. Judge: `claude-opus-5` throughout.

## Baselines (every role on opus-5 at default effort)

| Experiment | N | Rates |
|---|---|---|
| analyst-base-feb4d978 | 12 | feedback_quality 100, grounded 8, pulls_splits 100, states_window 100, uses_sql 100; 0 errored |
| coach-base-1ccbf857 | 13 | brief_quality 100, no_unrequested_adjustment 100, routing_accuracy 92 |
| fuel-base-b432db9b | 5 | fuel_respects_profile 80, fuel_within_bounds 100, targets_within_bounds 100 |
| report-base-fa797ec0 | 4 | cites_functional_ranges 75, has_required_sections 100, names_active_confounders 50 |
| design-base-6d37af94 | 23 | validator_pass 74 |

## Candidates and the gate

| Experiment | Against | Rates | Gate |
|---|---|---|---|
| analyst-opus5-med-bff86186 (`TRI_EFFORT_ANALYST=medium`) | analyst-base | grounded 33, the rest 100; 0 errored | pass |
| analyst-sonnet5-med-056519a8 (`TRI_MODEL_ANALYST=claude-sonnet-5`, effort medium) | analyst-base | feedback_quality 67, grounded 33, pulls_splits 100, states_window 80, uses_sql 100 | fail: feedback_quality down more than one example |
| coach-opus5-high-2a6b99b7 (`TRI_EFFORT_COACH=high`) | coach-base | brief_quality 83, no_unrequested_adjustment 100, routing_accuracy 92 | fail: brief_quality down, no gain elsewhere, higher cost |
| fuel-sonnet5-e2de5e8a (`TRI_MODEL_NUTRITION_FUEL=claude-sonnet-5`) | fuel-base | identical: 80 / 100 / 100 | pass |

## Adopted (one commit each)

- `analyst`: claude-opus-5 / medium (70126ac).
- `nutrition_fuel`: claude-sonnet-5, no effort (286a605).
- `coach`, `planning_design`, `lab_report` and the ungated roles stay on opus-5 at default effort.

## Notes for the next round

- The report baseline needed `TRI_ATHLETE_SEX` in `.env`; it is `male` now.
- The printed block gives rates only. Printing the scored count per key would make the one-example gate exact when LangSmith holds no rows.
- `grounded` at 8% on the baseline is the analyst prompt's known weak spot, not a routing matter.
