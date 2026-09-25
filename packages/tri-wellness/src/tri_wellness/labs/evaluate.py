"""LabResults plus contexts to Findings. Pure: no I/O, no model.

Every threshold from the spec's confounder table is a constant here and nowhere else.
"""

from __future__ import annotations

import math
from datetime import time
from typing import Any, get_args

from tri_wellness.labs.models import (
    Bound,
    Confounder,
    ConventionalStatus,
    Finding,
    FunctionalStatus,
    LabResult,
    PanelContext,
    PreviousValue,
    TrainingContext,
)
from tri_wellness.labs.normalize import bound_step
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

HARD_SESSION_TSS = 150.0  # a session above this in the 72 h before the draw
HARD_SESSION_MIN = 120  # or longer than this
ACUTE_LOAD_ATL_OVER_CTL = 15.0  # ATL exceeds CTL by more than this on the draw day
POOR_SLEEP_DEFICIT_SEC = 3600  # two-night mean more than 60 min under the 30-day mean
LOW_HRV_FRACTION = 0.10  # two-night mean more than 10 % under the 30-day mean
AFTERNOON_DRAW_AFTER = time(10, 0)  # draws after this are 'afternoon' for cortisol/testosterone
INFLAMMATION_MARKER = "hs_crp"  # above its functional high fires 'inflammation'

CONFOUNDER_ORDER: tuple[Confounder, ...] = get_args(Confounder)


def conventional_status(
    value: float, lab_low: float | None, lab_high: float | None, spec: MarkerSpec
) -> ConventionalStatus:
    """The lab's printed range when it printed one (either side), else the table's."""
    if lab_low is None and lab_high is None:
        lab_low, lab_high = spec.conventional.low, spec.conventional.high
    if lab_low is not None and value < lab_low:
        return "low"
    if lab_high is not None and value > lab_high:
        return "high"
    return "in_range"


def functional_status(value: float, spec: MarkerSpec) -> FunctionalStatus:
    """Table ranges only. `direction` collapses the irrelevant side to optimal."""
    c, f = spec.conventional, spec.functional
    if spec.direction in ("low", "both"):
        if c.low is not None and value < c.low:
            return "low"
        if f.low is not None and value < f.low:
            return "suboptimal_low"
    if spec.direction in ("high", "both"):
        if c.high is not None and value > c.high:
            return "high"
        if f.high is not None and value > f.high:
            return "suboptimal_high"
    return "optimal"


def _is_hard(session: dict[str, Any]) -> bool:
    tss = session.get("tss")
    minutes = session.get("duration_min")
    return (tss is not None and float(tss) > HARD_SESSION_TSS) or (
        minutes is not None and float(minutes) > HARD_SESSION_MIN
    )


def active_confounders(
    results: list[LabResult],
    registry: MarkerRegistry,
    context: PanelContext,
    training: TrainingContext,
) -> list[Confounder]:
    """Panel-level confounders, in Confounder declaration order. A rule whose inputs are missing
    does not fire."""
    fired: set[Confounder] = set()
    if any(_is_hard(s) for s in training.last_sessions):
        fired.add("recent_hard_session")
    if (
        training.atl is not None
        and training.ctl is not None
        and training.atl - training.ctl > ACUTE_LOAD_ATL_OVER_CTL
    ):
        fired.add("high_acute_load")
    if (
        training.sleep_2n_avg_sec is not None
        and training.sleep_30d_avg_sec is not None
        and training.sleep_30d_avg_sec - training.sleep_2n_avg_sec > POOR_SLEEP_DEFICIT_SEC
    ):
        fired.add("poor_sleep")
    if (
        training.hrv_2n_avg is not None
        and training.hrv_30d_avg is not None
        and training.hrv_2n_avg < training.hrv_30d_avg * (1 - LOW_HRV_FRACTION)
    ):
        fired.add("low_hrv")
    if context.fasting is False:
        fired.add("not_fasting")
    if context.draw_time is not None and context.draw_time > AFTERNOON_DRAW_AFTER:
        fired.add("afternoon_draw")
    crp = next((r for r in results if r.marker == INFLAMMATION_MARKER), None)
    if crp is not None and INFLAMMATION_MARKER in registry.markers:
        high = registry.get(INFLAMMATION_MARKER).functional.high
        if high is not None and crp.value > high:
            fired.add("inflammation")
    return [c for c in CONFOUNDER_ORDER if c in fired]


def _ends(value: float, bound: Bound | None, step: float) -> tuple[float, float]:
    """The lowest and highest value a result can stand for: `<x` is [0, x), `>x` is (x, inf),
    with the open end one printed unit (`step`) inside the bound. A plain value is its own ends."""
    if bound is None:
        return value, value
    if bound == "<":
        return 0.0, max(0.0, value - step)
    if bound == "<=":
        return 0.0, value
    if bound == ">":
        return value + step, math.inf
    return value, math.inf


def bounded_conventional_status(
    value: float,
    bound: Bound | None,
    step: float,
    lab_low: float | None,
    lab_high: float | None,
    spec: MarkerSpec,
) -> ConventionalStatus:
    """`conventional_status` at both ends of the interval when they agree, else indeterminate."""
    lo, hi = _ends(value, bound, step)
    at_lo = conventional_status(lo, lab_low, lab_high, spec)
    at_hi = conventional_status(hi, lab_low, lab_high, spec)
    return at_lo if at_lo == at_hi else "indeterminate"


def bounded_functional_status(
    value: float, bound: Bound | None, step: float, spec: MarkerSpec
) -> FunctionalStatus:
    """`functional_status` at both ends of the interval when they agree, else indeterminate."""
    lo, hi = _ends(value, bound, step)
    at_lo, at_hi = functional_status(lo, spec), functional_status(hi, spec)
    return at_lo if at_lo == at_hi else "indeterminate"


def _delta_pct(value: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)


def _functional_range(spec: MarkerSpec) -> tuple[float | None, float | None]:
    """Collapse the side `functional_status` ignores, so the reported range matches direction."""
    if spec.direction == "low":
        return (spec.functional.low, None)
    if spec.direction == "high":
        return (None, spec.functional.high)
    return (spec.functional.low, spec.functional.high)


def evaluate(
    results: list[LabResult],
    registry: MarkerRegistry,
    previous: dict[str, PreviousValue],
    context: PanelContext,
    training: TrainingContext,
) -> list[Finding]:
    panel_active = active_confounders(results, registry, context, training)
    findings: list[Finding] = []
    for r in results:
        spec = registry.get(r.marker)
        prev = previous.get(r.marker)
        step = bound_step(r.raw.value, r.value) if r.bound else 0.0
        any_bounded = r.bound is not None or (prev is not None and prev[2] is not None)
        findings.append(
            Finding(
                marker=r.marker,
                display=spec.display,
                system=spec.system,
                value=r.value,
                unit=r.unit,
                bound=r.bound,
                raw_value=r.raw.value.strip(),
                conventional_status=bounded_conventional_status(
                    r.value, r.bound, step, r.lab_ref_low, r.lab_ref_high, spec
                ),
                functional_status=bounded_functional_status(r.value, r.bound, step, spec),
                functional_range=_functional_range(spec),
                previous=(prev[0], prev[1]) if prev else None,
                delta_pct=None if any_bounded else _delta_pct(r.value, prev[1] if prev else None),
                active_confounders=[c for c in spec.confounders if c in panel_active],
                athlete_note=spec.athlete_note,
            )
        )
    return findings
