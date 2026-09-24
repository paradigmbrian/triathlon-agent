"""Real PDF extraction against one redacted panel Brian provides (spec §15, §19 item 1).
Opt-in: `uv run pytest --live packages/tri-wellness/tests/test_live_pdf.py -s`
with TRI_WELLNESS_LIVE_PDF=<path> and, optionally, TRI_WELLNESS_LIVE_ROWS=<expected row count>
and TRI_WELLNESS_LIVE_DRAWN_ON=<YYYY-MM-DD> in .env."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tri_core.llm import Role, make_model
from tri_wellness.config import WellnessSettings
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.normalize import normalize
from tri_wellness.ranges.registry import load_registry

pytestmark = pytest.mark.live


async def test_live_pdf_extraction():
    load_dotenv()
    path = os.environ.get("TRI_WELLNESS_LIVE_PDF")
    if not path:
        pytest.skip("set TRI_WELLNESS_LIVE_PDF to a redacted lab PDF")
    settings = WellnessSettings()
    panel, pages = await extract_pdf(make_model(settings, Role.LAB_EXTRACT), Path(path), None, None)
    print(
        f"\n{pages} pages, {len(panel.results)} rows, drawn {panel.drawn_on}, lab {panel.lab_name}"
    )
    assert panel.results and panel.drawn_on is not None
    expected_rows = os.environ.get("TRI_WELLNESS_LIVE_ROWS")
    if expected_rows:
        assert len(panel.results) == int(expected_rows)
    expected_date = os.environ.get("TRI_WELLNESS_LIVE_DRAWN_ON")
    if expected_date:
        assert panel.drawn_on == date.fromisoformat(expected_date)
    out = normalize(panel.results, load_registry(settings.tri_athlete_sex))
    print(f"{len(out.results)} mapped; unmapped: {[(u.raw.name, u.reason) for u in out.unmapped]}")
    by_page = sorted({r.page for r in panel.results if r.page is not None})
    print(f"rows on pages {by_page}")
