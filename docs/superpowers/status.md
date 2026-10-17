# Specs and plans: status

The one place to see what is open and what shipped. Each spec and plan also carries the same
`**Status:**` line under its title. Updated 2026-10-17.

## How to keep this current

- A new spec starts as `**Status:** Open: draft, no implementation plan yet.` and gets a row
  under Open.
- A new plan gets `**Status:** Open: not started.` under its H1, and its spec's row names it.
- At merge, set both status lines to `Implemented YYYY-MM-DD (merge <sha>)` and move the row
  from Open to Shipped. Anything the merge leaves undone (an eval run, a follow-up test) goes in
  the status line after `Open:` and stays listed under Open follow-ups.
- A spec replaced by another one reads `Superseded by <file>`.
- Checkboxes inside plans are working notes for the run that executes them. They are not the
  record; this file and the status lines are.

## Open

| Spec | State | Next step |
|---|---|---|
| [`2026-09-28-optimizations-design.md`](specs/2026-09-28-optimizations-design.md) | Draft, no plan | Write the plan first in round two: coach thread bound and cacheable prefix (§4.4), parallel sync (§4.3), fuel fingerprint (§4.2), SQL cell cap (§4.1), non-blocking web reads (§4.6). |
| [`2026-09-28-test-gaps-design.md`](specs/2026-09-28-test-gaps-design.md) | Draft, no plan | Second: judge calibration (§4.1) before more analyst prompt work; bought-plan reject test (§4.2); real-backend e2e (§4.4). |
| [`2026-09-28-features-design.md`](specs/2026-09-28-features-design.md) | Draft, no plan | Third: C3 resumable turns and ask-while-paused, C4a weekly and race readiness; then C1, C2, C4b. |

### Open follow-ups from shipped work

| Item | From | Next step |
|---|---|---|
| Design-v2 eval run: `uv run tri-planning eval`, 23 cases, no baseline (~$1 per the usage audit) | [evaluators](plans/2026-09-27-evaluators.md) | Needs Brian's approval before it runs. |
| Coach-v4 eval comparison: `uv run tri-coach eval`, 13 cases, no baseline (~$1 per the usage audit) | [guardrails-02](plans/2026-09-27-guardrails-02-consults-and-held-reviews.md) | Needs Brian's approval before it runs. |
| Analyst `grounded` at 6/12 | [analyst-grounding](specs/2026-09-28-analyst-grounding-design.md) | After judge calibration (test-gaps §4.1). Failures: `docs/notes/2026-09-28-analyst-grounding-runs.md`. |
| Sync DB calls on the event loop in `build_today`, `build_progress` and the coach node | `docs/notes/2026-10-17-codebase-review.md` | Fix with `asyncio.to_thread` (part of optimizations §4.6). |
| Nutrition and Labs pages are placeholders | `PRODUCT.md` | No spec yet. |

## Shipped

