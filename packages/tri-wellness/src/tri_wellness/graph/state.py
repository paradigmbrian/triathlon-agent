"""Ingest graph state. Every key is last-write-wins; there is no conversation."""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from tri_wellness.labs.models import IngestKind, LabResult, PanelContext, RawResult, Unmapped

# Pydantic models that live in IngestState. Registering them with the checkpointer's serializer
# keeps it from warning (and, in strict mode, refusing) when it loads them. Ingest threads are
# keyed `ingest:<sha256>`.
STATE_TYPES: tuple[type, ...] = (RawResult, LabResult, Unmapped, PanelContext)


class IngestState(TypedDict, total=False):
    source_path: str
    source_kind: IngestKind
    source_sha: str | None  # sha256 of the file; set by extract, checked at review, stored
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
