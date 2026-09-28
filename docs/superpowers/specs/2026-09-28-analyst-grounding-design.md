# Analyst grounding: zones in context, weekdays, SQL arithmetic, a judge that checks derivations

**Date:** 2026-09-28
**Status:** Draft
**Purpose:** Fix what the local `analyst-v2-base` run (`.evals/fresh-decision-92.jsonl`, grounded 1/12) showed. The analyst invents zone ranges, thresholds and baselines, miscounts, and misnames weekdays. The judge fails plain conversions it could check, misreads SQL rows, and misnames weekdays itself. Follows `2026-09-24-evaluators-design.md`; lands before `2026-09-28-test-gaps-design.md` §4.1, whose calibration labels must use this spec's `grounded` rule. Line numbers are `main` @ 8acf0bf.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Zones | The analyst's context block shows the athlete's HR, power and pace zones. The eval seeds real zones (chosen 2026-09-28). | The context points at a jsonb column, and the eval profile's zones are null (`seed.py:351-353`). Every "Z2 = …" in the run was invented by construction. |
| `grounded` | A number is grounded when it appears in the evidence or the judge can reproduce it from the evidence within the answer's rounding. Shown arithmetic is no longer required (chosen 2026-09-28). | Most flagged lines were checkable conversions ("5460 s = 91:00", "132/172"). They hid the real errors: wrong sums, invented ranges. |
| Rollout | Judge first, then analyst: two local runs (chosen 2026-09-28). | Each change's effect is visible on its own. |
| Weekdays | The analyst context shows weekdays on every date and the Monday of each week. The judge prompt gets the same calendar line (chosen 2026-09-28). | Both the analyst and the judge named 2026-09-12 and 2026-09-19 wrongly. |
| SQL rows | The judge sees `query_training_db` results as one `column: value` line per row. The analyst's tool output is unchanged. | The judge read a 21-column row out of position (`last_z2_ride`: power read as HR and cadence). The analyst read it correctly, and records would cost it tokens on every query. |
| Judge model | Unchanged: `Role.JUDGE`, structured output. Only its prompt and field description change; `JUDGE_VERSION` records which. | Comparability, and experiments say which judge scored them. |

## 2. Feasibility, verified 2026-09-28

- Context: `render_system_prompt` (`tri_analyze/prompts/analyst.py:123`) renders `Today is {iso}` (`:132`), `_profile_block` (`:67`, thresholds plus a pointer to the zone columns), `_days_block` (`:80`) and `_workouts_block` (`:94`), all with ISO dates and no weekday. `load_athlete_context` selects only threshold columns (`tri_analyze/repo.py:23-25`).
- Zone shape: sync stores TrainingPeaks zone groups as lists of `{workoutTypeId, threshold, zones: [{label, minimum, maximum}]}`, where `workoutTypeId` 1 is swim, 2 bike, 3 run and 0 the default (`tri_core/sync/trainingpeaks.py:17`, `:121-129`). Speed zones are in m/s. The fixture `tri-core/tests/fixtures/mcp/tp_get_athlete_settings.json` has HR groups 0/1/2/3, power 0/2 and speed 0/1/3.
- Judge: `FeedbackJudgement.grounded` (`tri_analyze/evals/evaluators.py:110`), `JUDGE_SYSTEM` (`:137`), `render_judge_prompt` (`:155`), which passes each tool result's content through verbatim.
- Analyst rules: `FEEDBACK_RULES` (`prompts/analyst.py:37`), `PROMPT_VERSION = "2"` (`:13`).
- Eval: `PROFILE` (`evals/cases.py:20`), `TODAY = 2026-09-16`, a Wednesday; the seeded profile has null zones (`evals/seed.py:351-353`). Local runs write `.evals/<name>.jsonl`.

## 3. Judge (step 1)

### 3.1 `grounded`

The field description becomes, exactly: `every number in the answer appears in the context or the tool results, or can be reproduced from them by a unit conversion or arithmetic within the answer's rounding; a number that appears nowhere or does not reproduce is ungrounded; a prescribed range must come from the athlete's zones or a stated fraction of a threshold; missing data is stated as missing`.

`JUDGE_SYSTEM`'s Grounded paragraph says the same. It also says: check derivations yourself and do not flag a correct one because its arithmetic is not written out; list in problems only numbers that appear nowhere, do not reproduce (give the value you get), or are prescriptions with no zone or threshold behind them. Dates: use the calendar line to name weekdays and never infer a weekday otherwise.

### 3.2 Judge input

- `render_judge_prompt` renders a `query_training_db` result whose content parses as the tool's envelope (`columns`, `rows`) as one line per row: `- col: value; col: value`. Nulls are shown as `null`, and `truncated`/`note` are kept on a closing line. Content that isn't that envelope, and every other tool, passes through unchanged.
- A calendar line goes before the context: `Calendar: today {iso} is a {Weekday}. Weeks start Monday: {the six Mondays from four weeks back to next week}.`
- `JUDGE_VERSION = "2"` goes into the experiment metadata and into each `.evals` row's metadata.

