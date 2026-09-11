"""Extraction instructions. The model transcribes; it does not interpret."""

from __future__ import annotations

from datetime import date

from tri_wellness.labs.models import IngestKind

EXTRACT_SYSTEM = """\
You transcribe laboratory reports into structured rows and return an ExtractedPanel.

results: one RawResult per printed test that has a numeric or bounded value ("<5", ">200",
"<=0.9"). Copy name, value, unit, reference range and flag exactly as printed, character for
character; do not rename tests, do not convert units, do not fill in a range or flag the report
does not print. value is the printed number or bound as text, never rounded. ref_low and ref_high
are the printed reference range split into its two ends; a one-sided range such as "<3.0" gives
ref_high "3.0" and ref_low null; ">39" gives ref_low "39". flag is the lab's own marker (H, L,
HH, LL, A, or its text). page is the page the row appears on, starting at 1.

drawn_on: the specimen collection date (labels such as "Collected", "Drawn", "Specimen
collected"), as YYYY-MM-DD; null when the report does not print one. Do not use the report or
received date. lab_name: the laboratory that ran the tests, as printed, or null.

Skip rows that are only text ("Negative", "Not detected", "See note"): they carry no numeric
or bounded value. Skip calculated summary lines the report labels as such only when they have no
value. Never invent a row, never merge two tests, never skip a page. Return every row."""


def render_extract_prompt(kind: IngestKind, drawn_on_hint: date | None, body: str | None) -> str:
    lines = [
        f"Source kind: {kind}. Transcribe every result row verbatim into an ExtractedPanel.",
        "Include the draw date and lab name when the document prints them.",
    ]
    if drawn_on_hint is not None:
        lines.append(
            f"If the document prints no collection date, the athlete says the draw date was "
            f"{drawn_on_hint.isoformat()}; use it only in that case."
        )
    if body is not None:
        lines += ["", "The document is this text:", "", body]
    return "\n".join(lines)
