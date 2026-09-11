"""Structured exports: deterministic parsers keyed by detected format, model fallback.

One format ships: `generic_csv`, a CSV with a name column and a value column. When Brian
provides a real Function Health export, add a parser keyed on its header next to it.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from tri_wellness.labs.extract.structured import extract_structured
from tri_wellness.labs.models import ExtractedPanel, RawResult
from tri_wellness.prompts.extract import render_extract_prompt

NAME_COLS = ("name", "marker", "test", "biomarker", "analyte", "test name")
VALUE_COLS = ("value", "result")
UNIT_COLS = ("unit", "units")
LOW_COLS = ("ref_low", "reference low", "low", "range low", "ref low")
HIGH_COLS = ("ref_high", "reference high", "high", "range high", "ref high")
FLAG_COLS = ("flag", "abnormal")
DATE_COLS = ("drawn_on", "collected", "collection date", "collection_date", "date")
LAB_COLS = ("lab", "lab_name", "laboratory")
MAX_FALLBACK_CHARS = 200_000


def _norm(h: str) -> str:
    return h.strip().lower()


def _col(header: list[str], candidates: tuple[str, ...]) -> str | None:
    by_norm = {_norm(h): h for h in header}
    return next((by_norm[c] for c in candidates if c in by_norm), None)


def _read_header(path: Path) -> list[str] | None:
    if path.suffix.lower() not in (".csv", ".tsv"):
        return None
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
        return next(reader, None)


def detect_format(path: Path) -> str | None:
    header = _read_header(path)
    if header and _col(header, NAME_COLS) and _col(header, VALUE_COLS):
        return "generic_csv"
    return None


def _cell(row: dict[str, str], col: str | None) -> str | None:
    if col is None:
        return None
    v = row.get(col, "").strip()
    return v or None


def parse_generic_csv(text: str, delimiter: str = ",") -> ExtractedPanel:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = list(reader.fieldnames or [])
    name, value = _col(header, NAME_COLS), _col(header, VALUE_COLS)
    assert name is not None and value is not None
    unit, low, high = _col(header, UNIT_COLS), _col(header, LOW_COLS), _col(header, HIGH_COLS)
    flag, dcol, lcol = _col(header, FLAG_COLS), _col(header, DATE_COLS), _col(header, LAB_COLS)
    results: list[RawResult] = []
    drawn_on: date | None = None
    lab_name: str | None = None
    for row in reader:
        n, v = _cell(row, name), _cell(row, value)
        if not n or not v:
            continue
        results.append(
            RawResult(
                name=n,
                value=v,
                unit=_cell(row, unit),
                ref_low=_cell(row, low),
                ref_high=_cell(row, high),
                flag=_cell(row, flag),
            )
        )
        if drawn_on is None and (d := _cell(row, dcol)):
            try:
                drawn_on = date.fromisoformat(d[:10])
            except ValueError:
                drawn_on = None
        if lab_name is None:
            lab_name = _cell(row, lcol)
    return ExtractedPanel(drawn_on=drawn_on, lab_name=lab_name, results=results)


def parse_export(path: Path) -> ExtractedPanel | None:
    """Deterministic parse, or None when the layout is unknown (the caller falls back to the
    model)."""
    if detect_format(path) == "generic_csv":
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        return parse_generic_csv(path.read_text(encoding="utf-8-sig"), delimiter)
    return None


async def extract_export_with_model(
    model: BaseChatModel, path: Path, drawn_on_hint: date | None, config: RunnableConfig | None
) -> ExtractedPanel:
    body = path.read_text(encoding="utf-8-sig", errors="replace")[:MAX_FALLBACK_CHARS]
    return await extract_structured(
        model,
        render_extract_prompt("export", drawn_on_hint, body),
        None,
        ["source_kind:export", "page_count:0"],
        config,
    )
