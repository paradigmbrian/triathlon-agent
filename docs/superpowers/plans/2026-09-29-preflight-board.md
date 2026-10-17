# Preflight Board Implementation Plan

**Status:** Implemented 2026-09-29 (commits `0b593b4` to `a672719`, direct to main).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lead Today with a server-computed go / easy / rest verdict and restyle tri-web as a dark-first preflight board: verdict strip, conditions table and a docked coach panel.

**Architecture:**
- **P1 (Tasks 1–3), server.** A new pure module, `tri_web/verdict.py`, computes the verdict and the condition rows from the existing `ReadinessOut` and today's workouts. `build_today` serves them on `TodayView`, and the TypeScript types are regenerated.
- **P2 (Tasks 4–9), web.** New tokens under the existing token names, a shell with visible tabs, and new `components/board/*` components that replace `components/today/*` and the avatar menu. Today becomes the board plus a coach panel.
- **Task 10.** The Impeccable code-led finish.

**Tech Stack:** Python 3.12, FastAPI, pydantic, pytest (Postgres test DB); React 19, Vite, Tailwind v4, TanStack Query, react-router, vitest + Testing Library, Playwright (stubbed e2e).

**Spec:** `docs/superpowers/specs/2026-09-29-preflight-board-design.md` (approved 2026-09-29). Product truth: `PRODUCT.md`.

## Global Constraints

- **Branch and scope.** Branch `feat/preflight-board` off `main`, one commit per task. No migration, no prompt change, no `tri-* eval` run and no `pytest --live`.
- **No new dependencies.** No web fonts, no chart or component library.
- **Thresholds live only in Python.** Keep them in `tri_web/verdict.py` and `tri_web/metrics.py`. The frontend never compares a value against a limit.
- **Verdict constants:** `SLEEP_CAUTION = 60`, `READINESS_CAUTION = 50`, `READINESS_STOP = 25`, `ACWR_STOP = 1.5`, `ACWR_MIN_CTL = 20`, `STALE_DAYS = 1`, `NO_CALL_DAYS = 3`, `HARD_IF = 0.75`, `HARD_TSS_PER_H = 55`. It reuses `ACWR_HIGH = 1.3`, `ACWR_LOW = 0.8` and `RAMP_CAUTION = 8` from `metrics.py`.
- **Call rule.** Any stop, or three or more cautions, gives `rest`. One or two cautions give `easy`, none gives `go`. There is no row, or the row is more than 3 days old, gives `none`.
- **Tokens: dark first.** The `:root` values are dark, and `@media (prefers-color-scheme: light)` overrides them.
  - Dark: `--surface #0b0f14`, `--surface-2 #111820`, `--ink #d9dee5`, `--ink-2 #95a0ae`, `--line #2e3d52`, `--go #5fd38d`, `--easy #f2c14e`, `--rest #ff8f6b`, `--hold #8fb8ff`.
  - Light: `--surface #f4f5f7`, `--surface-2 #ffffff`, `--ink #12161c`, `--ink-2 #555e6b`, `--line #d3d8df`, `--go #19663a`, `--easy #7d5400`, `--rest #a13a18`, `--hold #2f5fb3`.
  - All were measured at ≥ 4.5:1 on both surfaces and on a 15% tint of themselves.
- **Status colour always comes with a word.** Minimum text size is `text-xs`, and there is no `text-[10px]` or `text-[11px]`.
- **Three emphasis sizes:** the verdict word `text-5xl`, values `text-base font-medium`, and everything else `text-sm` or `text-xs`.
- **Null-state sentences stay verbatim:** "No session planned", "No Garmin data yet, sync first", "No targets yet, ask the coach", "No plan; ask the coach to build one".
- **Existing tests may change only as spec §5.2 lists.** This plan's rulings on it:
  - `strip.test.tsx` is renamed to `board.test.tsx` and migrated.
  - The two avatar-menu tests in `shell.test.tsx` are removed, and its skip-link test clicks a tab instead of the menu.
  - `styles.test.ts` asserts the new tokens.
  - `fixtures.tsx` and the e2e stub gain fields. The e2e layout assertions about `strip-card` and the avatar move to the board and tabs, because those elements no longer exist.
- **Web checks.** Every web task runs `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build` before committing.
- **Python checks.** Every Python task runs `uv run ruff check . && uv run ruff format --check . && uv run mypy`.
- **Commit trailer.** Each commit message ends with a blank line followed by `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- **Ruling: the Coach toggle.** Below 1280px the Coach toggle sits at the top of the board, not in the shell's tab row (spec §3.3), because the shell doesn't own Today's panel state. The behaviour is the same: it toggles the panel, and Escape closes it.
- **Ruling: the observations line.** It keeps `Header`'s existing text formats (for example `garmin Sep 27, 5:12 AM · stale`) rather than the spec's sketched `05:12 Sep 27`, so the existing header tests carry over unchanged.
- **Test database.** DB tests run only against postgresql://tri_analyze@localhost:5435/tri_analyze_test. Brian approved this for this repo's test runs.

## Review Focus

1. **Readiness taken from an earlier day.** The verdict must say which day it is based on and stay a call up to three days old. Pinned in Task 1: `test_stale_edges`.
2. **A pending review while the coach panel is closed, at a narrow width.** The HOLD line must open the panel and put focus on the gate. Pinned in Task 8: `hold opens the coach and focuses the gate`.
3. **A low-fitness athlete: CTL under 20 with a high ACWR.** The rule must ignore ACWR, and the ACWR row must say why. Pinned in Task 1 (`test_acwr_guard`) and Task 2 (`test_acwr_row_statuses`).
4. **A first load of the page.** It must not flash every row as if it changed. Pinned in Task 7: `rows flash only when a value changes after the first render`.
5. **Keyboard-only use of the signature link.** Tabbing to a reason chip must highlight its row, and activating the chip must move focus to the row. Pinned in Task 7: `a reason chip and its row light each other, by keyboard too`.

---

### Task 1: The verdict rule

**Files:**
- Create: `packages/tri-web/src/tri_web/verdict.py`
- Test: `packages/tri-web/tests/test_verdict.py` (new)

**Interfaces:**
- Consumes: `tri_web.today.ReadinessOut` (fields `date`, `sleep_score`, `training_readiness`, `ctl`, `tsb`, `trends: dict[str, MetricTrend]`, `tsb_zone`, `ramp_7d`, `ramp_caution`, `acwr`, `acwr_flag`), and `tri_web.metrics.MetricTrend`, `ACWR_HIGH`, `ACWR_LOW` and `RAMP_CAUTION`.
- Produces:
  - `ReasonOut(key: str, text: str, severity: Literal["caution","stop","info"])`
  - `VerdictOut(call: Literal["go","easy","rest","none"], reasons: list[ReasonOut], based_on: date | None, stale: bool, harder_than_call: bool, session_done: bool)`
  - `verdict(readiness: ReadinessOut | None, todays: list[dict[str, Any]], today: date) -> VerdictOut`
  - `flags(readiness: ReadinessOut) -> list[ReasonOut]`, used by Task 2
  - the constants listed in Global Constraints

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/preflight-board
```

- [ ] **Step 2: Write the failing tests** in `packages/tri-web/tests/test_verdict.py`:

