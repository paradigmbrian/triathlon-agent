import contextlib

import pytest
from psycopg.types.json import Jsonb

from tri_core.db.writes import Recorded, mark_failed, pending_rows, recorded_write

pytestmark = pytest.mark.db


class _Open:
    """The rolled-back test connection behind a factory; commit is a no-op."""

    def __init__(self, conn):
        self._c = conn

    def commit(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)


def _factory(db):
    wrapped = _Open(db)
    return lambda: contextlib.nullcontext(wrapped)


def _insert(conn):
    return conn.execute(
        "insert into plan_changes (thread_id, operation, payload, status) "
        "values ('t', 'create', '{}'::jsonb, 'pending') returning id"
    ).fetchone()["id"]


def _mark(conn, row_id, result):
    conn.execute(
        "update plan_changes set status = 'applied', result = %s where id = %s",
        (Jsonb(result), row_id),
    )


def _row(db, row_id):
    return db.execute(
        "select status, error, result from plan_changes where id = %s", (row_id,)
    ).fetchone()


async def test_marks_applied(db):
    seen: list[int] = []

    async def call():
        seen.append(_row(db, rid_holder[0])["status"] == "pending")
        return {"workout_id": 9}

    rid_holder: list[int] = []

    def insert(conn):
        rid_holder.append(_insert(conn))
        return rid_holder[0]

    rec = await recorded_write(
        _factory(db), table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
    )
    assert rec == Recorded(row_id=rid_holder[0], result={"workout_id": 9})
    assert seen == [True]  # the row existed, pending, before the call
    assert _row(db, rec.row_id)["status"] == "applied"


async def test_marks_failed_and_reraises(db):
    ids: list[int] = []

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await recorded_write(
            _factory(db), table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
        )
    row = _row(db, ids[0])
    assert row["status"] == "failed" and row["error"] == "RuntimeError: boom"


async def test_leaves_pending_when_mark_applied_raises(db):
    ids: list[int] = []

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        return {"ok": True}

    def broken(conn, row_id, result):
        raise RuntimeError("db went away")

    with pytest.raises(RuntimeError, match="db went away"):
        await recorded_write(
            _factory(db),
            table="plan_changes",
            insert_pending=insert,
            call=call,
            mark_applied=broken,
        )
    assert _row(db, ids[0])["status"] == "pending"


async def test_the_call_error_survives_a_failed_failure_mark(db):
    ids: list[int] = []
    opens = {"n": 0}
    wrapped = _Open(db)

    def factory():
        opens["n"] += 1
        if opens["n"] > 1:
            raise OSError("database unreachable")
        return contextlib.nullcontext(wrapped)

    def insert(conn):
        ids.append(_insert(conn))
        return ids[0]

    async def call():
        raise RuntimeError("TP said no")

    with pytest.raises(RuntimeError, match="TP said no") as info:
        await recorded_write(
            factory, table="plan_changes", insert_pending=insert, call=call, mark_applied=_mark
        )
    assert any("left pending" in n for n in info.value.__notes__)
    assert _row(db, ids[0])["status"] == "pending"


def test_pending_rows_skips_young_and_settled_rows(db):
    old = _insert(db)
    young = _insert(db)
    done = _insert(db)
    db.execute(
        "update plan_changes set applied_at = now() - interval '5 minutes' where id in (%s, %s)",
        (old, done),
    )
    mark_failed(db, "plan_changes", done, "x")
    assert [r["id"] for r in pending_rows(db, "plan_changes")] == [old]
    assert young not in [r["id"] for r in pending_rows(db, "plan_changes")]


def test_mark_failed_never_overwrites_an_applied_row(db):
    rid = _insert(db)
    _mark(db, rid, {"workout_id": 9})
    mark_failed(db, "plan_changes", rid, "late failure")
    row = _row(db, rid)
    assert row["status"] == "applied" and row["error"] is None
