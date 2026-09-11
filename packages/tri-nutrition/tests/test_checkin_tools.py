import contextlib
import json
from datetime import timedelta

import pytest

from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import DayTarget, NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin, call_tool_in_graph
from tri_nutrition.tools.checkin import make_checkin_tools, summarize_by_day_type

pytestmark = pytest.mark.db


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def target(day, day_type="easy", kcal=2500):
    return DayTarget(
        day=day,
        day_type=day_type,
        session_kcal=300,
        total_kcal=kcal,
        carbs_g=300,
        protein_g=150,
        fat_g=70,
        fluid_baseline_ml=3000,
        source="plan",
    )


def tools(ndb, garmin):
    made = make_checkin_tools(garmin, lambda: contextlib.nullcontext(ndb), lambda: MONDAY)
    return {t.name: t for t in made}


def food_log(kcal_by_date):
    def respond(args):
        kcal = kcal_by_date.get(args["date"])
        if kcal is None:
            return "No food logged"
        return {
            "mealDate": args["date"],
            "dailyNutritionContent": {
                "calories": kcal,
                "carbs": 250.0,
                "protein": 120.0,
                "fat": 60.0,
            },
            "mealDetails": [
                {
                    "meal": {"mealName": "DINNER"},
                    "mealNutritionContent": {"calories": kcal},
                    "loggedFoods": [{"foodMetaData": {"foodName": "Rice bowl"}, "servingQty": 2.0}],
                }
            ],
        }

    return respond


async def test_read_intake_vs_targets_joins_and_summarizes(ndb, mem_store):
    days = [MONDAY - timedelta(days=n) for n in range(7, 0, -1)]  # 7 days ending yesterday
    past = [target(d, "hard" if i % 2 else "easy") for i, d in enumerate(days)]
    future = [target(MONDAY + timedelta(days=n)) for n in range(4)]
    repo.upsert_targets(ndb, past + future)
    logged = {days[0].isoformat(): 2000, days[1].isoformat(): 2600, days[6].isoformat(): 2400}
    g = FakeGarmin(responses={"get_nutrition_daily_food_log": food_log(logged)})
    t = tools(ndb, g)["read_intake_vs_targets"]
    out = json.loads(await call_tool_in_graph(mem_store, t, {"days": 7}))
    assert [r["day"] for r in out["days"]] == [d.isoformat() for d in days]
    first = out["days"][0]
    assert first["logged"] and first["logged_kcal"] == 2000 and first["target_kcal"] == 2500
    assert first["delta_kcal"] == -500 and first["items"] == ["Rice bowl x2"]
    assert out["days"][2]["logged"] is False and out["days"][2]["delta_kcal"] is None
    easy = out["by_day_type"]["easy"]
    assert easy["days"] == 2 and easy["avg_delta_kcal"] == -300
    assert out["by_day_type"]["hard"] == {
        "days": 1,
        "avg_logged_kcal": 2600,
        "avg_target_kcal": 2500,
        "avg_delta_kcal": 100,
        "avg_logged_protein_g": 120,
        "avg_target_protein_g": 150,
    }
    assert out["targets_through"] == (MONDAY + timedelta(days=3)).isoformat()
    assert out["days_of_targets_remaining"] == 4
    assert [c[1]["date"] for c in g.calls] == [d.isoformat() for d in days]


async def test_read_intake_without_garmin_or_targets(ndb, mem_store):
    t = tools(ndb, None)["read_intake_vs_targets"]
    assert "error" in json.loads(await call_tool_in_graph(mem_store, t, {}))
    t = tools(ndb, FakeGarmin())["read_intake_vs_targets"]
    out = json.loads(await call_tool_in_graph(mem_store, t, {"days": 2}))
    assert len(out["days"]) == 2
    assert out["days"][0]["target_kcal"] is None and out["days"][0]["delta_kcal"] is None
    assert out["targets_through"] is None and out["days_of_targets_remaining"] == 0