```python
"""The go / easy / rest call from the athlete's own numbers."""

from datetime import date, timedelta
from typing import Any

import pytest

from tri_web.metrics import MetricTrend
from tri_web.today import ReadinessOut
from tri_web.verdict import verdict

TODAY = date(2026, 9, 29)


def trend(now: float, avg: float, sd: float, band: str | None) -> MetricTrend:
    return MetricTrend(now=now, avg_7d=avg, avg_28d=avg, sd_28d=sd, band=band, better=None, spark=[])


TRENDS = {
    "hrv": trend(60, 60, 3, "normal"),
    "resting_hr": trend(48, 48, 2, "normal"),
    "sleep_score": trend(80, 78, 4, "normal"),
    "sleep_hours": trend(7.5, 7.3, 0.4, "normal"),
    "training_readiness": trend(70, 68, 6, "normal"),
}


def rd(**over: Any) -> ReadinessOut:
    base: dict[str, Any] = dict(
        date=TODAY, is_today=True, sleep_score=80, sleep_hours=7.5, hrv=60, resting_hr=48,
        body_battery=80, training_readiness=70, ctl=40.0, atl=42.0, tsb=-2.0, trends=dict(TRENDS),
        tsb_zone="neutral", ramp_7d=2.0, ramp_caution=False, acwr=1.05, acwr_flag=None,
    )
    base.update(over)
    return ReadinessOut(**base)


def with_trend(key: str, t: MetricTrend, **over: Any) -> ReadinessOut:
    return rd(trends={**TRENDS, key: t}, **over)


HRV_LOW = trend(52, 60, 3, "below")
RHR_HIGH = trend(55, 48, 2, "above")


def call(r: ReadinessOut | None, todays: list[dict[str, Any]] | None = None) -> str:
    return verdict(r, todays or [], TODAY).call


def test_no_readiness_is_no_call():
    v = verdict(None, [], TODAY)
    assert v.call == "none" and v.based_on is None and not v.stale
    assert [(r.key, r.text, r.severity) for r in v.reasons] == [
        ("training_readiness", "No Garmin data, sync first", "info")
    ]


def test_clean_day_is_go():
    v = verdict(rd(), [], TODAY)
    assert v.call == "go" and v.reasons == [] and v.based_on == TODAY and not v.stale


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (with_trend("hrv", HRV_LOW, hrv=52), "hrv"),
        (with_trend("resting_hr", RHR_HIGH, resting_hr=55), "resting_hr"),
        (rd(sleep_score=59), "sleep_score"),
        (rd(training_readiness=49), "training_readiness"),
        (rd(acwr=1.31, acwr_flag="high"), "acwr"),
        (rd(ramp_7d=9.0, ramp_caution=True), "ramp"),
    ],
)
def test_each_caution_alone_is_easy(r, key):
    v = verdict(r, [], TODAY)
    assert v.call == "easy"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "caution")]


def test_threshold_edges_do_not_flag():
    assert call(rd(sleep_score=60)) == "go"
    assert call(rd(training_readiness=50)) == "go"
    assert call(rd(acwr=1.3)) == "go"


def test_two_cautions_easy_three_rest():
    assert call(rd(sleep_score=59, training_readiness=49)) == "easy"
    assert call(rd(sleep_score=59, training_readiness=49, ramp_7d=9.0, ramp_caution=True)) == "rest"


@pytest.mark.parametrize(
    ("r", "key"),
    [
        (rd(training_readiness=24), "training_readiness"),
        (rd(tsb=-31.0, tsb_zone="overreaching"), "tsb"),
        (rd(acwr=1.51, acwr_flag="high"), "acwr"),
    ],
)
def test_each_stop_is_rest(r, key):
    v = verdict(r, [], TODAY)
    assert v.call == "rest"
    assert [(x.key, x.severity) for x in v.reasons] == [(key, "stop")]


def test_readiness_25_is_a_caution_not_a_stop():
    v = verdict(rd(training_readiness=25), [], TODAY)
    assert v.call == "easy" and v.reasons[0].severity == "caution"


def test_hrv_low_and_rhr_high_together_are_one_stop():
    r = rd(trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55)
    v = verdict(r, [], TODAY)
    assert v.call == "rest"
    assert [(x.key, x.severity) for x in v.reasons] == [("hrv", "stop")]
    assert "52" in v.reasons[0].text and "55" in v.reasons[0].text


def test_stops_come_before_cautions():
    v = verdict(rd(sleep_score=59, training_readiness=24), [], TODAY)
    assert [x.severity for x in v.reasons] == ["stop", "caution"]


def test_acwr_guard():
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=19.9)) == "go"
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=20.0)) == "rest"
    assert call(rd(acwr=1.6, acwr_flag="high", ctl=None)) == "go"


def test_stale_edges():
    one = verdict(rd(date=TODAY - timedelta(days=1), is_today=False), [], TODAY)
    assert one.call == "go" and one.stale and one.based_on == TODAY - timedelta(days=1)
    three = verdict(rd(date=TODAY - timedelta(days=3), is_today=False), [], TODAY)
    assert three.call == "go" and three.stale
    four = verdict(rd(date=TODAY - timedelta(days=4), is_today=False), [], TODAY)
    assert four.call == "none" and four.based_on == TODAY - timedelta(days=4)
    assert four.reasons[0].text == "Last Garmin data Fri Sep 25, sync first"


def w(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        completed=False, planned_if=None, planned_tss=None, planned_duration_sec=3600
    )
    base.update(over)
    return base


def test_harder_than_call():
    easy = rd(sleep_score=59)
    assert verdict(easy, [w(planned_if=0.8)], TODAY).harder_than_call
    assert not verdict(easy, [w(planned_if=0.7)], TODAY).harder_than_call
    assert verdict(easy, [w(planned_tss=60)], TODAY).harder_than_call  # 60 TSS/h, IF unknown
    assert not verdict(easy, [w(planned_tss=50)], TODAY).harder_than_call
    assert not verdict(easy, [w(planned_if=0.8, completed=True)], TODAY).harder_than_call
    assert not verdict(rd(), [w(planned_if=0.9)], TODAY).harder_than_call  # go


def test_session_done():
    assert verdict(rd(), [w(completed=True), w(completed=True)], TODAY).session_done
    assert not verdict(rd(), [w(completed=True), w()], TODAY).session_done
    assert not verdict(rd(), [], TODAY).session_done
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_verdict.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_web.verdict'`.

- [ ] **Step 4: Write `packages/tri-web/src/tri_web/verdict.py`**

```python
"""The morning call, go / easy / rest, from the athlete's own numbers against his own baseline,
and the condition rows the board shows beside it. Pure: build_today hands it the readiness
view and today's workouts. Every threshold lives here or in metrics.py, never in the web app."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from tri_web.metrics import ACWR_HIGH

if TYPE_CHECKING:  # today.py imports this module
    from tri_web.today import ReadinessOut

SLEEP_CAUTION = 60  # sleep score under this is a caution
READINESS_CAUTION = 50
READINESS_STOP = 25  # Garmin's "poor" band
ACWR_STOP = 1.5  # the caution is metrics.ACWR_HIGH (1.3)
ACWR_MIN_CTL = 20  # below this fitness the ratio swings on one workout, so it is ignored
STALE_DAYS = 1
NO_CALL_DAYS = 3
HARD_IF = 0.75  # a planned session at or above this intensity is harder than easy
HARD_TSS_PER_H = 55  # the same test when planned IF is unknown

Call = Literal["go", "easy", "rest", "none"]
Severity = Literal["caution", "stop", "info"]


class ReasonOut(BaseModel):
    key: str  # a condition key, so the board can link a reason to its row
    text: str
    severity: Severity


class VerdictOut(BaseModel):
    call: Call
    reasons: list[ReasonOut]  # stops first, then cautions
    based_on: date | None
    stale: bool
    harder_than_call: bool
    session_done: bool


def _band(r: ReadinessOut, key: str) -> str:
    t = r.trends.get(key)
    if t is None or t.avg_28d is None or t.sd_28d is None:
        return ""
    return f", {t.avg_28d - t.sd_28d:.0f}–{t.avg_28d + t.sd_28d:.0f}"


def acwr_counts(r: ReadinessOut) -> bool:
    return r.acwr is not None and r.ctl is not None and r.ctl >= ACWR_MIN_CTL


def flags(r: ReadinessOut) -> list[ReasonOut]:
    """The cautions and stops for one readiness row, stops first, in the spec's table order."""
    out: list[ReasonOut] = []
    hrv, rhr = r.trends.get("hrv"), r.trends.get("resting_hr")
    hrv_low = hrv is not None and hrv.band == "below"
    rhr_high = rhr is not None and rhr.band == "above"
    if hrv_low and rhr_high:
        assert hrv is not None and rhr is not None
        out.append(ReasonOut(key="hrv", severity="stop",
                             text=f"HRV {hrv.now:.0f} ms low and RHR {rhr.now:.0f} bpm high together"))
    else:
        if hrv_low:
            assert hrv is not None
            out.append(ReasonOut(key="hrv", severity="caution",
                                 text=f"HRV {hrv.now:.0f} ms, below your band{_band(r, 'hrv')}"))
        if rhr_high:
            assert rhr is not None
            out.append(ReasonOut(key="resting_hr", severity="caution",
                                 text=f"RHR {rhr.now:.0f} bpm, above your band{_band(r, 'resting_hr')}"))
    if r.sleep_score is not None and r.sleep_score < SLEEP_CAUTION:
        out.append(ReasonOut(key="sleep_score", severity="caution",
                             text=f"Sleep score {r.sleep_score}, under {SLEEP_CAUTION}"))
    tr = r.training_readiness
    if tr is not None and tr < READINESS_STOP:
        out.append(ReasonOut(key="training_readiness", severity="stop",
                             text=f"Readiness {tr}, under {READINESS_STOP}"))
    elif tr is not None and tr < READINESS_CAUTION:
        out.append(ReasonOut(key="training_readiness", severity="caution",
                             text=f"Readiness {tr}, under {READINESS_CAUTION}"))
    if r.tsb_zone == "overreaching" and r.tsb is not None:
        out.append(ReasonOut(key="tsb", severity="stop", text=f"Form {r.tsb:.1f}, overreaching"))
    if acwr_counts(r):
        assert r.acwr is not None
        if r.acwr > ACWR_STOP:
            out.append(ReasonOut(key="acwr", severity="stop", text=f"ACWR {r.acwr:.2f}, over {ACWR_STOP}"))
        elif r.acwr > ACWR_HIGH:
            out.append(ReasonOut(key="acwr", severity="caution", text=f"ACWR {r.acwr:.2f}, over {ACWR_HIGH}"))
    if r.ramp_caution and r.ramp_7d is not None:
        out.append(ReasonOut(key="ramp", severity="caution", text=f"Ramp +{r.ramp_7d:.1f} CTL/wk, fast"))
    return sorted(out, key=lambda f: f.severity != "stop")  # stable: table order within each group


def _hard(w: dict[str, Any]) -> bool:
    if w.get("planned_if") is not None:
        return float(w["planned_if"]) >= HARD_IF
    tss, secs = w.get("planned_tss"), w.get("planned_duration_sec")
    return tss is not None and bool(secs) and float(tss) / (secs / 3600) >= HARD_TSS_PER_H


def verdict(r: ReadinessOut | None, todays: list[dict[str, Any]], today: date) -> VerdictOut:
    done = bool(todays) and all(bool(w["completed"]) for w in todays)
    if r is None:
        reason = ReasonOut(key="training_readiness", text="No Garmin data, sync first", severity="info")
        return VerdictOut(call="none", reasons=[reason], based_on=None, stale=False,
                          harder_than_call=False, session_done=done)
    age = (today - r.date).days
    if age > NO_CALL_DAYS:
        text = f"Last Garmin data {r.date:%a %b} {r.date.day}, sync first"
        reason = ReasonOut(key="training_readiness", text=text, severity="info")
        return VerdictOut(call="none", reasons=[reason], based_on=r.date, stale=True,
                          harder_than_call=False, session_done=done)
    found = flags(r)
    stops = any(f.severity == "stop" for f in found)
    c: Call = "rest" if stops or len(found) >= 3 else "easy" if found else "go"
    harder = c in ("easy", "rest") and any(not w["completed"] and _hard(w) for w in todays)
    return VerdictOut(call=c, reasons=found, based_on=r.date, stale=age >= STALE_DAYS,
                      harder_than_call=harder, session_done=done)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_verdict.py -q`
