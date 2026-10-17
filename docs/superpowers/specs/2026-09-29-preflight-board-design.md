# tri-web preflight board: a go / easy / rest verdict and a new visual world

**Date:** 2026-09-29
**Status:** Implemented 2026-09-29 (commits `0b593b4` to `a672719`, direct to main; `DESIGN.md` recorded in `9760e03`). Amended 2026-09-29 after the first build review: §8 supersedes the call vocabulary in §2.2 and §2.3 and the order and verdict strip in §3.3 (plan `2026-09-29-readiness-scale.md`).
**Purpose:** Replace tri-web's look with the "Go / No-Go Preflight Board" direction chosen in the Impeccable shape round (seed `f2f09b9e`, pick card, code-led), with Today as the lead surface. Add the server-side verdict that the board leads with. Product truth lives in `PRODUCT.md`. This spec follows `2026-09-28-web-polish-design.md` (merged to `main` @ 4fa5b1d) and replaces that spec's Today cards. Line numbers are `main` @ 4fa5b1d.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Direction | Go / No-Go Preflight Board (Impeccable shape round, 2026-09-29) | The morning question is a call: go, easy or rest. A preflight briefing states the call first, then the conditions behind it in exact figures. |
| Hierarchy | The day first, with the coach docked alongside | Brian's choice. The coach expands for the weekly sit-down. |
| First read | A go / easy / rest verdict | Brian's choice. |
| Verdict source | A deterministic rule over his own numbers (rule A: flag count with hard stops) | Free, instant and traceable. Every reason is an exact figure. |
| Scope | The whole app look, led by Today: shell, Today, Settings, placeholders | Brian's choice. |
| Anti-goals | Hiding the numbers; dashboard noise | Brian's choice. Exactly one element is loud: the verdict. |
| Build path | Code-led. No image generation is available here. | The ambition lives in the direction contract and the finish review. |
| Libraries | None added. No web fonts, no chart or component library. | A local, offline app. Limit markers are CSS. |
| Plans | P1 server (verdict and conditions), P2 web (board) | P2 renders what P1 serves. |

## 2. P1: verdict and condition rows (tri-web server)

### 2.1 Module and constants (`tri_web/verdict.py`, new)

A new pure module keeps `metrics.py` focused on trends. It reuses `metrics.py`'s `ACWR_HIGH`, `ACWR_LOW` and `RAMP_CAUTION`, and imports `ReadinessOut` under `TYPE_CHECKING` only, since `today.py` imports this module. The thresholds still live only in Python.

| Name | Value |
|---|---|
| `SLEEP_CAUTION` | sleep score < 60 |
| `READINESS_CAUTION` | training readiness < 50 |
| `READINESS_STOP` | training readiness < 25 |
| `ACWR_STOP` | ACWR > 1.5 (the caution is the existing `ACWR_HIGH` = 1.3) |
| `ACWR_MIN_CTL` | ACWR is ignored while CTL < 20 |
| `STALE_DAYS` | 1: the readiness row is older than today by at least one day |
| `NO_CALL_DAYS` | 3: the readiness row is more than 3 days old, so there is no call |
| `HARD_IF` | 0.75: a planned session with planned IF ≥ 0.75 is harder than easy |
| `HARD_TSS_PER_H` | 55: when planned IF is null, planned TSS per planned hour ≥ 55 is harder than easy |

### 2.2 Rule

Flags, each with a key, a severity and one plain sentence carrying the exact figures:

| Key | Caution | Hard stop |
|---|---|---|
| `hrv` | `trends.hrv.band == "below"` | with `resting_hr` band `above` on the same day, both become one stop keyed `hrv` |
| `resting_hr` | `trends.resting_hr.band == "above"` | (see `hrv`) |
| `sleep_score` | `sleep_score < 60` | none |
| `training_readiness` | `< 50` | `< 25` |
| `tsb` | none | `tsb_zone == "overreaching"` |
| `acwr` | `acwr_flag == "high"` (> 1.3) | `acwr > 1.5` |
| `ramp` | `ramp_caution` | none |

The ACWR flag is skipped entirely when CTL is null or below `ACWR_MIN_CTL`. The combined HRV/RHR stop replaces the two separate cautions.

Call: `rest` when any hard stop is present or there are three or more cautions; `easy` with one or two cautions; `go` with none. It is `none` when there is no readiness row or the row is more than `NO_CALL_DAYS` old; its single reason is then "no Garmin data, sync first" or "last Garmin data {date}, sync first".

### 2.3 Output

`verdict(readiness: ReadinessOut | None, todays: list[dict], today: date) -> VerdictOut`, pure, in `verdict.py`:

