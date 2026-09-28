# Anthropic API usage audit, September 2026

**Date:** 2026-09-28
**Question:** What made live Claude calls on the `tri_analyze_api_key` key ($20.29 month to date), when the web server and CLI chat were barely used?

## Answer

Almost all of the spend is **LangSmith evals** (`tri-* eval`) that the specs and plans told someone to run. Each eval runs every case through the real target model (Opus 5) and then through an Opus 5 judge. A small amount comes from `pytest --live` and from live probes during the early builds. Nothing ran unattended: CI has no Anthropic secret, and there is no cron job, launchd agent or leftover process.

All seven CLIs read the one `ANTHROPIC_API_KEY` from the repo's `.env`, so every package's evals bill to this key, not just `tri-analyze`. (The console shows the key's name. I couldn't confirm locally that the `.env` value is the key named `tri_analyze_api_key`, but it is the only Anthropic key the repo uses.)

## Sources

- Claude Code transcripts for this project, which cover 2026-09-25 17:28 to 2026-09-28 UTC. Older transcripts have been pruned.
- The `.evals/*.jsonl` results files and their modification times.
- `docs/notes/2026-09-24-model-routing-tuning.md` and `2026-09-28-analyst-grounding-runs.md`.
- Git history for 2026-09-05 to 2026-09-24. This is the only source before Sep 25, so the rows for those dates are inferred.

Times are UTC to match the console. Local time is EDT (UTC−4).

## Live calls by day

| Console day (UTC) | Console cost | What ran | Who started it | Spec / plan | Evidence |
|---|---|---|---|---|---|
| Sep 7 to 15 | about $5 total (bars on Sep 7, 10, 11, 14, 15) | First builds of each package. Live probes, then the first eval runs as each eval command landed: nutrition fuel eval and live runs (Sep 10–11), planning design-week eval (Sep 11), wellness live PDF extraction and report eval (Sep 11–12), coach routing eval and analyst feedback eval (Sep 13), analyze harness refactor (Sep 15) | Plan execution sessions | `2026-09-07-tri-planning-*`, `2026-09-10-tri-nutrition-*`, `2026-09-11-tri-wellness-*`, `2026-09-12/13-tri-coach-*`, `2026-09-13-tri-analyze-02-eval` | **Inferred** from commits (`15da0fc` "first live run notes", `8a7ebb3` fuel eval, `87dfd41` design dataset, `2f9aa3d` live PDF test, `fa19e1d` report eval, `dc1ee89` coach eval, `91a8329` analyst eval, `a4e77e6`). No transcripts remain |
| Sep 24 | about $9.50 (Opus 5 plus a little Sonnet 5) | **Model-routing tuning, 9 eval runs:** 5 baselines (analyst 12, coach 13, fuel 5, report 4, design 23 cases) and 4 candidates (analyst opus-5 medium, analyst sonnet-5 medium, coach opus-5 high, fuel sonnet-5). The Sonnet 5 slice is the two sonnet candidates | Plan execution (plan 02 Task 3) | `2026-09-15-model-routing-design.md` §7.2 and `2026-09-22-model-routing-02-evals.md` lines 841–856 | `2026-09-24-model-routing-tuning.md`, commit `fda73d5` |
| Sep 26 | about $0.20 | `pytest --live -m live`, run twice (10:35 and 10:36) while checking MCP auth. Of the live tests, only `tri-coach/tests/test_live.py` calls Claude: one real coach turn per run. The wellness live PDF test skipped because `TRI_WELLNESS_LIVE_PDF` is unset | A Claude session, checking Garmin and TrainingPeaks auth | `2026-09-25-data-layer.md` (auth follow-up) | Transcript `1cdcb0c8`: "4 passed, 1 skipped" |
| Sep 27 | $4.74 (Opus 5) | **`tri-analyze eval`, `tri-coach eval` and `tri-planning eval` in parallel** at 09:45. coach-v3 ran 13 cases and design ran 23; the retained log doesn't show the analyze result | A Claude session, following your handoff note ("3. Re-run the evals: tri-analyze eval, tri-coach eval and tri-planning eval") | Handoff note; `2026-09-27-evaluators.md` post-merge steps | Transcript `c431991c`, background task `b4g4e4t1s` |
| Sep 28 | not yet in the console | **4 `tri-analyze eval` runs from your terminal**, 12 cases each, analyst and judge both `claude-opus-5`: `analyst-v2-base` (10:39), `fresh-decision-92` (12:09), `analyst-v2-judge2 --local` (15:00), `analyst-v3-judge2 --local` (15:17) | You, as the spec asked | `2026-09-28-analyst-grounding-design.md` §Rollout ("Brian runs `uv run tri-analyze eval …`"), `2026-09-27-evaluators.md` line 1361 | `.evals/*.jsonl` modification times; pasted output in transcripts `5f66d72d` and `f1957e39` |

## What an eval run costs

Sep 24 had 9 runs for about $9.50, so a typical run costs **about $1**. The analyst eval is the most expensive per case: each case is a multi-turn tool-using agent run on Opus 5 plus an Opus 5 judge call with the full tool results. At that rate Sep 28's four analyst runs should show up as roughly $4–6 once the console catches up.

`--local` only stops LangSmith uploads. The model calls are the same, so a local run costs the same as a normal one.

## Ruled out

- **Web server and CLI chat:** no `tri-web serve` or `tri-* chat` in any retained transcript.
- **CI:** `.github/workflows/ci.yml` has no `ANTHROPIC_API_KEY` secret, and `pytest` in CI skips `--live`.
- **Scheduled jobs:** no crontab entry, no LaunchAgent, and no `tri-*` process running now.
- **The pre-Sep-24 test suite:** before `f5e64e4`, importing a CLI loaded `.env` into pytest. That sent 4,746 test traces to LangSmith on Sep 11–12, but the tests run on fake models. The console shows no matching spend on those days, so the leak cost LangSmith quota, not Anthropic credit.

## Coming next in the specs and plans

- `2026-09-27-evaluators.md` line 1362: `uv run tri-planning eval` (design-v2) is still pending. That's 23 cases.
- `2026-09-27-guardrails-02` line 992: a `tri-coach eval` (coach-v4) comparison.
- `2026-09-28-features-design.md` bumps three prompt versions (wellness report 3, fuel 5, design 3). Each bump implies an eval run.
- `2026-09-28-test-gaps-design.md` (judge calibration) draws its cases from existing `.evals/*.jsonl` files. That needs no new target runs, but it does make judge calls.

## Options to cut cost (not applied)

- Run candidate or iteration evals with the judge on Sonnet 5 (`TRI_MODEL_JUDGE=claude-sonnet-5`), and keep Opus for the final gate.
- Run a subset of cases while iterating (for example the failing `grounded` cases), and the full set only for the gate.
- Ask for eval runs to be listed with an estimated cost in each plan's hand-off steps.