Expected: all pass.

- [ ] **Step 6: Format, lint, type-check**

Run: `uv run ruff format packages/tri-web && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean. Ruff may re-wrap long lines; accept its formatting.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-web/src/tri_web/verdict.py packages/tri-web/tests/test_verdict.py
git commit -m "feat(web): go/easy/rest verdict from the athlete's own numbers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Condition rows

**Files:**
- Modify: `packages/tri-web/src/tri_web/verdict.py`
- Test: `packages/tri-web/tests/test_verdict.py`

**Interfaces:**
- Consumes: Task 1's `flags`, `acwr_counts`, `ReasonOut`; `metrics.ACWR_LOW`, `ACWR_HIGH`, `RAMP_CAUTION`.
- Produces:
  - `ConditionOut(key, label, value: float | None, unit: str, baseline: float | None, band_low: float | None, band_high: float | None, status: str, flagged: bool)`
  - `conditions(readiness: ReadinessOut | None) -> list[ConditionOut]`, with rows in the key order `training_readiness, hrv, resting_hr, sleep_score, sleep_hours, tsb, acwr, ramp`

- [ ] **Step 1: Write the failing tests** (append to `test_verdict.py`, and add `conditions` to the `tri_web.verdict` import):

```python
KEYS = ["training_readiness", "hrv", "resting_hr", "sleep_score", "sleep_hours", "tsb", "acwr", "ramp"]


def rows(r: ReadinessOut | None) -> dict[str, Any]:
    return {c.key: c for c in conditions(r)}


def test_no_readiness_no_rows():
    assert conditions(None) == []


def test_row_order_labels_and_units():
    cs = conditions(rd())
    assert [c.key for c in cs] == KEYS
    assert [c.label for c in cs] == ["Readiness", "HRV", "RHR", "Sleep", "Slept", "Form (TSB)", "ACWR", "Ramp"]
    assert [c.unit for c in cs] == ["", "ms", "bpm", "", "h", "", "", "/wk"]


def test_trend_rows_carry_baseline_band_and_status():
    c = rows(with_trend("hrv", HRV_LOW, hrv=52))["hrv"]
    assert (c.value, c.baseline, c.band_low, c.band_high) == (52, 60, 57, 63)
    assert c.status == "low" and c.flagged
    assert rows(rd())["hrv"].status == "within" and not rows(rd())["hrv"].flagged
    assert rows(with_trend("resting_hr", RHR_HIGH, resting_hr=55))["resting_hr"].status == "high"


def test_rows_without_data_or_baseline():
    no_band = trend(60, 60, 3, None)
    assert rows(with_trend("hrv", no_band))["hrv"].status == "no baseline"
    r = rows(rd(sleep_hours=None, trends={k: v for k, v in TRENDS.items() if k != "sleep_hours"}))
    assert r["sleep_hours"].status == "no data" and r["sleep_hours"].value is None


def test_sleep_score_flag_follows_the_threshold_not_the_band():
    assert rows(rd(sleep_score=59))["sleep_score"].flagged


def test_tsb_row():
    c = rows(rd(tsb=-31.0, tsb_zone="overreaching"))["tsb"]
    assert (c.band_low, c.band_high, c.status, c.flagged) == (-30, 25, "overreaching", True)
    assert rows(rd(tsb=None, tsb_zone=None))["tsb"].status == "no data"


def test_acwr_row_statuses():
    assert rows(rd(acwr=1.05))["acwr"].status == "within"
    assert rows(rd(acwr=1.4))["acwr"].status == "high"
    assert rows(rd(acwr=1.4))["acwr"].flagged
    assert rows(rd(acwr=0.7))["acwr"].status == "low"
    assert not rows(rd(acwr=0.7))["acwr"].flagged
    guarded = rows(rd(acwr=1.6, ctl=19.0))["acwr"]
    assert guarded.status == "ignored: CTL under 20" and not guarded.flagged
    c = rows(rd())["acwr"]
    assert (c.band_low, c.band_high) == (0.8, 1.3)


def test_ramp_row():
    c = rows(rd(ramp_7d=9.0, ramp_caution=True))["ramp"]
    assert (c.value, c.band_low, c.band_high, c.status, c.flagged) == (9.0, None, 8, "fast", True)
    assert rows(rd(ramp_7d=None))["ramp"].status == "no data"


def test_combined_stop_flags_both_rows():
    r = rd(trends={**TRENDS, "hrv": HRV_LOW, "resting_hr": RHR_HIGH}, hrv=52, resting_hr=55)
    assert rows(r)["hrv"].flagged and rows(r)["resting_hr"].flagged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_verdict.py -q`
Expected: `ImportError: cannot import name 'conditions'`.

- [ ] **Step 3: Implement.** Change the metrics import to `from tri_web.metrics import ACWR_HIGH, ACWR_LOW, RAMP_CAUTION`, then append:

```python
TSB_BAND = (-30.0, 25.0)  # outside is overreaching or detraining (metrics.TSB_ZONES)

ConditionKey = Literal[
    "training_readiness", "hrv", "resting_hr", "sleep_score", "sleep_hours", "tsb", "acwr", "ramp"
]
_TREND_ROWS: tuple[tuple[ConditionKey, str, str], ...] = (
    ("training_readiness", "Readiness", ""),
    ("hrv", "HRV", "ms"),
    ("resting_hr", "RHR", "bpm"),
    ("sleep_score", "Sleep", ""),
    ("sleep_hours", "Slept", "h"),
)
_BAND_WORD = {"below": "low", "above": "high", "normal": "within"}


class ConditionOut(BaseModel):
    key: ConditionKey
    label: str
    value: float | None
    unit: str
    baseline: float | None
    band_low: float | None
    band_high: float | None
    status: str
    flagged: bool


def _raw(r: ReadinessOut, key: str) -> float | None:
    v = {
        "training_readiness": r.training_readiness, "hrv": r.hrv, "resting_hr": r.resting_hr,
        "sleep_score": r.sleep_score, "sleep_hours": r.sleep_hours,
    }[key]
    return None if v is None else float(v)


def conditions(r: ReadinessOut | None) -> list[ConditionOut]:
    """One row per condition the board shows, built here so the web app holds no threshold."""
    if r is None:
        return []
    found = flags(r)
    flagged = {f.key for f in found}
    if any(f.key == "hrv" and f.severity == "stop" for f in found):
        flagged.add("resting_hr")  # the combined HRV/RHR stop is keyed hrv but covers both rows
    out: list[ConditionOut] = []
    for key, label, unit in _TREND_ROWS:
        t, value = r.trends.get(key), _raw(r, key)
        lo = hi = None
        if t is not None and t.band is not None and t.avg_28d is not None and t.sd_28d is not None:
            lo, hi = round(t.avg_28d - t.sd_28d, 2), round(t.avg_28d + t.sd_28d, 2)
        if value is None:
            status = "no data"
        elif lo is None or t is None or t.band is None:
            status = "no baseline"
        else:
            status = _BAND_WORD[t.band]
        out.append(ConditionOut(
            key=key, label=label, value=value, unit=unit,
            baseline=t.avg_28d if t is not None else None, band_low=lo, band_high=hi,
            status=status, flagged=key in flagged,
        ))
    out.append(ConditionOut(
        key="tsb", label="Form (TSB)", value=r.tsb, unit="", baseline=None,
        band_low=TSB_BAND[0], band_high=TSB_BAND[1],
        status="no data" if r.tsb is None else (r.tsb_zone or "no data"), flagged="tsb" in flagged,
    ))
    if r.acwr is None:
        acwr_status = "no data"
    elif not acwr_counts(r):
        acwr_status = f"ignored: CTL under {ACWR_MIN_CTL}"
    else:
        acwr_status = "high" if r.acwr > ACWR_HIGH else "low" if r.acwr < ACWR_LOW else "within"
    out.append(ConditionOut(
        key="acwr", label="ACWR", value=r.acwr, unit="", baseline=None,
        band_low=ACWR_LOW, band_high=ACWR_HIGH, status=acwr_status, flagged="acwr" in flagged,
    ))
    out.append(ConditionOut(
        key="ramp", label="Ramp", value=r.ramp_7d, unit="/wk", baseline=None,
        band_low=None, band_high=RAMP_CAUTION,
        status="no data" if r.ramp_7d is None else ("fast" if r.ramp_caution else "within"),
        flagged="ramp" in flagged,
    ))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_verdict.py -q`
Expected: all pass.

- [ ] **Step 5: Format, lint, type-check.** Run the same command as Task 1 Step 6. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-web/src/tri_web/verdict.py packages/tri-web/tests/test_verdict.py
git commit -m "feat(web): condition rows built server-side, with bands and status words

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Serve the verdict and conditions on TodayView

**Files:**
- Modify: `packages/tri-web/src/tri_web/today.py` (`TodayView`, `build_today`)
- Modify: `web/openapi.json`, `web/src/api/types.ts` (regenerated)
- Modify: `web/tests/fixtures.tsx`, `web/tests/e2e/smoke.spec.ts` (stub fields)
- Test: `packages/tri-web/tests/test_today.py` (new tests only)

**Interfaces:**
- Consumes: `verdict`, `conditions`, `VerdictOut`, `ConditionOut` from Task 1 and Task 2.
- Produces:
  - `TodayView.verdict: VerdictOut` (always present) and `TodayView.conditions: list[ConditionOut]`.
  - In TypeScript: `TodayView["verdict"]` and `TodayView["conditions"]`. `web/src/api/queries.ts` gains `export type VerdictOut = S["VerdictOut"]; export type ConditionOut = S["ConditionOut"]; export type ReasonOut = S["ReasonOut"];`.

- [ ] **Step 1: Write the failing tests** (append to `packages/tri-web/tests/test_today.py`; it already has `seed_metrics`, `TODAY`, `build_today` and `runtime`):

```python
async def test_today_carries_the_verdict_and_conditions(nocommit, runtime):
    seed_metrics(nocommit, TODAY)  # HRV 50 below band and RHR 55 above band on TODAY
    view = await build_today(runtime(today=TODAY))
    assert view.verdict.call == "rest"
    assert [(r.key, r.severity) for r in view.verdict.reasons] == [("hrv", "stop")]
    assert view.verdict.based_on == TODAY and not view.verdict.stale
    keys = [c.key for c in view.conditions]
    assert keys[:3] == ["training_readiness", "hrv", "resting_hr"] and len(keys) == 8
    hrv = next(c for c in view.conditions if c.key == "hrv")
    assert hrv.status == "low" and hrv.flagged


