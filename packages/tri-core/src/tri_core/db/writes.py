"""Record-before-write for every TrainingPeaks and Garmin write. The change row is inserted as
`pending` and committed before the call, then set to `applied` or `failed`. A database failure
after a successful call therefore leaves a `pending` row the next apply reconciles, instead of
a write nobody recorded."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import sql

from tri_core.db.repo import Conn

ChangeTable = Literal["plan_changes", "nutrition_changes"]
ConnectFactory = Callable[[], AbstractContextManager[Conn]]
PENDING_GRACE_SEC = 60  # a younger pending row may belong to a write still in flight


@dataclass(frozen=True)
class Recorded:
    row_id: int
    result: Any


class SentUnrecorded(Exception):
    """The call went through but its row could not be marked applied: the row stays `pending`
    for the next apply to reconcile, and the change must not be sent again."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(
            f"sent, but its record failed ({type(cause).__name__}: {cause}); "
            "it will be reconciled on the next apply"
        )


def mark_failed(conn: Conn, table: ChangeTable, row_id: int, error: str) -> None:
    conn.execute(
        sql.SQL(
            "update {} set status = 'failed', error = %s where id = %s and status = 'pending'"
        ).format(sql.Identifier(table)),
        (error[:2000], row_id),
    )


def pending_rows(
    conn: Conn, table: ChangeTable, *, older_than_sec: int = PENDING_GRACE_SEC
) -> list[dict[str, Any]]:
    return conn.execute(
        sql.SQL(
            "select * from {} where status = 'pending' "
            "and applied_at < now() - make_interval(secs => %s) order by id"
        ).format(sql.Identifier(table)),
        (older_than_sec,),
    ).fetchall()


async def recorded_write(
    conn_factory: ConnectFactory,
    *,
    table: ChangeTable,
    insert_pending: Callable[[Conn], int],
    call: Callable[[], Awaitable[Any]],
    mark_applied: Callable[[Conn, int, Any], None],
) -> Recorded:
    """Insert the pending row and commit; make the call; mark the row applied (or failed, and
    re-raise). If `mark_applied` raises, the row stays pending and the exception propagates."""
    with conn_factory() as conn:
        row_id = insert_pending(conn)
        conn.commit()
    try:
        result = await call()
    except Exception as exc:
        try:
            with conn_factory() as conn:
                mark_failed(conn, table, row_id, f"{type(exc).__name__}: {exc}")
                conn.commit()
        except Exception as db_exc:  # the server's error is the one the caller must see
            exc.add_note(f"{table} row {row_id} left pending: {type(db_exc).__name__}: {db_exc}")
        raise
    with conn_factory() as conn:
        mark_applied(conn, row_id, result)
        conn.commit()
    return Recorded(row_id=row_id, result=result)
