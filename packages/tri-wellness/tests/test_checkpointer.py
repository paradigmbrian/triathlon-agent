import logging
from datetime import time

from tri_wellness.graph.checkpointer import make_serde
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    raw = RawResult(name="Ferritin", value="42", unit="ng/mL")
    result = LabResult(marker="ferritin", value=42.0, unit="ng/mL", raw=raw)
    unmapped = Unmapped(raw=RawResult(name="ESR", value="4"), reason="name")
    ctx = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["iron"])
    state = {"raw_results": [raw], "results": [result], "unmapped": [unmapped], "context": ctx}
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed(state))
    assert back == state
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]
