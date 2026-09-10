import logging
from datetime import date

from tri_nutrition.graph.checkpointer import make_serde
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    change = NutritionChange(
        op="set_day_targets",
        target_key="2026-09-14",
        day=date(2026, 9, 14),
        payload={"calorie_goal": 2500, "carbs_grams": 300, "protein_grams": 150, "fat_grams": 60},
        reason="r",
    )
    decision = ReviewDecision(action="edit", changes=[change])
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(
            serde.dumps_typed({"pending_changes": [change], "review_decision": decision})
        )
    assert back == {"pending_changes": [change], "review_decision": decision}
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]
