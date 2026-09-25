"""The review node over plain state: interrupt() is replaced so the node runs outside a graph."""

import tri_coach.graph.nodes.review as review
from tri_coach.graph.nodes.review import review_node
from tri_coach.models import Proposal, ProposalRequest


def proposal(pid: str) -> Proposal:
    return Proposal.model_validate(
        {
            "id": pid,
            "domain": "planning",
            "summary": "move it",
            "changes": [
                {"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "rest"}
            ],
        }
    )


def test_a_repeated_proposal_id_is_reviewed_and_applied_once(monkeypatch):
    shown = []

    def fake_interrupt(payload):
        shown.append(payload)
        return {"action": "approve"}

    monkeypatch.setattr(review, "interrupt", fake_interrupt)
    state = {
        "proposals": [proposal("p1"), proposal("p2")],
        "proposal_request": ProposalRequest(narration="Move it.", ids=["p1", "p1", "p2", "p1"]),
        "pending": None,
    }
    out = review_node(state)
    assert [p["id"] for p in shown[0]["proposals"]] == ["p1", "p2"]
    assert [p.id for p in out["pending"].proposals] == ["p1", "p2"]
    assert out["review_decision"].action == "approve" and out["carried"] == []
