from pathlib import Path

import pytest

from tri_wellness.ranges.registry import (
    Range,
    RegistryError,
    load_registry,
    normalize_alias,
)

FIX = Path(__file__).parent / "fixtures" / "ranges"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Ferritin", "ferritin"),
        ("Ferritin, Serum", "ferritin serum"),
        ("  Vitamin D (25-Hydroxy)  ", "vitamin d"),
        ("hs-CRP", "hs crp"),
        ("Testosterone,Free (Direct)", "testosterone free"),
        ("HDL   Cholesterol", "hdl cholesterol"),
        ("Hemoglobin A1c", "hemoglobin a1c"),
    ],
)
def test_normalize_alias(raw, expected):
    assert normalize_alias(raw) == expected


def test_load_resolves_sex_and_indexes_aliases():
    reg = load_registry("female", FIX / "good_sexed.yaml")
    assert reg.version == "test.1"
    assert reg.sex == "female"
    assert len(reg) == 2 and set(reg) == {"ferritin", "hs_crp"}
    f = reg.get("ferritin")
    assert f.key == "ferritin"
    assert f.conventional == Range(low=15, high=150)
    assert f.functional == Range(low=50, high=120)
    assert f.conversions == {"µg/L": 1.0, "ug/L": 1.0}
    assert f.confounders == ["recent_hard_session", "inflammation"]
    assert load_registry("male", FIX / "good_sexed.yaml").get("ferritin").conventional == Range(
        low=30, high=400
    )


def test_unsexed_marker_and_open_range():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    c = reg.get("hs_crp")
    assert c.conventional == Range(low=None, high=3.0)
    assert c.functional == Range(low=None, high=1.0)
    assert c.direction == "high"
    assert c.athlete_note == ""
    assert c.confounders == []


def test_lookup_uses_normalized_aliases():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    assert reg.lookup("FERRITIN, Serum").key == "ferritin"
    assert reg.lookup("C-Reactive Protein, High Sensitivity").key == "hs_crp"
    assert reg.lookup("CRP (hs)") is None  # 'crp' alone is not an alias
    assert reg.lookup("Ferritin (serum)").key == "ferritin"  # qualifier stripped
    assert reg.lookup("Vitamin D") is None


def test_get_unknown_raises_keyerror():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    with pytest.raises(KeyError):
        reg.get("nope")


@pytest.mark.parametrize(
    "file, marker, field",
    [
        ("bad_missing_field.yaml", "ferritin", "unit"),
        ("bad_functional_outside.yaml", "ferritin", "functional"),
        ("bad_duplicate_alias.yaml", "iron_serum", "aliases"),
        ("bad_conversion_target.yaml", "ferritin", "conversions"),
    ],
)
def test_validation_names_marker_and_field(file, marker, field):
    with pytest.raises(RegistryError) as exc:
        load_registry("male", FIX / file)
    msg = str(exc.value)
    assert marker in msg and field in msg


def test_missing_sex_block_is_an_error(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "version: t\nmarkers:\n  x:\n    display: X\n    system: iron\n    unit: u\n"
        "    aliases: [x]\n    conventional: {male: {low: 1, high: 2}}\n"
        "    functional: {low: 1, high: 2}\n    direction: both\n    sources: [s]\n"
    )
    with pytest.raises(RegistryError, match="x.*conventional.*female"):
        load_registry("female", p)


def test_unknown_system_is_an_error(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "version: t\nmarkers:\n  x:\n    display: X\n    system: bones\n    unit: u\n"
        "    aliases: [x]\n    conventional: {low: 1, high: 2}\n"
        "    functional: {low: 1, high: 2}\n    direction: both\n    sources: [s]\n"
    )
    with pytest.raises(RegistryError, match="x.*system"):
        load_registry("male", p)
