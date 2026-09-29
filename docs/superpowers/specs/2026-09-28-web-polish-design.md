# tri-web polish: accessible styling, markdown chat, richer Today cards

**Date:** 2026-09-28
**Status:** Approved 2026-09-28
**Amended:** 2026-09-29, after Brian's review in the browser: the Readiness card became compact tiles and load chips, with no sparklines (§1, §6.3). 2026-09-28, while planning: `acwr_flag` (§6.1, §6.2, §6.3) and the full list of existing test lines that change (§7).
**Purpose:** Option A from the 2026-09-28 web review: a styling and accessibility pass over the React app and richer numbers on the four Today cards, backed by a `ui-ux-pro-max` audit. The Progress page with charts and the visible navigation rail (option B) get their own spec. Line numbers are `main` @ 328ed9a.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | Styling, accessibility and interaction fixes, markdown in the chat, baselines and load zones on the Today cards (chosen 2026-09-28). | Small, independent of the chart library, visible on the page Brian uses every day. |
| Navigation | Stays in the avatar menu; the left rail moves to the Progress spec (B). | It only earns its space once Progress is a real page. |
| Style | Keep the existing minimal look and the `index.css` token palette; do not adopt the skill's stock palettes. | The skill's style pick ("Minimalism & Swiss") matches what exists; its palettes clash with the planning and nutrition hues. |
| Component library | None added. | Tailwind v4 with the existing tokens covers everything here. |
| New dependencies | `react-markdown` and `remark-gfm` only. | Checked with Context7: safe by default (no raw HTML, `defaultUrlTransform`). |
| Charts | None on the Today cards (sparklines were tried and removed, 2026-09-29, as too bulky). Trend charts arrive with B. | The cards stay compact; history belongs on Progress. |

## 2. Findings this spec fixes (verified 2026-09-28)

- No `aria-live`, `role="log"` or `role="status"` anywhere in `web/src`: streamed replies, "thinking…" and job progress are silent to screen readers.
- `animate-pulse` without `motion-safe:` (`AvatarMenu.tsx:55`, `Card.tsx:23`); nothing honours `prefers-reduced-motion`.
- `--warn` `#9a6b00` is 4.34:1 on `--surface` and 3.88:1 on the `bg-warn/15` badge (AA needs 4.5:1).
- `--line` is about 1.2:1 against the surfaces in both themes; cards barely separate from the page.
- Sync status is conveyed by colour alone (`Header.tsx`, `text-warn` on error).
- `cursor-pointer` appears only in `JobButton.tsx`; Tailwind v4 preflight gives buttons `cursor: default` (upgrade guide, checked with Context7).
- 44 uses of `text-xs`, `text-[11px]` or `text-[10px]`; card titles are 11px (`Card.tsx:7`).
- Text buttons ("forget", "retry", Activity toggles) are text-sized, under the 24×24 px WCAG 2.2 minimum.
- No skip link; focus stays on the menu after a route change.
- Assistant bubbles render plain text with `whitespace-pre-wrap` (`Message.tsx:22`), so any markdown shows as raw `*` and `#`.
- The composer hint is always `text-warn` (`Composer.tsx`), even for the routine "a turn is running".
- Readiness leads with sleep score and shows HRV, RHR and TSB as bare numbers with no baseline (`ReadinessCard.tsx`).
- Session and Week cards omit data the tables already hold: IF, HR, power (`workouts`), per-sport TSS and hours.

## 3. Tokens and base styles (`web/src/index.css`)

**Colour.** Changes to `:root` and the dark block, all measured against both surfaces:

| Token | Light | Dark | Note |
|---|---|---|---|
| `--warn` | `#805800` (was `#9a6b00`) | unchanged `#e0b449` | 5.86:1 on surface, 5.10:1 on the 15% badge |
| `--good` (new) | `#23703a` | `#6fcf97` | 5.63:1 / 8.67:1 |
| `--line` | `#d6d3c8` (was `#e2e0d8`) | `#3a3e47` (was `#2c2f36`) | decorative, but cards read as cards |

`--good` joins `@theme inline` as `--color-good`. The status set is then `good`, `warn` and `danger`; status text always carries a word or an arrow as well as the colour.

**Type scale.** No new font: the system stack stays (a local, offline app; no Google Fonts request). The floor is 12px: every `text-[10px]` and `text-[11px]` becomes `text-xs`. Chat bubbles go from `text-sm` to `text-base`; cards stay `text-sm`. `tabular-nums` stays on every metric.

