"""The findings sets behind the LangSmith dataset, stored as LabResult inputs so they stay valid
when markers.yaml changes: the target evaluates them with the current registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DRAWN = "2026-08-20"
PROFILE: dict[str, Any] = {"ftp_watts": 260, "weight_kg": 74.5, "lthr_bpm": 165}
FASTED_AM: dict[str, Any] = {
    "fasting": True,
    "draw_time": "07:30:00",
    "supplements": [],
    "symptoms": [],
}


def result(marker: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "marker": marker,
        "value": value,
        "unit": unit,
        "raw": {"name": marker, "value": str(value), "unit": unit},
    }


def training(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "drawn_on": DRAWN,
        "ctl": 60.0,
        "atl": 62.0,
        "tsb": -2.0,
        "tss_7d": 380.0,
        "last_sessions": [],
        "sleep_2n_avg_sec": 27000,
        "sleep_30d_avg_sec": 27000,
        "hrv_2n_avg": 60,
        "hrv_30d_avg": 60,
    }
    base.update(over)
    return base


LONG_RIDE = {
    "date": "2026-08-19",
    "sport": "bike",
    "duration_min": 180,
    "tss": 210,
    "title": "long ride",
}


@dataclass(frozen=True)
class EvalCase:
    name: str
    results: list[dict[str, Any]]
    context: dict[str, Any]
    training: dict[str, Any]
    previous: dict[str, list[Any]] = field(default_factory=dict)  # marker -> [date, value]
    profile: dict[str, Any] | None = None

    def inputs(self) -> dict[str, Any]:
        return {
            "results": self.results,
            "context": self.context,
            "training": self.training,
            "previous": self.previous,
            "profile": self.profile,
        }


CASES: list[EvalCase] = [
    EvalCase(
        name="iron_after_long_ride",
        results=[
            result("ferritin", 42.0, "ng/mL"),
            result("hs_crp", 1.8, "mg/L"),
            result("hemoglobin", 15.1, "g/dL"),
            result("tsh", 1.5, "mIU/L"),
        ],
        context=FASTED_AM,
        training=training(last_sessions=[LONG_RIDE]),
        previous={"ferritin": ["2026-03-01", 35.0]},
        profile=PROFILE,
    ),
    EvalCase(
        name="overreaching_hormones",
        results=[
            result("testosterone_total", 480.0, "ng/dL"),
            result("cortisol_am", 19.0, "ug/dL"),
            result("free_t3", 2.8, "pg/mL"),
            result("reverse_t3", 19.0, "ng/dL"),
            result("tsh", 2.4, "mIU/L"),
            result("ferritin", 80.0, "ng/mL"),
        ],
        context={**FASTED_AM, "symptoms": ["flat legs", "poor sleep"]},
        training=training(
            ctl=70.0, atl=92.0, tsb=-22.0, tss_7d=640.0, sleep_2n_avg_sec=21000, hrv_2n_avg=48
        ),
        previous={"testosterone_total": ["2026-03-01", 610.0], "free_t3": ["2026-03-01", 3.4]},
        profile=PROFILE,
    ),
    EvalCase(
        name="all_optimal",
        results=[
            result("ferritin", 90.0, "ng/mL"),
            result("hs_crp", 0.4, "mg/L"),
            result("vitamin_d", 62.0, "ng/mL"),
            result("hba1c", 5.1, "%"),
        ],
        context=FASTED_AM,
        training=training(),
        previous={"ferritin": ["2026-03-01", 70.0]},
        profile=PROFILE,
    ),
    EvalCase(
        name="lipids_metabolic_first_panel",
        results=[
            result("ldl", 128.0, "mg/dL"),
            result("apob", 96.0, "mg/dL"),
            result("triglycerides", 140.0, "mg/dL"),
            result("insulin", 7.5, "uIU/mL"),
            result("glucose", 94.0, "mg/dL"),
            result("hdl", 58.0, "mg/dL"),
        ],
        context={"fasting": False, "draw_time": "13:15:00", "supplements": [], "symptoms": []},
        training=training(),
        profile=None,
    ),
]
