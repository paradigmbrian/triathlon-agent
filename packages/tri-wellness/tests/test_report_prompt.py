from datetime import date, time

import pytest

from tri_wellness.labs.evaluate import evaluate
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, TrainingContext
from tri_wellness.prompts.report import (
    CHANGES_TITLE,
    DISCLAIMER,
    REPORT_RULES,
    REPORT_SYSTEM,
    SECTION_TITLES,
    findings_block,
    format_range,
    render_report_prompt,
)
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import extract_section

D = date(2026, 8, 20)


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def lr(marker, value, unit):
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        raw=RawResult(name=marker, value=str(value), unit=unit),
    )


@pytest.fixture
def findings(reg):
    results = [
        lr("ferritin", 42.0, "ng/mL"),
        lr("hs_crp", 1.8, "mg/L"),
        lr("hemoglobin", 15.1, "g/dL"),
        lr("tsh", 1.5, "mIU/L"),
    ]
    hard = {
        "date": "2026-08-19",
        "sport": "bike",
        "duration_min": 180,
        "tss": 210,
        "title": "long ride",
    }
    training = TrainingContext(
        drawn_on=D,
        ctl=62.0,
        atl=80.0,
        tsb=-18.0,
        tss_7d=520.0,
        last_sessions=[hard],
        sleep_2n_avg_sec=24000,
        sleep_30d_avg_sec=27000,
        hrv_2n_avg=52,
        hrv_30d_avg=60,
    )
    return evaluate(
        results,
        reg,
        {"ferritin": (date(2026, 3, 1), 35.0, None)},
        PanelContext(fasting=True, draw_time=time(7, 30)),
        training,
    ), training


def test_system_prompt_has_structure_and_rules():
    assert DISCLAIMER in REPORT_SYSTEM
    for title in SECTION_TITLES:
        assert f"## {title}" in REPORT_SYSTEM
    assert CHANGES_TITLE in REPORT_SYSTEM
    assert "pattern suggests" in REPORT_RULES and "no generic" in REPORT_RULES.lower()
    assert REPORT_RULES in REPORT_SYSTEM


def test_findings_block_groups_by_system_and_never_shows_a_bare_value(reg, findings):
    fs, _ = findings
    text = findings_block(fs, reg)
    assert text.index("## iron") < text.index("## inflammation")
    assert "Ferritin: 42 ng/mL" in text and "suboptimal_low" in text and "functional 50-150" in text
    assert "previous 35 on 2026-03-01 (+20.0%)" in text
    assert "confounders: recent_hard_session, inflammation" in text
    assert "hs-CRP: 1.8 mg/L" in text and "functional up to 1" in text  # one-sided range
    # optimal markers: one compact line per system, still with their range
    assert "optimal: Hemoglobin 15.1 g/dL (14-15.5)" in text
    assert "optimal: TSH 1.5 mIU/L (1-2)" in text
    # athlete note and sources travel with flagged markers only
    assert "acute-phase reactant" in text
    assert "Weatherby" in text
    assert text.count("note:") == 2


def test_render_report_prompt_sections(reg, findings):
    fs, training = findings
    ctx = PanelContext(
        fasting=False,
        draw_time=time(14, 0),
        supplements=["iron 25 mg"],
        symptoms=["fatigue"],
        notes="week 3 of build",
    )
    profile = {
        "ftp_watts": 260,
        "weight_kg": 74.5,
        "lthr_bpm": 165,
        "run_threshold_pace_sec_per_km": 255,
        "swim_css_sec_per_100m": None,
        "max_hr_bpm": 188,
    }
    text = render_report_prompt(
        fs, ctx, training, "1. Ferritin first.\n2. Sleep.", profile, reg, has_previous=True
    )
    assert "Athlete:" in text and "male" in text and "260 W" in text and "74.5 kg" in text
    assert (
        "not fasted" in text
        and "14:00" in text
        and "iron 25 mg" in text
        and "fatigue" in text
        and "week 3 of build" in text
    )
    assert "CTL 62" in text and "ATL 80" in text and "TSB -18" in text and "520" in text
    assert "long ride" in text and "210" in text
    assert "sleep 400 min vs 450 min" in text and "HRV 52 vs 60" in text
    assert "Previous report priorities:" in text and "Ferritin first" in text
    assert f"include the section '## {CHANGES_TITLE}'" in text
    first = render_report_prompt(fs, ctx, training, None, None, reg, has_previous=False)
    assert "first panel" in first and CHANGES_TITLE not in first
    assert "thresholds: not available" in first


def test_extract_section():
    md = "line\n\n## Draw conditions\nfasted\n\n## Priorities\n1. A\n2. B\n\n## Levers\nx\n"
    assert extract_section(md, "Priorities") == "1. A\n2. B"
    assert extract_section(md, "Levers") == "x"
    assert extract_section(md, "Missing") is None
    assert extract_section("## 3. Priorities\nA\n## Next\n", "Priorities") == "A"
    assert extract_section("### Priorities\nA", "Priorities") is None  # only level-2 headings


def test_format_range():
    assert format_range(50.0, 150.0) == "50-150"
    assert format_range(None, 1.0) == "up to 1"
    assert format_range(50.0, None) == "50 or above"
    assert format_range(None, None) == "no range"


def test_findings_block_shows_bounded_values_as_printed(reg):
    tg = LabResult(
        marker="tg_ab",
        value=1.0,
        unit="IU/mL",
        bound="<",
        raw=RawResult(name="Thyroglobulin Antibody", value="<1.0", unit="IU/mL"),
    )
    fer = LabResult(
        marker="ferritin",
        value=50.0,
        unit="ng/mL",
        bound="<",
        raw=RawResult(name="Ferritin", value="<50", unit="ng/mL"),
        lab_ref_low=30.0,
        lab_ref_high=100.0,
    )
    fs = evaluate([tg, fer], reg, {}, PanelContext(fasting=True), TrainingContext(drawn_on=D))
    text = findings_block(fs, reg)
    assert "optimal: Thyroglobulin antibodies <1.0 IU/mL (up to 0.9)" in text
    assert (
        "- Ferritin: <50 ng/mL — indeterminate (reported as <50) "
        "(functional 50-150; conventional indeterminate)"
    ) in text
