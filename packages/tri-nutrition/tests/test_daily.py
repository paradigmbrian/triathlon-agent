from datetime import timedelta

import pytest

from tri_core.testing import ScriptedChatModel
from tri_nutrition import daily, repo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin

pytestmark = pytest.mark.db


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


async def test_propose_and_write_today(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    deps = make_deps(ScriptedChatModel(script=[]), garmin=g, horizon=5)
    h = await daily.propose_today(deps, mem_store)
    assert not h.error and not h.violations and len(h.targets) == 5
    assert [c.day for c in h.changes] == [MONDAY]
    assert "kcal" in daily.describe_change(h) and MONDAY.isoformat() in daily.describe_change(h)
    out = await daily.write_today(deps, h)
    assert "written to Garmin" in out
    assert g.calls == [
        ("set_nutrition_daily_settings", {"date": MONDAY.isoformat(), **h.changes[0].payload})
    ]
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=4))
    assert [s.written_to_garmin for s in stored] == [True, False, False, False, False]
    assert ndb.execute("select thread_id from nutrition_changes").fetchone()["thread_id"] == "today"
    # already written with the same values: nothing to write
    again = await daily.propose_today(deps, mem_store)
    assert again.changes == [] and "already on Garmin" in again.summary()
    assert await daily.write_today(deps, again) == "nothing to write"


async def test_without_profile(ndb, make_deps, mem_store):
    h = await daily.propose_today(make_deps(ScriptedChatModel(script=[])), mem_store)
    assert h.error and "no nutrition profile" in h.summary()
