"""Schema migrations: `migrations/*.sql` applied in version order and recorded in
`schema_migrations`. `tri migrate` is the only caller outside tests.

A database migrated by hand before this existed has no record; the first run detects each
hand-applied file by a probe (a table or column it creates) and records it without running it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import tuple_row

# packages/tri-core/src/tri_core/db/migrate.py -> the repository root
MIGRATIONS_DIR = Path(__file__).resolve().parents[5] / "migrations"

TRACKING_DDL = """\
create table if not exists schema_migrations (
  version     int primary key,
  name        text not null,
  sha256      text not null,
  applied_at  timestamptz not null default now()
);"""


def _table(name: str) -> str:
    return f"select to_regclass('{name}') is not null"


def _column(table: str, column: str) -> str:
    return (
        "select exists (select 1 from information_schema.columns where table_schema = "
        f"current_schema() and table_name = '{table}' and column_name = '{column}')"
    )


# What each hand-applied migration creates; present means applied. Consulted only when nothing
# is recorded yet; files after 008 have no probe and always run.
PROBES: dict[int, str] = {
    1: _table("workouts"),
    2: _table("training_goals"),
    3: _column("training_plans", "targets"),
    4: _table("nutrition_targets"),
    5: _table("lab_panels"),
    6: _column("lab_results", "bound"),
    7: _table("garmin_activities"),
    8: _column("plan_weeks", "violations"),
}

_NAME = re.compile(r"^(\d+)_\w+\.sql$")

Log = Callable[[str], None]


@dataclass(frozen=True)
class Migration:
    version: int  # leading integer of the filename
    name: str  # filename without extension
    path: Path
    sha256: str  # of the file's bytes

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


class MigrationError(RuntimeError):
    """A migration set that cannot be applied as it stands; the message names the file."""


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every `<number>_<words>.sql` in `directory`, sorted by number."""
    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        m = _NAME.match(path.name)
        if not m:
            raise MigrationError(f"{path.name}: name must be <number>_<words>.sql")
        version = int(m.group(1))
        if version in found:
            raise MigrationError(
                f"{found[version].path.name} and {path.name} share version {version}"
            )
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        found[version] = Migration(version, path.stem, path, sha)
    return [found[v] for v in sorted(found)]


def applied(conn: psycopg.Connection[Any]) -> dict[int, str]:
    """version -> sha256 of every recorded migration; {} when the table is missing."""
    cur = conn.cursor(row_factory=tuple_row)
    row = cur.execute("select to_regclass('schema_migrations')").fetchone()
    if row is None or row[0] is None:
        return {}
    rows = cur.execute("select version, sha256 from schema_migrations").fetchall()
    return {int(v): str(s) for v, s in rows}


def _probe(conn: psycopg.Connection[Any], sql: str) -> bool:
    row = conn.cursor(row_factory=tuple_row).execute(sql).fetchone()
    return bool(row and row[0])


def plan(
    conn: psycopg.Connection[Any],
    migrations: list[Migration],
    probes: Mapping[int, str] = PROBES,
) -> tuple[list[Migration], list[Migration]]:
    """(record, run): files to record as applied by hand without running them, and files to run,
    each in version order. Raises MigrationError when an applied file was edited."""
    recorded = applied(conn)
    for m in migrations:
        if m.version in recorded and recorded[m.version] != m.sha256:
            raise MigrationError(
                f"migrations/{m.path.name} was edited after it was applied "
                f"(recorded {recorded[m.version][:8]}, file {m.sha256[:8]})"
            )
    todo = [m for m in migrations if m.version not in recorded]
    if recorded:
        return [], todo
    record = [m for m in todo if m.version in probes and _probe(conn, probes[m.version])]
    return record, [m for m in todo if m not in record]


def _insert(conn: psycopg.Connection[Any], m: Migration) -> None:
    conn.execute(
        "insert into schema_migrations (version, name, sha256) values (%s, %s, %s)",
        (m.version, m.name, m.sha256),
    )


def apply_migrations(
    conn: psycopg.Connection[Any],
    migrations: list[Migration],
    *,
    probes: Mapping[int, str] = PROBES,
    dry_run: bool = False,
    log: Log = print,
) -> list[Migration]:
    """Record the hand-applied files, then run each pending file and insert its row in one
    transaction. Pass an autocommit connection: each `conn.transaction()` is then a real
    transaction, so a failing file rolls back alone and earlier ones stay recorded. (On a
    connection already inside a transaction they are savepoints; the tests rely on that.)
    Returns the files run, or on a dry run the files that would run."""
    record, run = plan(conn, migrations, probes)
    if dry_run:
        for m in record:
            log(f"would record {m.name} (already applied by hand)")
        for m in run:
            log(f"would apply {m.name}")
    else:
        with conn.transaction():
            conn.execute(TRACKING_DDL)
            for m in record:
                _insert(conn, m)
        for m in record:
            log(f"recorded {m.name} (already applied by hand)")
        for m in run:
            try:
                with conn.transaction():
                    conn.execute(m.sql)
                    _insert(conn, m)
            except psycopg.Error as exc:
                raise MigrationError(
                    f"migrations/{m.path.name} failed and was rolled back: {exc}"
                ) from exc
            log(f"applied {m.name}")
    if not record and not run:
        log("up to date")
    return run


async def _langgraph_setup(url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
    async with AsyncPostgresStore.from_conn_string(url) as store:
        await store.setup()


def ensure_langgraph_tables(url: str) -> None:
    """LangGraph's checkpoint and Store tables; both setups are idempotent."""
    asyncio.run(_langgraph_setup(url))