```python
class ReasonOut(BaseModel):
    key: str          # a condition key (§2.4), so the UI can link a reason to its row
    text: str         # e.g. "HRV 51 ms, below your band 56–64"
    severity: Literal["caution", "stop", "info"]

class VerdictOut(BaseModel):
    call: Literal["go", "easy", "rest", "none"]
    reasons: list[ReasonOut]          # stops first, then cautions, in the §2.2 table order
    based_on: date | None
    stale: bool                       # based_on < today
    harder_than_call: bool            # call is easy/rest and a planned, not completed session is harder than easy
    session_done: bool                # today has ≥1 planned workout and all of them are completed
```

`todays` are today's `workouts` rows, which `build_today` already reads (`today.py`, `crepo.list_workouts_between`). They carry `planned_if`, `planned_tss`, `planned_duration_sec` and `completed`.

### 2.4 Condition rows

`conditions(readiness: ReadinessOut | None) -> list[ConditionOut]`, pure, in `verdict.py`. The server builds the rows so the frontend never holds a threshold:

```python
class ConditionOut(BaseModel):
    key: Literal["training_readiness", "hrv", "resting_hr", "sleep_score", "sleep_hours", "tsb", "acwr", "ramp"]
    label: str                 # "Readiness", "HRV", "RHR", "Sleep", "Slept", "Form (TSB)", "ACWR", "Ramp"
    value: float | None
    unit: str                  # "", "ms", "bpm", "h", "/wk"
    baseline: float | None     # trends avg_28d for the five trend rows; None for tsb/acwr/ramp
    band_low: float | None     # trend rows: avg_28d − sd_28d; tsb −30; acwr 0.8; ramp None
    band_high: float | None    # trend rows: avg_28d + sd_28d; tsb 25; acwr 1.3; ramp 8
    status: str                # "within" | "low" | "high" | the TSB zone name | "fast" | "ignored: CTL under 20" | "no baseline" | "no data"
    flagged: bool              # the row raised a caution or a stop in §2.2
```

Rows are in the key order above. A row with a null value keeps its place and reads `no data`. A trend row whose band is null (fewer than `BASELINE_MIN` values) reads `no baseline`.

### 2.5 Wiring

`TodayView` gains `verdict: VerdictOut` (always present) and `conditions: list[ConditionOut]` (empty when readiness is null). `build_today` calls both after `_readiness`. Regenerate `web/openapi.json` and `web/src/api/types.ts`.

## 3. P2: the preflight board (web/)

### 3.1 World and tokens (`web/src/index.css`)

Dark first. The scene is 5 AM, a dark room, a laptop.

| Role | Dark | Light ("daylight board") |
|---|---|---|
| ground | `#0b0f14` | `#f4f5f7` |
| panel | `#111820` | `#ffffff` |
| ink | `#d9dee5` | `#12161c` |
| ink-2 | measured ≥ 4.5:1 on ground and panel | measured ≥ 4.5:1 |
| rule | `#243040` | `#d3d8df` |
| go | `#5fd38d` | a darker green ≥ 4.5:1 |
| easy | `#f2c14e` | a darker amber ≥ 4.5:1 |
| rest | `#ff8f6b` | a darker coral ≥ 4.5:1 |
| hold | `#8fb8ff` | a darker blue ≥ 4.5:1 |
| accent (focus, links) | the hold blue | the hold blue |

Exact light values and ink-2 are chosen at build time and measured with the same contrast script as the web-polish spec. Every pair is recorded in the plan. Existing planning, nutrition and danger roles map onto this set, and the plan lists the mapping. Status colours always come with a word.

Type: the system UI stack with tabular figures everywhere. No web fonts. Three emphasis sizes: the verdict word (large, tracked caps), section values, and everything else. The minimum text size stays at 12px.

### 3.2 Shell

- **Observations line:** date, then phase and week, then each source as `garmin 05:12 Sep 27 · stale`, reusing the web-polish failed and stale words, then two small buttons, Sync and Check-in, which reuse `JobButton` and its stream.
- **Tabs:** Today, Progress, Nutrition, Labs, Settings, as visible links with `aria-current`. They replace the avatar menu. The skip link and route focus stay.

### 3.3 Today

At 1280px and wider there are two regions: the board (left, about two-thirds) and the coach panel (right, full height).

1. **Verdict strip.**
   - Content: the call word (`GO` / `EASY` / `REST` / `NO CALL`) in its status colour; `based on Sun Sep 27` when stale; the reasons as chips; `planned session is harder than today's call` when `harder_than_call`; `session done, recover` when `session_done`.
   - Status: `role="status"`.
