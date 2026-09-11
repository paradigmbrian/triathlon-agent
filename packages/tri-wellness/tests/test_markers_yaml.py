"""The real markers.yaml loads for both sexes and every alias and conversion round-trips."""

import pytest

from tri_wellness.ranges.registry import MARKERS_PATH, load_registry, normalize_alias

EXPECTED_KEYS = {
    # cbc
    "wbc",
    "rbc",
    "hemoglobin",
    "hematocrit",
    "mcv",
    "mch",
    "mchc",
    "rdw",
    "platelets",
    "neutrophils_pct",
    "lymphocytes_pct",
    "monocytes_pct",
    "eosinophils_pct",
    "basophils_pct",
    # metabolic / kidney / liver / electrolytes
    "glucose",
    "insulin",
    "hba1c",
    "bun",
    "creatinine",
    "egfr",
    "bun_creatinine_ratio",
    "sodium",
    "potassium",
    "chloride",
    "co2",
    "calcium",
    "total_protein",
    "albumin",
    "globulin",
    "alt",
    "ast",
    "alp",
    "bilirubin_total",
    "ggt",
    "uric_acid",
    "ck",
    # lipids
    "total_cholesterol",
    "ldl",
    "hdl",
    "triglycerides",
    "apob",
    "lpa",
    # thyroid
    "tsh",
    "free_t4",
    "free_t3",
    "reverse_t3",
    "tpo_ab",
    "tg_ab",
    # iron
    "ferritin",
    "iron_serum",
    "tibc",
    "transferrin_saturation",
    # inflammation
    "hs_crp",
    "homocysteine",
    # vitamins and minerals
    "vitamin_d",
    "b12",
    "folate",
    "rbc_magnesium",
    "zinc",
    "omega3_index",
    # hormones
    "testosterone_total",
    "testosterone_free",
    "shbg",
    "cortisol_am",
    "dhea_s",
}


@pytest.mark.parametrize("sex", ["male", "female"])
def test_loads_for_both_sexes(sex):
    reg = load_registry(sex, MARKERS_PATH)
    assert reg.version == "2026-09-11.1"
    assert set(reg) == EXPECTED_KEYS


def test_every_alias_round_trips():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        spec = reg.get(key)
        for alias in spec.aliases:
            found = reg.lookup(alias)
            assert found is not None and found.key == key, (key, alias)
        # the display name also resolves, so a lab printing our own label maps
        assert reg.lookup(spec.display) is not None, (key, spec.display)


def test_every_conversion_lands_on_the_canonical_unit():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        spec = reg.get(key)
        for unit, factor in spec.conversions.items():
            assert factor > 0, (key, unit)
            assert normalize_alias(unit) != "", (key, unit)
            if unit == spec.unit:
                assert factor == 1.0


def test_directional_markers_have_the_relevant_side():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        s = reg.get(key)
        if s.direction in ("high", "both"):
            assert s.functional.high is not None, key
        if s.direction in ("low", "both"):
            assert s.functional.low is not None, key
        assert s.sources, key
        assert s.athlete_note or s.direction != "both" or key in {"mch", "mchc", "globulin"}, key
