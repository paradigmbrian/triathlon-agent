import contextlib
import json
from datetime import timedelta

import pytest

from tri_nutrition.testing import MONDAY, seed_goal_and_plan, session_json
from tri_nutrition.tools.plan import make_plan_tool

pytestmark = pytest.mark.db


async def test_read_training_plan_describes_horizon(nocommit):
    if nocommit.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    seed_goal_and_plan(
        nocommit,
        MONDAY,
        [("build", [session_json(MONDAY + timedelta(days=1), "run", 50, "threshold", 60)])],
        event_date=MONDAY + timedelta(days=40),
    )
    tool = make_plan_tool(lambda: contextlib.nullcontext(nocommit), lambda: MONDAY, 14)
    out = json.loads(await tool.ainvoke({}))
    assert out["source"] == "plan" and out["phases"][MONDAY.isoformat()] == "build"
    assert out["sessions"][0]["intensity"] == "threshold" and out["event_priority"] == "A"


async def test_read_training_plan_without_plan(nocommit):
    tool = make_plan_tool(lambda: contextlib.nullcontext(nocommit), lambda: MONDAY, 14)
    out = json.loads(await tool.ainvoke({}))
    assert out["source"] == "profile_hours" and out["sessions"] == []
