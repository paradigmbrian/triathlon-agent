"""Record-before-write for every TrainingPeaks and Garmin write. The change row is inserted as
`pending` and committed before the call, then set to `applied`, or `failed` when the server
definitively rejected it. A timeout, a server error or a database failure after a successful
call leaves a `pending` row the next apply reconciles, instead of a write nobody recorded or a
change sent twice."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import sql

from tri_core.db.repo import Conn
from tri_core.mcp.client import McpToolError

ChangeTable = Literal["plan_changes", "nutrition_changes"]
ConnectFactory = Callable[[], AbstractContextManager[Conn]]
PENDING_GRACE_SEC = 60  # a younger pending row may belong to a write still in flight
# tp-mcp error codes (client/http.py ErrorCode and server.py dispatch at TP_MCP_REF) that mean
# the write was refused before TrainingPeaks acted on it: input rejected by the tool or the
# dispatcher, a blocked endpoint, 401/403, 404. API_ERROR (any other status, 5xx included),
# NETWORK_ERROR (timeouts) and RATE_LIMITED are not listed: those stay pending.
DEFINITIVE_TP_CODES = (
    "VALIDATION_ERROR",
    "INVALID_ARGS",
    "UNKNOWN_TOOL",
    "FORBIDDEN_ENDPOINT",
    "AUTH_EXPIRED",
    "AUTH_INVALID",
    "NOT_FOUND",
)


@dataclass(frozen=True)
class Recorded:
    row_id: int
    result: Any


class OutcomeUnknown(Exception):
    """The call may have gone through and its row is still `pending`: the next apply settles
    it, and the change must not be sent again before then."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(self.describe(cause))

    @staticmethod
    def describe(cause: Exception) -> str:
        return (
            f"{type(cause).__name__}: {cause}; outcome unknown, it will be checked on the next "
            "apply"
        )


class SentUnrecorded(OutcomeUnknown):
    """The call went through but its row could not be marked applied."""

    @staticmethod
    def describe(cause: Exception) -> str:
        return (
            f"sent, but its record failed ({type(cause).__name__}: {cause}); "
            "it will be reconciled on the next apply"
        )


def is_definitive_rejection(exc: BaseException) -> bool:
    """A TrainingPeaks tool error whose code says the write did not happen. Every Garmin error
    and every other exception is ambiguous: the server may have acted before it failed."""
    if not isinstance(exc, McpToolError) or not exc.tool.startswith("tp_"):
        return False
    code = exc.message.split(":", 1)[0].strip()
    return code in DEFINITIVE_TP_CODES


def mark_failed(conn: Conn, table: ChangeTable, row_id: int, error: str) -> None:
    conn.execute(
        sql.SQL(
            "update {} set status = 'failed', error = %s where id = %s and status = 'pending'"
        ).format(sql.Identifier(table)),
        (error[:2000], row_id),
    )


def note_pending_error(conn: Conn, table: ChangeTable, row_id: int, error: str) -> None:
    conn.execute(
        sql.SQL("update {} set error = %s where id = %s and status = 'pending'").format(
            sql.Identifier(table)
        ),
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
    """Insert the pending row and commit; make the call; mark the row applied. A definitive
    rejection marks the row failed and re-raises; any other call failure keeps the row pending
    with its error text and raises `OutcomeUnknown` from it. If `mark_applied` raises, the row
    stays pending and the exception propagates."""
    with conn_factory() as conn:
        row_id = insert_pending(conn)
        conn.commit()
    try:
        result = await call()
    except Exception as exc:
        definitive = is_definitive_rejection(exc)
        raised = exc if definitive else OutcomeUnknown(exc)
        error = f"{type(exc).__name__}: {exc}"
        try:
            with conn_factory() as conn:
                if definitive:
                    mark_failed(conn, table, row_id, error)
                else:
                    note_pending_error(conn, table, row_id, error)
                conn.commit()
        except Exception as db_exc:  # the server's error is the one the caller must see
            raised.add_note(f"{table} row {row_id} left pending: {type(db_exc).__name__}: {db_exc}")
        if definitive:
            raise
        raise raised from exc
    with conn_factory() as conn:
        mark_applied(conn, row_id, result)
        conn.commit()
    return Recorded(row_id=row_id, result=result)
