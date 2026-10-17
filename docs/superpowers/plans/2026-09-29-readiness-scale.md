# Readiness Scale Implementation Plan

**Status:** Implemented 2026-09-29 (commits `e1c8981` to `1fb159c`, direct to main).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the go / easy / rest call with a Garmin-style Poor to Prime readiness level (Garmin's score band, capped by Brian's own flags), and move the status container below the conditions table so the metrics are read first.

**Architecture:**
- **Task 1, server.** `tri_web/verdict.py` renames `VerdictOut.call` to `level` and computes it as the lower of a Garmin-band cap and a flags cap. Reasons, stale rule, ACWR guard and the condition rows are unchanged.
- **Task 2, web.** Regenerate the types, replace `VerdictStrip` with a quieter `ReadinessStatus` container (level word, five-step scale, reason chips), and reorder `Board` to conditions, status, HOLD line, plan, week.

**Tech Stack:** Python 3.12, FastAPI, pydantic, pytest (Postgres test DB); React 19, Vite, Tailwind v4, vitest + Testing Library, Playwright (stubbed e2e, not runnable here).

**Spec:** `docs/superpowers/specs/2026-09-29-preflight-board-design.md`, §8 (amendment approved 2026-09-29; §8 wins over §2.2, §2.3, §3.3 where they disagree). This plan continues `2026-09-29-preflight-board.md`, whose Tasks 1-9 are built and whose Task 10 (Impeccable finish) is still open and runs after this plan.

## Global Constraints

- **Branch and scope.** Stay on `feat/preflight-board`, one commit per task. No migration, no prompt change, no `tri-* eval` run and no `pytest --live`. Never push.
- **No new dependencies.** No web fonts, no chart or component library.
- **Thresholds live only in Python.** `GARMIN_BANDS` and the flag counts stay in `tri_web/verdict.py`. The web app maps `level` words to colours and compares no value against a limit.
- **Level rule (spec §8.2).** `level` is one of `poor | low | moderate | high | prime | none`, ordered poor < low < moderate < high < prime. It is the lower of:
  - the Garmin cap from `training_readiness`: under 25 poor, 25-49 low, 50-74 moderate, 75-94 high, 95 and up prime. With no score the Garmin cap is `high`;
  - the flags cap: any stop poor, three or more cautions low, two moderate, one high, none prime.
  `none` is unchanged: no readiness row, or one more than `NO_CALL_DAYS` old.
- **`harder_than_call`.** Keeps its name. True when the level is `poor`, `low` or `moderate` and a planned, not completed session is harder than easy. Its on-screen sentence stays "planned session is harder than today's call".
- **Plan ruling (spec is silent): the level explains itself.** When the Garmin cap is strictly lower than the flags cap and no reason already has key `training_readiness`, `verdict()` appends one `info` reason keyed `training_readiness`: `Garmin readiness {score}, {level} band`, or `No Garmin readiness score today, capped at high` when the score is missing. Info reasons render as plain text, never as a button. Without this, a Moderate with no flags would read as an unexplained all-clear.
- **Level words and colours (spec §8.3).** Words: `POOR`, `LOW`, `MODERATE`, `HIGH`, `PRIME`, `NO READING`. Colours reuse the existing tokens: prime and high `go`, moderate `easy`, low and poor `rest`, none `ink-2`. Status colour always comes with the word. Minimum text size is `text-xs`. The level word is `text-2xl`, well under the `text-4xl` figures.
- **Null-state sentences stay verbatim:** "No Garmin data yet, sync first", "No session planned", "No targets yet, ask the coach", "No plan; ask the coach to build one", and the no-call reason "No Garmin data, sync first".
- **Existing tests may change only as spec §8.5 lists:** `test_verdict.py`, `test_today.py`, `verdict.test.tsx`, `board.test.tsx` (one test added), `fixtures.tsx` and the e2e stub. Do not weaken an assertion to hide a failure.
- **Python checks.** Every Python task runs `uv run ruff check . && uv run ruff format --check . && uv run mypy`, checking each exit status.
- **Web checks.** Every web task runs `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build` before committing.
- **Commit trailer.** Each commit message ends with a blank line and `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **Test database.** DB tests run only against the approved test database (postgresql://tri_analyze@localhost:5435/tri_analyze_test). Brian approved it for this repo's test runs.

## Review Focus

1. **No Garmin score today.** A missing score must not read as Prime, and the container must say why it is capped. Pinned in Task 1: `test_missing_garmin_score_caps_at_high_and_says_so`.
2. **A score exactly on a band edge** (24, 25, 49, 50, 74, 75, 94, 95). The step must not be off by one; 25 stays "a caution, not a stop". Pinned in Task 1: `test_garmin_bands_set_the_level`.
3. **A level held down only by Garmin's score, with no flags.** The container must not read as an unexplained all-clear, and the readiness row must point at its explanation. Pinned in Task 2: `a level held down only by Garmin's score explains itself`.
4. **A no-reading day.** `none` must show "NO READING" with no step lit and no chip that goes nowhere. Pinned in Task 2: `the scale lights only the current step` (the `none` case) and `a no-call reason is plain text, not a button that goes nowhere`.
5. **The moved container.** The metrics must come first in reading order, and a chip must still land on its row. Pinned in Task 2: `the metrics come first` in `board.test.tsx`, and `a reason chip and its row light each other, by keyboard too`.

