import contextlib
import json
from datetime import timedelta

import pytest

from tri_planning import repo
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp
from tri_planning.tools.goal import make_goal_tools

pytestmark = pytest.mark.db


def tools(nocommit, tp=None):
    named = {
        t.name: t
        for t in make_goal_tools(lambda: contextlib.nullcontext(nocommit), tp, lambda: MONDAY)
    }
    return named["set_training_goal"], named["list_tp_training_plans"]


def test_set_goal_inserts_and_reports_weeks(nocommit):
    set_goal, _ = tools(nocommit)
    out = json.loads(set_goal.invoke(GOAL_ARGS))
    assert out["weeks"] == 14 and out["compressed"] is False and out["warning"] is None
    stored = repo.get_goal(nocommit, out["goal_id"])
    assert stored is not None and stored.goal.event_name == "City Tri"


def test_set_goal_warns_when_compressed(nocommit):
    set_goal, _ = tools(nocommit)
    args = {**GOAL_ARGS, "event_date": (MONDAY + timedelta(weeks=9, days=6)).isoformat()}  # 10
    out = json.loads(set_goal.invoke(args))
    assert out["compressed"] is True and "12" in out["warning"]


def test_set_goal_refuses_impossible_goal(nocommit):
    set_goal, _ = tools(nocommit)
    args = {**GOAL_ARGS, "event_date": (MONDAY + timedelta(weeks=2)).isoformat()}
    out = json.loads(set_goal.invoke(args))
    assert "error" in out and repo.get_active_goal(nocommit) is None


def test_set_goal_reports_validation_errors_as_text(nocommit):
    set_goal, _ = tools(nocommit)
    out = json.loads(set_goal.invoke({**GOAL_ARGS, "weekly_hours_min": 20}))
    assert "error" in out and "weekly_hours_min" in out["error"]


async def test_list_plans_uses_server_or_reports_unavailable(nocommit):
    _, list_plans = tools(nocommit, FakeTp())
    assert "12 week olympic" in await list_plans.ainvoke({})
    _, list_plans = tools(nocommit, None)
    assert "unavailable" in await list_plans.ainvoke({})
