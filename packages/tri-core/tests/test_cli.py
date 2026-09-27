from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from tri_core import cli
from tri_core.config import Settings
from tri_core.db.migrate import MigrationError

MAIN = "postgresql://o:p@h:1/main"
TEST = "postgresql://o:p@h:1/test"
UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/nope"


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """CliRunner invokes `main`'s `load_dotenv()` for real; stub it so a developer's .env
    never leaks into os.environ during these tests."""
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def calls(monkeypatch):
    seen: dict[str, object] = {"connect": [], "apply": [], "langgraph": []}

    @contextmanager
    def fake_connect(url, **kw):
        seen["connect"].append((url, kw))
        yield "conn"

    def fake_apply(conn, migrations, *, dry_run=False, log=print):
        seen["apply"].append((conn, dry_run))
        log("applied 009_schema_migrations")
        return []

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(_env_file=None, database_url=MAIN, test_database_url=TEST),
    )
    monkeypatch.setattr(cli.psycopg, "connect", fake_connect)
    monkeypatch.setattr(cli, "apply_migrations", fake_apply)
    monkeypatch.setattr(cli, "ensure_langgraph_tables", lambda url: seen["langgraph"].append(url))
    return seen


def test_migrate_targets_the_main_database_then_langgraph(calls):
    result = CliRunner().invoke(cli.app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert calls["connect"] == [(MAIN, {"autocommit": True})]
    assert calls["apply"] == [("conn", False)]
    assert calls["langgraph"] == [MAIN]
    assert "applied 009_schema_migrations" in result.output
    assert "checkpoint and store tables ready" in result.output


def test_migrate_test_targets_the_test_database(calls):
    result = CliRunner().invoke(cli.app, ["migrate", "--test"])
    assert result.exit_code == 0, result.output
    assert calls["connect"][0][0] == TEST and calls["langgraph"] == [TEST]


def test_migrate_dry_run_skips_langgraph(calls):
    result = CliRunner().invoke(cli.app, ["migrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls["apply"] == [("conn", True)] and calls["langgraph"] == []


def test_migrate_exits_1_on_a_migration_error(calls, monkeypatch):
    def refuse(conn, migrations, *, dry_run=False, log=print):
        raise MigrationError("migrations/003_x.sql was edited after it was applied")

    monkeypatch.setattr(cli, "apply_migrations", refuse)
    result = CliRunner().invoke(cli.app, ["migrate"])
    assert result.exit_code == 1
    assert "003_x.sql was edited" in result.output and calls["langgraph"] == []


def test_migrate_exits_1_when_discover_cannot_read_the_migrations(calls, monkeypatch):
    def boom() -> list[object]:
        raise OSError("permission denied")

    monkeypatch.setattr(cli, "discover", boom)
    result = CliRunner().invoke(cli.app, ["migrate"])
    assert result.exit_code == 1
    assert "permission denied" in result.output
    assert calls["langgraph"] == []


def test_migrate_exits_1_when_the_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, database_url=UNREACHABLE)
    )
    ran: list[str] = []
    monkeypatch.setattr(cli, "ensure_langgraph_tables", ran.append)
    result = CliRunner().invoke(cli.app, ["migrate"])
    assert result.exit_code == 1 and ran == []
    assert "127.0.0.1" in result.output or "connection" in result.output.lower()