---

### Task 1: The level rule (server)

**Files:**
- Modify: `packages/tri-web/src/tri_web/verdict.py`
- Modify: `packages/tri-web/tests/test_verdict.py` (rewrite everything above the line `KEYS = [`; leave the condition-row tests from `KEYS = [` down unchanged)
- Modify: `packages/tri-web/tests/test_today.py` (two assertions)

**Interfaces:**
- Consumes: `tri_web.today.ReadinessOut` (`training_readiness: int | None`, `date`, and the fields `flags` already reads) and `MetricTrend`.
- Produces:
  - `Level = Literal["poor", "low", "moderate", "high", "prime", "none"]`
  - `GARMIN_BANDS = (25, 50, 75, 95)`
  - `VerdictOut(level: Level, reasons: list[ReasonOut], based_on: date | None, stale: bool, harder_than_call: bool, session_done: bool)`. `call` is gone; every other field is unchanged.
  - `verdict(readiness, todays, today) -> VerdictOut`: same signature. `flags`, `conditions`, `ConditionOut` and `ReasonOut` are unchanged.

- [ ] **Step 1: Write the failing tests.** In `packages/tri-web/tests/test_verdict.py`, replace everything above the line `KEYS = [` with:

```python
"""The readiness level from Garmin's score and the athlete's own numbers."""

from datetime import date, timedelta
from typing import Any

import pytest

from tri_web.metrics import MetricTrend
from tri_web.today import ReadinessOut
from tri_web.verdict import conditions, verdict

TODAY = date(2026, 9, 29)


def trend(now: float, avg: float, sd: float, band: str | None) -> MetricTrend:
    return MetricTrend(
        now=now, avg_7d=avg, avg_28d=avg, sd_28d=sd, band=band, better=None, spark=[]
    )


TRENDS = {
    "hrv": trend(60, 60, 3, "normal"),
    "resting_hr": trend(48, 48, 2, "normal"),
    "sleep_score": trend(80, 78, 4, "normal"),
    "sleep_hours": trend(7.5, 7.3, 0.4, "normal"),
    "training_readiness": trend(70, 68, 6, "normal"),
}


def rd(**over: Any) -> ReadinessOut:
    base: dict[str, Any] = dict(
        date=TODAY,
        is_today=True,
        sleep_score=80,
        sleep_hours=7.5,
        hrv=60,
        resting_hr=48,
        body_battery=80,
        training_readiness=70,
        ctl=40.0,
        atl=42.0,
        tsb=-2.0,
        trends=dict(TRENDS),
        tsb_zone="neutral",
        ramp_7d=2.0,
        ramp_caution=False,
        acwr=1.05,
        acwr_flag=None,
    )
    base.update(over)
    return ReadinessOut(**base)


def with_trend(key: str, t: MetricTrend, **over: Any) -> ReadinessOut:
    return rd(trends={**TRENDS, key: t}, **over)


HRV_LOW = trend(52, 60, 3, "below")
RHR_HIGH = trend(55, 48, 2, "above")

# Garmin's top band, so only the flags can cap the level. Never pass training_readiness as well.
PRIME: dict[str, Any] = dict(training_readiness=96)


def level(r: ReadinessOut | None, todays: list[dict[str, Any]] | None = None) -> str:
    return verdict(r, todays or [], TODAY).level


def test_no_readiness_is_no_reading():
    v = verdict(None, [], TODAY)
    assert v.level == "none" and v.based_on is None and not v.stale
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin data, sync first", "info")
    ]


def test_clean_day_with_a_prime_score_is_prime():
    v = verdict(rd(**PRIME), [], TODAY)
    assert v.level == "prime" and v.reasons == [] and v.based_on == TODAY and not v.stale


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (24, "poor"),
        (25, "low"),
        (49, "low"),
        (50, "moderate"),
        (74, "moderate"),
        (75, "high"),
        (94, "high"),
        (95, "prime"),
    ],
)
def test_garmin_bands_set_the_level(score, expected):
    assert level(rd(training_readiness=score)) == expected


def test_missing_garmin_score_caps_at_high_and_says_so():
    v = verdict(rd(training_readiness=None), [], TODAY)
    assert v.level == "high"
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin readiness score today, capped at high", "info")
    ]


def test_garmin_holds_the_level_down_and_gives_the_reason():
    v = verdict(rd(training_readiness=62), [], TODAY)
    assert v.level == "moderate"
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "Garmin readiness 62, moderate band", "info")
    ]


def test_no_extra_reason_when_a_readiness_flag_already_explains():
    v = verdict(rd(training_readiness=40), [], TODAY)
    assert v.level == "low"
    assert [(r.key, r.severity) for r in v.reasons] == [("training_readiness", "caution")]


def test_no_extra_reason_when_the_flags_are_the_cap():
    v = verdict(rd(sleep_score=59, **PRIME), [], TODAY)
    assert v.level == "high"
    assert [(r.key, r.severity) for r in v.reasons] == [("sleep_score", "caution")]


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (with_trend("hrv", HRV_LOW, hrv=52, **PRIME), "hrv"),
        (with_trend("resting_hr", RHR_HIGH, resting_hr=55, **PRIME), "resting_hr"),
        (rd(sleep_score=59, **PRIME), "sleep_score"),
        (rd(acwr=1.31, acwr_flag="high", **PRIME), "acwr"),
        (rd(ramp_7d=9.0, ramp_caution=True, **PRIME), "ramp"),
    ],
)
def test_each_caution_alone_caps_at_high(r, key):
    v = verdict(r, [], TODAY)
    assert v.level == "high"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "caution")]


def test_a_readiness_caution_is_low_because_the_score_is_under_50():
    v = verdict(rd(training_readiness=49), [], TODAY)
    assert v.level == "low"
    assert [(x.key, x.severity) for x in v.reasons] == [("training_readiness", "caution")]


def test_threshold_edges_do_not_flag():
    assert level(rd(sleep_score=60, **PRIME)) == "prime"
    assert level(rd(acwr=1.3, **PRIME)) == "prime"
    v = verdict(rd(training_readiness=50), [], TODAY)
    assert v.level == "moderate"
    assert [r.severity for r in v.reasons] == ["info"]  # the Garmin band only, no flag


def test_two_cautions_moderate_three_low():
    two = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, **PRIME)
    assert level(two) == "moderate"
    three = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, acwr=1.31, acwr_flag="high", **PRIME)
    assert level(three) == "low"


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (rd(training_readiness=24), "training_readiness"),
        (rd(tsb=-31.0, tsb_zone="overreaching", **PRIME), "tsb"),
        (rd(acwr=1.51, acwr_flag="high", **PRIME), "acwr"),
    ],
)
def test_each_stop_is_poor(r, key):
    v = verdict(r, [], TODAY)
    assert v.level == "poor"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "stop")]


def test_readiness_25_is_a_caution_not_a_stop():
    v = verdict(rd(training_readiness=25), [], TODAY)
    assert v.level == "low" and v.reasons[0].severity == "caution"


def test_hrv_low_and_rhr_high_together_are_one_stop():
    r = rd(trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55, **PRIME)
    v = verdict(r, [], TODAY)
    assert v.level == "poor"
    assert [(x.key, x.severity) for x in v.reasons] == [("hrv", "stop")]
    assert "52" in v.reasons[0].text and "55" in v.reasons[0].text


def test_stops_come_before_cautions():
    v = verdict(rd(sleep_score=59, training_readiness=24), [], TODAY)
    assert [x.severity for x in v.reasons] == ["stop", "caution"]


def test_acwr_guard():
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=19.9, **PRIME)) == "prime"
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=20.0, **PRIME)) == "poor"
    assert level(rd(acwr=1.6, acwr_flag="high", ctl=None, **PRIME)) == "prime"


def test_stale_edges():
    one = verdict(rd(date=TODAY - timedelta(days=1), is_today=False, **PRIME), [], TODAY)
    assert one.level == "prime" and one.stale and one.based_on == TODAY - timedelta(days=1)
    three = verdict(rd(date=TODAY - timedelta(days=3), is_today=False, **PRIME), [], TODAY)
    assert three.level == "prime" and three.stale
    four = verdict(rd(date=TODAY - timedelta(days=4), is_today=False, **PRIME), [], TODAY)
    assert four.level == "none" and four.based_on == TODAY - timedelta(days=4)
    assert four.reasons[0].text == "Last Garmin data Fri Sep 25, sync first"


def w(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        completed=False, planned_if=None, planned_tss=None, planned_duration_sec=3600
    )
    base.update(over)
    return base


def test_harder_than_call():
    moderate = rd(sleep_score=59, ramp_7d=9.0, ramp_caution=True, **PRIME)
    assert verdict(moderate, [w(planned_if=0.8)], TODAY).harder_than_call
    assert not verdict(moderate, [w(planned_if=0.7)], TODAY).harder_than_call
    assert verdict(moderate, [w(planned_tss=60)], TODAY).harder_than_call  # 60 TSS/h, IF unknown
    assert not verdict(moderate, [w(planned_tss=50)], TODAY).harder_than_call
    assert not verdict(moderate, [w(planned_if=0.8, completed=True)], TODAY).harder_than_call
    assert not verdict(rd(**PRIME), [w(planned_if=0.9)], TODAY).harder_than_call  # prime
    high = rd(sleep_score=59, **PRIME)  # one caution no longer warns
    assert not verdict(high, [w(planned_if=0.9)], TODAY).harder_than_call


def test_session_done():
    assert verdict(rd(), [w(completed=True), w(completed=True)], TODAY).session_done
    assert not verdict(rd(), [w(completed=True), w()], TODAY).session_done
    assert not verdict(rd(), [], TODAY).session_done


```