def test_summarize_by_day_type_skips_unlogged_and_untyped():
    def row(day_type, logged, kcal, tkcal, delta, prot, tprot):
        return {
            "day_type": day_type,
            "logged": logged,
            "logged_kcal": kcal,
            "target_kcal": tkcal,
            "delta_kcal": delta,
            "logged_protein_g": prot,
            "target_protein_g": tprot,
        }

    rows = [
        row("easy", True, 2000, 2500, -500, 100, 150),
        row("easy", False, 0, 2500, None, 0, 150),
        row(None, True, 2000, None, None, 100, None),
    ]
    assert summarize_by_day_type(rows) == {
        "easy": {
            "days": 1,
            "avg_logged_kcal": 2000,
            "avg_target_kcal": 2500,
            "avg_delta_kcal": -500,
            "avg_logged_protein_g": 100,
            "avg_target_protein_g": 150,
        }
    }


async def test_record_fuel_feedback_appends_and_adds_tested_product(ndb, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    t = tools(ndb, None)["record_fuel_feedback"]
    ok = {
        "day": "2026-09-12",
        "sport": "bike",
        "duration_min": 150,
        "carbs_g_per_h": 75,
        "outcome": "ok",
        "products": ["Gel", "Chews"],
        "new_product": {"name": "Chews", "form": "chew", "carbs_g": 24, "sodium_mg": 40},
    }
    out = json.loads(await call_tool_in_graph(mem_store, t, ok))
    assert out == {
        "recorded": True,
        "entries": 1,
        "product_added": True,
        "carbs_evidence_g_per_h": 75,
    }
    library = {p.name: p for p in await S.get_product_library(mem_store)}
    assert library["Chews"].tested is True and library["Chews"].carbs_g == 24
    upset = {
        "day": "2026-09-13",
        "sport": "run",
        "duration_min": 60,
        "carbs_g_per_h": 90,
        "outcome": "gi_upset",
        "note": "cramps at 40 min",
        "new_product": {"name": "Mystery", "form": "gel", "carbs_g": 30},
    }
    out = json.loads(await call_tool_in_graph(mem_store, t, upset))
    assert out["entries"] == 2 and out["product_added"] is False
    assert out["carbs_evidence_g_per_h"] == 75
    assert "Mystery" not in {p.name for p in await S.get_product_library(mem_store)}
    log = await S.get_fuel_log(mem_store)
    assert [e.outcome for e in log] == ["ok", "gi_upset"] and log[1].note == "cramps at 40 min"
    bad = {
        "day": "2026-09-13",
        "sport": "run",
        "duration_min": -5,
        "carbs_g_per_h": 40,
        "outcome": "ok",
    }
    out = json.loads(await call_tool_in_graph(mem_store, t, bad))
    assert "error" in out and len(await S.get_fuel_log(mem_store)) == 2


async def test_propose_target_changes_validates_against_profile(ndb, mem_store):
    t = tools(ndb, None)["propose_target_changes"]

    async def call(overrides, reason="x"):
        args = {"overrides": overrides, "reason": reason}
        return json.loads(await call_tool_in_graph(mem_store, t, args))

    out = await call({"activity_factor": 1.4})
    assert "error" in out and "no profile" in out["error"]
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    out = await call({"activity_factor": 1.4}, "on my feet more")
    assert out == {
        "proposed": True,
        "overrides": {"activity_factor": 1.4},
        "reason": "on my feet more",
    }
    out = await call({}, "extend horizon")
    assert out["proposed"] is True and out["overrides"] == {}
    out = await call({"activity_factor": 1.9})
    assert "error" in out and "activity_factor" in out["error"]
    out = await call({"shoe_size": 44})
    assert "error" in out and "shoe_size" in out["error"]
    assert (await S.get_profile(mem_store)).activity_factor == 1.35  # nothing was written