| Spec | Plans | Merged |
|---|---|---|
| [tri-analyze](specs/2026-09-06-tri-analyze-design.md) (superseded by tri-analyze alignment) | [foundation-and-sync](plans/2026-09-06-foundation-and-sync.md), [agent-v1](plans/2026-09-06-agent-v1.md) | 2026-09-06 to 09-07, `51ad9ff`, `165da30` |
| [tri-planning](specs/2026-09-07-tri-planning-design.md) | [01](plans/2026-09-07-tri-planning-01-workspace.md), [02](plans/2026-09-07-tri-planning-02-targets-and-schema.md), [03](plans/2026-09-07-tri-planning-03-graph-v1.md), [04](plans/2026-09-07-tri-planning-04-adjust-and-checkin.md) | 2026-09-11, last `d66a54b` |
| [tri-nutrition](specs/2026-09-10-tri-nutrition-design.md) | [01](plans/2026-09-10-tri-nutrition-01-math-and-schema.md), [02](plans/2026-09-10-tri-nutrition-02-profile-and-targets.md), [03](plans/2026-09-10-tri-nutrition-03-fueling.md), [04](plans/2026-09-10-tri-nutrition-04-checkin.md) | 2026-09-11, last `41e2288` |
| [tri-wellness](specs/2026-09-10-tri-wellness-design.md) | [01](plans/2026-09-11-tri-wellness-01-ranges-and-evaluate.md), [02](plans/2026-09-11-tri-wellness-02-ingest.md), [03](plans/2026-09-11-tri-wellness-03-report-and-chat.md) | 2026-09-12, last `b223e1f` |
| [tri-coach](specs/2026-09-11-tri-coach-design.md) | [01](plans/2026-09-12-tri-coach-01-sub-package-preparation.md), [02](plans/2026-09-12-tri-coach-02-coach-v1.md), [03](plans/2026-09-13-tri-coach-03-wellness-consult.md), [04](plans/2026-09-13-tri-coach-04-checkin-and-follow-on.md) | 2026-09-13, last `2ab4b70` |
| [tri-analyze alignment](specs/2026-09-13-tri-analyze-alignment-design.md) | [01](plans/2026-09-13-tri-analyze-01-alignment.md), [02](plans/2026-09-13-tri-analyze-02-eval.md) | 2026-09-13, `9623c5d`, `b8c1b04` |
| [tri-web](specs/2026-09-14-tri-web-design.md) | [01](plans/2026-09-14-tri-web-01-server-core.md), [02](plans/2026-09-14-tri-web-02-today-jobs-settings.md), [03](plans/2026-09-14-tri-web-03-frontend.md) | 2026-09-14, `66f3575`, `86d50e5`, `eaa7fb1` |
| [tri-harness](specs/2026-09-15-tri-harness-design.md) | [01](plans/2026-09-15-tri-harness-01-core.md), [02](plans/2026-09-15-tri-harness-02-analyze-wellness.md), [03](plans/2026-09-15-tri-harness-03-planning-nutrition.md), [04](plans/2026-09-15-tri-harness-04-coach-web.md) | 2026-09-16, `a9c4a8b`, `6e06e78`, `8f3a62d`, `506c086` |
| [model routing](specs/2026-09-15-model-routing-design.md) | [01](plans/2026-09-22-model-routing-01-registry.md), [02](plans/2026-09-22-model-routing-02-evals.md) | 2026-09-24, `165cf49`, `0186d8f` |
| [correctness fixes](specs/2026-09-24-correctness-fixes-design.md) | [01](plans/2026-09-24-correctness-fixes-01-wellness-nutrition.md), [02](plans/2026-09-24-correctness-fixes-02-planning-coach-core.md) | 2026-09-25, `b14a0bc`, `146a2a1` |
| [data layer](specs/2026-09-24-data-layer-design.md) | [data-layer](plans/2026-09-25-data-layer.md) | 2026-09-26, `a850c94`, follow-up `91faf25` |
| [hygiene](specs/2026-09-24-hygiene-design.md) | [hygiene](plans/2026-09-27-hygiene.md) | 2026-09-27, `38d2661` |
| [guardrails](specs/2026-09-24-guardrails-design.md) | [01](plans/2026-09-27-guardrails-01-tss-and-refuse.md), [02](plans/2026-09-27-guardrails-02-consults-and-held-reviews.md) | 2026-09-27, `d9ca6b0`, `8545f8e`; coach-v4 eval open |
| [evaluators](specs/2026-09-24-evaluators-design.md) | [evaluators](plans/2026-09-27-evaluators.md) | 2026-09-28, `9f4e6b1`, follow-ups `a04184b`; design-v2 eval open |
| [analyst grounding](specs/2026-09-28-analyst-grounding-design.md) | [analyst-grounding](plans/2026-09-28-analyst-grounding.md) | 2026-09-28, `8eb8506` |
| [eval cost](specs/2026-09-28-eval-cost-design.md) | [eval-cost](plans/2026-09-28-eval-cost.md), [follow-up](plans/2026-09-28-eval-cost-followup.md) | 2026-09-28, `9f4f048`, `3c11c15` |
| [web polish](specs/2026-09-28-web-polish-design.md) | [web-polish](plans/2026-09-28-web-polish.md) | 2026-09-29, `4fa5b1d` |
| [preflight board](specs/2026-09-29-preflight-board-design.md) | [preflight-board](plans/2026-09-29-preflight-board.md), [readiness-scale](plans/2026-09-29-readiness-scale.md) | 2026-09-29, `0b593b4` to `a672719`, `e1c8981` to `1fb159c` |
| [Progress page](specs/2026-09-29-progress-page-design.md) | [progress-page](plans/2026-09-29-progress-page.md) | 2026-09-29, `292e2db` to `123ab0e` |
