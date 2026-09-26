from datetime import timedelta

import psycopg
import pytest

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.nodes.apply import ApplyResult, apply_changes, make_apply_node
from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.planning.tp_calls import event_change
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="base", target_tss=300, target_hours=6
        )
        for i in range(2)
    ]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid


def create(day=0, title="Ride"):
    s = PlannedSession(
        date=MONDAY + timedelta(days=day),
        sport="bike",
        title=title,
        description="",
        duration_minutes=60,
        tss_planned=50,
        intensity="endurance",
    )
    return CalendarChange(op="create", workout_date=s.date, workout=s, reason="plan")


def state(gid, pid, changes):
    return {
        "goal_id": gid,
        "plan_id": pid,
        "pending_changes": changes,
        "pending_summary": "s",
        "phase": "planning",
    }


async def test_applies_all_records_rows_marks_designed_weeks_and_activates(nocommit, make_deps):
    gid, pid = seed(nocommit)
    repo.set_week_designed(
        nocommit, pid, MONDAY, PlannedWeek(week_start=MONDAY, sessions=[], coach_note="n")
    )
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(7, "Ride 2")]), CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert out["phase"] == "active"
    assert [c[0] for c in tp.calls] == ["tp_create_workout", "tp_create_workout"]
    assert len(repo.owned_workout_ids(nocommit, pid)) == 2
    # week 2 received a create but was never designed, so it is not a written plan week
    assert [w.written_to_tp for w in repo.list_weeks(nocommit, pid)] == [True, False]
    assert "applied 2" in out["messages"][0].content


async def test_mid_batch_failure_keeps_remainder_pending(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp(fail_on_call=2)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(1, "B"), create(2, "C")]), CFG)
    assert [c.workout.title for c in out["pending_changes"]] == ["B", "C"]
    assert "boom" in out["last_error"] and "phase" not in out
    assert len(repo.owned_workout_ids(nocommit, pid)) == 1
    rows = nocommit.execute(
        "select status, error from plan_changes where plan_id = %s order by id", (pid,)
    ).fetchall()
    assert [r["status"] for r in rows] == ["applied", "failed"]
    assert "boom" in rows[1]["error"]


async def test_ownership_refusal_unless_athlete_requested(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    foreign = CalendarChange(op="delete", tp_workout_id="coach-1", reason="drop")
    asked = CalendarChange(
        op="delete",
        tp_workout_id="coach-2",
        reason="athlete said delete it",
        athlete_requested=True,
    )
    out = await node(state(gid, pid, [foreign, asked]), CFG)
    assert [c[1]["workout_id"] for c in tp.calls] == ["coach-2"]
    text = out["messages"][0].content
    assert "coach-1" in text and "not agent-authored" in text
    assert out["pending_changes"] == []


async def test_event_id_is_stored_on_goal(nocommit, make_deps):
    gid, pid = seed(nocommit, create_tp_event=True)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    goal = repo.get_goal(nocommit, gid).goal
    await node(state(gid, pid, [event_change(goal)]), CFG)
    assert repo.get_goal(nocommit, gid).tp_event_id == "77"


async def test_apply_plan_sets_flag_and_does_not_activate(nocommit, make_deps):
    gid, pid = seed(nocommit)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    ch = CalendarChange(
        op="apply_plan", payload={"plan_id": "p1", "start_date": MONDAY.isoformat()}, reason="r"
    )
    out = await node(state(gid, None, [ch]), CFG)
    assert out["tp_plan_applied"] is True and "phase" not in out


async def test_refuses_without_tp_server(nocommit, make_deps):
    gid, pid = seed(nocommit)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=None))
    out = await node(state(gid, pid, [create()]), CFG)
    assert len(out["pending_changes"]) == 1 and "unavailable" in out["last_error"]


async def test_apply_changes_direct_reports_sessions_changed_and_thread(nocommit, make_deps):
    gid, pid = seed(nocommit, create_tp_event=True)
    tp = FakeTp()
    deps = make_deps(ScriptedChatModel(script=[]), tp=tp)
    r = await apply_changes(deps, [create(0)], "coach", plan_id=pid, goal_id=gid)
    assert isinstance(r, ApplyResult)
    assert r.sessions_changed is True and r.remaining == [] and r.error is None
    assert len(r.applied) == 1 and r.skipped == [] and r.tp_plan_applied is False
    rows = nocommit.execute(
        "select thread_id from plan_changes where plan_id = %s", (pid,)
    ).fetchall()
    assert [row["thread_id"] for row in rows] == ["coach"]
    assert r.report(1).startswith("TrainingPeaks: applied 1 of 1 changes.")

    goal = repo.get_goal(nocommit, gid).goal
    r2 = await apply_changes(deps, [event_change(goal)], "coach", plan_id=pid, goal_id=gid)
    assert r2.sessions_changed is False and len(r2.applied) == 1


async def test_apply_changes_direct_holds_everything_without_tp(nocommit, make_deps):
    gid, pid = seed(nocommit)
    deps = make_deps(ScriptedChatModel(script=[]), tp=None)
    r = await apply_changes(deps, [create(0), create(1, "B")], "coach", plan_id=pid, goal_id=gid)
    assert r.applied == [] and len(r.remaining) == 2 and r.sessions_changed is False
    assert r.error is not None and "unavailable" in r.error
    assert "applied 0 of 2" in r.report(2) and "2 changes still pending" in r.report(2)


