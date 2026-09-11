from datetime import date

from tri_planning.evals.design_eval import build_examples, validator_pass
from tri_planning.planning.models import TrainingGoal, WeekTarget
from tri_planning.testing import week_json


def test_examples_cover_presets_and_phases():
    ex = build_examples(date(2026, 9, 14))
    kinds = {(e["metadata"]["goal_type"], e["metadata"]["phase"]) for e in ex}
    assert (
        ("olympic", "base") in kinds
        and ("ironman", "taper") in kinds
        and ("sprint", "race") in kinds
    )
    for e in ex:
        TrainingGoal.model_validate(e["inputs"]["goal"])
        WeekTarget.model_validate(e["inputs"]["target"])
    assert len(ex) >= 16


def test_validator_pass_scores_week():
    ex = next(
        e
        for e in build_examples(date(2026, 9, 14))
        if e["metadata"]["goal_type"] == "olympic" and e["metadata"]["phase"] == "base"
    )
    target = WeekTarget.model_validate(ex["inputs"]["target"])
    good = {"week": week_json(target.week_start, target.target_tss)}
    bad = {"week": week_json(target.week_start, target.target_tss * 2)}
    assert validator_pass(ex["inputs"], good)["score"] == 1
    out = validator_pass(ex["inputs"], bad)
    assert out["score"] == 0 and "TSS" in out["comment"]
