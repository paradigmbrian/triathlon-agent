"""Lab vocabulary shared by the registry, normalize, evaluate, repository, graph and tools."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field

ConventionalStatus = Literal["low", "in_range", "high"]
FunctionalStatus = Literal["low", "suboptimal_low", "optimal", "suboptimal_high", "high"]
Confounder = Literal[
    "recent_hard_session",
    "high_acute_load",
    "poor_sleep",
    "low_hrv",
    "not_fasting",
    "afternoon_draw",
    "inflammation",
]
SourceKind = Literal["pdf", "export", "manual"]


class RawResult(BaseModel):
    """One row as extraction returned it. Verbatim strings; no interpretation."""

    name: str
    value: str
    unit: str | None = None
    ref_low: str | None = None
    ref_high: str | None = None
    flag: str | None = None
    page: int | None = None


class LabResult(BaseModel):
    """A RawResult mapped to a canonical marker and unit."""

    marker: str
    value: float
    unit: str
    raw: RawResult
    lab_ref_low: float | None = None
    lab_ref_high: float | None = None
    note: str | None = None


class PanelContext(BaseModel):
    """What the athlete tells us about the draw. Collected at review."""

    fasting: bool | None = None
    draw_time: time | None = None
    supplements: list[str] = Field(default_factory=list)
    diet_pattern: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    notes: str | None = None


class TrainingContext(BaseModel):
    """Load, sleep and HRV around the draw date, read from workouts and daily_metrics."""

    drawn_on: date
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    tss_7d: float | None = None
    last_sessions: list[dict[str, Any]] = Field(default_factory=list)
    sleep_2n_avg_sec: int | None = None
    sleep_30d_avg_sec: int | None = None
    hrv_2n_avg: int | None = None
    hrv_30d_avg: int | None = None


class Finding(BaseModel):
    """evaluate's output: one per LabResult, everything the report needs about a marker."""

    marker: str
    display: str
    system: str
    value: float
    unit: str
    conventional_status: ConventionalStatus
    functional_status: FunctionalStatus
    functional_range: tuple[float | None, float | None]
    previous: tuple[date, float] | None = None
    delta_pct: float | None = None
    active_confounders: list[Confounder] = Field(default_factory=list)
    athlete_note: str = ""


UnmappedReason = Literal["name", "unit", "value", "duplicate"]


class Unmapped(BaseModel):
    """A raw row normalize could not turn into a LabResult, and why."""

    raw: RawResult
    reason: UnmappedReason
    marker: str | None = None  # set when the name mapped but the unit or value did not


class NormalizeResult(BaseModel):
    """normalize's output. `results` are storable; `unmapped` rows need review."""

    results: list[LabResult] = Field(default_factory=list)
    unmapped: list[Unmapped] = Field(default_factory=list)


class StoredPanel(BaseModel):
    id: int
    drawn_on: date
    lab_name: str | None
    source_file: str | None
    source_kind: SourceKind
    context: PanelContext
    raw_extract: list[RawResult]
    created_at: datetime


class StoredResult(BaseModel):
    panel_id: int
    marker: str
    value: float
    unit: str
    raw_name: str
    raw_value: str
    raw_unit: str | None
    lab_ref_low: float | None
    lab_ref_high: float | None
    flag: str | None


class StoredReport(BaseModel):
    id: int
    panel_id: int
    ranges_version: str
    findings: list[Finding]
    report_md: str
    created_at: datetime


class PanelSummary(BaseModel):
    """One line of `tri-wellness panels`."""

    id: int
    drawn_on: date
    lab_name: str | None
    result_count: int
    unmapped_count: int
    has_report: bool
