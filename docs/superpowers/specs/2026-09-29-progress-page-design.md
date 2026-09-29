# Progress page: performance management and weekly volume

**Date:** 2026-09-29
**Status:** Approved 2026-09-29; implemented on `feat/progress-page` (plan: `docs/superpowers/plans/2026-09-29-progress-page.md`)
**Purpose:** Piece 1 of three toward surfacing the TrainingPeaks dashboard metrics (Brian's screenshots, 2026-09-29) in tri-web. This piece fills the `/progress` placeholder using only data already synced. Piece 2 (sleep, HRV, weight and body-fat history) and piece 3 (time in zones, peak power/HR/pace) get their own specs; piece 3 starts with a feasibility spike because the store holds per-workout aggregates only. Line references are `main` @ 9760e03.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | PMC chart, ramp rates, weekly volume by sport, longest workout, sport share. | The TP charts computable from `workouts` and `daily_metrics` today. |
| Range | Picker: 6 weeks, 6 months, 12 months, All. Default 12 months. | Weekly charts stay readable; the PMC covers a season. |
| Charts | Hand-rolled SVG components, no chart library. | Matches `Sparkline.tsx`, no dependency, full control of DESIGN.md tokens and accessibility. |
| Data | One endpoint, `GET /api/progress`, computed in Python. | The frontend only draws; types come from OpenAPI as today. |
| Sport share | Horizontal bars, not pies. | Lengths compare better and take direct labels. |
| Out of scope | Event-date CTL projection; zones, peaks; weight, body fat, nutrition. | Events not confirmed stored; the rest are pieces 2 and 3. |

## 2. Backend

New `packages/tri-web/src/tri_web/progress.py` with `build_progress(rt, range)`, and `routes/progress.py` registering `GET /api/progress?range=6w|6m|12m|all` (default `12m`). Structure follows `today.py` and `routes/today.py`. Models go in `schemas.py`.

### 2.1 Response (`ProgressView`)

- `range`: the requested range, plus `start` and `end` dates actually covered (`all` starts at the earliest stored workout or metric).
- `as_of`: date of the latest `daily_metrics` row with CTL, so the page can state how fresh the curve is.
- `pmc`: one entry per day in range: `{date, ctl, atl, tsb, tss}`. A day with no stored value is null, never interpolated.
- `ramp`: for windows 7, 28, 90 and 365 days, `{days, delta, series}`. `delta` is CTL(as_of) minus CTL(as_of minus days), null when either end is missing. `series` is the CTL over that window (nulls kept) for the tile's sparkline.
- `weeks`: one entry per Monday-start week in range: `{week_start, partial, by_sport, longest}`.
  - `by_sport` maps sport to `{duration_sec, distance_m, elevation_m, calories, tss}`, summed over completed workouts only.
  - `longest` is `{duration_sec, distance_m}`: the largest single completed workout in the week.
  - `partial` is true for the week containing today.
- `share`: `{completed, planned}`, each `{duration_sec, distance_m}` mapping sport to its total over the range. Planned uses the `planned_*` columns of all non-deleted workouts in range.
- Sports keep the normalised vocabulary from `sync/sports.py`; the frontend maps unknown sports to "Other".

### 2.2 Rules

- Aggregation reads `workouts` (`completed`, `actual_*`, `planned_*`, `elevation_gain_m`, `calories`, `sport`) and `daily_metrics` (`ctl`, `atl`, `tsb`, `tss_day`) through the existing repo layer; add a `list_daily_metrics_between` query only if none exists.
- Deleted workouts are excluded, as elsewhere in the repo.
- Null columns count as zero in sums but never make a workout "longest".
- No LLM calls; this endpoint spends no Anthropic credit.

## 3. Frontend

- `web/src/pages/Progress.tsx` replaces `Placeholder` for `/progress` in `router.tsx`. `Placeholder` stays for Nutrition and Labs; its `subProject` type loses `2`.
- `useProgress(range)` in `queries.ts`, keyed by range; the range picker state lives in the URL search param `?range=` so a view is linkable and survives reload.
- `web/src/components/progress/`:
  - `RangePicker`: segmented control, keyboard operable, at least 24px targets.
  - `Pmc`: CTL area and ATL line in one panel, and TSB in a second panel below on the same x axis, with the 0 line and the neutral-form band (-10 to 5). Two panels replace a dual axis, which reads more clearly. Null days break the line.
  - `RampRates`: four tiles (7, 28, 90, 365 days) with the delta as a signed figure and a `Sparkline`.
  - `WeeklyBars`: stacked bars by sport, a metric switch (distance, duration, elevation, calories), a dashed average line, and the partial week drawn hatched and labelled.
  - `LongestWorkout`: one bar per week with a dashed average, switchable between duration and distance.
  - `ShareBars`: horizontal bars by sport for completed vs planned, duration and distance.
  - Shared: an axis and scale helper and a chart frame that carries the title, the summary text and the "view as table" toggle.
- Styling uses the DESIGN.md tokens. Sport identity uses a distinct fill plus a distinct marker shape in the legend and a direct label on the share bars, so colour is never the only cue.

### 3.1 Accessibility (WCAG 2.2 AA)

- Each chart frame has a one-sentence text summary (for example, "CTL 16, up 1 over 28 days") and a "view as table" toggle that swaps the SVG for a real `<table>` of the same data.
- Each chart has a slider that steps through its points with the arrow keys and shows the value in a visible readout, and the PMC also reads on pointer move; bars and points are not individual tab stops, so a 150-week history is one stop.
- Motion respects `prefers-reduced-motion`; nothing animates by default.
- Contrast for text and lines meets AA in both themes; no status by colour alone.
- Layout works at phone width with a 16px gutter and no horizontal page scroll; wide charts scroll inside their frame only if needed.

### 3.2 States

- Loading: skeleton frames per chart. Error: one inline message with retry, not a blank page.
- Empty range: each chart says "No data in this range" and the page states `as_of` and the last sync date.
- Stale data: if `as_of` is more than 3 days old, show it next to the title (Product Principle 4).

## 4. Testing

- `tests/test_progress.py`: week bucketing on Monday boundaries; the partial current week; gaps in `daily_metrics` staying null; ramp windows with a missing start; range clipping including `all`; sport sums with null columns; deleted workouts excluded; empty store.
- Route test in `tests/test_routes_progress.py` with the existing fake runtime: default range, each range value, an invalid range returns 422.
- Frontend (vitest): each chart with empty, single-week and gapped data; the table toggle; the range picker updating the URL param; the partial-week label.
- Playwright: one smoke test that `/progress` renders all frames and the range picker changes the request.
- Definition of Done, in order: full tests, lint and type checks (`npm run lint`, `tsc`), production build.
- No `tri-* eval` runs and no `pytest --live` are needed.

## 5. Delivery

- Regenerate `web/openapi.json` and `web/src/api/types.ts` with `npm run types`.
- Update `docs/architecture/tri-web.md` with the new route and `DESIGN.md` with the chart components once shipped.
- Copy this spec and the resulting plan to the Obsidian vault at `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/docs/superpowers/`.