async def test_no_metrics_is_no_call(nocommit, runtime):
    view = await build_today(runtime(today=TODAY))
    assert view.verdict.call == "none" and view.conditions == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_today.py -q -k "verdict or no_call"`
Expected: FAIL (`AttributeError: 'TodayView' object has no attribute 'verdict'`).

- [ ] **Step 3: Wire it in `today.py`.** Import `from tri_web.verdict import ConditionOut, VerdictOut, conditions, verdict`. Add these fields to `TodayView`, after `labs_missing` and before `pending`:

```python
    verdict: VerdictOut
    conditions: list[ConditionOut]
```

In `build_today`, after `readiness = _readiness(...)`, add:

```python
    call = verdict(readiness, todays, today)
    rows = conditions(readiness)
```

Pass `verdict=call, conditions=rows` to `TodayView(...)`.

- [ ] **Step 4: Run all tri-web tests**

Run: `uv run pytest packages/tri-web -q`
Expected: all pass (DB tests hit the approved test database).

- [ ] **Step 5: Regenerate the types and export the aliases**

Run: `npm --prefix web run types`. Then add to `web/src/api/queries.ts`, after `export type JobOut = S["JobOut"];`:

```ts
export type VerdictOut = S["VerdictOut"];
export type ReasonOut = S["ReasonOut"];
export type ConditionOut = S["ConditionOut"];
```

- [ ] **Step 6: Update `web/tests/fixtures.tsx`.** In `todayEmpty()`, add:

```tsx
    verdict: { call: "none", reasons: [{ key: "training_readiness", text: "No Garmin data, sync first", severity: "info" }], based_on: null, stale: false, harder_than_call: false, session_done: false },
    conditions: [],
```

In `todayFull()`, add:

```tsx
    verdict: { call: "go", reasons: [], based_on: "2026-09-16", stale: false, harder_than_call: false, session_done: false },
    conditions: [
      { key: "training_readiness", label: "Readiness", value: 77, unit: "", baseline: 70, band_low: 62, band_high: 78, status: "within", flagged: false },
      { key: "hrv", label: "HRV", value: 62, unit: "ms", baseline: 58, band_low: 55, band_high: 61, status: "high", flagged: false },
      { key: "resting_hr", label: "RHR", value: 48, unit: "bpm", baseline: 50, band_low: 48, band_high: 52, status: "within", flagged: false },
      { key: "sleep_score", label: "Sleep", value: 81, unit: "", baseline: 78, band_low: 73, band_high: 83, status: "within", flagged: false },
      { key: "sleep_hours", label: "Slept", value: 7.5, unit: "h", baseline: 7.2, band_low: 6.8, band_high: 7.6, status: "within", flagged: false },
      { key: "tsb", label: "Form (TSB)", value: -4.9, unit: "", baseline: null, band_low: -30, band_high: 25, status: "neutral", flagged: false },
      { key: "acwr", label: "ACWR", value: 1.11, unit: "", baseline: null, band_low: 0.8, band_high: 1.3, status: "within", flagged: false },
      { key: "ramp", label: "Ramp", value: 3.5, unit: "/wk", baseline: null, band_low: null, band_high: 8, status: "within", flagged: false },
    ],
```

In `web/tests/e2e/smoke.spec.ts`, add the same two `todayEmpty` lines (the no-call verdict and `conditions: []`) to the stubbed `today` object.

- [ ] **Step 7: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass (the components don't read the new fields yet).

- [ ] **Step 8: Python checks and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`. Then:

```bash
git add packages/tri-web web/openapi.json web/src/api web/tests/fixtures.tsx web/tests/e2e/smoke.spec.ts
git commit -m "feat(web): TodayView carries the verdict and the condition rows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Direction contract in Today's surface brief (Impeccable)

**Files:**
- Create or update, via the Impeccable launcher: the surface brief for `web/src/pages/Today.tsx`. The launcher decides its path under `.impeccable/`.

**Interfaces:**
- Produces: the contract that Task 10's finish reviewer audits against. It is never copied into source.

- [ ] **Step 1: Read any existing brief**

Run: `"/Users/brian/.claude/plugins/cache/impeccable/impeccable/4.4.0/skills/impeccable/scripts/impeccable" surface-brief read web/src/pages/Today.tsx`

- [ ] **Step 2: Write the body file.** Save the following to the session scratchpad as `today-brief.md`:

```markdown
Scope: tri-web Today, leading the whole-app look (shell, Settings, placeholders inherit it). Mode: Operate.
Audience and job: Brian, about 5 AM, laptop, dark room, before training. Decide go / easy / rest, see why in exact figures, act on the coach's proposals. Also used for the weekly sit-down and post-session analysis.
Constraints: PRODUCT.md; WCAG 2.2 AA; local-only; no new libraries or web fonts; status never by colour alone.