- [ ] **Step 2: Update the two assertions in `packages/tri-web/tests/test_today.py`.**
  - In `test_today_carries_the_verdict_and_conditions`, change `assert view.verdict.call == "rest"` to `assert view.verdict.level == "poor"`.
  - In `test_no_metrics_is_no_call`, change `assert view.verdict.call == "none" and view.conditions == []` to `assert view.verdict.level == "none" and view.conditions == []`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_verdict.py packages/tri-web/tests/test_today.py -q`
Expected: FAIL. The level tests and the two `test_today` tests raise `AttributeError: 'VerdictOut' object has no attribute 'level'`; the condition-row tests from `KEYS = [` down still pass.

- [ ] **Step 4: Implement in `packages/tri-web/src/tri_web/verdict.py`.**
  - Replace the module docstring with:

```python
"""The morning readiness level, poor to prime, from Garmin's score and the athlete's own numbers
against his own baseline, and the condition rows the board shows beside it. Pure: build_today
hands it the readiness view and today's workouts. Every threshold lives here or in metrics.py,
never in the web app."""
```

  - Replace the line `Call = Literal["go", "easy", "rest", "none"]` with:

```python
Level = Literal["poor", "low", "moderate", "high", "prime", "none"]
_STEPS: tuple[Level, ...] = ("poor", "low", "moderate", "high", "prime")
# A Training Readiness score at or over each edge climbs one step: 25 low, 50 moderate, 75 high, 95 prime.
GARMIN_BANDS = (25, 50, 75, 95)
```

  - In `VerdictOut`, change `call: Call` to `level: Level`.
  - After the `_hard` function, add:

```python
def _garmin_cap(score: int | None) -> Level:
    """Garmin's own band. With no score the cap is high, so a missing reading is never prime."""
    if score is None:
        return "high"
    return _STEPS[sum(score >= edge for edge in GARMIN_BANDS)]


def _flag_cap(found: list[ReasonOut]) -> Level:
    """Any stop is poor; otherwise three or more cautions low, two moderate, one high, none prime."""
    if any(f.severity == "stop" for f in found):
        return "poor"
    return _STEPS[max(1, 4 - len(found))]
```

  - Replace the whole `verdict()` function with:

```python
def verdict(r: ReadinessOut | None, todays: list[dict[str, Any]], today: date) -> VerdictOut:
    done = bool(todays) and all(bool(w["completed"]) for w in todays)
    if r is None:
        reason = ReasonOut(
            key="training_readiness", text="No Garmin data, sync first", severity="info"
        )
        return VerdictOut(
            level="none",
            reasons=[reason],
            based_on=None,
            stale=False,
            harder_than_call=False,
            session_done=done,
        )
    age = (today - r.date).days
    if age > NO_CALL_DAYS:
        text = f"Last Garmin data {r.date:%a %b} {r.date.day}, sync first"
        reason = ReasonOut(key="training_readiness", text=text, severity="info")
        return VerdictOut(
            level="none",
            reasons=[reason],
            based_on=r.date,
            stale=True,
            harder_than_call=False,
            session_done=done,
        )
    found = flags(r)
    score = r.training_readiness
    garmin, capped = _garmin_cap(score), _flag_cap(found)
    lvl: Level = min(garmin, capped, key=_STEPS.index)
    reasons = list(found)
    if _STEPS.index(garmin) < _STEPS.index(capped) and not any(
        f.key == "training_readiness" for f in found
    ):
        text = (
            f"Garmin readiness {score}, {garmin} band"
            if score is not None
            else f"No Garmin readiness score today, capped at {garmin}"
        )
        reasons.append(ReasonOut(key="training_readiness", text=text, severity="info"))
    harder = lvl in ("poor", "low", "moderate") and any(
        not w["completed"] and _hard(w) for w in todays
    )
    return VerdictOut(
        level=lvl,
        reasons=reasons,
        based_on=r.date,
        stale=age >= STALE_DAYS,
        harder_than_call=harder,
        session_done=done,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web -q`
Expected: all pass (the DB tests use the approved test database).

- [ ] **Step 6: Format, lint, type-check**

Run: `uv run ruff format packages/tri-web && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean. Check the exit status of mypy directly, not through a pipe.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-web/src/tri_web/verdict.py packages/tri-web/tests/test_verdict.py packages/tri-web/tests/test_today.py
git commit -m "feat(web): readiness level from Garmin's band, capped by the athlete's flags

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

This task does not regenerate `web/openapi.json` or `web/src/api/types.ts`; Task 2 does, so the web app keeps compiling until then.

---

### Task 2: Metrics first, readiness container below (web)

**Files:**
- Modify (regenerated): `web/openapi.json`, `web/src/api/types.ts`
- Rename and rewrite: `web/src/components/board/VerdictStrip.tsx` to `web/src/components/board/ReadinessStatus.tsx`
- Modify: `web/src/components/board/Board.tsx`
- Modify: `web/tests/fixtures.tsx`, `web/tests/e2e/smoke.spec.ts`
- Rewrite: `web/tests/verdict.test.tsx`
- Modify: `web/tests/board.test.tsx` (one test added)

**Interfaces:**
- Consumes: `VerdictOut` from Task 1 as regenerated (`level` in place of `call`); `Conditions`, `HoldLine`, `Plan`, `Week` unchanged.
- Produces: `ReadinessStatus({ verdict: VerdictOut; active: string | null; onActive: (k: string | null) => void })`. An `<section aria-label="Readiness">` containing a `role="status"` line (label, level word, stale and done notes), an `<ol aria-label="Readiness scale">` of five `<li>` with `aria-current="true"` on the current one, the all-clear sentence, the reasons list, and the harder-than line. Info reasons render as `<li id="reason-{key}">` plain text; caution and stop reasons render as buttons with `id="reason-{key}"` exactly as `VerdictStrip` did.

- [ ] **Step 1: Regenerate the types**

Run: `npm --prefix web run types`
Expected: `web/src/api/types.ts` now has `level` on `VerdictOut` and no `call`. Check: `rg -n '"poor" \| "low"' web/src/api/types.ts` matches.

- [ ] **Step 2: Update the fixtures and the e2e stub.**
  - `web/tests/fixtures.tsx`: in `todayEmpty()` change `verdict: { call: "none",` to `verdict: { level: "none",`. In `todayFull()` change `verdict: { call: "go",` to `verdict: { level: "high",` (the fixture's Garmin readiness is 77).
  - `web/tests/e2e/smoke.spec.ts`: in the stubbed `today` object change `verdict: { call: "none",` to `verdict: { level: "none",`. In the first test replace `await expect(page.getByRole("region", { name: "Today's call" })).toBeVisible();` with `await expect(page.getByRole("region", { name: "Readiness" })).toBeVisible();` and `await expect(page.getByText("NO CALL")).toBeVisible();` with `await expect(page.getByText("NO READING")).toBeVisible();`. In the phone test make the same region replacement.

- [ ] **Step 3: Write the failing tests.** Replace `web/tests/verdict.test.tsx` with:

```tsx
import { useState } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReadinessStatus from "../src/components/board/ReadinessStatus";
import Conditions from "../src/components/board/Conditions";
import type { ConditionOut, VerdictOut } from "../src/api/queries";
import { todayFull } from "./fixtures";

const base: VerdictOut = {
  level: "moderate",
  reasons: [{ key: "acwr", text: "ACWR 1.45, over 1.3", severity: "caution" }],
  based_on: "2026-09-16", stale: false, harder_than_call: true, session_done: false,
};

// The page's order: the metrics first, then the readiness container.
function Board({ verdict = base, rows = todayFull().conditions }: { verdict?: VerdictOut; rows?: ConditionOut[] }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <>
      <Conditions readiness={todayFull().readiness} rows={rows} reasons={verdict.reasons} active={active} onActive={setActive} />
      <ReadinessStatus verdict={verdict} active={active} onActive={setActive} />
    </>
  );
}

test.each([
  ["prime", "PRIME", "text-go"],
  ["high", "HIGH", "text-go"],
  ["moderate", "MODERATE", "text-easy"],
  ["low", "LOW", "text-rest"],
  ["poor", "POOR", "text-rest"],
  ["none", "NO READING", "text-ink-2"],
] as const)("the %s level reads %s in its colour", (level, word, tone) => {
  render(<Board verdict={{ ...base, level, reasons: [] }} />);
  expect(screen.getByText(word)).toHaveClass(tone);
  expect(screen.getByText(word)).toHaveClass("text-2xl");
});

test("the scale lights only the current step and always shows every label", () => {
  const { unmount } = render(<Board verdict={{ ...base, level: "moderate" }} />);
  const scale = screen.getByRole("list", { name: "Readiness scale" });
  const steps = within(scale).getAllByRole("listitem");
  expect(steps.map((li) => li.textContent)).toEqual(["Poor", "Low", "Moderate", "High", "Prime"]);
  expect(steps.filter((li) => li.getAttribute("aria-current") === "true")).toHaveLength(1);
  const current = within(scale).getByText("Moderate").closest("li")!;
  expect(current).toHaveAttribute("aria-current", "true");
  expect(current.querySelector("[data-bar]")).toHaveClass("bg-easy");
  expect(within(scale).getByText("High").closest("li")!.querySelector("[data-bar]")).toHaveClass("bg-line");
  unmount();
  render(<Board verdict={{ ...base, level: "none", reasons: [] }} />);
  const none = within(screen.getByRole("list", { name: "Readiness scale" })).getAllByRole("listitem");
  expect(none.filter((li) => li.getAttribute("aria-current") === "true")).toHaveLength(0);
});

test("an all-clear says so in words", () => {
  render(<Board verdict={{ ...base, level: "prime", reasons: [], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument();
});

test("a level held down only by Garmin's score explains itself", () => {
  const info = { key: "training_readiness", text: "Garmin readiness 62, moderate band", severity: "info" } as const;
  render(<Board verdict={{ ...base, level: "moderate", reasons: [info], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument(); // no flags
  expect(screen.getByText("Garmin readiness 62, moderate band")).toBeInTheDocument();
  expect(document.getElementById("reason-training_readiness")).not.toBeNull();
  expect(document.getElementById("cond-training_readiness")).toHaveAttribute("aria-describedby", "reason-training_readiness");
});

test("the container says when the data is old, when the plan is harder, and when the session is done", () => {
  render(<Board verdict={{ ...base, stale: true, based_on: "2026-09-14", session_done: true }} />);
  expect(screen.getByText(/based on Mon, Sep 14/)).toBeInTheDocument();
  expect(screen.getByText("planned session is harder than today's call")).toBeInTheDocument();
  expect(screen.getByText("session done, recover")).toBeInTheDocument();
});

test("the conditions table shows each row's figures and status word", () => {
  render(<Board />);
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  expect(document.getElementById("cond-hrv")).toHaveTextContent("62 ms");
  expect(screen.getByText("81")).toBeInTheDocument();
  expect(document.getElementById("cond-sleep_hours")).toHaveTextContent("7.5 h");
  expect(screen.getByText("-4.9")).toBeInTheDocument();
  expect(screen.getByText("1.11")).toBeInTheDocument();
  expect(document.getElementById("cond-ramp")).toHaveTextContent("+3.5/wk");
  expect(screen.getByText("neutral")).toBeInTheDocument();
  expect(screen.getAllByText("within").length).toBeGreaterThan(0);
});

test("a flagged row's status word takes its reason's colour", () => {
  const rows = todayFull().conditions.map((c) => (c.key === "acwr" ? { ...c, value: 1.45, status: "high", flagged: true } : c));
  render(<Board rows={rows} />);
  const row = document.getElementById("cond-acwr")!;
  expect(row).toHaveTextContent("high");
  expect(row.querySelector("[data-status]")).toHaveClass("text-easy");
});

test("the table says 'No Garmin data yet, sync first' when there are no rows", () => {
  render(<Conditions readiness={null} rows={[]} reasons={[]} active={null} onActive={() => {}} />);
  expect(screen.getByText("No Garmin data yet, sync first")).toBeInTheDocument();
});

test("a reason chip and its row light each other, by keyboard too", async () => {
  const user = userEvent.setup();
  render(<Board />);
  const chip = screen.getByRole("button", { name: "ACWR 1.45, over 1.3" });
  const row = document.getElementById("cond-acwr")!;
  act(() => chip.focus()); // the chip now follows the table in tab order
  expect(chip).toHaveFocus();
  expect(row).toHaveAttribute("data-active", "true");
  await user.keyboard("{Enter}");
  expect(row).toHaveFocus();
  expect(chip).toHaveAttribute("data-active", "true");
  expect(row).toHaveAttribute("aria-describedby", "reason-acwr");
  fireEvent.mouseLeave(row);
  fireEvent.blur(row);
  expect(row).toHaveAttribute("data-active", "false");
});

test("rows flash only when a value changes after the first render", () => {
  const rows = todayFull().conditions;
  const { rerender } = render(<Conditions readiness={null} rows={rows} reasons={[]} active={null} onActive={() => {}} />);
  expect(document.querySelectorAll(".board-flash")).toHaveLength(0);
  const next = rows.map((c) => (c.key === "hrv" ? { ...c, value: 64 } : c));
  rerender(<Conditions readiness={null} rows={next} reasons={[]} active={null} onActive={() => {}} />);
  const flashing = Array.from(document.querySelectorAll(".board-flash")).map((el) => el.closest("tr")!.id);
  expect(flashing).toEqual(["cond-hrv"]);
});

test("rows from an earlier day say which day", () => {
  const t = todayFull();
  render(<Conditions readiness={{ ...t.readiness!, is_today: false, date: "2026-09-14" }} rows={t.conditions} reasons={[]} active={null} onActive={() => {}} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
});

test("a no-call reason is plain text, not a button that goes nowhere", () => {
  const none: VerdictOut = {
    level: "none",
    reasons: [{ key: "training_readiness", text: "No Garmin data, sync first", severity: "info" }],
    based_on: null, stale: false, harder_than_call: false, session_done: false,
  };
  render(<ReadinessStatus verdict={none} active={null} onActive={() => {}} />);
  expect(screen.getByText("No Garmin data, sync first")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText("All conditions within your limits")).not.toBeInTheDocument();
});

test("each row wears its state: a rail and a large figure in the same colour, the unit small", () => {
  const rows = todayFull().conditions.map((c) => (c.key === "acwr" ? { ...c, value: 1.45, status: "high", flagged: true } : c));
  render(<Board rows={rows} />);
  const fig = (key: string) => document.querySelector(`#cond-${key} [data-figure]`)!;
  const rail = (key: string) => document.querySelector(`#cond-${key} th[scope="row"]`)!;
  expect(fig("hrv")).toHaveClass("text-4xl", "font-semibold");
  expect(fig("hrv").textContent).toBe("62"); // the unit is its own smaller element
  expect(document.querySelector("#cond-hrv [data-unit]")).toHaveClass("text-sm");
  // inside your band: go. above the band but not flagged: hold. flagged: its reason's colour. no band word: plain.
  expect(fig("sleep_score")).toHaveClass("text-go");
  expect(rail("sleep_score")).toHaveClass("border-go");
  expect(fig("hrv")).toHaveClass("text-hold");
  expect(rail("hrv")).toHaveClass("border-hold");
  expect(fig("acwr")).toHaveClass("text-easy");
  expect(rail("acwr")).toHaveClass("border-easy");
  expect(fig("tsb")).not.toHaveClass("text-go", "text-hold", "text-easy", "text-rest");
  expect(rail("tsb")).toHaveClass("border-line");
});

test("Figures is the default view, and Trends swaps the columns for a line per row", async () => {
  const user = userEvent.setup();
  render(<Board />);
  const figures = screen.getByRole("button", { name: "Figures" });
  const trends = screen.getByRole("button", { name: "Trends" });
  expect(figures).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("columnheader", { name: "28-day" })).toBeInTheDocument();
  expect(document.querySelectorAll("svg[data-trend]")).toHaveLength(0);
  await user.click(trends);
  expect(trends).toHaveAttribute("aria-pressed", "true");
  expect(figures).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByRole("columnheader", { name: "28-day" })).not.toBeInTheDocument();
  expect(document.querySelectorAll("svg[data-trend]")).toHaveLength(5); // the five rows with history
  expect(screen.getAllByText("no history")).toHaveLength(3); // Form, ACWR, Ramp
  expect(document.getElementById("cond-hrv")).toHaveTextContent("62 ms"); // the figure and the status word stay
  expect(document.getElementById("cond-hrv")).toHaveTextContent("high");
});

