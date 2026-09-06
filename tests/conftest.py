from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from tri_analyze.config import Settings
from tri_analyze.db.connection import connect


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live", action="store_true", default=False, help="run tests that hit real MCP servers"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def db() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Connection to the test database; every test runs in a rolled-back transaction."""
    url = Settings().test_database_url
    try:
        conn = connect(url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable at {url}: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