## Direction contract
THESIS: Each morning is a preflight. The board states the call first, then the conditions that produced it, each against the athlete's own limits. It refuses the category's card grid of equal-weight metric tiles and rings.
OWN-WORLD: Near-black instrument ground (#0b0f14) with panel #111820, instrument-white figures, thin #2e3d52 rules, tabular numerals throughout. Status words in go green, easy amber, rest coral and hold blue, always spelled out. Limit markers are hairline tracks with a shaded band and a single tick. Daylight board variant for light mode.
STORY: The athlete reads one word, sees which conditions moved it, traces each reason to its row and figure, then either trains or opens the coach to act on a held change.
FIRST VIEWPORT: At 1440px, the board takes the left two-thirds and the coach panel the right third at full height. Top of the board: the call word in large tracked caps, then the reason chips. Directly under it, the HOLD line when a review waits, then the conditions table (8 rows) with its limit column, all above the fold. Today's plan and the week sit below. The primary action is the chip-to-row trace, and the HOLD line jumps to the gate.
FORM: Go / No-Go Preflight Board, position 1 on the ordered list (pick card), seed key f2f09b9e.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
```

- [ ] **Step 3: Write and verify**

Run: `"/Users/brian/.claude/plugins/cache/impeccable/impeccable/4.4.0/skills/impeccable/scripts/impeccable" surface-brief write web/src/pages/Today.tsx <scratchpad>/today-brief.md web/src/components/Shell.tsx`, then `surface-brief read web/src/pages/Today.tsx`.
Expected: all six contract blocks and the seed key are present.

- [ ] **Step 4: Commit** whatever the launcher wrote under `.impeccable/`, if it is tracked. Check `git status`; if the brief is git-ignored, skip the commit.

```bash
git add .impeccable
git commit -m "docs(web): preflight-board direction contract in Today's surface brief

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Board tokens (dark first)

**Files:**
- Modify: `web/src/index.css`
- Test: `web/tests/styles.test.ts` (the token test changes, per spec §5.2)

**Interfaces:**
- Produces: the Tailwind utilities `bg-go/text-go`, `text-easy`, `text-rest`, `text-hold`, `bg-hold/10` and `border-rest`, plus the existing ones with new values. It also produces the CSS class `.board-flash`, used by Task 7.

- [ ] **Step 1: Replace the token test.** In `web/tests/styles.test.ts`, replace the test `"the tokens pass contrast and include good"` with:

```ts
test("the board tokens are dark first with a daylight variant", () => {
  for (const v of [
    "--surface: #0b0f14;", "--surface-2: #111820;", "--ink: #d9dee5;", "--ink-2: #95a0ae;", "--line: #2e3d52;",
    "--go: #5fd38d;", "--easy: #f2c14e;", "--rest: #ff8f6b;", "--hold: #8fb8ff;",
    "--surface: #f4f5f7;", "--ink: #12161c;", "--ink-2: #555e6b;",
    "--go: #19663a;", "--easy: #7d5400;", "--rest: #a13a18;", "--hold: #2f5fb3;",
  ]) expect(css).toContain(v);
  for (const c of ["go", "easy", "rest", "hold", "good", "warn", "danger"]) expect(css).toContain(`--color-${c}: var(--${c});`);
  expect(css).toContain("prefers-color-scheme: light");
  expect(css).toContain("prefers-reduced-motion: reduce");
  expect(css).toMatch(/button:not\(:disabled\)[^{]*\{\s*cursor: pointer;/);
});

test("the row flash only animates when motion is allowed", () => {
  expect(css).toMatch(/@media \(prefers-reduced-motion: no-preference\)\s*\{[^}]*\.board-flash/);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test -- tests/styles.test.ts`
Expected: FAIL on `--surface: #0b0f14;`.

- [ ] **Step 3: Rewrite the token blocks in `index.css`.** Replace the `:root` block and the `@media (prefers-color-scheme: dark)` block with:

```css
/* Dark first: the board is read at 5 AM. The daylight board overrides for light schemes. */
:root {
  color-scheme: dark;
  --surface: #0b0f14;
  --surface-2: #111820;
  --ink: #d9dee5;
  --ink-2: #95a0ae;
  --line: #2e3d52;
  --accent: #8fb8ff;
  --planning: #8ea3ea;
  --nutrition: #e9915a;
  --go: #5fd38d;
  --easy: #f2c14e;
  --rest: #ff8f6b;
  --hold: #8fb8ff;
  --warn: #f2c14e;
  --good: #5fd38d;
  --danger: #ef6a63;
  --on-fill: #0b0f14;
}

@media (prefers-color-scheme: light) {
  :root {
    color-scheme: light;
    --surface: #f4f5f7;
    --surface-2: #ffffff;
    --ink: #12161c;
    --ink-2: #555e6b;
    --line: #d3d8df;
    --accent: #2f5fb3;
    --planning: #3552a8;
    --nutrition: #9c4a18;
    --go: #19663a;
    --easy: #7d5400;
    --rest: #a13a18;
    --hold: #2f5fb3;
    --warn: #7d5400;
    --good: #19663a;
    --danger: #b3261e;
    --on-fill: #ffffff;
  }
}
```

In `@theme inline`, add after `--color-danger`:

```css
  --color-go: var(--go);
  --color-easy: var(--easy);
  --color-rest: var(--rest);
  --color-hold: var(--hold);
```

After the `@layer base { … }` block, add:

```css
@keyframes board-flash {
  from { background-color: color-mix(in srgb, var(--hold) 22%, transparent); }
  to { background-color: transparent; }
}
@media (prefers-reduced-motion: no-preference) {
  .board-flash { animation: board-flash 700ms ease-out 1; }
}
```

- [ ] **Step 4: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/index.css web/tests/styles.test.ts
git commit -m "style(web): preflight board tokens, dark first with a daylight variant

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Shell: observations line and visible tabs

**Files:**
- Create: `web/src/components/shell/Tabs.tsx`
- Modify: `web/src/components/Header.tsx` (restyle as the observations line; props and text formats unchanged)
- Modify: `web/src/components/Shell.tsx`
- Delete: `web/src/components/AvatarMenu.tsx`
- Test: `web/tests/shell.test.tsx`

**Interfaces:**
- Consumes: `JobButton({kind,label,body})` from `components/jobs/JobButton.tsx`.
- Produces: `Tabs()`, a `<nav aria-label="Sections">` of five `NavLink`s. `Header({ today, slots, now })` keeps its API.

- [ ] **Step 1: Update the tests** in `web/tests/shell.test.tsx`:
  - Delete the tests `"the avatar menu holds the five sections, marks the current one, and the two jobs"` and `"the menu closes on Escape, on an outside click, and after following a link"`.
  - In `"a skip link targets main, and main takes focus after a route change"`, delete the line `await user.click(screen.getByRole("button", { name: "Account menu" }));`. The Settings link is now always visible.
  - Append:

```tsx
test("the tabs show every section, mark the current one, and the jobs sit in the top bar", () => {
  renderWith(tree(), { route: "/progress" });
  const nav = screen.getByRole("navigation", { name: "Sections" });
  for (const name of ["Today", "Progress", "Nutrition", "Labs", "Settings"]) {
    expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
  }
  expect(within(nav).getByRole("link", { name: "Progress" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Sync now" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weekly check-in" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Account menu/ })).not.toBeInTheDocument();
});
```

Add `within` to the `@testing-library/react` import.

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/shell.test.tsx`
Expected: the new test fails, because there is no "Sections" navigation outside the closed menu.

- [ ] **Step 3: Create `web/src/components/shell/Tabs.tsx`**

```tsx
import { NavLink } from "react-router";

const items = [
  { to: "/", label: "Today" },
  { to: "/progress", label: "Progress" },
  { to: "/nutrition", label: "Nutrition" },
  { to: "/labs", label: "Labs" },
  { to: "/settings", label: "Settings" },
];

export default function Tabs() {
  return (
    <nav aria-label="Sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-surface-2 px-4">
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) =>
            `-mb-px inline-flex min-h-10 items-center border-b-2 px-3 text-sm whitespace-nowrap ${
              isActive ? "border-hold font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`
          }
        >
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 4: Restyle `Header.tsx` as the observations line.**
  - Keep every text and the `now` logic.
  - Change the `<header>` class to `flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2 tabular-nums`.
  - Change the date `div` class to `text-sm font-semibold tracking-wide uppercase`.
  - Change the badge class to `rounded-full border border-hold/60 px-2 py-0.5 text-xs font-medium text-hold`.

- [ ] **Step 5: Rewrite `Shell.tsx`.** Replace the `AvatarMenu` import with `import JobButton from "./jobs/JobButton"; import Tabs from "./shell/Tabs";`, then replace the `<Header … slots={<AvatarMenu />} />` line with:

```tsx
      <Header
        today={today.data}
        now={today.dataUpdatedAt || undefined}
        slots={
          <div className="flex items-start gap-2">
            <div className="w-40"><JobButton kind="sync" label="Sync now" body={{}} /></div>
            <div className="w-40"><JobButton kind="checkin" label="Weekly check-in" body={{ sync: true }} /></div>
          </div>
        }
      />
      <Tabs />
```

Delete `web/src/components/AvatarMenu.tsx`.

- [ ] **Step 6: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass. `rg AvatarMenu web/src web/tests` finds nothing.

- [ ] **Step 7: Commit**

```bash
git add -A web/src/components web/tests/shell.test.tsx
git commit -m "feat(web): observations line and visible tabs replace the avatar menu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Verdict strip, conditions table, limit marker, chip-to-row link

**Files:**
- Create: `web/src/components/board/VerdictStrip.tsx`, `web/src/components/board/Conditions.tsx`, `web/src/components/board/LimitMarker.tsx`, `web/src/components/board/format.ts`
- Test: `web/tests/verdict.test.tsx` (new)

**Interfaces:**
- Consumes: `VerdictOut`, `ReasonOut`, `ConditionOut`, `TodayView` from `api/queries`; `day()` from `lib/format`; the `.board-flash` class and `text-go/easy/rest/hold` from Task 5.
- Produces:
  - `VerdictStrip({ verdict: VerdictOut; active: string | null; onActive: (k: string | null) => void })`
  - `Conditions({ readiness: TodayView["readiness"]; rows: ConditionOut[]; reasons: ReasonOut[]; active: string | null; onActive: (k: string | null) => void })`
  - `LimitMarker({ low, high, value }: { low: number | null; high: number | null; value: number | null })`
  - `conditionValue(c: ConditionOut): string`

- [ ] **Step 1: Write the failing tests** in `web/tests/verdict.test.tsx`:

```tsx
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VerdictStrip from "../src/components/board/VerdictStrip";
import Conditions from "../src/components/board/Conditions";
import type { ConditionOut, VerdictOut } from "../src/api/queries";
import { todayFull } from "./fixtures";

const easy: VerdictOut = {
  call: "easy",
  reasons: [{ key: "acwr", text: "ACWR 1.45, over 1.3", severity: "caution" }],
  based_on: "2026-09-16", stale: false, harder_than_call: true, session_done: false,
};

function Board({ verdict = easy, rows = todayFull().conditions }: { verdict?: VerdictOut; rows?: ConditionOut[] }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <>
      <VerdictStrip verdict={verdict} active={active} onActive={setActive} />
      <Conditions readiness={todayFull().readiness} rows={rows} reasons={verdict.reasons} active={active} onActive={setActive} />
    </>
  );
}

test.each([
  ["go", "GO", "text-go"],
  ["easy", "EASY", "text-easy"],
  ["rest", "REST", "text-rest"],
  ["none", "NO CALL", "text-ink-2"],
] as const)("the %s call reads %s in its colour", (call, word, tone) => {
  render(<Board verdict={{ ...easy, call, reasons: call === "go" ? [] : easy.reasons }} />);
  expect(screen.getByText(word)).toHaveClass(tone);
});