test("a trend line breaks at a missing day and marks today's value", async () => {
  const user = userEvent.setup();
  render(<Board />);
  await user.click(screen.getByRole("button", { name: "Trends" }));
  const svg = document.querySelector("#cond-hrv svg[data-trend]")!;
  expect(svg.querySelectorAll("polyline")).toHaveLength(2); // one gap, so two runs
  expect(svg.querySelectorAll("circle")).toHaveLength(1);
  expect(svg.querySelector("rect[data-band]")).not.toBeNull();
  expect(svg).toHaveAttribute("aria-hidden", "true");
});

test("chips still find their row in the Trends view", async () => {
  const user = userEvent.setup();
  render(<Board />);
  await user.click(screen.getByRole("button", { name: "Trends" }));
  await user.click(screen.getByRole("button", { name: "ACWR 1.45, over 1.3" }));
  expect(document.getElementById("cond-acwr")).toHaveFocus();
});
```

Then append to `web/tests/board.test.tsx` (it already imports `screen`, `Board`, `paused`, `renderWith`, `todayFull`):

```tsx
test("the metrics come first: conditions, then readiness, then the HOLD line, then the plan", () => {
  renderWith(<Board today={todayFull()} review={{ narration: "n", proposals: [paused().proposals[0]] }} onHold={() => {}} />);
  const order = [
    screen.getByRole("heading", { name: "Conditions" }),
    screen.getByRole("region", { name: "Readiness" }),
    screen.getByRole("button", { name: /HOLD/ }),
    screen.getByRole("heading", { name: "Today's plan" }),
  ];
  for (let i = 1; i < order.length; i++) {
    expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
});
```

- [ ] **Step 4: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/verdict.test.tsx tests/board.test.tsx`
Expected: FAIL. `verdict.test.tsx` cannot resolve `../src/components/board/ReadinessStatus`, and the new `board.test.tsx` order test fails because `Board` still renders the verdict strip first.

- [ ] **Step 5: Create `ReadinessStatus.tsx`.** Run `git mv web/src/components/board/VerdictStrip.tsx web/src/components/board/ReadinessStatus.tsx`, then replace its contents with:

```tsx
import type { ReasonOut, VerdictOut } from "../../api/queries";
import { day } from "../../lib/format";

const STEPS = [
  ["poor", "Poor"],
  ["low", "Low"],
  ["moderate", "Moderate"],
  ["high", "High"],
  ["prime", "Prime"],
] as const;
const WORD = { poor: "POOR", low: "LOW", moderate: "MODERATE", high: "HIGH", prime: "PRIME", none: "NO READING" } as const;
// The word and the lit step carry the level; colour only adds to them.
const TONE = {
  poor: { text: "text-rest", bar: "bg-rest" },
  low: { text: "text-rest", bar: "bg-rest" },
  moderate: { text: "text-easy", bar: "bg-easy" },
  high: { text: "text-go", bar: "bg-go" },
  prime: { text: "text-go", bar: "bg-go" },
  none: { text: "text-ink-2", bar: "bg-line" },
} as const;
const CHIP = { stop: "border-rest/70 text-rest", caution: "border-easy/70 text-easy", info: "border-line text-ink-2" } as const;

type Props = { verdict: VerdictOut; active: string | null; onActive: (key: string | null) => void };

function Chip({ r, active, onActive }: { r: ReasonOut; active: boolean; onActive: Props["onActive"] }) {
  if (r.severity === "info") {
    // Nothing to trace: an info reason explains the level itself, so it is text, not a button.
    return (
      <li id={`reason-${r.key}`} className={`inline-flex min-h-7 items-center rounded-full border px-3 text-sm ${CHIP.info}`}>
        {r.text}
      </li>
    );
  }
  const toRow = () => {
    const row = document.getElementById(`cond-${r.key}`);
    row?.scrollIntoView?.({ block: "nearest" });
    row?.focus();
  };
  return (
    <li>
      <button
        type="button"
        id={`reason-${r.key}`}
        data-active={active}
        onClick={toRow}
        onMouseEnter={() => onActive(r.key)}
        onMouseLeave={() => onActive(null)}
        onFocus={() => onActive(r.key)}
        onBlur={() => onActive(null)}
        className={`inline-flex min-h-7 items-center rounded-full border px-3 text-sm tabular-nums ${CHIP[r.severity]} ${active ? "bg-hold/10" : ""}`}
      >
        {r.text}
      </button>
    </li>
  );
}

export default function ReadinessStatus({ verdict: v, active, onActive }: Props) {
  const tone = TONE[v.level];
  const flagged = v.reasons.some((r) => r.severity !== "info");
  return (
    <section aria-label="Readiness" className="mx-6 my-5 rounded-lg border border-line bg-surface-2 px-5 py-4">
      <div role="status" className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-xs font-medium tracking-wider text-ink-2 uppercase">Readiness</span>
        <span className={`text-2xl leading-none font-semibold tracking-[0.12em] ${tone.text}`}>{WORD[v.level]}</span>
        {v.stale && v.based_on && <span className="text-sm text-ink-2">based on {day(v.based_on)}</span>}
        {v.session_done && <span className="text-sm text-ink-2">session done, recover</span>}
      </div>
      <ol aria-label="Readiness scale" className="mt-3 grid max-w-md grid-cols-5 gap-1.5">
        {STEPS.map(([key, label]) => {
          const current = v.level === key;
          return (
            <li key={key} aria-current={current ? "true" : undefined} className="text-xs">
              <div data-bar className={`h-1.5 rounded-full ${current ? tone.bar : "bg-line"}`} />
              <span className={`mt-1 block ${current ? "font-semibold text-ink" : "text-ink-2"}`}>{label}</span>
            </li>
          );
        })}
      </ol>
      {v.level !== "none" && !flagged && <p className="mt-3 text-sm text-ink-2">All conditions within your limits</p>}
      {v.reasons.length > 0 && (
        <ul aria-label="Reasons" className="mt-3 flex flex-wrap gap-2">
          {v.reasons.map((r) => (
            <Chip key={r.key} r={r} active={active === r.key} onActive={onActive} />
          ))}
        </ul>
      )}
      {v.harder_than_call && <p className="mt-3 text-sm text-easy">planned session is harder than today's call</p>}
    </section>
  );
}
```

- [ ] **Step 6: Reorder `Board.tsx`.** Replace `import VerdictStrip from "./VerdictStrip";` with `import ReadinessStatus from "./ReadinessStatus";` and replace the returned `<div>` body so it reads:

```tsx
    <div className="mx-auto w-full max-w-5xl pb-10">
      <Conditions readiness={today.readiness} rows={today.conditions} reasons={today.verdict.reasons} active={active} onActive={setActive} />
      <ReadinessStatus verdict={today.verdict} active={active} onActive={setActive} />
      {review && <HoldLine count={review.proposals.length} onGo={onHold} />}
      <Plan session={today.session} fuel={today.fuel} />
      <Week week={today.week} />
    </div>
```

- [ ] **Step 7: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass. `rg -n "VerdictStrip|call: \"|NO CALL|Today's call" web/src web/tests` finds nothing except the `harder_than_call` field and its sentence "planned session is harder than today's call".

- [ ] **Step 8: Full checks**

Run, checking each exit status:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Expected: all green (the 6 live tests stay skipped). Playwright can't run here; Brian runs `npm --prefix web run test:e2e`.

- [ ] **Step 9: Commit**

```bash
git add -A web/src web/tests web/openapi.json
git commit -m "feat(web): metrics first, readiness level and scale in a quiet container below

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Then Task 10 of `2026-09-29-preflight-board.md` (Impeccable finish) runs as before, with these additions for `DESIGN.md`: the level word is `text-2xl`, figures are `text-4xl` with a `text-sm` unit, and the readiness scale is five labelled steps.
