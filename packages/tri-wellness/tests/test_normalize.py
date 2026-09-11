import pytest

from tri_wellness.labs.models import RawResult
from tri_wellness.labs.normalize import normalize, parse_value
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def raw(name, value, unit=None, ref_low=None, ref_high=None, flag=None):
    return RawResult(
        name=name, value=value, unit=unit, ref_low=ref_low, ref_high=ref_high, flag=flag
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("42", (42.0, None)),
        (" 12.4 ", (12.4, None)),
        ("1,245", (1245.0, None)),
        ("<5", (5.0, "value '<5' stored as bound 5")),
        ("< 0.5", (0.5, "value '< 0.5' stored as bound 0.5")),
        (">200", (200.0, "value '>200' stored as bound 200")),
        ("<=3", (3.0, "value '<=3' stored as bound 3")),
        ("≥ 60", (60.0, "value '≥ 60' stored as bound 60")),
        ("Not detected", None),
        ("", None),
        ("12.4 ng/mL", None),
    ],
)
def test_parse_value(text, expected):
    assert parse_value(text) == expected


def test_plain_row_maps_to_canonical(reg):
    out = normalize([raw("Ferritin, Serum", "42", "ng/mL", "30", "400")], reg)
    assert out.unmapped == []
    [r] = out.results
    assert (r.marker, r.value, r.unit) == ("ferritin", 42.0, "ng/mL")
    assert (r.lab_ref_low, r.lab_ref_high) == (30.0, 400.0)
    assert r.note is None
    assert r.raw.name == "Ferritin, Serum"


def test_unit_conversion_and_case_insensitive_units(reg):
    out = normalize([raw("Glucose", "5.2", "mmol/L"), raw("Hemoglobin", "150", "g/l")], reg)
    g, h = out.results
    assert (
        g.marker == "glucose" and g.unit == "mg/dL" and g.value == pytest.approx(93.6946, abs=1e-4)
    )
    assert g.note == "converted from 5.2 mmol/L"
    assert h.marker == "hemoglobin" and h.value == 15.0 and h.note == "converted from 150 g/l"


def test_bounded_value_keeps_note_and_verbatim_raw(reg):
    [r] = normalize([raw("hs-CRP", "<0.3", "mg/L", None, "3.0", None)], reg).results
    assert r.value == 0.3 and r.note == "value '<0.3' stored as bound 0.3"
    assert r.raw.value == "<0.3" and r.lab_ref_low is None and r.lab_ref_high == 3.0


def test_bounded_lab_reference_is_parsed(reg):
    [r] = normalize([raw("HDL Cholesterol", "62", "mg/dL", ">39", None)], reg).results
    assert r.lab_ref_low == 39.0 and r.lab_ref_high is None


def test_unknown_name_goes_to_unmapped(reg):
    out = normalize([raw("Sedimentation Rate", "4", "mm/hr")], reg)
    assert out.results == []
    [u] = out.unmapped
    assert u.reason == "name" and u.marker is None and u.raw.name == "Sedimentation Rate"


def test_unknown_or_missing_unit_is_unmapped_with_marker(reg):
    out = normalize([raw("Ferritin", "42", "furlongs"), raw("Ferritin", "42")], reg)
    assert out.results == []
    assert [(u.reason, u.marker) for u in out.unmapped] == [
        ("unit", "ferritin"),
        ("unit", "ferritin"),
    ]


def test_non_numeric_value_is_unmapped_with_marker(reg):
    out = normalize([raw("TPO Antibodies", "Negative", "IU/mL")], reg)
    [u] = out.unmapped
    assert u.reason == "value" and u.marker == "tpo_ab"


def test_duplicate_marker_first_row_wins(reg):
    out = normalize([raw("Iron", "90", "ug/dL"), raw("Iron, Serum", "95", "ug/dL")], reg)
    [r] = out.results
    assert r.value == 90.0 and r.raw.name == "Iron"
    [u] = out.unmapped
    assert u.reason == "duplicate" and u.marker == "iron_serum" and u.raw.value == "95"


def test_order_is_preserved_and_flag_kept(reg):
    rows = [
        raw("Glucose", "92", "mg/dL", flag="H"),
        raw("TSH", "2.4", "uIU/mL"),
        raw("ALT", "31", "IU/L"),
    ]
    out = normalize(rows, reg)
    assert [r.marker for r in out.results] == ["glucose", "tsh", "alt"]
    assert out.results[0].raw.flag == "H"