## 4. Analyst (step 2)

### 4.1 Context

- **Dates:** every date in `_days_block` and `_workouts_block` renders as `2026-09-12 (Sat)`. The today line becomes `Today is 2026-09-16 (Wed). Weeks start Monday: …`, with the same six Mondays as the judge's line. One helper, `calendar_line(today)`, lives in `tri_analyze/prompts/analyst.py`, and the judge imports it.
- **Zones:** `load_athlete_context` also selects `hr_zones`, `power_zones` and `pace_zones`. A new `_zones_block(profile)` renders, when present:
  - bike power (group 2, else 0) as `Z1 0-137 W, Z2 138-188 W, …`;
  - run HR (group 3, else 0) and bike HR (group 2) when it differs;
  - run pace (speed group 3) as min:ss/km, fastest last;
  - swim pace (speed group 1) as min:ss/100m.

  Labels become `Z<n>` plus TrainingPeaks' name when it has one (`Z2 Aerobic`). With no zones at all, the block says `Zones: not synced; prescribe only as a stated % of a threshold.`

### 4.2 Rules (`FEEDBACK_RULES`, `PROMPT_VERSION` → "3")

Added:
- **Prescriptions:** every prescribed range (power, HR, pace) names a zone from the context, or states a fraction of a threshold together with the result, for example "56-75% of FTP 250 W, 140-188 W". No other ranges.
- **No invented numbers:** no invented thresholds, baselines or cutoffs. A baseline is computed in SQL over a window you state (for example a 28-day mean HRV), or not given.
- **SQL for arithmetic:** counts, sums, averages, ratios and percentages come from SQL, not mental arithmetic. Quote the query's numbers.
- **Weekdays:** name a weekday only as the context shows it, or from SQL (`to_char(d, 'Dy')`).

The existing "show the arithmetic" sentence is removed; the judge no longer needs it.

### 4.3 Eval seed

`PROFILE` gains TrainingPeaks-shaped `hr_zones`, `power_zones` and `pace_zones` built from its thresholds:
- **Power:** Coggan cut-offs at 55/75/90/105/120% of FTP.
- **HR:** Friel run cut-offs at 85/89/94/100/103% of LTHR.
- **Run pace:** cut-offs at 129/114/106/100/97% of threshold time.
- **Swim:** CSS ±5 s/100m bands.

`seed_database` writes them. `athlete()` (the case context) carries them, so the context block and the seeded row agree.

## 5. Errors

- A zone group with a missing or garbled `zones` list is skipped. The block renders whatever groups remain, and says "not synced" when none do.
- A `query_training_db` content that isn't valid JSON, or has no `columns`/`rows`, passes through verbatim.

## 6. Testing

- **Judge:**
  - the exact `grounded` description;
  - `JUDGE_SYSTEM` contains the derivation and calendar sentences;
  - `render_judge_prompt` turns the `last_z2_ride` envelope into lines containing `normalized_power: 160; avg_power: 155; avg_hr: 132`;
  - a non-envelope content passes through unchanged;
  - the calendar line for 2026-09-16 says Wednesday and lists Mondays 2026-08-17 through 2026-09-21;
  - the metadata carries `judge_version`.
- **Context:**
  - weekdays on day and workout lines;
  - `_zones_block` on the tri-core fixture's groups (bike power, run HR, run and swim pace as min:ss, labels);
  - the "not synced" fallback;
  - `load_athlete_context` returns the zones (DB test).
- **Rules:** each §4.2 sentence is present; `PROMPT_VERSION == "3"`.
- **Seed:** the seeded profile's zones equal `PROFILE`'s; the rendered context shows `Z2 138-188 W` for FTP 250.

## 7. Out of scope

The coach's, planning's and nutrition's contexts; `query_training_db` output for the analyst; a judge model change; recomputing the "arithmetic shown" constraint in `2026-09-27-evaluators.md` (superseded here); calibration (test-gaps spec §4.1, which now labels against §3.1).

## 8. Rollout

One branch, `feat/analyst-grounding`, two steps, each ending in a local run that Brian starts:

1. Judge (§3). Brian runs `uv run tri-analyze eval --prefix analyst-v2-judge2`. This is the current analyst under the new judge, compared with `fresh-decision-92` (grounded 1/12).
2. Analyst (§4). Brian runs `uv run tri-analyze eval --prefix analyst-v3-judge2`. This is the analyst's change alone.

The two results files' `failed checks` go into `docs/notes/` with the pass rates. The test-gaps calibration drafts its analyst labels after step 2.