2. **HOLD line.** Shown only when `pending` is set: `HOLD · 1 change awaiting your approval`. It is a link that moves focus to the review gate in the coach panel.
3. **Conditions table.**
   - A real `<table>`. Columns: condition, now, 28-day baseline, limit, status.
   - The limit cell is a CSS track with the band shaded and a tick at the value, `aria-hidden`; the status word carries the meaning.
   - Flagged rows set their status word in the easy or rest colour.
4. **Today's plan.** The session and its fuel plan, keeping today's null sentence "No session planned".
5. **Week.** Per-sport rows and the so-far count, as served today, keeping "No plan; ask the coach to build one".

Fuel keeps "No targets yet, ask the coach". Readiness null keeps "No Garmin data yet, sync first", shown as the table's empty state.

**Signature interaction.**
- Each reason chip is a button whose target is its condition row.
- Hovering or focusing a chip highlights that row, and hovering or focusing a row highlights its chip. Activating a chip scrolls to the row and focuses it.
- Rows are focusable (`tabIndex=0`) and point back to the chip with `aria-describedby`.

**Motion.** After a refetch, a row whose `value` changed flashes its background once (about 600 ms). There is no motion under reduced motion.

**Coach panel.** The existing `Chat` (log, composer, gate) moves into the panel unchanged in behaviour.

**Widths.**
- 768–1279px: a "Coach" tab in the tab row toggles the panel over the board; Escape or the tab closes it.
- Under 768px: one column, verdict first, with the coach as the same tab.

### 3.4 Settings and placeholders

Restyled as ruled board sections in the same world. Same content and behaviour.

### 3.5 Components

- **Removed:** `components/today/*` (Strip, Card, SessionCard, ReadinessCard, FuelCard, WeekCard) and `AvatarMenu.tsx`.
- **Added:** `board/VerdictStrip`, `board/HoldLine`, `board/Conditions`, `board/LimitMarker`, `board/Plan` (session and fuel), `board/Week`, `shell/Tabs`, `shell/Observations`.
- **Kept as they are:** `Chat`, `Gate` and `JobButton`.

## 4. Impeccable process (code-led)

- **Before any P2 code:** write the direction contract (THESIS, OWN-WORLD, STORY, FIRST VIEWPORT, FORM, and the FINISH line) into Today's surface brief with `impeccable surface-brief write`. Never copy it into source or the bundle.
- **After the build:**
  - One batched screenshot round: desktop at 1440px and mobile at 390px, in both themes, into `.impeccable/review/`.
  - `impeccable detect --json` over the changed files, once.
  - A fresh `impeccable-finish-reviewer`, acting on its disposition.
  - `impeccable-documenter` writes DESIGN.md and `.impeccable/design.json` from the built world.

## 5. Testing

### 5.1 New tests

**pytest (`test_verdict.py`, new, pure).** The verdict truth table covers:
- each caution alone, which gives easy;
- two cautions (easy) against three (rest);
- each hard stop, which gives rest;
- the combined HRV/RHR stop;
- ACWR at 1.31 (caution) and 1.51 (stop), and ACWR ignored at CTL 19.9 and applied at 20;
- readiness at 49 and 50, and at 24 and 25;
- sleep at 59 and 60;
- the stale edge (a row one day old) and the no-call edge (a row four days old, where three days still calls);
- `harder_than_call` by IF and by TSS per hour, and its absence when the call is go;
- `session_done`.

**pytest, conditions.** Band arithmetic, every status word, the null-value and no-baseline rows.

**pytest, `test_today.py`.** `TodayView` carries `verdict` and `conditions` for a seeded day, and `call == "none"` with no metrics.

**vitest.**
- The strip for each call, and stale and no-call.
- The HOLD line appears only when pending, and moves focus to the gate.
- The conditions table's status words, and its empty state.
- The chip-to-row link: hovering, focusing, activating by keyboard, and highlighting in the reverse direction.
- The tabs, with `aria-current`.
- The coach toggle at a narrow width, including Escape.
- No flash under reduced motion.

### 5.2 Existing tests that change (approving this spec approves these)

- **`web/tests/strip.test.tsx`:** the four-card strip is removed, so its tests become board tests. The null-state sentences stay verbatim, so those assertions carry over: "No session planned", "No Garmin data yet, sync first", "No targets yet, ask the coach", "No plan; ask the coach to build one". The session, fuel and week figures are asserted in their new places.
- **`web/tests/shell.test.tsx`:** the avatar-menu tests are removed with the menu:
  - "the avatar menu holds the five sections…";
  - "the menu closes on Escape, on an outside click…".

  Tab tests replace them. The skip-link, route-focus, header and stale/failed tests stay, adapted to the observations line.
