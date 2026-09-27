import re
from pathlib import Path

import pytest

from tri_core.db.migrate import (
    MIGRATIONS_DIR,
    PROBES,
    TRACKING_DDL,
    MigrationError,
    applied,
    apply_migrations,
    discover,
)

TOY_PROBES = {
    1: "select to_regclass('a') is not null",
    2: "select to_regclass('b') is not null",
}


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def toy(directory: Path):
    write(directory, "001_a.sql", "create table a (id int);")
    write(directory, "002_b.sql", "create table b (id int);\ninsert into b values (1);")
    write(directory, "009_c.sql", "create table c (id int);")
    return discover(directory)


def regclass(conn, name: str):
    return conn.execute(f"select to_regclass('{name}') as t").fetchone()["t"]


@pytest.fixture
def scratch(db):
    """A schema of its own on the rolled-back test connection. The first execute opens the
    transaction, so every conn.transaction() inside apply_migrations is a savepoint and the
    fixture's rollback removes everything, schema included."""
    db.execute("create schema mig_scratch")
    db.execute("set local search_path to mig_scratch")
    return db


def test_discover_orders_by_version(tmp_path):
    write(tmp_path, "010_c.sql", "select 1;")
    write(tmp_path, "002_b.sql", "select 1;")
    write(tmp_path, "001_a.sql", "select 1;")
    ms = discover(tmp_path)
    assert [(m.version, m.name) for m in ms] == [(1, "001_a"), (2, "002_b"), (10, "010_c")]
    assert all(re.fullmatch(r"[0-9a-f]{64}", m.sha256) for m in ms)
    assert ms[0].sql == "select 1;"


def test_discover_rejects_a_duplicate_version(tmp_path):
    write(tmp_path, "001_a.sql", "select 1;")
    write(tmp_path, "001_b.sql", "select 1;")
    with pytest.raises(MigrationError, match="001_a.sql and 001_b.sql share version 1"):
        discover(tmp_path)


def test_discover_rejects_a_name_without_a_version(tmp_path):
    write(tmp_path, "initial.sql", "select 1;")
    with pytest.raises(MigrationError, match="initial.sql: name must be"):
        discover(tmp_path)


def test_the_real_migrations_have_distinct_versions_and_probes_for_the_hand_applied_set():
    ms = discover()
    versions = [m.version for m in ms]
    assert versions == sorted(set(versions))
    assert {1, 2, 3, 4, 5, 6, 7, 9} <= set(versions)
    assert all(m.version in PROBES for m in ms if m.version <= 8)
    assert max(PROBES) == 8


def test_migration_009_is_the_tracking_table():
    assert TRACKING_DDL in (MIGRATIONS_DIR / "009_schema_migrations.sql").read_text()


@pytest.mark.db
def test_first_run_on_an_empty_schema_runs_every_file_and_records_it(scratch, tmp_path):
    ms = toy(tmp_path)
    lines: list[str] = []
    ran = apply_migrations(scratch, ms, probes=TOY_PROBES, log=lines.append)
    assert [m.name for m in ran] == ["001_a", "002_b", "009_c"]
    assert lines == ["applied 001_a", "applied 002_b", "applied 009_c"]
    assert applied(scratch) == {m.version: m.sha256 for m in ms}
    assert scratch.execute("select count(*) as n from b").fetchone()["n"] == 1


@pytest.mark.db
def test_a_hand_migrated_schema_is_recorded_without_rerunning(scratch, tmp_path):
    ms = toy(tmp_path)
    scratch.execute("create table a (id int)")
    scratch.execute("create table b (id int)")
    lines: list[str] = []
    ran = apply_migrations(scratch, ms, probes=TOY_PROBES, log=lines.append)
    assert [m.name for m in ran] == ["009_c"]
    assert lines == [
        "recorded 001_a (already applied by hand)",
        "recorded 002_b (already applied by hand)",
        "applied 009_c",
    ]
    assert scratch.execute("select count(*) as n from b").fetchone()["n"] == 0  # 002 not re-run
    assert set(applied(scratch)) == {1, 2, 9}


@pytest.mark.db
def test_a_lower_version_added_later_still_runs(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "create table a (id int);")
    write(tmp_path, "009_c.sql", "create table c (id int);")
    apply_migrations(scratch, discover(tmp_path), probes=TOY_PROBES, log=lambda _: None)
    write(tmp_path, "002_b.sql", "create table b (id int);")
    lines: list[str] = []
    ran = apply_migrations(scratch, discover(tmp_path), probes=TOY_PROBES, log=lines.append)
    assert [m.name for m in ran] == ["002_b"] and lines == ["applied 002_b"]
    assert set(applied(scratch)) == {1, 2, 9}


@pytest.mark.db
def test_a_second_run_is_a_no_op(scratch, tmp_path):
    ms = toy(tmp_path)
    apply_migrations(scratch, ms, probes=TOY_PROBES, log=lambda _: None)
    lines: list[str] = []
    assert apply_migrations(scratch, ms, probes=TOY_PROBES, log=lines.append) == []
    assert lines == ["up to date"]
    assert apply_migrations(scratch, ms, probes=TOY_PROBES, dry_run=True, log=lines.append) == []
    assert lines == ["up to date", "up to date"]


@pytest.mark.db
def test_an_edited_applied_file_is_refused(scratch, tmp_path):
    apply_migrations(scratch, toy(tmp_path), probes=TOY_PROBES, log=lambda _: None)
    write(tmp_path, "001_a.sql", "create table a (id bigint);")
    with pytest.raises(
        MigrationError,
        match=r"^migrations/001_a\.sql was edited after it was applied "
        r"\(recorded [0-9a-f]{8}, file [0-9a-f]{8}\)$",
    ):
        apply_migrations(scratch, discover(tmp_path), probes=TOY_PROBES, log=lambda _: None)


@pytest.mark.db
def test_a_failing_file_is_rolled_back_and_earlier_ones_stay_recorded(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "create table a (id int);")
    write(tmp_path, "002_bad.sql", "create table z (id int);\nselect no_such_column from a;")
    write(tmp_path, "003_c.sql", "create table c (id int);")
    lines: list[str] = []
    with pytest.raises(
        MigrationError, match=r"^migrations/002_bad\.sql failed and was rolled back"
    ):
        apply_migrations(scratch, discover(tmp_path), probes={}, log=lines.append)
    assert lines == ["applied 001_a"]
    assert set(applied(scratch)) == {1}
    assert regclass(scratch, "z") is None and regclass(scratch, "c") is None


@pytest.mark.db
def test_dry_run_changes_nothing(scratch, tmp_path):
    ms = toy(tmp_path)
    scratch.execute("create table a (id int)")
    scratch.execute("create table b (id int)")
    lines: list[str] = []
    would = apply_migrations(scratch, ms, probes=TOY_PROBES, dry_run=True, log=lines.append)
    assert [m.name for m in would] == ["009_c"]
    assert lines == [
        "would record 001_a (already applied by hand)",
        "would record 002_b (already applied by hand)",
        "would apply 009_c",
    ]
    assert applied(scratch) == {}
    assert regclass(scratch, "schema_migrations") is None and regclass(scratch, "c") is None


@pytest.mark.db
def test_the_real_migrations_run_in_order_on_an_empty_schema(scratch):
    ms = discover()
    ran = apply_migrations(scratch, ms, log=lambda _: None)
    assert [m.version for m in ran] == [m.version for m in ms]
    assert set(applied(scratch)) == {m.version for m in ms}
    assert regclass(scratch, "garmin_activities") is not None