**Base layer.** In `@layer base`:
- `button:not(:disabled), [role="button"], summary { cursor: pointer; }`
- `button, a { transition: color, background-color, border-color 150ms ease-out; }`
- `@media (prefers-reduced-motion: reduce)` sets `transition-duration` and `animation-duration` to `0.01ms` on `*`.

`animate-pulse` becomes `motion-safe:animate-pulse` in both places.

## 4. Accessibility and interaction (web/)

- **Chat log.** The messages scroller (`Chat.tsx:38`) gets `role="log"`, `aria-live="polite"` and `aria-busy` while a turn streams, so a screen reader reads each finished reply once instead of every token.
- **Status line.** The composer hint becomes `role="status"`. Its colour is `text-ink-2` for "a … is running" and "thinking…", and `text-warn` only for lost connection, a paused review and a stuck thread.
- **Skip link.** `Shell.tsx` gains a visually hidden "Skip to main content" link, shown on focus, targeting `<main id="main" tabIndex={-1}>`.
- **Route focus.** On a pathname change `Shell` focuses `main`; the first render does not steal focus.
- **Targets.** Text buttons get `inline-flex min-h-6 min-w-6 items-center px-1` (24 px). That covers forget, retry, the Activity toggle and cancel.
- **Loading labels.** "Confirm reset" reads "Resetting…" while pending; a row's "forget" reads "forgetting…" while its own mutation runs.
- **Sync status.** In `Header.tsx`, each source shows `failed` in `text-danger` when `status !== "ok"`, `stale` in `text-warn` when `last_run_at` is more than 24 h old, and nothing extra otherwise. The error stays in `title`.
- **Placeholder pages.** The copy becomes "Coming soon: {what the page will show}" with no sub-project numbers.

## 5. Markdown in the chat (web/)

`Bubble` renders `role === "assistant"` children through `<Markdown remarkPlugins={[remarkGfm]}>` with a `components` map: `a` opens in a new tab with `rel="noreferrer"`, `table` is wrapped in `overflow-x-auto`, and headings map to one bold size so a reply never out-shouts the page. `urlTransform` stays the default and no rehype plugins are used. User, consult, report and error bubbles are unchanged. Streaming re-renders the partial string on each token; an unclosed `**` shows literally until its pair arrives, which is acceptable. A new `web/src/components/chat/prose.css` holds list, code and table spacing.

## 6. Richer Today cards (tri-web, web/)

### 6.1 Pure metrics, `tri_web/metrics.py` (new)

Constants:

| Name | Value |
|---|---|
| `BASELINE_DAYS` | 28 |
| `SHORT_DAYS` | 7 |
| `SPARK_DAYS` | 14 |
| `BASELINE_MIN` | 14 values |
| `TSB_ZONES` | `< -30` overreaching, `-30..-10` productive, `-10..5` neutral, `5..25` fresh, `> 25` detraining (lower bound inclusive) |
| `RAMP_CAUTION` | 8 CTL per 7 days |
| `ACWR_LOW`, `ACWR_HIGH` | 0.8, 1.3 |

Functions:
- `trend(values: list[float | None], higher_is_better: bool) -> MetricTrend | None`, where `values` is oldest first and ends today. `MetricTrend(now, avg_7d, avg_28d, sd_28d, band: "below" | "normal" | "above" | None, better: bool | None, spark: list[float | None])`. `band` is None under `BASELINE_MIN` values; it is "below"/"above" outside `avg_28d ± sd_28d`. `better` compares `now` with `avg_28d` in the metric's good direction. `spark` is the last `SPARK_DAYS` values. It returns None when `now` is None.
- `tsb_zone(tsb: float | None) -> str | None`.
- `ramp(ctl_now, ctl_week_ago) -> float | None`: the difference, None if either is missing.
- `acwr(atl, ctl) -> float | None`: `atl / ctl`, None when `ctl` is missing or 0.
- `acwr_flag(acwr: float | None) -> Literal["low", "high"] | None`: outside `ACWR_LOW`..`ACWR_HIGH`, so the thresholds live only here.

### 6.2 `TodayView` changes (`tri_web/today.py`)

