"""The morning call, go / easy / rest, from the athlete's own numbers against his own baseline,
and the condition rows the board shows beside it. Pure: build_today hands it the readiness
view and today's workouts. Every threshold lives here or in metrics.py, never in the web app."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from tri_web.metrics import ACWR_HIGH, ACWR_LOW, RAMP_CAUTION

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
        out.append(
            ReasonOut(
                key="hrv",
                severity="stop",
                text=f"HRV {hrv.now:.0f} ms low and RHR {rhr.now:.0f} bpm high together",
            )
        )
    else:
        if hrv_low:
            assert hrv is not None
            out.append(
                ReasonOut(
                    key="hrv",
                    severity="caution",
                    text=f"HRV {hrv.now:.0f} ms, below your band{_band(r, 'hrv')}",
                )
            )
        if rhr_high:
            assert rhr is not None
            out.append(
                ReasonOut(
                    key="resting_hr",
                    severity="caution",
                    text=f"RHR {rhr.now:.0f} bpm, above your band{_band(r, 'resting_hr')}",
                )
            )
    if r.sleep_score is not None and r.sleep_score < SLEEP_CAUTION:
        out.append(
            ReasonOut(
                key="sleep_score",
                severity="caution",
                text=f"Sleep score {r.sleep_score}, under {SLEEP_CAUTION}",
            )
        )
    tr = r.training_readiness
    if tr is not None and tr < READINESS_STOP:
        out.append(
            ReasonOut(
                key="training_readiness",
                severity="stop",
                text=f"Readiness {tr}, under {READINESS_STOP}",
            )
        )
    elif tr is not None and tr < READINESS_CAUTION:
        out.append(
            ReasonOut(
                key="training_readiness",
                severity="caution",
                text=f"Readiness {tr}, under {READINESS_CAUTION}",
            )
        )
    if r.tsb_zone == "overreaching" and r.tsb is not None:
        out.append(ReasonOut(key="tsb", severity="stop", text=f"Form {r.tsb:.1f}, overreaching"))
    if acwr_counts(r):
        assert r.acwr is not None
        if r.acwr > ACWR_STOP:
            out.append(
                ReasonOut(key="acwr", severity="stop", text=f"ACWR {r.acwr:.2f}, over {ACWR_STOP}")
            )
        elif r.acwr > ACWR_HIGH:
            out.append(
                ReasonOut(
                    key="acwr", severity="caution", text=f"ACWR {r.acwr:.2f}, over {ACWR_HIGH}"
                )
            )
    if r.ramp_caution and r.ramp_7d is not None:
        out.append(
            ReasonOut(key="ramp", severity="caution", text=f"Ramp +{r.ramp_7d:.1f} CTL/wk, fast")
        )
    return sorted(out, key=lambda f: f.severity != "stop")  # stable: table order within each group


def _hard(w: dict[str, Any]) -> bool:
    if w.get("planned_if") is not None:
        return float(w["planned_if"]) >= HARD_IF
    tss, secs = w.get("planned_tss"), w.get("planned_duration_sec")
    if tss is None or not secs:
        return False
    return float(tss) / (float(secs) / 3600) >= HARD_TSS_PER_H


def verdict(r: ReadinessOut | None, todays: list[dict[str, Any]], today: date) -> VerdictOut:
    done = bool(todays) and all(bool(w["completed"]) for w in todays)
    if r is None:
        reason = ReasonOut(
            key="training_readiness", text="No Garmin data, sync first", severity="info"
        )
        return VerdictOut(
            call="none",
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
            call="none",
            reasons=[reason],
            based_on=r.date,
            stale=True,
            harder_than_call=False,
            session_done=done,
        )
    found = flags(r)
    stops = any(f.severity == "stop" for f in found)
    c: Call = "rest" if stops or len(found) >= 3 else "easy" if found else "go"
    harder = c in ("easy", "rest") and any(not w["completed"] and _hard(w) for w in todays)
    return VerdictOut(
        call=c,
        reasons=found,
        based_on=r.date,
        stale=age >= STALE_DAYS,
        harder_than_call=harder,
        session_done=done,
    )


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
    spark: list[float | None]  # recent history, oldest first; empty where the server has none


def _raw(r: ReadinessOut, key: str) -> float | None:
    v = {
        "training_readiness": r.training_readiness,
        "hrv": r.hrv,
        "resting_hr": r.resting_hr,
        "sleep_score": r.sleep_score,
        "sleep_hours": r.sleep_hours,
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
        out.append(
            ConditionOut(
                key=key,
                label=label,
                value=value,
                unit=unit,
                baseline=t.avg_28d if t is not None else None,
                band_low=lo,
                band_high=hi,
                status=status,
                flagged=key in flagged,
                spark=list(t.spark) if t is not None else [],
            )
        )
    out.append(
        ConditionOut(
            key="tsb",
            label="Form (TSB)",
            value=r.tsb,
            unit="",
            baseline=None,
            band_low=TSB_BAND[0],
            band_high=TSB_BAND[1],
            status="no data" if r.tsb is None else (r.tsb_zone or "no data"),
            flagged="tsb" in flagged,
            spark=[],
        )
    )
    if r.acwr is None:
        acwr_status = "no data"
    elif not acwr_counts(r):
        acwr_status = f"ignored: CTL under {ACWR_MIN_CTL}"
    else:
        acwr_status = "high" if r.acwr > ACWR_HIGH else "low" if r.acwr < ACWR_LOW else "within"
    out.append(
        ConditionOut(
            key="acwr",
            label="ACWR",
            value=r.acwr,
            unit="",
            baseline=None,
            band_low=ACWR_LOW,
            band_high=ACWR_HIGH,
            status=acwr_status,
            flagged="acwr" in flagged,
            spark=[],
        )
    )
    out.append(
        ConditionOut(
            key="ramp",
            label="Ramp",
            value=r.ramp_7d,
            unit="/wk",
            baseline=None,
            band_low=None,
            band_high=RAMP_CAUTION,
            status="no data" if r.ramp_7d is None else ("fast" if r.ramp_caution else "within"),
            flagged="ramp" in flagged,
            spark=[],
        )
    )
    return out
