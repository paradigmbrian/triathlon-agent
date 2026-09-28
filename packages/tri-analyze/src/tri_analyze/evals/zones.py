"""TrainingPeaks-shaped zone groups built from the eval athlete's thresholds, so the analyst's
context (cases.PROFILE) and the seeded athlete_profile row carry the same zones. Power and HR
bounds are integer: zone n ends at floor(threshold x cut / 100) and the next starts 1 above.
Speed bounds are m/s; zone 1 starts at 0 and the last ends at 10x its start (TrainingPeaks'
open top)."""

from __future__ import annotations

from typing import Any

_SWIM, _BIKE, _RUN = 1, 2, 3
_COGGAN = (
    "Zone 1: Active Recovery",
    "Zone 2: Endurance",
    "Zone 3: Tempo",
    "Zone 4: Threshold",
    "Zone 5: VO2 Max",
    "Zone 6: Anaerobic",
)
_FRIEL = (
    "Zone 1: Recovery",
    "Zone 2: Aerobic",
    "Zone 3: Tempo",
    "Zone 4: SubThreshold",
    "Zone 5A: SuperThreshold",
    "Zone 5B: Aerobic Capacity",
)


def _cut(threshold: int, cuts: tuple[int, ...], labels: tuple[str, ...], top: int) -> list[Any]:
    ends = [threshold * c // 100 for c in cuts]
    lows, highs = [0, *(e + 1 for e in ends)], [*ends, top]
    return [
        {"label": label, "minimum": lo, "maximum": hi}
        for label, lo, hi in zip(labels, lows, highs, strict=True)
    ]


def _speed(metres: int, bounds_sec: list[float]) -> list[Any]:
    """`bounds_sec`: pace cut-offs in seconds per `metres`, slowest first."""
    speeds = [metres / s for s in bounds_sec]
    lows, highs = [0.0, *speeds], [*speeds, speeds[-1] * 10]
    return [
        {"label": f"Zone {n}", "minimum": lo, "maximum": hi}
        for n, (lo, hi) in enumerate(zip(lows, highs, strict=True), 1)
    ]


def power_zones(ftp: int) -> list[dict[str, Any]]:
    """Coggan: cut-offs at 55/75/90/105/120% of FTP."""
    return [
        {
            "workoutTypeId": _BIKE,
            "threshold": ftp,
            "zones": _cut(ftp, (55, 75, 90, 105, 120), _COGGAN, 2000),
        }
    ]


def hr_zones(lthr: int, max_hr: int) -> list[dict[str, Any]]:
    """Friel run: cut-offs at 85/89/94/100/103% of LTHR."""
    return [
        {
            "workoutTypeId": _RUN,
            "threshold": lthr,
            "maximumHeartRate": max_hr,
            "zones": _cut(lthr, (85, 89, 94, 100, 103), _FRIEL, max_hr),
        }
    ]


def pace_zones(run_sec_per_km: int, css_sec_per_100m: int) -> list[dict[str, Any]]:
    """Run: cut-offs at 129/114/106/100/97% of threshold time. Swim: CSS +15/+10/+5/-5 s."""
    run = [run_sec_per_km * c / 100 for c in (129, 114, 106, 100, 97)]
    swim = [float(css_sec_per_100m + d) for d in (15, 10, 5, -5)]
    return [
        {"workoutTypeId": _RUN, "threshold": 1000 / run_sec_per_km, "zones": _speed(1000, run)},
        {"workoutTypeId": _SWIM, "threshold": 100 / css_sec_per_100m, "zones": _speed(100, swim)},
    ]
