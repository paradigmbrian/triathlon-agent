from types import SimpleNamespace

import anthropic
import httpx
from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from tri_planning.checkin import run_checkin
from tri_planning.planning.models import CalendarChange
from tri_planning.prompts.checkin import CHECKIN_PROMPT


class StubGraph:
    """A graph whose turns are scripted stream events and whose state is a plain dict.

    `state_after_approve`, when given, is the state returned once the approval turn has run,
    so a test can show a failed or partial apply.
    """

    def __init__(
        self,
        turns,
        next=(),
        pending_changes=(),
        state_after_approve=None,
    ):
        self.turns = list(turns)
        self.inputs = []
        self.next = tuple(next)
        self.pending_changes = list(pending_changes)
        self.state_after_approve = state_after_approve
        self.approved = False

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        if isinstance(payload, Command):
            self.approved = True
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        if self.approved and self.state_after_approve is not None:
            return SimpleNamespace(values=dict(self.state_after_approve), next=())
        values = {"pending_changes": list(self.pending_changes)}
        return SimpleNamespace(values=values, next=self.next)


INTERRUPT = (
    (),
    "updates",
    {
        "__interrupt__": (
            Interrupt(
                value={
                    "summary": "s",
                    "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "sick"}],
                    "last_error": None,
                }
            ),
        )
    },
)
APPLIED = (
    (),
    "updates",
    {"apply": {"messages": [AIMessage(content="TrainingPeaks: applied 1 of 1 changes.")]}},
)


async def test_checkin_pauses_without_yes():
    g = StubGraph([[INTERRUPT]])
    buf = []
    assert await run_checkin(g, phase="active", yes=False, out=buf.append) == 3
    assert g.inputs[0]["messages"][0].content == CHECKIN_PROMPT
    assert "w1" in "".join(buf) and "paused" in "".join(buf)


async def test_checkin_yes_approves():
    g = StubGraph([[INTERRUPT], [APPLIED]])
    buf = []
    assert await run_checkin(g, phase="active", yes=True, out=buf.append) == 0
    assert isinstance(g.inputs[1], Command) and g.inputs[1].resume == {"action": "approve"}


async def test_checkin_requires_active_plan():
    g = StubGraph([])
    buf = []
    assert await run_checkin(g, phase="intake", yes=True, out=buf.append) == 2
    assert "no active plan" in "".join(buf)


async def test_checkin_no_changes_exits_zero():
    g = StubGraph(
        [[((), "updates", {"adjust": {"messages": [AIMessage(content="All on track.")]}})]]
    )
    assert await run_checkin(g, phase="active", yes=False, out=lambda s: None) == 0


class RaisingStubGraph(StubGraph):
    """A graph whose astream raises instead of yielding, simulating a failed model call."""

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        raise anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com")
        )
        yield  # pragma: no cover - makes this an async generator


async def test_checkin_returns_error_code_on_model_failure():
    g = RaisingStubGraph([])
    buf = []
    assert await run_checkin(g, phase="active", yes=False, out=buf.append) == 1
    assert "connection error" in "".join(buf)


async def test_checkin_refuses_a_review_it_did_not_produce():
    pending = [CalendarChange(op="delete", tp_workout_id="w1", reason="sick")]
    g = StubGraph([], next=("review",), pending_changes=pending)
    buf = []
    assert await run_checkin(g, phase="active", yes=True, out=buf.append) == 3
    text = "".join(buf)
    assert g.inputs == []  # no turn was run
    assert "a review is already pending" in text and "w1" in text


async def test_checkin_yes_reports_a_failed_apply():
    g = StubGraph(
        [[INTERRUPT], [APPLIED]],
        state_after_approve={
            "phase": "active",
            "last_error": "TrainingPeaks server unavailable",
            "pending_changes": [CalendarChange(op="delete", tp_workout_id="w1", reason="sick")],
        },
    )
    buf = []
    assert await run_checkin(g, phase="active", yes=True, out=buf.append) == 1
    assert "apply did not complete: TrainingPeaks server unavailable" in "".join(buf)
