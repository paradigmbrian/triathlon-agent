"""Ingest graph state. Every key is last-write-wins; there is no conversation."""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from tri_wellness.labs.models import IngestKind, LabResult, PanelContext, RawResult, Unmapped


class IngestState(TypedDict, total=False):
    source_path: str
    source_kind: IngestKind
    drawn_on_hint: date | None
    page_count: int | None
    raw_results: list[RawResult]
    drawn_on: date | None
    lab_name: str | None
    results: list[LabResult]
    unmapped: list[Unmapped]
    context: PanelContext | None
    decision: Literal["approve", "reject"] | None
    panel_id: int | None
    last_error: str | None
