"""Schema shapes; JSON and YAML validate paths with a wrong domain, a bad date and an unknown op."""

from tri_coach.models import Proposal
from tri_web.review import schema, to_yaml, typed, validate_json, validate_yaml


def proposals() -> list[Proposal]:
    return [
        Proposal.model_validate(
            {
                "id": "p1",
                "domain": "planning",
                "summary": "move it",
                "changes": [
                    {
                        "op": "move",
                        "tp_workout_id": "w1",
                        "new_date": "2026-09-18",
                        "reason": "rest",
                    }
                ],
            }
        ),
        Proposal.model_validate(
            {
                "id": "p2",
                "domain": "nutrition",
                "summary": "targets",
                "changes": [
                    {
                        "op": "set_day_targets",
                        "target_key": "2026-09-14",
                        "day": "2026-09-14",
                        "payload": {"calorie_goal": 2800},
                        "reason": "extend",
                    }
                ],
                "overrides": {"activity_factor": 1.45},
            }
        ),
    ]


def test_schema_has_the_three_models_with_their_enums():
    s = schema()
    assert set(s) == {"proposal", "planning_change", "nutrition_change"}
    assert s["proposal"]["properties"]["domain"]["enum"] == ["planning", "nutrition"]
    assert "create" in s["planning_change"]["properties"]["op"]["enum"]
    assert "set_day_targets" in s["nutrition_change"]["properties"]["op"]["enum"]
    assert "PlannedSession" in s["planning_change"]["$defs"]
    assert s["nutrition_change"]["properties"]["day"]["format"] == "date"


def test_validate_json_accepts_typed_proposals_and_round_trips():
    v = validate_json([p.model_dump(mode="json") for p in proposals()])
    assert v.ok and v.errors == [] and [p["id"] for p in v.proposals] == ["p1", "p2"]
    back = typed(v)
    assert back[0].changes[0].new_date.isoformat() == "2026-09-18"
    assert back[1].overrides == {"activity_factor": 1.45}


def test_validate_json_reports_loc_and_msg_per_error():
    bad = [p.model_dump(mode="json") for p in proposals()]
    bad[0]["domain"] = "cooking"
    bad[1]["changes"][0]["day"] = "2026-13-40"
    v = validate_json(bad)
    assert not v.ok and v.proposals == []
    locs = [e.loc for e in v.errors]
    assert [0, "domain"] in locs
    assert any(loc[:3] == [1, "changes", 0] and "day" in loc for loc in locs)
    assert all(e.msg for e in v.errors)


def test_validate_json_rejects_an_unknown_op():
    bad = [proposals()[0].model_dump(mode="json")]
    bad[0]["changes"][0]["op"] = "teleport"
    v = validate_json(bad)
    assert not v.ok and any("op" in e.loc for e in v.errors)


def test_yaml_path_edits_one_field_and_keeps_the_rest():
    text = to_yaml(proposals()).replace("2026-09-18", "2026-09-19")
    v = validate_yaml(text, proposals())
    assert v.ok and typed(v)[0].changes[0].new_date.isoformat() == "2026-09-19"
    assert typed(v)[1].overrides == {"activity_factor": 1.45}


def test_yaml_path_reports_parse_and_validation_errors():
    v = validate_yaml("p1: [unclosed", proposals())
    assert not v.ok and v.errors[0].loc == ["yaml"]
    v = validate_yaml(to_yaml(proposals()).replace("op: move", "op: teleport"), proposals())
    assert not v.ok and any("op" in e.loc for e in v.errors)


def test_json_missing_domain():
    """JSON with missing domain reports domain error, no fallback to changes."""
    bad = [p.model_dump(mode="json") for p in proposals()]
    del bad[0]["domain"]
    v = validate_json(bad)
    assert not v.ok
    locs = [e.loc for e in v.errors]
    assert [0, "domain"] in locs
    # Should not have changes errors for proposal 0 due to nutrition fallback
    assert not any(loc[:2] == [0, "changes"] for loc in locs)


def test_yaml_wrong_domain():
    """YAML with wrong domain reports domain error at yaml/pid/domain."""
    yaml_text = """
p1:
  domain: cooking
  summary: test
  changes: []
"""
    v = validate_yaml(yaml_text, proposals())
    assert not v.ok
    locs = [e.loc for e in v.errors]
    assert ["yaml", "p1", "domain"] in locs
    # Should not have nutrition-field errors for p1
    assert not any(loc[:3] == ["yaml", "p1", "changes"] for loc in locs), (
        "Should not validate changes when domain is invalid"
    )


def test_yaml_bad_date():
    """YAML with bad date reports error at yaml/pid/changes/0/day."""
    yaml_text = to_yaml(proposals()).replace("new_date: '2026-09-18'", "new_date: '2026-13-40'")
    v = validate_yaml(yaml_text, proposals())
    assert not v.ok
    locs = [e.loc for e in v.errors]
    # Check that there's an error with the right path structure
    assert any(loc[:4] == ["yaml", "p1", "changes", 0] and "new_date" in loc for loc in locs), (
        f"Expected error at yaml/p1/changes/0/new_date, got {locs}"
    )


def test_yaml_scalar_body():
    """YAML with scalar body (not a dict) reports error at yaml/pid."""
    yaml_text = "p1: hello"
    v = validate_yaml(yaml_text, proposals())
    assert not v.ok
    locs = [e.loc for e in v.errors]
    assert ["yaml", "p1"] in locs