- **`web/tests/styles.test.ts`:** the token assertions change to the new palette. The 12px floor, `motion-safe` and reduced-motion guards stay.
- **`web/tests/fixtures.tsx`:** gains `verdict` and `conditions`.
- **`web/tests/e2e/smoke.spec.ts`:** the stub gains `verdict` and `conditions`.
- **Python tests:** none change.

## 6. Out of scope

- Progress, Nutrition and Labs page content (charts arrive with those pages).
- A coach-written morning call.
- Hosting and multi-athlete support.
- A manual theme toggle.
- Changes to coach prompts.

## 7. Rollout

Branch `feat/preflight-board` off `main`. P1, then P2. No migration, no prompt change, **no eval runs**.

Definition of done:
- `uv run pytest`;
- `uv run ruff check . && uv run ruff format --check . && uv run mypy`;
- `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`;
- the Impeccable finish (§4);
- Brian's look in the browser.

## 8. Amendment: readiness scale, metrics first (2026-09-29, after the first build review)

Brian reviewed the built board and asked for three changes. Where this section and §1–§3 disagree, this section wins. Sections not named here are unchanged.

### 8.1 What Brian said

- The call was read before the metrics. The metrics should come first, then a container for the status.
- The GO / EASY / REST wording should give way to a Garmin-style scale from Poor to the top step. Garmin's own labels are Poor, Low, Moderate, High, Prime, so "Prime" is the top step (Brian wrote "Peaking").
- The level is Garmin's Training Readiness score band, capped by his own flags.

### 8.2 Level rule (supersedes the Call paragraph of §2.2)

`VerdictOut.call` becomes `level: Literal["poor", "low", "moderate", "high", "prime", "none"]`. The flags table, the stale rule, the ACWR guard and the reasons are unchanged. The level is the lower of two caps, ordered poor < low < moderate < high < prime.

| Cap | poor | low | moderate | high | prime |
|---|---|---|---|---|---|
| Garmin band (`training_readiness`) | under 25 | 25–49 | 50–74 | 75–94 | 95 and up |
| Flags | any stop | 3 or more cautions | 2 cautions | 1 caution | none |

- **No Garmin score today:** the Garmin cap is `high`, so a missing reading can never produce `prime`.
- **`none`:** unchanged: no readiness row, or one more than `NO_CALL_DAYS` old.
- **Constants:** the band edges live in `verdict.py` as `GARMIN_BANDS = (25, 50, 75, 95)`.
- **`harder_than_call`:** now true when the level is `poor`, `low` or `moderate` and a planned, not completed session is harder than easy (§2.3 tests unchanged). It no longer fires at `high`, where a single caution used to trigger it.
- **§2.3 model:** rename `call` to `level`; every other field is unchanged.

### 8.3 Layout (supersedes items 1–3 of §3.3 and the first-viewport order)

1. **Conditions table first**, then the readiness container, then the HOLD line, then Today's plan and Week.
2. **Readiness container** (replaces the verdict strip; `role="status"`, `aria-label="Readiness"`):
   - a small "Readiness" label and the level word (`POOR`, `LOW`, `MODERATE`, `HIGH`, `PRIME`, or `NO READING` for `none`) at `text-2xl`, well under the 36px figures;
   - a five-segment scale, Poor to Prime, with the current step lit; the labels are always visible;
   - the reason chips, still linked to their rows above; `based on {day}` when stale; `harder_than_call` and `session_done` lines as before.
3. **Colour** reuses the existing tokens: prime and high `go`, moderate `easy`, low and poor `rest`. The word and the lit segment carry the step; colour never does alone.
4. The "One loud element" anti-goal now means the figures lead: the level is a single quiet container, not the loudest thing on the page.

### 8.4 Conditions rows (built after §3.3 was approved, recorded here)

- Each row has a 4px left rail, a `text-4xl` semibold figure and a small unit, all in the row's state colour: a flagged row its reason's colour, a row inside its band `go`, a row outside its band but not flagged `hold`, and a row with no band word plain. The status word takes the same colour. The web app maps the server's status words; it compares no value against a limit.
- A Figures | Trends switch above the table. Trends replaces the 28-day and limit columns with a 14-day line per row: the band shaded, today's dot, a break at a missing day. `ConditionOut.spark` carries the history for the five trend rows; Form, ACWR and Ramp send `[]` and show "no history".

### 8.5 Tests and rollout

- **Existing tests that change:** `test_verdict.py` and `test_today.py` (`call` to `level`, the new mapping), `verdict.test.tsx`, `board.test.tsx`, `fixtures.tsx` and the e2e stub. All belong to this branch; no test outside the board changes.
- **Rollout:** unchanged: no migration, no prompt change, no eval run.