- `ReadinessOut` gains `trends: dict[str, MetricTrend]` for `hrv`, `resting_hr` (lower is better), `sleep_score`, `sleep_hours` and `training_readiness`, plus `tsb_zone`, `ramp_7d`, `ramp_caution: bool`, `acwr` and `acwr_flag`. `build_today` reads `daily_metrics` for the 28 days ending at the row it already picks (`today.py:215`) in the same connection, and a day with no row is None.
- `WorkoutOut` gains `actual_if`, `avg_hr`, `avg_power` and `normalized_power`, read from the `workouts` columns.
- `SportCount` gains `planned_tss`, `actual_tss`, `planned_hours` and `actual_hours`. Bricks count under `brick` as they do today.
- `WeekOut` gains `planned_to_date` and `completed_to_date`: sessions dated on or before today and how many of those are completed.

`npm --prefix web run types` regenerates `openapi.json` and `types.ts`.

### 6.3 Cards

- **Readiness.** The headline is `training_readiness`, falling back to `sleep_score` when it is null, with the label saying which. The headline carries its own compact arrow. One caption, `arrows: vs 28-day avg`, sits under it (the comparison is also screen-reader text on every arrow). Below is a 2×2 grid of tiles (HRV, RHR, Sleep, Slept), each with its value and a compact arrow (`↓7`, `↑0.3`, or `=` when it rounds to level), coloured `good`/`warn` by `better`. An outside-band value adds the word "low" or "high". The load is one row of chips: `TSB -4.9 neutral`, `ramp +6.1/wk` (warn with "fast" when `ramp_caution`), and `ACWR 1.11` (warn with the `acwr_flag` word). CTL and ATL stay on the small line.
- **Session.** A completed workout adds `IF 0.82 · 148 bpm · 212 W (NP 225)` when present, and `{pct}% of planned` for duration and TSS when both sides exist.
- **Week.** Under the hours bar, one row per sport shows `run 1/2 · 42 of 60 TSS · 1.2 of 2.0 h`. The compliance figure is `completed_to_date / planned_to_date` as "3 of 4 so far". It is hidden when `planned_to_date` is 0.
- **Sparkline.** Removed 2026-09-29: the card was too bulky. `MetricTrend.spark` stays in the API for the Progress page.

**Errors.** Fewer than `BASELINE_MIN` rows means no band and no arrow word; a missing metric omits its row; a missing CTL omits ramp and ACWR. Nothing throws on sparse data.

## 7. Testing

- **pytest.** `tests/test_metrics.py` (new, pure) covers:
  - `trend` below `BASELINE_MIN`, the band edges and `higher_is_better` false;
  - `tsb_zone` at each boundary;
  - `ramp` and `acwr` with missing inputs and zero CTL.

  `test_today.py` gains 28 seeded `daily_metrics` rows with one gap and asserts `trends`, `tsb_zone`, the new workout fields, the per-sport TSS and hours, and `planned_to_date`.
- **vitest.**
  - `strip.test.tsx`: the readiness headline fallback, a `below` HRV row, the TSB zone word, ACWR `high`, the Session IF line and the Week per-sport rows.
  - `chat.test.tsx`: an assistant `**bold**` renders `<strong>`, a user bubble does not, the log role and `aria-busy`.
  - `shell.test.tsx`: the skip link and focus on a route change.
  - A header test for `failed` and `stale`.
- **Existing tests touched (needs Brian's OK with this spec):** `web/tests/fixtures.tsx` gains the new fields. `strip.test.tsx:18` keeps asserting "81", now as the secondary sleep score. `strip.test.tsx:25` changes from the joined `run 1/2 · bike 1/2` line to one assertion per sport row. `shell.test.tsx:31` and `:49` change from `/arrives in sub-project 2/` to `/Coming soon/` for the new placeholder copy. No assertion is weakened or removed.
- **Manual.** `tri-web serve`, check light and dark mode, 375 px width, reduced motion on (macOS Accessibility → Display), and VoiceOver reading one streamed reply once.

## 8. Out of scope

The navigation rail and route layout, the Progress page and every chart (spec B). A manual theme toggle, web fonts, a component or icon library. Changes to coach prompts. C3 and C4a from `2026-09-28-features-design.md`: C4a's race card will reuse `tsb_zone` when it lands.

## 9. Rollout

One plan, one branch off `main`. No migration, no prompt change, **no eval runs** (nothing model-facing changes). Definition of done: `uv run pytest`, `uv run ruff check . && uv run ruff format --check . && uv run mypy`, `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`, and the manual pass in §7.
