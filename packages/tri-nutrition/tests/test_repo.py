from datetime import date, timedelta

import pytest

from tri_nutrition import repo
from tri_nutrition.nutrition.models import DayTarget, NutritionChange

pytestmark = pytest.mark.db

MON = date(2026, 9, 14)


@pytest.fixture
def ndb(db):
    if db.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied to the test database")
    return db


def target(day=MON, **over) -> DayTarget:
    base = dict(
        day=day,
        day_type="easy",
        session_kcal=300,
        total_kcal=2800,
        carbs_g=280,
        protein_g=150,
        fat_g=120,
        fluid_baseline_ml=2800,
        goal_adjust_kcal=0,
        plan_phase="base",
        source="plan",
        notes=["deficit"],
    )
    base.update(over)
    return DayTarget(**base)


def test_targets_roundtrip(ndb):
    ts = [target(MON + timedelta(days=i), total_kcal=2800 + i) for i in range(3)]
    repo.upsert_targets(ndb, ts)
    stored = repo.list_targets(ndb, MON, MON + timedelta(days=2))
    assert [s.target for s in stored] == ts
    assert all(s.written_to_garmin is False for s in stored)
    day2 = MON + timedelta(days=1)
    assert repo.list_targets(ndb, day2, day2)[0].target.total_kcal == 2801


def test_upsert_keeps_written_flag_when_unchanged(ndb):
    repo.upsert_targets(ndb, [target()])
    repo.mark_targets_written(ndb, [MON])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is True
    repo.upsert_targets(ndb, [target(notes=["different note only"])])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is True
    repo.upsert_targets(ndb, [target(carbs_g=300)])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is False


def test_delete_unwritten_targets(ndb):
    repo.upsert_targets(ndb, [target(MON), target(MON + timedelta(days=1))])
    repo.mark_targets_written(ndb, [MON])
    assert repo.delete_unwritten_targets(ndb) == 1
    assert [s.target.day for s in repo.list_targets(ndb, MON, MON + timedelta(days=1))] == [MON]


def test_fuel_plans_roundtrip_and_unique(ndb):
    pid = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"carbs_g_per_h": 60}, [])
    again = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"carbs_g_per_h": 70}, ["too much"])
    assert again == pid
    rid = repo.upsert_fuel_plan(ndb, "race", MON, None, {"note_text": "race"}, [])
    plans = repo.list_fuel_plans(ndb, MON, MON)
    assert {p.kind for p in plans} == {"session", "race"}
    sess = next(p for p in plans if p.kind == "session")
    assert sess.payload == {"carbs_g_per_h": 70} and sess.violations == ["too much"]
    assert sess.written is False and sess.tp_note_id is None
    repo.mark_fuel_written(ndb, rid, "note-9")
    race = next(p for p in repo.list_fuel_plans(ndb, MON, MON) if p.kind == "race")
    assert race.written is True and race.tp_note_id == "note-9"
    assert repo.delete_unwritten_fuel_plans(ndb) == 1


def test_two_idless_sessions_on_one_day_are_two_rows(ndb):
    idx = "select to_regclass('fuel_plans_kind_day_workout_title_idx') as t"
    if ndb.execute(idx).fetchone()["t"] is None:
        pytest.skip("migrations/006_fixes.sql not applied to the test database")
    swim = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "s"}, [], title="Swim")
    bike = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "b"}, [], title="Bike")
    assert swim != bike
    again = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "s2"}, [], title="Swim")
    assert again == swim
    plans = repo.list_fuel_plans(ndb, MON, MON)
    assert sorted(p.payload["title"] for p in plans) == ["Bike", "Swim"]
    assert next(p for p in plans if p.id == swim).payload["note_text"] == "s2"


def test_idd_session_rerun_without_title_stays_one_row(ndb):
    """The fuel node only passes title for id-less sessions (ruling: passing it for id'd
    sessions would key a TP rename as a new row). Confirm the conflict target stays stable
    across re-runs when title is omitted, matching what the node does for id'd sessions."""
    idx = "select to_regclass('fuel_plans_kind_day_workout_title_idx') as t"
    if ndb.execute(idx).fetchone()["t"] is None:
        pytest.skip("migrations/006_fixes.sql not applied to the test database")
    first = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"note_text": "a"}, [])
    again = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"note_text": "b"}, [])
    assert again == first
    plans = repo.list_fuel_plans(ndb, MON, MON)
    assert len(plans) == 1
    assert plans[0].payload["note_text"] == "b" and "title" not in plans[0].payload


def test_changes_and_note_ownership(ndb):
    assert repo.last_change_at(ndb) is None
    day_change = NutritionChange(
        op="set_day_targets",
        target_key=MON.isoformat(),
        day=MON,
        payload={"calorie_goal": 2800},
        reason="new",
    )
    repo.insert_change(ndb, "nutrition", day_change, {"ok": True})
    note = NutritionChange(
        op="set_race_note",
        target_key="note-9",
        day=MON,
        payload={"title": "Race fuel"},
        reason="race",
    )
    repo.insert_change(ndb, "nutrition", note, {"id": "note-9"})
    assert repo.owned_note_ids(ndb) == {"note-9"}
    row = ndb.execute("select * from nutrition_changes where target_key = 'note-9'").fetchone()
    assert row["operation"] == "set_race_note" and row["payload"]["op"] == "set_race_note"
    assert row["result"] == {"id": "note-9"} and row["reason"] == "race"
    assert repo.last_change_at(ndb) is not None


def test_mark_fuel_written_for_and_session_ownership(ndb):
    repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"note_text": "x"}, [])
    repo.mark_fuel_written_for(ndb, "session", MON, "w1", None)
    assert repo.list_fuel_plans(ndb, MON, MON)[0].written is True
    rid = repo.upsert_fuel_plan(ndb, "race", MON, None, {"note_text": "r"}, [])
    repo.mark_fuel_written_for(ndb, "race", MON, None, "n-1")
    race = next(p for p in repo.list_fuel_plans(ndb, MON, MON) if p.kind == "race")
    assert race.written and race.tp_note_id == "n-1" and race.id == rid
    assert repo.session_note_owned(ndb, "w1") is False
    change = NutritionChange(op="set_session_note", target_key="w1", day=MON, payload={}, reason="")
    repo.insert_change(ndb, "nutrition", change, {"success": True})
    assert repo.session_note_owned(ndb, "w1") is True


def test_last_target_day(ndb):
    assert repo.last_target_day(ndb) is None
    repo.upsert_targets(ndb, [target(MON), target(MON + timedelta(days=3))])
    assert repo.last_target_day(ndb) == MON + timedelta(days=3)