test("a go day says so in words", () => {
  render(<Board verdict={{ ...easy, call: "go", reasons: [], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument();
});

test("the strip says when the data is old, when the plan is harder, and when the session is done", () => {
  render(<Board verdict={{ ...easy, stale: true, based_on: "2026-09-14", session_done: true }} />);
  expect(screen.getByText(/based on Mon, Sep 14/)).toBeInTheDocument();
  expect(screen.getByText("planned session is harder than today's call")).toBeInTheDocument();
  expect(screen.getByText("session done, recover")).toBeInTheDocument();
});

test("the conditions table shows each row's figures and status word", () => {
  render(<Board />);
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  expect(screen.getByText("62 ms")).toBeInTheDocument();
  expect(screen.getByText("81")).toBeInTheDocument();
  expect(screen.getByText("7.5 h")).toBeInTheDocument();
  expect(screen.getByText("-4.9")).toBeInTheDocument();
  expect(screen.getByText("1.11")).toBeInTheDocument();
  expect(screen.getByText("+3.5/wk")).toBeInTheDocument();
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
  await user.tab(); // the first focusable element is the chip
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
  const flashing = [...document.querySelectorAll(".board-flash")].map((el) => el.closest("tr")!.id);
  expect(flashing).toEqual(["cond-hrv"]);
});

test("rows from an earlier day say which day", () => {
  const t = todayFull();
  render(<Conditions readiness={{ ...t.readiness!, is_today: false, date: "2026-09-14" }} rows={t.conditions} reasons={[]} active={null} onActive={() => {}} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/verdict.test.tsx`
Expected: FAIL (the modules can't be resolved).

- [ ] **Step 3: Create `web/src/components/board/format.ts`**

```ts
import type { ConditionOut } from "../../api/queries";

/** Display digits per condition: formatting only; the thresholds live on the server. */
const DIGITS: Record<string, number> = { sleep_hours: 1, tsb: 1, acwr: 2, ramp: 1 };

export function conditionValue(c: ConditionOut): string {
  if (c.value == null) return "no data";
  const digits = DIGITS[c.key] ?? 0;
  const x = Number(c.value.toFixed(digits));
  const num = c.key === "ramp" ? `${x > 0 ? "+" : ""}${(x === 0 ? 0 : x).toFixed(digits)}` : x.toFixed(digits);
  if (!c.unit) return num;
  return c.unit.startsWith("/") ? `${num}${c.unit}` : `${num} ${c.unit}`;
}

export function baselineValue(c: ConditionOut): string {
  if (c.baseline == null) return "";
  return c.baseline.toFixed(DIGITS[c.key] ?? 0);
}
```

- [ ] **Step 4: Create `web/src/components/board/LimitMarker.tsx`**

```tsx
/** A hairline track: your band shaded, a tick at today's value. Decorative; the status word carries the meaning. */
export default function LimitMarker({ low, high, value }: { low: number | null; high: number | null; value: number | null }) {
  if (value == null || (low == null && high == null)) return null;
  const lo = low ?? Math.min(0, value);
  const hi = high ?? lo;
  const span = hi - lo || Math.abs(hi) || 1;
  const min = Math.min(value, lo) - span * 0.25;
  const max = Math.max(value, hi) + span * 0.25;
  const pos = (x: number) => `${(((x - min) / (max - min)) * 100).toFixed(1)}%`;
  return (
    <div aria-hidden="true" className="relative h-1.5 w-24 rounded-full bg-line">
      <div className="absolute inset-y-0 rounded-full bg-ink-2/50" style={{ left: pos(lo), right: `calc(100% - ${pos(hi)})` }} />
      <div className="absolute -top-1 h-3.5 w-0.5 rounded-full bg-ink" style={{ left: pos(value) }} />
    </div>
  );
}
```

- [ ] **Step 5: Create `web/src/components/board/VerdictStrip.tsx`**

```tsx
import type { ReasonOut, VerdictOut } from "../../api/queries";
import { day } from "../../lib/format";

const WORD = { go: "GO", easy: "EASY", rest: "REST", none: "NO CALL" } as const;
const TONE = { go: "text-go", easy: "text-easy", rest: "text-rest", none: "text-ink-2" } as const;
const CHIP = { stop: "border-rest/70 text-rest", caution: "border-easy/70 text-easy", info: "border-line text-ink-2" } as const;

type Props = { verdict: VerdictOut; active: string | null; onActive: (key: string | null) => void };

function Chip({ r, active, onActive }: { r: ReasonOut; active: boolean; onActive: Props["onActive"] }) {
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

export default function VerdictStrip({ verdict: v, active, onActive }: Props) {
  return (
    <section aria-label="Today's call" className="border-b border-line px-6 pt-6 pb-5">
      <div role="status" className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span className={`text-5xl leading-none font-semibold tracking-[0.14em] ${TONE[v.call]}`}>{WORD[v.call]}</span>
        {v.stale && v.based_on && <span className="text-sm text-ink-2">based on {day(v.based_on)}</span>}
        {v.session_done && <span className="text-sm text-ink-2">session done, recover</span>}
      </div>
      {v.call === "go" ? (
        <p className="mt-3 text-sm text-ink-2">All conditions within your limits</p>
      ) : (
        v.reasons.length > 0 && (
          <ul aria-label="Reasons" className="mt-3 flex flex-wrap gap-2">
            {v.reasons.map((r) => (
              <Chip key={r.key} r={r} active={active === r.key} onActive={onActive} />
            ))}
          </ul>
        )
      )}
      {v.harder_than_call && <p className="mt-3 text-sm text-easy">planned session is harder than today's call</p>}
    </section>
  );
}
```

- [ ] **Step 6: Create `web/src/components/board/Conditions.tsx`**

```tsx
import { useState } from "react";
import type { ConditionOut, ReasonOut, TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import LimitMarker from "./LimitMarker";
import { baselineValue, conditionValue } from "./format";

type Props = {
  readiness: TodayView["readiness"];
  rows: ConditionOut[];
  reasons: ReasonOut[];
  active: string | null;
  onActive: (key: string | null) => void;
};

const SEVERITY_TONE = { stop: "text-rest", caution: "text-easy", info: "text-ink-2" } as const;

export default function Conditions({ readiness, rows, reasons, active, onActive }: Props) {
  // Remember the last rows (React's adjust-state-during-render pattern) so only a value that
  // changes after a refetch flashes; the first render flashes nothing.
  const [prevRows, setPrevRows] = useState(rows);
  const [changed, setChanged] = useState<ReadonlySet<string>>(new Set());
  if (rows !== prevRows) {
    const before = new Map(prevRows.map((c) => [c.key, c.value]));
    setChanged(new Set(rows.filter((c) => before.has(c.key) && before.get(c.key) !== c.value).map((c) => c.key)));
    setPrevRows(rows);
  }
  const severity = new Map(reasons.map((r) => [r.key, r.severity]));
  const title = readiness && !readiness.is_today ? `Conditions from ${day(readiness.date)}` : "Conditions";
  return (
    <section aria-labelledby="conditions-h" className="border-b border-line px-6 py-5">
      <h2 id="conditions-h" className="text-xs font-medium tracking-wider text-ink-2 uppercase">
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-ink-2">No Garmin data yet, sync first</p>
      ) : (
        <table className="mt-2 w-full text-sm tabular-nums">
          <thead className="text-left text-xs text-ink-2">
            <tr>
              <th scope="col" className="py-1.5 font-medium">Condition</th>
              <th scope="col" className="font-medium">Now</th>
              <th scope="col" className="font-medium">28-day</th>
              <th scope="col" className="font-medium"><span className="sr-only">Limit</span></th>
              <th scope="col" className="font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const tone = c.flagged ? SEVERITY_TONE[severity.get(c.key) ?? "caution"] : "text-ink-2";
              return (
                <tr
                  key={c.key}
                  id={`cond-${c.key}`}
                  tabIndex={0}
                  data-active={active === c.key}
                  aria-describedby={severity.has(c.key) ? `reason-${c.key}` : undefined}
                  onMouseEnter={() => onActive(c.key)}
                  onMouseLeave={() => onActive(null)}
                  onFocus={() => onActive(c.key)}
                  onBlur={() => onActive(null)}
                  className={`border-t border-line focus:outline-none focus-visible:ring-2 focus-visible:ring-hold ${active === c.key ? "bg-hold/10" : ""}`}
                >
                  <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-2">{c.label}</th>
                  <td key={`${c.key}:${c.value}`} className={`pr-3 text-base font-medium ${changed.has(c.key) ? "board-flash" : ""}`}>
                    {conditionValue(c)}
                  </td>
                  <td className="pr-3 text-ink-2">{baselineValue(c)}</td>
                  <td className="pr-3"><LimitMarker low={c.band_low} high={c.band_high} value={c.value} /></td>
                  <td data-status className={tone}>{c.status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {readiness && (
        <p className="mt-3 text-xs text-ink-2">
          CTL / ATL / TSB {n(readiness.ctl, 1)} / {n(readiness.atl, 1)} / {n(readiness.tsb, 1)} · battery {readiness.body_battery ?? "no data"}
        </p>
      )}
    </section>
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web run test -- tests/verdict.test.tsx`
Expected: all pass. If `user.tab()` lands elsewhere, the chip is not the first focusable element in the harness: check that nothing focusable precedes it in `VerdictStrip`.

- [ ] **Step 8: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass (the existing strip tests still pass; nothing mounts the board yet).

- [ ] **Step 9: Commit**

```bash
git add web/src/components/board web/tests/verdict.test.tsx
git commit -m "feat(web): verdict strip and conditions table, linked chip to row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Board layout, plan and week, coach panel; retire the strip

**Files:**
- Create: `web/src/components/board/Board.tsx`, `HoldLine.tsx`, `Plan.tsx`, `Week.tsx`, `Section.tsx` (all under `web/src/components/board/`)
- Modify: `web/src/pages/Today.tsx`
- Delete: `web/src/components/today/` (Strip, Card, SessionCard, ReadinessCard, FuelCard, WeekCard)
- Rename and migrate: `web/tests/strip.test.tsx` → `web/tests/board.test.tsx` (spec §5.2)
- Modify: `web/tests/e2e/smoke.spec.ts` (layout assertions move to the board and tabs)

**Interfaces:**
- Consumes: Task 7's `VerdictStrip` and `Conditions`; `Chat`, `Gate`, `useTurnStream`, `useThread`, `useToday`; `ReviewPayload` from `api/queries`.
- Produces:
  - `Board({ today: TodayView | undefined; review: ReviewPayload | null; onHold: () => void })`
  - `HoldLine({ count: number; onGo: () => void })`
  - the Today page, with `#coach-panel` (`<aside aria-label="Coach">`) and a gate wrapper `#review-gate` (`tabIndex=-1`)

- [ ] **Step 1: Migrate the strip tests.** Run `git mv web/tests/strip.test.tsx web/tests/board.test.tsx`. Then:
  - Replace the `Strip` import with `import Board from "../src/components/board/Board";` and every `<Strip today={X} />` with `<Board today={X} review={null} onHold={() => {}} />`.
  - Keep these tests, with their assertions unchanged:
    - `"every card has a sentence for its null state"`: rename it `"every section has a sentence for its null state"`;
    - `"the cards show today's numbers"`: rename it `"the board shows today's numbers"`;
    - `"readiness from an earlier day says which day"`;
    - `"a completed session shows intensity, HR, power and percent of planned"`;
    - `"the week shows sessions done so far, hidden before the first session"`.
  - Delete these tests, whose subject was removed by the spec:
    - `"the strip shows skeletons while loading"`;
    - `"readiness leads with training readiness and falls back to sleep score"`;
    - `"a trend row says how today compares, in words and colour"`;
    - `"the load line names the TSB zone and flags ramp and ACWR"`;
    - `"the readiness card copes with no trends and no load"`;
    - `"skeletons pulse only when motion is allowed"`;
    - `"the headline carries its own vs-28-day-avg context"`;
    - `"a delta that rounds to zero reads as level, not as an arrow"`;
    - `"a ramp that rounds to zero never shows a minus sign"`;
    - `"the readiness card draws no sparklines"`.
  - Append:

```tsx
test("the board shows a loading line before today arrives", () => {
  renderWith(<Board today={undefined} review={null} onHold={() => {}} />);
  expect(screen.getByText("Loading today…")).toBeInTheDocument();
});

test("the HOLD line appears only while a review waits", () => {
  const hold = vi.fn();
  const { unmount } = renderWith(<Board today={todayFull()} review={null} onHold={hold} />);
  expect(screen.queryByText(/HOLD/)).not.toBeInTheDocument();
  unmount();
  renderWith(<Board today={todayFull()} review={{ narration: "n", proposals: [paused().proposals[0]] }} onHold={hold} />);
  screen.getByRole("button", { name: "HOLD · 1 change awaiting your approval" }).click();
  expect(hold).toHaveBeenCalledOnce();
});
```

  Import `paused` from `./fixtures`. Add a Today page test file `web/tests/today.test.tsx`:

```tsx
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Today from "../src/pages/Today";
import { paused, renderWith, threadEmpty, todayFull } from "./fixtures";

function stub(thread = threadEmpty()) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url === "/api/today" ? { ...todayFull(), pending: thread.paused } : url === "/api/coach/thread" ? thread : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
}
afterEach(() => vi.restoreAllMocks());

test("the coach toggle opens the panel and Escape closes it", async () => {
  stub();
  const user = userEvent.setup();
  renderWith(<Today />);
  const toggle = await screen.findByRole("button", { name: "Coach" });
  const panel = screen.getByRole("complementary", { name: "Coach" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(panel).toHaveClass("hidden");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(panel).not.toHaveClass("hidden");
  await user.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("hold opens the coach and focuses the gate", async () => {
  stub({ ...threadEmpty(), paused: paused() });
  const user = userEvent.setup();
  renderWith(<Today />);
  await user.click(await screen.findByRole("button", { name: /HOLD · 1 change awaiting your approval/ }));
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(screen.getByRole("button", { name: /Coach/ })).toHaveAttribute("aria-expanded", "true");
  expect(document.getElementById("review-gate")).toHaveFocus();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/board.test.tsx tests/today.test.tsx`
Expected: FAIL (`Board` and the new Today don't exist yet).

- [ ] **Step 3: Create `web/src/components/board/Section.tsx`**

```tsx
import type { ReactNode } from "react";

export default function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-6 py-5 text-sm">
      <h2 className="text-xs font-medium tracking-wider text-ink-2 uppercase">{title}</h2>
      <div className="mt-2 space-y-1">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-ink-2">{children}</p>;
}
```

- [ ] **Step 4: Create `Plan.tsx` and `Week.tsx`.** These carry over the content of SessionCard, FuelCard and WeekCard, keeping the same text.

`web/src/components/board/Plan.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { day, kcal, n, secsAsHours } from "../../lib/format";
import Section, { Empty } from "./Section";

type Workout = NonNullable<TodayView["session"]>["workouts"][number];

const pct = (actual: number | null, planned: number | null) =>
  actual != null && planned ? Math.round((actual / planned) * 100) : null;

function detail(w: Workout): string[] {
  const effort = [
    w.actual_if != null ? `IF ${w.actual_if.toFixed(2)}` : null,
    w.avg_hr != null ? `${w.avg_hr} bpm` : null,
    w.avg_power != null ? `${w.avg_power} W${w.normalized_power != null ? ` (NP ${w.normalized_power})` : ""}` : null,
  ].filter(Boolean);
  const time = pct(w.actual_duration_sec, w.planned_duration_sec);
  const tss = pct(w.actual_tss, w.planned_tss);
  const vsPlan = [time != null ? `${time}% of planned time` : null, tss != null ? `${tss}% of planned TSS` : null].filter(Boolean);
  return [effort.join(" · "), vsPlan.join(" · ")].filter(Boolean);
}

export default function Plan({ session, fuel }: { session: TodayView["session"]; fuel: TodayView["fuel"] }) {
  const t = fuel.target;
  return (
    <Section title="Today's plan">
      {!session ? (
        <Empty>No session planned</Empty>
      ) : (
        <ul className="space-y-2">
          {session.workouts.map((w, i) => (
            <li key={w.tp_workout_id}>
              <div className={i === 0 ? "text-base font-medium" : "font-medium"}>{w.title || w.sport}</div>
              <div className="text-ink-2 tabular-nums">
                {w.sport} · {secsAsHours(w.completed ? w.actual_duration_sec : w.planned_duration_sec)} · {n(w.completed ? w.actual_tss : w.planned_tss)} TSS
                {w.completed ? " · done" : ""}
              </div>
              {w.completed &&
                detail(w).map((line, j) => (
                  <div key={j} className="text-xs text-ink-2 tabular-nums">
                    {line}
                  </div>
                ))}
            </li>
          ))}
          {session.fuel && (
            <li className="text-xs text-ink-2">
              fuel: {String(session.fuel.payload.carbs_g_per_h ?? "–")} g/h
              {session.fuel.payload.pre ? ` · pre: ${String(session.fuel.payload.pre)}` : ""}
            </li>
          )}
        </ul>
      )}
      <div className="pt-2">
        {!t ? (
          <Empty>No targets yet, ask the coach</Empty>
        ) : (
          <>
            <div className="text-base font-medium tabular-nums">{kcal(t.total_kcal)}</div>
            <div className="text-ink-2 tabular-nums">
              {t.day_type} · {t.carbs_g} C · {t.protein_g} P · {t.fat_g} F · {t.fluid_baseline_ml} ml
            </div>
            <div className="text-xs text-ink-2">targets through {day(fuel.targets_through)}{t.written_to_garmin ? " · on Garmin" : ""}</div>
          </>
        )}
      </div>
    </Section>
  );
}
```

`web/src/components/board/Week.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { hours, n } from "../../lib/format";
import Section, { Empty } from "./Section";

export default function Week({ week }: { week: TodayView["week"] }) {
  if (!week) {
    return (
      <Section title="Week">
        <Empty>No plan; ask the coach to build one</Empty>
      </Section>
    );
  }
  const pct = week.target_hours ? Math.min(100, Math.round((week.actual_hours / week.target_hours) * 100)) : 0;
  return (
    <Section title={`Week · ${week.phase}`}>
      <div className="text-base font-medium tabular-nums">
        {hours(week.actual_hours)} of {hours(week.target_hours)}
      </div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-full max-w-md rounded-full bg-line">
        <div className="h-1.5 rounded-full bg-hold" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-ink-2 tabular-nums">
        {n(week.actual_tss)} of {n(week.target_tss)} TSS
      </div>
      <ul className="space-y-0.5 text-ink-2 tabular-nums">
        {week.sessions.map((s) => (
          <li key={s.sport}>
            {`${s.sport} ${s.completed}/${s.planned} · ${n(s.actual_tss)} of ${n(s.planned_tss)} TSS · ${n(s.actual_hours, 1)} of ${hours(s.planned_hours)}`}
          </li>
        ))}
      </ul>
      {week.planned_to_date > 0 && (
        <div className="text-xs text-ink-2">
          {week.completed_to_date} of {week.planned_to_date} so far
        </div>
      )}
    </Section>
  );
}
```

- [ ] **Step 5: Create `HoldLine.tsx` and `Board.tsx`**

`web/src/components/board/HoldLine.tsx`:

```tsx
export default function HoldLine({ count, onGo }: { count: number; onGo: () => void }) {
  const what = count > 0 ? `${count} change${count === 1 ? "" : "s"}` : "a review";
  return (
    <div className="border-b border-line px-6 py-3">
      <button type="button" onClick={onGo} className="inline-flex min-h-8 items-center rounded-md border border-hold/60 px-3 text-sm font-medium text-hold hover:bg-hold/10">
        HOLD · {what} awaiting your approval
      </button>
    </div>
  );
}
```

`web/src/components/board/Board.tsx`:

```tsx
import { useState } from "react";
import type { ReviewPayload, TodayView } from "../../api/queries";
import Conditions from "./Conditions";
import HoldLine from "./HoldLine";
import Plan from "./Plan";
import VerdictStrip from "./VerdictStrip";
import Week from "./Week";

type Props = { today: TodayView | undefined; review: ReviewPayload | null; onHold: () => void };

export default function Board({ today, review, onHold }: Props) {
  const [active, setActive] = useState<string | null>(null);
  if (!today) return <p role="status" className="px-6 py-6 text-sm text-ink-2">Loading today…</p>;
  return (
    <div className="mx-auto w-full max-w-5xl pb-10">
      <VerdictStrip verdict={today.verdict} active={active} onActive={setActive} />
      {review && <HoldLine count={review.proposals.length} onGo={onHold} />}
      <Conditions readiness={today.readiness} rows={today.conditions} reasons={today.verdict.reasons} active={active} onActive={setActive} />
      <Plan session={today.session} fuel={today.fuel} />
      <Week week={today.week} />
    </div>
  );
}
```

- [ ] **Step 6: Rewrite `web/src/pages/Today.tsx`**

```tsx
import { useEffect, useState } from "react";
import Board from "../components/board/Board";
import Chat from "../components/chat/Chat";
import Gate from "../components/gate/Gate";
import { useTurnStream } from "../components/chat/useTurnStream";
import { useThread, useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  const stream = useTurnStream();
  // The turn-stream hook is the single poller while busy (it invalidates ["thread"] every
  // 2 s); this query just reads whatever that invalidation last put in the cache.
  const thread = useThread();
  const [coachOpen, setCoachOpen] = useState(false);
  const paused = stream.state.interrupt ?? thread.data?.paused ?? null;
  const held = !paused ? (thread.data?.held ?? null) : null;
  const review = paused ?? held ?? today.data?.pending ?? null;
  const gateBody = paused ? (
    <Gate payload={paused} mode="paused" onDecide={stream.resume} disabled={stream.state.status !== "idle"} />
  ) : held ? (
    <Gate payload={held} mode="held" onDecide={stream.resume} />
  ) : null;
  const gate = gateBody && (
    <div id="review-gate" tabIndex={-1} className="focus:outline-none">
      {gateBody}
    </div>
  );

  useEffect(() => {
    if (!coachOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCoachOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [coachOpen]);

  const toHold = () => {
    setCoachOpen(true);
    window.setTimeout(() => document.getElementById("review-gate")?.focus(), 0);
  };

  return (
    // From xl the board and the coach sit side by side and each scrolls on its own; below xl
    // the coach opens over the board from the Coach toggle (kept mounted so a stream survives).
    <div className="flex min-h-0 flex-1">
      <div className={`min-w-0 flex-1 overflow-y-auto ${coachOpen ? "hidden xl:block" : ""}`}>
        <div className="flex justify-end px-6 pt-4 xl:hidden">
          <button
            type="button"
            aria-expanded={coachOpen}
            aria-controls="coach-panel"
            onClick={() => setCoachOpen(true)}
            className="inline-flex min-h-8 items-center rounded-md border border-line px-3 text-sm"
          >
            Coach{review ? " · hold" : ""}
          </button>
        </div>
        <Board today={today.data} review={review} onHold={toHold} />
      </div>
      <aside
        id="coach-panel"
        aria-label="Coach"
        className={`${coachOpen ? "flex" : "hidden"} min-h-0 w-full flex-col bg-surface-2 xl:flex xl:w-[32rem] xl:shrink-0 xl:border-l xl:border-line`}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2 xl:hidden">
          <span className="text-xs font-medium tracking-wider text-ink-2 uppercase">Coach</span>
          <button type="button" onClick={() => setCoachOpen(false)} className="inline-flex min-h-8 items-center rounded-md border border-line px-3 text-sm">
            Back to board
          </button>
        </div>
        <Chat thread={thread.data} stream={stream} gate={gate} paused={paused != null} />
      </aside>
    </div>
  );
}
```

Note: the toggle's accessible name is "Coach" with no review, and "Coach · hold" with one. The first test expects exactly "Coach"; the second uses `/Coach/`.

- [ ] **Step 7: Delete the strip components**

Run: `git rm -r web/src/components/today`, then `rg "components/today" web/src web/tests`. Expected: no matches.

- [ ] **Step 8: Update the e2e smoke test** (`web/tests/e2e/smoke.spec.ts`).

In the first test, replace the block from `// from md the cards stack…` through the `chat-messages` bounding-box assertion with:

```ts
  await expect(page.getByRole("region", { name: "Today's call" })).toBeVisible();
  await expect(page.getByText("NO CALL")).toBeVisible();
  // at 1200 px the coach opens over the board from the Coach toggle
  await page.getByRole("button", { name: "Coach" }).click();
```

In the phone test, replace the lines from `const avatar = …` through the `Escape` / `Settings toBeHidden` assertion with:

```ts
  await expect(page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sync now" })).toBeVisible();
```

Replace the `// the strip stacks…` block (the `cards` count and box loop) with:

```ts
  await expect(page.getByRole("region", { name: "Today's call" })).toBeVisible();
  await page.getByRole("button", { name: "Coach" }).click();
```

Keep the overflow check and everything after it. Remove the `await expect(page.getByLabel("Message")).toBeVisible();` line that followed the menu steps, since the chat is now behind the Coach toggle; it is asserted again after the toggle by the send flow. Playwright can't run in this environment (browsers not installed), so Brian runs `npm --prefix web run test:e2e`.

- [ ] **Step 9: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add -A web/src web/tests
git commit -m "feat(web): Today is the preflight board with the coach docked; the card strip retires

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Settings and placeholders in the board world

**Files:**
- Modify: `web/src/pages/Settings.tsx`, `web/src/pages/Placeholder.tsx`
- Test: `web/tests/settings.test.tsx` and `web/tests/shell.test.tsx` (unchanged; they must still pass)

**Interfaces:**
- Consumes: `Section` from Task 8 (`components/board/Section`).

- [ ] **Step 1: Rewrite `Settings.tsx`**

```tsx
import MemoryTable from "../components/settings/MemoryTable";
import ResetButton from "../components/settings/ResetButton";
import Readiness from "../components/settings/Readiness";
import Section from "../components/board/Section";

export default function Settings() {
  return (
    <div className="mx-auto w-full max-w-4xl pb-10">
      <h1 className="px-6 pt-6 text-sm font-semibold tracking-wide uppercase">Settings</h1>
      <Section title="Coach memory"><MemoryTable /></Section>
      <Section title="Reset"><ResetButton /></Section>
      <Section title="Readiness"><Readiness /></Section>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `Placeholder.tsx`** (keep the props and the "Coming soon" copy):

```tsx
const blurbs = {
  2: "your fitness curve, weekly load by sport and recovery trends",
  3: "daily targets, fuel plans and the fuel log",
  4: "lab panels, reports and PDF upload",
};

export default function Placeholder({ name, subProject }: { name: string; subProject: 2 | 3 | 4 }) {
  return (
    <section className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-sm font-semibold tracking-wide uppercase">{name}</h1>
      <p className="mt-3 border-t border-line pt-3 text-sm text-ink-2">Coming soon: {blurbs[subProject]}.</p>
    </section>
  );
}
```

- [ ] **Step 3: Run the web checks**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass. The settings tests query by button names, labels and texts, which are unchanged. If one queried the old `h1` text "Coach memory" by role `heading` level 1, it is now an `h2`; in that case update only the level and note it in the report.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Settings.tsx web/src/pages/Placeholder.tsx
git commit -m "style(web): Settings and placeholders as ruled board sections

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Impeccable finish and definition of done (controller, with Brian)

**Files:** `.impeccable/review/*` (screenshots), `DESIGN.md` and `.impeccable/design.json` (documenter).

- [ ] **Step 1: Full checks**

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build
```

Expected: all green.

- [ ] **Step 2: One screenshot round.** Brian runs `uv run tri-web serve --no-live`. Capture into `.impeccable/review/`: `desktop.png` (1440 wide, full page), `mobile.png` (390 wide), and the same two in light mode (`desktop-light.png`, `mobile-light.png`). Capture with Claude in Chrome if Brian approves the site permission, or Brian captures them and drops them in. Before sending, open each file and confirm it isn't blank or half-loaded.

- [ ] **Step 3: Detector, once.** Run `"/Users/brian/.claude/plugins/cache/impeccable/impeccable/4.4.0/skills/impeccable/scripts/impeccable" detect --json web/src/components/board web/src/components/shell web/src/pages web/src/index.css`. Fix what is mechanical in one batch; pass the rest to the reviewer.

- [ ] **Step 4: Finish review.** Spawn `impeccable:impeccable-finish-reviewer` fresh, with:
  - the original request and Brian's confirmed answers (from the spec §1);
  - the artifact paths;
  - the screenshot paths;
  - the direction contract (the Today surface brief);
  - the detector findings;
  - the craft-floor reference path `/Users/brian/.claude/plugins/cache/impeccable/impeccable/4.4.0/skills/impeccable/reference/craft-floor.md`;
  - the QUALITY BAR note: this is a code-led build with no comp.

  Act on its disposition: recapture, rebuild, ship or fix. For fix, the budget is one batch, a recapture, and a verdict pass.

- [ ] **Step 5: Documenter.** Spawn `impeccable:impeccable-documenter` with the project root, artifact paths, direction contract, `PRODUCT.md` and `reference/document.md`. Verify that `DESIGN.md` and `.impeccable/design.json` exist with tokens.

- [ ] **Step 6: Brian's look** in the browser at his own width, in both themes, with a real synced day. Record the result, then use superpowers:finishing-a-development-branch.