async def test_apply_changes_direct_stops_at_failure(nocommit, make_deps):
    gid, pid = seed(nocommit)
    deps = make_deps(ScriptedChatModel(script=[]), tp=FakeTp(fail_on_call=2))
    r = await apply_changes(
        deps, [create(0), create(1, "B"), create(2, "C")], "coach", plan_id=pid, goal_id=gid
    )
    assert [c.workout.title for c in r.applied] == ["Ride"]
    assert [c.workout.title for c in r.remaining] == ["B", "C"]
    assert r.sessions_changed is True and "boom" in r.error


def _backdate(conn, row_id):
    conn.execute(
        "update plan_changes set applied_at = now() - interval '5 minutes' where id = %s", (row_id,)
    )


def _listing(*items):
    return {"tp_get_workouts": {"workouts": list(items), "count": len(items)}}


def _listed(wid, title="Ride", sport="Bike", day=MONDAY):
    return {"id": wid, "date": day.isoformat(), "title": title, "sport": sport}


def _status(conn, row_id):
    return conn.execute(
        "select status, error, tp_workout_id from plan_changes where id = %s", (row_id,)
    ).fetchone()


async def test_a_pending_create_found_on_tp_is_recorded_as_applied(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555")))
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    assert tp.calls == [
        (
            "tp_get_workouts",
            {"start_date": "2026-09-14", "end_date": "2026-09-14", "workout_filter": "all"},
        )
    ]
    assert _status(nocommit, rid)["status"] == "applied"
    assert repo.owned_workout_ids(nocommit, pid) == {"555"}
    assert "reconciled: create" in r.report(0) and "recorded as applied" in r.report(0)


async def test_a_pending_create_missing_on_tp_is_failed(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555", title="Something else")))
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    row = _status(nocommit, rid)
    assert (
        row["status"] == "failed"
        and row["error"] == "not found on TrainingPeaks after a pending write"
    )
    assert repo.owned_workout_ids(nocommit, pid) == set()
    assert "not found on TrainingPeaks" in r.report(0)


async def test_an_ambiguous_pending_create_is_failed(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(responses=_listing(_listed("555"), _listed("athletes-own")))
    await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    row = _status(nocommit, rid)
    assert row["status"] == "failed" and "more than one" in row["error"]
    assert repo.owned_workout_ids(nocommit, pid) == set()


async def test_a_young_pending_row_is_left_alone(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    tp = FakeTp(responses=_listing(_listed("555")))
    await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp), [], "t", plan_id=pid, goal_id=gid
    )
    assert tp.calls == [] and _status(nocommit, rid)["status"] == "pending"


async def test_unreachable_tp_leaves_rows_pending_and_the_apply_goes_on(nocommit, make_deps):
    gid, pid = seed(nocommit)
    rid = repo.insert_pending_change(nocommit, pid, "t", create(0))
    _backdate(nocommit, rid)
    tp = FakeTp(fail_on_call=1)
    r = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp),
        [create(1, "New")],
        "t",
        plan_id=pid,
        goal_id=gid,
    )
    assert _status(nocommit, rid)["status"] == "pending"
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_create_workout"]
    assert [c.workout.title for c in r.applied] == ["New"]
    assert "left pending" in r.report(1)


async def test_ownership_counts_applied_rows_only(nocommit, make_deps):
    gid, pid = seed(nocommit)
    repo.insert_change(nocommit, pid, "t", create(0), tp_workout_id="w1", result={})
    drop = CalendarChange(op="delete", tp_workout_id="w1", workout_date=MONDAY, reason="drop")
    repo.insert_pending_change(nocommit, pid, "t", drop)
    assert repo.owned_workout_ids(nocommit, pid) == {"w1"}
    assert [w["tp_workout_id"] for w in repo.owned_workouts(nocommit, pid)] == ["w1"]


async def test_a_change_whose_record_failed_is_not_sent_again(nocommit, make_deps, monkeypatch):
    gid, pid = seed(nocommit)
    real = repo.mark_change_applied
    broken = [True]

    def flaky(conn, row_id, **kw):
        if broken:
            broken.pop()
            raise psycopg.OperationalError("server closed the connection")
        real(conn, row_id, **kw)

    monkeypatch.setattr(repo, "mark_change_applied", flaky)
    tp = FakeTp()
    deps = make_deps(ScriptedChatModel(script=[]), tp=tp)
    r = await apply_changes(deps, [create(0, "A"), create(1, "B")], "t", plan_id=pid, goal_id=gid)
    assert [c[1]["title"] for c in tp.calls] == ["A"]
    assert r.applied == [] and [c.workout.title for c in r.remaining] == ["B"]
    assert "'A': sent, but its record failed" in r.report(2)
    assert "reconciled on the next apply" in r.report(2)
    rows = nocommit.execute(
        "select id, status from plan_changes where plan_id = %s order by id", (pid,)
    ).fetchall()
    assert [row["status"] for row in rows] == ["pending"]

    _backdate(nocommit, rows[0]["id"])
    tp2 = FakeTp(listings=[[_listed("1001", title="A")]])
    r2 = await apply_changes(
        make_deps(ScriptedChatModel(script=[]), tp=tp2),
        r.remaining,
        "t",
        plan_id=pid,
        goal_id=gid,
    )
    assert [c[0] for c in tp2.calls] == ["tp_get_workouts", "tp_create_workout"]
    assert tp2.calls[1][1]["title"] == "B"
    assert _status(nocommit, rows[0]["id"])["status"] == "applied"
    assert [c.workout.title for c in r2.applied] == ["B"] and r2.error is None
