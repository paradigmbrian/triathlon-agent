from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from tri_planning.checkin import run_checkin
from tri_planning.prompts.checkin import CHECKIN_PROMPT


class StubGraph:
    def __init__(self, turns, phase="active"):
        self.turns = list(turns)
        self.inputs = []
        self.phase = phase

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"phase": self.phase, "pending_changes": []}
            next = ()

        return S()


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
    assert await run_checkin(g, yes=False, out=buf.append) == 3
    assert g.inputs[0]["messages"][0].content == CHECKIN_PROMPT
    assert "w1" in "".join(buf) and "paused" in "".join(buf)


async def test_checkin_yes_approves():
    g = StubGraph([[INTERRUPT], [APPLIED]])
    buf = []
    assert await run_checkin(g, yes=True, out=buf.append) == 0
    assert isinstance(g.inputs[1], Command) and g.inputs[1].resume == {"action": "approve"}


async def test_checkin_requires_active_plan():
    g = StubGraph([], phase="intake")
    buf = []
    assert await run_checkin(g, yes=True, out=buf.append) == 2 and "no active plan" in "".join(buf)


async def test_checkin_no_changes_exits_zero():
    g = StubGraph(
        [[((), "updates", {"adjust": {"messages": [AIMessage(content="All on track.")]}})]]
    )
    assert await run_checkin(g, yes=False, out=lambda s: None) == 0
